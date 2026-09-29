"""Scoped read-only designation previews and their existing explicit posting boundary."""

import os
from copy import deepcopy
from datetime import date
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.late_payment import DecisionOutcome, FinalizeLatePaymentDecisionCommand
from test_credit_application_migration import source as credit_source
from test_invoice_due_migration import (
    DB,
    adjustment,
    legacy_adjustment,
    legacy_financial_snapshot,
    position,
    source,
    upgrade_populated_due_history,
)
from test_invoice_due_migration import due_connection as due_connection
from test_invoice_due_migration import legacy_due_connection as legacy_due_connection
from test_invoice_due_posting_migration import post, recorded
from test_invoice_due_proposal_migration import Context, funds
from test_invoice_migration import create_recurring_rent_invoice, runtime_database_url
from test_late_payment_migration import late_payment_actor, setup_invoice
from test_late_payment_migration import service as late_service
from test_reservation_migration import migrated_database_url as migrated_database_url

KINDS = ["PAYMENT", "CREDIT"]


def intent_for(kind: str, invoice: UUID, line: UUID, amount: int = 100) -> dict[str, Any]:
    target = {
        "invoice_id": str(invoice),
        "amount_usd_cents": amount,
        "details": [{"invoice_line_id": str(line), "amount_usd_cents": amount}],
    }
    base: dict[str, Any] = {
        "mode": "DESIGNATED",
        "designation_reference": "Synthetic Customer choice",
    }
    return base | ({"targets": [target]} if kind == "PAYMENT" else target)


def target_for(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], value["targets"][0] if kind == "PAYMENT" else value)


def preview(
    connection: DB, kind: str, context: Context, money: UUID, intent: dict[str, Any]
) -> dict[str, Any]:
    function = (
        "payment_allocation_designation_preview"
        if kind == "PAYMENT"
        else "credit_application_designation_preview"
    )
    actor, prop, _, _, _ = context
    row = connection.execute(
        f"SELECT app.{function}(%s,%s,%s,%s)", (prop, money, actor, Jsonb(intent))
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("explicit", [False, True])
def test_due_preview_is_read_only_and_prepared_intent_posts_exact_parts(
    due_connection: DB, kind: str, explicit: bool
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2027, 1, 1))
    intent = intent_for(kind, invoice, line)
    if explicit:
        target_for(kind, intent)["details"][0]["source_parts"] = [
            {"source_kind": "ORIGINAL_LINE", "source_id": str(line), "amount_usd_cents": 100}
        ]
    original = deepcopy(intent)
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    with psycopg.connect(runtime_database_url()) as runtime:
        runtime.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        runtime.execute("SET LOCAL lock_timeout='3000ms'")
        runtime.execute("SET LOCAL statement_timeout='5000ms'")
        value = preview(runtime, kind, context, money, intent)
    assert intent == original and legacy_financial_snapshot(due_connection) == before
    assert value["property_id"] == str(prop)
    assert value["payment_id" if kind == "PAYMENT" else "credit_id"] == str(money)
    assert value["available_usd_cents"] == value["amount_usd_cents"] == 100
    assert value["part_count"] == (1 if explicit else 2)
    prepared = value["intent"]
    assert target_for(kind, prepared)["invoice_version"] > 0
    parts = target_for(kind, prepared)["details"][0]["due_attribution"]["parts"]
    assert [(x["source_id"], x["amount_usd_cents"]) for x in parts] == (
        [(str(line), 100)] if explicit else [(str(debit), 50), (str(line), 50)]
    )
    assert recorded(due_connection, kind, line) == []
    post(due_connection, kind, context, money, prepared)
    assert [(str(x[2]), x[3]) for x in recorded(due_connection, kind, line)] == [
        (x["source_id"], x["amount_usd_cents"]) for x in parts
    ]
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 79950


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "case", ["mode", "reference", "unexpected", "fractional", "boolean", "extra_target", "empty"]
)
def test_due_preview_rejects_malformed_envelopes_without_writes(
    due_connection: DB, kind: str, case: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    intent = intent_for(kind, context[-2], context[-1])
    target = target_for(kind, intent)
    if case == "mode":
        intent["mode"] = "PROPOSAL"
    elif case == "reference":
        intent["designation_reference"] = " invalid "
    elif case == "unexpected":
        intent["unexpected"] = 1
    elif case in ("fractional", "boolean"):
        target["amount_usd_cents"] = 100.5 if case == "fractional" else True
    elif case == "extra_target":
        target["invoice_version"] = 1
    elif kind == "PAYMENT":
        intent["targets"] = []
    else:
        intent["details"] = []
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            preview(due_connection, kind, context, money, intent)
    assert error.value.sqlstate == ("P4902" if kind == "PAYMENT" else "P5102")
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["property", "source", "customer"])
def test_due_preview_enforces_source_property_and_customer_context(
    due_connection: DB, kind: str, case: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, customer, invoice, line = context
    if case == "property":
        context = actor, uuid4(), customer, invoice, line
    elif case == "source":
        money = uuid4()
    else:
        other = uuid4()
        due_connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Unrelated preview Customer',%s,%s)",
            (other, actor, actor),
        )
        assert other != customer
        assert due_connection.execute(
            "SELECT count(*) FROM app.invoices WHERE customer_id=%s", (other,)
        ).fetchone() == (0,)
        money = seed_payment(
            due_connection, actor_id=actor, property_id=prop, customer_id=other, amount=100
        )
        if kind == "CREDIT":
            row = due_connection.execute(
                "SELECT app.recognize_customer_credit(%s,%s,%s,%s,100,%s,%s)",
                (prop, money, actor, uuid4(), "Synthetic Customer authority", "True excess"),
            ).fetchone()
            assert row is not None and isinstance(row[0], dict)
            money = UUID(row[0]["credit"]["id"])
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            preview(due_connection, kind, context, money, intent_for(kind, invoice, line))
    assert error.value.sqlstate == ("P4901" if kind == "PAYMENT" else "P5101")
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["unknown", "disabled"])
def test_due_preview_requires_fresh_active_human(due_connection: DB, kind: str, case: str) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, customer, invoice, line = context
    if case == "unknown":
        context = uuid4(), prop, customer, invoice, line
    else:
        due_connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (actor,)
        )
    with pytest.raises(psycopg.Error, match="active human") as error:
        with due_connection.transaction():
            preview(due_connection, kind, context, money, intent_for(kind, invoice, line))
    assert error.value.sqlstate == "P4506"


