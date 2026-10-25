"""The automatic late-payment charge pass (V1-056 slice 11g-1; DL-076 answers 1 to 3).

The billing worker runs this pass while it holds its Property's worker lock. The database decides
everything (`app.automatic_late_payment_charge_window`, `_candidates` and `_record`): the day's
window, the Invoices to look at, and for each one the charge or the reason it gets none. This
module only pages through the candidates on one connection, records each Invoice in its own short
READ COMMITTED transaction (the closed Final Settlement guard needs it), and marks the day done
when every candidate was looked at with no failure; a failed Invoice is tried again on the next
pass, which then also covers the days since the last finished one.

Only outcome counts and SQLSTATE codes are written to the log: no amounts, no Customer data.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Protocol, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import IsolationLevel

CONNECT_TIMEOUT_SECONDS: Final = 5
# Each Invoice locks its own row and its Lease's Final Settlement row only.
TRANSACTION_OPTIONS: Final = "-c lock_timeout=3000 -c statement_timeout=5000"
PAGE_SIZE: Final = 200
CHARGED: Final = "CHARGED"
NO_AMOUNT: Final = "NO_AMOUNT"
# Another pass charged the Invoice first: nothing to count.
ALREADY_ASSESSED: Final = "ALREADY_ASSESSED"
# The reasons the rule gives no charge. Any other outcome is counted as a failure, so that an
# outcome added later never lets the day be marked done without a charge it should have had.
SKIPPED: Final = frozenset(
    {
        "NOT_YET_DUE",
        "NO_LEASE",
        "LEASE_NOT_SIGNED_OR_TERMINATED",
        "INITIAL_RENT",
        "NOT_ISSUED_OR_VOID",
        "NOT_IN_WINDOW",
        "ISSUED_AFTER_CHARGE_TIME",
        "FINAL_SETTLEMENT_CLOSED",
    }
)
# Refusals that every later Invoice would get too (lost connection, no privilege, no resources,
# a bad pass argument): they stop the pass at once instead of being counted one Invoice at a
# time. Other data errors (class 22) stay with their own Invoice.
WHOLE_PASS_SQLSTATE_CLASSES: Final = ("08", "42", "53")
WHOLE_PASS_SQLSTATES: Final = frozenset({"22023"})
# More days than this since the last finished pass are reported in the log.
CATCH_UP_WARNING_DAYS: Final = 3

WINDOW_KEYS: Final = frozenset({"business_date", "from_date", "ready", "done"})

Connection = psycopg.Connection[tuple[object, ...]]


class LateChargePassError(RuntimeError):
    """The database answered the pass in a shape it does not expect."""


@dataclass(frozen=True, slots=True)
class LateChargePassResult:
    business_date: date
    charged: int = 0
    no_amount: int = 0
    skipped: int = 0
    failed: int = 0
    done: bool = False


class LateChargePass(Protocol):
    def run(self, *, as_of: datetime) -> LateChargePassResult: ...


class AutomaticLatePaymentChargeJob:
    """One Property's automatic late-payment charge pass, as its billing service principal."""

    def __init__(
        self,
        financial_database_url: str,
        *,
        property_id: UUID,
        actor_id: UUID,
        page_size: int = PAGE_SIZE,
    ) -> None:
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        self._financial_database_url = financial_database_url
        self._property_id = property_id
        self._actor_id = actor_id
        self._page_size = page_size

    @contextmanager
    def _session(self) -> Iterator[Connection]:
        """One connection for the pass; each call below is its own transaction."""
        with psycopg.connect(
            self._financial_database_url,
            autocommit=True,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            options=TRANSACTION_OPTIONS,
        ) as connection:
            connection.isolation_level = IsolationLevel.READ_COMMITTED
            yield connection

    @staticmethod
    def _one(connection: Connection, sql: str, parameters: tuple[object, ...]) -> object:
        with connection.transaction():
            row = connection.execute(sql, parameters).fetchone()
        return None if row is None else row[0]

    def _window(self, connection: Connection, as_of: datetime) -> object:
        return self._one(
            connection,
            "SELECT app.automatic_late_payment_charge_window(%s,%s,%s)",
            (self._property_id, self._actor_id, as_of),
        )

    def _candidates(
        self, connection: Connection, as_of: datetime, after: UUID | None
    ) -> list[UUID]:
        with connection.transaction():
            rows = connection.execute(
                "SELECT invoice_id FROM app.automatic_late_payment_charge_candidates"
                "(%s,%s,%s,%s,%s)",
                (self._property_id, self._actor_id, as_of, after, self._page_size),
            ).fetchall()
        return [cast(UUID, row[0]) for row in rows]

    def _record(self, connection: Connection, invoice_id: UUID) -> str:
        outcome = self._one(
            connection,
            "SELECT app.record_automatic_late_payment_charge(%s,%s,%s,%s,%s,%s)",
            (self._property_id, self._actor_id, invoice_id, uuid4(), uuid4(), uuid4()),
        )
        if not isinstance(outcome, dict) or "outcome" not in outcome:
            raise LateChargePassError("The late-payment charge outcome is unavailable")
        return str(cast(dict[str, object], outcome)["outcome"])

    def _finish(
        self,
        connection: Connection,
        as_of: datetime,
        charged: int,
        no_amount: int,
        skipped: int,
    ) -> None:
        self._one(
            connection,
            "SELECT app.record_late_payment_charge_run(%s,%s,%s,%s,%s,%s)",
            (self._property_id, self._actor_id, as_of, charged, no_amount, skipped),
        )

    def run(self, *, as_of: datetime) -> LateChargePassResult:
        if as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        with self._session() as connection:
            return self._run(connection, as_of)

    def _run(self, connection: Connection, as_of: datetime) -> LateChargePassResult:
        window = self._window(connection, as_of)
        if not isinstance(window, dict) or not WINDOW_KEYS <= window.keys():
            raise LateChargePassError("The late-payment pass window is unavailable")
        try:
            business_date = date.fromisoformat(str(window["business_date"]))
            from_date = date.fromisoformat(str(window["from_date"]))
        except ValueError as exc:
            raise LateChargePassError("The late-payment pass window is unavailable") from exc
        if window["done"] is True or window["ready"] is not True:
            return LateChargePassResult(business_date, done=window["done"] is True)
        behind = (business_date - from_date).days
        if behind > CATCH_UP_WARNING_DAYS:
            print(f"late_charge_catch_up_days:{behind}", file=sys.stderr, flush=True)
        charged = no_amount = skipped = failed = 0
        after: UUID | None = None
        while True:
            page = self._candidates(connection, as_of, after)
            for invoice_id in page:
                try:
                    outcome = self._record(connection, invoice_id)
                except psycopg.Error as exc:
                    code = exc.sqlstate or "unknown"
                    if (
                        connection.closed
                        or connection.broken
                        or code.startswith(WHOLE_PASS_SQLSTATE_CLASSES)
                        or code in WHOLE_PASS_SQLSTATES
                    ):
                        # The connection is gone, or every later Invoice would be refused too.
                        raise
                    # A lock wait, a timeout or a check on this Invoice: tried again on the
                    # next pass; the day is not marked done.
                    failed += 1
                    print(f"late_charge_failed:{code}", file=sys.stderr, flush=True)
                    continue
                if outcome == CHARGED:
                    charged += 1
                elif outcome == NO_AMOUNT:
                    no_amount += 1
                elif outcome in SKIPPED:
                    skipped += 1
                elif outcome != ALREADY_ASSESSED:
                    failed += 1
                    print("late_charge_failed:unknown_outcome", file=sys.stderr, flush=True)
            if len(page) < self._page_size:
                break
            after = page[-1]
        if failed:
            return LateChargePassResult(business_date, charged, no_amount, skipped, failed)
        self._finish(connection, as_of, charged, no_amount, skipped)
        return LateChargePassResult(business_date, charged, no_amount, skipped, done=True)
