"""Authorized dated source pagination preserves financial facts and explicit posting."""

import json
from datetime import date, datetime
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
from test_invoice_due_proposal_migration import Context, funds
from test_invoice_migration import runtime_database_url
from test_reservation_migration import migrated_database_url as migrated_database_url

KINDS = ["PAYMENT", "CREDIT"]
SIGNATURE = (
    "app.financial_invoice_due_sources_page(uuid,uuid,text,uuid,uuid,uuid,integer,text,text,uuid)"
)


@pytest.fixture
def source_runtime_observations() -> list[dict[str, object]]:
    return []


def page(
    connection: DB,
    kind: str,
    context: Context,
    money: UUID,
    **overrides: Any,
) -> dict[str, Any]:
    actor, prop, _, invoice, line = context
    arguments: dict[str, Any] = {
        "property": prop,
        "actor": actor,
        "purpose": "allocation" if kind == "PAYMENT" else "credit_application",
        "source": money,
        "invoice": invoice,
        "line": line,
        "limit": 1,
        "expected": None,
        "after_kind": None,
        "after_id": None,
    }
    assert set(overrides) <= arguments.keys()
    arguments.update(overrides)
    row = connection.execute(
        "SELECT app.financial_invoice_due_sources_page(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        tuple(arguments.values()),
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


def cursor(value: dict[str, Any]) -> dict[str, Any]:
    last = value["items"][-1]
    return {
        "expected": value["revision"],
        "after_kind": last["source_kind"],
        "after_id": UUID(last["source_id"]),
    }


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("limit", [1, 2, 100])
def test_due_sources_read_only_ordered_pagination(
    due_connection: DB,
    kind: str,
    limit: int,
    source_runtime_observations: list[dict[str, object]],
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    first = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    last = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 70, date(2027, 3, 1))
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    with psycopg.connect(runtime_database_url()) as runtime:
        runtime.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        runtime.execute("SET LOCAL lock_timeout='3000ms'")
        runtime.execute("SET LOCAL statement_timeout='5000ms'")
        runtime.execute("SET LOCAL timezone='UTC'")
        row = runtime.execute(
            "SELECT current_database(),current_user,current_setting('transaction_read_only'),"
            "current_setting('transaction_isolation'),current_setting('lock_timeout'),"
            "current_setting('statement_timeout'),current_setting('timezone')"
        ).fetchone()
        assert row == (
            runtime.info.dbname,
            "prm_runtime",
            "on",
            "repeatable read",
            "3s",
            "5s",
            "UTC",
        )
        source_runtime_observations.append(
            {
                "database": runtime.info.dbname,
                "role": runtime.info.user,
                "host": runtime.info.host,
                "port": runtime.info.port,
                "read_only": True,
                "repeatable_read": True,
                "lock_timeout_ms": 3000,
                "statement_timeout_ms": 5000,
                "utc": True,
            }
        )
        value = page(runtime, kind, context, money, limit=limit)
        revision = value["revision"]
        observed: list[dict[str, Any]] = []
        for _ in range(3):
            assert set(value) == {
                "property_id",
                "purpose",
                "source_id",
                "invoice_id",
                "invoice_line_id",
                "invoice_version",
                "revision",
                "as_of",
                "aggregate_outstanding_usd_cents",
                "item_count",
                "has_more",
                "items",
            }
            assert value["property_id"] == str(prop) and value["source_id"] == str(money)
            assert value["invoice_id"] == str(invoice) and value["invoice_line_id"] == str(line)
            assert value["purpose"] == ("allocation" if kind == "PAYMENT" else "credit_application")
            assert value["invoice_version"] > 0 and value["revision"] == revision
            assert value["item_count"] == 3 and value["aggregate_outstanding_usd_cents"] == 80120
            assert len(value["items"]) <= limit and len(json.dumps(value).encode()) < 100000
            assert datetime.fromisoformat(value["as_of"]).tzinfo is not None
            for item in value["items"]:
                assert set(item) == {
                    "source_kind",
                    "source_id",
                    "approved_due_date",
                    "source_occurred_at",
                    "remaining_usd_cents",
                }
                assert datetime.fromisoformat(item["source_occurred_at"]).tzinfo is not None
            observed.extend(value["items"])
            if not value["has_more"]:
                break
            value = page(runtime, kind, context, money, limit=limit, **cursor(value))
        assert not value["has_more"]
        assert [
            (x["source_id"], x["remaining_usd_cents"], x["approved_due_date"]) for x in observed
        ] == [
            (str(first), 50, "2027-01-01"),
            (str(line), 80000, "2027-02-05"),
            (str(last), 70, "2027-03-01"),
        ]
        assert [x["source_kind"] for x in observed] == [
            "DEBIT_ADJUSTMENT",
            "ORIGINAL_LINE",
            "DEBIT_ADJUSTMENT",
        ]
        exhausted = page(runtime, kind, context, money, limit=limit, **cursor(value))
        assert exhausted["items"] == [] and exhausted["has_more"] is False
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "case",
    [
        "purpose",
        "limit0",
        "limit101",
        "nil_line",
        "partial_cursor",
        "bad_revision",
        "bad_kind",
        "nil_after",
    ],
)
def test_due_sources_invalid_parameters(due_connection: DB, kind: str, case: str) -> None:
    context, money = funds(due_connection, kind, 100)
    parameters: dict[str, Any] = {}
    if case == "purpose":
        parameters["purpose"] = "refund"
    elif case.startswith("limit"):
        parameters["limit"] = int(case.removeprefix("limit"))
    elif case == "nil_line":
        parameters["line"] = UUID(int=0)
    else:
        parameters = {"expected": "a" * 64, "after_kind": "ORIGINAL_LINE", "after_id": context[-1]}
        if case == "partial_cursor":
            parameters["after_kind"] = None
        elif case == "bad_revision":
            parameters["expected"] = "A" * 64
        elif case == "bad_kind":
            parameters["after_kind"] = "PAYMENT"
        else:
            parameters["after_id"] = UUID(int=0)
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            page(due_connection, kind, context, money, **parameters)
    assert error.value.sqlstate == "22023"
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "case", ["property", "source", "invoice", "line", "unknown_actor", "disabled_actor"]
)
def test_due_sources_current_authorized_context(due_connection: DB, kind: str, case: str) -> None:
    context, money = funds(due_connection, kind, 100)
    parameters: dict[str, Any] = {}
    if case in ("property", "source", "line"):
        parameters[case] = uuid4()
    elif case == "invoice":
        other = source(due_connection)
        parameters.update(invoice=other[-2], line=other[-1])
    elif case == "unknown_actor":
        parameters["actor"] = uuid4()
    else:
        due_connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (context[0],),
        )
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            page(due_connection, kind, context, money, **parameters)
    assert error.value.sqlstate == ("P4506" if case.endswith("actor") else "P4501")
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("change", ["debit", "post", "limit"])
def test_due_sources_stale_continuation(due_connection: DB, kind: str, change: str) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    value = page(due_connection, kind, context, money)
    if change == "debit":
        adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 70, date(2027, 3, 1))
    elif change == "post":
        prepared = preview(due_connection, kind, context, money, intent_for(kind, invoice, line))
        post(due_connection, kind, context, money, prepared["intent"])
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            page(
                due_connection,
                kind,
                context,
                money,
                limit=2 if change == "limit" else 1,
                **cursor(value),
            )
    assert error.value.sqlstate == "P4507"
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
def test_due_sources_depleted_sources_and_paid_line(due_connection: DB, kind: str) -> None:
    context, money = funds(due_connection, kind, 80050)
    actor, prop, _, invoice, line = context
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    prepared = preview(due_connection, kind, context, money, intent_for(kind, invoice, line, 50))
    post(due_connection, kind, context, money, prepared["intent"])
    value = page(due_connection, kind, context, money)
    assert value["item_count"] == 1 and value["has_more"] is False
    assert value["items"][0]["source_id"] == str(line)
    assert value["aggregate_outstanding_usd_cents"] == 80000
    prepared = preview(due_connection, kind, context, money, intent_for(kind, invoice, line, 80000))
    post(due_connection, kind, context, money, prepared["intent"])
    before = legacy_financial_snapshot(due_connection)
    value = page(due_connection, kind, context, money)
    assert value["items"] == [] and value["has_more"] is False and value["item_count"] == 0
    assert value["aggregate_outstanding_usd_cents"] == 0
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
def test_due_sources_legacy_unknown_attribution_blocks(
    legacy_due_connection: DB, kind: str
) -> None:
    context, money = funds(legacy_due_connection, kind, 100)
    legacy_adjustment(legacy_due_connection, context, "DEBIT", 50)
    before = upgrade_populated_due_history(legacy_due_connection)
    with pytest.raises(psycopg.Error) as error:
        with legacy_due_connection.transaction():
            page(legacy_due_connection, kind, context, money)
    assert error.value.sqlstate == "P4507"
    assert legacy_financial_snapshot(legacy_due_connection) == before


