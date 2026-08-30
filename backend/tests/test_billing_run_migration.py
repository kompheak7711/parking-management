"""Real PostgreSQL exact-once and recovery coverage for V1-044."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from property_rental.billing_run import (
    BillingRunAuthorizationError,
    BillingRunCommand,
    PostgresBillingRunService,
    billing_run_request_digest,
    stable_billing_id,
)
from property_rental.billing_worker import ScheduledBillingWorker
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.utility import (
    UTILITY_CALCULATE_CAPABILITY,
    UTILITY_ESTIMATE_CAPABILITY,
    FinalizeActualConsumptionCommand,
    PostgresUtilityService,
)
from test_billing_service_migration import add_service, setup_billing_source
from test_invoice_migration import register_billing_service_principal
from test_utility_consumption_migration import (
    authorized_actor,
    committed_source,
    database_now,
    finalize_estimate,
    open_case,
    replace_failed_meter,
)
from test_utility_meter_migration import add_meter, add_rate, add_reading


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    value = os.environ.get("MIGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("MIGRATION_DATABASE_URL is required")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def financial_database_url() -> str:
    value = os.environ.get("FINANCIAL_DATABASE_URL")
    if value is None:
        pytest.skip("FINANCIAL_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def service_actor(actor_id: UUID, property_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant("billing.generate", frozenset({str(property_id)}))}
        ),
    )


def rent_source(
    database_url: str,
    *,
    period_start: date = date(2026, 9, 1),
    configure_service: bool = True,
) -> tuple[UUID, UUID, UUID, BillingRunCommand]:
    with psycopg.connect(database_url) as owner:
        human_actor_id, property_id, _, lease_id, _ = setup_billing_source(
            owner,
            configure_trash=False,
            configure_internet=False,
            move_in_date=date(2026, 4, 26),
        )
        if configure_service:
            approved_service = owner.execute(
                "SELECT service.id, approval.id "
                "FROM app.property_services AS service "
                "JOIN app.property_service_approval_periods AS approval "
                "ON approval.property_service_id=service.id "
                "WHERE service.property_id=%s AND service.service_code='TRASH_COLLECTION' "
                "AND approval.effective_from <= %s AND approval.effective_through >= %s "
                "ORDER BY approval.effective_from DESC LIMIT 1",
                (property_id, period_start, period_start),
            ).fetchone()
            if approved_service is None:
                add_service(
                    owner,
                    actor_id=human_actor_id,
                    property_id=property_id,
                    lease_id=lease_id,
                    code="TRASH_COLLECTION",
                    display_name="Trash Collection",
                    first_rate=1_000,
                    second_rate=1_200,
                )
            else:
                service_id, approval_id = approved_service
                owner.execute(
                    "INSERT INTO app.lease_service_terms("
                    "id,lease_id,property_service_id,applicable_from,applicable_through,"
                    "service_approval_period_id,terms_reference,recorded_at,recorded_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,statement_timestamp(),%s)",
                    (
                        uuid4(),
                        lease_id,
                        service_id,
                        date(2026, 7, 27),
                        date(2026, 12, 31),
                        approval_id,
                        f"LEASE-SCHEDULED-{lease_id}",
                        human_actor_id,
                    ),
                )
        worker_actor_id = register_billing_service_principal(
            owner, property_id=property_id, created_by=human_actor_id
        )
        owner.commit()
    return (
        worker_actor_id,
        property_id,
        lease_id,
        BillingRunCommand(
            property_id=property_id,
            run_kind="RENT",
            logical_run_key=f"rent/{period_start:%Y-%m}/{lease_id}",
            business_date=(period_start - timedelta(days=7)).replace(day=25),
            period_start=period_start,
            period_end=(period_start + timedelta(days=32)).replace(day=1) - timedelta(days=1),
            idempotency_key=uuid4(),
        ),
    )


def test_two_concurrent_workers_replay_one_rent_service_invoice(
    migrated_database_url: str,
) -> None:
    worker_actor_id, property_id, lease_id, _ = rent_source(migrated_database_url)
    workers = tuple(
        ScheduledBillingWorker(
            financial_database_url(),
            property_id=property_id,
            actor_id=worker_actor_id,
            max_catchup_runs=1,
        )
        for _ in range(2)
    )
    as_of = datetime(2026, 8, 31, 12, tzinfo=UTC)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda worker: worker.run_once(as_of=as_of),
                workers,
            )
        )
    completed = tuple(run for result in results for run in result.runs)
    replay = workers[0].run_once(as_of=as_of)

    assert len(completed) == 1
    assert completed[0].business_date == date(2026, 8, 25)
    assert len(completed[0].attempts) == 1
    target_items = tuple(
        item for item in completed[0].attempts[0].items if item.source_id == lease_id
    )
    assert [item.outcome for item in target_items] == ["GENERATED"]
    assert not replay.runs or {run.id for run in replay.runs} == {completed[0].id}
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.invoices WHERE lease_id=%s "
            "AND billing_period_start=DATE '2026-09-01' AND status<>'VOID'",
            (lease_id,),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT count(*) FROM app.audit_events WHERE correlation_id=%s AND entity_id=%s",
            (completed[0].correlation_id, target_items[0].invoice_id),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT array_agg(category ORDER BY line_sequence) FROM app.invoice_lines "
            "WHERE invoice_id=%s",
            (target_items[0].invoice_id,),
        ).fetchone() == (["RENT", "SERVICE_CHARGES"],)


def test_principal_recheck_and_after_commit_replay_are_idempotent(
    migrated_database_url: str,
) -> None:
    disabled_actor_id, property_id, lease_id, run_command = rent_source(
        migrated_database_url,
        period_start=date(2026, 7, 1),
        configure_service=False,
    )
    run_id = stable_billing_id(
        run_command.property_id,
        "/".join(
            (
                run_command.run_kind,
                run_command.logical_run_key,
                run_command.period_start.isoformat(),
                run_command.period_end.isoformat(),
            )
        ),
    )
    with psycopg.connect(migrated_database_url) as owner:
        human_actor_row = owner.execute(
            "SELECT created_by FROM app.billing_service_principals WHERE actor_id=%s",
            (disabled_actor_id,),
        ).fetchone()
        assert human_actor_row is not None
        human_actor_id = UUID(str(human_actor_row[0]))
        owner.execute(
            "UPDATE app.billing_service_principals SET lifecycle_state='disabled',"
            "disabled_at=statement_timestamp(),disabled_by=%s WHERE actor_id=%s",
            (human_actor_id, disabled_actor_id),
        )
        owner.commit()

    service = PostgresBillingRunService(financial_database_url())
    with pytest.raises(BillingRunAuthorizationError, match="not active"):
        service.execute(
            run_command,
            actor=service_actor(disabled_actor_id, property_id),
            invocation_source="SCHEDULED",
        )
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.billing_runs WHERE id=%s", (run_id,)
        ).fetchone() == (0,)
        active_actor_id = register_billing_service_principal(
            owner, property_id=property_id, created_by=human_actor_id
        )
        owner.commit()

    created = service.execute(
        run_command,
        actor=service_actor(active_actor_id, property_id),
        invocation_source="SCHEDULED",
    )
    replayed_after_lost_response = service.execute(
        run_command,
        actor=service_actor(active_actor_id, property_id),
        invocation_source="SCHEDULED",
    )

    assert created.id == replayed_after_lost_response.id
    assert created.attempts == replayed_after_lost_response.attempts[: len(created.attempts)]
    target_items = tuple(item for item in created.attempts[0].items if item.source_id == lease_id)
    assert [item.outcome for item in target_items] == ["GENERATED"]
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.invoices WHERE lease_id=%s "
            "AND billing_period_start=DATE '2026-07-01' AND status<>'VOID'",
            (lease_id,),
        ).fetchone() == (1,)


def test_audit_failure_rolls_back_invoice_and_retry_uses_new_attempt(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as owner:
        human_actor_id, property_id, _, lease_id, _ = setup_billing_source(
            owner,
            configure_trash=False,
            configure_internet=False,
            move_in_date=date(2026, 6, 1),
        )
        unit_row = owner.execute(
            "SELECT unit_id FROM app.leases WHERE id=%s", (lease_id,)
        ).fetchone()
        assert unit_row is not None
        unit_id = UUID(str(unit_row[0]))
        meter_id = add_meter(
            owner, actor_id=human_actor_id, unit_id=unit_id, installed_date=date(2026, 6, 1)
        )
        start_reading = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=meter_id,
            reading_date=date(2026, 6, 30),
            reading_value="100",
        )
        end_reading = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=meter_id,
            reading_date=date(2026, 7, 31),
            reading_value="150",
        )
        add_rate(
            owner,
            actor_id=human_actor_id,
            property_id=property_id,
            utility_type="ELECTRICITY",
            measurement_unit_code="KWH",
            effective_date=date(2026, 7, 30),
        )
        worker_actor_id = register_billing_service_principal(
            owner, property_id=property_id, created_by=human_actor_id
        )
        owner.commit()
    human_actor = AuthenticatedActor(
        actor_id=str(human_actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(UTILITY_CALCULATE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    period_id = uuid4()
    PostgresUtilityService(financial_database_url(), property_id, human_actor_id).finalize_actual(
        FinalizeActualConsumptionCommand(
            idempotency_key=uuid4(),
            consumption_period_id=period_id,
            unit_id=unit_id,
            utility_type="ELECTRICITY",
            start_reading_id=start_reading,
            end_reading_id=end_reading,
            finalized_at=database_now(),
        ),
        actor=human_actor,
    )
    run_command = BillingRunCommand(
        property_id=property_id,
        run_kind="UTILITIES",
        logical_run_key=f"utilities/2026-07/{period_id}",
        business_date=date(2026, 7, 31),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        idempotency_key=uuid4(),
    )
    actor = service_actor(worker_actor_id, property_id)
    digest = billing_run_request_digest(run_command, "SCHEDULED")
    run_id = stable_billing_id(
        run_command.property_id,
        "/".join(
            (
                run_command.run_kind,
                run_command.logical_run_key,
                run_command.period_start.isoformat(),
                run_command.period_end.isoformat(),
            )
        ),
    )
    correlation_id = stable_billing_id(run_id, "correlation")
    with psycopg.connect(financial_database_url()) as financial:
        started = financial.execute(
            "SELECT * FROM app.start_scheduled_billing_run(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                run_id,
                property_id,
                "UTILITIES",
                run_command.logical_run_key,
                run_command.business_date,
                run_command.period_start,
                run_command.period_end,
                run_command.idempotency_key,
                digest,
                worker_actor_id,
                correlation_id,
                "SCHEDULED",
            ),
        ).fetchone()
        financial.commit()
    assert started is not None
    attempt_id = UUID(str(started[1]))
    source_id: UUID
    with psycopg.connect(migrated_database_url) as owner:
        source_row = owner.execute(
            "SELECT source_id FROM app.billing_run_eligible_sources "
            "WHERE billing_run_id=%s AND source_kind='UTILITY_PERIOD'",
            (run_id,),
        ).fetchone()
        assert source_row is not None
        source_id = UUID(str(source_row[0]))
        audit_id = stable_billing_id(attempt_id, f"audit/UTILITY_PERIOD/{source_id}")
        owner.execute(
            "INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,"
            "entity_type,entity_id,reason,property_id,previous_state,correlation_id,"
            "source,outcome) "
            "VALUES (%s,statement_timestamp(),%s,%s,'injected.audit.collision','test',%s,"
            "'Injected audit collision',%s,'{}'::jsonb,%s,'SCHEDULED','FAILED')",
            (
                audit_id,
                run_command.business_date,
                worker_actor_id,
                uuid4(),
                property_id,
                uuid4(),
            ),
        )
        owner.commit()

    service = PostgresBillingRunService(financial_database_url())
    failed = service.execute(run_command, actor=actor, invocation_source="SCHEDULED")

    assert failed.status == "RETRYABLE"
    assert failed.attempts[0].items[0].diagnostic_code == "UTILITY_PERSISTENCE_23505"
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.invoices WHERE originating_billing_run_attempt_id=%s",
            (attempt_id,),
        ).fetchone() == (0,)

    recovered = service.execute(run_command, actor=actor, invocation_source="SCHEDULED")

    assert recovered.status == "SUCCEEDED"
    assert [attempt.outcome for attempt in recovered.attempts] == ["FAILED", "SUCCEEDED"]
    assert (
        sum(item.outcome == "GENERATED" for attempt in recovered.attempts for item in attempt.items)
        == 1
    )


def test_finalized_utility_issues_exact_rate_and_responsibility_evidence(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as owner:
        human_actor_id, property_id, _, lease_id, _ = setup_billing_source(
            owner,
            configure_trash=False,
            configure_internet=False,
            move_in_date=date(2026, 7, 1),
        )
        unit_row = owner.execute(
            "SELECT unit_id FROM app.leases WHERE id=%s", (lease_id,)
        ).fetchone()
        assert unit_row is not None
        unit_id = UUID(str(unit_row[0]))
        meter_id = add_meter(
            owner, actor_id=human_actor_id, unit_id=unit_id, installed_date=date(2026, 7, 1)
        )
        start_reading = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=meter_id,
            reading_date=date(2026, 7, 31),
            reading_value="100",
        )
        end_reading = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=meter_id,
            reading_date=date(2026, 8, 31),
            reading_value="223.456789",
        )
        rate_id = add_rate(
            owner,
            actor_id=human_actor_id,
            property_id=property_id,
            utility_type="ELECTRICITY",
            measurement_unit_code="KWH",
            effective_date=date(2026, 8, 30),
        )
        worker_actor_id = register_billing_service_principal(
            owner, property_id=property_id, created_by=human_actor_id
        )
        owner.commit()
    human_actor = AuthenticatedActor(
        actor_id=str(human_actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(UTILITY_CALCULATE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    period_id = uuid4()
    PostgresUtilityService(financial_database_url(), property_id, human_actor_id).finalize_actual(
        FinalizeActualConsumptionCommand(
            idempotency_key=uuid4(),
            consumption_period_id=period_id,
            unit_id=unit_id,
            utility_type="ELECTRICITY",
            start_reading_id=start_reading,
            end_reading_id=end_reading,
            finalized_at=database_now(),
        ),
        actor=human_actor,
    )
    run_command = BillingRunCommand(
        property_id=property_id,
        run_kind="UTILITIES",
        logical_run_key=f"utilities/2026-08/{period_id}",
        business_date=date(2026, 8, 31),
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        idempotency_key=uuid4(),
    )

    result = PostgresBillingRunService(financial_database_url()).execute(
        run_command,
        actor=service_actor(worker_actor_id, property_id),
        invocation_source="SCHEDULED",
    )

    assert result.status == "SUCCEEDED", result
    item = result.attempts[0].items[0]
    assert item.outcome == "GENERATED"
    assert item.source_evidence["calculation_kind"] == "ACTUAL"
    with psycopg.connect(migrated_database_url) as owner:
        line = owner.execute(
            "SELECT amount_usd_cents,quantity::text,utility_rate_id,"
            "calculation_trace->>'responsible_lease_id' "
            "FROM app.invoice_lines WHERE utility_consumption_period_id=%s",
            (period_id,),
        ).fetchone()
    assert line == (3086, "123.456789", rate_id, str(lease_id))


def test_completed_approved_estimate_issues_once_with_preserved_basis(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as owner:
        human_actor_id, property_id, _, lease_id, _ = setup_billing_source(
            owner,
            configure_trash=False,
            configure_internet=False,
            move_in_date=date(2026, 1, 1),
        )
        unit_row = owner.execute(
            "SELECT unit_id FROM app.leases WHERE id=%s", (lease_id,)
        ).fetchone()
        assert unit_row is not None
        unit_id = UUID(str(unit_row[0]))
        failed_meter_id = add_meter(
            owner,
            actor_id=human_actor_id,
            unit_id=unit_id,
            installed_date=date(2026, 1, 1),
        )
        start_reading = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=failed_meter_id,
            reading_date=date(2026, 1, 1),
            reading_value="100",
        )
        end_reading = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=failed_meter_id,
            reading_date=date(2026, 1, 31),
            reading_value="130",
        )
        rate_row = owner.execute(
            "SELECT id FROM app.utility_rates WHERE property_id=%s "
            "AND utility_type='ELECTRICITY' AND measurement_unit_code='KWH' "
            "AND effective_date<=DATE '2026-03-10' ORDER BY effective_date DESC LIMIT 1",
            (property_id,),
        ).fetchone()
        if rate_row is None:
            rate_id = add_rate(
                owner,
                actor_id=human_actor_id,
                property_id=property_id,
                utility_type="ELECTRICITY",
                measurement_unit_code="KWH",
                effective_date=date(2026, 2, 15),
            )
        else:
            rate_id = UUID(str(rate_row[0]))
        owner.commit()
    utility_actor = authorized_actor(
        human_actor_id,
        property_id,
        UTILITY_CALCULATE_CAPABILITY,
        UTILITY_ESTIMATE_CAPABILITY,
    )
    utility_service = PostgresUtilityService(financial_database_url(), property_id, human_actor_id)
    basis_period_id = uuid4()
    utility_service.finalize_actual(
        FinalizeActualConsumptionCommand(
            idempotency_key=uuid4(),
            consumption_period_id=basis_period_id,
            unit_id=unit_id,
            utility_type="ELECTRICITY",
            start_reading_id=start_reading,
            end_reading_id=end_reading,
            finalized_at=database_now(),
        ),
        actor=utility_actor,
    )
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=human_actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_meter_id,
        failure_date=date(2026, 3, 1),
        replacement_date=date(2026, 3, 11),
    )
    case_id, _ = open_case(utility_service, utility_actor, failed_meter_id, replacement_id)
    estimate_period_id, _ = finalize_estimate(utility_service, utility_actor, case_id)
    with psycopg.connect(migrated_database_url) as owner:
        period_row = owner.execute(
            "SELECT start_date,end_date FROM app.utility_consumption_periods WHERE id=%s",
            (estimate_period_id,),
        ).fetchone()
        assert period_row == (date(2026, 3, 1), date(2026, 3, 10))
        worker_actor_id = register_billing_service_principal(
            owner, property_id=property_id, created_by=human_actor_id
        )
        owner.commit()

    result = PostgresBillingRunService(financial_database_url()).execute(
        BillingRunCommand(
            property_id=property_id,
            run_kind="UTILITIES",
            logical_run_key=f"utilities/estimate/{estimate_period_id}",
            business_date=date(2026, 3, 10),
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 10),
            idempotency_key=uuid4(),
        ),
        actor=service_actor(worker_actor_id, property_id),
        invocation_source="SCHEDULED",
    )

    target_items = tuple(
        item for item in result.attempts[0].items if item.source_id == estimate_period_id
    )
    assert [(item.outcome, item.source_evidence["calculation_kind"]) for item in target_items] == [
        ("GENERATED", "BROKEN_METER_ESTIMATE")
    ]
    with psycopg.connect(migrated_database_url) as owner:
        line = owner.execute(
            "SELECT utility_rate_id,calculation_trace->'source_evidence'"
            "->'calculation_trace'->'basis_period_ids',"
            "calculation_trace->>'responsible_lease_id' "
            "FROM app.invoice_lines WHERE utility_consumption_period_id=%s",
            (estimate_period_id,),
        ).fetchone()
    assert line == (rate_id, [str(basis_period_id)], str(lease_id))


def test_pending_future_basis_is_preserved_without_utility_invoice(
    migrated_database_url: str,
) -> None:
    human_actor_id, property_id, unit_id, failed_meter_id, _ = committed_source(
        migrated_database_url, ()
    )
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=human_actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_meter_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    utility_actor = authorized_actor(
        human_actor_id,
        property_id,
        UTILITY_CALCULATE_CAPABILITY,
        UTILITY_ESTIMATE_CAPABILITY,
    )
    case_id, _ = open_case(
        PostgresUtilityService(financial_database_url(), property_id, human_actor_id),
        utility_actor,
        failed_meter_id,
        replacement_id,
    )
    with psycopg.connect(migrated_database_url) as owner:
        period_row = owner.execute(
            "SELECT unmeasured_start_date,unmeasured_end_date "
            "FROM app.broken_meter_estimation_cases WHERE id=%s",
            (case_id,),
        ).fetchone()
        assert period_row is not None
        worker_actor_id = register_billing_service_principal(
            owner, property_id=property_id, created_by=human_actor_id
        )
        owner.commit()
    period_start = period_row[0]
    period_end = period_row[1]
    assert isinstance(period_start, date)
    assert isinstance(period_end, date)
    result = PostgresBillingRunService(financial_database_url()).execute(
        BillingRunCommand(
            property_id=property_id,
            run_kind="UTILITIES",
            logical_run_key=f"utilities/pending/{case_id}",
            business_date=period_end,
            period_start=period_start,
            period_end=period_end,
            idempotency_key=uuid4(),
        ),
        actor=service_actor(worker_actor_id, property_id),
        invocation_source="SCHEDULED",
    )

    assert result.status in {"SUCCEEDED", "RETRYABLE"}
    assert len(result.attempts) == 1
    pending_items = tuple(item for item in result.attempts[0].items if item.source_id == case_id)
    assert [(item.outcome, item.diagnostic_code) for item in pending_items] == [
        ("SKIPPED", "PENDING_FUTURE_ACTUAL_BASIS")
    ]
    assert pending_items[0].invoice_id is None
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.invoices WHERE originating_billing_run_attempt_id=%s",
            (result.attempts[0].id,),
        ).fetchone() == (0,)
