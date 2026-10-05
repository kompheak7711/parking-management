"""Real PostgreSQL coverage for V1-037 Deposit persistence and services."""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config

from deposit_disposition_test_support import disposition_context, terminate_for_disposition
from lease_deposit_forfeiture_test_support import (
    forfeit_through_draft,
    record_disposition_as_owner,
    reverse_disposition_as_owner,
    reverse_through_draft,
)
from payment_test_support import seed_deposit_payment
from property_rental.deposit import (
    DEPOSIT_CORRECT_CAPABILITY,
    DEPOSIT_DISPOSE_CAPABILITY,
    DEPOSIT_MANAGE_CAPABILITY,
    DEPOSIT_REFUND_QUALIFY_CAPABILITY,
    AdjustDepositRequiredAmountCommand,
    CreatePetDepositCommand,
    DepositAdjustmentType,
    DepositConflictError,
    DepositInvalidError,
    DepositNotFoundError,
    DepositSnapshot,
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordDepositDispositionCommand,
    RecordPetDepartureCommand,
    ReverseDepositDispositionCommand,
    ReverseDepositReceiptCommand,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_move_in_migration import setup_move_in
from test_reservation_migration import create_reservation, setup_reservation_sources


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    value = os.environ.get("MIGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("MIGRATION_DATABASE_URL is required")
    alembic_command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def financial_database_url() -> str:
    value = os.environ.get("FINANCIAL_DATABASE_URL")
    if value is None:
        pytest.skip("FINANCIAL_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def deposit_actor(actor_id: UUID, property_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {
                CapabilityGrant(capability, frozenset({str(property_id)}))
                for capability in (
                    DEPOSIT_MANAGE_CAPABILITY,
                    DEPOSIT_CORRECT_CAPABILITY,
                    DEPOSIT_DISPOSE_CAPABILITY,
                    DEPOSIT_REFUND_QUALIFY_CAPABILITY,
                )
            }
        ),
    )


def setup_signed_pet_lease(
    database_url: str, *, requires_deposit: bool = True
) -> tuple[PostgresDepositService, AuthenticatedActor, UUID, UUID, date]:
    with psycopg.connect(database_url) as connection:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
        property_clock = connection.execute(
            "SELECT timezone(property.timezone_name, statement_timestamp())::date "
            "FROM app.properties AS property WHERE property.id=%s",
            (property_id,),
        ).fetchone()
        assert property_clock is not None
        business_day = property_clock[0]
        assert isinstance(business_day, date)
        lease_id = create_draft(
            connection,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=business_day - timedelta(days=30),
            end_date=business_day + timedelta(days=335),
        )
        sign_lease(connection, lease_id, actor_id)
        approval_id = uuid4()
        approval_date = business_day - timedelta(days=1)
        connection.execute(
            """
            INSERT INTO app.lease_pet_approvals(
                id,lease_id,approved_date,deposit_required_by_signed_terms,
                pet_description,approved_at,approved_by
            ) VALUES (%s,%s,%s,%s,'Approved cat',clock_timestamp(),%s)
            """,
            (approval_id, lease_id, approval_date, requires_deposit, actor_id),
        )
        connection.commit()
    return (
        PostgresDepositService(financial_database_url(), property_id, actor_id),
        deposit_actor(actor_id, property_id),
        lease_id,
        approval_id,
        approval_date,
    )


def create_pet(
    service: PostgresDepositService,
    actor: AuthenticatedActor,
    lease_id: UUID,
    approval_id: UUID,
    effective_date: date,
) -> tuple[UUID, DepositSnapshot]:
    deposit_id = uuid4()
    command = CreatePetDepositCommand(
        uuid4(),
        deposit_id,
        lease_id,
        approval_id,
        20_000,
        effective_date,
        "Approved signed Lease pet terms",
    )
    return deposit_id, service.create_pet_deposit(command, actor=actor)


