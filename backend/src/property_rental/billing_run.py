"""Idempotent scheduled billing command and immutable run-detail boundary."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg import IsolationLevel

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

BILLING_GENERATE_CAPABILITY: Final = "billing.generate"
BILLING_RUN_CONNECT_TIMEOUT_SECONDS: Final = 3
BILLING_RUN_LOCK_TIMEOUT_MS: Final = 5_000
BILLING_RUN_QUERY_TIMEOUT_MS: Final = 30_000
LOGICAL_RUN_KEY_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
NIL_UUID: Final = UUID(int=0)


class BillingRunNotFound(LookupError):
    pass


class BillingRunConflict(RuntimeError):
    pass


class BillingRunInvalid(ValueError):
    pass


class BillingRunAuthorizationError(PermissionError):
    pass


class BillingRunUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BillingRunCommand:
    property_id: UUID
    run_kind: str
    logical_run_key: str
    business_date: date
    period_start: date
    period_end: date
    idempotency_key: UUID

    def __post_init__(self) -> None:
        if self.property_id == NIL_UUID or self.idempotency_key == NIL_UUID:
            raise ValueError("billing run identifiers must not be nil")
        if self.run_kind not in {"RENT", "UTILITIES"}:
            raise ValueError("run_kind is not supported")
        if not LOGICAL_RUN_KEY_PATTERN.fullmatch(self.logical_run_key):
            raise ValueError("logical_run_key is not canonical")
        if self.period_end < self.period_start:
            raise ValueError("period_end must not precede period_start")
        if (self.period_end - self.period_start).days > 62:
            raise ValueError("billing period exceeds the bounded window")
        if self.run_kind == "RENT":
            expected_start = _next_month(self.business_date.replace(day=1))
            if (
                self.business_date.day != 25
                or self.period_start != expected_start
                or self.period_end != _month_end(expected_start)
            ):
                raise ValueError("Rent run must bill next month from Property-local day 25")
        elif self.period_end > self.business_date:
            raise ValueError("Utility run cannot bill a future period")


@dataclass(frozen=True, slots=True)
class BillingRunItem:
    id: UUID
    attempt_id: UUID
    attempt_number: int
    source_kind: str
    source_id: UUID
    period_start: date
    period_end: date
    outcome: str
    invoice_id: UUID | None
    diagnostic_code: str | None
    recorded_at: datetime
    source_evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class BillingRunAttempt:
    id: UUID
    attempt_number: int
    started_at: datetime
    completed_at: datetime | None
    outcome: str
    diagnostic_code: str | None
    items: tuple[BillingRunItem, ...]


@dataclass(frozen=True, slots=True)
class BillingRunDetail:
    id: UUID
    property_id: UUID
    run_kind: str
    logical_run_key: str
    business_date: date
    period_start: date
    period_end: date
    idempotency_key: UUID
    request_digest: str
    correlation_id: UUID
    invocation_source: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    failure_code: str | None
    attempts: tuple[BillingRunAttempt, ...]


def _next_month(value: date) -> date:
    return (value.replace(day=28) + date.resolution * 4).replace(day=1)


def _month_end(value: date) -> date:
    return _next_month(value) - date.resolution


def billing_run_request_digest(command: BillingRunCommand, invocation_source: str) -> str:
    """Bind every canonical command input, including invocation provenance."""
    if invocation_source not in {"API", "SCHEDULED"}:
        raise ValueError("invocation_source is not supported")
    encoded = json.dumps(
        {
            "business_date": command.business_date.isoformat(),
            "idempotency_key": str(command.idempotency_key),
            "invocation_source": invocation_source,
            "logical_run_key": command.logical_run_key,
            "period_end": command.period_end.isoformat(),
            "period_start": command.period_start.isoformat(),
            "property_id": str(command.property_id),
            "run_kind": command.run_kind,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def stable_billing_id(run_id: UUID, value: str) -> UUID:
    """Return one restart-stable identity within a logical run."""
    return uuid5(NAMESPACE_URL, f"property-rental/billing-run/{run_id}/{value}")


class PostgresBillingRunService:
    """Execute a run through protected SQL wrappers around existing billing services."""

    def __init__(self, financial_database_url: str) -> None:
        self._financial_database_url = financial_database_url

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, *, hide: bool = False) -> UUID:
        try:
            actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            error = BillingRunNotFound if hide else BillingRunAuthorizationError
            raise error("Billing actor is invalid") from exc
        if not is_authorized(
            actor,
            AuthorizationRequirement(
                capability=BILLING_GENERATE_CAPABILITY,
                property_id=str(property_id),
            ),
        ):
            error = BillingRunNotFound if hide else BillingRunAuthorizationError
            raise error("Billing run is outside authorized Property scope")
        return actor_id

    @staticmethod
    def _map_error(exc: psycopg.Error) -> Exception:
        message = str(exc).lower()
        if exc.sqlstate == "P0002":
            return BillingRunNotFound("Billing run source was not found")
        if exc.sqlstate == "23505":
            return BillingRunConflict("Billing run idempotency input conflicted")
        if exc.sqlstate == "55000" and ("actor" in message or "principal" in message):
            return BillingRunAuthorizationError("Billing service principal is not active")
        if exc.sqlstate in {"22023", "23514", "55000"}:
            return BillingRunInvalid("Billing run command is invalid")
        if exc.sqlstate in {"23P01", "40001", "55P03"}:
            return BillingRunConflict("Billing run conflicted with concurrent state")
        return BillingRunUnavailable("Billing run persistence is unavailable")

    @staticmethod
    def _configure(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        connection.isolation_level = IsolationLevel.READ_COMMITTED
        connection.execute(
            "SELECT pg_catalog.set_config('lock_timeout',%s,false)",
            (str(BILLING_RUN_LOCK_TIMEOUT_MS),),
        )
        connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout',%s,false)",
            (str(BILLING_RUN_QUERY_TIMEOUT_MS),),
        )
        connection.commit()

    def execute(
        self,
        command: BillingRunCommand,
        *,
        actor: AuthenticatedActor,
        invocation_source: str,
    ) -> BillingRunDetail:
        actor_id = self._authorize(actor, command.property_id)
        digest = billing_run_request_digest(command, invocation_source)
        run_id = stable_billing_id(
            command.property_id,
            "/".join(
                (
                    command.run_kind,
                    command.logical_run_key,
                    command.period_start.isoformat(),
                    command.period_end.isoformat(),
                )
            ),
        )
        correlation_id = stable_billing_id(run_id, "correlation")
        try:
            with psycopg.connect(
                self._financial_database_url,
                connect_timeout=BILLING_RUN_CONNECT_TIMEOUT_SECONDS,
            ) as connection:
                self._configure(connection)
                started = connection.execute(
                    "SELECT * FROM app.start_scheduled_billing_run("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        run_id,
                        command.property_id,
                        command.run_kind,
                        command.logical_run_key,
                        command.business_date,
                        command.period_start,
                        command.period_end,
                        command.idempotency_key,
                        digest,
                        actor_id,
                        correlation_id,
                        invocation_source,
                    ),
                ).fetchone()
                if started is None:
                    raise BillingRunUnavailable("Billing run did not start")
                persisted_run_id, attempt_id, should_execute = cast(
                    tuple[UUID, UUID, bool], started
                )
                connection.commit()
                if not should_execute:
                    return self._get_on_connection(connection, persisted_run_id)
                generation_row = connection.execute(
                    "SELECT app.billing_run_generation_at(%s)", (persisted_run_id,)
                ).fetchone()
                if generation_row is None or not isinstance(generation_row[0], datetime):
                    raise BillingRunUnavailable("Billing generation evidence is unavailable")
                generation_at = generation_row[0]
                eligible = connection.execute(
                    "SELECT source_kind,source_id FROM app.billing_run_eligible_sources "
                    "WHERE billing_run_id=%s "
                    "ORDER BY source_period_start,source_period_end,source_kind,source_id",
                    (persisted_run_id,),
                ).fetchall()
                connection.commit()
                for source_kind_value, source_id_value in eligible:
                    source_kind = str(source_kind_value)
                    source_id = UUID(str(source_id_value))
                    invoice_id = stable_billing_id(persisted_run_id, f"invoice/{source_id}")
                    audit_id = stable_billing_id(
                        UUID(str(attempt_id)), f"audit/{source_kind}/{source_id}"
                    )
                    if command.run_kind == "RENT":
                        command_key = stable_billing_id(
                            UUID(str(attempt_id)), f"rent-command/{source_id}"
                        )
                        compact_source_id = str(source_id).replace("-", "")[:12]
                        invoice_number = f"RENT-{command.period_start:%Y%m}-{compact_source_id}"
                        item_digest = hashlib.sha256(
                            "/".join(
                                (
                                    digest,
                                    str(source_id),
                                    str(invoice_id),
                                    str(command_key),
                                    str(attempt_id),
                                    generation_at.isoformat(),
                                )
                            ).encode()
                        ).hexdigest()
                        connection.execute(
                            "SELECT app.record_scheduled_rent_item(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                persisted_run_id,
                                attempt_id,
                                source_id,
                                invoice_id,
                                invoice_number,
                                command_key,
                                item_digest,
                                audit_id,
                                generation_at,
                            ),
                        ).fetchone()
                    else:
                        compact_source_id = str(source_id).replace("-", "")[:12]
                        invoice_number = f"UTIL-{command.period_end:%Y%m%d}-{compact_source_id}"
                        connection.execute(
                            "SELECT app.record_scheduled_utility_item(%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                persisted_run_id,
                                attempt_id,
                                source_kind,
                                source_id,
                                invoice_id,
                                invoice_number,
                                audit_id,
                                generation_at,
                            ),
                        ).fetchone()
                    connection.commit()
                connection.execute(
                    "SELECT app.finish_scheduled_billing_attempt(%s,%s)",
                    (persisted_run_id, attempt_id),
                ).fetchone()
                connection.commit()
                return self._get_on_connection(connection, persisted_run_id)
        except (BillingRunNotFound, BillingRunInvalid, BillingRunUnavailable):
            raise
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc

    def get(self, run_id: UUID, *, actor: AuthenticatedActor) -> BillingRunDetail:
        if run_id == NIL_UUID:
            raise BillingRunNotFound("Billing run was not found")
        try:
            with psycopg.connect(
                self._financial_database_url,
                connect_timeout=BILLING_RUN_CONNECT_TIMEOUT_SECONDS,
            ) as connection:
                property_row = connection.execute(
                    "SELECT property_id FROM app.billing_runs WHERE id=%s", (run_id,)
                ).fetchone()
                if property_row is None:
                    raise BillingRunNotFound("Billing run was not found")
                self._authorize(actor, UUID(str(property_row[0])), hide=True)
                return self._get_on_connection(connection, run_id)
        except BillingRunNotFound:
            raise
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc

    @staticmethod
    def _get_on_connection(
        connection: psycopg.Connection[tuple[object, ...]], run_id: UUID
    ) -> BillingRunDetail:
        run = connection.execute(
            "SELECT id,property_id,run_kind,logical_run_key,business_date,period_start,"
            "period_end,idempotency_key,request_digest,correlation_id,invocation_source,"
            "status,started_at,completed_at,failure_code FROM app.billing_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        if run is None:
            raise BillingRunNotFound("Billing run was not found")
        attempt_rows = connection.execute(
            "SELECT id,attempt_number,started_at,completed_at,outcome,diagnostic_code "
            "FROM app.billing_run_attempts WHERE billing_run_id=%s ORDER BY attempt_number",
            (run_id,),
        ).fetchall()
        item_rows = connection.execute(
            "SELECT item.id,item.billing_run_attempt_id,attempt.attempt_number,item.source_kind,"
            "item.source_id,item.source_period_start,item.source_period_end,item.outcome,"
            "item.invoice_id,item.diagnostic_code,item.recorded_at,eligible.source_evidence "
            "FROM app.billing_run_items AS item "
            "JOIN app.billing_run_attempts AS attempt ON attempt.id=item.billing_run_attempt_id "
            "JOIN app.billing_run_eligible_sources AS eligible "
            "ON eligible.billing_run_id=item.billing_run_id "
            "AND eligible.source_kind=item.source_kind AND eligible.source_id=item.source_id "
            "AND eligible.source_period_start=item.source_period_start "
            "AND eligible.source_period_end=item.source_period_end "
            "WHERE item.billing_run_id=%s "
            "ORDER BY attempt.attempt_number,item.source_period_start,item.source_period_end,"
            "item.source_kind,item.source_id,item.id",
            (run_id,),
        ).fetchall()
        items_by_attempt: dict[UUID, list[BillingRunItem]] = {}
        for item in item_rows:
            attempt_key = UUID(str(item[1]))
            evidence = cast(dict[str, object], item[11])
            items_by_attempt.setdefault(attempt_key, []).append(
                BillingRunItem(
                    id=UUID(str(item[0])),
                    attempt_id=attempt_key,
                    attempt_number=int(str(item[2])),
                    source_kind=str(item[3]),
                    source_id=UUID(str(item[4])),
                    period_start=cast(date, item[5]),
                    period_end=cast(date, item[6]),
                    outcome=str(item[7]),
                    invoice_id=None if item[8] is None else UUID(str(item[8])),
                    diagnostic_code=None if item[9] is None else str(item[9]),
                    recorded_at=cast(datetime, item[10]),
                    source_evidence=evidence,
                )
            )
        attempts = tuple(
            BillingRunAttempt(
                id=UUID(str(attempt[0])),
                attempt_number=int(str(attempt[1])),
                started_at=cast(datetime, attempt[2]),
                completed_at=cast(datetime | None, attempt[3]),
                outcome=str(attempt[4]),
                diagnostic_code=None if attempt[5] is None else str(attempt[5]),
                items=tuple(items_by_attempt.get(UUID(str(attempt[0])), [])),
            )
            for attempt in attempt_rows
        )
        status = str(run[11])
        if status == "RUNNING" and attempts and attempts[-1].outcome == "FAILED":
            status = "RETRYABLE"
        return BillingRunDetail(
            id=UUID(str(run[0])),
            property_id=UUID(str(run[1])),
            run_kind=str(run[2]),
            logical_run_key=str(run[3]),
            business_date=cast(date, run[4]),
            period_start=cast(date, run[5]),
            period_end=cast(date, run[6]),
            idempotency_key=UUID(str(run[7])),
            request_digest=str(run[8]),
            correlation_id=UUID(str(run[9])),
            invocation_source=str(run[10]),
            status=status,
            started_at=cast(datetime, run[12]),
            completed_at=cast(datetime | None, run[13]),
            failure_code=None if run[14] is None else str(run[14]),
            attempts=attempts,
        )
