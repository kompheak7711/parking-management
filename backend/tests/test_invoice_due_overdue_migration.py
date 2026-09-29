"""Proved Invoice-wide overdue balances; consumer acceptance remains separate."""

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from test_invoice_due_migration import (
    DB,
    adjustment,
    legacy_adjustment,
    legacy_financial_snapshot,
    source,
    upgrade_populated_due_history,
)
from test_invoice_due_migration import due_connection as due_connection
from test_invoice_due_migration import legacy_due_connection as legacy_due_connection
from test_invoice_due_posting_migration import post
from test_invoice_due_preview_wrappers_migration import intent_for, preview
from test_invoice_due_proposal_migration import funds
from test_reservation_migration import migrated_database_url as migrated_database_url

SIGNATURE = "app.invoice_due_overdue_position_at(uuid,timestamptz)"


def overdue(connection: DB, invoice: UUID, at: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT app.invoice_due_overdue_position_at(%s,%s::timestamptz)", (invoice, at)
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


@pytest.mark.parametrize(
    ("at", "business_date", "expected"),
    [
        ("2026-12-31T16:59:59.999999Z", "2026-12-31", 0),
        ("2026-12-31T17:00:00Z", "2027-01-01", 0),
        ("2027-01-01T16:59:59.999999Z", "2027-01-01", 0),
        ("2027-01-01T17:00:00Z", "2027-01-02", 101),
        ("2027-02-05T16:59:59.999999Z", "2027-02-05", 101),
        ("2027-02-05T17:00:00Z", "2027-02-06", 80101),
        ("2027-03-01T17:00:00Z", "2027-03-02", 80303),
    ],
)
def test_due_overdue_approved_dates_use_exact_khmer_midnight(
    due_connection: DB, at: str, business_date: str, expected: int
) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 101, date(2027, 1, 1))
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 202, date(2027, 3, 1))
    before = legacy_financial_snapshot(due_connection)
    value = overdue(due_connection, invoice, at)
    assert set(value) == {
        "invoice_id",
        "source_due_date",
        "as_of",
        "business_date",
        "timezone",
        "line_count",
        "unknown_line_count",
        "attribution_complete",
        "aggregate_outstanding_usd_cents",
        "dated_source_count",
        "overdue_balance_usd_cents",
        "not_overdue_balance_usd_cents",
    }
    assert value["invoice_id"] == str(invoice) and value["source_due_date"] == "2027-02-05"
    assert value["business_date"] == business_date and value["timezone"] == "Asia/Phnom_Penh"
    assert value["attribution_complete"] is True and value["unknown_line_count"] == 0
    assert value["line_count"] == 1 and value["dated_source_count"] == 3
    assert value["aggregate_outstanding_usd_cents"] == 80303
    assert value["overdue_balance_usd_cents"] == expected
    assert value["not_overdue_balance_usd_cents"] == 80303 - expected
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_due_overdue_designated_future_source_preserves_overdue_balance(
    due_connection: DB, kind: str
) -> None:
    context, money = funds(due_connection, kind, 50)
    actor, prop, _, invoice, line = context
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 101, date(2027, 1, 1))
    future = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 202, date(2027, 3, 1))
    intent = intent_for(kind, invoice, line, 50)
    target = intent["targets"][0] if kind == "PAYMENT" else intent
    target["details"][0]["source_parts"] = [
        {"source_kind": "DEBIT_ADJUSTMENT", "source_id": str(future), "amount_usd_cents": 50}
    ]
    prepared = preview(due_connection, kind, context, money, intent)
    post(due_connection, kind, context, money, prepared["intent"])
    before = legacy_financial_snapshot(due_connection)
    value = overdue(due_connection, invoice, "2027-02-05T17:00:00Z")
    assert value["aggregate_outstanding_usd_cents"] == 80253
    assert value["overdue_balance_usd_cents"] == 80101
    assert value["not_overdue_balance_usd_cents"] == 152
    assert value["attribution_complete"] is True
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("invalid", ["nil", "missing_id", "missing_time", "infinity", "-infinity"])
def test_due_overdue_invalid_identity_and_time_fail_closed(
    due_connection: DB, invalid: str
) -> None:
    identity = None if invalid == "missing_id" else UUID(int=0) if invalid == "nil" else uuid4()
    at = (
        None
        if invalid == "missing_time"
        else invalid
        if "infinity" in invalid
        else "2027-02-06T00:00:00Z"
    )
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            due_connection.execute(
                "SELECT app.invoice_due_overdue_position_at(%s::uuid,%s::timestamptz)",
                (identity, at),
            )
    assert error.value.sqlstate == "23514"


@pytest.mark.parametrize("missing", [True, False])
def test_due_overdue_missing_or_not_yet_issued_has_no_projection(
    due_connection: DB, missing: bool
) -> None:
    _, _, _, invoice, _ = source(due_connection)
    assert due_connection.execute(
        "SELECT app.invoice_due_overdue_position_at(%s,%s::timestamptz)",
        (uuid4() if missing else invoice, "2000-01-01T00:00:00Z"),
    ).fetchone() == (None,)


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_due_overdue_legacy_unknown_is_never_zero(legacy_due_connection: DB, kind: str) -> None:
    context, _ = funds(legacy_due_connection, kind, 100)
    legacy_adjustment(legacy_due_connection, context, "DEBIT", 50)
    before = upgrade_populated_due_history(legacy_due_connection)
    value = overdue(legacy_due_connection, context[3], "2027-04-01T00:00:00Z")
    assert value["attribution_complete"] is False and value["unknown_line_count"] == 1
    assert value["line_count"] == 1 and value["aggregate_outstanding_usd_cents"] == 80050
    assert value["overdue_balance_usd_cents"] is None
    assert value["not_overdue_balance_usd_cents"] is None
    assert value["dated_source_count"] is None
    assert legacy_financial_snapshot(legacy_due_connection) == before


def test_due_overdue_private_stable_invoker_contract(due_connection: DB) -> None:
    assert due_connection.execute(
        "SELECT provolatile,prosecdef,proconfig FROM pg_proc WHERE oid=%s::regprocedure",
        (SIGNATURE,),
    ).fetchone() == ("s", False, ["search_path=pg_catalog", "TimeZone=UTC"])
    for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
        assert due_connection.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, SIGNATURE)
        ).fetchone() == (False,)
    assert due_connection.execute(
        "SELECT NOT EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a "
        "WHERE p.oid=%s::regprocedure AND a.grantee=0)",
        (SIGNATURE,),
    ).fetchone() == (True,)
