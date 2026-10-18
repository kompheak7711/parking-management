"""The receipt writer for an existing Deposit of a Lease (V1-056 sub-slice 10e-2b-4b-2b).

Owner answer to Q-2026-10-12-92: staff record a Pet Deposit receipt, or a later Security Deposit
receipt within the required amount, from a received Payment under `payments.allocate`, with no
draft and no `financial.approve`; refused once the Lease's Final Settlement is closed. The writer
is `app.record_lease_deposit_receipt`, called by `PostgresDepositService.record_receipt`. Every
receipt table check still runs. Also the owner's first example of Q-2026-10-17-123 on the real
path: a Pet Refund-review Refund recovered by a charge adds what is charged back to the pay-back
count, now that Pet Deposit money enters through the app before closure.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_disposition_test_support import terminate_for_disposition
from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from lease_deposit_forfeiture_test_support import forfeit_through_draft, reverse_through_draft
from payment_test_support import seed_deposit_payment, seed_payment
from property_rental.deposit import (
    DepositAuthorizationError,
    DepositConflictError,
    DepositIdempotencyKeyReused,
    DepositInvalidError,
    DepositNotFoundError,
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordDepositReceiptCommand,
    RecordPetDepartureCommand,
    ReverseDepositReceiptCommand,
    deposit_request_digest,
)
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    FinalSettlementStaleDraftError,
)
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureInvalidError,
    LeaseDepositForfeitureService,
    RecordLeaseDepositForfeitureCommand,
)
from property_rental.payment_return import PaymentReturnConflictError
from refund_test_support import create_pet_refund
from test_credit_migration import actor
from test_deposit_migration import (
    create_pet,
    deposit_actor,
    runtime_database_url,
    seed_historical_deposit_receipt,
    setup_signed_pet_lease,
)
from test_final_settlement_closed_refusal_migration import overdue_case
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import held, one, outstanding, start, today
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import draft_id, reconciled, request, returns
from test_payment_return_migration import preparer as return_preparer
from test_pet_payback_recovery_standing_migration import open_lease_recovery, standing
from test_pet_payback_restoration_refusal_migration import (
    one_call,
    owner,
    recovered_case,
    terminate,
    void,
    wait_until_blocked_by,
)
from test_pet_refund_migration import command as pet_refund_command
from test_refund_service_migration import refund_id, returned
from test_refund_service_migration import service as refund_service
from test_reservation_migration import create_reservation, setup_reservation_sources
from test_settlement_deposit_receipt_payback_forfeiture_migration import payback_count
from test_settlement_extra_charge_migration import cause
from test_settlement_extra_charge_migration import state as draft_state
from test_settlement_pet_receipt_link_migration import closed, pet_lease_case
from test_settlement_returned_payment_migration import RELIED_ON, STILL_HOLDS, counts
from test_settlement_returned_payment_migration import command as returned_command
from test_settlement_returned_payment_migration import record as record_returned
from test_settlement_returned_payment_migration import status as payment_status
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20261228_154"
WRITER = "app.record_lease_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,text,text)"
CALL = "SELECT app.record_lease_deposit_receipt(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
ALLOCATE = "payments.allocate"
REASON = "Pet Deposit paid at the front desk"
DIGEST = "a" * 64
INVALID = "Deposit receipt evidence is invalid"
CLOSED = "A closed Final Settlement changes only through a post-settlement correction"
FORFEITED = "The Deposit has an active forfeiture; reverse the forfeiture first"
READ_COMMITTED = "A Deposit receipt is recorded at READ COMMITTED"
PET_LIMIT = "Pet Deposit receipt exceeds its approved liability"
SECURITY_LIMIT = "Deposit receipt does not preserve the accepted or required amount"
ONE_PER_PAYMENT = "A Deposit holds at most one active receipt from each Payment"
AVAILABILITY = "Deposit receipt exceeds Payment availability"
INELIGIBLE = "Deposit receipt Payment source is ineligible"
# Sub-slice 10e-2b-4d (owner answer (b) to Q-2026-10-18-128): the whole-Payment refusal ("A Payment
# confirmed for an Invoice or a Late-payment Charge is not a Deposit receipt", 55000) became the
# Credit path's excess check, 23514, while the named target has anything outstanding.
EXCESS = "Applicable obligations must be handled before excess disposition"
SHARED = (
    "A Deposit this Payment funded also holds another Payment's money and has a Refund that is "
    "not fully returned"
)
DEPENDENT = "Deposit receipt has active dependent financial history"
STALE_FORFEITURE = "Lease Deposit forfeiture draft is stale"
# Sub-slice 10e-2b-4d (owner answer (a) to Q-2026-10-18-131): no receipt after a termination whose
# ground keeps the Deposit, also after a forfeiture reversal.
KEPT = "The Lease's termination ground keeps this Deposit; this receipt is not recorded here"


def pet_case(url: str) -> dict[str, Any]:
    """A signed Lease with an approved Pet Deposit of 20,000 that holds nothing."""
    service, manager, lease, approval, day = setup_signed_pet_lease(url)
    pet, _ = create_pet(service, manager, lease, approval, day)
    customer = UUID(str(value(url, "SELECT customer_id FROM app.deposits WHERE id=%s", pet)))
    return {
        "url": url,
        "service": service,
        "human": service.actor_id,
        "prop": service.property_id,
        "lease": lease,
        "pet": pet,
        "customer": customer,
    }


def payment(url: str, human: UUID, deposit: UUID, amount: int) -> UUID:
    """A received Payment of the Deposit's Customer (committed)."""
    with psycopg.connect(url) as connection:
        return seed_deposit_payment(connection, deposit_id=deposit, actor_id=human, amount=amount)


