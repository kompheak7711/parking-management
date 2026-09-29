"""Dated Payment/Credit proposal helper contracts; command/UI acceptance is separate."""

from datetime import date, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.invoice_due import (
    DueAmount,
    DueSourceKind,
    propose_within_line_due_allocation,
)
from test_invoice_due_migration import (
    DB,
    adjustment,
    legacy_adjustment,
    legacy_financial_snapshot,
    position,
    source,
    upgrade_populated_due_history,
)
from test_invoice_due_migration import (
    due_connection as due_connection,
)
from test_invoice_due_migration import (
    legacy_due_connection as legacy_due_connection,
)
from test_reservation_migration import migrated_database_url as migrated_database_url

SQL = "SELECT app.invoice_line_due_application_parts(%s,%s,clock_timestamp(),%s,%s)"


def preview(
    connection: DB,
    line: UUID,
    amount: int,
    selected: object = None,
    maximum: int = 500,
) -> dict[str, Any]:
    row = connection.execute(
        SQL, (line, amount, Jsonb(selected) if selected is not None else None, maximum)
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


def selection(line: UUID, amount: object, kind: str = "ORIGINAL_LINE") -> dict[str, object]:
    return {"source_kind": kind, "source_id": str(line), "amount_usd_cents": amount}


def test_due_application_default_order_matches_python_and_has_exact_source_facts(
    due_connection: DB,
) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    later = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 20000, date(2027, 3, 5))
    earlier = adjustment(
        due_connection, actor, prop, invoice, line, "DEBIT", 10000, date(2027, 1, 5)
    )
    before = legacy_financial_snapshot(due_connection)
    facts = position(due_connection, line)
    amounts = tuple(
        DueAmount(
            line,
            DueSourceKind(x["source_kind"]),
            UUID(x["source_id"]),
            date.fromisoformat(x["approved_due_date"]),
            datetime.fromisoformat(x["source_occurred_at"]),
            x["remaining_usd_cents"],
        )
        for x in facts["amounts"]
    )
    expected = propose_within_line_due_allocation(line, 85000, amounts)
    actual = preview(due_connection, line, 85000)
    assert actual["basis"] == "EARLIEST_DUE"
    assert actual["amount_usd_cents"] == expected.applied_usd_cents == 85000
    assert actual["remaining_requested_usd_cents"] == 0
    assert (
        [(x["source_id"], x["amount_usd_cents"]) for x in actual["parts"]]
        == [(str(earlier), 10000), (str(line), 75000)]
        == [(str(x.source.source_id), x.amount_usd_cents) for x in expected.allocations]
    )
    assert str(later) not in [x["source_id"] for x in actual["parts"]]
    by_source = {x["source_id"]: x for x in facts["amounts"]}
    for part in actual["parts"]:
        current = by_source[part["source_id"]]
        assert part["outstanding_usd_cents"] == current["remaining_usd_cents"]
        assert part["approved_due_date"] == current["approved_due_date"]
        assert part["source_occurred_at"] == current["source_occurred_at"]
    assert legacy_financial_snapshot(due_connection) == before
    assert position(due_connection, line)["amounts"] == facts["amounts"]
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_due_source_parts"
    ).fetchone() == (0,)


def test_due_application_equal_dates_preserve_source_chronology(
    due_connection: DB,
) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 20000, date(2027, 2, 5))
    actual = preview(due_connection, line, 90000)
    assert [(x["source_id"], x["amount_usd_cents"]) for x in actual["parts"]] == [
        (str(line), 80000),
        (str(debit), 10000),
    ]


def test_due_application_part_limit_stops_before_later_sources(
    due_connection: DB,
) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    first = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 100, date(2027, 1, 1))
    second = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 200, date(2027, 1, 2))
    actual = preview(due_connection, line, 400, maximum=1)
    assert actual["amount_usd_cents"] == 100
    assert actual["remaining_requested_usd_cents"] == 300
    assert [x["source_id"] for x in actual["parts"]] == [str(first)]
    complete = preview(due_connection, line, 400, maximum=3)
    assert [(x["source_id"], x["amount_usd_cents"]) for x in complete["parts"]] == [
        (str(first), 100),
        (str(second), 200),
        (str(line), 100),
    ]


def test_due_application_depleted_source_is_not_proposed(due_connection: DB) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 10000, date(2027, 3, 5))
    adjustment(
        due_connection,
        actor,
        prop,
        invoice,
        line,
        "CREDIT",
        80000,
        correction_parts=((None, 80000, 1),),
    )
    actual = preview(due_connection, line, 10000)
    assert [x["source_id"] for x in actual["parts"]] == [str(debit)]


