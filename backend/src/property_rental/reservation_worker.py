"""Singleton-safe and retry-safe automatic Reservation expiration runner."""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.reservation import (
    PostgresReservationService,
    ReservationExpireCommand,
)


@dataclass(frozen=True, slots=True)
class ExpirationRunResult:
    run_id: UUID | None
    business_date: date | None
    candidates: int
    expired: int
    outcome: str


class ExpirationWorker(Protocol):
    def run(self) -> ExpirationRunResult: ...


def _stable_id(property_id: UUID, business_date: date, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"property-rental/{property_id}/{business_date}/{value}")


class ReservationExpirationWorker:
    """Run one Property-local expiration batch under a database advisory lock."""

    _MAX_BATCHES = 100

    def __init__(
        self,
        database_url: str,
        financial_database_url: str,
        *,
        property_id: UUID,
        actor_id: UUID,
        limit: int = 100,
    ) -> None:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        self._database_url = database_url
        self._financial_database_url = financial_database_url
        self._property_id = property_id
        self._actor_id = actor_id
        self._limit = limit

    def run(self) -> ExpirationRunResult:
        with psycopg.connect(self._database_url, autocommit=True) as control:
            lock_row = control.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                (f"reservation-expiration/{self._property_id}",),
            ).fetchone()
            if lock_row is None:
                raise RuntimeError("Expiration singleton lock returned no result")
            locked = bool(lock_row[0])
            if not locked:
                return ExpirationRunResult(None, None, 0, 0, "singleton_skipped")
            try:
                business_date = control.execute(
                    """
                    SELECT timezone(property.timezone_name, clock_timestamp())::date,
                           min(reservation.effective_expiration_date)
                    FROM app.properties AS property
                    LEFT JOIN app.units AS unit ON unit.property_id=property.id
                    LEFT JOIN app.reservations AS reservation
                      ON reservation.unit_id=unit.id AND reservation.status='ACTIVE'
                    WHERE property.id = %s GROUP BY property.timezone_name
                    """,
                    (self._property_id,),
                ).fetchone()
                if business_date is None:
                    raise RuntimeError("Property was not found")
                current_date = business_date[0]
                earliest_due = business_date[1]
                logical_date = (
                    current_date
                    if earliest_due is None
                    else min(current_date, earliest_due + date.resolution)
                )
                run_seed = _stable_id(self._property_id, logical_date, "run")
                started = control.execute(
                    "SELECT * FROM app.start_reservation_expiration_run(%s,%s,%s)",
                    (run_seed, self._property_id, logical_date),
                ).fetchone()
                if started is None:
                    raise RuntimeError("Expiration run did not start")
                run_id, should_execute, _attempt = started
                if not should_execute:
                    return ExpirationRunResult(run_id, logical_date, 0, 0, "already_succeeded")
                ordinary = PostgresReservationService(
                    self._database_url,
                    self._property_id,
                    self._actor_id,
                )
                financial = PostgresReservationService(
                    self._database_url,
                    self._property_id,
                    self._actor_id,
                    self._financial_database_url,
                )
                scope = frozenset({str(self._property_id)})
                # Expiry never forfeits (owner answer, 2026-10-04): the forfeiture waits for
                # a Staff draft and a financial.approve holder.
                actor = AuthenticatedActor(
                    actor_id=str(self._actor_id),
                    capability_grants=frozenset({CapabilityGrant("reservations.cancel", scope)}),
                )
                candidates = 0
                expired = 0
                try:
                    for _batch_number in range(self._MAX_BATCHES):
                        due = ordinary.list_due(limit=self._limit, as_of=logical_date)
                        if not due:
                            break
                        candidates += len(due)
                        for item in due:
                            base = f"{item.reservation_id}/v{item.version}"
                            financial.expire(
                                ReservationExpireCommand(
                                    idempotency_key=_stable_id(
                                        self._property_id, logical_date, base + "/command"
                                    ),
                                    event_id=_stable_id(
                                        self._property_id, logical_date, base + "/event"
                                    ),
                                    reservation_id=item.reservation_id,
                                    expected_version=item.version,
                                    property_could_provide_unit=True,
                                    authorization_reference="reservations.cancel",
                                ),
                                actor=actor,
                            )
                            expired += 1
                    else:
                        raise RuntimeError("Expiration backlog exceeded the bounded batch limit")
                except Exception as exc:
                    control.execute(
                        "SELECT app.fail_reservation_expiration_run(%s,%s)",
                        (run_id, type(exc).__name__[:100]),
                    )
                    raise
                control.execute(
                    "SELECT app.finish_reservation_expiration_run(%s,%s,%s)",
                    (run_id, candidates, expired),
                )
                return ExpirationRunResult(run_id, logical_date, candidates, expired, "succeeded")
            finally:
                control.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                    (f"reservation-expiration/{self._property_id}",),
                )


def run_scheduled(
    worker: ExpirationWorker,
    *,
    once: bool,
    poll_interval_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run automatically at a bounded cadence; database locks make replicas safe."""
    consecutive_failures = 0
    while True:
        try:
            result = worker.run()
        except Exception as exc:
            consecutive_failures = min(consecutive_failures + 1, 3)
            print(f"failed:{type(exc).__name__}", flush=True)
            sleep(min(poll_interval_seconds, 2**consecutive_failures))
            continue
        consecutive_failures = 0
        print(result.outcome, flush=True)
        if once:
            return
        sleep(poll_interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Expire due Reservations for one Property")
    parser.add_argument("--property-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True, type=UUID)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval-seconds", type=int, default=300)
    args = parser.parse_args()
    database_url = os.environ.get("APP_DATABASE_URL")
    financial_url = os.environ.get("APP_FINANCIAL_DATABASE_URL")
    if not database_url or not financial_url:
        parser.error("APP_DATABASE_URL and APP_FINANCIAL_DATABASE_URL are required")
    if args.poll_interval_seconds < 1:
        parser.error("--poll-interval-seconds must be positive")
    run_scheduled(
        ReservationExpirationWorker(
            database_url,
            financial_url,
            property_id=args.property_id,
            actor_id=args.actor_id,
            limit=args.limit,
        ),
        once=args.once,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
