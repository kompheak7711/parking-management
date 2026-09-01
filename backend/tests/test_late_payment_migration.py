"""Real PostgreSQL coverage for the V1-046 late-payment API boundary."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentConflictError,
    LatePaymentIdempotencyKeyReused,
    LatePaymentInvalidError,
    LatePaymentNotFoundError,
    PostgresLatePaymentService,
)
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    runtime_database_url,
    setup_signed_lease,
)
from test_migrations import _run_alembic, _temporary_migration_database


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    value = os.environ.get("MIGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("MIGRATION_DATABASE_URL is required")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def late_payment_actor(actor_id: UUID, property_id: UUID) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            CapabilityGrant(capability, scope)
            for capability in (
                "late_payment.review",
                "late_payment.final_decision",
                "late_payment.charge_correction",
            )
        ),
    )


def setup_invoice(
    connection: Connection[tuple[object, ...]],
    *,
    period_start: date,
    invoice_date: date | None = None,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    actor_id, property_id, customer_id, lease_id = setup_signed_lease(
        connection,
        start_date=date(2025, 1, 1),
        end_date=date(2027, 12, 31),
    )
    invoice_id, line_id = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=customer_id,
        lease_id=lease_id,
        period_start=period_start,
        invoice_date=invoice_date,
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.commit()
    return actor_id, property_id, customer_id, invoice_id, line_id


def service() -> PostgresLatePaymentService:
    return PostgresLatePaymentService(runtime_database_url(), financial_database_url())


def test_review_decisions_replay_and_source_isolation_use_authoritative_current_balance(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, invoice_id, line_id = setup_invoice(
        connection, period_start=date(2026, 5, 1)
    )
    connection.execute(
        "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
        "amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,%s,'CREDIT',48995,'paid-before-assessment',"
        "'Valid amount already applied',statement_timestamp(),%s,'invoices.adjust')",
        (uuid4(), invoice_id, line_id, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.commit()
    flow = service()
    actor = late_payment_actor(actor_id, property_id)
    before = flow._read("SELECT app.invoice_resource_snapshot(%s)", invoice_id)

    review = flow.review(invoice_id, actor=actor)
    assert review["property_timezone"] == "Asia/Phnom_Penh"
    assert review["eligible"] is True
    assert review["blocking_conditions"] == []
    assert review["overdue_balance"] == {"currency": "USD", "minor_units": 31_005}
    assert review["default_rate_basis_points"] == 1000
    assert review["calculated_default_amount"] == {
        "currency": "USD",
        "minor_units": 3_101,
    }
    assert connection.execute(
        "SELECT count(*) FROM app.late_payment_decisions WHERE source_invoice_id=%s",
        (invoice_id,),
    ).fetchone() == (0,)

    key = uuid4()
    reduced = FinalizeLatePaymentDecisionCommand(
        key, DecisionOutcome.REDUCED, 1_500, "Approved exact reduced amount"
    )
    result = flow.finalize_decision(property_id, invoice_id, reduced, actor=actor)
    replay = flow.finalize_decision(property_id, invoice_id, reduced, actor=actor)
    assert replay == result
    lease_row = connection.execute(
        "SELECT lease_id FROM app.invoices WHERE id=%s", (invoice_id,)
    ).fetchone()
    assert lease_row is not None
    assert result["event_type"] == "LATE_PAYMENT_DECISION"
    assert result["lease_id"] == str(lease_row[0])
    assert result["business_date"] == str(
        connection.execute(
            "SELECT timezone(property.timezone_name,decision.finalized_at)::date "
            "FROM app.late_payment_decisions AS decision "
            "JOIN app.invoices AS invoice ON invoice.id=decision.source_invoice_id "
            "JOIN app.leases AS lease ON lease.id=invoice.lease_id "
            "JOIN app.units AS unit ON unit.id=lease.unit_id "
            "JOIN app.properties AS property ON property.id=unit.property_id "
            "WHERE decision.id=%s",
            (UUID(str(result["id"])),),
        ).fetchone()[0]  # type: ignore[index]
    )
    assert set(result) == {
        "id",
        "event_type",
        "property_id",
        "customer_id",
        "lease_id",
        "business_date",
        "source_invoice",
        "overdue_balance_at_assessment",
        "default_rate_basis_points",
        "calculated_default_amount",
        "outcome",
        "approved_amount",
        "assessed_at",
        "finalized_at",
        "finalized_by",
        "reason",
        "authorization_reference",
        "calculation_evidence",
        "charge",
    }
    assert result["outcome"] == "REDUCED"
    assert result["approved_amount"] == {"currency": "USD", "minor_units": 1_500}
    charge_id = UUID(str(result["charge"]["id"]))  # type: ignore[index]
    charge = flow.get_charge(charge_id, actor=actor)
    assert charge["event_type"] == "LATE_PAYMENT_CHARGE"
    assert charge["lease_id"] == str(lease_row[0])
    assert charge["business_date"] == result["business_date"]
    assert set(charge) == {
        "id",
        "event_type",
        "property_id",
        "customer_id",
        "lease_id",
        "business_date",
        "source_invoice",
        "decision",
        "original_amount",
        "adjusted_obligation",
        "remaining_balance",
        "application_summary",
        "corrections",
        "payable_at",
        "created_at",
        "created_by",
    }
    assert charge["original_amount"] == {"currency": "USD", "minor_units": 1_500}
    assert charge["adjusted_obligation"] == charge["remaining_balance"]
    assert charge["application_summary"] == {
        "active_total": {"currency": "USD", "minor_units": 0},
        "payment_total": {"currency": "USD", "minor_units": 0},
        "credit_total": {"currency": "USD", "minor_units": 0},
        "items": [],
    }
    assert flow.get_decision(invoice_id, actor=actor) == result
    assert flow._read("SELECT app.invoice_resource_snapshot(%s)", invoice_id) == before
    assert connection.execute(
        "SELECT count(*),count(DISTINCT source_invoice_id) "
        "FROM app.late_payment_charges WHERE source_invoice_id=%s",
        (invoice_id,),
    ).fetchone() == (1, 1)
    assert connection.execute(
        "SELECT response_status,result_snapshot FROM app.late_payment_commands "
        "WHERE idempotency_key=%s",
        (key,),
    ).fetchone() == (201, result)

    with pytest.raises(LatePaymentIdempotencyKeyReused):
        flow.finalize_decision(
            property_id,
            invoice_id,
            FinalizeLatePaymentDecisionCommand(
                key, DecisionOutcome.REDUCED, 1_499, "Changed response after loss"
            ),
            actor=actor,
        )
    with pytest.raises(LatePaymentConflictError):
        flow.finalize_decision(
            property_id,
            invoice_id,
            FinalizeLatePaymentDecisionCommand(
                uuid4(), DecisionOutcome.REDUCED, 1_400, "Supplemental decision"
            ),
            actor=actor,
        )


def test_waiver_default_and_ineligible_boundaries_do_not_create_arbitrary_receivables(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, waived_invoice_id, _ = setup_invoice(
        connection, period_start=date(2026, 4, 1)
    )
    actor = late_payment_actor(actor_id, property_id)
    flow = service()
    waived = flow.finalize_decision(
        property_id,
        waived_invoice_id,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.WAIVED, 0, "Approved contractual waiver"
        ),
        actor=actor,
    )
    assert waived["outcome"] == "WAIVED"
    assert waived["charge"] is None
    assert connection.execute(
        "SELECT count(*) FROM app.late_payment_charges WHERE source_invoice_id=%s",
        (waived_invoice_id,),
    ).fetchone() == (0,)

    default_actor_id, default_property_id, _, default_invoice_id, _ = setup_invoice(
        connection, period_start=date(2026, 3, 1)
    )
    default_actor = late_payment_actor(default_actor_id, default_property_id)
    default_review = flow.review(default_invoice_id, actor=default_actor)
    default_amount = int(default_review["calculated_default_amount"]["minor_units"])  # type: ignore[index]
    confirmed = flow.finalize_decision(
        default_property_id,
        default_invoice_id,
        FinalizeLatePaymentDecisionCommand(
            uuid4(),
            DecisionOutcome.CONFIRMED_DEFAULT,
            default_amount,
            "Confirmed contractual default",
        ),
        actor=default_actor,
    )
    assert confirmed["outcome"] == "CONFIRMED_DEFAULT"
    with pytest.raises(LatePaymentNotFoundError):
        flow.finalize_decision(
            property_id,
            uuid4(),
            FinalizeLatePaymentDecisionCommand(
                uuid4(), DecisionOutcome.WAIVED, 0, "Hidden nonexistent source"
            ),
            actor=actor,
        )


def test_zero_rounded_confirmed_default_preserves_decision_without_charge(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, invoice_id, line_id = setup_invoice(
        connection, period_start=date(2026, 3, 1)
    )
    balance_row = connection.execute(
        "SELECT app.invoice_adjusted_line_obligation(%s)", (line_id,)
    ).fetchone()
    assert balance_row is not None
    assert isinstance(balance_row[0], int)
    adjustment_amount = balance_row[0] - 4
    assert adjustment_amount > 0
    connection.execute(
        "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
        "amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,%s,'CREDIT',%s,'four-cent-balance',"
        "'Leave exact eligible four-cent balance',statement_timestamp(),%s,'invoices.adjust')",
        (uuid4(), invoice_id, line_id, adjustment_amount, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.commit()
    flow = service()
    actor = late_payment_actor(actor_id, property_id)

    review = flow.review(invoice_id, actor=actor)
    assert review["eligible"] is True
    assert review["overdue_balance"] == {"currency": "USD", "minor_units": 4}
    assert review["calculated_default_amount"] == {
        "currency": "USD",
        "minor_units": 0,
    }
    key = uuid4()
    command = FinalizeLatePaymentDecisionCommand(
        key,
        DecisionOutcome.CONFIRMED_DEFAULT,
        0,
        "Confirm exact zero-rounded default",
    )
    result = flow.finalize_decision(property_id, invoice_id, command, actor=actor)

    assert flow.finalize_decision(property_id, invoice_id, command, actor=actor) == result
    assert result["outcome"] == "CONFIRMED_DEFAULT"
    assert result["approved_amount"] == {"currency": "USD", "minor_units": 0}
    assert result["charge"] is None
    assert connection.execute(
        "SELECT decision_outcome,approved_amount_usd_cents,"
        "calculated_default_amount_usd_cents FROM app.late_payment_decisions "
        "WHERE source_invoice_id=%s",
        (invoice_id,),
    ).fetchone() == ("CONFIRMED_DEFAULT", 0, 0)
    assert connection.execute(
        "SELECT count(*) FROM app.late_payment_charges WHERE source_invoice_id=%s",
        (invoice_id,),
    ).fetchone() == (0,)


def test_review_due_date_boundary_is_property_local_and_never_posts_automatically(
    connection: Connection[tuple[object, ...]],
) -> None:
    business_date_row = connection.execute(
        "SELECT timezone('Asia/Phnom_Penh',statement_timestamp())::date"
    ).fetchone()
    assert business_date_row is not None
    business_date = business_date_row[0]
    assert isinstance(business_date, date)
    next_month = (business_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    actor_id, property_id, _, invoice_id, _ = setup_invoice(
        connection,
        period_start=next_month,
        invoice_date=business_date,
    )
    actor = late_payment_actor(actor_id, property_id)
    flow = service()
    review = flow.review(invoice_id, actor=actor)
    assert review["business_date"] == business_date.isoformat()
    assert isinstance(review["source_due_date"], str)
    assert isinstance(review["business_date"], str)
    assert review["source_due_date"] > review["business_date"]
    assert review["eligible"] is False
    assert review["blocking_conditions"] == ["DUE_DATE_NOT_PASSED"]
    assert connection.execute(
        "SELECT count(*) FROM app.late_payment_decisions WHERE source_invoice_id=%s",
        (invoice_id,),
    ).fetchone() == (0,)
    with pytest.raises(LatePaymentConflictError):
        flow.finalize_decision(
            property_id,
            invoice_id,
            FinalizeLatePaymentDecisionCommand(
                uuid4(), DecisionOutcome.WAIVED, 0, "Due date has not passed"
            ),
            actor=actor,
        )


def test_corrections_preserve_original_history_bounds_and_future_application_boundary(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, invoice_id, _ = setup_invoice(
        connection, period_start=date(2026, 2, 1)
    )
    actor = late_payment_actor(actor_id, property_id)
    flow = service()
    decision = flow.finalize_decision(
        property_id,
        invoice_id,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.REDUCED, 1_500, "Approved reduced charge"
        ),
        actor=actor,
    )
    charge_id = UUID(str(decision["charge"]["id"]))  # type: ignore[index]
    reduction_key = uuid4()
    reduction_command = CorrectLatePaymentChargeCommand(
        reduction_key, CorrectionKind.REDUCTION, "Correct approved amount", 500
    )
    reduced = flow.correct_charge(property_id, charge_id, reduction_command, actor=actor)
    assert flow.correct_charge(property_id, charge_id, reduction_command, actor=actor) == reduced
    assert reduced["original_amount"] == {"currency": "USD", "minor_units": 1_500}
    assert reduced["adjusted_obligation"] == {"currency": "USD", "minor_units": 1_000}
    assert connection.execute(
        "SELECT response_status,result_snapshot FROM app.late_payment_commands "
        "WHERE idempotency_key=%s",
        (reduction_key,),
    ).fetchone() == (200, reduced)
    reduction_id = UUID(str(reduced["corrections"][0]["id"]))  # type: ignore[index]

    restored = flow.correct_charge(
        property_id,
        charge_id,
        CorrectLatePaymentChargeCommand(
            uuid4(),
            CorrectionKind.REDUCTION_REVERSAL,
            "Reverse the prior correction",
            reverses_correction_id=reduction_id,
        ),
        actor=actor,
    )
    assert restored["adjusted_obligation"] == {"currency": "USD", "minor_units": 1_500}
    with pytest.raises(LatePaymentConflictError):
        flow.correct_charge(
            property_id,
            charge_id,
            CorrectLatePaymentChargeCommand(
                uuid4(),
                CorrectionKind.REDUCTION_REVERSAL,
                "Cannot reverse twice",
                reverses_correction_id=reduction_id,
            ),
            actor=actor,
        )

    connection.execute(
        "CREATE OR REPLACE FUNCTION app.late_payment_charge_application_summary(p_charge_id uuid) "
        "RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ "
        "SELECT jsonb_build_object('active_total_usd_cents',1400,"
        "'payment_total_usd_cents',1400,'credit_total_usd_cents',0,'items','[]'::jsonb) $$"
    )
    position = connection.execute(
        "SELECT original_amount_usd_cents,reduction_usd_cents,"
        "reduction_reversal_usd_cents,active_reduction_usd_cents,"
        "charge_reversal_usd_cents,active_correction_effect_usd_cents,"
        "payment_applied_usd_cents,credit_applied_usd_cents,"
        "active_applications_usd_cents,adjusted_obligation_usd_cents,"
        "remaining_balance_usd_cents,source_invoice_id,late_payment_decision_id,"
        "customer_id,payable_at FROM app.late_payment_charge_financial_position "
        "WHERE late_payment_charge_id=%s",
        (charge_id,),
    ).fetchone()
    assert position is not None
    assert position[:-1] == (
        1_500,
        500,
        500,
        0,
        0,
        0,
        1_400,
        0,
        1_400,
        1_500,
        100,
        invoice_id,
        UUID(str(decision["id"])),
        UUID(str(decision["customer_id"])),
    )
    assert isinstance(position[-1], datetime)
    with pytest.raises(Error) as application_conflict:
        with connection.transaction():
            connection.execute(
                "SELECT app.correct_late_payment_charge(%s,%s,%s,%s,%s,'REDUCTION',200,NULL,"
                "'Would exceed active applications',%s,%s)",
                (
                    property_id,
                    charge_id,
                    actor_id,
                    uuid4(),
                    "a" * 64,
                    uuid4(),
                    uuid4(),
                ),
            ).fetchone()
    assert application_conflict.value.sqlstate == "P4608"
    connection.rollback()

    reversed_charge = flow.correct_charge(
        property_id,
        charge_id,
        CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.CHARGE_REVERSAL, "Reverse complete charge"
        ),
        actor=actor,
    )
    assert reversed_charge["original_amount"] == {"currency": "USD", "minor_units": 1_500}
    assert reversed_charge["adjusted_obligation"] == {"currency": "USD", "minor_units": 0}
    assert len(reversed_charge["corrections"]) == 3  # type: ignore[arg-type]
    assert connection.execute(
        "SELECT original_amount_usd_cents,reduction_usd_cents,"
        "reduction_reversal_usd_cents,active_reduction_usd_cents,"
        "charge_reversal_usd_cents,active_correction_effect_usd_cents,"
        "active_applications_usd_cents,adjusted_obligation_usd_cents,"
        "remaining_balance_usd_cents,correction_count "
        "FROM app.late_payment_charge_financial_position "
        "WHERE late_payment_charge_id=%s",
        (charge_id,),
    ).fetchone() == (1_500, 500, 500, 0, 1_500, 1_500, 0, 0, 0, 3)
    with pytest.raises(LatePaymentConflictError):
        flow.correct_charge(
            property_id,
            charge_id,
            CorrectLatePaymentChargeCommand(
                uuid4(), CorrectionKind.REDUCTION, "Terminal charge", 1
            ),
            actor=actor,
        )


def test_concurrent_decisions_and_over_reductions_commit_at_most_one_effect(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, invoice_id, _ = setup_invoice(
        connection, period_start=date(2026, 1, 1)
    )
    actor = late_payment_actor(actor_id, property_id)
    flow = service()

    def decide(index: int) -> str:
        try:
            flow.finalize_decision(
                property_id,
                invoice_id,
                FinalizeLatePaymentDecisionCommand(
                    uuid4(),
                    DecisionOutcome.REDUCED,
                    7_000 + index,
                    f"Concurrent decision {index}",
                ),
                actor=actor,
            )
            return "committed"
        except LatePaymentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, (1, 2)))
    assert sorted(outcomes) == ["committed", "conflict"]
    row = connection.execute(
        "SELECT charge.id FROM app.late_payment_charges AS charge "
        "WHERE charge.source_invoice_id=%s",
        (invoice_id,),
    ).fetchone()
    assert row is not None
    charge_id = row[0]
    assert isinstance(charge_id, UUID)

    def reduce(index: int) -> str:
        try:
            flow.correct_charge(
                property_id,
                charge_id,
                CorrectLatePaymentChargeCommand(
                    uuid4(), CorrectionKind.REDUCTION, f"Concurrent reduction {index}", 5_000
                ),
                actor=actor,
            )
            return "committed"
        except (LatePaymentConflictError, LatePaymentInvalidError):
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        correction_outcomes = list(pool.map(reduce, (1, 2)))
    assert sorted(correction_outcomes) == ["committed", "rejected"]
    assert connection.execute(
        "SELECT count(*) FROM app.late_payment_charge_corrections WHERE late_payment_charge_id=%s",
        (charge_id,),
    ).fetchone() == (1,)


def test_audit_failure_rolls_back_decision_charge_and_command(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, invoice_id, _ = setup_invoice(
        connection, period_start=date(2025, 12, 1)
    )
    existing_audit_id = connection.execute(
        "SELECT id FROM app.audit_events ORDER BY occurred_at,id LIMIT 1"
    ).fetchone()
    assert existing_audit_id is not None
    key = uuid4()
    with pytest.raises(Error) as collision:
        with connection.transaction():
            connection.execute(
                "SELECT app.finalize_late_payment_decision(%s,%s,%s,%s,%s,"
                "'WAIVED',0,'Audit collision rollback',%s,%s,%s)",
                (
                    property_id,
                    invoice_id,
                    actor_id,
                    key,
                    "b" * 64,
                    uuid4(),
                    uuid4(),
                    existing_audit_id[0],
                ),
            ).fetchone()
    assert collision.value.sqlstate == "23505"
    assert connection.execute(
        "SELECT count(*) FROM app.late_payment_decisions WHERE source_invoice_id=%s",
        (invoice_id,),
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.late_payment_commands WHERE idempotency_key=%s", (key,)
    ).fetchone() == (0,)


def test_late_payment_runtime_privileges_are_least_privilege_and_forward_only(
    connection: Connection[tuple[object, ...]],
) -> None:
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
        "20260831_37",
    )
    assert connection.execute(
        "SELECT has_table_privilege('prm_runtime','app.late_payment_commands','SELECT'),"
        "has_table_privilege('prm_runtime','app.late_payment_commands','INSERT'),"
        "has_table_privilege('prm_runtime',"
        "'app.late_payment_charge_financial_position','SELECT'),"
        "has_table_privilege('prm_runtime',"
        "'app.late_payment_charge_financial_position','INSERT'),"
        "has_table_privilege('prm_bootstrap',"
        "'app.late_payment_charge_financial_position','SELECT'),"
        "has_function_privilege('prm_runtime','app.late_payment_review_snapshot(uuid)','EXECUTE'),"
        "has_function_privilege('prm_runtime',"
        "'app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,bigint,text,uuid,uuid,uuid)',"
        "'EXECUTE'),has_function_privilege('prm_financial',"
        "'app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,bigint,text,uuid,uuid,uuid)',"
        "'EXECUTE')"
    ).fetchone() == (True, False, True, False, False, True, False, True)
    assert connection.execute(
        "SELECT reloptions FROM pg_catalog.pg_class "
        "WHERE oid='app.late_payment_charge_financial_position'::regclass"
    ).fetchone() == (["security_invoker=true"],)
    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "20260831_36")
    connection.rollback()


def test_revision_36_upgrades_to_late_payment_api_head() -> None:
    with _temporary_migration_database("prm_late_payment_upgrade") as migration_url:
        upgraded_36 = _run_alembic("upgrade", "20260831_36")
        assert upgraded_36.returncode == 0, upgraded_36.stderr
        with psycopg.connect(migration_url) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260831_36",
            )
            assert connection.execute(
                "SELECT count(*) FROM app.late_payment_decisions"
            ).fetchone() == (0,)
        upgraded_head = _run_alembic("upgrade", "head")
        assert upgraded_head.returncode == 0, upgraded_head.stderr
        with psycopg.connect(migration_url) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260831_37",
            )
            assert connection.execute(
                "SELECT count(*) FROM app.late_payment_commands"
            ).fetchone() == (0,)
