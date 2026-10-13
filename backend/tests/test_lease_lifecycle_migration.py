"""Real PostgreSQL coverage for V1-034 Lease lifecycle services."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from property_rental.billing import month_end
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LEASE_SIGNER_MANAGE_CAPABILITY,
    LEASE_TERMINATE_CAPABILITY,
    LeaseAddSignerCommand,
    LeaseCancelCommand,
    LeaseCommandConflictError,
    LeaseCommandInvalidError,
    LeaseDraftCommand,
    LeaseNotFoundError,
    LeaseRecordSignatureCommand,
    LeaseRemoveSignerCommand,
    LeaseSignCommand,
    LeaseStatus,
    LeaseTerminateCommand,
    LeaseVersionConflictError,
    PostgresLeaseService,
)
from termination_test_support import approved_test_termination_context


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def database_now() -> datetime:
    """Read the time from the database's own clock.

    The database refuses a signing time later than its statement time, and it runs in a
    container whose clock can lag the host clock, so a signing time taken from the host
    clock can fail at random (TEST-019).
    """
    with psycopg.connect(runtime_database_url()) as connection:
        value = connection.execute("SELECT clock_timestamp()").fetchone()
    assert value is not None and isinstance(value[0], datetime)
    return value[0]


def setup_sources(
    connection: psycopg.Connection[tuple[object, ...]],
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    actor_id = uuid4()
    property_row = connection.execute("SELECT id FROM app.properties").fetchone()
    property_id = UUID(str(property_row[0])) if property_row is not None else uuid4()
    unit_id = uuid4()
    primary_tenant_id = uuid4()
    additional_customer_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.user_accounts(
            actor_id, normalized_username, display_name, audit_name,
            lifecycle_state, mfa_policy_class, provenance
        ) VALUES (%s,%s,'Lease Service Actor','Lease Service Actor',
                  'active','optional','test')
        """,
        (actor_id, f"lease-service-{actor_id}"),
    )
    if property_row is None:
        connection.execute(
            "INSERT INTO app.properties(id,name,created_by,updated_by) VALUES (%s,%s,%s,%s)",
            (property_id, f"Lease Service Property {property_id}", actor_id, actor_id),
        )
    connection.execute(
        """
        INSERT INTO app.units(
            id,property_id,unit_number,floor,unit_type,status,created_by,updated_by
        ) VALUES (%s,%s,%s,'1','ONE_BEDROOM','VACANT',%s,%s)
        """,
        (unit_id, property_id, f"LS-{unit_id.hex[:12]}", actor_id, actor_id),
    )
    for customer_id, legal_name in (
        (primary_tenant_id, "Primary Lease Tenant"),
        (additional_customer_id, "Additional Lease Signer"),
    ):
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) VALUES (%s,%s,%s,%s)",
            (customer_id, legal_name, actor_id, actor_id),
        )
    return actor_id, property_id, unit_id, primary_tenant_id, additional_customer_id


def actor(actor_id: UUID, property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            CapabilityGrant(capability, scope) for capability in capabilities
        ),
    )


def draft_command(
    unit_id: UUID,
    primary_tenant_id: UUID,
    *,
    start_date: date = date(2027, 1, 1),
    end_date: date = date(2027, 12, 31),
) -> LeaseDraftCommand:
    return LeaseDraftCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=uuid4(),
        unit_id=unit_id,
        primary_tenant_id=primary_tenant_id,
        primary_signer_id=uuid4(),
        start_date=start_date,
        end_date=end_date,
        monthly_rent_usd_cents=80_000,
        predecessor_lease_id=None,
        reason="Authorized Lease draft",
        authorization_reference=LEASE_DRAFT_CAPABILITY,
    )