def receipt_command(deposit: UUID, paid_by: UUID, amount: int) -> RecordDepositReceiptCommand:
    return RecordDepositReceiptCommand(uuid4(), uuid4(), deposit, paid_by, amount, REASON)


def allocator(human: UUID, prop: UUID) -> Any:
    return actor(human, prop, ALLOCATE)


def attempt(
    prop: UUID,
    human: UUID,
    deposit: UUID,
    paid_by: UUID,
    amount: int,
    *,
    url: str | None = None,
    isolation: psycopg.IsolationLevel | None = None,
    reason: str = REASON,
    authorization: str = ALLOCATE,
) -> tuple[Any, Any]:
    """Call the writer as the financial role (or the given role) in a transaction of its own,
    which commits when the call passes; the refusal (SQLSTATE and message) or (None, None)."""
    with psycopg.connect(url or financial_database_url()) as connection:
        if isolation is not None:
            connection.isolation_level = isolation
        try:
            connection.execute(
                CALL,
                (
                    prop,
                    human,
                    uuid4(),
                    DIGEST,
                    uuid4(),
                    deposit,
                    paid_by,
                    amount,
                    reason,
                    authorization,
                ),
            )
        except psycopg.Error as refused:
            if refused.sqlstate is None:
                # A client-side error is not a database refusal; never read it as a pass.
                raise
            connection.rollback()
            return refused.sqlstate, refused.diag.message_primary
        connection.commit()
    return None, None


def written(url: str, deposit: UUID) -> tuple[Any, ...]:
    """The Deposit's receipts, their receipt audit events and the writer's command records."""
    return one(
        url,
        "SELECT (SELECT count(*) FROM app.deposit_receipts WHERE deposit_id=%s),"
        "(SELECT count(*) FROM app.audit_events audit JOIN app.deposit_receipts receipt "
        "ON receipt.id=audit.entity_id WHERE receipt.deposit_id=%s "
        "AND audit.action='deposit.receipt.recorded'),"
        "(SELECT count(*) FROM app.deposit_commands WHERE deposit_id=%s "
        "AND action='deposit.receipt.record')",
        deposit,
        deposit,
        deposit,
    )


def other_customer(url: str, human: UUID) -> UUID:
    customer = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Another Customer',%s,%s)",
            (customer, human, human),
        )
    return customer


def qualify_review(case: dict[str, Any]) -> UUID:
    """The pet's permanent departure and its qualified Pet Refund review (as `qualified`)."""
    url, human, prop, pet = case["url"], case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    departure = RecordPetDepartureCommand(uuid4(), uuid4(), pet, today(url), "Pet permanently left")
    service.record_pet_departure(departure, actor=deposit_actor(human, prop))
    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        pet,
        30_000,
        "All valid pet costs resolved separately; liability is not capped by Deposit",
        "Synthetic inspection and resolution evidence",
        "Qualified Pet exception",
    )
    service.qualify_pet_refund_review(review, actor=deposit_actor(human, prop))
    return review.review_id


def review_refund(case: dict[str, Any], review: UUID, amount: int) -> UUID:
    human, prop = case["human"], case["prop"]
    return refund_id(
        create_pet_refund(
            refund_service(),
            prop,
            pet_refund_command(case["pet"], review, amount),
            actor=actor(human, prop, "refunds.create"),
        )
    )


def terminated_pet_lease_case(
    url: str, *, voluntary: bool = False, receipts: tuple[int, ...] = ()
) -> dict[str, Any]:
    """`pet_lease_case` of `test_settlement_pet_receipt_link_migration` with two choices (sub-slice
    10e-2b-4d; owner answer (a) to Q-2026-10-18-131 refuses a receipt after a termination whose
    ground keeps the Deposit): before the termination the Pet Deposit takes one receipt of each
    of `receipts` through the writer, each from a Payment of its own (listed in `payments`); with
    `voluntary` the termination is voluntary early leaving (BR-LEASE-021), whose ground keeps the
    Security Deposit (BR-DEP-023) but not the Pet Deposit. The Security Deposit is forfeited
    through the draft; the Final Settlement is started, not closed."""
    source = signed_with_initial(url, this_month(url))
    human, prop, lease = source["actor"], source["property"], source["lease"]
    customer, day = source["customer"], source["today"]
    approval = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.lease_pet_approvals(id,lease_id,approved_date,"
            "deposit_required_by_signed_terms,pet_description,approved_at,approved_by) "
            "VALUES (%s,%s,%s,true,'Synthetic approved pet',clock_timestamp(),%s)",
            (approval, lease, day, human),
        )
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    pet, _ = create_pet(deposits, deposit_actor(human, prop), lease, approval, day)
    paid = tuple(payment(url, human, pet, amount) for amount in receipts)
    for paid_by, amount in zip(paid, receipts, strict=True):
        deposits.record_receipt(receipt_command(pet, paid_by, amount), actor=allocator(human, prop))
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    terminate_for_disposition(url, deposits, lease, day, voluntary=voluntary)
    forfeit_through_draft(deposits, source["deposit"])
    return {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": source["deposit"],
        "pet": pet,
        "payments": paid,
        "settlement": start(prop, human, lease),
    }


