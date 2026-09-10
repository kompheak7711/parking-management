"""Bounded read-only scheduled Rent nonpayment evaluation; never posts an event."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import psycopg

from property_rental.lease_enforcement import (
    LeaseEnforcementUnavailableError,
    PostgresLeaseEnforcementService,
    _identity,
)
from property_rental.lease_enforcement_context import EnforcementPage


@dataclass(frozen=True, slots=True)
class ScheduledRentNonpaymentEvaluator:
    database_url: str
    property_id: UUID
    actor_id: UUID

    def __post_init__(self) -> None:
        _identity(self.property_id, "property_id")
        _identity(self.actor_id, "actor_id")
        if not self.database_url:
            raise ValueError("A dedicated evaluation connection is required")

    def run_once(self, page: EnforcementPage | None = None) -> dict[str, object]:
        selected = page if page is not None else EnforcementPage()
        checked = EnforcementPage(selected.limit, selected.after_id)
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.read_only = True
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                row = connection.execute(
                    "SELECT app.scheduled_rent_nonpayment_evaluation(%s,%s,%s,%s)",
                    (self.actor_id, self.property_id, checked.limit, checked.after_id),
                ).fetchone()
        except psycopg.Error as exc:
            raise PostgresLeaseEnforcementService._error(exc) from exc
        if row is None or not isinstance(row[0], dict):
            raise LeaseEnforcementUnavailableError("Nonpayment evaluation result is unavailable")
        return cast(dict[str, object], row[0])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate one bounded read-only Rent nonpayment page"
    )
    parser.add_argument("--property-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True, type=UUID)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--cursor", type=UUID)
    args = parser.parse_args()
    url = os.environ.get("APP_NONPAYMENT_EVALUATION_DATABASE_URL")
    if not url:
        parser.error("APP_NONPAYMENT_EVALUATION_DATABASE_URL is required")
    try:
        result = ScheduledRentNonpaymentEvaluator(url, args.property_id, args.actor_id).run_once(
            EnforcementPage(args.limit, args.cursor)
        )
    except Exception as exc:
        # Neither a connection string nor source/customer details belong in logs.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1
    print(
        json.dumps(
            {
                "status": "evaluated",
                "count": len(cast(list[object], result["items"])),
                "next_cursor": result["next_cursor"],
                "business_date": result["business_date"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