@pytest.mark.parametrize("kind", KINDS)
def test_due_preview_stale_confirmation_cannot_post(due_connection: DB, kind: str) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    value = preview(due_connection, kind, context, money, intent_for(kind, invoice, line))
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 100, date(2027, 1, 1))
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            post(due_connection, kind, context, money, value["intent"])
    assert error.value.sqlstate == ("P4904" if kind == "PAYMENT" else "P5104")
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
def test_due_preview_rejects_reversed_source(due_connection: DB, kind: str) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    if kind == "PAYMENT":
        due_connection.execute(
            "SELECT app.reverse_payment_command(%s,%s,%s,%s,%s,'RECEIVED',%s)",
            (prop, money, actor, uuid4(), "a" * 64, "Synthetic reversal"),
        )
    else:
        due_connection.execute(
            "SELECT app.reverse_customer_credit(%s,%s,%s,%s,%s)",
            (prop, money, actor, uuid4(), "Synthetic reversal"),
        )
    with pytest.raises(psycopg.Error, match="source changed") as error:
        with due_connection.transaction():
            preview(due_connection, kind, context, money, intent_for(kind, invoice, line))
    assert error.value.sqlstate == ("P4904" if kind == "PAYMENT" else "P5104")


@pytest.mark.parametrize("matching", [True, False])
def test_due_preview_third_party_stays_bound_to_identified_invoice(
    due_connection: DB, matching: bool
) -> None:
    context = source(due_connection)
    actor, prop, customer, invoice, line = context
    other_payer = source(due_connection)[2]
    lease_row = due_connection.execute(
        "SELECT lease_id FROM app.invoices WHERE id=%s", (invoice,)
    ).fetchone()
    assert lease_row is not None and isinstance(lease_row[0], UUID)
    other_invoice, other_line = create_recurring_rent_invoice(
        due_connection,
        actor_id=actor,
        customer_id=customer,
        lease_id=lease_row[0],
        period_start=date(2027, 3, 1),
    )
    money = seed_payment(
        due_connection,
        actor_id=actor,
        property_id=prop,
        customer_id=other_payer,
        amount=100,
        scope="THIRD_PARTY_IDENTIFIED",
        invoice_id=invoice,
    )
    intent = intent_for(
        "PAYMENT", invoice if matching else other_invoice, line if matching else other_line
    )
    if matching:
        value = preview(due_connection, "PAYMENT", context, money, intent)
        post(due_connection, "PAYMENT", context, money, value["intent"])
        assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 79900
    else:
        with pytest.raises(psycopg.Error, match="confirmed context") as error:
            with due_connection.transaction():
                preview(due_connection, "PAYMENT", context, money, intent)
        assert error.value.sqlstate == "P4901"


