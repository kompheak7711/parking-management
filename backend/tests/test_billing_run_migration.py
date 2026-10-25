"""Real PostgreSQL exact-once and recovery coverage for V1-044."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.billing_run import (
    BillingRunAuthorizationError,
    BillingRunCommand,
    BillingRunDetail,
    BillingRunUnavailable,
    PostgresBillingRunService,
    billing_run_request_digest,
    stable_billing_id,
)
from property_rental.billing_worker import ScheduledBillingWorker
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment_job import LateChargePassResult
from property_rental.utility import (
    UTILITY_CALCULATE_CAPABILITY,
    UTILITY_ESTIMATE_CAPABILITY,
    FinalizeActualConsumptionCommand,
    PostgresUtilityService,
)
from test_billing_service_migration import add_service, setup_billing_source
from test_invoice_migration import register_billing_service_principal
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_utility_consumption_migration import (
    authorized_actor,
    database_now,
    finalize_actual,
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


def fresh_rent_property(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    lease_count: int,
    move_in_date: date,
    configure_service: bool = True,
) -> tuple[UUID, UUID, tuple[UUID, ...], UUID | None]:
    human_row = connection.execute(
        "SELECT actor_id FROM app.user_accounts WHERE lifecycle_state='active' "
        "ORDER BY created_at,actor_id LIMIT 1"
    ).fetchone()
    assert human_row is not None
    human_actor_id = UUID(str(human_row[0]))
    property_row = connection.execute("SELECT id FROM app.properties").fetchone()
    assert property_row is not None
    property_id = UUID(str(property_row[0]))
    lease_ids: list[UUID] = []
    for index in range(lease_count):
        unit_id = uuid4()
        customer_id = uuid4()
        connection.execute(
            "INSERT INTO app.units(id,property_id,unit_number,floor,unit_type,status,"
            "created_by,updated_by) VALUES (%s,%s,%s,'1','ONE_BEDROOM','VACANT',%s,%s)",
            (
                unit_id,
                property_id,
                f"V1-044-{index}-{unit_id.hex[:8]}",
                human_actor_id,
                human_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) VALUES (%s,%s,%s,%s)",
            (
                customer_id,
                f"V1-044 Tenant {index}",
                human_actor_id,
                human_actor_id,
            ),
        )
        lease_id = create_draft(
            connection,
            actor_id=human_actor_id,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=move_in_date,
            end_date=date(move_in_date.year + 1, 6, 30),
        )
        sign_lease(connection, lease_id, human_actor_id)
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,"
            "updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                lease_id,
                customer_id,
                move_in_date,
                human_actor_id,
                human_actor_id,
            ),
        )
        lease_ids.append(lease_id)
    service_actor_id = (
        register_billing_service_principal(
            connection,
            property_id=property_id,
            created_by=human_actor_id,
        )
        if configure_service
        else None
    )
    connection.commit()
    return human_actor_id, property_id, tuple(lease_ids), service_actor_id


def rent_source(
    database_url: str,
    *,
    period_start: date = date(2026, 9, 1),
    configure_service: bool = True,
) -> tuple[UUID, UUID, UUID, BillingRunCommand]:
    with psycopg.connect(database_url) as owner:
        human_actor_id, property_id, unit_id, customer_id, _ = setup_sources(owner)
        lease_id = create_draft(
            owner,
            actor_id=human_actor_id,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=date(2026, 4, 26),
            end_date=date(2027, 6, 30),
        )
        sign_lease(owner, lease_id, human_actor_id)
        owner.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_at,"
            "created_by,updated_at,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                lease_id,
                customer_id,
                date(2026, 4, 26),
                datetime(2026, 4, 26, tzinfo=UTC),
                human_actor_id,
                datetime(2026, 4, 26, tzinfo=UTC),
                human_actor_id,
            ),
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


class NoLateCharges:
    """The late-payment pass is covered by its own tests; this one leaves the shared Property's
    Invoices alone."""

    def run(self, *, as_of: datetime) -> LateChargePassResult:
        return LateChargePassResult(as_of.date())


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
            late_charges=NoLateCharges(),
        )
        for _ in range(2)
    )
    as_of = datetime(2026, 8, 31, 12, tzinfo=UTC)
    expected_candidate = (
        date(2026, 8, 25),
        date(2026, 9, 1),
        date(2026, 9, 30),
        "RENT",
    )
    with psycopg.connect(financial_database_url()) as financial:
        candidates = financial.execute(
            "SELECT * FROM app.scheduled_billing_worker_candidates(%s,%s,%s,1)",
            (property_id, worker_actor_id, as_of),
        ).fetchall()
    assert candidates == [expected_candidate]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda worker: worker.run_once(as_of=as_of),
                workers,
            )
        )
    completed = tuple(run for result in results for run in result.runs)
    replay = workers[0].run_once(as_of=as_of)
    completed_rent = tuple(
        run
        for run in completed
        if (run.business_date, run.period_start, run.period_end, run.run_kind) == expected_candidate
    )
    replayed_rent = tuple(
        run
        for run in replay.runs
        if (run.business_date, run.period_start, run.period_end, run.run_kind) == expected_candidate
    )

    assert len(completed) == len(completed_rent) == 1
    rent_run = completed_rent[0]
    assert rent_run.run_kind == "RENT"
    assert rent_run.business_date == date(2026, 8, 25)
    assert rent_run.period_start == date(2026, 9, 1)
    assert rent_run.period_end == date(2026, 9, 30)
    assert len(rent_run.attempts) == 1
    target_items = tuple(item for item in rent_run.attempts[0].items if item.source_id == lease_id)
    assert [item.outcome for item in target_items] == ["GENERATED"]
    assert not replayed_rent or {run.id for run in replayed_rent} == {rent_run.id}
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.invoices WHERE lease_id=%s "
            "AND billing_period_start=DATE '2026-09-01' AND status<>'VOID'",
            (lease_id,),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT count(*) FROM app.audit_events WHERE correlation_id=%s AND entity_id=%s",
            (rent_run.correlation_id, target_items[0].invoice_id),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT array_agg(category ORDER BY line_sequence) FROM app.invoice_lines "
            "WHERE invoice_id=%s",
            (target_items[0].invoice_id,),
        ).fetchone() == (["RENT", "SERVICE_CHARGES"],)


def test_live_api_uses_human_requester_and_one_property_service_for_rent_and_utility(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as owner:
        human_actor_id, property_id, lease_ids, service_actor_id = fresh_rent_property(
            owner,
            lease_count=1,
            move_in_date=date(1899, 10, 26),
        )
        assert service_actor_id is not None
        lease_id = lease_ids[0]
        unit_row = owner.execute(
            "SELECT unit_id FROM app.leases WHERE id=%s",
            (lease_id,),
        ).fetchone()
        assert unit_row is not None
        unit_id = UUID(str(unit_row[0]))
        meter_id = add_meter(
            owner,
            actor_id=human_actor_id,
            unit_id=unit_id,
            installed_date=date(1899, 11, 1),
        )
        start_reading = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=meter_id,
            reading_date=date(1899, 11, 30),
            reading_value="100",
        )
        end_reading = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=meter_id,
            reading_date=date(1899, 12, 31),
            reading_value="140",
        )
        owner.execute(
            "INSERT INTO app.utility_rates(id,property_id,utility_type,measurement_unit_code,"
            "rate_usd_per_unit,effective_date,notice_at,notice_evidence,actor_id) VALUES "
            "(%s,%s,'ELECTRICITY','KWH',0.25,DATE '1899-12-01',"
            "TIMESTAMPTZ '1899-11-30 00:00:00+07','V1-044 isolated API proof',%s)",
            (uuid4(), property_id, human_actor_id),
        )
        owner.commit()
    rent_run = BillingRunCommand(
        property_id=property_id,
        run_kind="RENT",
        logical_run_key=f"rent/1900-01/{lease_id}",
        business_date=date(1899, 12, 25),
        period_start=date(1900, 1, 1),
        period_end=date(1900, 1, 31),
        idempotency_key=uuid4(),
    )
    utility_actor = authorized_actor(
        human_actor_id,
        property_id,
        UTILITY_CALCULATE_CAPABILITY,
    )
    utility_period_id = uuid4()
    PostgresUtilityService(financial_database_url(), property_id, human_actor_id).finalize_actual(
        FinalizeActualConsumptionCommand(
            idempotency_key=uuid4(),
            consumption_period_id=utility_period_id,
            unit_id=unit_id,
            utility_type="ELECTRICITY",
            start_reading_id=start_reading,
            end_reading_id=end_reading,
            finalized_at=database_now(),
        ),
        actor=utility_actor,
    )
    requester = AuthenticatedActor(
        actor_id=str(human_actor_id),
        capability_grants=frozenset(
            {CapabilityGrant("billing.generate", frozenset({str(property_id)}))}
        ),
    )
    client = TestClient(
        create_app(
            actor_resolver=lambda _: requester,
            billing_run_flow=PostgresBillingRunService(
                financial_database_url(),
                api_service_actor_id=service_actor_id,
            ),
        )
    )
    client.cookies.set("__Host-prm_csrf", "csrf")
    headers = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
    }
    rent_payload = {
        "logical_run_key": rent_run.logical_run_key,
        "business_date": rent_run.business_date.isoformat(),
        "period_start": rent_run.period_start.isoformat(),
        "period_end": rent_run.period_end.isoformat(),
    }
    utility_payload = {
        "logical_run_key": f"utilities/1899-12/{utility_period_id}",
        "business_date": "1899-12-31",
        "period_start": "1899-12-01",
        "period_end": "1899-12-31",
    }

    assert (
        client.post(
            f"/api/v1/properties/{property_id}/billing-runs/rent",
            json=rent_payload,
            headers={"Idempotency-Key": str(rent_run.idempotency_key)},
        ).status_code
        == 403
    )
    rent_headers = {**headers, "Idempotency-Key": str(rent_run.idempotency_key)}
    rent_created = client.post(
        f"/api/v1/properties/{property_id}/billing-runs/rent",
        json=rent_payload,
        headers=rent_headers,
    )
    rent_replay = client.post(
        f"/api/v1/properties/{property_id}/billing-runs/rent",
        json=rent_payload,
        headers=rent_headers,
    )
    rent_conflict = client.post(
        f"/api/v1/properties/{property_id}/billing-runs/rent",
        json={**rent_payload, "logical_run_key": f"{rent_run.logical_run_key}/changed"},
        headers=rent_headers,
    )
    utility_key = uuid4()
    utility_headers = {**headers, "Idempotency-Key": str(utility_key)}
    utility_created = client.post(
        f"/api/v1/properties/{property_id}/billing-runs/utilities",
        json=utility_payload,
        headers=utility_headers,
    )
    utility_replay = client.post(
        f"/api/v1/properties/{property_id}/billing-runs/utilities",
        json=utility_payload,
        headers=utility_headers,
    )
    utility_conflict = client.post(
        f"/api/v1/properties/{property_id}/billing-runs/utilities",
        json={
            **utility_payload,
            "logical_run_key": f"{utility_payload['logical_run_key']}/changed",
        },
        headers=utility_headers,
    )

    assert rent_created.status_code == rent_replay.status_code == 200, rent_created.text
    assert rent_conflict.status_code == 409
    assert utility_created.status_code == utility_replay.status_code == 200, utility_created.text
    assert utility_conflict.status_code == 409
    for response in (rent_created, utility_created):
        detail = client.get(f"/api/v1/billing-runs/{response.json()['data']['id']}")
        assert detail.status_code == 200
        assert detail.json()["data"]["requester_actor_id"] == str(human_actor_id)
        assert detail.json()["data"]["system_actor_id"] == str(service_actor_id)
        assert (
            detail.json()["data"]["requester_actor_id"] != detail.json()["data"]["system_actor_id"]
        )
    assert (
        TestClient(
            create_app(
                actor_resolver=lambda _: None,
                billing_run_flow=PostgresBillingRunService(
                    financial_database_url(),
                    api_service_actor_id=service_actor_id,
                ),
            )
        )
        .post(
            f"/api/v1/properties/{property_id}/billing-runs/rent",
            json=rent_payload,
            headers=rent_headers,
        )
        .status_code
        == 401
    )
    assert (
        client.post(
            f"/api/v1/properties/{uuid4()}/billing-runs/rent",
            json=rent_payload,
            headers=rent_headers,
        ).status_code
        == 403
    )
    with psycopg.connect(migrated_database_url) as owner:
        evidence = owner.execute(
            "SELECT authorization_evidence->>'requester_actor_id',actor_id "
            "FROM app.audit_events WHERE correlation_id=%s ORDER BY occurred_at LIMIT 1",
            (UUID(rent_created.json()["data"]["correlation_id"]),),
        ).fetchone()
    assert evidence == (str(human_actor_id), service_actor_id)


def test_api_service_resolution_fails_closed_when_missing_or_ambiguous(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as owner:
        human_actor_id, property_id, lease_ids, service_actor_id = fresh_rent_property(
            owner,
            lease_count=1,
            move_in_date=date(1879, 10, 26),
            configure_service=False,
        )
        assert service_actor_id is None
        lease_id = lease_ids[0]
    command_value = BillingRunCommand(
        property_id=property_id,
        run_kind="RENT",
        logical_run_key=f"rent/1880-01/{lease_id}",
        business_date=date(1879, 12, 25),
        period_start=date(1880, 1, 1),
        period_end=date(1880, 1, 31),
        idempotency_key=uuid4(),
    )
    requester = AuthenticatedActor(
        actor_id=str(human_actor_id),
        capability_grants=frozenset(
            {CapabilityGrant("billing.generate", frozenset({str(property_id)}))}
        ),
    )
    service = PostgresBillingRunService(financial_database_url())

    with pytest.raises(BillingRunAuthorizationError, match="missing or ambiguous"):
        service.execute(command_value, actor=requester, invocation_source="API")
    with psycopg.connect(migrated_database_url) as owner:
        register_billing_service_principal(
            owner,
            property_id=property_id,
            created_by=human_actor_id,
        )
        register_billing_service_principal(
            owner,
            property_id=property_id,
            created_by=human_actor_id,
        )
        owner.commit()
    with pytest.raises(BillingRunAuthorizationError, match="missing or ambiguous"):
        service.execute(command_value, actor=requester, invocation_source="API")
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.billing_runs WHERE property_id=%s AND idempotency_key=%s",
            (property_id, command_value.idempotency_key),
        ).fetchone() == (0,)


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


def test_worker_once_subprocess_exit_status_and_diagnostics_are_truthful(
    migrated_database_url: str,
) -> None:
    del migrated_database_url
    property_id = uuid4()
    service_actor_id = uuid4()
    command_args = [
        sys.executable,
        "-m",
        "property_rental.billing_worker",
        "--property-id",
        str(property_id),
        "--actor-id",
        str(service_actor_id),
        "--max-catchup-runs",
        "1",
        "--once",
    ]
    succeeded = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "from datetime import date\n"
                "import property_rental.billing_worker as worker\n"
                "class Success:\n"
                " def run_once(self, *, as_of=None):\n"
                "  return worker.BillingWorkerResult(date(2026,8,31), ())\n"
                "worker.ScheduledBillingWorker=lambda *args, **kwargs: Success()\n"
                f"sys.argv=['worker','--property-id','{property_id}',"
                f"'--actor-id','{service_actor_id}','--once']\n"
                "raise SystemExit(worker.main())"
            ),
        ],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "APP_FINANCIAL_DATABASE_URL": "postgresql://unused"},
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert succeeded.returncode == 0, succeeded.stderr
    assert succeeded.stdout.startswith("succeeded:")
    unreachable_environment = os.environ.copy()
    diagnostic_sentinel = "must-not-appear"
    unreachable_environment["APP_FINANCIAL_DATABASE_URL"] = (
        "postgresql://"
        + "prm_financial:"
        + diagnostic_sentinel
        + "@127.0.0.1:1/prm?connect_timeout=1"
    )
    failed = subprocess.run(
        command_args,
        cwd=Path(__file__).parents[1],
        env=unreachable_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert failed.returncode != 0
    assert failed.stderr.strip() == "failed:OperationalError"
    assert diagnostic_sentinel not in failed.stdout + failed.stderr


def test_lost_response_after_commit_replays_exact_persisted_run(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with psycopg.connect(migrated_database_url) as owner:
        _, property_id, lease_ids, service_actor_id = fresh_rent_property(
            owner,
            lease_count=1,
            move_in_date=date(1884, 10, 26),
        )
    assert service_actor_id is not None
    lease_id = lease_ids[0]
    run_command = BillingRunCommand(
        property_id=property_id,
        run_kind="RENT",
        logical_run_key=f"rent/1885-01/lost/{lease_id}",
        business_date=date(1884, 12, 25),
        period_start=date(1885, 1, 1),
        period_end=date(1885, 1, 31),
        idempotency_key=uuid4(),
    )
    original_get = PostgresBillingRunService._get_on_connection
    lost_response = False

    def fail_once_after_commit(
        connection: psycopg.Connection[tuple[object, ...]], run_id: UUID
    ) -> BillingRunDetail:
        nonlocal lost_response
        status_row = connection.execute(
            "SELECT status FROM app.billing_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        if not lost_response and status_row == ("SUCCEEDED",):
            lost_response = True
            raise BillingRunUnavailable("injected response loss after commit")
        return original_get(connection, run_id)

    monkeypatch.setattr(
        PostgresBillingRunService,
        "_get_on_connection",
        staticmethod(fail_once_after_commit),
    )
    with pytest.raises(BillingRunUnavailable, match="after commit"):
        PostgresBillingRunService(financial_database_url()).execute(
            run_command,
            actor=service_actor(service_actor_id, property_id),
            invocation_source="SCHEDULED",
        )
    monkeypatch.setattr(
        PostgresBillingRunService,
        "_get_on_connection",
        staticmethod(original_get),
    )

    replay = PostgresBillingRunService(financial_database_url()).execute(
        run_command,
        actor=service_actor(service_actor_id, property_id),
        invocation_source="SCHEDULED",
    )

    assert lost_response
    assert replay.status == "SUCCEEDED"
    assert len(replay.attempts) == 1
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.invoices WHERE lease_id=%s "
            "AND billing_period_start=DATE '1885-01-01' AND status<>'VOID'",
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
            "SELECT * FROM app.start_scheduled_billing_run(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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


def test_mixed_two_source_retry_adopts_prior_invoice_and_finishes_unresolved_source(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as owner:
        _, property_id, lease_ids, service_actor_id = fresh_rent_property(
            owner,
            lease_count=2,
            move_in_date=date(1889, 10, 26),
        )
        assert service_actor_id is not None
        first_lease_id, second_lease_id = lease_ids
    run_command = BillingRunCommand(
        property_id=property_id,
        run_kind="RENT",
        logical_run_key=f"rent/1890-01/retry/{first_lease_id}",
        business_date=date(1889, 12, 25),
        period_start=date(1890, 1, 1),
        period_end=date(1890, 1, 31),
        idempotency_key=uuid4(),
    )
    digest = billing_run_request_digest(run_command, "SCHEDULED")
    run_id = stable_billing_id(
        property_id,
        "/".join(
            (
                run_command.run_kind,
                run_command.logical_run_key,
                run_command.period_start.isoformat(),
                run_command.period_end.isoformat(),
            )
        ),
    )
    with psycopg.connect(financial_database_url()) as financial:
        started = financial.execute(
            "SELECT * FROM app.start_scheduled_billing_run(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                run_id,
                property_id,
                "RENT",
                run_command.logical_run_key,
                run_command.business_date,
                run_command.period_start,
                run_command.period_end,
                run_command.idempotency_key,
                digest,
                service_actor_id,
                service_actor_id,
                stable_billing_id(run_id, "correlation"),
                "SCHEDULED",
            ),
        ).fetchone()
        financial.commit()
    assert started is not None
    first_attempt_id = UUID(str(started[1]))
    with psycopg.connect(migrated_database_url) as owner:
        ordered_sources = [
            UUID(str(row[0]))
            for row in owner.execute(
                "SELECT source_id FROM app.billing_run_eligible_sources WHERE billing_run_id=%s "
                "ORDER BY source_period_start,source_period_end,source_kind,source_id",
                (run_id,),
            ).fetchall()
        ]
        assert len(ordered_sources) == 2
        collision_id = stable_billing_id(
            first_attempt_id,
            f"audit/LEASE_PERIOD/{ordered_sources[1]}",
        )
        owner.execute(
            "INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,"
            "entity_type,entity_id,reason,property_id,previous_state,correlation_id,source,"
            "outcome) VALUES (%s,statement_timestamp(),%s,%s,'injected.retry.collision','test',"
            "%s,'Injected second-source collision',%s,'{}'::jsonb,%s,'SCHEDULED','FAILED')",
            (
                collision_id,
                run_command.business_date,
                service_actor_id,
                uuid4(),
                property_id,
                uuid4(),
            ),
        )
        owner.commit()

    service = PostgresBillingRunService(financial_database_url())
    actor = service_actor(service_actor_id, property_id)
    failed = service.execute(run_command, actor=actor, invocation_source="SCHEDULED")
    assert failed.status == "RETRYABLE"
    assert [item.outcome for item in failed.attempts[0].items] == ["GENERATED", "ERROR"]
    prior_invoice_id = failed.attempts[0].items[0].invoice_id
    assert prior_invoice_id is not None

    recovered = service.execute(run_command, actor=actor, invocation_source="SCHEDULED")
    replay = service.execute(run_command, actor=actor, invocation_source="SCHEDULED")

    assert recovered.status == replay.status == "SUCCEEDED"
    assert [attempt.outcome for attempt in recovered.attempts] == ["FAILED", "SUCCEEDED"]
    assert [item.outcome for item in recovered.attempts[1].items] == ["SKIPPED", "GENERATED"]
    assert recovered.attempts[1].items[0].invoice_id == prior_invoice_id
    assert recovered.attempts[1].items[0].diagnostic_code == "ACTIVE_INVOICE_ALREADY_EXISTS"
    assert replay.attempts == recovered.attempts
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.invoices WHERE lease_id=ANY(%s) "
            "AND billing_period_start=DATE '1890-01-01' AND status<>'VOID'",
            ([first_lease_id, second_lease_id],),
        ).fetchone() == (2,)


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
        rate_row = owner.execute(
            "SELECT id FROM app.utility_rates WHERE property_id=%s "
            "AND utility_type='ELECTRICITY' AND measurement_unit_code='KWH' "
            "AND effective_date<=DATE '2026-06-16' ORDER BY effective_date DESC LIMIT 1",
            (property_id,),
        ).fetchone()
        if rate_row is None:
            add_rate(
                owner,
                actor_id=human_actor_id,
                property_id=property_id,
                utility_type="ELECTRICITY",
                measurement_unit_code="KWH",
                effective_date=date(2026, 1, 1),
            )
        owner.commit()
    replacement_id, replacement_start_reading_id = replace_failed_meter(
        migrated_database_url,
        actor_id=human_actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_meter_id,
        failure_date=date(2026, 6, 3),
        replacement_date=date(2026, 6, 17),
    )
    utility_actor = authorized_actor(
        human_actor_id,
        property_id,
        UTILITY_CALCULATE_CAPABILITY,
        UTILITY_ESTIMATE_CAPABILITY,
    )
    utility_service = PostgresUtilityService(financial_database_url(), property_id, human_actor_id)
    case_id, _ = open_case(
        utility_service,
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
    run_command = BillingRunCommand(
        property_id=property_id,
        run_kind="UTILITIES",
        logical_run_key=f"utilities/pending/{case_id}",
        business_date=period_end,
        period_start=period_start,
        period_end=period_end,
        idempotency_key=uuid4(),
    )
    result = PostgresBillingRunService(financial_database_url()).execute(
        run_command,
        actor=service_actor(worker_actor_id, property_id),
        invocation_source="SCHEDULED",
    )

    assert result.status == "RETRYABLE"
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
        future_end_reading_id = add_reading(
            owner,
            actor_id=human_actor_id,
            meter_id=replacement_id,
            reading_date=date(2026, 6, 27),
            reading_value="20",
        )
        owner.commit()
    future_period_id, _ = finalize_actual(
        utility_service,
        utility_actor,
        unit_id,
        replacement_start_reading_id,
        future_end_reading_id,
    )
    estimate_period_id, _ = finalize_estimate(utility_service, utility_actor, case_id)
    with psycopg.connect(financial_database_url()) as financial:
        candidates = financial.execute(
            "SELECT * FROM app.scheduled_billing_worker_candidates(%s,%s,%s,10)",
            (property_id, worker_actor_id, database_now()),
        ).fetchall()
    assert (period_end, period_start, period_end, "UTILITIES") in candidates

    restarted_services = (
        PostgresBillingRunService(financial_database_url()),
        PostgresBillingRunService(financial_database_url()),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        recovered_results = tuple(
            pool.map(
                lambda service: service.execute(
                    run_command,
                    actor=service_actor(worker_actor_id, property_id),
                    invocation_source="SCHEDULED",
                ),
                restarted_services,
            )
        )
    retry_evidence = tuple(
        (
            recovered.status,
            tuple(
                (
                    attempt.outcome,
                    tuple((item.outcome, item.diagnostic_code) for item in attempt.items),
                )
                for attempt in recovered.attempts
            ),
        )
        for recovered in recovered_results
    )
    assert {recovered.status for recovered in recovered_results} == {"SUCCEEDED"}, retry_evidence
    recovered = recovered_results[0]
    assert [attempt.outcome for attempt in recovered.attempts] == ["FAILED", "SUCCEEDED"]
    assert [
        (item.outcome, item.diagnostic_code, item.invoice_id)
        for item in recovered.attempts[0].items
    ] == [("SKIPPED", "PENDING_FUTURE_ACTUAL_BASIS", None)]
    assert [(item.outcome, item.source_id) for item in recovered.attempts[1].items] == [
        ("GENERATED", case_id)
    ]
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.invoice_lines WHERE utility_consumption_period_id=%s",
            (estimate_period_id,),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT calculation_trace->'basis_period_ids' "
            "FROM app.utility_consumption_periods WHERE id=%s",
            (estimate_period_id,),
        ).fetchone() == ([str(future_period_id)],)