def test_a_pet_deposit_receipt_is_recorded_through_the_service_with_every_table_check(
    migrated_database_url: str,
) -> None:
    """A signed Lease's Pet Deposit (20,000 required) takes 8,000 from a received 12,000 Payment
    of its Customer through the service: the Deposit holds 8,000, the Payment has 4,000 left, the
    receipt's time is the database's, one `deposit.receipt.recorded` audit event (its id the
    receipt's, `payments.allocate`, correlated by the idempotency key) and one command record are
    written. An exact repeat returns the first result and writes nothing; the same key with another
    body is refused. The receipt table's checks still refuse a second active receipt from the same
    Payment (23505), more than a Payment's available value, another Customer's Payment and more
    than the required amount (23514). A later receipt from another Payment is dated one
    microsecond after the Deposit's latest balance event when that event is ahead of the clock
    (a 2,000 receipt inserted by hand 4 seconds ahead, right before the call), and fills the
    Deposit to its 20,000."""
    url = migrated_database_url
    case = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    first_payment = payment(url, human, pet, 12_000)
    command = receipt_command(pet, first_payment, 8_000)
    [before] = one(url, "SELECT clock_timestamp()")
    first = service.record_receipt(command, actor=allocator(human, prop))
    [after] = one(url, "SELECT clock_timestamp()")
    assert (
        first.deposit_receipt_id,
        first.payment_id,
        first.amount_usd_cents,
        first.payment_available_usd_cents,
    ) == (command.receipt_id, first_payment, 8_000, 4_000)
    assert (
        first.deposit.deposit_id,
        first.deposit.required_usd_cents,
        first.deposit.received_usd_cents,
        first.deposit.held_refundable_usd_cents,
        first.deposit.outstanding_required_usd_cents,
    ) == (pet, 20_000, 8_000, 8_000, 12_000)
    assert before <= first.occurred_at <= after
    assert one(
        url,
        "SELECT payment_id,amount_usd_cents,occurred_at,actor_id FROM app.deposit_receipts "
        "WHERE id=%s",
        command.receipt_id,
    ) == (first_payment, 8_000, first.occurred_at, human)
    assert one(
        url,
        "SELECT actor_id,entity_type,entity_id,authorization_reference,correlation_id,reason,"
        "(resulting_state->>'held_refundable_usd_cents')::bigint FROM app.audit_events "
        "WHERE id=%s AND action='deposit.receipt.recorded'",
        command.receipt_id,
    ) == (
        human,
        "deposit_receipt",
        command.receipt_id,
        ALLOCATE,
        command.idempotency_key,
        REASON,
        8_000,
    )
    assert one(
        url,
        "SELECT actor_id,request_digest,reason,authorization_reference,"
        "result_snapshot->>'deposit_receipt_id' FROM app.deposit_commands "
        "WHERE idempotency_key=%s AND action='deposit.receipt.record'",
        command.idempotency_key,
    ) == (
        human,
        deposit_request_digest("deposit.receipt.record", command),
        REASON,
        ALLOCATE,
        str(command.receipt_id),
    )
    assert (held(url, pet), written(url, pet)) == (8_000, (1, 1, 1))
    assert service.record_receipt(command, actor=allocator(human, prop)) == first
    with pytest.raises(DepositIdempotencyKeyReused):
        service.record_receipt(
            replace(command, amount_usd_cents=7_000), actor=allocator(human, prop)
        )
    assert (held(url, pet), written(url, pet)) == (8_000, (1, 1, 1))
    assert attempt(prop, human, pet, first_payment, 1_000) == ("23505", ONE_PER_PAYMENT)
    small = payment(url, human, pet, 1_000)
    assert attempt(prop, human, pet, small, 1_500) == ("23514", AVAILABILITY)
    with psycopg.connect(url) as connection:
        foreign = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=other_customer(url, human),
            amount=1_000,
        )
    assert attempt(prop, human, pet, foreign, 1_000) == ("23514", INELIGIBLE)
    last_payment = payment(url, human, pet, 12_001)
    assert attempt(prop, human, pet, last_payment, 12_001) == ("23514", PET_LIMIT)
    with pytest.raises(DepositInvalidError):
        service.record_receipt(
            receipt_command(pet, last_payment, 12_001), actor=allocator(human, prop)
        )
    assert (held(url, pet), written(url, pet)) == (8_000, (1, 1, 1))
    hand_payment = payment(url, human, pet, 2_000)
    ahead = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
            "occurred_at,actor_id) VALUES "
            "(%s,%s,%s,2000,clock_timestamp()+interval '4 seconds',%s)",
            (ahead, pet, hand_payment, human),
        )
    last = service.record_receipt(
        receipt_command(pet, last_payment, 10_000), actor=allocator(human, prop)
    )
    assert one(
        url,
        "SELECT occurred_at+interval '1 microsecond' FROM app.deposit_receipts WHERE id=%s",
        ahead,
    ) == (last.occurred_at,)
    assert (
        last.deposit.held_refundable_usd_cents,
        last.deposit.outstanding_required_usd_cents,
        last.payment_available_usd_cents,
    ) == (20_000, 0, 2_001)
    assert written(url, pet) == (3, 2, 2)
    reconciled(url, case["customer"])


