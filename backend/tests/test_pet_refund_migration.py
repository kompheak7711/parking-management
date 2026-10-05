"""Qualified Pet Refunds reuse approved evidence and conserve Deposit history."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from time import monotonic, sleep
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection
from psycopg.conninfo import make_conninfo

from deposit_receipt_reversal_test_support import approver as receipt_approver
from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from property_rental.deposit import (
    DepositInvalidError,
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordPetDepartureCommand,
    ReverseDepositReceiptCommand,
)
from property_rental.deposit_api import PostgresDepositResourceFlow, _ledger_body
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalService,
    RecordDepositReceiptReversalCommand,
)
from property_rental.financial_draft import FinancialDraftService
from property_rental.refund import (
    CreatePetRefundCommand,
    RefundConflictError,
    RefundIdempotencyKeyReused,
    RefundNotFoundError,
    RefundService,
    RefundUnavailableError,
    ReverseRefundCorrectionCommand,
)
from refund_test_support import approver as refund_approver
from refund_test_support import cash, create_pet_refund
from test_billing_service_migration import admin_database_url
from test_credit_migration import actor
from test_deposit_api_migration import seed_pet_deposit
from test_deposit_migration import financial_database_url, runtime_database_url
from test_move_in_migration import setup_move_in
from test_refund_migration import correct, insert_event, refund
from test_refund_service_migration import corrections, refund_id, returned, service
from test_reservation_migration import migrated_database_url  # noqa: F401


def qualified(
    database_url: str, *, findings: str | None = None
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    deposits, human, lease, deposit = seed_pet_deposit(database_url)
    departure = RecordPetDepartureCommand(
        uuid4(), uuid4(), deposit, date.today(), "Pet permanently left"
    )
    deposits.record_pet_departure(departure, actor=human)
    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        deposit,
        30000,
        findings or "All valid pet costs resolved separately; liability is not capped by Deposit",
        "Synthetic inspection and resolution evidence",
        "Qualified Pet exception",
    )
    deposits.qualify_pet_refund_review(review, actor=human)
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT customer_id FROM app.deposits WHERE id=%s", (deposit,)
        ).fetchone()
        assert row is not None
        customer = UUID(str(row[0]))
    return deposits.actor_id, deposits.property_id, customer, lease, deposit, review.review_id


def command(deposit: UUID, review: UUID, amount: int = 15000) -> CreatePetRefundCommand:
    return CreatePetRefundCommand(
        uuid4(), deposit, review, amount, "Return qualified remaining Pet Deposit"
    )


def receipt_reversal(
    connection: Connection[tuple[object, ...]],
    human: UUID,
    deposit: UUID,
    *,
    at: datetime | None = None,
) -> None:
    receipt = connection.execute(
        "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", (deposit,)
    ).fetchone()
    assert receipt is not None
    insert_event(
        connection,
        "deposit_receipt_reversals",
        {
            "id": uuid4(),
            "deposit_receipt_id": receipt[0],
            "reason": "Correct synthetic receipt",
            "occurred_at": at or datetime.now(UTC),
            "actor_id": human,
            "authorization_reference": "deposits.correct",
        },
    )


def test_pet_refund_reuses_review_preserves_lease_and_exact_replay_audit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, lease, deposit, review = qualified(migrated_database_url)
    creator = actor(human, prop, "refunds.create")
    before = service().pet_source(prop, deposit, review, actor=creator)
    assert before["available_usd_cents"] == 20000 and before["eligible"] is True
    request = command(deposit, review)
    result = create_pet_refund(service(), prop, request, actor=creator)
    identity = refund_id(result)
    assert create_pet_refund(service(), prop, request, actor=creator) == result
    with pytest.raises(RefundIdempotencyKeyReused):
        create_pet_refund(service(), prop, replace(request, amount_usd_cents=14999), actor=creator)
    assert service().get(prop, identity, actor=actor(human, prop, "refunds.read")) == result
    assert cast(dict[str, object], result["refund"])["recipient_customer_id"] == str(customer)
    assert cast(dict[str, object], result["pet_refund_review"])["id"] == str(review)
    assert (
        cast(dict[str, object], result["pet_refund_review"])["obligations_reviewed_usd_cents"]
        == 30000
    )
    assert cast(dict[str, object], result["pet_departure"])["lease_id"] == str(lease)
    assert service().pet_source(prop, deposit, review, actor=creator)["available_usd_cents"] == 5000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT status FROM app.leases WHERE id=%s", (lease,)
        ).fetchone() == ("SIGNED",)
        assert connection.execute(
            "SELECT count(*) FROM app.pet_deposit_refund_reviews WHERE pet_deposit_id=%s",
            (deposit,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_dispositions WHERE deposit_id=%s", (deposit,)
        ).fetchone() == (0,)
        # V1-056 sub-slice 8a-1: both tables exist since migration 86; the Pet Refund still
        # opens no Final Settlement and records no Deposit application.
        assert connection.execute(
            "SELECT (SELECT count(*) FROM app.final_settlements settlement JOIN app.deposits d "
            "ON d.lease_id=settlement.lease_id WHERE d.id=%s),"
            "(SELECT count(*) FROM app.deposit_applications WHERE deposit_id=%s)",
            (deposit, deposit),
        ).fetchone() == (0, 0)
        assert connection.execute(
            "SELECT property_id,customer_id,lease_id,authorization_reference FROM app.audit_events "
            "WHERE entity_id=%s AND action='refund.created'",
            (identity,),
        ).fetchone() == (prop, customer, lease, "refunds.create")


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_review",
        "wrong_review",
        "wrong_property",
        "wrong_customer",
        "overspend",
        "backdated",
        "authorization",
        "terminated",
    ],
)
def test_pet_refund_rejects_unqualified_scope_amount_and_chronology(
    migrated_database_url: str,  # noqa: F811
    invalid: str,
) -> None:
    human, _prop, customer, lease, deposit, review = qualified(migrated_database_url)
    if invalid == "wrong_property":
        unknown = uuid4()
        with pytest.raises(RefundNotFoundError):
            create_pet_refund(
                service(),
                unknown,
                command(deposit, review),
                actor=actor(human, unknown, "refunds.create"),
            )
        return
    if invalid == "wrong_review":
        _, _, _, _, _, review = qualified(migrated_database_url)
    if invalid == "terminated":
        with psycopg.connect(migrated_database_url) as connection:
            connection.execute(
                "UPDATE app.leases SET status='TERMINATED',terminated_at=clock_timestamp(),"
                "actual_termination_date=CURRENT_DATE,version=version+1,updated_at=clock_timestamp(),"
                "termination_reason='Synthetic authorized termination',updated_by=%s WHERE id=%s",
                (human, lease),
            )
    overrides: dict[str, object] = {"source_deposit_id": deposit, "pet_refund_review_id": review}
    if invalid == "missing_review":
        overrides["pet_refund_review_id"] = None
    if invalid == "wrong_customer":
        overrides["recipient_customer_id"] = uuid4()
    if invalid == "backdated":
        overrides["processed_at"] = datetime.now(UTC) - timedelta(days=1)
    if invalid == "authorization":
        overrides["authorization_reference"] = "deposits.refund.qualify"
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            refund(
                connection,
                human,
                customer,
                amount=20001 if invalid == "overspend" else 1000,
                overrides=overrides,
            )
            connection.commit()
        connection.rollback()
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (deposit,)
        ).fetchone() == (0,)


def test_departure_alone_and_security_deposit_never_qualify_for_active_refund(
    migrated_database_url: str,  # noqa: F811
) -> None:
    deposits, human, _, deposit = seed_pet_deposit(migrated_database_url)
    departure = RecordPetDepartureCommand(
        uuid4(), uuid4(), deposit, date.today(), "Pet permanently left"
    )
    deposits.record_pet_departure(departure, actor=human)
    creator = actor(deposits.actor_id, deposits.property_id, "refunds.create")
    with pytest.raises(RefundNotFoundError):
        create_pet_refund(
            service(), deposits.property_id, command(deposit, departure.departure_id), actor=creator
        )
    _, _, _, _, _, review = qualified(migrated_database_url)
    move_service, move_actor, move_command, security = setup_move_in(migrated_database_url)
    move_service.complete(move_command, actor=move_actor)
    security_creator = actor(move_service.actor_id, move_service.property_id, "refunds.create")
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT deposit.deposit_type,deposit.lease_id,lease.status,unit.property_id,"
            "deposit.customer_id=lease.primary_tenant_id,"
            "app.deposit_held_value_at(deposit.id,'infinity') "
            "FROM app.deposits deposit JOIN app.leases lease ON lease.id=deposit.lease_id "
            "JOIN app.units unit ON unit.id=lease.unit_id WHERE deposit.id=%s",
            (security,),
        ).fetchone() == (
            "SECURITY",
            move_command.lease_id,
            "SIGNED",
            move_service.property_id,
            True,
            50000,
        )
    with pytest.raises(RefundNotFoundError):
        service().pet_source(move_service.property_id, security, review, actor=security_creator)
    with pytest.raises(RefundNotFoundError):
        create_pet_refund(
            service(), move_service.property_id, command(security, review), actor=security_creator
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (security,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT status FROM app.leases WHERE id=%s", (move_command.lease_id,)
        ).fetchone() == ("SIGNED",)


def test_pet_verified_returns_reconcile_receipt_ledger_eligibility_and_reversal(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, deposit, review = qualified(migrated_database_url)
    flow = PostgresDepositResourceFlow(runtime_database_url(), financial_database_url())
    corrector = actor(human, prop, "deposits.correct")
    # The earlier one-call reversal runs as the owner: its own rules are the subject here.
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    reader = actor(human, prop, "deposits.read")

    def receipt() -> tuple[UUID, bool]:
        event = next(
            item
            for item in flow.ledger(deposit, limit=100, cursor=None).items
            if item.event_kind == "RECEIPT"
        )
        assert _ledger_body(event, reader, prop)["can_reverse"] is False
        # Since sub-slice 8r a receipt reversal is a draft: no one-call reverse is offered.
        assert _ledger_body(event, corrector, prop)["can_reverse"] is False
        return event.event_id, event.reversal_eligible

    receipt_id, eligible = receipt()
    assert eligible is True
    original = create_pet_refund(
        service(), prop, command(deposit, review, 20000), actor=actor(human, prop, "refunds.create")
    )
    identity = refund_id(original)
    assert receipt() == (receipt_id, False)
    reversal = ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt_id, "Correct receipt")
    with pytest.raises(DepositInvalidError):
        reverse_receipt_as_owner(deposits, reversal, actor=corrector)
    partial = service().verify_usd_return(
        prop, identity, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    assert partial["net_refund_usd_cents"] == 15000
    assert receipt() == (receipt_id, False)
    with pytest.raises(DepositInvalidError):
        reverse_receipt_as_owner(deposits, reversal, actor=corrector)
    full = service().verify_usd_return(
        prop, identity, returned(15000), actor=actor(human, prop, "refunds.correct")
    )
    assert full["net_refund_usd_cents"] == 0
    assert receipt() == (receipt_id, True)
    partial_correction_id = UUID(str(corrections(partial)[0]["id"]))
    undone = service().reverse_correction(
        prop,
        identity,
        partial_correction_id,
        ReverseRefundCorrectionCommand(uuid4(), "Synthetic evidence", "Correct return record"),
        actor=actor(human, prop, "refunds.corrections.reverse"),
    )
    assert undone["net_refund_usd_cents"] == 5000
    assert receipt() == (receipt_id, False)
    with pytest.raises(DepositInvalidError):
        reverse_receipt_as_owner(deposits, reversal, actor=corrector)
    service().verify_usd_return(
        prop, identity, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    assert receipt() == (receipt_id, True)
    reversed_snapshot = reverse_receipt_as_owner(deposits, reversal, actor=corrector)
    assert reverse_receipt_as_owner(deposits, reversal, actor=corrector) == reversed_snapshot
    assert receipt() == (receipt_id, False)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT amount_usd_cents FROM app.deposit_receipts WHERE id=%s", (receipt_id,)
        ).fetchone() == (20000,)
        assert connection.execute(
            "SELECT usd_accounting_value_cents FROM app.refunds WHERE id=%s", (identity,)
        ).fetchone() == (20000,)
        assert connection.execute(
            "SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s", (identity,)
        ).fetchone() == (4,)
        assert connection.execute(
            "SELECT app.deposit_held_value_at(%s,'infinity')", (deposit,)
        ).fetchone() == (0,)


def test_pet_verified_return_correction_reversal_and_reused_balance_are_exact(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, deposit, review = qualified(migrated_database_url)
    creator = actor(human, prop, "refunds.create")
    result = create_pet_refund(service(), prop, command(deposit, review, 20000), actor=creator)
    identity = refund_id(result)
    correction = service().verify_usd_return(
        prop, identity, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    event = corrections(correction)[0]
    reversal = ReverseRefundCorrectionCommand(
        uuid4(), "Synthetic reversal evidence", "Correction entered in error"
    )
    reversed_result = service().reverse_correction(
        prop,
        identity,
        UUID(str(event["id"])),
        reversal,
        actor=actor(human, prop, "refunds.corrections.reverse"),
    )
    assert reversed_result["net_refund_usd_cents"] == 20000
    assert (
        service().reverse_correction(
            prop,
            identity,
            UUID(str(event["id"])),
            reversal,
            actor=actor(human, prop, "refunds.corrections.reverse"),
        )
        == reversed_result
    )
    corrected = service().verify_usd_return(
        prop, identity, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    active = corrections(corrected)[0]
    create_pet_refund(service(), prop, command(deposit, review, 5000), actor=creator)
    with pytest.raises(RefundUnavailableError):
        service().reverse_correction(
            prop,
            identity,
            UUID(str(active["id"])),
            replace(reversal, idempotency_key=uuid4()),
            actor=actor(human, prop, "refunds.corrections.reverse"),
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.deposit_held_value_at(%s,'infinity')", (deposit,)
        ).fetchone() == (0,)


def test_deposit_historical_budget_rejects_backdated_receipt_reversal_after_return(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, deposit, review = qualified(migrated_database_url)
    result = create_pet_refund(
        service(), prop, command(deposit, review, 20000), actor=actor(human, prop, "refunds.create")
    )
    instant = datetime.fromisoformat(str(cast(dict[str, object], result["refund"])["processed_at"]))
    service().verify_usd_return(
        prop, refund_id(result), returned(20000), actor=actor(human, prop, "refunds.correct")
    )
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="Deposit historical held balance"):
            receipt_reversal(connection, human, deposit, at=instant + timedelta(microseconds=1))
            connection.commit()
        connection.rollback()
        receipt_reversal(connection, human, deposit)
        connection.commit()
        assert connection.execute(
            "SELECT app.deposit_held_value_at(%s,'infinity')", (deposit,)
        ).fetchone() == (0,)


@pytest.mark.parametrize("isolation", ["read committed", "repeatable read", "serializable"])
@pytest.mark.parametrize("consumer", ["refund", "receipt_reversal"])
def test_pet_deposit_mvcc_guard_rejects_stale_competing_consumers(
    migrated_database_url: str,  # noqa: F811
    isolation: str,
    consumer: str,
) -> None:
    human, prop, customer, _, deposit, review = qualified(migrated_database_url)
    with psycopg.connect(migrated_database_url) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        stale.execute("SET LOCAL statement_timeout='5000ms'")
        stale.execute("SELECT app.deposit_held_value_at(%s,'infinity')", (deposit,))
        create_pet_refund(
            service(), prop, command(deposit, review), actor=actor(human, prop, "refunds.create")
        )
        with pytest.raises(psycopg.Error) as failure:
            if consumer == "refund":
                refund(
                    stale,
                    human,
                    customer,
                    amount=15000,
                    overrides={"source_deposit_id": deposit, "pet_refund_review_id": review},
                )
            else:
                receipt_reversal(stale, human, deposit)
            stale.commit()
        expected = "23514" if consumer == "refund" else "55000"
        assert failure.value.sqlstate == (expected if isolation == "read committed" else "40001")
        stale.rollback()


@pytest.mark.parametrize("competing", ["refund", "receipt_reversal"])
def test_simultaneous_pet_refund_and_deposit_consumers_conserve_value(
    migrated_database_url: str,  # noqa: F811
    competing: str,
) -> None:
    human, _prop, customer, _, deposit, review = qualified(migrated_database_url)
    barrier = Barrier(2)

    def attempt(kind: str) -> str:
        try:
            with psycopg.connect(migrated_database_url) as connection:
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                barrier.wait()
                if kind == "refund":
                    refund(
                        connection,
                        human,
                        customer,
                        amount=15000,
                        overrides={"source_deposit_id": deposit, "pet_refund_review_id": review},
                    )
                else:
                    receipt_reversal(connection, human, deposit)
            return "ok"
        except psycopg.Error as exc:
            return str(exc.sqlstate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["refund", competing]))
    assert outcomes.count("ok") == 1
    assert all(value in {"ok", "23514", "55000"} for value in outcomes)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT app.deposit_held_value_at(%s,'infinity')", (deposit,)
        ).fetchone()
        assert row in {(0,), (5000,)}


def test_pet_return_cannot_restore_reversed_deposit_receipt_for_correction_reversal(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, deposit, review = qualified(migrated_database_url)
    result = create_pet_refund(
        service(), prop, command(deposit, review, 20000), actor=actor(human, prop, "refunds.create")
    )
    identity = refund_id(result)
    correction = service().verify_usd_return(
        prop, identity, returned(20000), actor=actor(human, prop, "refunds.correct")
    )
    with psycopg.connect(migrated_database_url) as connection:
        receipt_reversal(connection, human, deposit)
    with pytest.raises(RefundUnavailableError):
        service().reverse_correction(
            prop,
            identity,
            UUID(str(corrections(correction)[0]["id"])),
            ReverseRefundCorrectionCommand(uuid4(), "Evidence", "Reversal requested"),
            actor=actor(human, prop, "refunds.corrections.reverse"),
        )


def test_pet_helpers_and_guard_state_remain_private_and_financial_role_has_only_command(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname='b_deposit_balance_source' "
            "AND NOT tgisinternal AND tgenabled='O'"
        ).fetchone() == (6,)
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.deposit_serialization_guards',"
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                (role,),
            ).fetchone() == (False,)
            for signature in (
                "app.serialize_deposit_state(uuid)",
                "app.lock_pet_refund_source(uuid,uuid,uuid)",
                "app.pet_refund_qualification(uuid,uuid,uuid)",
            ):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
                ).fetchone() == (False,)
            assert connection.execute(
                "SELECT has_function_privilege(%s,"
                "'app.create_pet_usd_refund(uuid,uuid,uuid,uuid,uuid,bigint,text)','EXECUTE')",
                (role,),
            ).fetchone() == (False,)  # V1-056 slice 3a: only app.confirm_refund_draft calls it


def test_pet_refund_holds_signed_lease_status_until_commit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, _, customer, lease, deposit, review = qualified(migrated_database_url)
    with psycopg.connect(migrated_database_url) as creator:
        refund(
            creator,
            human,
            customer,
            overrides={
                "source_deposit_id": deposit,
                "pet_refund_review_id": review,
            },
        )
        with psycopg.connect(migrated_database_url) as concurrent:
            concurrent.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                concurrent.execute(
                    "UPDATE app.leases SET status='TERMINATED',terminated_at=clock_timestamp(),"
                    "actual_termination_date=CURRENT_DATE,version=version+1,updated_at=clock_timestamp(),"
                    "termination_reason='Synthetic authorized termination',"
                    "updated_by=%s WHERE id=%s",
                    (human, lease),
                )
            concurrent.rollback()
        creator.commit()
        assert creator.execute(
            "SELECT status FROM app.leases WHERE id=%s", (lease,)
        ).fetchone() == ("SIGNED",)


@pytest.mark.parametrize("isolation", ["read committed", "repeatable read", "serializable"])
def test_pet_correction_reversal_cannot_spend_stale_returned_balance(
    migrated_database_url: str,  # noqa: F811
    isolation: str,
) -> None:
    human, prop, _, _, deposit, review = qualified(migrated_database_url)
    creator = actor(human, prop, "refunds.create")
    result = create_pet_refund(service(), prop, command(deposit, review, 20000), actor=creator)
    identity = refund_id(result)
    corrected = service().verify_usd_return(
        prop, identity, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    correction = UUID(str(corrections(corrected)[0]["id"]))
    with psycopg.connect(migrated_database_url) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        stale.execute("SELECT app.deposit_held_value_at(%s,'infinity')", (deposit,))
        create_pet_refund(service(), prop, command(deposit, review, 5000), actor=creator)
        with pytest.raises(psycopg.Error) as failure:
            correct(stale, human, identity, -5000, reverses=correction)
            stale.commit()
        assert failure.value.sqlstate == ("23514" if isolation == "read committed" else "40001")
        stale.rollback()


def test_deposit_receipt_reversal_cannot_precede_its_original_receipt(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, _, _, _, deposit, _ = qualified(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="Deposit reversal cannot predate"):
            receipt_reversal(connection, human, deposit, at=datetime.now(UTC) - timedelta(days=1))
        connection.rollback()


def test_pet_refund_resource_links_retained_narratives_without_unbounded_embedding(
    migrated_database_url: str,  # noqa: F811
) -> None:
    findings = ("Synthetic resolved inspection evidence " * 20000).strip()
    human, prop, _, _, deposit, review = qualified(migrated_database_url, findings=findings)
    result = create_pet_refund(
        service(), prop, command(deposit, review), actor=actor(human, prop, "refunds.create")
    )
    assert result["source"] == {"type": "DEPOSIT", "id": str(deposit), "property_id": str(prop)}
    assert cast(dict[str, object], result["pet_refund_review"])["id"] == str(review)
    assert "review_findings" not in cast(dict[str, object], result["pet_refund_review"])
    assert len(str(result)) < 10000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT review_findings FROM app.pet_deposit_refund_reviews WHERE id=%s", (review,)
        ).fetchone() == (findings,)


def test_a_pet_refund_confirmation_waits_for_a_pending_receipt_reversal_draft(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Owner answer 2 to Q-2026-10-05-23 (V1-056 sub-slice 8a-2): no Refund while the receipt
    may be reversed. Kept in this module, after test_lease_migration, because that earlier
    test counts every Pet Refund review of the shared database."""
    url = migrated_database_url
    human, prop, _, _, deposit, review = qualified(url)

    def value(sql: str, *parameters: object) -> object:
        with psycopg.connect(url) as connection:
            row = connection.execute(sql, parameters).fetchone()
        assert row is not None
        return row[0]

    def held() -> int:
        return int(str(value("SELECT app.deposit_held_value_at(%s,'infinity')", deposit)))

    def decided(draft: UUID) -> int:
        return int(
            str(
                value("SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft)
            )
        )

    amount = held()
    receipt = UUID(str(value("SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", deposit)))
    reversal = DepositReceiptReversalService(financial_database_url()).record(
        prop,
        RecordDepositReceiptReversalCommand(uuid4(), receipt, uuid4(), "Transfer returned"),
        actor=receipt_approver(human, prop, "deposits.correct"),
    )
    creator = actor(human, prop, "refunds.create")
    # Recording the Refund draft stays allowed.
    recorded = service().record_pet_draft(
        prop, command(deposit, review), cash(service(), prop, creator), actor=creator
    )
    draft = UUID(str(recorded["draft_id"]))
    with pytest.raises(RefundConflictError, match="receipt reversal draft"):
        service().confirm_draft(prop, draft, actor=refund_approver(creator, prop))
    assert (decided(draft), held()) == (0, amount)
    assert value("SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", deposit) == 0
    # A rejected receipt reversal draft no longer holds the Refund back.
    FinancialDraftService(runtime_database_url(), financial_database_url()).reject(
        prop,
        UUID(str(reversal["draft_id"])),
        "The transfer was not returned",
        actor=receipt_approver(human, prop, "financial.approve"),
    )
    service().confirm_draft(prop, draft, actor=refund_approver(creator, prop))
    assert held() == amount - 15_000


def test_a_pet_refund_waits_for_a_receipt_reversal_draft_being_recorded(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """V1-056 sub-slice 8a-2 review round 1: the receipt reversal draft recorder locks the
    Deposit row, so a Pet Refund draft recorded and confirmed while that draft is not yet
    committed waits for it and is then refused, instead of paying out."""
    url = migrated_database_url
    human, prop, _, _, deposit, review = qualified(url)
    creator = actor(human, prop, "refunds.create")
    with psycopg.connect(url) as connection:
        receipt = connection.execute(
            "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", (deposit,)
        ).fetchone()
    assert receipt is not None
    name = f"pet-refund-wait-{uuid4().hex[:12]}"
    waiting = RefundService(
        runtime_database_url(), make_conninfo(financial_database_url(), application_name=name)
    )

    def record_and_confirm() -> dict[str, object]:
        recorded = waiting.record_pet_draft(
            prop, command(deposit, review), cash(waiting, prop, creator), actor=creator
        )
        return waiting.confirm_draft(
            prop, UUID(str(recorded["draft_id"])), actor=refund_approver(creator, prop)
        )

    with psycopg.connect(financial_database_url()) as recorder:
        recorder.execute(
            "SELECT app.record_deposit_receipt_reversal_draft(%s,%s,%s,%s,%s,%s,%s)",
            (prop, human, uuid4(), receipt[0], uuid4(), "Transfer returned", "deposits.correct"),
        )
        # Not committed yet: the recorder holds the Deposit row.
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(record_and_confirm)
            with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                deadline = monotonic() + 10
                while monotonic() < deadline and not future.done():
                    # Waiting for the recorder itself, not for some other lock.
                    state = observer.execute(
                        "SELECT wait_event_type,%s=ANY(pg_catalog.pg_blocking_pids(pid)) "
                        "FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (recorder.info.backend_pid, name),
                    ).fetchone()
                    if state is not None and state == ("Lock", True):
                        break
                    sleep(0.02)
                else:
                    pytest.fail("the Pet Refund did not wait for the receipt reversal draft")
            recorder.commit()
            with pytest.raises(RefundConflictError, match="receipt reversal draft"):
                future.result(timeout=30)
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (deposit,)
        ).fetchone() == (0,)


def test_the_deposit_history_reads_a_legacy_combined_qualification_departure(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """A departure recorded by the V1-037 combined qualification has only a
    deposit.pet_refund.qualify command; the head Deposit ledger read takes its authorization
    from that command (the branch test_v1_038_upgrade... checked on revision 37)."""
    url = migrated_database_url
    deposits, _, lease, deposit = seed_pet_deposit(url)
    departure = uuid4()
    with psycopg.connect(url) as connection:
        approval = connection.execute(
            "SELECT pet_approval_id FROM app.deposits WHERE id=%s", (deposit,)
        ).fetchone()
        assert approval is not None
        connection.execute(
            "INSERT INTO app.lease_pet_departures(id,pet_approval_id,lease_id,"
            "permanently_left_date,reason,occurred_at,actor_id) "
            "VALUES (%s,%s,%s,(SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date),"
            "'Pet permanently left',clock_timestamp(),%s)",
            (departure, approval[0], lease, deposits.actor_id),
        )
        connection.execute(
            "INSERT INTO app.deposit_commands(actor_id,property_id,action,idempotency_key,"
            "request_digest,deposit_id,reason,authorization_reference,result_snapshot) "
            "VALUES (%s,%s,'deposit.pet_refund.qualify',%s,%s,%s,'Legacy combined review',"
            "'deposits.refund.qualify',jsonb_build_object('pet_departure_id',%s::text))",
            (deposits.actor_id, deposits.property_id, uuid4(), "b" * 64, deposit, departure),
        )
    events = PostgresDepositResourceFlow(runtime_database_url()).ledger(
        deposit, limit=100, cursor=None
    )
    found = [event for event in events.items if event.event_id == departure]
    assert [(event.event_kind, event.authorization_reference) for event in found] == [
        ("PET_DEPARTURE", "deposits.refund.qualify")
    ]
