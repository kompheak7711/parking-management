"""Atomic dated application contracts; explicit preview transport remains separate."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from test_invoice_due_migration import (
    DB,
    adjustment,
    legacy_financial_snapshot,
    position,
    upgrade_populated_due_history,
)
from test_invoice_due_migration import due_connection as due_connection
from test_invoice_due_migration import legacy_due_connection as legacy_due_connection
from test_invoice_due_proposal_migration import Context, details, funds, proposal
from test_reservation_migration import migrated_database_url as migrated_database_url

KINDS = ["PAYMENT", "CREDIT"]


def post(
    connection: DB,
    kind: str,
    context: Context,
    money: UUID,
    intent: dict[str, Any],
    key: UUID | None = None,
) -> dict[str, Any]:
    actor, prop, _, _, _ = context
    identity = key or uuid4()
    if kind == "PAYMENT":
        digest = hashlib.sha256(
            json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row = connection.execute(
            "SELECT app.post_payment_allocations(%s,%s,%s,%s,%s,%s)",
            (prop, money, actor, identity, digest, Jsonb(intent)),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT app.post_credit_application(%s,%s,%s,%s,%s)",
            (prop, money, actor, identity, Jsonb(intent)),
        ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


def designated(
    connection: DB,
    kind: str,
    context: Context,
    amount: int,
    selected: list[dict[str, Any]] | None = None,
    *,
    legacy: bool = False,
) -> dict[str, Any]:
    _, _, _, invoice, line = context
    target: dict[str, Any] = {
        "invoice_id": str(invoice),
        "amount_usd_cents": amount,
        "details": [{"invoice_line_id": str(line), "amount_usd_cents": amount}],
    }
    if not legacy:
        row = connection.execute(
            "SELECT app.invoice_line_due_application_parts(%s,%s,clock_timestamp(),%s,500),"
            "(SELECT version FROM app.invoices WHERE id=%s)",
            (line, amount, Jsonb(selected) if selected is not None else None, invoice),
        ).fetchone()
        assert row is not None and isinstance(row[0], dict)
        target["invoice_version"] = row[1]
        target["details"][0]["due_attribution"] = {
            "basis": row[0]["basis"],
            "parts": row[0]["parts"],
        }
    return {
        "mode": "DESIGNATED",
        "designation_reference": "Synthetic confirmed Customer instruction",
        **({"targets": [target]} if kind == "PAYMENT" else target),
    }


def recorded(connection: DB, kind: str, line: UUID) -> list[tuple[object, ...]]:
    return connection.execute(
        "SELECT effect_id,source_kind,source_id,amount_usd_cents,part_sequence "
        "FROM app.invoice_due_recorded_parts(%s) WHERE effect_kind=%s ORDER BY part_sequence",
        (line, "PAYMENT_ALLOCATION" if kind == "PAYMENT" else "CUSTOMER_CREDIT_APPLICATION"),
    ).fetchall()


@pytest.mark.parametrize("kind", KINDS)
def test_due_posting_generated_parts_replay_and_reverse_as_one_transaction(
    due_connection: DB,
    kind: str,
) -> None:
    context, money = funds(due_connection, kind, 30000)
    actor, prop, _, invoice, line = context
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 10000, date(2027, 1, 1))
    selected = proposal(due_connection, kind, context, money, 30000)
    intent = {"mode": "PROPOSAL", "proposal": selected}
    key = uuid4()
    result = post(due_connection, kind, context, money, intent, key)
    parts = recorded(due_connection, kind, line)
    assert [(x[1], x[2], x[3], x[4]) for x in parts] == [
        ("DEBIT_ADJUSTMENT", debit, 10000, 1),
        ("ORIGINAL_LINE", line, 20000, 2),
    ]
    assert len({x[0] for x in parts}) == 1
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 60000
    before_replay = legacy_financial_snapshot(due_connection)
    assert post(due_connection, kind, context, money, intent, key) == result
    assert legacy_financial_snapshot(due_connection) == before_replay
    if kind == "PAYMENT":
        original = UUID(result["allocation_ids"][0])
        due_connection.execute(
            "SELECT app.reverse_payment_allocation_command(%s,%s,%s,%s,%s,%s)",
            (prop, original, actor, uuid4(), "f" * 64, "Reverse exact confirmed split"),
        )
    else:
        original = UUID(result["application"]["id"])
        due_connection.execute(
            "SELECT app.reverse_credit_application(%s,%s,%s,%s,%s)",
            (prop, original, actor, uuid4(), "Reverse exact confirmed split"),
        )
    assert recorded(due_connection, kind, line) == parts
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 90000


@pytest.mark.parametrize("kind", KINDS)
def test_due_posting_explicit_customer_source_choice_is_preserved(
    due_connection: DB, kind: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, prop, _, invoice, line = context
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 1000, date(2027, 3, 1))
    selected = [
        {"source_kind": "DEBIT_ADJUSTMENT", "source_id": str(debit), "amount_usd_cents": 100}
    ]
    intent = designated(due_connection, kind, context, 100, selected)
    post(due_connection, kind, context, money, intent)
    assert [(x[1], x[2], x[3]) for x in recorded(due_connection, kind, line)] == [
        ("DEBIT_ADJUSTMENT", debit, 100)
    ]
    assert {
        x["source_id"]: x["remaining_usd_cents"] for x in position(due_connection, line)["amounts"]
    } == {
        str(line): 80000,
        str(debit): 900,
    }


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "case", ["missing", "bad_date", "fractional", "wrong_source", "stale_balance", "wrong_basis"]
)
def test_due_posting_invalid_confirmation_rolls_back_all_financial_evidence(
    due_connection: DB,
    kind: str,
    case: str,
) -> None:
    context, money = funds(due_connection, kind, 100)
    intent = deepcopy(designated(due_connection, kind, context, 100))
    target = intent["targets"][0] if kind == "PAYMENT" else intent
    detail = target["details"][0]
    due = detail["due_attribution"]
    part = due["parts"][0]
    if case == "missing":
        del detail["due_attribution"]
    elif case == "bad_date":
        part["approved_due_date"] = "2020-01-01"
    elif case == "fractional":
        part["amount_usd_cents"] = 100.0
    elif case == "wrong_source":
        part["source_id"] = str(uuid4())
    elif case == "stale_balance":
        part["outstanding_usd_cents"] = 79999
    else:
        due["basis"] = "UNSUPPORTED"
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            post(due_connection, kind, context, money, intent)
    assert error.value.sqlstate in ({"P4902", "P4904"} if kind == "PAYMENT" else {"P5102", "P5104"})
    assert legacy_financial_snapshot(due_connection) == before
    assert recorded(due_connection, kind, context[-1]) == []


@pytest.mark.parametrize("kind", KINDS)
def test_due_posting_legacy_saved_reply_survives_without_backfill(
    legacy_due_connection: DB,
    kind: str,
) -> None:
    context, money = funds(legacy_due_connection, kind, 30000)
    intent = designated(legacy_due_connection, kind, context, 10000, legacy=True)
    key = uuid4()
    old = post(legacy_due_connection, kind, context, money, intent, key)
    before = upgrade_populated_due_history(legacy_due_connection)
    assert post(legacy_due_connection, kind, context, money, intent, key) == old
    assert legacy_financial_snapshot(legacy_due_connection) == before
    with pytest.raises(psycopg.Error, match="version") as error:
        with legacy_due_connection.transaction():
            post(legacy_due_connection, kind, context, money, intent)
    assert error.value.sqlstate == ("P4904" if kind == "PAYMENT" else "P5104")
    assert legacy_financial_snapshot(legacy_due_connection) == before
    assert recorded(legacy_due_connection, kind, context[-1]) == []


@pytest.mark.parametrize("kind", KINDS)
def test_due_posting_direct_writer_cannot_omit_atomic_source_parts(
    due_connection: DB, kind: str
) -> None:
    context, money = funds(due_connection, kind, 100)
    actor, _, customer, invoice, line = context
    header = uuid4()
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.errors.CheckViolation, match="atomic dated parts"):
        with due_connection.transaction():
            due_connection.execute("SET CONSTRAINTS ALL DEFERRED")
            if kind == "PAYMENT":
                due_connection.execute(
                    "INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,"
                    "target_kind,invoice_id,"
                    "amount_usd_cents,between_invoice_basis,within_invoice_basis,"
                    "customer_designation_reference,"
                    "posted_at,posted_by,authorization_reference) VALUES(%s,%s,%s,'INVOICE',%s,100,"
                    "'CUSTOMER_DESIGNATED','CUSTOMER_DESIGNATED','Synthetic designation',"
                    "clock_timestamp(),%s,'payments.allocate')",
                    (header, money, customer, invoice, actor),
                )
                due_connection.execute(
                    "INSERT INTO app.payment_allocation_details(id,payment_allocation_id,"
                    "invoice_line_id,"
                    "obligation_kind,invoice_line_category_snapshot,"
                    "posted_amount_usd_cents,attribution_basis,"
                    "detail_sequence,calculation_trace) VALUES(%s,%s,%s,'INVOICE_LINE','RENT',100,"
                    "'CUSTOMER_DESIGNATED',1,'{}')",
                    (uuid4(), header, line),
                )
            else:
                due_connection.execute(
                    "INSERT INTO app.customer_credit_applications(id,customer_credit_id,"
                    "target_kind,invoice_id,"
                    "amount_usd_cents,within_invoice_basis,customer_designation_reference,"
                    "occurred_at,actor_id,"
                    "authorization_reference) VALUES(%s,%s,'INVOICE',%s,100,'CUSTOMER_DESIGNATED',"
                    "'Synthetic designation',clock_timestamp(),%s,'credits.apply')",
                    (header, money, invoice, actor),
                )
                due_connection.execute(
                    "INSERT INTO app.customer_credit_application_details(id,"
                    "customer_credit_application_id,invoice_line_id,"
                    "obligation_kind,invoice_line_category_snapshot,"
                    "applied_amount_usd_cents,attribution_basis,"
                    "detail_sequence,calculation_trace) VALUES(%s,%s,%s,'INVOICE_LINE','RENT',100,"
                    "'CUSTOMER_DESIGNATED',1,'{}')",
                    (uuid4(), header, line),
                )
            due_connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert legacy_financial_snapshot(due_connection) == before
    assert recorded(due_connection, kind, line) == []


@pytest.mark.parametrize("kind", KINDS)
def test_due_posting_concurrent_confirmations_use_existing_lock_and_statement_limits(
    due_connection: DB,
    kind: str,
) -> None:
    context, money = funds(due_connection, kind, 200 if kind == "CREDIT" else 100)
    due_connection.commit()
    selected = proposal(due_connection, kind, context, money, 100)
    barrier = Barrier(2)

    def attempt() -> str:
        try:
            with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as connection:
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                barrier.wait(timeout=5)
                post(connection, kind, context, money, {"mode": "PROPOSAL", "proposal": selected})
            return "posted"
        except psycopg.Error as error:
            return error.sqlstate or "unknown"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt) for _ in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == sorted(["posted", "P4904" if kind == "PAYMENT" else "P5104"])
    assert len(recorded(due_connection, kind, context[-1])) == 1
    assert position(due_connection, context[-1])["aggregate_outstanding_usd_cents"] == 79900
    if kind == "CREDIT":
        assert due_connection.execute(
            "SELECT app.credit_available_value(%s)", (money,)
        ).fetchone() == (100,)


@pytest.mark.parametrize("kind", KINDS)
def test_due_posting_full_part_batch_respects_existing_statement_deadline(
    due_connection: DB,
    kind: str,
) -> None:
    context, money = funds(due_connection, kind, 500)
    actor, prop, _, invoice, line = context
    debits = [
        adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 1, date(2027, 1, 1))
        for _ in range(500)
    ]
    selected = proposal(due_connection, kind, context, money, 500)
    assert len(details(selected, kind)[0]["due_attribution"]["parts"]) == 500
    due_connection.execute("SET LOCAL lock_timeout='3000ms'")
    due_connection.execute("SET LOCAL statement_timeout='5000ms'")
    post(due_connection, kind, context, money, {"mode": "PROPOSAL", "proposal": selected})
    parts = recorded(due_connection, kind, line)
    assert len(parts) == 500 and [row[2] for row in parts] == debits
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 80000


def test_due_posting_commands_retain_grants_and_private_guards_are_not_exposed(
    due_connection: DB,
) -> None:
    for signature in (
        "app.post_payment_allocations(uuid,uuid,uuid,uuid,text,jsonb)",
        "app.post_credit_application(uuid,uuid,uuid,uuid,jsonb)",
    ):
        for role, expected in (
            ("prm_financial", True),
            ("prm_runtime", False),
            ("prm_bootstrap", False),
        ):
            assert due_connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
            ).fetchone() == (expected,)
    for signature in (
        "app.invoice_due_confirmed_parts(uuid,bigint,timestamptz,jsonb,boolean)",
        "app.validate_new_invoice_application_due()",
    ):
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            assert due_connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
            ).fetchone() == (False,)


@pytest.mark.parametrize(
    "case", ["valid_reverse", "overapplied_reverse", "incomplete_flush", "late_extra"]
)
def test_due_part_projection_checks_cannot_be_skipped_by_insert_order(
    due_connection: DB, case: str
) -> None:
    context, _ = funds(due_connection, "PAYMENT", 1)
    actor, prop, _, invoice, line = context
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 20000, date(2027, 3, 1))
    parent = uuid4()
    before = legacy_financial_snapshot(due_connection)

    def insert_part(source: UUID | None, amount: int, sequence: int) -> None:
        due_connection.execute(
            "INSERT INTO app.invoice_due_source_parts(id,invoice_line_id,debit_adjustment_id,"
            "credit_adjustment_id,amount_usd_cents,part_sequence) VALUES(%s,%s,%s,%s,%s,%s)",
            (uuid4(), line, source, parent, amount, sequence),
        )

    def write_parts() -> None:
        due_connection.execute("SET CONSTRAINTS ALL DEFERRED")
        due_connection.execute(
            "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
            "amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
            "authorization_reference) "
            "VALUES(%s,%s,%s,'CREDIT',50000,%s,'Synthetic projection-order regression',"
            "clock_timestamp(),%s,'invoices.adjust')",
            (parent, invoice, line, f"synthetic-projection:{parent}", actor),
        )
        if case == "late_extra":
            insert_part(None, 50000, 1)
            due_connection.execute(
                "SET CONSTRAINTS app.invoice_due_source_parts_complete IMMEDIATE"
            )
            due_connection.execute("SET CONSTRAINTS app.invoice_due_source_parts_complete DEFERRED")
            insert_part(debit, 1, 2)
        else:
            insert_part(debit, 30000 if case == "overapplied_reverse" else 10000, 2)
            if case != "incomplete_flush":
                insert_part(None, 20000 if case == "overapplied_reverse" else 40000, 1)
        # Exercise the part trigger before the independent parent completeness trigger.
        due_connection.execute("SET CONSTRAINTS app.invoice_due_source_parts_complete IMMEDIATE")
        due_connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

    if case == "valid_reverse":
        with due_connection.transaction():
            write_parts()
        actual = position(due_connection, line)
        assert actual["aggregate_outstanding_usd_cents"] == 50000
        assert {x["source_id"]: x["remaining_usd_cents"] for x in actual["amounts"]} == {
            str(line): 40000,
            str(debit): 10000,
        }
    else:
        with (
            pytest.raises(
                psycopg.errors.CheckViolation, match=r"invalid source balance|complete amount"
            ),
            due_connection.transaction(),
        ):
            write_parts()
        assert legacy_financial_snapshot(due_connection) == before
        assert due_connection.execute(
            "SELECT count(*) FROM app.invoice_due_source_parts WHERE credit_adjustment_id=%s",
            (parent,),
        ).fetchone() == (0,)
