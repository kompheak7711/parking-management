"""V1-057 step 3: the reads of the nine registers and lists (DL-072, DL-079 answer 5).

The Invoice register gives each issued Invoice its total, the part paid by Payments and what is
still owed, and counts a recurring Rent Invoice's overdue days from the 1st of the billed month;
the Payment register lists where each Payment's money went, and its Paid to Invoices equals the
register's Paid total; the Total Payment facts use the same split. Only the runtime role may run
the reads, for an active person and an allowed Property. The shared test database holds other
tests' rows, so each check keeps this test's Unit or Lease.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.rows import dict_row

from payment_test_support import seed_payment
from test_debit_adjustment_line_block_migration import first_line
from test_invoice_migration import (
    create_recurring_rent_invoice,
    runtime_database_url,
    setup_signed_lease,
)
from test_payment_allocation_migration import actor, designated, service
from test_reports_home_migration import today
from test_reservation_migration import migrated_database_url  # noqa: F401

REVISION = "20270304_223"
READS = (
    "report_invoice_register",
    "report_payment_register",
    "report_credit_ledger",
    "report_deposit_register",
    "report_final_settlement_register",
    "report_unit_occupancy",
    "report_lease_dates",
)


def read(name: str, human: UUID, prop: UUID, *extra: object) -> list[dict[str, Any]]:
    marks = "".join(",%s" for _ in extra)
    with psycopg.connect(runtime_database_url(), row_factory=dict_row) as connection:
        return connection.execute(
            f"SELECT * FROM app.{name}(%s,%s,%s::uuid[]{marks})", (human, prop, [prop], *extra)
        ).fetchall()


def test_the_invoice_and_payment_registers_agree_on_paid_to_invoices(
    migrated_database_url: str,  # noqa: F811
) -> None:
    now = today(migrated_database_url)
    first = (now.replace(day=1) - timedelta(days=80)).replace(day=1)
    billed = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease = setup_signed_lease(
            connection, start_date=first, end_date=now + timedelta(days=300)
        )
        invoice, _ = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=billed,
            invoice_date=billed - timedelta(days=6),
        )
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=100_000,
            lease_id=lease,
        )
        row = connection.execute("SELECT unit_id FROM app.leases WHERE id=%s", (lease,)).fetchone()
    assert row is not None
    unit = row[0]
    service().post(
        prop,
        payment,
        designated(invoice, first_line(migrated_database_url, invoice), 30_000),
        actor=actor(human, prop),
    )

    invoices = [
        item for item in read("report_invoice_register", human, prop) if item["lease_id"] == lease
    ]
    assert len(invoices) == 1
    mine = invoices[0]
    assert mine["invoice_id"] == invoice and mine["unit_id"] == unit
    assert mine["paid_usd_cents"] == 30_000
    assert mine["owed_usd_cents"] == mine["total_usd_cents"] - 30_000
    assert mine["other_settled_usd_cents"] == 0
    # Recurring Rent counts from the 1st of the billed month: day zero is the day before.
    assert mine["overdue_days"] == (now - (billed - timedelta(days=1))).days

    payments = [
        item
        for item in read("report_payment_register", human, prop)
        if item["payment_id"] == payment
    ]
    assert len(payments) == 1
    receipt = payments[0]
    assert receipt["unit_id"] == unit and receipt["amount_usd_cents"] == 100_000
    assert receipt["reversed_on"] is None
    parts = {
        (part["kind"], part["category"]): part["amount_usd_cents"] for part in receipt["parts"]
    }
    assert parts == {("INVOICES", "RENT"): 30_000, ("NOT_ALLOCATED", None): 70_000}

    unit_payments = [
        item for item in read("report_payment_register", human, prop) if item["unit_id"] == unit
    ]
    paid_to_invoices = sum(
        part["amount_usd_cents"]
        for item in unit_payments
        for part in item["parts"]
        if part["kind"] == "INVOICES"
    )
    unit_invoices = [
        item for item in read("report_invoice_register", human, prop) if item["unit_id"] == unit
    ]
    assert paid_to_invoices == sum(item["paid_usd_cents"] for item in unit_invoices) == 30_000
    facts = [item for item in read("report_payment_facts", human, prop) if item["unit_id"] == unit]
    assert sum(item["amount_usd_cents"] for item in facts) == 100_000

    occupancy = [
        item for item in read("report_unit_occupancy", human, prop) if item["unit_id"] == unit
    ]
    assert len(occupancy) == 1 and occupancy[0]["lease_id"] == lease
    assert occupancy[0]["customer_id"] == customer
    leases = [item for item in read("report_lease_dates", human, prop) if item["lease_id"] == lease]
    assert leases[0]["days_to_end"] == 300 and leases[0]["renewal_drafted"] is False


def test_the_register_reads_need_an_allowed_property_and_the_runtime_role(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_signed_lease(connection)
    for name in READS:
        read(name, human, prop)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(runtime_database_url()) as connection:
                connection.execute(f"SELECT * FROM app.{name}(%s,%s,'{{}}'::uuid[])", (human, prop))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            read(name, uuid4(), prop)
    assert read("report_audit_activity", human, prop, None, None)
    assert read("report_audit_activity", human, prop, date(2001, 1, 1), date(2001, 1, 2)) == []
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        read("report_audit_activity", human, prop, date(2026, 2, 1), date(2026, 1, 1))
    with psycopg.connect(migrated_database_url) as connection:
        grants = connection.execute(
            "SELECT p.proname, EXISTS(SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0), "
            "has_function_privilege('prm_runtime', p.oid, 'EXECUTE') FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='app' AND p.proname LIKE 'report\\_%%' ORDER BY 1"
        ).fetchall()
    expected = {name: True for name in (*READS, "report_audit_activity", "report_payment_facts")}
    expected |= {"report_income_facts": True, "report_utility_facts": True}
    expected["report_payment_parts"] = False
    expected["report_actor_property"] = False
    assert {name: runtime for name, public, runtime in grants} == expected
    assert all(not public for _, public, _ in grants)


def test_the_report_registers_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270303_222"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
