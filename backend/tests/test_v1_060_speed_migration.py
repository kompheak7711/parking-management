# ruff: noqa: E501
"""V1-060 speed migration `20270219_207`: the faster reads give the same answers.

Runs last in `scripts/database-test.sh`, on the shared test database after every other module
has left its Invoices, adjustments, Payments, credit and deposit applications and their
reversals behind, so each kind of money record is a case.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url

_SPEC = importlib.util.spec_from_file_location(
    "v1_060_speed",
    Path(__file__).parents[1] / "migrations/versions/20270219_207_v1_060_speed.py",
)
assert _SPEC is not None and _SPEC.loader is not None
SPEED = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SPEED)

# The migration's set-based balance, for every Invoice line at one instant.
_BALANCE = SPEED.OWED_FIRST_CHECK.split("AND line.amount_usd_cents", 1)[1].rsplit("> 0", 1)[0]
INLINE_BALANCE = (
    "SELECT line.id, app.invoice_line_outstanding_at(line.id,statement_timestamp()) AS exact, "
    f"line.amount_usd_cents {_BALANCE} AS inline FROM app.invoice_lines AS line"
)

OLD_ALERT_LINES = """
    SELECT line.id
    FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
    JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id
    WHERE u.property_id=%s AND line.category='RENT' AND line.source_lease_id=l.id
        AND i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=statement_timestamp()
        AND i.rent_billing_kind='RECURRING'
        AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-app.rent_nonpayment_day_zero(i.id)>=20
        AND app.invoice_line_outstanding_at(line.id,statement_timestamp())>0
"""


def _alert_lines(connection: psycopg.Connection[tuple[Any, ...]], prop: UUID) -> set[str]:
    seen: set[str] = set()
    after = None
    while True:
        row = connection.execute(
            "SELECT app.rent_nonpayment_alert_page(%s,100,%s)", (prop, after)
        ).fetchone()
        assert row is not None
        page = row[0]
        seen |= {str(item["rent_invoice_line_id"]) for item in page["items"]}
        if page["next_cursor"] is None:
            return seen
        after = page["next_cursor"]


def test_the_set_based_balance_matches_the_exact_function_for_every_invoice_line(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(INLINE_BALANCE).fetchall()
        kinds = connection.execute(
            "SELECT (SELECT count(*) FROM app.invoice_adjustments),"
            "(SELECT count(*) FROM app.payment_allocation_reversals),"
            "(SELECT count(*) FROM app.customer_credit_application_details),"
            "(SELECT count(*) FROM app.deposit_applications)"
        ).fetchone()
    assert rows, "the shared database has Invoice lines by the end of the run"
    assert kinds is not None and all(int(count) > 0 for count in kinds), kinds
    assert [row for row in rows if int(row[1]) != int(row[2])] == []


def test_the_alert_page_lists_exactly_the_lines_of_the_old_filter(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        properties = [
            UUID(str(row[0]))
            for row in connection.execute("SELECT id FROM app.properties").fetchall()
        ]
        for prop in properties:
            old = {str(row[0]) for row in connection.execute(OLD_ALERT_LINES, (prop,)).fetchall()}
            assert _alert_lines(connection, prop) == old


def test_the_invoice_list_order_has_its_index(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='app' "
            "AND indexname='invoices_invoice_date_order_idx'"
        ).fetchone()
    assert row is not None
    assert str(row[0]).endswith("(invoice_date, id)")