def test_a_later_security_deposit_receipt_on_a_lease_signed_from_a_reservation(
    migrated_database_url: str,
) -> None:
    """A Lease signed from a Reservation continues its Security Deposit (50,000 required, the
    accepted 10,000 received). Later receipts from new Payments of the Customer are recorded up to
    the required amount: 15,000, then 25,001 is refused (23514) and 25,000 fills it."""
    url = migrated_database_url
    source = signed_with_initial(url, this_month(url))
    human, prop, security = source["actor"], source["property"], source["deposit"]
    service = PostgresDepositService(financial_database_url(), prop, human)
    assert (held(url, security), written(url, security)) == (10_000, (1, 0, 0))
    first = service.record_receipt(
        receipt_command(security, payment(url, human, security, 20_000), 15_000),
        actor=allocator(human, prop),
    )
    assert (
        first.deposit.deposit_type,
        first.deposit.lease_id,
        first.deposit.received_usd_cents,
        first.deposit.outstanding_required_usd_cents,
        first.payment_available_usd_cents,
    ) == ("SECURITY", source["lease"], 25_000, 25_000, 5_000)
    rest = payment(url, human, security, 25_001)
    assert attempt(prop, human, security, rest, 25_001) == ("23514", SECURITY_LIMIT)
    last = service.record_receipt(
        receipt_command(security, rest, 25_000), actor=allocator(human, prop)
    )
    assert (
        last.deposit.held_refundable_usd_cents,
        last.deposit.outstanding_required_usd_cents,
        last.payment_available_usd_cents,
    ) == (50_000, 0, 1)
    assert (held(url, security), written(url, security)) == (50_000, (3, 2, 2))
    reconciled(url, source["customer"])


