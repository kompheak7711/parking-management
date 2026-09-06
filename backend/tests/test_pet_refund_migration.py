"""Qualified Pet Refunds reuse approved evidence and conserve Deposit history."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

from property_rental.deposit import (
    DepositInvalidError,
    QualifyPetDepositRefundReviewCommand,
    RecordPetDepartureCommand,
    ReverseDepositReceiptCommand,
)
from property_rental.deposit_api import PostgresDepositResourceFlow, _ledger_body
from property_rental.refund import (
    CreatePetRefundCommand,
    RefundIdempotencyKeyReused,
    RefundNotFoundError,
    RefundUnavailableError,
    ReverseRefundCorrectionCommand,
)
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
    result = service().create_pet(prop, request, actor=creator)
    identity = refund_id(result)
    assert service().create_pet(prop, request, actor=creator) == result
    with pytest.raises(RefundIdempotencyKeyReused):
        service().create_pet(prop, replace(request, amount_usd_cents=14999), actor=creator)
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
        assert connection.execute(
            "SELECT to_regclass('app.final_settlements'),to_regclass('app.deposit_applications')"
        ).fetchone() == (None, None)
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
            service().create_pet(
                unknown, command(deposit, review), actor=actor(human, unknown, "refunds.create")
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
        service().create_pet(
            deposits.property_id, command(deposit, departure.departure_id), actor=creator
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
        service().create_pet(
            move_service.property_id, command(security, review), actor=security_creator
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
    reader = actor(human, prop, "deposits.read")

    def receipt() -> tuple[UUID, bool]:
        event = next(
            item
            for item in flow.ledger(deposit, limit=100, cursor=None).items
            if item.event_kind == "RECEIPT"
        )
        assert _ledger_body(event, reader, prop)["can_reverse"] is False
        assert _ledger_body(event, corrector, prop)["can_reverse"] is event.reversal_eligible
        return event.event_id, event.reversal_eligible

    receipt_id, eligible = receipt()
    assert eligible is True
    original = service().create_pet(
        prop, command(deposit, review, 20000), actor=actor(human, prop, "refunds.create")
    )
    identity = refund_id(original)
    assert receipt() == (receipt_id, False)
    reversal = ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt_id, "Correct receipt")
    with pytest.raises(DepositInvalidError):
        flow.reverse_receipt(receipt_id, reversal, actor=corrector)
    partial = service().verify_usd_return(
        prop, identity, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    assert partial["net_refund_usd_cents"] == 15000
    assert receipt() == (receipt_id, False)
    with pytest.raises(DepositInvalidError):
        flow.reverse_receipt(receipt_id, reversal, actor=corrector)
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
        flow.reverse_receipt(receipt_id, reversal, actor=corrector)
    service().verify_usd_return(
        prop, identity, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    assert receipt() == (receipt_id, True)
    reversed_snapshot = flow.reverse_receipt(receipt_id, reversal, actor=corrector)
    assert flow.reverse_receipt(receipt_id, reversal, actor=corrector) == reversed_snapshot
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
    result = service().create_pet(prop, command(deposit, review, 20000), actor=creator)
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
    service().create_pet(prop, command(deposit, review, 5000), actor=creator)
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
    result = service().create_pet(
        prop, command(deposit, review, 20000), actor=actor(human, prop, "refunds.create")
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
        service().create_pet(
            prop, command(deposit, review), actor=actor(human, prop, "refunds.create")
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
    result = service().create_pet(
        prop, command(deposit, review, 20000), actor=actor(human, prop, "refunds.create")
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
            ).fetchone() == (role == "prm_financial",)


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
    result = service().create_pet(prop, command(deposit, review, 20000), actor=creator)
    identity = refund_id(result)
    corrected = service().verify_usd_return(
        prop, identity, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    correction = UUID(str(corrections(corrected)[0]["id"]))
    with psycopg.connect(migrated_database_url) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        stale.execute("SELECT app.deposit_held_value_at(%s,'infinity')", (deposit,))
        service().create_pet(prop, command(deposit, review, 5000), actor=creator)
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
    result = service().create_pet(
        prop, command(deposit, review), actor=actor(human, prop, "refunds.create")
    )
    assert result["source"] == {"type": "DEPOSIT", "id": str(deposit), "property_id": str(prop)}
    assert cast(dict[str, object], result["pet_refund_review"])["id"] == str(review)
    assert "review_findings" not in cast(dict[str, object], result["pet_refund_review"])
    assert len(str(result)) < 10000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT review_findings FROM app.pet_deposit_refund_reviews WHERE id=%s", (review,)
        ).fetchone() == (findings,)