def seed_historical_deposit_receipt(
    database_url: str, *, deposit_id: UUID, actor_id: UUID, amount_usd_cents: int
) -> UUID:
    """Represent synthetic receipt history backed by authoritative Payment evidence."""
    receipt_id = uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "INSERT INTO app.deposit_receipts("
            "id,deposit_id,payment_id,amount_usd_cents,occurred_at,actor_id) "
            "VALUES (%s,%s,%s,%s,clock_timestamp(),%s)",
            (
                receipt_id,
                deposit_id,
                seed_deposit_payment(
                    connection, deposit_id=deposit_id, actor_id=actor_id, amount=amount_usd_cents
                ),
                amount_usd_cents,
                actor_id,
            ),
        )
        connection.commit()
    return receipt_id


def test_pet_deposit_requires_matching_approved_signed_terms_and_is_idempotent(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, approved_date = setup_signed_pet_lease(
        migrated_database_url
    )
    command = CreatePetDepositCommand(
        uuid4(),
        uuid4(),
        lease_id,
        approval_id,
        20_000,
        approved_date,
        "Approved signed Lease pet terms",
    )
    first = service.create_pet_deposit(command, actor=actor)
    assert first.deposit_type == "PET"
    assert first.required_usd_cents == 20_000
    assert first.received_usd_cents == 0
    assert service.create_pet_deposit(command, actor=actor) == first
    with pytest.raises(DepositConflictError):
        service.create_pet_deposit(replace(command, required_usd_cents=20_001), actor=actor)

    no_terms, no_terms_actor, lease, approval, day = setup_signed_pet_lease(
        migrated_database_url, requires_deposit=False
    )
    with pytest.raises(DepositInvalidError):
        create_pet(no_terms, no_terms_actor, lease, approval, day)


def test_adjustments_and_receipt_reversals_preserve_history(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, day = setup_signed_pet_lease(migrated_database_url)
    deposit_id, created = create_pet(service, actor, lease_id, approval_id, day)
    assert created.outstanding_required_usd_cents == 20_000

    increased = service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            deposit_id,
            DepositAdjustmentType.INCREASE,
            5_000,
            day,
            "Signed Lease correction",
        ),
        actor=actor,
    )
    assert increased.required_usd_cents == 25_000
    receipt_id = seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=deposit_id,
        actor_id=service.actor_id,
        amount_usd_cents=25_000,
    )
    reversed_snapshot = service.reverse_receipt(
        ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt_id, "Payment receipt corrected"),
        actor=actor,
    )
    assert reversed_snapshot.received_usd_cents == 0
    assert reversed_snapshot.held_refundable_usd_cents == 0
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_receipts WHERE deposit_id=%s", (deposit_id,)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_receipt_reversals r "
            "JOIN app.deposit_receipts d ON d.id=r.deposit_receipt_id WHERE d.deposit_id=%s",
            (deposit_id,),
        ).fetchone() == (1,)


def test_pet_refund_qualification_keeps_signed_lease_and_creates_no_refund_or_application(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, day = setup_signed_pet_lease(migrated_database_url)
    deposit_id, _ = create_pet(service, actor, lease_id, approval_id, day)
    seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=deposit_id,
        actor_id=service.actor_id,
        amount_usd_cents=20_000,
    )
    departure_id = uuid4()
    service.record_pet_departure(
        RecordPetDepartureCommand(
            uuid4(),
            departure_id,
            deposit_id,
            date.today(),
            "Pet permanently left",
        ),
        actor=actor,
    )
    qualified = service.qualify_pet_refund_review(
        QualifyPetDepositRefundReviewCommand(
            uuid4(),
            uuid4(),
            departure_id,
            deposit_id,
            0,
            "No unresolved pet-caused obligations",
            "review-2027-08",
            "Pet obligations reviewed",
        ),
        actor=actor,
    )
    assert qualified.refund_qualified
    assert qualified.held_refundable_usd_cents == 20_000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT status FROM app.leases WHERE id=%s", (lease_id,)
        ).fetchone() == ("SIGNED",)
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (deposit_id,)
        ).fetchone() == (0,)
        # V1-056 sub-slice 8a-1: app.deposit_applications exists since migration 86; the
        # qualification still records no Deposit application.
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_applications WHERE deposit_id=%s", (deposit_id,)
        ).fetchone() == (0,)


