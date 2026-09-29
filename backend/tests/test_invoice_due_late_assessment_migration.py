"""Connected dated late-payment calculations preserve finality and history."""

from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from payment_test_support import seed_payment
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
from test_invoice_due_proposal_migration import Context
from test_invoice_migration import (
    create_recurring_rent_invoice,
    runtime_database_url,
    setup_signed_lease,
)
from test_reservation_migration import migrated_database_url as migrated_database_url


def past_source(connection: DB) -> Context:
    actor, prop, customer, lease = setup_signed_lease(
        connection, start_date=date(2025, 1, 1), end_date=date(2027, 12, 31)
    )
    invoice, line = create_recurring_rent_invoice(
        connection,
        actor_id=actor,
        customer_id=customer,
        lease_id=lease,
        period_start=date(2026, 3, 1),
    )
    return actor, prop, customer, invoice, line


def review(connection: DB, invoice: UUID) -> dict[str, Any]:
    row = connection.execute("SELECT app.late_payment_review_snapshot(%s)", (invoice,)).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


def finalize(
    connection: DB,
    context: Context,
    outcome: str,
    amount: int,
    key: UUID | None = None,
) -> dict[str, Any]:
    actor, prop, _, invoice, _ = context
    # Model the initially deferred decision guard of a fresh API transaction.
    # The command still forces every constraint immediate before returning.
    connection.execute("SET CONSTRAINTS app.late_payment_decisions_validate DEFERRED")
    row = connection.execute(
        "SELECT app.finalize_late_payment_decision(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            prop,
            invoice,
            actor,
            key or uuid4(),
            "d" * 64,
            "due-late-assessment",
            outcome,
            amount,
            "Synthetic authorized decision",
            uuid4(),
            uuid4(),
            uuid4(),
        ),
    ).fetchone()
    connection.execute("SET CONSTRAINTS app.late_payment_decisions_validate IMMEDIATE")
    assert row is not None and isinstance(row[0], dict)
    return row[0]


def credited_past_source(connection: DB) -> tuple[Context, UUID]:
    actor, prop, customer, lease = setup_signed_lease(
        connection, start_date=date(2025, 1, 1), end_date=date(2027, 12, 31)
    )
    payment = seed_payment(
        connection, actor_id=actor, property_id=prop, customer_id=customer, amount=50
    )
    row = connection.execute(
        "SELECT app.recognize_customer_credit(%s,%s,%s,%s,%s,%s,%s)",
        (
            prop,
            payment,
            actor,
            uuid4(),
            50,
            "Synthetic Customer authorization",
            "Test recognition",
        ),
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    invoice, line = create_recurring_rent_invoice(
        connection,
        actor_id=actor,
        customer_id=customer,
        lease_id=lease,
        period_start=date(2026, 3, 1),
    )
    return (actor, prop, customer, invoice, line), UUID(row[0]["credit"]["id"])


def mixed_dates(connection: DB, context: Context, past_amount: int = 5) -> None:
    actor, prop, _, invoice, line = context
    adjustment(connection, actor, prop, invoice, line, "DEBIT", past_amount, date(2026, 3, 5))
    adjustment(connection, actor, prop, invoice, line, "DEBIT", 100, date(2099, 1, 1))


@pytest.mark.parametrize("past_amount", [4, 5])
@pytest.mark.parametrize("outcome", ["CONFIRMED_DEFAULT", "REDUCED", "WAIVED"])
def test_due_late_assessment_excludes_future_dates_and_rounds_once(
    due_connection: DB, past_amount: int, outcome: str
) -> None:
    context = past_source(due_connection)
    mixed_dates(due_connection, context, past_amount)
    before = legacy_financial_snapshot(due_connection)
    value = review(due_connection, context[3])
    expected = (80000 + past_amount + 5) // 10
    assert value["eligible"] is True and value["blocking_conditions"] == []
    assert value["source_due_date"] == "2026-03-05"
    assert value["overdue_balance"] == {"currency": "USD", "minor_units": 80000 + past_amount}
    assert value["calculated_default_amount"] == {"currency": "USD", "minor_units": expected}
    assert value["due_attribution"]["not_overdue_balance_usd_cents"] == 100
    assert legacy_financial_snapshot(due_connection) == before
    approved = expected if outcome == "CONFIRMED_DEFAULT" else 100 if outcome == "REDUCED" else 0
    decision = finalize(due_connection, context, outcome, approved)["body"]["data"]
    evidence = decision["calculation_evidence"]
    assert decision["approved_amount"] == {"currency": "USD", "minor_units": approved}
    assert decision["source_invoice"]["due_date"] == "2026-03-05"
    assert decision["calculated_default_amount"]["minor_units"] == expected
    assert evidence["due_attribution"]["overdue_balance_usd_cents"] == 80000 + past_amount
    assert evidence["due_attribution"]["not_overdue_balance_usd_cents"] == 100
    assert evidence["due_attribution"]["as_of"] == decision["assessed_at"]
    assert evidence["assessment_business_date"] == evidence["due_attribution"]["business_date"]
    assert (decision["charge"] is None) == (outcome == "WAIVED")


def test_due_late_assessment_keeps_original_invoice_eligibility(due_connection: DB) -> None:
    context = source(due_connection)
    actor, prop, _, invoice, line = context
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2026, 3, 5))
    value = review(due_connection, invoice)
    assert value["overdue_balance"]["minor_units"] == 50
    assert value["eligible"] is False
    assert value["blocking_conditions"] == ["DUE_DATE_NOT_PASSED"]
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            finalize(due_connection, context, "WAIVED", 0)
    assert error.value.sqlstate == "P4603"
    assert legacy_financial_snapshot(due_connection) == before