def test_the_writer_takes_a_reservation_deposit_and_refuses_after_closure_and_while_forfeited(
    migrated_database_url: str,
) -> None:
    """A Reservation's Security Deposit before signing has no Lease; since sub-slice 10e-2b-4c
    (owner answer to Q-2026-10-17-124 point 3) a second receipt is taken while the Reservation is
    ACTIVE, within the required total (renamed in 10e-2b-4c from
    `test_the_writer_refuses_before_signing_after_closure_and_while_a_forfeiture_is_active`; it
    was refused, 55000). On a Lease terminated for pet noncompliance, the forfeited Security
    Deposit is refused while its forfeiture is active (55000). After the real closure both Deposit
    types are refused with the 8e-1 refusal (P5S01), also the forfeited Security Deposit, and the
    service shows it as a conflict; nothing is written. Unknown Deposits and Payments are not found
    (P0002); a stricter isolation level (55000), invalid input (22023), the runtime role (42501)
    and an actor without `payments.allocate` (before any call) are refused."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, unit, customer = setup_reservation_sources(connection)
        _, ids = create_reservation(
            connection, actor_id=human, property_id=prop, unit_id=unit, customer_id=customer
        )
    reserved = ids["deposit_id"]
    # Sub-slice 10e-2b-4c (owner answer to Q-2026-10-17-124 point 3): was 55000 ("The Deposit
    # has no Lease yet; this receipt is not recorded here") and (1, 0, 0); the second receipt is
    # now recorded with its audit event and command.
    assert attempt(prop, human, reserved, payment(url, human, reserved, 5_000), 5_000) == (
        None,
        None,
    )
    assert written(url, reserved) == (2, 1, 1)
    case = pet_lease_case(url)
    human, prop, pet, security = case["human"], case["prop"], case["pet"], case["security"]
    service = PostgresDepositService(financial_database_url(), prop, human)
    security_payment = payment(url, human, security, 5_000)
    assert attempt(prop, human, security, security_payment, 5_000) == ("55000", FORFEITED)
    closed(case)
    pet_payment = payment(url, human, pet, 5_000)
    assert attempt(prop, human, pet, pet_payment, 5_000) == ("P5S01", CLOSED)
    assert attempt(prop, human, security, security_payment, 5_000) == ("P5S01", CLOSED)
    with pytest.raises(DepositConflictError):
        service.record_receipt(
            receipt_command(pet, pet_payment, 5_000), actor=allocator(human, prop)
        )
    assert (written(url, pet), written(url, security)) == ((0, 0, 0), (1, 0, 0))
    assert attempt(prop, human, uuid4(), pet_payment, 5_000) == ("P0002", "Deposit was not found")
    assert attempt(prop, human, pet, uuid4(), 5_000) == ("P0002", "Payment was not found")
    with pytest.raises(DepositNotFoundError):
        service.record_receipt(
            receipt_command(uuid4(), pet_payment, 5_000), actor=allocator(human, prop)
        )
    fresh = pet_case(url)
    human, prop, pet = fresh["human"], fresh["prop"], fresh["pet"]
    fresh_payment = payment(url, human, pet, 5_000)
    assert attempt(
        prop, human, pet, fresh_payment, 5_000, isolation=psycopg.IsolationLevel.REPEATABLE_READ
    ) == ("55000", READ_COMMITTED)
    assert attempt(prop, uuid4(), pet, fresh_payment, 5_000) == (
        "55000",
        "Financial action requires an active scoped actor",
    )
    assert attempt(prop, human, UUID(int=0), fresh_payment, 5_000) == ("22023", INVALID)
    for refused in (
        {"amount": 0},
        {"reason": REASON + " "},
        {"reason": "x" * 1_001},
        {"authorization": "deposits.manage"},
    ):
        found = attempt(
            prop,
            human,
            pet,
            fresh_payment,
            cast(int, refused.get("amount", 5_000)),
            reason=cast(str, refused.get("reason", REASON)),
            authorization=cast(str, refused.get("authorization", ALLOCATE)),
        )
        assert found == ("22023", INVALID), refused
    assert attempt(prop, human, pet, fresh_payment, 5_000, url=runtime_database_url())[0] == (
        "42501"
    )
    with pytest.raises(DepositAuthorizationError):
        fresh["service"].record_receipt(
            receipt_command(pet, fresh_payment, 5_000), actor=deposit_actor(human, prop)
        )
    assert (held(url, pet), written(url, pet)) == (0, (0, 0, 0))


def test_a_review_refund_recovered_by_a_charge_raises_the_count_on_the_real_path(
    migrated_database_url: str,
) -> None:
    """The owner's first example of Q-2026-10-17-123 with the Pet Deposit money recorded by the
    new writer (owner answer (a): what a charge recovers of a Pet Refund-review Refund counts like
    a verified return). A 20,000 Pet receipt; a 15,000 Pet Refund-review Refund and its verified
    return (count 15,000); a second 15,000 review Refund pays the returned money out again (count
    0); the Payment's return then recovers the second Refund by a 15,000 charge on the signed Lease
    (the first is fully returned, so it is not charged), reverses the receipt, and the count rises
    by the 15,000 charged back while the charge stands; the Deposit holds nothing."""
    url = migrated_database_url
    case = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    funding = payment(url, human, pet, 20_000)
    service.record_receipt(receipt_command(pet, funding, 20_000), actor=allocator(human, prop))
    review = qualify_review(case)
    first = review_refund(case, review, 15_000)
    assert (held(url, pet), payback_count(url, pet)) == (5_000, 0)
    refund_service().verify_usd_return(
        prop, first, returned(15_000), actor=actor(human, prop, "refunds.correct")
    )
    assert (held(url, pet), payback_count(url, pet)) == (20_000, 15_000)
    second = review_refund(case, review, 15_000)
    assert (held(url, pet), payback_count(url, pet)) == (5_000, 0)
    draft = returns().record(prop, request(funding), actor=return_preparer(human, prop))
    returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    recovery, line, _, _ = open_lease_recovery(url, second)
    assert (standing(url, recovery), outstanding(url, line)) == (15_000, 15_000)
    assert (
        value(
            url,
            "SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s "
            "AND correction_kind='RECOVERED_BY_CHARGE'",
            first,
        )
        == 0
    )
    assert (held(url, pet), payback_count(url, pet)) == (0, 15_000)
    reconciled(url, case["customer"])


def test_a_payment_confirmed_for_an_owed_invoice_is_not_a_deposit_receipt(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security blocker): a Payment confirmed for an Invoice (or a Late-payment
    Charge) is allocated only to that target (BR-PAY-024, BR-PAY-026; the allocation check refuses
    any other target) and its rest may become Credit or a Refund, never a Deposit receipt, so the
    writer refused the whole Payment (55000). Since sub-slice 10e-2b-4d (owner answer (b) to
    Q-2026-10-18-128; renamed from
    `test_a_payment_confirmed_for_an_invoice_is_not_a_deposit_receipt`) it is refused while the
    named Invoice is owed (23514, the Credit path's excess check), and nothing is written: the
    Customer's own Payment naming the Initial Rent Invoice, and a third-party Payment naming the
    Lease and that Invoice; the leftover case is in `test_deposit_receipt_leftover_migration.py`.
    A third-party Payment that names only the Lease still funds the Lease's Security Deposit (the
    receipt table's existing rule)."""
    url = migrated_database_url
    source = signed_with_initial(url, this_month(url))
    human, prop, security = source["actor"], source["property"], source["deposit"]
    payer = other_customer(url, human)
    with psycopg.connect(url) as connection:
        named = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=source["customer"],
            amount=10_000,
            invoice_id=source["invoice"],
        )
        third = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=payer,
            amount=10_000,
            lease_id=source["lease"],
            scope="THIRD_PARTY_IDENTIFIED",
            invoice_id=source["invoice"],
        )
        lease_only = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=payer,
            amount=10_000,
            lease_id=source["lease"],
            scope="THIRD_PARTY_IDENTIFIED",
        )
    # Sub-slice 10e-2b-4d: was ("55000", the intent message) for both.
    assert attempt(prop, human, security, named, 10_000) == ("23514", EXCESS)
    assert attempt(prop, human, security, third, 10_000) == ("23514", EXCESS)
    assert written(url, security) == (1, 0, 0)
    available = "SELECT app.payment_available_value(%s)"
    assert (value(url, available, named), value(url, available, third)) == (10_000, 10_000)
    assert attempt(prop, human, security, lease_only, 10_000) == (None, None)
    assert (held(url, security), written(url, security)) == (20_000, (2, 1, 1))


