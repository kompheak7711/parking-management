"""Generated dated Payment/Credit proposal contracts; posting acceptance is separate."""

import json
from datetime import date, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.credit import ApplyCreditCommand
from property_rental.payment_allocation import PostAllocationsCommand
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
from test_invoice_due_migration import (
    DB,
    adjustment,
    legacy_adjustment,
    legacy_financial_snapshot,
    source,
    source_with_credit,
    upgrade_populated_due_history,
)
from test_invoice_due_migration import due_connection as due_connection
from test_invoice_due_migration import legacy_due_connection as legacy_due_connection
from test_invoice_migration import create_recurring_rent_invoice, financial_database_url
from test_reservation_migration import migrated_database_url as migrated_database_url

Context = tuple[UUID, UUID, UUID, UUID, UUID]
KINDS = ["PAYMENT", "CREDIT"]


def funds(connection: DB, kind: str, amount: int) -> tuple[Context, UUID]:
    if kind == "CREDIT":
        return source_with_credit(connection, amount)
    context = source(connection)
    actor, prop, customer, _, _ = context
    return context, seed_payment(
        connection, actor_id=actor, property_id=prop, customer_id=customer, amount=amount
    )


def proposal(
    connection: DB,
    kind: str,
    context: Context,
    money: UUID,
    amount: int,
    generated: datetime | None = None,
) -> dict[str, Any]:
    _, prop, _, invoice, _ = context
    if kind == "PAYMENT":
        row = connection.execute(
            "SELECT app.payment_allocation_proposal(%s,%s,COALESCE(%s,clock_timestamp()),%s)",
            (prop, money, generated, UUID(int=123)),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT app.credit_application_proposal(%s,%s,%s,%s,COALESCE(%s,clock_timestamp()))",
            (prop, money, invoice, amount, generated),
        ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


def details(value: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        value["targets"][0]["details"] if kind == "PAYMENT" else value["details"],
    )


@pytest.mark.parametrize("kind", KINDS)
def test_due_generated_proposals_expose_exact_dated_parts_without_posting(
    due_connection: DB,
    kind: str,
) -> None:
    context, money = funds(due_connection, kind, 30000)
    actor, prop, _, invoice, line = context
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 10000, date(2027, 1, 5))
    before = legacy_financial_snapshot(due_connection)
    value = proposal(due_connection, kind, context, money, 30000)
    rows = details(value, kind)
    assert len(rows) == 1 and rows[0]["amount_usd_cents"] == 30000
    due = rows[0]["due_attribution"]
    assert due["basis"] == "EARLIEST_DUE"
    assert [(x["source_id"], x["amount_usd_cents"]) for x in due["parts"]] == [
        (str(debit), 10000),
        (str(line), 20000),
    ]
    assert [x["approved_due_date"] for x in due["parts"]] == ["2027-01-05", "2027-02-05"]
    assert [x["outstanding_usd_cents"] for x in due["parts"]] == [10000, 80000]
    instant = datetime.fromisoformat(value["generated_at"])
    assert proposal(due_connection, kind, context, money, 30000, instant) == value
    intent: dict[str, object] = {"mode": "PROPOSAL", "proposal": value}
    captured = (
        PostAllocationsCommand(uuid4(), intent).intent
        if kind == "PAYMENT"
        else ApplyCreditCommand(uuid4(), intent).intent
    )
    assert captured == intent
    assert legacy_financial_snapshot(due_connection) == before
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_due_source_parts"
    ).fetchone() == (0,)