def test_due_late_assessment_future_only_balance_is_ineligible(due_connection: DB) -> None:
    context = past_source(due_connection)
    actor, prop, _, invoice, line = context
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 100, date(2099, 1, 1))
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
    value = review(due_connection, invoice)
    assert value["due_attribution"]["aggregate_outstanding_usd_cents"] == 100
    assert value["overdue_balance"]["minor_units"] == 0
    assert value["calculated_default_amount"]["minor_units"] == 0
    assert value["eligible"] is False
    assert value["blocking_conditions"] == ["NO_REMAINING_BALANCE"]
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            finalize(due_connection, context, "WAIVED", 0)
    assert error.value.sqlstate == "P4603"


def test_due_late_assessment_legacy_unknown_blocks_without_fabricated_zero(
    legacy_due_connection: DB,
) -> None:
    context = past_source(legacy_due_connection)
    legacy_adjustment(legacy_due_connection, context, "DEBIT", 50)
    before = upgrade_populated_due_history(legacy_due_connection)
    value = review(legacy_due_connection, context[3])
    assert value["eligible"] is False
    assert value["blocking_conditions"] == ["DUE_ATTRIBUTION_UNRESOLVED"]
    assert value["overdue_balance"] is None and value["calculated_default_amount"] is None
    assert value["due_attribution"]["aggregate_outstanding_usd_cents"] == 80050
    assert value["due_attribution"]["unknown_line_count"] == 1
    with pytest.raises(psycopg.Error) as error:
        with legacy_due_connection.transaction():
            finalize(legacy_due_connection, context, "WAIVED", 0)
    assert error.value.sqlstate == "P4603"
    assert legacy_financial_snapshot(legacy_due_connection) == before


@pytest.mark.parametrize("outcome", ["CONFIRMED_DEFAULT", "WAIVED"])
def test_due_late_assessment_preserves_legacy_decision_and_receipt(
    legacy_due_connection: DB, outcome: str
) -> None:
    context = past_source(legacy_due_connection)
    key = uuid4()
    amount = 8000 if outcome == "CONFIRMED_DEFAULT" else 0
    original = finalize(legacy_due_connection, context, outcome, amount, key)
    assert "due_attribution" not in original["body"]["data"]["calculation_evidence"]
    before = upgrade_populated_due_history(legacy_due_connection)
    assert finalize(legacy_due_connection, context, outcome, amount, key) == original
    value = review(legacy_due_connection, context[3])
    assert value["blocking_conditions"] == ["FINAL_DECISION_EXISTS"]
    assert value["prior_decision"] == original["body"]["data"]
    assert legacy_financial_snapshot(legacy_due_connection) == before


def test_due_late_assessment_rejects_aggregate_derived_default(due_connection: DB) -> None:
    context = past_source(due_connection)
    mixed_dates(due_connection, context)
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            finalize(due_connection, context, "CONFIRMED_DEFAULT", 8011)
    assert error.value.sqlstate == "P4602"
    assert legacy_financial_snapshot(due_connection) == before