def test_on_a_terminated_lease_whose_ground_keeps_the_deposit_a_receipt_is_refused(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent S2), changed by sub-slice 10e-2b-4d (owner answer (a) to
    Q-2026-10-18-131; renamed from
    `test_on_a_terminated_lease_a_receipt_passes_until_closure_and_after_a_forfeiture_reversal`):
    on a Lease terminated for pet noncompliance, whose ground keeps both Deposits (BR-DEP-022), and
    whose Settlement is started but not closed, a Pet Deposit receipt was recorded and is now
    refused (55000; the service shows it as invalid); the forfeited Security Deposit is refused
    while its forfeiture is active, and once the forfeiture is reversed through the 6b draft it
    took a receipt and is now refused too (the reversal does not change the ground). Nothing is
    written and both Payments keep their value."""
    url = migrated_database_url
    case = pet_lease_case(url)
    human, prop, security, pet = case["human"], case["prop"], case["security"], case["pet"]
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    assert value(url, "SELECT status FROM app.leases WHERE id=%s", case["lease"]) == "TERMINATED"
    pet_payment = payment(url, human, pet, 5_000)
    # Sub-slice 10e-2b-4d: was recorded (the Pet Deposit held 5,000; (1, 1, 1)).
    assert attempt(prop, human, pet, pet_payment, 5_000) == ("55000", KEPT)
    with pytest.raises(DepositInvalidError):
        deposits.record_receipt(
            receipt_command(pet, pet_payment, 5_000), actor=allocator(human, prop)
        )
    paid_by = payment(url, human, security, 5_000)
    assert attempt(prop, human, security, paid_by, 5_000) == ("55000", FORFEITED)
    dispositions = "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s"
    [disposition] = [UUID(str(row[0])) for row in rows(url, dispositions, security)]
    reverse_through_draft(deposits, disposition)
    held_before = held(url, security)
    # Sub-slice 10e-2b-4d: was recorded (held_before + 5,000; (2, 1, 1)).
    assert attempt(prop, human, security, paid_by, 5_000) == ("55000", KEPT)
    available = "SELECT app.payment_available_value(%s)"
    assert (held(url, pet), written(url, pet), held(url, security), written(url, security)) == (
        0,
        (0, 0, 0),
        held_before,
        (1, 0, 0),
    )
    assert (value(url, available, pet_payment), value(url, available, paid_by)) == (5_000, 5_000)


def test_a_receipt_makes_a_pending_forfeiture_draft_stale(migrated_database_url: str) -> None:
    """Review round 1 (security S3 (c); the design has no pending-draft refusal): on a Pet
    Deposit holding 15,000 with a pay-back count of 0 after a pet noncompliance termination, a
    forfeiture draft of the whole held amount is recorded; a 3,000 receipt then makes the draft's
    confirm stale, and the confirm writes no forfeiture. Since sub-slice 10e-2b-4d (owner answer
    (a) to Q-2026-10-18-131) the writer refuses that receipt (55000: the termination ground keeps
    the Pet Deposit) and writes nothing, so the scenario cannot be reached through the writer;
    the stale check is kept with a hand-built receipt (an owner insert, as the committed pay-back
    fixtures seed receipts)."""
    url = migrated_database_url
    case = recovered_case(url, 15_000)
    void(case)
    terminate(case)
    human, prop, deposit = case["human"], case["prop"], case["deposit"]
    person = actor(human, prop, "deposits.dispose", "financial.approve")
    forfeitures = LeaseDepositForfeitureService(financial_database_url())
    draft = forfeitures.record(
        prop,
        RecordLeaseDepositForfeitureCommand(uuid4(), deposit, uuid4(), "Approved forfeiture"),
        actor=person,
    )
    later = payment(url, human, deposit, 3_000)
    # Sub-slice 10e-2b-4d: was (None, None), the receipt recorded through the writer.
    assert attempt(prop, human, deposit, later, 3_000) == ("55000", KEPT)
    assert (held(url, deposit), value(url, "SELECT app.payment_available_value(%s)", later)) == (
        15_000,
        3_000,
    )
    seed_historical_deposit_receipt(url, deposit_id=deposit, actor_id=human, amount_usd_cents=3_000)
    with pytest.raises(LeaseDepositForfeitureInvalidError) as refused:
        forfeitures.confirm(prop, deposit, UUID(str(draft["draft_id"])), actor=person)
    assert cause(refused) == ("23514", STALE_FORFEITURE)
    count = "SELECT count(*) FROM app.deposit_dispositions WHERE deposit_id=%s"
    assert (value(url, count, deposit), held(url, deposit)) == (0, 18_000)
    assert draft_state(url, UUID(str(draft["draft_id"]))) == "PENDING"


def test_a_closure_committed_while_the_writer_waits_is_read_after_the_deposit_lock(
    migrated_database_url: str,
) -> None:
    """Review round 1 (both reviewers): the closing confirm holds the Lease's Deposits; a
    Security Deposit receipt that waits for them reads the committed closure (P5S01), not the
    forfeiture it would read before the lock (55000), and writes nothing. In the other order, a
    Pet Deposit receipt holding the Deposit first makes the waiting closing confirm stale; the
    Settlement stays open and the receipt stands. Since sub-slice 10e-2b-4d (owner answer (a) to
    Q-2026-10-18-131 refuses a Pet Deposit receipt after the pet noncompliance termination) the
    other order runs on a Lease terminated for voluntary early leaving, whose ground keeps only the
    Security Deposit."""
    url = migrated_database_url
    case = pet_lease_case(url)
    human, prop, security = case["human"], case["prop"], case["security"]
    draft = record_settlement(case, ())
    paid_by = payment(url, human, security, 5_000)
    with psycopg.connect(financial_database_url()) as closing:
        closing.execute(
            "SELECT app.confirm_final_settlement_draft(%s,%s,%s,'financial.approve')",
            (prop, human, UUID(str(draft["draft_id"]))),
        )
        with ThreadPoolExecutor(1) as pool:
            waiting = pool.submit(attempt, prop, human, security, paid_by, 5_000)
            wait_until_blocked_by(url, closing)
            closing.commit()
            assert waiting.result(timeout=60) == ("P5S01", CLOSED)
    assert written(url, security) == (1, 0, 0)
    # Sub-slice 10e-2b-4d: was `pet_lease_case(url)` (pet noncompliance).
    other = terminated_pet_lease_case(url, voluntary=True)
    human, prop, pet = other["human"], other["prop"], other["pet"]
    draft = record_settlement(other, ())
    paid_by = payment(url, human, pet, 5_000)
    with psycopg.connect(financial_database_url()) as writing:
        writing.execute(
            CALL, (prop, human, uuid4(), DIGEST, uuid4(), pet, paid_by, 5_000, REASON, ALLOCATE)
        )
        with ThreadPoolExecutor(1) as pool:
            confirming = pool.submit(confirm_settlement, other, draft)
            wait_until_blocked_by(url, writing)
            writing.commit()
            with pytest.raises(FinalSettlementStaleDraftError) as stale:
                confirming.result(timeout=60)
    assert cause(stale)[0] == "P5S02"
    assert value(
        url,
        "SELECT closed_at IS NULL FROM app.final_settlements WHERE id=%s",
        other["settlement"],
    )
    assert (held(url, pet), written(url, pet)) == (5_000, (1, 1, 1))


def test_a_forfeiture_committed_while_the_writer_waits_refuses_the_receipt(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent S1 (c)): the owner's one-call forfeiture of a Pet Deposit
    holds the Deposit; a receipt that waits for it reads the committed forfeiture (55000) and
    writes nothing."""
    url = migrated_database_url
    case = recovered_case(url, 15_000)
    void(case)
    terminate(case)
    human, prop, deposit = case["human"], case["prop"], case["deposit"]
    later = payment(url, human, deposit, 5_000)
    receipts = "SELECT count(*) FROM app.deposit_receipts WHERE deposit_id=%s"
    before = value(url, receipts, deposit)
    with psycopg.connect(owner()) as forfeiting:
        forfeiting.execute(*one_call(case, 15_000))
        with ThreadPoolExecutor(1) as pool:
            waiting = pool.submit(attempt, prop, human, deposit, later, 5_000)
            wait_until_blocked_by(url, forfeiting)
            forfeiting.commit()
            assert waiting.result(timeout=60) == ("55000", FORFEITED)
    assert (value(url, receipts, deposit), held(url, deposit)) == (before, 0)