def test_due_generated_payment_keeps_invoice_fifo_before_debit_dates(due_connection: DB) -> None:
    context, money = funds(due_connection, "PAYMENT", 160000)
    actor, prop, customer, first, line = context
    row = due_connection.execute(
        "SELECT lease_id FROM app.invoices WHERE id=%s", (first,)
    ).fetchone()
    assert row is not None and isinstance(row[0], UUID)
    second, next_line = create_recurring_rent_invoice(
        due_connection,
        actor_id=actor,
        customer_id=customer,
        lease_id=row[0],
        period_start=date(2027, 3, 1),
    )
    debit = adjustment(
        due_connection, actor, prop, second, next_line, "DEBIT", 1000, date(2027, 1, 1)
    )
    value = proposal(due_connection, "PAYMENT", context, money, 160000)
    targets = value["targets"]
    assert [x["invoice_id"] for x in targets] == [str(first), str(second)]
    assert targets[0]["details"][0]["due_attribution"]["parts"][0]["source_id"] == str(line)
    assert targets[1]["details"][0]["due_attribution"]["parts"][0]["source_id"] == str(debit)
    assert [x["amount_usd_cents"] for x in targets] == [80000, 80000]


@pytest.mark.parametrize("kind", KINDS)
def test_due_generated_part_budget_is_batch_wide_and_stops_inside_line(
    due_connection: DB,
    kind: str,
) -> None:
    requested = 160500 if kind == "PAYMENT" else 80500
    context, money = funds(due_connection, kind, requested)
    actor, prop, customer, invoice, line = context
    if kind == "PAYMENT":
        row = due_connection.execute(
            "SELECT lease_id FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert row is not None and isinstance(row[0], UUID)
        invoice, line = create_recurring_rent_invoice(
            due_connection,
            actor_id=actor,
            customer_id=customer,
            lease_id=row[0],
            period_start=date(2027, 3, 1),
        )
    debits = [
        adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 1, date(2027, 1, 1))
        for _ in range(500)
    ]
    value = proposal(due_connection, kind, context, money, requested)
    rows = (
        [line_row for target in value["targets"] for line_row in target["details"]]
        if kind == "PAYMENT"
        else details(value, kind)
    )
    parts = [part for row in rows for part in row["due_attribution"]["parts"]]
    assert len(parts) == 500 and value["continuation_status"] == "MORE_ELIGIBLE"
    last = rows[-1]
    expected_count = 499 if kind == "PAYMENT" else 500
    assert [x["source_id"] for x in last["due_attribution"]["parts"]] == [
        str(x) for x in debits[:expected_count]
    ]
    assert last["amount_usd_cents"] == expected_count
    assert str(line) not in [x["source_id"] for x in last["due_attribution"]["parts"]]
    remaining = (
        value["unallocated_after_usd_cents"]
        if kind == "PAYMENT"
        else value["remaining_requested_usd_cents"]
    )
    assert remaining == requested - sum(x["amount_usd_cents"] for x in rows)
    bounded = value["targets"] if kind == "PAYMENT" else value["details"]
    assert len(json.dumps(bounded, ensure_ascii=False).encode()) < (
        200000 if kind == "PAYMENT" else 190000
    )
    assert value["continuation"] == "CONFIRM_PAGE_THEN_REQUEST_FRESH_PROPOSAL"


@pytest.mark.parametrize("kind", KINDS)
def test_due_generated_unresolved_legacy_blocks_instead_of_skipping(
    legacy_due_connection: DB,
    kind: str,
) -> None:
    context, money = funds(legacy_due_connection, kind, 100)
    legacy_adjustment(legacy_due_connection, context, "DEBIT", 1000)
    before = upgrade_populated_due_history(legacy_due_connection)
    with pytest.raises(psycopg.Error, match="fresh resolved") as error:
        with legacy_due_connection.transaction():
            proposal(legacy_due_connection, kind, context, money, 100)
    assert error.value.sqlstate == ("P4904" if kind == "PAYMENT" else "P5104")
    assert legacy_financial_snapshot(legacy_due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
def test_due_generated_original_freshness_guard_rejects_new_debit(
    due_connection: DB,
    kind: str,
) -> None:
    context, money = funds(due_connection, kind, 100)
    before = proposal(due_connection, kind, context, money, 100)
    actor, prop, _, invoice, line = context
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 100, date(2027, 1, 1))
    with pytest.raises(psycopg.Error, match="predates") as error:
        with due_connection.transaction():
            proposal(
                due_connection,
                kind,
                context,
                money,
                100,
                datetime.fromisoformat(before["generated_at"]),
            )
    assert error.value.sqlstate == ("P4904" if kind == "PAYMENT" else "P5104")