@pytest.mark.parametrize("departure_offset", [-2, 2])
def test_pet_refund_qualification_rejects_impossible_departure_chronology(
    migrated_database_url: str, departure_offset: int
) -> None:
    service, actor, lease_id, approval_id, approved_day = setup_signed_pet_lease(
        migrated_database_url
    )
    deposit_id, _ = create_pet(service, actor, lease_id, approval_id, approved_day)
    seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=deposit_id,
        actor_id=service.actor_id,
        amount_usd_cents=20_000,
    )
    invalid_day = approved_day + timedelta(days=departure_offset)
    with pytest.raises(DepositInvalidError):
        service.record_pet_departure(
            RecordPetDepartureCommand(
                uuid4(),
                uuid4(),
                deposit_id,
                invalid_day,
                "Chronology must be real",
            ),
            actor=actor,
        )


def test_property_scope_and_security_deposit_cannot_use_pet_refund_exception(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, day = setup_signed_pet_lease(migrated_database_url)
    deposit_id, _ = create_pet(service, actor, lease_id, approval_id, day)
    wrong_service = PostgresDepositService(financial_database_url(), uuid4(), service.actor_id)
    wrong_actor = deposit_actor(service.actor_id, wrong_service.property_id)
    with pytest.raises(DepositNotFoundError):
        wrong_service.adjust_required_amount(
            AdjustDepositRequiredAmountCommand(
                uuid4(),
                uuid4(),
                deposit_id,
                DepositAdjustmentType.INCREASE,
                1,
                day,
                "Wrong Property attempt",
            ),
            actor=wrong_actor,
        )

    with psycopg.connect(migrated_database_url) as connection:
        security_actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
        _, identities = create_reservation(
            connection,
            actor_id=security_actor_id,
            property_id=property_id,
            unit_id=unit_id,
            customer_id=customer_id,
        )
        connection.commit()
    security_service = PostgresDepositService(
        financial_database_url(), property_id, security_actor_id
    )
    with pytest.raises(DepositNotFoundError):
        security_service.record_pet_departure(
            RecordPetDepartureCommand(
                uuid4(),
                uuid4(),
                identities["deposit_id"],
                date.today(),
                "Security Deposit cannot use Pet exception",
            ),
            actor=deposit_actor(security_actor_id, property_id),
        )


def test_concurrent_pet_deposit_creation_preserves_one_liability(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, day = setup_signed_pet_lease(migrated_database_url)
    barrier = Barrier(2)

    def attempt() -> str:
        barrier.wait()
        try:
            create_pet(service, actor, lease_id, approval_id, day)
        except DepositConflictError:
            return "conflict"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["conflict", "created"]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.deposits WHERE lease_id=%s AND deposit_type='PET'",
            (lease_id,),
        ).fetchone() == (1,)


def test_same_key_replays_are_concurrency_safe_for_exposed_deposit_commands(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, day = setup_signed_pet_lease(migrated_database_url)
    create = CreatePetDepositCommand(
        uuid4(), uuid4(), lease_id, approval_id, 20_000, day, "Approved signed Lease terms"
    )

    def concurrent(call: Callable[[], DepositSnapshot]) -> list[DepositSnapshot]:
        barrier = Barrier(2)

        def attempt(_: int) -> DepositSnapshot:
            barrier.wait()
            return call()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(attempt, range(2)))

    created = concurrent(lambda: service.create_pet_deposit(create, actor=actor))
    assert created[0] == created[1]

    receipt_id = seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=create.deposit_id,
        actor_id=service.actor_id,
        amount_usd_cents=20_000,
    )
    receipt_reversal = ReverseDepositReceiptCommand(
        uuid4(), uuid4(), receipt_id, "Verified duplicate receipt"
    )
    reversed_receipts = concurrent(lambda: service.reverse_receipt(receipt_reversal, actor=actor))
    assert reversed_receipts[0] == reversed_receipts[1]

    service2, actor2, lease2, approval2, day2 = setup_signed_pet_lease(migrated_database_url)
    deposit2, _ = create_pet(service2, actor2, lease2, approval2, day2)
    seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=deposit2,
        actor_id=service2.actor_id,
        amount_usd_cents=20_000,
    )
    terminate_for_disposition(migrated_database_url, service2, lease2, date.today())
    disposition = RecordDepositDispositionCommand(
        uuid4(),
        uuid4(),
        deposit2,
        lease2,
        5_000,
        date.today(),
        "Approved Lease outcome",
        context=disposition_context(migrated_database_url, deposit2),
    )
    record_disposition_as_owner(service2, disposition, actor=actor2)
    disposition_reversal = ReverseDepositDispositionCommand(
        uuid4(), uuid4(), disposition.disposition_id, "Correct evidence", "CASE-038"
    )
    reversed_dispositions = concurrent(
        lambda: reverse_disposition_as_owner(service2, disposition_reversal, actor=actor2)
    )
    assert reversed_dispositions[0] == reversed_dispositions[1]
    with psycopg.connect(migrated_database_url) as evidence:
        assert evidence.execute(
            "SELECT id,action FROM app.audit_events WHERE id IN (%s,%s,%s) ORDER BY action",
            (
                create.deposit_id,
                receipt_reversal.reversal_id,
                disposition_reversal.reversal_id,
            ),
        ).fetchall() == [
            (disposition_reversal.reversal_id, "deposit.disposition.reversed"),
            (create.deposit_id, "deposit.pet.created"),
            (receipt_reversal.reversal_id, "deposit.receipt.reversed"),
        ]