def test_a_deposit_funded_by_two_payments_plans_only_the_shortfall_of_a_return(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security S2; Q-2026-10-18-127): with this writer a Deposit can hold money
    from two Payments. A Pet Deposit takes 10,000 from each of two Payments, then pays a 15,000 Pet
    Refund-review Refund. Until sub-slice 10e-2b-4e-1 the first Payment's return was refused (the
    shared-Deposit guard of owner answer 2 to Q-2026-10-11-81); since owner answer (a) its return
    plans to charge back only the 5,000 shortfall (its 10,000 less the 5,000 held) on the Refund.
    The second receipt's staff reversal is still refused while the Refund is not returned (fail
    closed: nothing is written). Review round 2: once the Refund comes back in full (a verified
    return), the first Payment's return draft is accepted with nothing to charge back. Renamed
    from `test_a_deposit_funded_by_two_payments_keeps_the_shared_deposit_refusal`."""
    url = migrated_database_url
    case = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    first = payment(url, human, pet, 10_000)
    second = payment(url, human, pet, 10_000)
    service.record_receipt(receipt_command(pet, first, 10_000), actor=allocator(human, prop))
    later = service.record_receipt(
        receipt_command(pet, second, 10_000), actor=allocator(human, prop)
    )
    refund = review_refund(case, qualify_review(case), 15_000)
    assert held(url, pet) == 5_000
    plan = value(
        url, "SELECT app.payment_return_draft_source(%s,%s,NULL)->'recoveries'", prop, first
    )
    assert [
        (entry["refund_id"], entry["amount_usd_cents"], entry["net_usd_cents"]) for entry in plan
    ] == [(str(refund), 5_000, 15_000)]
    with pytest.raises((DepositInvalidError, DepositConflictError)) as refused:
        reverse_receipt_as_owner(
            service,
            ReverseDepositReceiptCommand(
                uuid4(), uuid4(), later.deposit_receipt_id, "The second transfer bounced"
            ),
            actor=deposit_actor(human, prop),
        )
    cause = refused.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert cause.diag.message_primary == DEPENDENT
    reversals = (
        "SELECT count(*) FROM app.deposit_receipt_reversals reversal JOIN app.deposit_receipts "
        "receipt ON receipt.id=reversal.deposit_receipt_id WHERE receipt.deposit_id=%s"
    )
    assert (value(url, reversals, pet), held(url, pet)) == (0, 5_000)
    refund_service().verify_usd_return(
        prop, refund, returned(15_000), actor=actor(human, prop, "refunds.correct")
    )
    draft = returns().record(prop, request(first), actor=return_preparer(human, prop))
    assert draft_state(url, draft_id(draft)) == "PENDING"


def test_a_payment_confirmed_for_an_owed_late_payment_charge_is_not_a_deposit_receipt(
    migrated_database_url: str,
) -> None:
    """Review round 2 (security S1, independent N-2): the Late-payment Charge branch of the intent
    refusal. A Payment of an overdue Customer that names only that Customer's Late-payment Charge
    is refused as a Deposit receipt (55000 until sub-slice 10e-2b-4d; since then 23514, the Credit
    path's excess check, while the Charge is owed; renamed from
    `test_a_payment_confirmed_for_a_late_payment_charge_is_not_a_deposit_receipt`). The refusal
    runs before the receipt table's checks, so here the Charge branch alone decides: without it the
    table would refuse the Payment as another Customer's (23514, another message). Nothing is
    written and the Payment keeps its value."""
    url = migrated_database_url
    overdue = overdue_case(url)
    source = signed_with_initial(url, this_month(url))
    human, prop, security = source["actor"], source["property"], source["deposit"]
    assert overdue["prop"] == prop
    with psycopg.connect(url) as connection:
        charged = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=overdue["customer"],
            amount=10_000,
            late_payment_charge_id=overdue["charge"],
        )
    # Sub-slice 10e-2b-4d: was ("55000", the intent message).
    assert attempt(prop, human, security, charged, 10_000) == ("23514", EXCESS)
    assert written(url, security) == (1, 0, 0)
    assert value(url, "SELECT app.payment_available_value(%s)", charged) == 10_000


def test_after_closure_a_deposit_funded_by_two_payments_keeps_a_bounced_payment_received(
    migrated_database_url: str,
) -> None:
    """Review round 2 (security S2; the known limit of Q-2026-10-18-127): after closure, a Deposit
    funded by two Payments cannot have one of them returned, with or without a Refund. A Pet
    Deposit takes 5,000 from each of two Payments, the pet noncompliance forfeiture keeps the
    10,000 and the Settlement closes. The first Payment's RETURNED_PAYMENT correction is refused
    because the Deposit would not end empty (55000), the ordinary return draft is refused as
    relied on, nothing is written, and the Payment stays RECEIVED. Since sub-slice 10e-2b-4d
    (owner answer (a) to Q-2026-10-18-131 refuses a receipt after the pet noncompliance
    termination) the two receipts are recorded before the termination."""
    url = migrated_database_url
    # Sub-slice 10e-2b-4d: was `pet_lease_case(url)` and the two receipts after the termination.
    case = terminated_pet_lease_case(url, receipts=(5_000, 5_000))
    human, prop, pet = case["human"], case["prop"], case["pet"]
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    first, _ = case["payments"]
    assert held(url, pet) == 10_000
    forfeit_through_draft(deposits, pet)
    closed(case)
    before = counts(url)
    with pytest.raises(FinalSettlementConflictError) as refused:
        record_returned(case, returned_command(case, first))
    assert cause(refused) == ("55000", STILL_HOLDS)
    with pytest.raises(PaymentReturnConflictError) as plain:
        returns().record(prop, request(first), actor=return_preparer(human, prop))
    assert cause(plain) == ("55000", RELIED_ON)
    assert (counts(url), payment_status(url, first)) == (before, "RECEIVED")


def test_the_receipt_writer_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4b-2b adds one writer (SECURITY DEFINER, the fixed search path and UTC,
    EXECUTE only to the financial role) and widens the Deposit command action list by
    `deposit.receipt.record`; no other function, constraint or trigger changes, and it is
    forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261227_153"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert revision.module.GRANTED == (WRITER,)
    assert one(
        migrated_database_url,
        "SELECT p.prosecdef,p.proconfig::text,"
        "has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
        "has_function_privilege('prm_financial',p.oid,'EXECUTE'),"
        "has_function_privilege('prm_bootstrap',p.oid,'EXECUTE'),"
        "p.proacl IS NOT NULL AND p.proacl::text !~ '(^|[{,])=X' "
        "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
        WRITER,
    ) == (True, "{search_path=pg_catalog,TimeZone=UTC}", False, True, False, True)

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str]]:
        functions = {
            str(row[0]): tuple(row[1:])
            for row in rows(
                database,
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'",
            )
        }
        others = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT 'constraint',c.conrelid::regclass::text,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname='app' AND c.contype<>'t' "
                "UNION ALL SELECT 'trigger',t.tgrelid::regclass::text,t.tgname,t.tgenabled::text "
                "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, others

    with _temporary_migration_database("lease_deposit_receipt_writer") as temporary:
        alembic_command.upgrade(config, "20261227_153")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    [old_check] = [item for item in before_others if ":deposit_commands_action_check:" in item]
    [new_check] = [item for item in after_others if ":deposit_commands_action_check:" in item]
    assert after_others - {new_check} == before_others - {old_check}
    assert new_check == old_check.replace(
        "'deposit.reservation_disposition.correct'::text]",
        "'deposit.reservation_disposition.correct'::text, 'deposit.receipt.record'::text]",
    )
    assert set(after_functions) == set(before_functions) | {WRITER}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set()