@pytest.mark.parametrize("kind", KINDS)
def test_due_generated_original_property_scope_remains_required(
    due_connection: DB, kind: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, _, customer, invoice, line = context
    with pytest.raises(psycopg.Error, match="not found") as error:
        with due_connection.transaction():
            proposal(due_connection, kind, (actor, uuid4(), customer, invoice, line), money, 100)
    assert error.value.sqlstate == ("P4901" if kind == "PAYMENT" else "P5101")


@pytest.mark.parametrize("kind", KINDS)
def test_due_generated_mixed_invoice_keeps_rent_before_earlier_service_debit(
    due_connection: DB,
    kind: str,
) -> None:
    actor, prop, customer, lease, occupancy = setup_billing_source(due_connection)
    money = seed_payment(
        due_connection, actor_id=actor, property_id=prop, customer_id=customer, amount=1000000
    )
    if kind == "CREDIT":
        row = due_connection.execute(
            "SELECT app.recognize_customer_credit(%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                money,
                actor,
                uuid4(),
                1000000,
                "Synthetic Customer authorization",
                "Before billing",
            ),
        ).fetchone()
        assert row is not None and isinstance(row[0], dict)
        money = UUID(row[0]["credit"]["id"])
    due_connection.commit()
    issued = PostgresRentBillingService(financial_database_url(), prop, actor).generate(
        initial_command(lease, occupancy), actor=authenticated(actor, prop)
    )
    line_rows = due_connection.execute(
        "SELECT line.id,line.category,invoice.due_date FROM app.invoice_lines line "
        "JOIN app.invoices invoice ON invoice.id=line.invoice_id WHERE invoice.id=%s "
        "ORDER BY line.line_sequence,line.id",
        (issued.invoice_id,),
    ).fetchall()
    rent = cast(UUID, next(x[0] for x in line_rows if x[1] == "RENT"))
    service_line = cast(UUID, next(x[0] for x in line_rows if x[1] == "SERVICE_CHARGES"))
    original_date = cast(date, line_rows[0][2])
    debit = adjustment(
        due_connection,
        actor,
        prop,
        issued.invoice_id,
        service_line,
        "DEBIT",
        100,
        original_date - timedelta(days=1),
    )
    context = (actor, prop, customer, issued.invoice_id, rent)
    # Payment's available amount is larger; both producers must still keep Rent first.
    value = proposal(due_connection, kind, context, money, issued.rent_usd_cents + 50)
    rows = details(value, kind)
    assert rows[0]["category"] == "RENT" and rows[0]["amount_usd_cents"] == issued.rent_usd_cents
    assert rows[1]["invoice_line_id"] == str(service_line)
    assert rows[1]["due_attribution"]["parts"][0]["source_id"] == str(debit)
    if kind == "CREDIT":
        assert rows[1]["amount_usd_cents"] == 50


def test_due_generated_producer_grants_are_unchanged(due_connection: DB) -> None:
    for signature, expected in (
        ("app.payment_allocation_proposal(uuid,uuid,timestamptz,uuid)", True),
        ("app.credit_application_proposal(uuid,uuid,uuid,bigint,timestamptz)", False),
    ):
        for role in ("prm_runtime", "prm_financial"):
            assert due_connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
            ).fetchone() == (expected,)
        assert due_connection.execute(
            "SELECT has_function_privilege('prm_bootstrap',%s,'EXECUTE')",
            (signature,),
        ).fetchone() == (False,)