def test_security_and_pet_deposits_for_one_lease_keep_separate_balances_and_history(
    migrated_database_url: str,
) -> None:
    move_service, move_actor, move_command, security_deposit_id = setup_move_in(
        migrated_database_url
    )
    move_service.complete(move_command, actor=move_actor)
    actor_id = move_service.actor_id
    property_id = move_service.property_id
    with psycopg.connect(migrated_database_url) as connection:
        approval_id = uuid4()
        connection.execute(
            "INSERT INTO app.lease_pet_approvals("
            "id,lease_id,approved_date,deposit_required_by_signed_terms,pet_description,"
            "approved_at,approved_by) VALUES (%s,%s,%s,true,'Approved dog',"
            "clock_timestamp(),%s)",
            (approval_id, move_command.lease_id, date.today(), actor_id),
        )
        connection.commit()
    service = PostgresDepositService(financial_database_url(), property_id, actor_id)
    authenticated = deposit_actor(actor_id, property_id)
    pet_deposit_id, _ = create_pet(
        service, authenticated, move_command.lease_id, approval_id, date.today()
    )
    seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=pet_deposit_id,
        actor_id=actor_id,
        amount_usd_cents=20_000,
    )
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            pet_deposit_id,
            DepositAdjustmentType.INCREASE,
            2_500,
            date.today(),
            "Pet terms adjustment",
        ),
        actor=authenticated,
    )
    with psycopg.connect(financial_database_url()) as financial:
        security = financial.execute(
            "SELECT app.deposit_snapshot(%s)", (security_deposit_id,)
        ).fetchone()
        pet = financial.execute("SELECT app.deposit_snapshot(%s)", (pet_deposit_id,)).fetchone()
    assert security is not None and pet is not None
    assert security[0]["deposit_type"] == "SECURITY"
    assert security[0]["required_usd_cents"] == 50_000
    assert security[0]["received_usd_cents"] == 50_000
    assert pet[0]["deposit_type"] == "PET"
    assert pet[0]["required_usd_cents"] == 22_500
    assert pet[0]["received_usd_cents"] == 20_000
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.deposit_required_amount_adjustments WHERE deposit_id=%s",
            (security_deposit_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT count(*) FROM app.deposit_required_amount_adjustments WHERE deposit_id=%s",
            (pet_deposit_id,),
        ).fetchone() == (1,)


