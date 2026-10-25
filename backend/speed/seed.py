"""Made-up history for the V1-060 speed test (DL-071 answer 14): 300 Units, 10 years.

Test-only. It writes into a disposable PostgreSQL started by scripts/speed-test.sh, never into
an office database. Every name, phone and amount is invented. The rows are written in the same
shapes the PostgreSQL test fixtures use (tests/test_lease_migration.py,
tests/test_invoice_migration.py, tests/payment_test_support.py), so the database's own checks
and triggers accept or refuse them as they would accept or refuse real records. Payments are
put on Invoices by the real allocation service, so allocation history is real too.

History per Unit: one-year Leases back to back for ten years (a new Customer each year; the last
Lease runs two years), one recurring Rent Invoice per month after the first, paid on the 3rd. The
last two months of one Unit in five stay unpaid, so overdue lists have rows. Each Unit has an
electricity and a water Meter with a reading at every month end.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))

from payment_test_support import seed_payment
from property_rental.property import configure_postgres_property
from test_invoice_migration import create_recurring_rent_invoice
from test_lease_migration import create_draft, sign_lease
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_sign_in_code_migration import CodeDatabase, add_account
from test_utility_meter_migration import add_meter

RENT_CENTS = 80_000


@dataclass(frozen=True)
class Seeded:
    actor_id: UUID
    property_id: UUID
    unit_ids: list[UUID]


def month_starts(first: date, last: date) -> list[date]:
    months = []
    current = first
    while current <= last:
        months.append(current)
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def month_end(start: date) -> date:
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def base(url: str, runtime_url: str, units: int) -> Seeded:
    """The Property through its real one-time setup (default bundles) and a signed-in Owner."""
    owner = add_account(CodeDatabase(url, runtime_url), "speed-owner", account_class="owner")
    actor_id = owner.actor_id
    property_id = uuid4()
    unit_ids = [uuid4() for _ in range(units)]
    configure_postgres_property(
        runtime_url, property_id, name="Speed Test Residence", actor_id=actor_id
    )
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO app.units(id,property_id,unit_number,floor,unit_type,status,"
                "created_by,updated_by) VALUES (%s,%s,%s,%s,'ONE_BEDROOM','VACANT',%s,%s)",
                [
                    (
                        unit,
                        property_id,
                        f"U{(index // 20) + 1}{(index % 20) + 1:02d}",
                        str((index // 20) + 1),
                        actor_id,
                        actor_id,
                    )
                    for index, unit in enumerate(unit_ids)
                ],
            )
    return Seeded(actor_id, property_id, unit_ids)


def seed_unit(url: str, seeded: Seeded, index: int, first: date, years: int) -> int:
    """Write one Unit's ten years; return the number of Rent Invoices written."""
    unit = seeded.unit_ids[index]
    human = seeded.actor_id
    service = allocations()
    staff = allocation_actor(human, seeded.property_id)
    invoices = 0
    with psycopg.connect(url) as connection:
        # An electricity and a water Meter, read on the last day of every month.
        installed = first - timedelta(days=31)
        for utility_type, unit_code, step in (("ELECTRICITY", "KWH", 150), ("WATER", "M3", 6)):
            meter = add_meter(
                connection,
                actor_id=human,
                unit_id=unit,
                utility_type=utility_type,
                measurement_unit_code=unit_code,
                installed_date=installed,
                serial_number=f"{utility_type[:2]}-SPEED-{index + 1:03d}",
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO app.utility_readings(id,meter_id,reading_date,reading_value,"
                    "validated_at,validated_by,created_by,updated_by) "
                    "VALUES (%s,%s,%s,%s,statement_timestamp(),%s,%s,%s)",
                    [
                        (uuid4(), meter, month_end(period), str(step * number), human, human, human)
                        for number, period in enumerate(
                            month_starts(
                                installed.replace(day=1),
                                first.replace(year=first.year + years) - timedelta(days=1),
                            )
                        )
                    ],
                )
    for year in range(years):
        start = first.replace(year=first.year + year)
        # The last Lease runs two years, so the next month's billing run has every Unit to bill.
        length = 2 if year == years - 1 else 1
        end = month_end(start.replace(year=start.year + length) - timedelta(days=1))
        billed_until = first.replace(year=first.year + years)
        customer = uuid4()
        to_pay: list[tuple[UUID, UUID, date]] = []
        with psycopg.connect(url) as connection:
            connection.execute(
                "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
                "VALUES (%s,%s,%s,%s)",
                (customer, f"Made-up Tenant {index + 1}-{year + 1}", human, human),
            )
            lease = create_draft(
                connection,
                actor_id=human,
                unit_id=unit,
                primary_tenant_id=customer,
                start_date=start,
                end_date=end,
            )
            sign_lease(connection, lease, human)
            # The first month is the Lease's Initial Rent (BR-RENT-005), not a recurring month.
            months = [month for month in month_starts(start, end)[1:] if month < billed_until]
            for number, period in enumerate(months):
                invoice, line = create_recurring_rent_invoice(
                    connection,
                    actor_id=human,
                    customer_id=customer,
                    lease_id=lease,
                    period_start=period,
                    add_occupancy=number == 0,
                )
                invoices += 1
                unpaid_tail = year == years - 1 and number >= len(months) - 2 and index % 5 == 0
                if not unpaid_tail:
                    to_pay.append((invoice, line, period))
            connection.commit()
            payments = [
                (
                    seed_payment(
                        connection,
                        actor_id=human,
                        property_id=seeded.property_id,
                        customer_id=customer,
                        amount=RENT_CENTS,
                        confirmed_at=datetime.combine(
                            period.replace(day=3), clock_time(3, 0), tzinfo=UTC
                        ),
                    ),
                    invoice,
                    line,
                )
                for invoice, line, period in to_pay
            ]
        for payment, invoice, line in payments:
            service.post(
                seeded.property_id,
                payment,
                designated(invoice, line, RENT_CENTS),
                actor=staff,
            )
    return invoices


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--units", type=int, default=300)
    parser.add_argument("--years", type=int, default=10)
    # By default the history ends with this month, so next month's Rent run has every Unit.
    parser.add_argument("--first", type=date.fromisoformat, default=None)
    parser.add_argument("--workers", type=int, default=8)
    arguments = parser.parse_args()
    if arguments.first is None:
        next_month = (date.today().replace(day=28) + timedelta(days=4)).replace(day=1)
        arguments.first = next_month.replace(year=next_month.year - arguments.years)
    url = os.environ["MIGRATION_DATABASE_URL"]
    runtime_url = os.environ["APP_DATABASE_URL"]
    started = time.monotonic()
    seeded = base(url, runtime_url, arguments.units)
    with ThreadPoolExecutor(arguments.workers) as pool:
        counts = list(
            pool.map(
                lambda index: seed_unit(url, seeded, index, arguments.first, arguments.years),
                range(arguments.units),
            )
        )
    print(
        f"seeded {arguments.units} Units, {sum(counts)} Rent Invoices "
        f"in {time.monotonic() - started:.0f} s; property {seeded.property_id}"
    )


if __name__ == "__main__":
    main()