def test_due_sources_minimal_role_and_function_contract(due_connection: DB) -> None:
    row = due_connection.execute(
        "SELECT provolatile,prosecdef,proconfig FROM pg_proc WHERE oid=%s::regprocedure",
        (SIGNATURE,),
    ).fetchone()
    assert row == ("s", True, ["search_path=pg_catalog", "TimeZone=UTC"])
    for role, expected in (
        ("prm_runtime", True),
        ("prm_financial", False),
        ("prm_bootstrap", False),
    ):
        assert due_connection.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, SIGNATURE)
        ).fetchone() == (expected,)
        assert due_connection.execute(
            "SELECT has_function_privilege(%s,"
            "'app.invoice_line_due_position_at(uuid,timestamptz)','EXECUTE')",
            (role,),
        ).fetchone() == (False,)
    assert due_connection.execute(
        "SELECT NOT EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a "
        "WHERE p.oid=%s::regprocedure AND a.grantee=0)",
        (SIGNATURE,),
    ).fetchone() == (True,)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["missing_anchor", "forged_revision"])
def test_due_sources_anchor_is_bound_to_current_revision(
    due_connection: DB, kind: str, case: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    value = page(due_connection, kind, context, money)
    parameters = cursor(value)
    if case == "missing_anchor":
        parameters["after_id"] = uuid4()
    else:
        parameters["expected"] = "f" * 64
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            page(due_connection, kind, context, money, **parameters)
    assert error.value.sqlstate == ("22023" if case == "missing_anchor" else "P4507")
    assert legacy_financial_snapshot(due_connection) == before