def test_due_late_assessment_deferred_guard_rejects_wrong_balance(due_connection: DB) -> None:
    context = past_source(due_connection)
    actor, _, customer, invoice, _ = context
    mixed_dates(due_connection, context)
    before = legacy_financial_snapshot(due_connection)
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            due_connection.execute("SET CONSTRAINTS ALL DEFERRED")
            due_connection.execute(
                "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
                "source_due_date,overdue_balance_at_assessment_usd_cents,default_rate_basis_points,"
                "calculated_default_amount_usd_cents,decision_outcome,approved_amount_usd_cents,"
                "assessed_at,finalized_at,finalized_by,reason,authorization_reference,"
                "calculation_trace) VALUES(%s,%s,%s,'2026-03-05',80105,1000,8011,'WAIVED',0,"
                "statement_timestamp(),statement_timestamp(),%s,'Synthetic guard test',"
                "'late_payment.final_decision','{}'::jsonb)",
                (uuid4(), invoice, customer, actor),
            )
            due_connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert error.value.sqlstate == "23514"
    assert "assessment snapshot is invalid" in str(error.value)
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("outcome", ["CONFIRMED_DEFAULT", "WAIVED"])
def test_due_late_assessment_new_debit_never_authorizes_second_decision(
    due_connection: DB, outcome: str
) -> None:
    context = past_source(due_connection)
    actor, prop, _, invoice, line = context
    key = uuid4()
    amount = 8000 if outcome == "CONFIRMED_DEFAULT" else 0
    first = finalize(due_connection, context, outcome, amount, key)
    adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 50, date(2026, 3, 5))
    before = legacy_financial_snapshot(due_connection)
    assert finalize(due_connection, context, outcome, amount, key) == first
    value = review(due_connection, invoice)
    assert value["overdue_balance"]["minor_units"] == 80050
    assert value["blocking_conditions"] == ["FINAL_DECISION_EXISTS"]
    with pytest.raises(psycopg.Error) as error:
        with due_connection.transaction():
            finalize(due_connection, context, "WAIVED", 0)
    assert error.value.sqlstate == "P4603"
    assert legacy_financial_snapshot(due_connection) == before


def test_due_late_assessment_runtime_read_only_preserves_private_grants(
    due_connection: DB, record_property: Callable[[str, object], None]
) -> None:
    context = past_source(due_connection)
    mixed_dates(due_connection, context)
    due_connection.commit()
    before = legacy_financial_snapshot(due_connection)
    with psycopg.connect(
        runtime_database_url(),
        connect_timeout=3,
        options="-c statement_timeout=5000 -c lock_timeout=3000",
    ) as reader:
        reader.read_only = True
        assert reader.info.dbname == due_connection.info.dbname
        assert reader.info.host == due_connection.info.host
        assert reader.info.port == due_connection.info.port
        row = reader.execute(
            "SELECT current_user,current_setting('transaction_read_only'),"
            "has_function_privilege(current_user,"
            "'app.invoice_due_overdue_position_at(uuid,timestamptz)','EXECUTE')"
        ).fetchone()
        assert row == ("prm_runtime", "on", False)
        assert review(reader, context[3])["overdue_balance"]["minor_units"] == 80005
        record_property(
            "due_late_runtime_read_only",
            {
                "role": row[0],
                "read_only": True,
                "private_execute": False,
                "actual_target_verified": True,
            },
        )
    assert legacy_financial_snapshot(due_connection) == before


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_due_late_assessment_designated_future_payment_preserves_overdue(
    due_connection: DB, kind: str
) -> None:
    if kind == "CREDIT":
        context, money = credited_past_source(due_connection)
    else:
        context = past_source(due_connection)
    actor, prop, customer, invoice, line = context
    debit = adjustment(due_connection, actor, prop, invoice, line, "DEBIT", 100, date(2099, 1, 1))
    if kind == "PAYMENT":
        money = seed_payment(
            due_connection, actor_id=actor, property_id=prop, customer_id=customer, amount=50
        )
    intent = intent_for(kind, invoice, line, 50)
    target = intent["targets"][0] if kind == "PAYMENT" else intent
    target["details"][0]["source_parts"] = [
        {"source_kind": "DEBIT_ADJUSTMENT", "source_id": str(debit), "amount_usd_cents": 50}
    ]
    prepared = preview(due_connection, kind, context, money, intent)
    post(due_connection, kind, context, money, prepared["intent"])
    value = review(due_connection, invoice)
    assert value["overdue_balance"]["minor_units"] == 80000
    assert value["due_attribution"]["aggregate_outstanding_usd_cents"] == 80050
    assert value["due_attribution"]["not_overdue_balance_usd_cents"] == 50
    decision = finalize(due_connection, context, "CONFIRMED_DEFAULT", 8000)["body"]["data"]
    assert decision["overdue_balance_at_assessment"]["minor_units"] == 80000
    assert decision["calculated_default_amount"]["minor_units"] == 8000
