"""Private read-only designation preparation; authorized HTTP preview remains pending."""

from datetime import date
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.billing import PostgresRentBillingService
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
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
from test_invoice_migration import financial_database_url
from test_reservation_migration import migrated_database_url as migrated_database_url


def preview(
    connection: DB, invoice: UUID, amount: int, details: object, maximum: int = 500
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT app.invoice_due_designated_details(%s,%s,%s,clock_timestamp(),%s)",
        (invoice, amount, Jsonb(details), maximum),
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


def selected(line: UUID, amount: int) -> dict[str, object]:
    return {"invoice_line_id": str(line), "amount_usd_cents": amount}


def test_due_designation_defaults_exact_line_amounts_without_writes(due_connection: DB) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    version = due_connection.execute(
        "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
    ).fetchone()
    assert version is not None
    due_connection.commit()
    due_connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    before = legacy_financial_snapshot(due_connection)
    value = preview(due_connection, invoice, 100, [selected(line, 100)])
    assert set(value) == {
        "invoice_id",
        "invoice_version",
        "amount_usd_cents",
        "details",
        "part_count",
    }
    assert value["invoice_id"] == str(invoice) and value["invoice_version"] == version[0]
    assert value["amount_usd_cents"] == 100 and value["part_count"] == 2
    due = value["details"][0]["due_attribution"]
    assert due["basis"] == "EARLIEST_DUE"
    assert [(x["source_id"], x["amount_usd_cents"]) for x in due["parts"]] == [
        (str(debit), 50),
        (str(line), 50),
    ]
    assert legacy_financial_snapshot(due_connection) == before
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_due_source_parts"
    ).fetchone() == (0,)


def test_due_designation_preserves_explicit_later_source(due_connection: DB) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 100, date(2027, 3, 1))
    detail = selected(line, 100)
    detail["source_parts"] = [
        {"source_kind": "DEBIT_ADJUSTMENT", "source_id": str(debit), "amount_usd_cents": 100}
    ]
    before = legacy_financial_snapshot(due_connection)
    value = preview(due_connection, invoice, 100, [detail])
    due = value["details"][0]["due_attribution"]
    assert due["basis"] == "CUSTOMER_DESIGNATED" and value["part_count"] == 1
    assert due["parts"][0]["source_id"] == str(debit)
    assert due["parts"][0]["approved_due_date"] == "2027-03-01"
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "object",
        "null",
        "unknown_field",
        "bad_uuid",
        "duplicate_line",
        "fractional",
        "boolean",
        "confirmation",
        "missing_amount",
        "null_selectors",
        "wrong_total",
    ],
)
def test_due_designation_rejects_invalid_selection_without_changes(
    due_connection: DB, case: str
) -> None:
    _, _, _, invoice, line = source(due_connection)
    detail = selected(line, 100)
    values: dict[str, object] = {
        "empty": [],
        "object": {},
        "null": None,
        "unknown_field": [detail | {"unexpected": 1}],
        "bad_uuid": [detail | {"invoice_line_id": "bad"}],
        "duplicate_line": [detail, detail],
        "fractional": [detail | {"amount_usd_cents": 100.5}],
        "boolean": [detail | {"amount_usd_cents": True}],
        "confirmation": [detail | {"due_attribution": {"basis": "EARLIEST_DUE", "parts": []}}],
        "missing_amount": [{"invoice_line_id": str(line)}],
        "null_selectors": [detail | {"source_parts": None}],
        "wrong_total": [selected(line, 99)],
    }
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            preview(due_connection, invoice, 100, values[case])
    assert error.value.sqlstate == "P4502"
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("maximum", [1, 2])
def test_due_designation_never_truncates_selected_line(due_connection: DB, maximum: int) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    if maximum == 1:
        with pytest.raises(psycopg.Error, match="complete designated line") as error:
            with due_connection.transaction():
                preview(due_connection, invoice, 100, [selected(line, 100)], maximum)
        assert error.value.sqlstate == "P4502"
    else:
        value = preview(due_connection, invoice, 100, [selected(line, 100)], maximum)
        assert value["amount_usd_cents"] == 100 and value["part_count"] == 2


def test_due_designation_rejects_line_from_another_invoice(due_connection: DB) -> None:
    _, _, _, invoice, _ = source(due_connection)
    _, _, _, _, foreign = source(due_connection)
    with pytest.raises(psycopg.Error, match="belong to the target") as error:
        with due_connection.transaction():
            preview(due_connection, invoice, 100, [selected(foreign, 100)])
    assert error.value.sqlstate == "P4502"


def test_due_designation_unresolved_legacy_requires_evidence(legacy_due_connection: DB) -> None:
    context = source(legacy_due_connection)
    legacy_adjustment(legacy_due_connection, context, "DEBIT", 100)
    before = upgrade_populated_due_history(legacy_due_connection)
    with pytest.raises(psycopg.Error, match="must be resolved") as error:
        with legacy_due_connection.transaction():
            preview(legacy_due_connection, context[-2], 1, [selected(context[-1], 1)])
    assert error.value.sqlstate == "P4507"
    assert legacy_financial_snapshot(legacy_due_connection) == before


def test_due_designation_builder_has_no_direct_runtime_grant(due_connection: DB) -> None:
    signature = "app.invoice_due_designated_details(uuid,bigint,jsonb,timestamptz,integer)"
    for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
        assert due_connection.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
        ).fetchone() == (False,)


def test_due_designation_missing_invoice_is_not_prepared(due_connection: DB) -> None:
    with pytest.raises(psycopg.Error, match="Invoice was not found") as error:
        with due_connection.transaction():
            preview(due_connection, uuid4(), 100, [selected(uuid4(), 100)])
    assert error.value.sqlstate == "P4501"


@pytest.mark.parametrize("maximum", [1, 2])
def test_due_designation_part_budget_spans_customer_ordered_lines(
    due_connection: DB, maximum: int
) -> None:
    actor, prop, _, lease, occupancy = setup_billing_source(due_connection)
    due_connection.commit()
    issued = PostgresRentBillingService(financial_database_url(), prop, actor).generate(
        initial_command(lease, occupancy), actor=authenticated(actor, prop)
    )
    rows = due_connection.execute(
        "SELECT id,category FROM app.invoice_lines WHERE invoice_id=%s", (issued.invoice_id,)
    ).fetchall()
    rent = cast(UUID, next(x[0] for x in rows if x[1] == "RENT"))
    service = cast(UUID, next(x[0] for x in rows if x[1] == "SERVICE_CHARGES"))
    choices = [selected(service, 100), selected(rent, 100)]
    if maximum == 1:
        with pytest.raises(psycopg.Error, match="complete designation") as error:
            with due_connection.transaction():
                preview(due_connection, issued.invoice_id, 200, choices, maximum)
        assert error.value.sqlstate == "P4502"
    else:
        value = preview(due_connection, issued.invoice_id, 200, choices, maximum)
        assert value["amount_usd_cents"] == 200 and value["part_count"] == 2
        assert [x["invoice_line_id"] for x in value["details"]] == [str(service), str(rent)]
