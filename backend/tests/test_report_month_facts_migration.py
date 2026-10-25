"""V1-057 step 2: the month facts of the four "Totals by Unit and month" reports (DL-079 1 to 4).

Income counts each issued Invoice line in its month, with credit Adjustments as a minus; Payment
money counts in the month it came in, split as the records are now, with a reversal as a minus
in its own month; only the runtime role may run the reads, for an active person and an allowed
Property. The shared test database holds other tests' rows, so each check keeps this test's Unit.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.payment_allocation import ReverseAllocationCommand, ReversePaymentCommand
from test_credit_adjustment_excess_migration import credit
from test_debit_adjustment_line_block_migration import first_line
from test_invoice_migration import (
    create_recurring_rent_invoice,
    runtime_database_url,
    setup_signed_lease,
)
from test_payment_allocation_migration import actor, designated, service
from test_reservation_migration import migrated_database_url  # noqa: F401

REVISION = "20270302_221"


def facts(read: str, human: UUID, prop: UUID, allowed: list[UUID] | None = None) -> list[Any]:
    with psycopg.connect(runtime_database_url()) as connection:
        cursor = connection.execute(
            f"SELECT * FROM app.{read}(%s,%s,%s::uuid[])",
            (human, prop, [prop] if allowed is None else allowed),
        )
        return cursor.fetchall()


def lease_unit(url: str, lease: UUID) -> UUID:
    with psycopg.connect(url) as connection:
        row = connection.execute("SELECT unit_id FROM app.leases WHERE id=%s", (lease,)).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def payment_month(url: str, payment: UUID) -> date:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT date_trunc('month',payment_date)::date FROM app.payments WHERE id=%s",
            (payment,),
        ).fetchone()
    assert row is not None and isinstance(row[0], date)
    return row[0]


def test_income_and_payment_facts_count_each_record_in_its_month(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease = setup_signed_lease(connection)
        invoices = [
            create_recurring_rent_invoice(
                connection,
                actor_id=human,
                customer_id=customer,
                lease_id=lease,
                period_start=date(2027, month, 1),
            )[0]
            for month in (2, 3)
        ]
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=100_000
        )
        returned = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=30_000,
            lease_id=lease,
        )
    unit = lease_unit(migrated_database_url, lease)
    february, march = invoices
    credit(
        migrated_database_url, human, prop, march, first_line(migrated_database_url, march), 10_000
    )

    income = {
        (row[1], row[2]): row[3]
        for row in facts("report_income_facts", human, prop)
        if row[0] == unit
    }
    assert income == {(date(2027, 2, 1), "RENT"): 80_000, (date(2027, 3, 1), "RENT"): 70_000}

    staff = actor(human, prop)
    posted = [
        service().post(
            prop,
            payment,
            designated(invoice, first_line(migrated_database_url, invoice), amount),
            actor=staff,
        )
        for invoice, amount in ((february, 80_000), (march, 20_000))
    ]
    month = payment_month(migrated_database_url, payment)
    paid = [row for row in facts("report_payment_facts", human, prop) if row[0] == unit]
    assert (month, "INVOICES", "RENT", 100_000) in [tuple(row[1:]) for row in paid]

    allocation = posted[1]["allocation_ids"]
    assert isinstance(allocation, list)
    service().reverse_allocation(
        prop,
        UUID(str(allocation[0])),
        ReverseAllocationCommand(uuid4(), "Wrong Invoice"),
        actor=staff,
    )
    service().reverse_payment(
        prop, returned, ReversePaymentCommand(uuid4(), "Money returned"), actor=staff
    )
    paid = [tuple(row[1:]) for row in facts("report_payment_facts", human, prop) if row[0] == unit]
    assert (month, "INVOICES", "RENT", 80_000) in paid
    assert (month, "REVERSED_LATER", None, 30_000) in paid
    reversal = [row for row in paid if row[1] == "REVERSAL"]
    assert [row[3] for row in reversal] == [-30_000]
    # Payment money with no Lease has no Unit: its unpaid part is in the no-Unit row.
    no_unit = [
        row
        for row in facts("report_payment_facts", human, prop)
        if row[0] is None and row[1] == month and row[2] == "NOT_ALLOCATED"
    ]
    assert no_unit and no_unit[0][4] >= 20_000

    utility = facts("report_utility_facts", human, prop)
    assert all(len(row) == 10 for row in utility)


def test_the_month_facts_need_an_allowed_property_and_the_runtime_role(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_signed_lease(connection)
    for read in ("report_income_facts", "report_payment_facts", "report_utility_facts"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            facts(read, human, prop, allowed=[])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            facts(read, uuid4(), prop)
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(
            "SELECT p.proname, EXISTS(SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0), "
            "has_function_privilege('prm_runtime', p.oid, 'EXECUTE') FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='app' AND p.proname LIKE 'report\\_%%\\_facts' ORDER BY 1"
        ).fetchall()
    assert rows == [
        ("report_income_facts", False, True),
        ("report_payment_facts", False, True),
        ("report_utility_facts", False, True),
    ]


def test_the_report_month_facts_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270301_220"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