def test_lease_disposition_and_reversal_are_bounded_idempotent_and_auditable(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, day = setup_signed_pet_lease(migrated_database_url)
    deposit_id, _ = create_pet(service, actor, lease_id, approval_id, day)
    seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=deposit_id,
        actor_id=service.actor_id,
        amount_usd_cents=20_000,
    )
    terminate_for_disposition(migrated_database_url, service, lease_id, date.today())
    # V1-056 slice 6: the forfeiture is a draft confirmed under financial.approve and covers the
    # whole held Pet Deposit (BR-DEP-022); a repeat replays both steps. Sub-slice 6b: the
    # reversal is a draft confirmed under financial.approve as well.
    key, disposition = uuid4(), uuid4()
    disposed = forfeit_through_draft(
        service,
        deposit_id,
        disposition_id=disposition,
        idempotency_key=key,
        reason="Approved non-refundable Lease outcome",
    )
    assert disposed.deposit_disposition_id == disposition
    assert disposed.held_refundable_usd_cents == 0
    assert (
        forfeit_through_draft(
            service,
            deposit_id,
            disposition_id=disposition,
            idempotency_key=key,
            reason="Approved non-refundable Lease outcome",
        )
        == disposed
    )
    reversed_snapshot = reverse_through_draft(
        service,
        disposition,
        reason="Authorized correction",
        evidence_reference="case-review-37",
    )
    assert reversed_snapshot.deposit_disposition_reversal_id is not None
    assert reversed_snapshot.held_refundable_usd_cents == 20_000
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT governing_reservation_id,source_lifecycle_event_id,governing_lease_id "
            "FROM app.deposit_dispositions WHERE id=%s",
            (disposition,),
        ).fetchone() == (None, None, lease_id)


def test_concurrent_lease_dispositions_cannot_exceed_one_held_balance(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, day = setup_signed_pet_lease(migrated_database_url)
    deposit_id, _ = create_pet(service, actor, lease_id, approval_id, day)
    seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=deposit_id,
        actor_id=service.actor_id,
        amount_usd_cents=20_000,
    )
    terminate_for_disposition(migrated_database_url, service, lease_id, date.today())
    barrier = Barrier(2)

    def attempt() -> str:
        barrier.wait()
        try:
            record_disposition_as_owner(
                service,
                RecordDepositDispositionCommand(
                    uuid4(),
                    uuid4(),
                    deposit_id,
                    lease_id,
                    15_000,
                    date.today(),
                    "Concurrent approved disposition",
                    context=disposition_context(migrated_database_url, deposit_id),
                ),
                actor=actor,
            )
        except (DepositInvalidError, DepositConflictError):
            return "invalid"
        return "disposed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: attempt(), range(2))) == ["disposed", "invalid"]
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*),sum(amount_usd_cents) FROM app.deposit_dispositions "
            "WHERE deposit_id=%s",
            (deposit_id,),
        ).fetchone() == (1, 15_000)