def test_due_application_explicit_designation_preserves_later_source_and_exact_order(
    due_connection: DB,
) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 10000, date(2027, 3, 5))
    selected = [selection(debit, 3000, "DEBIT_ADJUSTMENT"), selection(line, 2000)]
    actual = preview(due_connection, line, 5000, selected)
    assert actual["basis"] == "CUSTOMER_DESIGNATED"
    assert actual["remaining_requested_usd_cents"] == 0
    assert [(x["source_id"], x["amount_usd_cents"]) for x in actual["parts"]] == [
        (str(debit), 3000),
        (str(line), 2000),
    ]
    assert selected == [
        selection(debit, 3000, "DEBIT_ADJUSTMENT"),
        selection(line, 2000),
    ]
    with pytest.raises(psycopg.Error, match="complete bounded selection"):
        with due_connection.transaction():
            preview(due_connection, line, 5000, selected, maximum=1)


@pytest.mark.parametrize(
    "case",
    [
        "zero",
        "negative",
        "too_large",
        "over_line",
        "zero_limit",
        "large_limit",
        "null_time",
        "unknown_line",
    ],
)
def test_due_application_rejects_invalid_request_bounds(due_connection: DB, case: str) -> None:
    *_, line = source(due_connection)
    amount = {
        "zero": 0,
        "negative": -1,
        "too_large": 9000000000000001,
        "over_line": 80001,
    }.get(case, 1)
    maximum = {"zero_limit": 0, "large_limit": 501}.get(case, 500)
    selected_line = uuid4() if case == "unknown_line" else line
    statement = (
        SQL.replace("clock_timestamp()", "NULL::timestamptz") if case == "null_time" else SQL
    )
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            due_connection.execute(statement, (selected_line, amount, None, maximum))
    assert error.value.sqlstate == (
        "P4508" if case == "over_line" else "P4507" if case == "unknown_line" else "P4502"
    )


@pytest.mark.parametrize(
    "case",
    [
        "object",
        "empty",
        "unknown_kind",
        "bad_uuid",
        "float",
        "boolean",
        "extra",
        "duplicate",
        "wrong_total",
        "other_source",
    ],
)
def test_due_application_rejects_inexact_or_unprovable_parts(due_connection: DB, case: str) -> None:
    *_, line = source(due_connection)
    cases: dict[str, object] = {
        "object": {},
        "empty": [],
        "unknown_kind": [selection(line, 100, "OTHER")],
        "bad_uuid": [{**selection(line, 100), "source_id": "not-an-identity"}],
        "float": [selection(line, 100.0)],
        "boolean": [selection(line, True)],
        "extra": [{**selection(line, 100), "approved_due_date": "2027-01-01"}],
        "duplicate": [
            selection(line, 50),
            {**selection(line, 50), "source_id": str(line).upper()},
        ],
        "wrong_total": [selection(line, 99)],
        "other_source": [selection(uuid4(), 100)],
    }
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            preview(due_connection, line, 100, cases[case])
    assert error.value.sqlstate == ("P4508" if case == "other_source" else "P4502")
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 80000


def test_due_application_legacy_missing_date_blocks_without_inventing_parts(
    legacy_due_connection: DB,
) -> None:
    context = source(legacy_due_connection)
    legacy_adjustment(legacy_due_connection, context, "DEBIT", 1000)
    before = upgrade_populated_due_history(legacy_due_connection)
    with pytest.raises(psycopg.Error, match="must be resolved") as error:
        with legacy_due_connection.transaction():
            preview(legacy_due_connection, context[-1], 100)
    assert error.value.sqlstate == "P4507"
    assert legacy_financial_snapshot(legacy_due_connection) == before
    assert legacy_due_connection.execute(
        "SELECT count(*) FROM app.invoice_due_source_parts"
    ).fetchone() == (0,)


def test_due_application_helper_is_invoker_and_not_a_direct_role_boundary(
    due_connection: DB,
) -> None:
    signature = "app.invoice_line_due_application_parts(uuid,bigint,timestamptz,jsonb,integer)"
    for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
        assert due_connection.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
        ).fetchone() == (False,)
    assert due_connection.execute(
        "SELECT prosecdef,provolatile FROM pg_proc WHERE oid=%s::regprocedure",
        (signature,),
    ).fetchone() == (False, "s")


def test_due_application_new_earlier_source_changes_fresh_preview(
    due_connection: DB,
) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    previous = preview(due_connection, line, 100)
    original_date = date.fromisoformat(cast(str, previous["parts"][0]["approved_due_date"]))
    debit = adjustment(
        due_connection,
        actor,
        prop,
        invoice,
        line,
        "DEBIT",
        100,
        original_date - timedelta(days=1),
    )
    current = preview(due_connection, line, 100)
    assert previous["parts"][0]["source_id"] == str(line)
    assert current["parts"][0]["source_id"] == str(debit)
    assert previous != current
