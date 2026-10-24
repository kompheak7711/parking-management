"""Real PostgreSQL coverage for Reservation Deposit drafts (V1-056 slice 3b).

Owner answers of 2026-10-04 (docs/010): Staff cancellation cancels at once and releases the
Unit while the Security Deposit stays held until a financial.approve holder confirms the Refund
or forfeiture draft; the expiry worker never forfeits; outcome corrections are drafts; a bounded
per-Property list shows the Reservations waiting for a Deposit decision; Reservation Refunds go
to the Reservation Customer.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Error

from lease_deposit_forfeiture_test_support import owner_database_url
from property_rental.deposit_api import PostgresDepositResourceFlow
from property_rental.financial_draft import FinancialDraftService
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.refund import RefundMethodChoice
from property_rental.reservation import (
    CancellationResponsibility,
    DepositOutcomeState,
    PostgresReservationService,
    ReservationCancelCommand,
    ReservationExpireCommand,
)
from property_rental.reservation_api import PostgresReservationResourceFlow
from property_rental.reservation_deposit_draft import (
    RecordReservationDepositCorrectionDraftCommand,
    RecordReservationDepositDraftCommand,
    ReservationDepositDecision,
    ReservationDepositDecisionPage,
    ReservationDepositDraftAuthorizationError,
    ReservationDepositDraftConflictError,
    ReservationDepositDraftInvalidError,
    ReservationDepositDraftKeyReused,
    ReservationDepositDraftNotFoundError,
    ReservationDepositDraftService,
)
from reservation_deposit_test_support import cash_method_id
from test_reservation_lifecycle_migration import (
    active_reservation,
    expired_reservation,
    financial_database_url,
    runtime_database_url,
)

NOTE = "Cash handed over at the Property office"


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def person(actor_id: UUID, property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(CapabilityGrant(value, scope) for value in capabilities),
    )


def drafts() -> ReservationDepositDraftService:
    return ReservationDepositDraftService(runtime_database_url(), financial_database_url())


def waiting(property_id: UUID, actor_id: UUID) -> dict[UUID, dict[str, object]]:
    """Every waiting Reservation of the shared test Property, read page by page."""
    reader = person(actor_id, property_id, "reservations.read")
    found: dict[UUID, dict[str, object]] = {}
    page = ReservationDepositDecisionPage(limit=100)
    for _ in range(100):
        value = drafts().awaiting(property_id, actor=reader, page=page)
        for item in cast(list[dict[str, object]], value["items"]):
            found[UUID(str(item["reservation_id"]))] = item
        after = value.get("next_after")
        if after is None:
            return found
        cursor = cast(dict[str, str], after)
        page = ReservationDepositDecisionPage(
            limit=100,
            after_cancelled_at=datetime.fromisoformat(cursor["cancelled_at"]),
            after_id=UUID(cursor["reservation_id"]),
        )
    raise AssertionError("waiting list did not end")


def cancel_by_staff(
    actor_id: UUID,
    property_id: UUID,
    reservation_id: UUID,
    responsibility: CancellationResponsibility = CancellationResponsibility.CUSTOMER,
) -> None:
    service = PostgresReservationService(
        runtime_database_url(), property_id, actor_id, financial_database_url()
    )
    result = service.cancel(
        ReservationCancelCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=reservation_id,
            expected_version=1,
            reason_code="CUSTOMER_WITHDREW"
            if responsibility is CancellationResponsibility.CUSTOMER
            else "PROPERTY_UNABLE_TO_PROVIDE_UNIT",
            responsibility=responsibility,
            property_could_provide_unit=responsibility is CancellationResponsibility.CUSTOMER,
            reason_memo="Approved cancellation reason",
            coordination_reference=None
            if responsibility is CancellationResponsibility.CUSTOMER
            else "CASE-RESERVATION-REFUND",
            authorization_reference="reservations.cancel",
        ),
        actor=person(actor_id, property_id, "reservations.cancel"),
    )
    assert result.deposit_outcome_state is DepositOutcomeState.AWAITING_DECISION
    assert result.outcome_id is None
    assert result.unit_status == "VACANT"


def outcome_rows(migrated_database_url: str, reservation_id: UUID) -> tuple[int, int]:
    with psycopg.connect(migrated_database_url) as verify:
        row = verify.execute(
            """
            SELECT
                (SELECT count(*) FROM app.deposit_dispositions
                 WHERE governing_reservation_id = %s),
                (SELECT count(*) FROM app.refunds AS refund
                 JOIN app.deposits AS deposit ON deposit.id = refund.source_deposit_id
                 WHERE deposit.reservation_id = %s)
            """,
            (reservation_id, reservation_id),
        ).fetchone()
    assert row is not None
    return int(str(row[0])), int(str(row[1]))


def held(reservation_id: UUID) -> int:
    snapshots = PostgresDepositResourceFlow(runtime_database_url()).list_for_reservation(
        reservation_id
    )
    return sum(snapshot.held_refundable_usd_cents for snapshot in snapshots)


def test_staff_cancellation_holds_the_deposit_until_an_approver_confirms_the_forfeiture(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, _, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id)
    held_before = held(reservation_id)
    listed = waiting(property_id, actor_id)[reservation_id]
    assert listed["decision_kind"] == "DEPOSIT_FORFEITURE"
    assert listed["held_usd_cents"] == held_before == 10_000
    assert listed["pending_draft_id"] is None
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)

    staff = person(actor_id, property_id, "reservations.read", "reservation_deposits.dispose")
    outcome_id = uuid4()
    draft = drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(
            uuid4(), reservation_id, outcome_id, "Customer withdrew before move-in"
        ),
        actor=staff,
    )
    draft_id = UUID(str(draft["draft_id"]))
    # A draft has no financial effect (BR-AUTH-010).
    assert draft["state"] == "PENDING"
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)
    assert held(reservation_id) == held_before
    assert waiting(property_id, actor_id)[reservation_id]["pending_draft_id"] == str(draft_id)

    # Staff cannot confirm: the service needs financial.approve, the database the reference.
    with pytest.raises(ReservationDepositDraftAuthorizationError):
        drafts().confirm(property_id, reservation_id, draft_id, actor=staff)
    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(Error) as refused:
            financial.execute(
                "SELECT app.confirm_reservation_deposit_draft(%s,%s,%s,%s,%s)",
                (property_id, actor_id, reservation_id, draft_id, "reservation_deposits.dispose"),
            )
        assert refused.value.sqlstate == "42501"
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)

    approver = person(actor_id, property_id, "financial.approve")
    confirmed = drafts().confirm(property_id, reservation_id, draft_id, actor=approver)
    replayed = drafts().confirm(property_id, reservation_id, draft_id, actor=approver)
    assert confirmed == replayed
    reservation = cast(dict[str, object], confirmed["reservation"])
    assert reservation["outcome_id"] == str(outcome_id)
    assert reservation["deposit_outcome_state"] == "NON_REFUNDABLE_DISPOSITION"
    assert cast(dict[str, object], confirmed["draft"])["state"] == "CONFIRMED"
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT amount_usd_cents, actor_id, authorization_reference, reason "
            "FROM app.deposit_dispositions WHERE id = %s",
            (outcome_id,),
        ).fetchone() == (
            10_000,
            actor_id,
            "reservation_deposits.dispose",
            "Customer withdrew before move-in",
        )
        assert verify.execute(
            "SELECT status FROM app.units WHERE id = %s", (unit_id,)
        ).fetchone() == ("VACANT",)
    assert reservation_id not in waiting(property_id, actor_id)
    assert held(reservation_id) == 0
    resource = PostgresReservationResourceFlow(runtime_database_url()).get(reservation_id)
    assert resource.deposit_outcome_state is DepositOutcomeState.NON_REFUNDABLE_DISPOSITION


def test_expired_reservation_stays_on_the_waiting_list_until_its_draft_is_confirmed(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, _, reservation_id, _ = expired_reservation(setup)
        setup.commit()
    # The expiry command the worker runs; worker runs are keyed by logical date and the
    # shared test Property may already have today's run.
    expired = PostgresReservationService(
        runtime_database_url(), property_id, actor_id, financial_database_url()
    ).expire(
        ReservationExpireCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=reservation_id,
            expected_version=1,
            property_could_provide_unit=True,
            authorization_reference="reservations.cancel",
        ),
        actor=person(actor_id, property_id, "reservations.cancel"),
    )
    assert expired.deposit_outcome_state is DepositOutcomeState.AWAITING_DECISION
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT reservation.status, reservation.cancellation_reason_code, unit.status "
            "FROM app.reservations AS reservation JOIN app.units AS unit "
            "ON unit.id = reservation.unit_id WHERE reservation.id = %s",
            (reservation_id,),
        ).fetchone() == ("CANCELLED", "RESERVATION_EXPIRED", "VACANT")
    # The worker never forfeits (owner answer, 2026-10-04).
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)
    assert waiting(property_id, actor_id)[reservation_id]["decision_kind"] == ("DEPOSIT_FORFEITURE")

    staff = person(actor_id, property_id, "reservation_deposits.dispose")
    approver = person(actor_id, property_id, "financial.approve")
    first = drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(
            uuid4(), reservation_id, uuid4(), "Reservation expired; Unit stayed available"
        ),
        actor=staff,
    )
    first_id = UUID(str(first["draft_id"]))
    assert waiting(property_id, actor_id)[reservation_id]["pending_draft_id"] == str(first_id)
    FinancialDraftService(runtime_database_url(), financial_database_url()).reject(
        property_id, first_id, "Wrong reason text", actor=approver
    )
    # A rejected draft leaves the Reservation waiting, with no pending draft.
    after_reject = waiting(property_id, actor_id)[reservation_id]
    assert after_reject["pending_draft_id"] is None
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)

    second = drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(
            uuid4(), reservation_id, uuid4(), "Reservation expired while the Unit was available"
        ),
        actor=staff,
    )
    assert reservation_id in waiting(property_id, actor_id)
    drafts().confirm(property_id, reservation_id, UUID(str(second["draft_id"])), actor=approver)
    assert reservation_id not in waiting(property_id, actor_id)
    assert outcome_rows(migrated_database_url, reservation_id) == (1, 0)
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT status FROM app.units WHERE id = %s", (unit_id,)
        ).fetchone() == ("VACANT",)


def test_property_cancellation_refund_goes_to_the_reservation_customer_with_method_and_note(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, customer_id, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id, CancellationResponsibility.PROPERTY)
    assert waiting(property_id, actor_id)[reservation_id]["decision_kind"] == "REFUND"
    staff = person(actor_id, property_id, "reservation_deposits.refund")
    method_id = cash_method_id(property_id, actor_id)
    with pytest.raises(ReservationDepositDraftInvalidError):
        drafts().record(
            property_id,
            ReservationDepositDecision.REFUND,
            RecordReservationDepositDraftCommand(
                uuid4(), reservation_id, uuid4(), "Property could not provide the Unit"
            ),
            actor=staff,
        )
    outcome_id = uuid4()
    draft = drafts().record(
        property_id,
        ReservationDepositDecision.REFUND,
        RecordReservationDepositDraftCommand(
            uuid4(),
            reservation_id,
            outcome_id,
            "Property could not provide the Unit",
            RefundMethodChoice(method_id, NOTE),
        ),
        actor=staff,
    )
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)
    drafts().confirm(
        property_id,
        reservation_id,
        UUID(str(draft["draft_id"])),
        actor=person(actor_id, property_id, "financial.approve"),
    )
    with psycopg.connect(migrated_database_url) as verify:
        refund_row = verify.execute(
            "SELECT recipient_customer_id, usd_accounting_value_cents, refund_currency, "
            "refund_number, processed_by, authorization_reference, "
            "to_char(processed_at AT TIME ZONE 'Asia/Phnom_Penh', 'YY') "
            "FROM app.refunds WHERE id = %s",
            (outcome_id,),
        ).fetchone()
        assert refund_row is not None
        assert refund_row[:3] == (customer_id, 10_000, "USD")
        assert refund_row[4:6] == (actor_id, "reservation_deposits.refund")
        # DL-071 answer 10 (V1-059 part B): the database gives the Refund its RFD number when
        # the draft is confirmed; the draft carried only an internal reference.
        assert re.fullmatch(rf"RFD{refund_row[6]}\d{{4,}}", str(refund_row[3]))
        assert verify.execute(
            "SELECT draft_id, refund_method_id, reference_note "
            "FROM app.refund_draft_details WHERE refund_id = %s",
            (outcome_id,),
        ).fetchone() == (UUID(str(draft["draft_id"])), method_id, NOTE)
    assert reservation_id not in waiting(property_id, actor_id)


def test_reservation_deposit_draft_refuses_wrong_kind_second_draft_and_used_number(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        _, _, _, _, active_id = active_reservation(setup)
        _, _, _, _, refunded_id = active_reservation(setup)
        setup.commit()
    staff = person(
        actor_id,
        property_id,
        "reservation_deposits.dispose",
        "reservation_deposits.refund",
    )
    with pytest.raises(ReservationDepositDraftInvalidError):
        drafts().record(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositDraftCommand(uuid4(), active_id, uuid4(), "Not cancelled"),
            actor=staff,
        )
    cancel_by_staff(actor_id, property_id, reservation_id, CancellationResponsibility.PROPERTY)
    method = RefundMethodChoice(cash_method_id(property_id, actor_id), NOTE)
    # The kind follows the cancellation responsibility (BR-RES-021, BR-RES-022).
    with pytest.raises(ReservationDepositDraftInvalidError):
        drafts().record(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositDraftCommand(uuid4(), reservation_id, uuid4(), "Wrong kind"),
            actor=staff,
        )
    cancel_by_staff(actor_id, property_id, refunded_id, CancellationResponsibility.PROPERTY)
    refunded_outcome = uuid4()
    refunded = drafts().record(
        property_id,
        ReservationDepositDecision.REFUND,
        RecordReservationDepositDraftCommand(
            uuid4(), refunded_id, refunded_outcome, "Refund", method
        ),
        actor=staff,
    )
    drafts().confirm(
        property_id,
        refunded_id,
        UUID(str(refunded["draft_id"])),
        actor=person(actor_id, property_id, "financial.approve"),
    )
    # A Refund number is never typed or used twice (DL-071 answer 10): the confirmed Refund has
    # the database's RFD number, and a reference that is a used Refund number is refused.
    with psycopg.connect(migrated_database_url) as verify:
        used = verify.execute(
            "SELECT refund_number FROM app.refunds WHERE id = %s", (refunded_outcome,)
        ).fetchone()
    assert used is not None and str(used[0]).startswith("RFD")
    with (
        psycopg.connect(financial_database_url()) as financial,
        pytest.raises(psycopg.Error) as refused,
    ):
        financial.execute(
            "SELECT app.record_reservation_deposit_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                uuid4(),
                reservation_id,
                "REFUND",
                uuid4(),
                "Used number",
                used[0],
                method.refund_method_id,
                method.reference_note,
                "reservation_deposits.refund",
            ),
        )
    assert refused.value.sqlstate == "23505"
    key = uuid4()
    first = RecordReservationDepositDraftCommand(
        key, reservation_id, uuid4(), "First draft", method
    )
    recorded = drafts().record(property_id, ReservationDepositDecision.REFUND, first, actor=staff)
    assert (
        drafts().record(property_id, ReservationDepositDecision.REFUND, first, actor=staff)
        == recorded
    )
    with pytest.raises(ReservationDepositDraftConflictError):
        drafts().record(
            property_id,
            ReservationDepositDecision.REFUND,
            RecordReservationDepositDraftCommand(
                uuid4(), reservation_id, uuid4(), "Second draft", method
            ),
            actor=staff,
        )
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)


def reverse_receipt(property_id: UUID, actor_id: UUID, reservation_id: UUID) -> None:
    with psycopg.connect(runtime_database_url()) as reader:
        receipt = reader.execute(
            "SELECT receipt.id FROM app.deposit_receipts AS receipt "
            "JOIN app.deposits AS deposit ON deposit.id = receipt.deposit_id "
            "WHERE deposit.reservation_id = %s",
            (reservation_id,),
        ).fetchone()
    assert receipt is not None
    # Since sub-slice 8r a receipt reversal is a draft and the financial role cannot run the
    # one-call function; the owner runs it so its pending-draft guard is still tested here.
    with psycopg.connect(owner_database_url(financial_database_url())) as financial:
        financial.execute(
            "SELECT app.reverse_deposit_receipt_v2(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                uuid4(),
                "a" * 64,
                uuid4(),
                receipt[0],
                "Receipt recorded against the wrong Deposit",
                "deposits.correct",
            ),
        )


def test_receipt_reversal_is_refused_only_while_a_draft_is_pending(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id)
    staff = person(actor_id, property_id, "reservation_deposits.dispose")
    draft = drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(uuid4(), reservation_id, uuid4(), "Forfeit"),
        actor=staff,
    )
    # Owner answer of 2026-10-04: refused only while a Reservation Deposit draft is pending.
    with pytest.raises(Error) as refused:
        reverse_receipt(property_id, actor_id, reservation_id)
    assert refused.value.sqlstate == "55000"
    assert waiting(property_id, actor_id)[reservation_id]["held_usd_cents"] == 10_000
    drafts().withdraw(
        property_id,
        reservation_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        UUID(str(draft["draft_id"])),
        "Receipt must be corrected first",
        actor=staff,
    )
    # With no draft pending the reversal works as before; nothing is held any more.
    reverse_receipt(property_id, actor_id, reservation_id)
    assert reservation_id not in waiting(property_id, actor_id)
    resource = PostgresReservationResourceFlow(runtime_database_url()).get(reservation_id)
    assert resource.deposit_outcome_state is not DepositOutcomeState.AWAITING_DECISION
    with pytest.raises(ReservationDepositDraftInvalidError):
        drafts().record(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositDraftCommand(uuid4(), reservation_id, uuid4(), "Forfeit"),
            actor=staff,
        )
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)


def test_cancellation_without_a_held_deposit_does_not_wait_for_a_decision(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    reverse_receipt(property_id, actor_id, reservation_id)
    result = PostgresReservationService(
        runtime_database_url(), property_id, actor_id, financial_database_url()
    ).cancel(
        ReservationCancelCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=reservation_id,
            expected_version=1,
            reason_code="CUSTOMER_WITHDREW",
            responsibility=CancellationResponsibility.CUSTOMER,
            property_could_provide_unit=True,
            reason_memo="Approved cancellation reason",
            coordination_reference=None,
            authorization_reference="reservations.cancel",
        ),
        actor=person(actor_id, property_id, "reservations.cancel"),
    )
    assert result.deposit_outcome_state is DepositOutcomeState.PENDING_V1_031
    assert reservation_id not in waiting(property_id, actor_id)
    resource = PostgresReservationResourceFlow(runtime_database_url()).get(reservation_id)
    assert resource.deposit_outcome_state is DepositOutcomeState.PENDING_V1_031


def test_a_completed_earlier_outcome_does_not_read_as_waiting(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id, CancellationResponsibility.PROPERTY)
    outcome_id = uuid4()
    draft = drafts().record(
        property_id,
        ReservationDepositDecision.REFUND,
        RecordReservationDepositDraftCommand(
            uuid4(),
            reservation_id,
            outcome_id,
            "Property could not provide the Unit",
            RefundMethodChoice(cash_method_id(property_id, actor_id), NOTE),
        ),
        actor=person(actor_id, property_id, "reservation_deposits.refund"),
    )
    drafts().confirm(
        property_id,
        reservation_id,
        UUID(str(draft["draft_id"])),
        actor=person(actor_id, property_id, "financial.approve"),
    )
    # An earlier-style full return of the Refund leaves an outcome record with no effect.
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,"
            "source_balance_effect_usd_cents,previous_net_refund_usd_cents,"
            "resulting_net_refund_usd_cents,reason,evidence_reference,occurred_at,actor_id,"
            "authorization_reference) VALUES (%s,%s,'VALUE_CORRECTION',10000,10000,0,"
            "'Bank proved funds never left','SYNTHETIC-RETURN',clock_timestamp(),%s,"
            "'reservation_deposits.correct')",
            (uuid4(), outcome_id, actor_id),
        )
        receipt = owner.execute(
            "SELECT receipt.id FROM app.deposit_receipts AS receipt "
            "JOIN app.deposits AS deposit ON deposit.id = receipt.deposit_id "
            "WHERE deposit.reservation_id = %s",
            (reservation_id,),
        ).fetchone()
        assert receipt is not None
        owner.execute(
            "SELECT app.reverse_deposit_receipt_v2(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                uuid4(),
                "b" * 64,
                uuid4(),
                receipt[0],
                "Synthetic unwind",
                "deposits.correct",
            ),
        )
        owner.commit()
    resource = PostgresReservationResourceFlow(runtime_database_url()).get(reservation_id)
    assert resource.deposit_outcome_state is DepositOutcomeState.PENDING_V1_031
    assert reservation_id not in waiting(property_id, actor_id)


def test_reject_and_withdraw_decide_without_moving_money(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        preparer, property_id, _, _, reservation_id = active_reservation(setup)
        other, *_ = active_reservation(setup)
        setup.commit()
    cancel_by_staff(preparer, property_id, reservation_id)
    staff = person(preparer, property_id, "reservation_deposits.dispose")
    approver = person(other, property_id, "financial.approve")

    def record() -> UUID:
        value = drafts().record(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositDraftCommand(uuid4(), reservation_id, uuid4(), "Forfeit"),
            actor=staff,
        )
        return UUID(str(value["draft_id"]))

    first = record()
    with pytest.raises(ReservationDepositDraftAuthorizationError):
        drafts().reject(property_id, reservation_id, first, "Not mine", actor=staff)
    with pytest.raises(ReservationDepositDraftAuthorizationError):
        drafts().withdraw(
            property_id,
            reservation_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            first,
            "Not mine",
            actor=person(other, property_id, "reservation_deposits.dispose"),
        )
    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(Error) as staff_reject:
            financial.execute(
                "SELECT app.reject_reservation_deposit_draft(%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    preparer,
                    reservation_id,
                    first,
                    "No",
                    "reservation_deposits.dispose",
                ),
            )
        assert staff_reject.value.sqlstate == "42501"
    with pytest.raises(ReservationDepositDraftInvalidError):
        drafts().reject(property_id, reservation_id, first, " padded ", actor=approver)
    rejected = drafts().reject(property_id, reservation_id, first, "Wrong reason", actor=approver)
    assert rejected["state"] == "REJECTED"
    assert (
        drafts().reject(property_id, reservation_id, first, "Wrong reason", actor=approver)
        == rejected
    )
    second = record()
    withdrawn = drafts().withdraw(
        property_id,
        reservation_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        second,
        "Recorded twice by mistake",
        actor=staff,
    )
    assert withdrawn["state"] == "WITHDRAWN"
    with pytest.raises(ReservationDepositDraftConflictError):
        drafts().confirm(property_id, reservation_id, second, actor=approver)
    # Reject and withdraw never move money; the Deposit still waits for a decision.
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)
    assert held(reservation_id) == 10_000
    assert waiting(property_id, actor_id=preparer)[reservation_id]["pending_draft_id"] is None


def test_drafts_cannot_cross_reservations_properties_or_flows(migrated_database_url: str) -> None:
    from psycopg.types.json import Jsonb

    from property_rental.refund import RefundInvalidError, RefundService

    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        _, _, _, _, other_reservation = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id)
    cancel_by_staff(actor_id, property_id, other_reservation)
    approver = person(actor_id, property_id, "financial.approve", "refunds.create")
    draft = drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(uuid4(), reservation_id, uuid4(), "Forfeit"),
        actor=person(actor_id, property_id, "reservation_deposits.dispose"),
    )
    draft_id = UUID(str(draft["draft_id"]))
    # Another Reservation of the same Property.
    with pytest.raises(ReservationDepositDraftNotFoundError):
        drafts().confirm(property_id, other_reservation, draft_id, actor=approver)
    with pytest.raises(ReservationDepositDraftNotFoundError):
        drafts().reject(property_id, other_reservation, draft_id, "No", actor=approver)
    # Another Property (the schema holds one Property, so any other id is foreign).
    foreign = uuid4()
    with psycopg.connect(financial_database_url()) as financial:
        for sql, parameters in (
            (
                "SELECT app.confirm_reservation_deposit_draft(%s,%s,%s,%s,%s)",
                (foreign, actor_id, reservation_id, draft_id, "financial.approve"),
            ),
            (
                "SELECT app.reject_reservation_deposit_draft(%s,%s,%s,%s,%s,%s)",
                (foreign, actor_id, reservation_id, draft_id, "No", "financial.approve"),
            ),
        ):
            with pytest.raises(Error) as refused:
                financial.execute(sql, parameters)
            assert refused.value.sqlstate in {"P4501", "P0002"}
            financial.rollback()
    # Slice 3a Refund confirm refuses a Reservation draft ...
    refunds = RefundService(runtime_database_url(), financial_database_url())
    with pytest.raises(RefundInvalidError):
        refunds.confirm_draft(property_id, draft_id, actor=approver)
    # ... and the Reservation confirm, reject and withdraw refuse a slice 3a Refund draft.
    # A pending slice 3a Credit Refund draft, written directly with the slice 3a payload shape.
    foreign_draft = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.financial_drafts(id,property_id,kind,prepare_capability,payload,"
            "source_revision,reason,prepared_at,prepared_by) VALUES "
            "(%s,%s,'REFUND','refunds.create',%s,NULL,'Credit Refund',clock_timestamp(),%s)",
            (
                foreign_draft,
                property_id,
                Jsonb(
                    {
                        "variant": "USD",
                        "source_kind": "CREDIT",
                        "source_id": str(uuid4()),
                        "amount_usd_cents": 100,
                        "reason": "Credit Refund",
                        "reservation_id": str(reservation_id),
                    }
                ),
                actor_id,
            ),
        )
        owner.commit()
    # It names this Reservation, so the kind check refuses it (not a Reservation draft).
    with pytest.raises(ReservationDepositDraftInvalidError):
        drafts().confirm(property_id, reservation_id, foreign_draft, actor=approver)
    with pytest.raises(ReservationDepositDraftNotFoundError):
        drafts().reject(property_id, reservation_id, foreign_draft, "No", actor=approver)
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)
    assert outcome_rows(migrated_database_url, other_reservation) == (0, 0)


def test_reused_draft_key_with_other_input_is_refused(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id)
    staff = person(
        actor_id, property_id, "reservation_deposits.dispose", "reservation_deposits.correct"
    )
    key, outcome_id = uuid4(), uuid4()
    first = RecordReservationDepositDraftCommand(key, reservation_id, outcome_id, "Forfeit")
    recorded = drafts().record(
        property_id, ReservationDepositDecision.DEPOSIT_FORFEITURE, first, actor=staff
    )
    with pytest.raises(ReservationDepositDraftKeyReused):
        drafts().record(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositDraftCommand(key, reservation_id, outcome_id, "Changed"),
            actor=staff,
        )
    with pytest.raises(ReservationDepositDraftKeyReused):
        drafts().record_correction(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositCorrectionDraftCommand(
                key, reservation_id, outcome_id, uuid4(), uuid4(), "Forfeit", "CASE-1"
            ),
            actor=staff,
        )
    assert (
        drafts().record(
            property_id, ReservationDepositDecision.DEPOSIT_FORFEITURE, first, actor=staff
        )
        == recorded
    )
    assert outcome_rows(migrated_database_url, reservation_id) == (0, 0)


def test_another_person_confirms_and_a_third_cannot_confirm_again(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        preparer, property_id, _, _, reservation_id = active_reservation(setup)
        approver, approver_property, *_ = active_reservation(setup)
        latecomer, latecomer_property, *_ = active_reservation(setup)
        setup.commit()
    assert approver_property == latecomer_property == property_id
    assert len({preparer, approver, latecomer}) == 3
    cancel_by_staff(preparer, property_id, reservation_id)
    draft = drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(uuid4(), reservation_id, uuid4(), "Forfeit"),
        actor=person(preparer, property_id, "reservation_deposits.dispose"),
    )
    draft_id = UUID(str(draft["draft_id"]))
    drafts().confirm(
        property_id,
        reservation_id,
        draft_id,
        actor=person(approver, property_id, "financial.approve"),
    )
    with pytest.raises(ReservationDepositDraftConflictError):
        drafts().confirm(
            property_id,
            reservation_id,
            draft_id,
            actor=person(latecomer, property_id, "financial.approve"),
        )
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT draft.prepared_by, decision.decided_by, decision.decision "
            "FROM app.financial_drafts AS draft JOIN app.financial_draft_decisions AS decision "
            "ON decision.draft_id = draft.id WHERE draft.id = %s",
            (draft_id,),
        ).fetchone() == (preparer, approver, "CONFIRMED")
        assert verify.execute(
            "SELECT actor_id FROM app.deposit_dispositions WHERE governing_reservation_id = %s",
            (reservation_id,),
        ).fetchone() == (approver,)


def test_two_drafts_sent_at_once_leave_exactly_one_pending(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id)
    staff = person(actor_id, property_id, "reservation_deposits.dispose")
    barrier = Barrier(2)

    def attempt(_: int) -> str:
        barrier.wait()
        try:
            drafts().record(
                property_id,
                ReservationDepositDecision.DEPOSIT_FORFEITURE,
                RecordReservationDepositDraftCommand(uuid4(), reservation_id, uuid4(), "Forfeit"),
                actor=staff,
            )
        except ReservationDepositDraftConflictError:
            return "conflict"
        return "recorded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(attempt, range(2)))
    assert outcomes == ["conflict", "recorded"]
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT count(*) FROM app.financial_drafts WHERE payload->>'reservation_id' = %s",
            (str(reservation_id),),
        ).fetchone() == (1,)


def test_outcome_correction_is_a_draft_and_keeps_the_original_until_confirmed(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id)
    approver = person(actor_id, property_id, "financial.approve")
    original_id = uuid4()
    draft = drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(uuid4(), reservation_id, original_id, "Forfeit"),
        actor=person(actor_id, property_id, "reservation_deposits.dispose"),
    )
    drafts().confirm(property_id, reservation_id, UUID(str(draft["draft_id"])), actor=approver)
    corrector = person(
        actor_id, property_id, "reservation_deposits.correct", "reservation_deposits.dispose"
    )
    with pytest.raises(ReservationDepositDraftAuthorizationError):
        drafts().record_correction(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositCorrectionDraftCommand(
                uuid4(), reservation_id, original_id, uuid4(), uuid4(), "Fix", "CASE-1"
            ),
            actor=person(actor_id, property_id, "reservation_deposits.dispose"),
        )
    with pytest.raises(ReservationDepositDraftConflictError):
        drafts().record_correction(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositCorrectionDraftCommand(
                uuid4(), reservation_id, uuid4(), uuid4(), uuid4(), "Stale outcome", "CASE-1"
            ),
            actor=corrector,
        )
    correction_id, replacement_id = uuid4(), uuid4()
    correction = drafts().record_correction(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositCorrectionDraftCommand(
            uuid4(),
            reservation_id,
            original_id,
            correction_id,
            replacement_id,
            "Correct the cancellation evidence",
            "CASE-RESERVATION-CORRECTION",
        ),
        actor=corrector,
    )
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT count(*) FROM app.deposit_disposition_reversals "
            "WHERE deposit_disposition_id = %s",
            (original_id,),
        ).fetchone() == (0,)
    with pytest.raises(ReservationDepositDraftAuthorizationError):
        drafts().confirm(
            property_id, reservation_id, UUID(str(correction["draft_id"])), actor=corrector
        )
    drafts().confirm(property_id, reservation_id, UUID(str(correction["draft_id"])), actor=approver)
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT id, reason, evidence_reference, authorization_reference "
            "FROM app.deposit_disposition_reversals WHERE deposit_disposition_id = %s",
            (original_id,),
        ).fetchone() == (
            correction_id,
            "Correct the cancellation evidence",
            "CASE-RESERVATION-CORRECTION",
            "reservation_deposits.correct",
        )
        assert verify.execute(
            "SELECT amount_usd_cents, reason FROM app.deposit_dispositions WHERE id = %s",
            (original_id,),
        ).fetchone() == (10_000, "Forfeit")
        assert verify.execute(
            "SELECT amount_usd_cents FROM app.deposit_dispositions WHERE id = %s",
            (replacement_id,),
        ).fetchone() == (10_000,)
    assert reservation_id not in waiting(property_id, actor_id)


def test_reservation_deposit_draft_roles_and_retired_one_call_paths(
    migrated_database_url: str,
) -> None:
    retired = (
        "app.cancel_reservation_v2(uuid,uuid,text,uuid,uuid,text,uuid,integer,text,text,boolean,text,text,text,text,uuid)",
        "app.expire_reservation_v2(uuid,uuid,text,uuid,uuid,uuid,integer,boolean,text,text,uuid)",
        "app.correct_reservation_deposit_outcome(uuid,uuid,text,uuid,uuid,uuid,text,uuid,integer,text,text,text,text,uuid)",
        "app.correct_reservation_deposit_disposition_v2(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,integer,text,text,text,text)",
    )
    financial_functions = (
        "app.cancel_reservation_v3(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,uuid)",
        "app.expire_reservation_v3(uuid,uuid,text,uuid,uuid,integer,boolean,text,uuid)",
        "app.record_reservation_deposit_draft(uuid,uuid,uuid,uuid,text,uuid,text,text,uuid,text,text)",
        "app.record_reservation_deposit_correction_draft(uuid,uuid,uuid,uuid,text,uuid,uuid,uuid,text,text,text,uuid,text,text,text)",
        "app.confirm_reservation_deposit_draft(uuid,uuid,uuid,uuid,text)",
        "app.reject_reservation_deposit_draft(uuid,uuid,uuid,uuid,text,text)",
        "app.withdraw_reservation_deposit_draft(uuid,uuid,uuid,uuid,text,text)",
    )
    listing = (
        "app.list_reservations_awaiting_deposit_decision("
        "uuid,uuid,integer,timestamp with time zone,uuid)"
    )
    with psycopg.connect(migrated_database_url) as owner:

        def can(role: str, function: str) -> bool:
            row = owner.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, function)
            ).fetchone()
            assert row is not None
            return bool(row[0])

        assert [can("prm_financial", function) for function in retired] == [False] * 4
        assert [can("prm_financial", function) for function in financial_functions] == [True] * 7
        assert [can("prm_runtime", function) for function in financial_functions] == [False] * 7
        assert can("prm_runtime", listing) is True
        assert can("prm_financial", listing) is False
        internal = (
            "app.reservation_deposit_has_outcome(uuid)",
            "app.reservation_deposit_draft_scope(uuid,uuid,uuid)",
            "app.reservation_deposit_draft_source(uuid,uuid,text)",
            "app.reservation_deposit_held_cents(uuid)",
        )
        for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
            assert [can(role, function) for function in internal] == [False] * 4, role
            assert [can(role, function) for function in retired] == [False] * 4, role
        assert owner.execute(
            "SELECT count(*) FROM pg_catalog.pg_proc AS procedure "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) AS privilege "
            "WHERE procedure.oid = ANY(%s::regprocedure[]) AND privilege.grantee = 0",
            (list((*financial_functions, listing)),),
        ).fetchone() == (0,)
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, *_ = active_reservation(setup)
        setup.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        for limit, after_at, after_id in ((0, None, None), (101, None, None), (5, None, uuid4())):
            with pytest.raises(Error) as invalid:
                runtime.execute(
                    "SELECT app.list_reservations_awaiting_deposit_decision(%s,%s,%s,%s,%s)",
                    (property_id, actor_id, limit, after_at, after_id),
                )
            assert invalid.value.sqlstate == "22023"
            runtime.rollback()