def test_storage_triggers_reject_negative_required_amount_and_dependent_receipt_reversal(
    migrated_database_url: str,
) -> None:
    service, actor, lease_id, approval_id, day = setup_signed_pet_lease(migrated_database_url)
    deposit_id, _ = create_pet(service, actor, lease_id, approval_id, day)
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(psycopg.Error) as negative:
            owner.execute(
                "INSERT INTO app.deposit_required_amount_adjustments("
                "id,deposit_id,adjustment_type,amount_usd_cents,effective_date,reason,"
                "occurred_at,actor_id,authorization_reference) VALUES "
                "(%s,%s,'DECREASE',20001,%s,'Invalid direct decrease',clock_timestamp(),%s,%s)",
                (uuid4(), deposit_id, day, service.actor_id, DEPOSIT_MANAGE_CAPABILITY),
            )
        assert negative.value.sqlstate == "23514"
        owner.rollback()
    receipt_id = seed_historical_deposit_receipt(
        migrated_database_url,
        deposit_id=deposit_id,
        actor_id=service.actor_id,
        amount_usd_cents=20_000,
    )
    terminate_for_disposition(migrated_database_url, service, lease_id, date.today())
    record_disposition_as_owner(
        service,
        RecordDepositDispositionCommand(
            uuid4(),
            uuid4(),
            deposit_id,
            lease_id,
            1_000,
            date.today(),
            "Approved disposition",
            context=disposition_context(migrated_database_url, deposit_id),
        ),
        actor=actor,
    )
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(psycopg.Error) as dependent:
            owner.execute(
                "INSERT INTO app.deposit_receipt_reversals("
                "id,deposit_receipt_id,reason,occurred_at,actor_id,authorization_reference) "
                "VALUES (%s,%s,'Invalid dependent reversal',clock_timestamp(),%s,%s)",
                (uuid4(), receipt_id, service.actor_id, DEPOSIT_CORRECT_CAPABILITY),
            )
        assert dependent.value.sqlstate == "55000"


def test_deposit_acl_uses_only_financial_command_role_and_withholds_receipt_recording(
    migrated_database_url: str,
) -> None:
    del migrated_database_url
    superseded_signature = (
        "app.create_pet_deposit(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)"
    )
    mutation_signature = (
        "app.create_pet_deposit_v2(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)"
    )
    with psycopg.connect(runtime_database_url()) as runtime:
        assert runtime.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE'),"
            "has_function_privilege(current_user,'app.deposit_snapshot(uuid)','EXECUTE'),"
            "has_table_privilege(current_user,'app.deposit_commands','INSERT'),"
            "to_regprocedure("
            "'app.record_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,"
            "timestamptz,text,text)') IS NULL",
            (superseded_signature,),
        ).fetchone() == (False, True, False, True)
    with psycopg.connect(financial_database_url()) as financial:
        assert financial.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE'),"
            "has_function_privilege(current_user,%s,'EXECUTE'),"
            "has_table_privilege(current_user,'app.deposit_commands','INSERT'),"
            "has_table_privilege(current_user,'app.deposit_receipts','INSERT')",
            (superseded_signature, mutation_signature),
        ).fetchone() == (False, True, False, False)


def test_undisclosed_pet_warning_does_not_create_deposit_or_terminate_lease(
    migrated_database_url: str,
) -> None:
    service, _, lease_id, _, _ = setup_signed_pet_lease(
        migrated_database_url, requires_deposit=False
    )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            """
            INSERT INTO app.lease_violation_warnings(
                id,lease_id,warning_sequence,violation_date,warning_date,
                violation_description,lease_provision,communication_record,
                occurred_at,actor_id
            ) VALUES (%s,%s,1,%s,%s,'Undisclosed pet requires approval',
                'Signed Lease pet terms','Customer informed; approval required',
                clock_timestamp(),%s)
            """,
            (uuid4(), lease_id, date(2027, 6, 1), date(2027, 6, 1), service.actor_id),
        )
        connection.commit()
        assert connection.execute(
            "SELECT status FROM app.leases WHERE id=%s", (lease_id,)
        ).fetchone() == ("SIGNED",)
        assert connection.execute(
            "SELECT count(*) FROM app.deposits WHERE lease_id=%s", (lease_id,)
        ).fetchone() == (0,)
