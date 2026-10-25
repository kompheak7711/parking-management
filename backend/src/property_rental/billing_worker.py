"""Bounded Property-local catch-up worker for scheduled billing runs.

Since V1-056 slice 11g-1 (DL-076) each pass also runs the automatic late-payment charge pass
(`property_rental.late_payment_job`) after the billing runs, while it holds the same lock."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from property_rental.billing_run import (
    BillingRunCommand,
    BillingRunDetail,
    PostgresBillingRunService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment_job import (
    AutomaticLatePaymentChargeJob,
    LateChargePass,
    LateChargePassError,
    LateChargePassResult,
)


@dataclass(frozen=True, slots=True)
class BillingWorkerResult:
    current_business_date: date
    runs: tuple[BillingRunDetail, ...]
    late_charges: LateChargePassResult | None = None
    # The charge pass failed as a whole; the billing runs above are still reported.
    late_charges_error: str | None = None


class BillingWorker(Protocol):
    def run_once(self, *, as_of: datetime | None = None) -> BillingWorkerResult: ...


def property_local_date(instant: datetime, timezone_name: str) -> date:
    """Convert an aware instant without consulting the host timezone."""
    if instant.utcoffset() is None:
        raise ValueError("instant must be timezone-aware")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone_name must identify an installed IANA timezone") from exc
    return instant.astimezone(timezone).date()


def _worker_id(property_id: UUID, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"property-rental/billing-worker/{property_id}/{value}")


class ScheduledBillingWorker:
    """Discover missed work oldest-first and invoke the shared command service."""

    def __init__(
        self,
        financial_database_url: str,
        *,
        property_id: UUID,
        actor_id: UUID,
        max_catchup_runs: int = 12,
        service: PostgresBillingRunService | None = None,
        late_charges: LateChargePass | None = None,
    ) -> None:
        if not 1 <= max_catchup_runs <= 100:
            raise ValueError("max_catchup_runs must be between 1 and 100")
        self._financial_database_url = financial_database_url
        self._property_id = property_id
        self._actor_id = actor_id
        self._max_catchup_runs = max_catchup_runs
        self._service = service or PostgresBillingRunService(financial_database_url)
        self._late_charges = late_charges or AutomaticLatePaymentChargeJob(
            financial_database_url, property_id=property_id, actor_id=actor_id
        )

    def run_once(self, *, as_of: datetime | None = None) -> BillingWorkerResult:
        instant = as_of or datetime.now(UTC)
        if instant.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        scope = frozenset({str(self._property_id)})
        actor = AuthenticatedActor(
            actor_id=str(self._actor_id),
            capability_grants=frozenset(
                {CapabilityGrant(capability="billing.generate", property_ids=scope)}
            ),
        )
        results: list[BillingRunDetail] = []
        with psycopg.connect(self._financial_database_url) as connection:
            current_date_row = connection.execute(
                "SELECT app.billing_worker_property_date(%s,%s,%s)",
                (self._property_id, self._actor_id, instant),
            ).fetchone()
            if current_date_row is None or not isinstance(current_date_row[0], date):
                raise RuntimeError("Property-local worker date is unavailable")
            current_business_date = current_date_row[0]
            lock_row = connection.execute(
                "SELECT app.try_scheduled_billing_worker_lock(%s,%s)",
                (self._property_id, self._actor_id),
            ).fetchone()
            if lock_row != (True,):
                return BillingWorkerResult(current_business_date, ())
            candidates = connection.execute(
                "SELECT * FROM app.scheduled_billing_worker_candidates(%s,%s,%s,%s)",
                (
                    self._property_id,
                    self._actor_id,
                    instant,
                    self._max_catchup_runs,
                ),
            ).fetchall()
            for (
                business_date_value,
                period_start_value,
                period_end_value,
                run_kind_value,
            ) in candidates:
                business_date = business_date_value
                period_start = period_start_value
                period_end = period_end_value
                run_kind = str(run_kind_value)
                logical_run_key = (
                    f"rent/{period_start:%Y-%m}"
                    if run_kind == "RENT"
                    else f"utilities/{period_start:%Y-%m-%d}/{period_end:%Y-%m-%d}"
                )
                results.append(
                    self._service.execute(
                        BillingRunCommand(
                            property_id=self._property_id,
                            run_kind=run_kind,
                            logical_run_key=logical_run_key,
                            business_date=business_date,
                            period_start=period_start,
                            period_end=period_end,
                            idempotency_key=_worker_id(
                                self._property_id,
                                f"{run_kind}/{business_date}/{period_start}/{period_end}",
                            ),
                        ),
                        actor=actor,
                        invocation_source="SCHEDULED",
                    )
                )
            # DL-076: after the day's Invoices exist, still under the worker lock. The charge
            # pass always runs at the real time: the database refuses an instant older than an
            # hour, so a billing catch-up instant is not used for it.
            try:
                late_charges = self._late_charges.run(as_of=datetime.now(UTC))
            except (psycopg.Error, LateChargePassError) as exc:
                code = getattr(exc, "sqlstate", None) or type(exc).__name__
                return BillingWorkerResult(current_business_date, tuple(results), None, code)
        return BillingWorkerResult(current_business_date, tuple(results), late_charges)


def run_bounded_loop(
    worker: BillingWorker,
    *,
    max_iterations: int,
    poll_interval_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Run a finite loop with bounded exponential failure backoff."""
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    if poll_interval_seconds < 1:
        raise ValueError("poll_interval_seconds must be positive")
    consecutive_failures = 0
    all_succeeded = True
    for iteration in range(max_iterations):
        try:
            result = worker.run_once()
        except Exception as exc:
            all_succeeded = False
            consecutive_failures = min(consecutive_failures + 1, 6)
            print(f"failed:{type(exc).__name__}", file=sys.stderr, flush=True)
            if iteration + 1 < max_iterations:
                sleep(min(poll_interval_seconds, 2**consecutive_failures))
            continue
        consecutive_failures = 0
        print(f"succeeded:{len(result.runs)}", flush=True)
        if result.late_charges_error is not None:
            all_succeeded = False
            print(f"late_charges:error:{result.late_charges_error}", file=sys.stderr, flush=True)
        if result.late_charges is not None:
            late = result.late_charges
            print(
                f"late_charges:charged={late.charged},no_amount={late.no_amount},"
                f"skipped={late.skipped},failed={late.failed},done={late.done}",
                flush=True,
            )
            # An Invoice the pass could not record is tried again; the pass still reports it.
            if late.failed:
                all_succeeded = False
        if iteration + 1 < max_iterations:
            sleep(poll_interval_seconds)
    return all_succeeded


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded scheduled billing catch-up")
    parser.add_argument("--property-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True, type=UUID)
    parser.add_argument("--max-catchup-runs", type=int, default=12)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--max-iterations", type=int)
    parser.add_argument("--poll-interval-seconds", type=int, default=300)
    args = parser.parse_args()
    financial_url = os.environ.get("APP_FINANCIAL_DATABASE_URL")
    if not financial_url:
        parser.error("APP_FINANCIAL_DATABASE_URL is required")
    worker = ScheduledBillingWorker(
        financial_url,
        property_id=args.property_id,
        actor_id=args.actor_id,
        max_catchup_runs=args.max_catchup_runs,
    )
    try:
        succeeded = run_bounded_loop(
            worker,
            max_iterations=1 if args.once else args.max_iterations,
            poll_interval_seconds=args.poll_interval_seconds,
        )
    except (ValueError, KeyboardInterrupt) as exc:
        if isinstance(exc, ValueError):
            parser.error(str(exc))
        return 130
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