@pytest.mark.parametrize("kind", KINDS)
def test_due_preview_keeps_charge_separate_from_invoice(due_connection: DB, kind: str) -> None:
    if kind == "CREDIT":
        actor, prop, money, invoice, line, _ = credit_source(
            os.environ["MIGRATION_DATABASE_URL"], 100, period_start=date(2026, 5, 1)
        )
        row = due_connection.execute(
            "SELECT customer_id FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert row is not None and isinstance(row[0], UUID)
        customer = row[0]
    else:
        actor, prop, customer, invoice, line = setup_invoice(
            due_connection, period_start=date(2026, 5, 1)
        )
        money = seed_payment(
            due_connection, actor_id=actor, property_id=prop, customer_id=customer, amount=100
        )
        due_connection.commit()
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8000, "Synthetic confirmed Charge"
        ),
        actor=late_payment_actor(actor, prop),
    )
    row = due_connection.execute(
        "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", (invoice,)
    ).fetchone()
    assert row is not None and isinstance(row[0], UUID)
    charge = row[0]
    context: Context = actor, prop, customer, invoice, line
    target: dict[str, Any] = {"late_payment_charge_id": str(charge), "amount_usd_cents": 100}
    base: dict[str, Any] = {
        "mode": "DESIGNATED",
        "designation_reference": "Synthetic Charge choice",
    }
    intent = base | ({"targets": [target]} if kind == "PAYMENT" else target)
    before = legacy_financial_snapshot(due_connection)
    value = preview(due_connection, kind, context, money, intent)
    assert value["intent"] == intent and value["part_count"] == 0
    assert legacy_financial_snapshot(due_connection) == before
    post(due_connection, kind, context, money, value["intent"])
    assert recorded(due_connection, kind, line) == []
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 80000
    assert due_connection.execute(
        "SELECT remaining_balance_usd_cents FROM app.late_payment_charge_financial_position "
        "WHERE late_payment_charge_id=%s",
        (charge,),
    ).fetchone() == (7900,)


def test_due_preview_rejects_duplicate_payment_targets(due_connection: DB) -> None:
    context, money = funds(due_connection, "PAYMENT", 200)
    intent = intent_for("PAYMENT", context[-2], context[-1])
    intent["targets"] *= 2
    with pytest.raises(psycopg.Error, match="must be unique") as error:
        with due_connection.transaction():
            preview(due_connection, "PAYMENT", context, money, intent)
    assert error.value.sqlstate == "P4902"


def test_due_preview_grants_only_existing_read_service_roles(due_connection: DB) -> None:
    for name in (
        "payment_allocation_designation_preview",
        "credit_application_designation_preview",
    ):
        signature = f"app.{name}(uuid,uuid,uuid,jsonb)"
        for role, expected in (
            ("prm_runtime", True),
            ("prm_financial", True),
            ("prm_bootstrap", False),
        ):
            assert due_connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
            ).fetchone() == (expected,)
        assert due_connection.execute(
            "SELECT NOT EXISTS(SELECT 1 FROM pg_proc proc, LATERAL aclexplode(proc.proacl) acl "
            "WHERE proc.oid=%s::regprocedure AND acl.grantee=0)",
            (signature,),
        ).fetchone() == (True,)


@pytest.mark.parametrize("kind", KINDS)
def test_due_preview_unresolved_legacy_blocks_without_rewriting(
    legacy_due_connection: DB, kind: str
) -> None:
    context, money = funds(legacy_due_connection, kind, 100)
    legacy_adjustment(legacy_due_connection, context, "DEBIT", 100)
    before = upgrade_populated_due_history(legacy_due_connection)
    with pytest.raises(psycopg.Error, match="fresh resolved") as error:
        with legacy_due_connection.transaction():
            preview(
                legacy_due_connection,
                kind,
                context,
                money,
                intent_for(kind, context[-2], context[-1]),
            )
    assert error.value.sqlstate == ("P4904" if kind == "PAYMENT" else "P5104")
    assert legacy_financial_snapshot(legacy_due_connection) == before


@pytest.mark.parametrize("kind", KINDS)
def test_due_preview_exhausted_source_requires_refresh(due_connection: DB, kind: str) -> None:
    context, money = funds(due_connection, kind, 100)
    intent = intent_for(kind, context[-2], context[-1])
    prepared = preview(due_connection, kind, context, money, intent)
    post(due_connection, kind, context, money, prepared["intent"])
    with pytest.raises(psycopg.Error, match="source changed") as error:
        with due_connection.transaction():
            preview(due_connection, kind, context, money, intent)
    assert error.value.sqlstate == ("P4904" if kind == "PAYMENT" else "P5104")


def test_due_preview_part_limit_covers_entire_payment_designation(due_connection: DB) -> None:
    context, money = funds(due_connection, "PAYMENT", 600)
    actor, prop, customer, invoice, line = context
    for _ in range(499):
        adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 1, date(2027, 1, 1))
    row = due_connection.execute(
        "SELECT lease_id FROM app.invoices WHERE id=%s", (invoice,)
    ).fetchone()
    assert row is not None and isinstance(row[0], UUID)
    second, second_line = create_recurring_rent_invoice(
        due_connection,
        actor_id=actor,
        customer_id=customer,
        lease_id=row[0],
        period_start=date(2027, 3, 1),
    )
    intent = intent_for("PAYMENT", invoice, line, 500)
    intent["targets"].append(target_for("PAYMENT", intent_for("PAYMENT", second, second_line, 1)))
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error, match="part budget") as error:
        with due_connection.transaction():
            preview(due_connection, "PAYMENT", context, money, intent)
    assert error.value.sqlstate == "P4902"
    assert legacy_financial_snapshot(due_connection) == before