def signature_command(
    lease_id: UUID,
    signer_id: UUID,
    expected_version: int,
    *,
    signed_at: datetime | None = None,
) -> LeaseRecordSignatureCommand:
    return LeaseRecordSignatureCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=lease_id,
        signer_id=signer_id,
        expected_version=expected_version,
        signed_at=database_now() if signed_at is None else signed_at,
        reason="Signer accepted the complete Lease",
        authorization_reference=LEASE_SIGN_CAPABILITY,
    )


def test_commands_are_idempotent_versioned_audited_and_preserve_signer_rules(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, tenant_id, additional_id = setup_sources(setup)
        clock = setup.execute(
            "SELECT statement_timestamp(), "
            "timezone(property.timezone_name, statement_timestamp())::date "
            "FROM app.properties AS property WHERE property.id=%s",
            (property_id,),
        ).fetchone()
        assert clock is not None
        event_now, business_date = clock
        assert isinstance(event_now, datetime)
        assert isinstance(business_date, date)
        setup.commit()
    service = PostgresLeaseService(runtime_database_url(), property_id, actor_id)
    authenticated = actor(
        actor_id,
        property_id,
        LEASE_DRAFT_CAPABILITY,
        LEASE_SIGN_CAPABILITY,
        LEASE_SIGNER_MANAGE_CAPABILITY,
        LEASE_TERMINATE_CAPABILITY,
    )
    draft = draft_command(
        unit_id,
        tenant_id,
        start_date=business_date - timedelta(days=30),
        end_date=month_end(business_date + timedelta(days=365)),
    )

    created = service.draft(draft, actor=authenticated)
    replayed = service.draft(draft, actor=authenticated)

    assert created == replayed
    assert created.status is LeaseStatus.DRAFTED
    assert created.version == 1
    assert created.signer_count == 1
    assert created.signed_signer_count == 0
    with pytest.raises(LeaseCommandConflictError):
        service.draft(
            replace(draft, reason="Changed command using the same idempotency key"),
            actor=authenticated,
        )

    with pytest.raises(LeaseCommandInvalidError):
        service.record_signature(
            signature_command(
                draft.lease_id,
                draft.primary_signer_id,
                1,
                signed_at=event_now + timedelta(days=1),
            ),
            actor=authenticated,
        )
    primary_signature = signature_command(
        draft.lease_id,
        draft.primary_signer_id,
        1,
        signed_at=database_now(),
    )
    assert service.record_signature(primary_signature, actor=authenticated).version == 2
    additional_signer_id = uuid4()
    add_signer = LeaseAddSignerCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=draft.lease_id,
        signer_id=additional_signer_id,
        customer_id=additional_id,
        expected_version=2,
        reason="Add jointly responsible Lease Signer",
        authorization_reference=LEASE_SIGNER_MANAGE_CAPABILITY,
    )
    added = service.add_signer(add_signer, actor=authenticated)
    assert (added.version, added.signer_count, added.signed_signer_count) == (3, 2, 1)
    sign = LeaseSignCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=draft.lease_id,
        expected_version=3,
        signed_at=database_now(),
        reason="Every Lease Signer completed signing",
        authorization_reference=LEASE_SIGN_CAPABILITY,
    )
    with pytest.raises(LeaseCommandInvalidError):
        service.sign(sign, actor=authenticated)
    additional_signature = signature_command(
        draft.lease_id,
        additional_signer_id,
        3,
        signed_at=database_now(),
    )
    assert service.record_signature(additional_signature, actor=authenticated).version == 4
    for invalid_signed_at in (
        additional_signature.signed_at - timedelta(microseconds=1),
        database_now() + timedelta(days=1),
    ):
        with pytest.raises(LeaseCommandInvalidError):
            service.sign(
                LeaseSignCommand(
                    idempotency_key=uuid4(),
                    event_id=uuid4(),
                    lease_id=draft.lease_id,
                    expected_version=4,
                    signed_at=invalid_signed_at,
                    reason="Lease signing must follow every signer and database time",
                    authorization_reference=LEASE_SIGN_CAPABILITY,
                ),
                actor=authenticated,
            )
    sign = LeaseSignCommand(
        idempotency_key=sign.idempotency_key,
        event_id=sign.event_id,
        lease_id=sign.lease_id,
        expected_version=4,
        signed_at=database_now(),
        reason=sign.reason,
        authorization_reference=sign.authorization_reference,
    )
    signed = service.sign(sign, actor=authenticated)
    assert signed.status is LeaseStatus.SIGNED
    assert signed.version == 5
    assert signed.signer_count == signed.signed_signer_count == 2
    assert service.sign(sign, actor=authenticated) == signed
    termination_timestamp = database_now()
    with pytest.raises(LeaseVersionConflictError):
        service.terminate(
            LeaseTerminateCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=draft.lease_id,
                expected_version=4,
                actual_termination_date=business_date,
                occurred_at=termination_timestamp,
                governing_event_reference="AUTHORIZED-EVENT-STALE",
                reason="Authorized early termination",
                authorization_reference=LEASE_TERMINATE_CAPABILITY,
                context=approved_test_termination_context(),
            ),
            actor=authenticated,
        )
    with pytest.raises(LeaseCommandInvalidError):
        service.terminate(
            LeaseTerminateCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=draft.lease_id,
                expected_version=5,
                actual_termination_date=business_date + timedelta(days=1),
                occurred_at=termination_timestamp + timedelta(days=1),
                governing_event_reference="AUTHORIZED-FUTURE-TERMINATION",
                reason="Future termination must remain signed until its actual date",
                authorization_reference=LEASE_TERMINATE_CAPABILITY,
                context=approved_test_termination_context(),
            ),
            actor=authenticated,
        )

    with psycopg.connect(migrated_database_url) as setup:
        occupancy_id = uuid4()
        setup.execute(
            """
            INSERT INTO app.occupancies(
                id,lease_id,customer_id,move_in_date,created_by,updated_by
            ) VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                occupancy_id,
                draft.lease_id,
                tenant_id,
                business_date - timedelta(days=10),
                actor_id,
                actor_id,
            ),
        )
        setup.commit()
    termination = LeaseTerminateCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=draft.lease_id,
        expected_version=5,
        actual_termination_date=business_date,
        occurred_at=termination_timestamp,
        governing_event_reference="AUTHORIZED-ACTUAL-TERMINATION-001",
        reason="Authorized early termination",
        authorization_reference=LEASE_TERMINATE_CAPABILITY,
        context=approved_test_termination_context(),
    )
    terminated = service.terminate(termination, actor=authenticated)
    assert terminated.status is LeaseStatus.TERMINATED
    assert terminated.version == 6
    assert service.terminate(termination, actor=authenticated) == terminated

    with psycopg.connect(migrated_database_url) as check:
        command_rows = check.execute(
            "SELECT action,authorization_reference,governing_event_reference,"
            "previous_snapshot,result_snapshot FROM app.lease_commands "
            "WHERE lease_id=%s ORDER BY (result_snapshot->>'version')::integer,event_id",
            (draft.lease_id,),
        ).fetchall()
        persisted = check.execute(
            "SELECT lease.status,lease.version,unit.status,occupancy.move_out_date "
            "FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id "
            "JOIN app.occupancies AS occupancy ON occupancy.lease_id=lease.id "
            "WHERE lease.id=%s",
            (draft.lease_id,),
        ).fetchone()
        revisions = check.execute(
            "SELECT version,status FROM app.lease_revisions WHERE lease_id=%s ORDER BY version",
            (draft.lease_id,),
        ).fetchall()
    assert [row[0] for row in command_rows] == [
        "lease.draft",
        "lease.signer.sign",
        "lease.signer.add",
        "lease.signer.sign",
        "lease.sign",
        "lease.terminate",
    ]
    assert command_rows[-1][1:3] == (
        LEASE_TERMINATE_CAPABILITY,
        termination.governing_event_reference,
    )
    assert all(row[4]["lease_id"] == str(draft.lease_id) for row in command_rows)
    # DL-066: signing occupies the Unit, and termination alone does not release an open
    # Occupancy, so the Unit stays OCCUPIED until physical move-out.
    assert persisted == ("TERMINATED", 6, "OCCUPIED", None)
    assert revisions == [
        (1, "DRAFTED"),
        (2, "DRAFTED"),
        (3, "DRAFTED"),
        (4, "DRAFTED"),
        (5, "SIGNED"),
        (6, "TERMINATED"),
    ]
    for statement in (
        "UPDATE app.lease_commands SET reason='Rewritten' WHERE event_id=%s",
        "DELETE FROM app.lease_commands WHERE event_id=%s",
    ):
        with psycopg.connect(migrated_database_url) as owner:
            with pytest.raises(psycopg.Error) as mutation:
                owner.execute(statement, (termination.event_id,))
            assert mutation.value.sqlstate == "55000"


def test_draft_cancellation_signer_removal_scope_and_end_date_boundaries(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, tenant_id, additional_id = setup_sources(setup)
        setup.commit()
    authenticated = actor(
        actor_id,
        property_id,
        LEASE_DRAFT_CAPABILITY,
        LEASE_SIGN_CAPABILITY,
        LEASE_SIGNER_MANAGE_CAPABILITY,
    )
    service = PostgresLeaseService(runtime_database_url(), property_id, actor_id)
    draft = draft_command(
        unit_id,
        tenant_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    service.draft(draft, actor=authenticated)
    removable_id = uuid4()
    service.add_signer(
        LeaseAddSignerCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            signer_id=removable_id,
            customer_id=additional_id,
            expected_version=1,
            reason="Temporarily add signer",
            authorization_reference=LEASE_SIGNER_MANAGE_CAPABILITY,
        ),
        actor=authenticated,
    )
    removed = service.remove_signer(
        LeaseRemoveSignerCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            signer_id=removable_id,
            expected_version=2,
            reason="Remove unsigned non-primary signer",
            authorization_reference=LEASE_SIGNER_MANAGE_CAPABILITY,
        ),
        actor=authenticated,
    )
    assert (removed.version, removed.signer_count) == (3, 1)
    with pytest.raises(LeaseCommandInvalidError):
        service.remove_signer(
            LeaseRemoveSignerCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=draft.lease_id,
                signer_id=draft.primary_signer_id,
                expected_version=3,
                reason="Invalid Primary Tenant removal",
                authorization_reference=LEASE_SIGNER_MANAGE_CAPABILITY,
            ),
            actor=authenticated,
        )
    cancelled = service.cancel(
        LeaseCancelCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            expected_version=3,
            reason="Draft terms were not accepted",
            authorization_reference=LEASE_DRAFT_CAPABILITY,
        ),
        actor=authenticated,
    )
    assert cancelled.status is LeaseStatus.CANCELLED
    assert cancelled.end_date == date(2025, 12, 31)

    ended_draft = draft_command(
        unit_id,
        tenant_id,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
    )
    service.draft(ended_draft, actor=authenticated)
    service.record_signature(
        signature_command(ended_draft.lease_id, ended_draft.primary_signer_id, 1),
        actor=authenticated,
    )
    ended_signed = service.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=ended_draft.lease_id,
            expected_version=2,
            signed_at=database_now(),
            reason="Explicit signing remains required after the contractual boundary",
            authorization_reference=LEASE_SIGN_CAPABILITY,
        ),
        actor=authenticated,
    )
    assert ended_signed.status is LeaseStatus.SIGNED
    with psycopg.connect(migrated_database_url) as check:
        assert check.execute(
            "SELECT status FROM app.leases WHERE id=%s", (ended_draft.lease_id,)
        ).fetchone() == ("SIGNED",)

    other_property_id = uuid4()
    wrong_scope_service = PostgresLeaseService(runtime_database_url(), other_property_id, actor_id)
    with pytest.raises(LeaseNotFoundError):
        wrong_scope_service.cancel(
            LeaseCancelCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=draft.lease_id,
                expected_version=4,
                reason="Wrong Property scope must not disclose Lease",
                authorization_reference=LEASE_DRAFT_CAPABILITY,
            ),
            actor=actor(actor_id, other_property_id, LEASE_DRAFT_CAPABILITY),
        )


def test_concurrent_overlapping_signing_allows_exactly_one_lease(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(setup)
        setup.commit()
    authenticated = actor(actor_id, property_id, LEASE_DRAFT_CAPABILITY, LEASE_SIGN_CAPABILITY)
    service = PostgresLeaseService(runtime_database_url(), property_id, actor_id)
    drafts = [draft_command(unit_id, tenant_id) for _ in range(2)]
    for draft in drafts:
        service.draft(draft, actor=authenticated)
        service.record_signature(
            signature_command(draft.lease_id, draft.primary_signer_id, 1),
            actor=authenticated,
        )
    barrier = Barrier(2)
    # Read once before the threads start, so a failed read cannot leave one thread waiting.
    signed_at = database_now()

    def sign(draft: LeaseDraftCommand) -> str:
        barrier.wait()
        try:
            service.sign(
                LeaseSignCommand(
                    idempotency_key=uuid4(),
                    event_id=uuid4(),
                    lease_id=draft.lease_id,
                    expected_version=2,
                    signed_at=signed_at,
                    reason="Concurrent signing attempt",
                    authorization_reference=LEASE_SIGN_CAPABILITY,
                ),
                actor=authenticated,
            )
        except LeaseCommandConflictError:
            return "conflict"
        return "signed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(sign, drafts))

    assert sorted(outcomes) == ["conflict", "signed"]
    with psycopg.connect(migrated_database_url) as check:
        states = check.execute(
            "SELECT status FROM app.leases WHERE id IN (%s,%s) ORDER BY id",
            (drafts[0].lease_id, drafts[1].lease_id),
        ).fetchall()
    assert sorted(row[0] for row in states) == ["DRAFTED", "SIGNED"]


def test_open_occupancy_blocks_unrelated_signing_but_allows_exact_renewal(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(setup)
        clock = setup.execute(
            "SELECT statement_timestamp(), "
            "timezone(property.timezone_name, statement_timestamp())::date "
            "FROM app.properties AS property WHERE property.id=%s",
            (property_id,),
        ).fetchone()
        assert clock is not None
        _, business_date = clock
        assert isinstance(business_date, date)
        setup.commit()
    authenticated = actor(
        actor_id,
        property_id,
        LEASE_DRAFT_CAPABILITY,
        LEASE_SIGN_CAPABILITY,
    )
    service = PostgresLeaseService(runtime_database_url(), property_id, actor_id)
    occupied_lease = draft_command(
        unit_id,
        tenant_id,
        start_date=business_date - timedelta(days=30),
        end_date=month_end(business_date),
    )
    service.draft(occupied_lease, actor=authenticated)
    service.record_signature(
        signature_command(
            occupied_lease.lease_id,
            occupied_lease.primary_signer_id,
            1,
            signed_at=database_now(),
        ),
        actor=authenticated,
    )
    service.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=occupied_lease.lease_id,
            expected_version=2,
            signed_at=database_now(),
            reason="Complete the occupied Lease signing",
            authorization_reference=LEASE_SIGN_CAPABILITY,
        ),
        actor=authenticated,
    )
    with psycopg.connect(migrated_database_url) as setup:
        setup.execute(
            "INSERT INTO app.occupancies("
            "id,lease_id,customer_id,move_in_date,created_by,updated_by"
            ") VALUES (%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                occupied_lease.lease_id,
                tenant_id,
                business_date - timedelta(days=10),
                actor_id,
                actor_id,
            ),
        )
        setup.commit()
    successor = draft_command(
        unit_id,
        tenant_id,
        start_date=month_end(business_date) + timedelta(days=1),
        end_date=month_end(business_date + timedelta(days=365)),
    )
    service.draft(successor, actor=authenticated)
    service.record_signature(
        signature_command(
            successor.lease_id,
            successor.primary_signer_id,
            1,
            signed_at=database_now(),
        ),
        actor=authenticated,
    )
    with pytest.raises(LeaseCommandConflictError):
        service.sign(
            LeaseSignCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=successor.lease_id,
                expected_version=2,
                signed_at=database_now(),
                reason="Open physical Occupancy must block contractual reuse",
                authorization_reference=LEASE_SIGN_CAPABILITY,
            ),
            actor=authenticated,
        )
    with psycopg.connect(migrated_database_url) as check:
        status = check.execute(
            "SELECT status FROM app.leases WHERE id=%s", (successor.lease_id,)
        ).fetchone()
        sign_events = check.execute(
            "SELECT count(*) FROM app.lease_commands WHERE lease_id=%s AND action='lease.sign'",
            (successor.lease_id,),
        ).fetchone()
    assert status == ("DRAFTED",)
    assert sign_events == (0,)

    renewal = replace(
        draft_command(
            unit_id,
            tenant_id,
            start_date=month_end(business_date) + timedelta(days=1),
            end_date=month_end(business_date + timedelta(days=365)),
        ),
        predecessor_lease_id=occupied_lease.lease_id,
        reason="Authorized non-overlapping renewal draft",
    )
    service.draft(renewal, actor=authenticated)
    service.record_signature(
        signature_command(
            renewal.lease_id,
            renewal.primary_signer_id,
            1,
            signed_at=database_now(),
        ),
        actor=authenticated,
    )
    renewed = service.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=renewal.lease_id,
            expected_version=2,
            signed_at=database_now(),
            reason="Sign the exact non-overlapping predecessor renewal",
            authorization_reference=LEASE_SIGN_CAPABILITY,
        ),
        actor=authenticated,
    )
    assert renewed.status is LeaseStatus.SIGNED
    assert renewed.predecessor_lease_id == occupied_lease.lease_id


def test_runtime_role_uses_only_bounded_functions_and_command_history_is_permanent(
    migrated_database_url: str,
) -> None:
    del migrated_database_url
    with psycopg.connect(runtime_database_url()) as runtime:
        privileges = runtime.execute(
            """
            SELECT
                has_table_privilege(current_user,'app.lease_commands','SELECT'),
                has_table_privilege(current_user,'app.lease_commands','INSERT'),
                has_function_privilege(current_user,
                    'app.sign_lease(uuid,uuid,text,uuid,uuid,integer,timestamptz,text,uuid)',
                    'EXECUTE'),
                has_function_privilege(current_user,
                    'app.sign_draft_lease_signer(uuid,timestamptz,uuid)','EXECUTE'),
                has_function_privilege(current_user,
                    'app.remove_draft_lease_signer(uuid,uuid)','EXECUTE'),
                has_function_privilege(current_user,
                    'app.validate_lease_relationships()','EXECUTE'),
                (SELECT procedure.prosecdef
                 FROM pg_proc AS procedure
                 JOIN pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
                 WHERE namespace.nspname='app'
                   AND procedure.proname='validate_lease_relationships')
            """
        ).fetchone()
    # Since migration 20261009_74 the runtime role signs only through
    # app.sign_lease_with_reservation, so direct EXECUTE on app.sign_lease is gone.
    assert privileges == (True, False, False, False, False, False, True)


def test_lease_lifecycle_migration_is_forward_only() -> None:
    source = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260826_24_lease_lifecycle_services.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "20260826_23"' in source
    assert "Lease lifecycle service migration is forward-only" in source
