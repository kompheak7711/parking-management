"""Real PostgreSQL and HTTP coverage for corrected bounded V1-038 workflows."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from fastapi.testclient import TestClient

from deposit_receipt_reversal_test_support import approver, reverse_receipt_through_draft
from payment_test_support import seed_deposit_payment
from pre_settlement_test_support import pre_settlement_database  # noqa: F401
from property_rental.app import create_app
from property_rental.customer_api import PostgresCustomerResourceFlow
from property_rental.deposit import (
    DEPOSIT_REFUND_QUALIFY_CAPABILITY,
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    DepositConflictError,
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordPetDepartureCommand,
    ReverseDepositDispositionCommand,
)
from property_rental.deposit_api import PostgresDepositResourceFlow
from property_rental.deposit_receipt_reversal import DepositReceiptReversalService
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.reservation_deposit_draft import (
    RecordReservationDepositCorrectionDraftCommand,
    ReservationDepositDecision,
    ReservationDepositDraftService,
)
from reservation_deposit_test_support import correct_reservation_outcome
from test_deposit_migration import (
    create_pet,
    financial_database_url,
    runtime_database_url,
    setup_signed_pet_lease,
)
from test_reservation_lifecycle_migration import active_reservation, cancel
from test_reservation_migration import create_reservation


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    value = os.environ.get("MIGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("MIGRATION_DATABASE_URL is required")
    alembic_command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def seed_pet_deposit(
    database_url: str,
) -> tuple[PostgresDepositService, AuthenticatedActor, UUID, UUID]:
    service, actor, lease_id, approval_id, effective_date = setup_signed_pet_lease(database_url)
    deposit_id, _ = create_pet(service, actor, lease_id, approval_id, effective_date)
    receipt_id = uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "INSERT INTO app.deposit_receipts("
            "id,deposit_id,payment_id,amount_usd_cents,occurred_at,actor_id) "
            "VALUES (%s,%s,%s,20000,clock_timestamp(),%s)",
            (
                receipt_id,
                deposit_id,
                seed_deposit_payment(
                    connection, deposit_id=deposit_id, actor_id=service.actor_id, amount=20_000
                ),
                service.actor_id,
            ),
        )
        connection.commit()
    return service, actor, lease_id, deposit_id


def api_actor(actor_id: UUID, property_id: UUID) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            CapabilityGrant(value, scope)
            for value in (
                "deposits.read",
                "deposits.correct",
                DEPOSIT_REFUND_QUALIFY_CAPABILITY,
            )
        ),
    )


def headers(key: UUID | None = None) -> dict[str, str]:
    return {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(key or uuid4()),
    }


def test_split_departure_and_review_are_idempotent_and_create_no_refund(
    migrated_database_url: str,
) -> None:
    service, actor, _, deposit_id = seed_pet_deposit(migrated_database_url)
    departure = RecordPetDepartureCommand(
        uuid4(), uuid4(), deposit_id, date.today(), "Approved pet permanently left"
    )
    first = service.record_pet_departure(departure, actor=actor)
    assert first.pet_departure_id == departure.departure_id
    assert first.refund_qualified is False
    assert service.record_pet_departure(departure, actor=actor) == first

    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        deposit_id,
        0,
        "No unresolved pet obligations",
        "inspection-2026-08-26",
        "Authorized active-Lease exception review",
    )
    qualified = service.qualify_pet_refund_review(review, actor=actor)
    assert qualified.pet_refund_review_id == review.review_id
    assert qualified.refund_qualified is True
    assert service.qualify_pet_refund_review(review, actor=actor) == qualified
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (deposit_id,)
        ).fetchone() == (0,)
        # V1-056 sub-slice 8a-1: app.final_settlements now exists (migration 86); the review
        # still opens no Final Settlement for this Lease.
        assert connection.execute(
            "SELECT count(*) FROM app.final_settlements settlement JOIN app.deposits deposit "
            "ON deposit.lease_id=settlement.lease_id WHERE deposit.id=%s",
            (deposit_id,),
        ).fetchone() == (0,)


def test_departure_without_received_balance_persists_independently(
    migrated_database_url: str,
) -> None:
    service, actor, _, approval_id, effective_date = setup_signed_pet_lease(migrated_database_url)
    deposit_id, _ = create_pet(service, actor, _, approval_id, effective_date)
    command = RecordPetDepartureCommand(
        uuid4(), uuid4(), deposit_id, date.today(), "Approved pet permanently left"
    )
    result = service.record_pet_departure(command, actor=actor)
    assert result.pet_departure_id == command.departure_id
    assert result.held_refundable_usd_cents == 0


def test_concurrent_departures_preserve_one_append_only_fact(
    migrated_database_url: str,
) -> None:
    service, actor, _, deposit_id = seed_pet_deposit(migrated_database_url)
    barrier = Barrier(2)

    def attempt() -> str:
        command = RecordPetDepartureCommand(
            uuid4(), uuid4(), deposit_id, date.today(), "Concurrent verified departure"
        )
        barrier.wait()
        try:
            service.record_pet_departure(command, actor=actor)
            return "created"
        except DepositConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt) for _ in range(2)]
        outcomes = sorted(future.result() for future in futures)
    assert outcomes == ["conflict", "created"]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.lease_pet_departures AS departure "
            "JOIN app.deposits AS deposit ON deposit.pet_approval_id=departure.pet_approval_id "
            "WHERE deposit.id=%s",
            (deposit_id,),
        ).fetchone() == (1,)


def test_concurrent_identical_departure_replays_original_result(
    migrated_database_url: str,
) -> None:
    service, actor, _, deposit_id = seed_pet_deposit(migrated_database_url)
    command = RecordPetDepartureCommand(
        uuid4(), uuid4(), deposit_id, date.today(), "Concurrent replayed departure"
    )
    barrier = Barrier(2)

    def attempt() -> object:
        barrier.wait()
        return service.record_pet_departure(command, actor=actor)

    with ThreadPoolExecutor(max_workers=2) as executor:
        values = [
            future.result() for future in [executor.submit(attempt), executor.submit(attempt)]
        ]
    assert values[0] == values[1]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.lease_pet_departures WHERE id=%s",
            (command.departure_id,),
        ).fetchone() == (1,)


def test_real_http_reads_history_and_splits_departure_from_review(
    migrated_database_url: str,
) -> None:
    service, domain_actor, lease_id, deposit_id = seed_pet_deposit(migrated_database_url)
    actor = api_actor(service.actor_id, service.property_id)
    client = TestClient(
        create_app(
            actor_resolver=lambda _: actor,
            deposit_resource_flow=PostgresDepositResourceFlow(
                runtime_database_url(), financial_database_url()
            ),
        )
    )
    client.cookies.set("__Host-prm_csrf", "csrf")
    listed = client.get(f"/api/v1/leases/{lease_id}/deposits")
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    assert listed.json()["data"][0]["new_receipt_creation_deferred"] is True
    history = client.get(f"/api/v1/deposits/{deposit_id}/ledger?limit=10")
    assert history.status_code == 200
    assert history.json()["data"][0]["event_kind"] == "RECEIPT"

    departure_id = uuid4()
    departure = client.post(
        f"/api/v1/leases/{lease_id}/pet-departures",
        json={
            "departure_id": str(departure_id),
            "deposit_id": str(deposit_id),
            "permanently_left_date": date.today().isoformat(),
            "reason": "Approved pet permanently left",
        },
        headers=headers(),
    )
    assert departure.status_code == 201
    assert departure.json()["data"]["refund_qualified"] is False
    review_id = uuid4()
    review = client.post(
        f"/api/v1/pet-departures/{departure_id}/refund-review",
        json={
            "review_id": str(review_id),
            "deposit_id": str(deposit_id),
            "obligations_reviewed_usd_cents": 0,
            "review_findings": "No unresolved pet obligations",
            "resolution_reference": "inspection-2026-08-26",
            "reason": "Authorized active-Lease exception review",
        },
        headers=headers(),
    )
    assert review.status_code == 201
    assert review.json()["data"]["refund_qualified"] is True
    reloaded = client.get(f"/api/v1/deposits/{deposit_id}")
    assert reloaded.status_code == 200
    assert reloaded.json()["data"]["pet_departure_id"] == str(departure_id)
    assert (
        reloaded.json()["data"]["pet_refund_review_id"]
        == review.json()["data"]["pet_refund_review_id"]
    )
    assert reloaded.json()["data"]["refund_qualified"] is True
    assert (
        client.get(f"/api/v1/leases/{lease_id}/pet-departures").json()["data"][0][
            "refund_review_id"
        ]
        is not None
    )
    refreshed_history = client.get(f"/api/v1/deposits/{deposit_id}/ledger?limit=10").json()["data"]
    departure_event = next(
        item for item in refreshed_history if item["event_kind"] == "PET_DEPARTURE"
    )
    assert departure_event["authorization_reference"] == "deposits.refund.qualify"
    with psycopg.connect(runtime_database_url()) as runtime:
        direct_review = runtime.execute(
            "SELECT * FROM app.pet_refund_review_resource_snapshot(%s)", (review_id,)
        ).fetchone()
        assert direct_review is not None
    review_resource = client.get(f"/api/v1/pet-deposit-refund-reviews/{review_id}")
    assert review_resource.status_code == 200
    assert review_resource.json()["data"]["refundable_usd_cents"] == 20_000
    assert review_resource.json()["data"]["current_refundable_usd_cents"] == 20_000
    with psycopg.connect(migrated_database_url) as evidence:
        receipt_row = evidence.execute(
            "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", (deposit_id,)
        ).fetchone()
        assert receipt_row is not None
        receipt_id = cast(UUID, receipt_row[0])
    reversal_key = uuid4()
    reversal_id = uuid4()
    reversal = client.post(
        f"/api/v1/deposit-receipts/{receipt_id}/reverse",
        json={"reversal_id": str(reversal_id), "reason": "Verified duplicate receipt"},
        headers=headers(reversal_key),
    )
    # Since sub-slice 8r a receipt reversal is a draft: the one-call route answers 409 and the
    # reversal is recorded and confirmed through the draft (owner answer to Q-2026-10-05-22).
    assert reversal.status_code == 409
    assert reversal.json()["error"]["code"] == "DEPOSIT_RECEIPT_REVERSAL_DRAFT_REQUIRED"
    confirmed = reverse_receipt_through_draft(
        financial_database_url(),
        service.property_id,
        service.actor_id,
        receipt_id,
        reason="Verified duplicate receipt",
        reversal_id=reversal_id,
    )
    reversed_body = client.get(f"/api/v1/deposits/{deposit_id}").json()["data"]
    assert reversed_body["pet_departure_id"] == str(departure_id)
    assert reversed_body["pet_refund_review_id"] == str(review_id)
    assert reversed_body["refund_qualified"] is True
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            deposit_id,
            DepositAdjustmentType.INCREASE,
            1_000,
            date.today(),
            "Later signed-term correction",
        ),
        actor=domain_actor,
    )
    # An exact repeat of the confirmation still replays after later Deposit activity.
    draft = cast(dict[str, object], confirmed["draft"])
    assert (
        DepositReceiptReversalService(financial_database_url()).confirm(
            service.property_id,
            receipt_id,
            UUID(str(draft["draft_id"])),
            actor=approver(service.actor_id, service.property_id, "financial.approve"),
        )
        == confirmed
    )
    assert (
        client.get(f"/api/v1/deposits/{deposit_id}").json()["data"]["required_usd_cents"] == 21_000
    )
    after_reversal = client.get(f"/api/v1/pet-deposit-refund-reviews/{review_id}")
    assert after_reversal.json()["data"]["refundable_usd_cents"] == 20_000
    assert after_reversal.json()["data"]["current_refundable_usd_cents"] == 0
    receipt_event = next(
        item
        for item in client.get(f"/api/v1/deposits/{deposit_id}/ledger?limit=10").json()["data"]
        if item["event_kind"] == "RECEIPT"
    )
    assert receipt_event["can_reverse"] is False
    with psycopg.connect(migrated_database_url) as evidence:
        assert evidence.execute(
            "SELECT id,action,authorization_reference,source,outcome FROM app.audit_events "
            "WHERE id IN (%s,%s) ORDER BY action",
            (departure_id, review_id),
        ).fetchall() == [
            (
                departure_id,
                "deposit.pet_departure.recorded",
                "deposits.refund.qualify",
                "API",
                "SUCCEEDED",
            ),
            (
                review_id,
                "deposit.pet_refund.reviewed",
                "deposits.refund.qualify",
                "API",
                "SUCCEEDED",
            ),
        ]


def test_runtime_role_can_read_but_only_financial_role_can_execute_split_commands(
    migrated_database_url: str,
) -> None:
    del migrated_database_url
    signature = (
        "app.record_active_lease_pet_departure(uuid,uuid,uuid,text,uuid,uuid,date,text,text)"
    )
    with psycopg.connect(runtime_database_url()) as connection:
        assert connection.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE'),"
            "has_function_privilege(current_user,'app.deposit_snapshot(uuid)','EXECUTE')",
            (signature,),
        ).fetchone() == (False, True)
    with psycopg.connect(financial_database_url()) as connection:
        assert connection.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE'),"
            "has_table_privilege(current_user,'app.lease_pet_departures','INSERT'),"
            "has_function_privilege(current_user,"
            "'app.qualify_active_lease_pet_refund(uuid,uuid,uuid,text,uuid,uuid,uuid,date,bigint,text,text,text,text)',"
            "'EXECUTE')",
            (signature,),
        ).fetchone() == (True, False, False)
    with psycopg.connect(runtime_database_url()) as connection:
        assert connection.execute(
            "SELECT has_function_privilege(current_user,"
            "'app.deposit_resource_snapshot(uuid)','EXECUTE'),"
            "has_function_privilege(current_user,"
            "'app.pet_refund_review_resource_snapshot(uuid)','EXECUTE'),"
            "has_function_privilege(current_user,"
            "'app.deposit_has_active_application(uuid)','EXECUTE')"
        ).fetchone() == (True, True, True)


def test_future_deposit_application_dependency_is_fail_closed_and_reversal_aware(
    pre_settlement_database: str,  # noqa: F811
) -> None:
    # V1-056 sub-slice 8a-1: migration 86 creates app.deposit_applications, so this contract test
    # of the migration 28 forward check now runs on the schema before it (revision 20261020_85);
    # every assertion is unchanged. The head behavior is tested in test_final_settlement_migration.
    migrated_database_url = pre_settlement_database
    _, _, _, deposit_id = seed_pet_deposit(migrated_database_url)
    application_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT to_regclass('app.deposit_applications'),"
            "to_regclass('app.deposit_application_reversals')"
        ).fetchone() == (None, None)
        owner.execute(
            "CREATE TABLE app.deposit_applications(id uuid PRIMARY KEY,deposit_id uuid NOT NULL)"
        )
        owner.execute(
            "CREATE TABLE app.deposit_application_reversals("
            "id uuid PRIMARY KEY,deposit_application_id uuid NOT NULL UNIQUE)"
        )
        owner.execute(
            "INSERT INTO app.deposit_applications(id,deposit_id) VALUES (%s,%s)",
            (application_id, deposit_id),
        )
        assert owner.execute(
            "SELECT app.deposit_has_active_application(%s)", (deposit_id,)
        ).fetchone() == (True,)
        owner.execute(
            "INSERT INTO app.deposit_application_reversals(id,deposit_application_id) "
            "VALUES (%s,%s)",
            (uuid4(), application_id),
        )
        assert owner.execute(
            "SELECT app.deposit_has_active_application(%s)", (deposit_id,)
        ).fetchone() == (False,)
        owner.rollback()


def test_customer_financial_summary_reads_bounded_separate_deposit_liabilities(
    migrated_database_url: str,
) -> None:
    _, _, _, deposit_id = seed_pet_deposit(migrated_database_url)
    with psycopg.connect(migrated_database_url) as owner:
        row = owner.execute(
            "SELECT customer_id FROM app.deposits WHERE id=%s", (deposit_id,)
        ).fetchone()
        assert row is not None
        customer_id = cast(UUID, row[0])
    summary = PostgresCustomerResourceFlow(runtime_database_url()).financial_summary(
        customer_id, deposit_limit=50, deposit_cursor=None
    )
    assert summary["source_status"] == "PARTIALLY_AVAILABLE"
    assert cast(dict[str, str], summary["source_availability"])["deposits"] == "AVAILABLE"
    liabilities = cast(list[dict[str, object]], summary["deposit_liabilities"])
    assert len(liabilities) == 1
    assert liabilities[0]["deposit_id"] == str(deposit_id)
    assert liabilities[0]["deposit_type"] == "PET"
    assert liabilities[0]["reservation_id"] is None
    assert liabilities[0]["required_usd_cents"] == 20_000
    assert liabilities[0]["received_usd_cents"] == 20_000
    assert liabilities[0]["held_refundable_usd_cents"] == 20_000
    assert liabilities[0]["outstanding_required_usd_cents"] == 0
    assert liabilities[0]["lease_id"] is not None
    assert liabilities[0]["pet_approval_id"] is not None


def test_ledger_preserves_backdated_required_adjustment_effective_date(
    migrated_database_url: str,
) -> None:
    service, actor, _, deposit_id = seed_pet_deposit(migrated_database_url)
    effective_date = date.today() - timedelta(days=2)
    adjustment_id = uuid4()
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            adjustment_id,
            deposit_id,
            DepositAdjustmentType.INCREASE,
            1_000,
            effective_date,
            "Backdated signed-term correction",
        ),
        actor=actor,
    )
    event = next(
        item
        for item in PostgresDepositResourceFlow(runtime_database_url())
        .ledger(deposit_id, limit=100, cursor=None)
        .items
        if item.event_id == adjustment_id
    )
    assert event.effective_date == effective_date
    assert event.occurred_at.date() > effective_date
    assert event.reversal_eligible is False


def test_customer_deposit_summary_aggregates_all_rows_and_pages_newest_first(
    migrated_database_url: str,
) -> None:
    service, _, _, pet_deposit_id = seed_pet_deposit(migrated_database_url)
    with psycopg.connect(migrated_database_url) as owner:
        source = owner.execute(
            "SELECT lease.primary_tenant_id,unit.property_id "
            "FROM app.deposits AS deposit "
            "JOIN app.leases AS lease ON lease.id=deposit.lease_id "
            "JOIN app.units AS unit ON unit.id=lease.unit_id WHERE deposit.id=%s",
            (pet_deposit_id,),
        ).fetchone()
        assert source is not None
        customer_id, property_id = cast(UUID, source[0]), cast(UUID, source[1])
        unit_id = uuid4()
        owner.execute(
            "INSERT INTO app.units(id,property_id,unit_number,floor,unit_type,status,"
            "created_by,updated_by) VALUES (%s,%s,%s,'2','ONE_BEDROOM','VACANT',%s,%s)",
            (
                unit_id,
                property_id,
                f"SUMMARY-{unit_id.hex[:12]}",
                service.actor_id,
                service.actor_id,
            ),
        )
        create_reservation(
            owner,
            actor_id=service.actor_id,
            property_id=property_id,
            unit_id=unit_id,
            customer_id=customer_id,
        )
        owner.commit()

    flow = PostgresCustomerResourceFlow(runtime_database_url())
    first = flow.financial_summary(customer_id, deposit_limit=1, deposit_cursor=None)
    aggregate = cast(dict[str, int], first["deposit_aggregate"])
    assert aggregate["count"] == 2
    assert aggregate["required_usd_cents"] == 70_000
    first_page = cast(dict[str, object], first["deposit_liabilities_page"])
    assert isinstance(first_page["next_cursor"], str)
    first_items = cast(list[dict[str, object]], first["deposit_liabilities"])
    assert len(first_items) == 1

    second = flow.financial_summary(
        customer_id,
        deposit_limit=1,
        deposit_cursor=first_page["next_cursor"],
    )
    second_items = cast(list[dict[str, object]], second["deposit_liabilities"])
    assert len(second_items) == 1
    assert second_items[0]["deposit_id"] != first_items[0]["deposit_id"]
    assert cast(dict[str, object], second["deposit_liabilities_page"])["next_cursor"] is None


def test_conflicting_deposit_audit_identity_rolls_back_financial_mutation(
    migrated_database_url: str,
) -> None:
    service, actor, _, deposit_id = seed_pet_deposit(migrated_database_url)
    departure_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        source = owner.execute(
            "SELECT deposit.customer_id,deposit.lease_id,unit.id,unit.property_id "
            "FROM app.deposits AS deposit JOIN app.leases AS lease ON lease.id=deposit.lease_id "
            "JOIN app.units AS unit ON unit.id=lease.unit_id WHERE deposit.id=%s",
            (deposit_id,),
        ).fetchone()
        assert source is not None
        owner.execute(
            "INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,"
            "entity_type,entity_id,reason,authorization_reference,property_id,resulting_state,"
            "correlation_id,source,outcome,customer_id,unit_id,lease_id) "
            "VALUES (%s,clock_timestamp(),current_date,%s,'unrelated.action','deposit',%s,"
            "'unrelated evidence','deposits.refund.qualify',%s,'{}'::jsonb,%s,'API','SUCCEEDED',"
            "%s,%s,%s)",
            (
                departure_id,
                service.actor_id,
                deposit_id,
                source[3],
                uuid4(),
                source[0],
                source[2],
                source[1],
            ),
        )
        owner.commit()
    with pytest.raises(DepositConflictError):
        service.record_pet_departure(
            RecordPetDepartureCommand(
                uuid4(), departure_id, deposit_id, date.today(), "Verified permanent departure"
            ),
            actor=actor,
        )
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.lease_pet_departures WHERE id=%s", (departure_id,)
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT action FROM app.audit_events WHERE id=%s", (departure_id,)
        ).fetchone() == ("unrelated.action",)


def test_ledger_includes_refund_and_refund_correction_history(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    refund_id, correction_id, replacement_id = uuid4(), uuid4(), uuid4()
    with psycopg.connect(financial_database_url()) as financial:
        cancelled = cancel(
            financial,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            outcome_id=refund_id,
            responsibility="PROPERTY",
            property_could_provide_unit=False,
            coordination_reference="CASE-LEDGER",
            refund_number="RF-LEDGER-ORIGINAL",
        )
        financial.commit()
        # V1-056 slice 3b: the correction is a draft confirmed under financial.approve.
        correct_reservation_outcome(
            financial,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            correction_id=correction_id,
            expected_outcome_id=refund_id,
            replacement_outcome_id=replacement_id,
            replacement_refund_number="RF-LEDGER-REPLACEMENT",
            reason="Correct external processing reference",
            evidence_reference="EVIDENCE-LEDGER",
        )
        financial.commit()
    page = PostgresDepositResourceFlow(runtime_database_url()).ledger(
        cast(UUID, cancelled[9]), limit=100, cursor=None
    )
    kinds = {event.event_kind for event in page.items}
    assert "REFUND" in kinds
    assert "REFUND_VALUE_CORRECTION" in kinds
    refunds = [event for event in page.items if event.event_kind == "REFUND"]
    correction = next(
        event for event in page.items if event.event_kind == "REFUND_VALUE_CORRECTION"
    )
    # DL-071 answer 10 (V1-059 part B): each Refund shows the RFD number the database gave it.
    numbers = {event.reference_number for event in refunds}
    assert len(numbers) == 2
    assert all(re.fullmatch(r"RFD\d{6,}", str(number)) for number in numbers)
    assert all(event.currency == "USD" for event in refunds)
    assert all(event.amount_minor is not None for event in refunds)
    assert correction.evidence_reference == "EVIDENCE-LEDGER"
    assert correction.authorization_reference == "reservation_deposits.correct"


def test_reservation_disposition_correction_is_atomic_replay_safe_and_reconstructable(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    disposition_id = uuid4()
    with psycopg.connect(financial_database_url()) as financial:
        disposed = cancel(
            financial,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            outcome_id=disposition_id,
        )
        financial.commit()
    scoped_actor = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {
                CapabilityGrant("reservation_deposits.correct", frozenset({str(property_id)})),
                CapabilityGrant("reservation_deposits.dispose", frozenset({str(property_id)})),
                CapabilityGrant("financial.approve", frozenset({str(property_id)})),
            }
        ),
    )
    flow = PostgresDepositResourceFlow(runtime_database_url(), financial_database_url())
    replacement_id = uuid4()
    correction = ReverseDepositDispositionCommand(
        uuid4(),
        uuid4(),
        disposition_id,
        "Correct customer cancellation evidence",
        "EVIDENCE-RESERVATION-DISPOSITION",
    )
    # V1-056 slice 3b: a Reservation outcome correction is a draft confirmed under
    # financial.approve; the same command replays exactly, also when sent twice at once.
    drafts = ReservationDepositDraftService(runtime_database_url(), financial_database_url())
    draft_command = RecordReservationDepositCorrectionDraftCommand(
        correction.idempotency_key,
        reservation_id,
        disposition_id,
        correction.reversal_id,
        replacement_id,
        correction.reason,
        correction.evidence_reference,
    )
    barrier = Barrier(2)

    def confirmed_correction() -> dict[str, object]:
        draft = drafts.record_correction(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            draft_command,
            actor=scoped_actor,
        )
        return drafts.confirm(
            property_id, reservation_id, UUID(str(draft["draft_id"])), actor=scoped_actor
        )

    def correct(_: int) -> dict[str, object]:
        barrier.wait()
        return confirmed_correction()

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_results = list(executor.map(correct, range(2)))
    assert concurrent_results[0] == concurrent_results[1]
    corrected = concurrent_results[0]
    replay = confirmed_correction()
    assert corrected == replay
    client = TestClient(
        create_app(actor_resolver=lambda _: scoped_actor, deposit_resource_flow=flow)
    )
    client.cookies.set("__Host-prm_csrf", "csrf")
    correction_payload = {
        "reversal_id": str(correction.reversal_id),
        "replacement_disposition_id": str(replacement_id),
        "expected_reservation_version": cast(int, disposed[6]),
        "reason": correction.reason,
        "evidence_reference": correction.evidence_reference,
    }
    http_replay = client.post(
        f"/api/v1/deposit-dispositions/{disposition_id}/reverse",
        json=correction_payload,
        headers=headers(correction.idempotency_key),
    )
    changed_http_replay = client.post(
        f"/api/v1/deposit-dispositions/{disposition_id}/reverse",
        json={**correction_payload, "reason": "Changed correction evidence"},
        headers=headers(correction.idempotency_key),
    )
    # The earlier one-call correction route records nothing now.
    assert http_replay.status_code == 409
    assert http_replay.json()["error"]["code"] == "RESERVATION_DEPOSIT_DRAFT_REQUIRED"
    assert changed_http_replay.status_code == 409
    assert changed_http_replay.json()["error"]["code"] == "RESERVATION_DEPOSIT_DRAFT_REQUIRED"
    reservation_result = cast(dict[str, object], corrected["reservation"])
    assert reservation_result["outcome_id"] == str(replacement_id)
    draft_result = cast(dict[str, dict[str, object]], corrected["draft"])
    assert draft_result["payload"]["correction_id"] == str(correction.reversal_id)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT deposit_disposition_id FROM app.deposit_disposition_reversals WHERE id=%s",
            (correction.reversal_id,),
        ).fetchone() == (disposition_id,)
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_dispositions WHERE id IN (%s,%s)",
            (disposition_id, replacement_id),
        ).fetchone() == (2,)
    events = (
        PostgresDepositResourceFlow(runtime_database_url())
        .ledger(cast(UUID, disposed[9]), limit=100, cursor=None)
        .items
    )
    original = next(event for event in events if event.event_id == disposition_id)
    replacement = next(event for event in events if event.event_id == replacement_id)
    receipt = next(event for event in events if event.event_kind == "RECEIPT")
    assert original.effective_date is not None
    assert original.reversal_eligible is False
    assert replacement.effective_date == original.effective_date
    assert replacement.reversal_eligible is True
    assert receipt.reversal_eligible is False
