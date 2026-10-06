"""Bill and pay the Rent months a Rent run would still bill (V1-056 sub-slice 8e-3).

Owner answer 2 to Q-2026-10-06-33: a Final Settlement cannot close while a recurring Rent month of
its Lease is unbilled (the preview's blocking issue RENT_PERIOD_NOT_BILLED). Fixtures whose Lease
started long before its termination without Rent Invoices bill each such month here and pay it in
full, so the obligations their tests settle stay exactly as before.
"""

from uuid import UUID

import psycopg

from test_final_settlement_preview_migration import pay
from test_invoice_migration import create_recurring_rent_invoice

MONTHS = (
    "SELECT period_start,period_end FROM app.final_settlement_unbilled_rent_months("
    "%s,statement_timestamp())"
)


def unbilled_rent_months(url: str, lease: UUID) -> list[tuple[object, object]]:
    with psycopg.connect(url) as connection:
        return [(row[0], row[1]) for row in connection.execute(MONTHS, (lease,)).fetchall()]


def bill_unbilled_rent_months(url: str, human: UUID, prop: UUID, lease: UUID) -> list[UUID]:
    """Issue each unbilled recurring Rent month (80,000) to the Primary Tenant and pay it in full.

    The Lease keeps its move-in state: no Occupancy is added (recurring Rent coverage follows the
    Lease Start Date). The early final month of a voluntary early termination is billed with its
    BR-RENT-024 source, as the Rent generator bills it."""
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT primary_tenant_id,actual_termination_date FROM app.leases WHERE id=%s",
            (lease,),
        ).fetchone()
        assert row is not None
        customer, termination = UUID(str(row[0])), row[1]
        months = connection.execute(MONTHS, (lease,)).fetchall()
        billed = [
            create_recurring_rent_invoice(
                connection,
                actor_id=human,
                customer_id=customer,
                lease_id=lease,
                period_start=start,
                due_date_source=(
                    "BR-RENT-024"
                    if termination is not None and end > termination
                    else "BR-RENT-018"
                ),
                add_occupancy=False,
            )
            for start, end in months
        ]
    for invoice, line in billed:
        pay(url, prop, human, customer, invoice, line, 80_000)
    assert unbilled_rent_months(url, lease) == []
    return [invoice for invoice, _ in billed]
