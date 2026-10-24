"""The walk-in Lease's Security Deposit and a second receipt before signing (V1-056 sub-slice
10e-2b-4c).

Owner answers to Q-2026-10-17-124: staff enter a walk-in Lease's required Security Deposit total
from the Lease terms with a new `deposits.manage` command (point 1 (a)); its first receipt may be
any amount above 0, never above the required total (point 2 (a)); a second receipt into a
Reservation's Security Deposit before signing is allowed, never above the required total (point 3).
Owner note of 2026-10-17: DL-009 as written also covers extra Deposit money paid before signing (a
Customer-caused cancellation or expiration keeps all of it, a Property-caused one refunds all of
it); the Reservation outcome code classifies, and the cancellation and expiration report, the money
the Deposit holds: its active receipts (review rounds 1 and 2).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_receipt_reversal_test_support import reverse_receipt_through_draft
from payment_test_support import seed_deposit_payment
from property_rental.billing import month_end
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    CreateLeaseSecurityDepositCommand,
    DepositAdjustmentType,
    DepositAuthorizationError,
    DepositIdempotencyKeyReused,
    DepositInvalidError,
    DepositNotFoundError,
    DepositType,
    PostgresDepositService,
)
from property_rental.lease import LEASE_SIGN_CAPABILITY, LeaseSignCommand
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    CompleteMoveInCommand,
    MoveInInvalidError,
    MoveInOccupant,
    PostgresMoveInService,
)
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
    RecordReservationDepositDraftCommand,
    ReservationDepositDecision,
)
from reservation_deposit_test_support import cash_method_id
from test_deposit_migration import deposit_actor, runtime_database_url
from test_deposit_receipt_record_migration import (
    SECURITY_LIMIT,
    allocator,
    attempt,
    other_customer,
    payment,
    receipt_command,
    written,
)
from test_final_settlement_migration import held, one
from test_invoice_migration import financial_database_url
from test_lease_lifecycle_migration import database_now, draft_command, signature_command
from test_lease_migration import create_draft
from test_lease_migration import sign_lease as legacy_sign
from test_lease_signing_reservation_migration import (
    business_date,
    leases,
    reserved_unit,
    signed,
)
from test_migrations import _temporary_migration_database
from test_move_in_migration import actor as move_in_actor
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_pet_payback_restoration_refusal_migration import wait_until_blocked_by
from test_reservation_deposit_draft_migration import drafts, outcome_rows, person
from test_reservation_lifecycle_migration import expired_reservation
from test_reservation_migration import create_reservation, setup_reservation_sources

REVISION = "20261229_155"
CREATE = "app.create_lease_security_deposit(uuid,uuid,uuid,text,uuid,uuid,bigint,text,text)"
CALL = "SELECT app.create_lease_security_deposit(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
MANAGE = "deposits.manage"
REASON = "Security Deposit total from the signed Lease terms"
DIGEST = "b" * 64
CREATE_INVALID = "Security Deposit evidence is invalid"
NOT_SIGNED = "Signed Lease was not found"
FROM_RESERVATION = "Only a walk-in Lease's Security Deposit is created here"
ALREADY = "The Lease already has a Security Deposit"
INACTIVE = "The Deposit's Reservation is not active; this receipt is not recorded here"
DISPOSED = "SELECT amount_usd_cents FROM app.deposit_dispositions WHERE id=%s"
WALK_IN_SOURCE = (
    "A walk-in Security Deposit requires a signed walk-in Lease with no other Security Deposit"
)


def walk_in_lease(url: str) -> dict[str, Any]:
    """A Lease signed through the new path with no Reservation (DL-066), and its sources."""
    with psycopg.connect(url) as connection:
        human, prop, unit, customer = setup_reservation_sources(connection)
    command, _ = signed(url, human, prop, unit, customer, None)
    return {
        "human": human,
        "prop": prop,
        "unit": unit,
        "customer": customer,
        "lease": command.lease_id,
        "service": PostgresDepositService(financial_database_url(), prop, human),
    }


def create_command(lease: UUID, required: int) -> CreateLeaseSecurityDepositCommand:
    return CreateLeaseSecurityDepositCommand(uuid4(), uuid4(), lease, required, REASON)


def create_attempt(
    prop: UUID,
    human: UUID,
    lease: UUID,
    required: int,
    *,
    url: str | None = None,
    reason: str = REASON,
    authorization: str = MANAGE,
    deposit: UUID | None = None,
) -> tuple[Any, Any]:
    """Call the create as the financial role (or the given role) in a transaction of its own,
    which commits when the call passes; the refusal (SQLSTATE and message) or (None, None)."""
    with psycopg.connect(url or financial_database_url()) as connection:
        try:
            connection.execute(
                CALL,
                (
                    prop,
                    human,
                    uuid4(),
                    DIGEST,
                    uuid4() if deposit is None else deposit,
                    lease,
                    required,
                    reason,
                    authorization,
                ),
            )
        except psycopg.Error as refused:
            if refused.sqlstate is None:
                raise
            connection.rollback()
            return refused.sqlstate, refused.diag.message_primary
        connection.commit()
    return None, None


def security_deposits(url: str, lease: UUID) -> int:
    return int(
        value(
            url,
            "SELECT count(*) FROM app.deposits WHERE lease_id=%s AND deposit_type='SECURITY'",
            lease,
        )
    )


def reservation_case(url: str, **options: Any) -> dict[str, Any]:
    """An ACTIVE Reservation (accepted 10,000, required 50,000) and its Security Deposit."""
    human, prop, unit, customer, reservation, deposit = reserved_unit(url)
    return {
        "human": human,
        "prop": prop,
        "unit": unit,
        "customer": customer,
        "reservation": reservation,
        "deposit": deposit,
        "service": PostgresDepositService(financial_database_url(), prop, human),
        **options,
    }


def cancel(case: dict[str, Any], responsibility: CancellationResponsibility) -> Any:
    human, prop = case["human"], case["prop"]
    customer_caused = responsibility is CancellationResponsibility.CUSTOMER
    return PostgresReservationService(
        runtime_database_url(), prop, human, financial_database_url()
    ).cancel(
        ReservationCancelCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=case["reservation"],
            expected_version=1,
            reason_code=(
                "CUSTOMER_WITHDREW" if customer_caused else "PROPERTY_UNABLE_TO_PROVIDE_UNIT"
            ),
            responsibility=responsibility,
            property_could_provide_unit=customer_caused,
            reason_memo="Approved cancellation reason",
            coordination_reference=None if customer_caused else "CASE-RESERVATION-REFUND",
            authorization_reference="reservations.cancel",
        ),
        actor=person(human, prop, "reservations.cancel"),
    )


def expire(human: UUID, prop: UUID, reservation: UUID) -> Any:
    """The expiry command the worker runs, for a Reservation past its expiration date."""
    return PostgresReservationService(
        runtime_database_url(), prop, human, financial_database_url()
    ).expire(
        ReservationExpireCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=reservation,
            expected_version=1,
            property_could_provide_unit=True,
            authorization_reference="reservations.cancel",
        ),
        actor=person(human, prop, "reservations.cancel"),
    )


def forfeit(human: UUID, prop: UUID, reservation: UUID, reason: str) -> UUID:
    """The Reservation Deposit forfeiture draft, confirmed by an approver; the disposition id."""
    outcome = uuid4()
    draft = drafts().record(
        prop,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(uuid4(), reservation, outcome, reason),
        actor=person(human, prop, "reservation_deposits.dispose"),
    )
    drafts().confirm(
        prop,
        reservation,
        UUID(str(draft["draft_id"])),
        actor=person(human, prop, "financial.approve"),
    )
    return outcome


def refund_reservation(case: dict[str, Any]) -> UUID:
    """The Property-caused Reservation Refund draft, confirmed by an approver; the Refund id."""
    human, prop, reservation = case["human"], case["prop"], case["reservation"]
    refund = uuid4()
    draft = drafts().record(
        prop,
        ReservationDepositDecision.REFUND,
        RecordReservationDepositDraftCommand(
            uuid4(),
            reservation,
            refund,
            "Property could not provide the Unit",
            RefundMethodChoice(cash_method_id(prop, human), "Cash handed over at the office"),
        ),
        actor=person(human, prop, "reservation_deposits.refund"),
    )
    drafts().confirm(
        prop,
        reservation,
        UUID(str(draft["draft_id"])),
        actor=person(human, prop, "financial.approve"),
    )
    return refund


def test_a_walk_in_lease_s_security_deposit_is_created_and_takes_any_first_receipt(
    migrated_database_url: str,
) -> None:
    """Owner answers (a) to Q-2026-10-17-124 points 1 and 2: staff create a walk-in Lease's
    Security Deposit with its required total (`deposits.manage`, audited, a command record, an
    exact replay; a reused key with another body is refused); the Customer is the Lease's Primary
    Tenant and the required effective date is the business date of the signing. Its first receipt
    may be any amount above 0, through the 4b writer; receipts reach exactly the required total and
    one cent more is refused by the receipt table."""
    url = migrated_database_url
    case = walk_in_lease(url)
    human, prop, lease = case["human"], case["prop"], case["lease"]
    service: PostgresDepositService = case["service"]
    command = create_command(lease, 30_000)
    created = service.create_lease_security_deposit(command, actor=deposit_actor(human, prop))
    assert (
        created.deposit_type,
        created.customer_id,
        created.reservation_id,
        created.lease_id,
        created.pet_approval_id,
        created.required_usd_cents,
        created.received_usd_cents,
        created.held_refundable_usd_cents,
        created.outstanding_required_usd_cents,
    ) == (DepositType.SECURITY, case["customer"], None, lease, None, 30_000, 0, 0, 30_000)
    assert one(
        url,
        "SELECT deposit.required_effective_date="
        "timezone(property.timezone_name,lease.signed_at)::date,"
        "(SELECT count(*) FROM app.audit_events audit WHERE audit.entity_id=deposit.id "
        "AND audit.action='deposit.security.created' AND audit.authorization_reference=%s "
        "AND audit.reason=%s AND audit.lease_id=deposit.lease_id),"
        "(SELECT count(*) FROM app.deposit_commands item WHERE item.deposit_id=deposit.id "
        "AND item.action='deposit.security.create') "
        "FROM app.deposits deposit JOIN app.leases lease ON lease.id=deposit.lease_id "
        "JOIN app.units unit ON unit.id=lease.unit_id "
        "JOIN app.properties property ON property.id=unit.property_id WHERE deposit.id=%s",
        MANAGE,
        REASON,
        command.deposit_id,
    ) == (True, 1, 1)
    assert service.create_lease_security_deposit(command, actor=deposit_actor(human, prop)) == (
        created
    )
    with pytest.raises(DepositIdempotencyKeyReused):
        service.create_lease_security_deposit(
            CreateLeaseSecurityDepositCommand(
                command.idempotency_key, command.deposit_id, lease, 30_001, REASON
            ),
            actor=deposit_actor(human, prop),
        )
    assert security_deposits(url, lease) == 1
    deposit = command.deposit_id
    first = service.record_receipt(
        receipt_command(deposit, payment(url, human, deposit, 1_234), 1_234),
        actor=allocator(human, prop),
    )
    assert (first.deposit.received_usd_cents, first.deposit.outstanding_required_usd_cents) == (
        1_234,
        28_766,
    )
    rest = service.record_receipt(
        receipt_command(deposit, payment(url, human, deposit, 28_766), 28_766),
        actor=allocator(human, prop),
    )
    assert (
        rest.deposit.held_refundable_usd_cents,
        rest.deposit.outstanding_required_usd_cents,
    ) == (30_000, 0)
    assert attempt(prop, human, deposit, payment(url, human, deposit, 1), 1) == (
        "23514",
        SECURITY_LIMIT,
    )
    assert (held(url, deposit), written(url, deposit)) == (30_000, (2, 2, 2))


def test_the_create_is_only_for_a_signed_walk_in_lease_with_no_security_deposit(
    migrated_database_url: str,
) -> None:
    """Refused: a Lease signed from a Reservation (its Security Deposit is the Reservation's,
    BR-DEP-005; 55000), a Lease signed through the old path with no signing outcome (55000), a
    second create for the same Lease (55000), a Lease that is not signed (P0002); invalid input
    (22023), the runtime role (42501) and an actor without `deposits.manage` (before any call).
    Nothing is written. Two creates for one Lease wait for each other on the Lease row; the second
    is refused."""
    url = migrated_database_url
    human, prop, unit, customer, reservation, _ = reserved_unit(url)
    from_reservation, _ = signed(url, human, prop, unit, customer, reservation)
    assert create_attempt(prop, human, from_reservation.lease_id, 30_000) == (
        "55000",
        FROM_RESERVATION,
    )
    assert security_deposits(url, from_reservation.lease_id) == 1
    with psycopg.connect(url) as connection:
        human, prop, unit, customer = setup_reservation_sources(connection)
        today = business_date(url, prop)
        old_path = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=365),
        )
        legacy_sign(connection, old_path, human)
    assert create_attempt(prop, human, old_path, 30_000) == ("55000", FROM_RESERVATION)
    assert security_deposits(url, old_path) == 0

    case = walk_in_lease(url)
    human, prop, lease = case["human"], case["prop"], case["lease"]
    for refused in (
        {"required": 0},
        {"reason": REASON + " "},
        {"reason": "x" * 1_001},
        {"authorization": "payments.allocate"},
        {"deposit": UUID(int=0)},
    ):
        found = create_attempt(
            prop,
            human,
            lease,
            cast(int, refused.get("required", 30_000)),
            reason=cast(str, refused.get("reason", REASON)),
            authorization=cast(str, refused.get("authorization", MANAGE)),
            deposit=cast(UUID | None, refused.get("deposit")),
        )
        assert found == ("22023", CREATE_INVALID), refused
    assert create_attempt(prop, human, lease, 30_000, url=runtime_database_url())[0] == "42501"
    with pytest.raises(DepositAuthorizationError):
        case["service"].create_lease_security_deposit(
            create_command(lease, 30_000), actor=allocator(human, prop)
        )
    with pytest.raises(DepositNotFoundError):
        case["service"].create_lease_security_deposit(
            create_command(uuid4(), 30_000), actor=deposit_actor(human, prop)
        )
    assert security_deposits(url, lease) == 0

    with psycopg.connect(financial_database_url()) as holder:
        holder.execute(CALL, (prop, human, uuid4(), DIGEST, uuid4(), lease, 30_000, REASON, MANAGE))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting_create = pool.submit(create_attempt, prop, human, lease, 40_000)
            wait_until_blocked_by(url, holder)
            holder.commit()
            assert waiting_create.result(timeout=30) == ("55000", ALREADY)
    assert security_deposits(url, lease) == 1
    assert (
        value(url, "SELECT required_usd_cents FROM app.deposits WHERE lease_id=%s", lease) == 30_000
    )

    with psycopg.connect(url) as connection:
        human, prop, unit, customer = setup_reservation_sources(connection)
        drafted = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=365),
        )
    assert create_attempt(prop, human, drafted, 30_000) == ("P0002", NOT_SIGNED)


def test_the_deposit_table_holds_the_walk_in_rule_and_the_receipt_time_for_every_writer(
    migrated_database_url: str,
) -> None:
    """The table, not only the create, holds the rule (owner inserts, rolled back): a walk-in
    Security Deposit for a Lease signed from a Reservation, for a Lease that is not signed, or a
    second one for a walk-in Lease is refused by the deferred source check (23514). A walk-in
    Deposit's receipt dated before the Lease's signing is refused by the receipt check (23514);
    one dated at the signing passes."""
    url = migrated_database_url
    human, prop, unit, customer, reservation, _ = reserved_unit(url)
    from_reservation, _ = signed(url, human, prop, unit, customer, reservation)
    case = walk_in_lease(url)
    created = case["service"].create_lease_security_deposit(
        create_command(case["lease"], 30_000), actor=deposit_actor(case["human"], case["prop"])
    )
    with psycopg.connect(url) as connection:
        drafter, drafted_prop, drafted_unit, drafted_tenant = setup_reservation_sources(connection)
        drafted = create_draft(
            connection,
            actor_id=drafter,
            unit_id=drafted_unit,
            primary_tenant_id=drafted_tenant,
            start_date=business_date(url, drafted_prop) - timedelta(days=1),
            end_date=business_date(url, drafted_prop) + timedelta(days=365),
        )
    insert = (
        "INSERT INTO app.deposits(id,deposit_type,customer_id,reservation_id,lease_id,"
        "pet_approval_id,required_usd_cents,required_effective_date,created_by,updated_by) "
        "VALUES (%s,'SECURITY',%s,NULL,%s,NULL,30000,current_date,%s,%s)"
    )
    for lease, tenant in (
        (from_reservation.lease_id, customer),
        (drafted, drafted_tenant),
        (case["lease"], case["customer"]),
    ):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(insert, (uuid4(), tenant, lease, human, human))
                connection.execute("SET CONSTRAINTS app.deposits_validate_source IMMEDIATE")
            assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
                "23514",
                WALK_IN_SOURCE,
            ), lease
            connection.rollback()
    deposit = created.deposit_id
    signed_at = value(url, "SELECT signed_at FROM app.leases WHERE id=%s", case["lease"])
    receipt = (
        "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,occurred_at,"
        "actor_id) VALUES (%s,%s,%s,100,%s,%s)"
    )
    with psycopg.connect(url) as connection:
        paid_by = seed_deposit_payment(
            connection,
            deposit_id=deposit,
            actor_id=case["human"],
            amount=100,
            confirmed_at=signed_at - timedelta(hours=1),
        )
        with pytest.raises(psycopg.Error) as early:
            with connection.transaction():
                connection.execute(
                    receipt,
                    (uuid4(), deposit, paid_by, signed_at - timedelta(microseconds=1), human),
                )
        assert (early.value.sqlstate, early.value.diag.message_primary) == (
            "23514",
            SECURITY_LIMIT,
        )
        connection.execute(receipt, (uuid4(), deposit, paid_by, signed_at, human))
        connection.rollback()
    assert held(url, deposit) == 0


def test_a_second_receipt_into_a_reservation_deposit_before_signing_continues_into_the_lease(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-17-124 point 3 (DL-008: the rest may be paid before move-in): a
    second receipt into an ACTIVE Reservation's Security Deposit is recorded through the 4b writer
    (`payments.allocate`) within the required total; more is refused; once staff raise the
    required total with the existing `deposits.manage` adjustment, the next receipt passes; the
    signing then links the same Deposit to the Lease (BR-DEP-005), holding all of it."""
    url = migrated_database_url
    case = reservation_case(url)
    human, prop, deposit = case["human"], case["prop"], case["deposit"]
    service: PostgresDepositService = case["service"]
    second = service.record_receipt(
        receipt_command(deposit, payment(url, human, deposit, 30_000), 30_000),
        actor=allocator(human, prop),
    )
    assert (second.deposit.lease_id, second.deposit.held_refundable_usd_cents) == (None, 40_000)
    assert attempt(prop, human, deposit, payment(url, human, deposit, 10_001), 10_001) == (
        "23514",
        SECURITY_LIMIT,
    )
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            deposit,
            DepositAdjustmentType.INCREASE,
            5_000,
            business_date(url, prop),
            "Required total from the agreed Lease terms",
        ),
        actor=deposit_actor(human, prop),
    )
    third = service.record_receipt(
        receipt_command(deposit, payment(url, human, deposit, 15_000), 15_000),
        actor=allocator(human, prop),
    )
    assert (
        third.deposit.required_usd_cents,
        third.deposit.held_refundable_usd_cents,
        third.deposit.outstanding_required_usd_cents,
    ) == (55_000, 55_000, 0)
    assert written(url, deposit) == (3, 2, 2)
    command, _ = signed(url, human, prop, case["unit"], case["customer"], case["reservation"])
    assert one(
        url,
        "SELECT deposit.lease_id,(SELECT count(*) FROM app.deposits other "
        "WHERE other.lease_id=%s AND other.deposit_type='SECURITY') "
        "FROM app.deposits deposit WHERE deposit.id=%s",
        command.lease_id,
        deposit,
    ) == (command.lease_id, 1)
    assert held(url, deposit) == 55_000


def test_a_receipt_into_a_reservation_deposit_is_refused_once_the_reservation_has_ended(
    migrated_database_url: str,
) -> None:
    """A receipt into a Reservation's Security Deposit is refused (55000) once the Reservation is
    cancelled, and also while it is still ACTIVE but its effective expiration date has passed (the
    signing check's date rule); the service shows it as invalid; nothing is written."""
    url = migrated_database_url
    case = reservation_case(url)
    human, prop, deposit = case["human"], case["prop"], case["deposit"]
    cancel(case, CancellationResponsibility.CUSTOMER)
    paid_by = payment(url, human, deposit, 5_000)
    assert attempt(prop, human, deposit, paid_by, 5_000) == ("55000", INACTIVE)
    with pytest.raises(DepositInvalidError):
        case["service"].record_receipt(
            receipt_command(deposit, paid_by, 5_000), actor=allocator(human, prop)
        )
    assert written(url, deposit) == (1, 0, 0)
    with psycopg.connect(url) as setup:
        human, prop, _, _, reservation, deposit = expired_reservation(setup)
        setup.commit()
    assert value(url, "SELECT status FROM app.reservations WHERE id=%s", reservation) == "ACTIVE"
    assert attempt(prop, human, deposit, payment(url, human, deposit, 5_000), 5_000) == (
        "55000",
        INACTIVE,
    )
    assert written(url, deposit) == (1, 0, 0)
    # The shared test Property keeps no ACTIVE Reservation past its date (the expiry worker tests
    # count them): expire it, as the worker would.
    expire(human, prop, reservation)


def test_dl_009_keeps_or_refunds_all_security_deposit_money_paid_before_signing(
    migrated_database_url: str,
) -> None:
    """Owner note of 2026-10-17 on DL-009: a Customer-caused cancellation keeps all Security Deposit
    money received, also the extra money paid before signing (10,000 accepted and 25,000 more: the
    forfeiture takes 35,000); a Property-caused cancellation refunds all of it (35,000); a
    Customer-caused expiration keeps all of it (the extra receipt in the expired case is seeded by
    an owner insert dated before the expiration, as a receipt recorded while the Reservation was
    active; the writer refuses after the date; every table check still runs)."""
    url = migrated_database_url
    kept = reservation_case(url)
    human, prop, deposit = kept["human"], kept["prop"], kept["deposit"]
    kept["service"].record_receipt(
        receipt_command(deposit, payment(url, human, deposit, 25_000), 25_000),
        actor=allocator(human, prop),
    )
    cancelled = cancel(kept, CancellationResponsibility.CUSTOMER)
    assert (cancelled.deposit_received_usd_cents, cancelled.deposit_outcome_state) == (
        35_000,
        DepositOutcomeState.AWAITING_DECISION,
    )
    outcome = forfeit(human, prop, kept["reservation"], "Customer withdrew before move-in")
    assert value(url, DISPOSED, outcome) == 35_000
    assert (held(url, deposit), outcome_rows(url, kept["reservation"])) == (0, (1, 0))

    refunded = reservation_case(url)
    human, prop, deposit = refunded["human"], refunded["prop"], refunded["deposit"]
    refunded["service"].record_receipt(
        receipt_command(deposit, payment(url, human, deposit, 25_000), 25_000),
        actor=allocator(human, prop),
    )
    cancel(refunded, CancellationResponsibility.PROPERTY)
    refund = uuid4()
    draft = drafts().record(
        prop,
        ReservationDepositDecision.REFUND,
        RecordReservationDepositDraftCommand(
            uuid4(),
            refunded["reservation"],
            refund,
            "Property could not provide the Unit",
            RefundMethodChoice(cash_method_id(prop, human), "Cash handed over at the office"),
        ),
        actor=person(human, prop, "reservation_deposits.refund"),
    )
    drafts().confirm(
        prop,
        refunded["reservation"],
        UUID(str(draft["draft_id"])),
        actor=person(human, prop, "financial.approve"),
    )
    assert one(
        url,
        "SELECT recipient_customer_id,usd_accounting_value_cents FROM app.refunds WHERE id=%s",
        refund,
    ) == (refunded["customer"], 35_000)
    assert (held(url, deposit), outcome_rows(url, refunded["reservation"])) == (0, (0, 1))

    with psycopg.connect(url) as setup:
        human, prop, _, _, reservation, deposit = expired_reservation(setup)
        accepted_at = setup.execute(
            "SELECT accepted_at FROM app.reservation_deposit_acceptances WHERE reservation_id=%s",
            (reservation,),
        ).fetchone()
        assert accepted_at is not None
        extra_at = accepted_at[0] + timedelta(hours=1)
        setup.execute(
            "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
            "occurred_at,actor_id) VALUES (%s,%s,%s,25000,%s,%s)",
            (
                uuid4(),
                deposit,
                seed_deposit_payment(
                    setup, deposit_id=deposit, actor_id=human, amount=25_000, confirmed_at=extra_at
                ),
                extra_at,
                human,
            ),
        )
        setup.commit()
    expired = expire(human, prop, reservation)
    assert (expired.deposit_received_usd_cents, expired.deposit_outcome_state) == (
        35_000,
        DepositOutcomeState.AWAITING_DECISION,
    )
    outcome = forfeit(human, prop, reservation, "Reservation expired while the Unit was available")
    assert value(url, DISPOSED, outcome) == 35_000
    assert held(url, deposit) == 0


def test_a_cancellation_waits_for_a_receipt_that_holds_the_reservation(
    migrated_database_url: str,
) -> None:
    """The writer locks the Reservation (FOR SHARE) before the Deposit, the order signing uses: a
    cancellation started while a receipt is recorded waits for it, and then counts it (10,000 and
    5,000); the forfeiture keeps all 15,000 (DL-009)."""
    url = migrated_database_url
    case = reservation_case(url)
    human, prop, deposit = case["human"], case["prop"], case["deposit"]
    paid_by = payment(url, human, deposit, 5_000)
    with psycopg.connect(financial_database_url()) as holder:
        holder.execute(
            "SELECT app.record_lease_deposit_receipt(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                human,
                uuid4(),
                "c" * 64,
                uuid4(),
                deposit,
                paid_by,
                5_000,
                "Security Deposit balance paid at the office",
                "payments.allocate",
            ),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting_cancel = pool.submit(cancel, case, CancellationResponsibility.CUSTOMER)
            wait_until_blocked_by(url, holder)
            holder.commit()
            cancelled = waiting_cancel.result(timeout=30)
    assert cancelled.deposit_received_usd_cents == 15_000
    outcome = forfeit(human, prop, case["reservation"], "Customer withdrew before move-in")
    assert value(url, DISPOSED, outcome) == 15_000
    assert written(url, deposit) == (2, 1, 1)


def test_the_lease_security_deposit_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4c adds one function (SECURITY DEFINER, the fixed search path, EXECUTE only
    to the financial role), widens the Deposit command action list by `deposit.security.create`
    and the Deposit shape check by the walk-in branch, and patches ten functions by exactly their
    listed replacements; no other function, constraint or trigger changes, and it is
    forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261228_154"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert revision.module.GRANTED == (CREATE,)
    assert one(
        migrated_database_url,
        "SELECT p.prosecdef,p.proconfig::text,"
        "has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
        "has_function_privilege('prm_financial',p.oid,'EXECUTE'),"
        "has_function_privilege('prm_bootstrap',p.oid,'EXECUTE'),"
        "p.proacl IS NOT NULL AND p.proacl::text !~ '(^|[{,])=X' "
        "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
        CREATE,
    ) == (True, "{search_path=pg_catalog}", False, True, False, True)

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str]]:
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

    with _temporary_migration_database("lease_security_deposit") as temporary:
        alembic_command.upgrade(config, "20261228_154")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    changed_checks = {":deposit_commands_action_check:", ":deposits_source_shape:"}
    assert {item for item in after_others if not any(name in item for name in changed_checks)} == {
        item for item in before_others if not any(name in item for name in changed_checks)
    }
    [old_action] = [item for item in before_others if ":deposit_commands_action_check:" in item]
    [new_action] = [item for item in after_others if ":deposit_commands_action_check:" in item]
    assert new_action == old_action.replace(
        "'deposit.receipt.record'::text]",
        "'deposit.receipt.record'::text, 'deposit.security.create'::text]",
    )
    [old_shape] = [item for item in before_others if ":deposits_source_shape:" in item]
    [new_shape] = [item for item in after_others if ":deposits_source_shape:" in item]
    walk_in = (
        " OR ((deposit_type = 'SECURITY'::text) AND (reservation_id IS NULL) "
        "AND (lease_id IS NOT NULL) AND (pet_approval_id IS NULL))"
    )
    pet = " OR ((deposit_type = 'PET'::text)"
    assert old_shape.count(pet) == 1 and walk_in not in old_shape
    assert new_shape == old_shape.replace(pet, walk_in + pet)
    assert set(after_functions) == set(before_functions) | {CREATE}
    patched = {signature: replacements for signature, replacements in revision.module.PATCHES}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(patched)
    for signature, replacements in patched.items():
        expected = before_functions[signature][0]
        for before, after in replacements:
            assert expected.count(before) == 1, signature
            expected = expected.replace(before, after)
        assert after_functions[signature][0] == expected, signature
        assert after_functions[signature][1:] == before_functions[signature][1:], signature


def test_dl_009_classifies_the_active_money_after_an_extra_receipt_is_reversed(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent B1; owner note of 2026-10-17 on DL-009): 10,000 accepted,
    20,000 and 5,000 more paid, and the 20,000 receipt reversed (its Payment bounced) leave the
    Reservation Deposit holding 15,000. A Property-caused cancellation refunds those 15,000 and a
    Customer-caused one forfeits them; before sub-slice 10e-2b-4c the outcome draft was refused
    ("Reservation Deposit has a reversed receipt") and the money could not leave."""
    url = migrated_database_url
    for responsibility in (
        CancellationResponsibility.PROPERTY,
        CancellationResponsibility.CUSTOMER,
    ):
        case = reservation_case(url)
        human, prop, deposit = case["human"], case["prop"], case["deposit"]
        service: PostgresDepositService = case["service"]
        bounced = service.record_receipt(
            receipt_command(deposit, payment(url, human, deposit, 20_000), 20_000),
            actor=allocator(human, prop),
        )
        service.record_receipt(
            receipt_command(deposit, payment(url, human, deposit, 5_000), 5_000),
            actor=allocator(human, prop),
        )
        reverse_receipt_through_draft(
            financial_database_url(), prop, human, bounced.deposit_receipt_id
        )
        assert held(url, deposit) == 15_000
        cancel(case, responsibility)
        if responsibility is CancellationResponsibility.PROPERTY:
            refund = refund_reservation(case)
            assert (
                value(url, "SELECT usd_accounting_value_cents FROM app.refunds WHERE id=%s", refund)
                == 15_000
            )
            assert outcome_rows(url, case["reservation"]) == (0, 1)
        else:
            outcome = forfeit(human, prop, case["reservation"], "Customer withdrew before move-in")
            assert value(url, DISPOSED, outcome) == 15_000
            assert outcome_rows(url, case["reservation"]) == (1, 0)
        assert held(url, deposit) == 0


def test_a_renewal_or_another_customer_gets_no_walk_in_security_deposit(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent S1; Q-2026-10-18-129): a renewal Lease, signed with no
    Reservation, gets no walk-in Security Deposit (the create refuses it, 55000, and so does the
    table, 23514); the table also refuses a walk-in Security Deposit whose Customer is not the
    Lease's Primary Tenant (23514). Nothing is written."""
    url = migrated_database_url
    case = walk_in_lease(url)
    human, prop, predecessor = case["human"], case["prop"], case["lease"]
    service, who = leases(human, prop)
    ends = value(url, "SELECT end_date FROM app.leases WHERE id=%s", predecessor)
    draft = replace(
        draft_command(
            case["unit"],
            case["customer"],
            start_date=ends + timedelta(days=1),
            end_date=month_end(ends + timedelta(days=365)),
        ),
        predecessor_lease_id=predecessor,
    )
    service.draft(draft, actor=who)
    service.record_signature(
        signature_command(draft.lease_id, draft.primary_signer_id, 1), actor=who
    )
    service.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            expected_version=2,
            signed_at=database_now(),
            reason="Renewal signed",
            authorization_reference=LEASE_SIGN_CAPABILITY,
            reservation_id=None,
        ),
        actor=who,
    )
    assert create_attempt(prop, human, draft.lease_id, 30_000) == (
        "55000",
        "A renewal Lease's Security Deposit is not created here",
    )
    insert = (
        "INSERT INTO app.deposits(id,deposit_type,customer_id,reservation_id,lease_id,"
        "pet_approval_id,required_usd_cents,required_effective_date,created_by,updated_by) "
        "VALUES (%s,'SECURITY',%s,NULL,%s,NULL,30000,current_date,%s,%s)"
    )
    for lease, tenant in (
        (draft.lease_id, case["customer"]),
        (predecessor, other_customer(url, human)),
    ):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(insert, (uuid4(), tenant, lease, human, human))
                connection.execute("SET CONSTRAINTS app.deposits_validate_source IMMEDIATE")
            assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
                "23514",
                WALK_IN_SOURCE,
            ), lease
            connection.rollback()
    assert (security_deposits(url, draft.lease_id), security_deposits(url, predecessor)) == (0, 0)


def test_the_create_runs_only_at_read_committed(migrated_database_url: str) -> None:
    """Review round 1 (security note 1): at REPEATABLE READ a second create whose snapshot predates
    the first one's commit would read no Security Deposit; it is refused (55000), as the receipt
    writer refuses other isolation levels; the Lease keeps one Security Deposit."""
    url = migrated_database_url
    case = walk_in_lease(url)
    human, prop, lease = case["human"], case["prop"], case["lease"]
    with (
        psycopg.connect(financial_database_url()) as first,
        psycopg.connect(financial_database_url()) as second,
    ):
        first.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        second.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        second.execute("SELECT 1")
        with pytest.raises(psycopg.Error) as stricter:
            first.execute(
                CALL, (prop, human, uuid4(), DIGEST, uuid4(), lease, 30_000, REASON, MANAGE)
            )
        assert (stricter.value.sqlstate, stricter.value.diag.message_primary) == (
            "55000",
            "A Security Deposit is created at READ COMMITTED",
        )
        first.rollback()
        assert create_attempt(prop, human, lease, 30_000) == (None, None)
        with pytest.raises(psycopg.Error) as refused:
            second.execute(
                CALL, (prop, human, uuid4(), DIGEST, uuid4(), lease, 40_000, REASON, MANAGE)
            )
        assert refused.value.sqlstate == "55000"
        second.rollback()
    assert security_deposits(url, lease) == 1


def test_a_receipt_that_waits_for_a_signing_or_a_cancellation_reads_the_committed_state(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent S2, security note 3): a receipt that waits for a signing holding
    the Reservation lock then finds the Deposit linked to the Lease and takes the Lease path (it is
    recorded, its audit event names the Lease); a receipt that waits for a cancellation is then
    refused (55000) and nothing is written."""
    url = migrated_database_url
    case = reservation_case(url)
    human, prop, deposit = case["human"], case["prop"], case["deposit"]
    service, who = leases(human, prop)
    today = business_date(url, prop)
    draft = draft_command(
        case["unit"],
        case["customer"],
        start_date=today - timedelta(days=1),
        end_date=month_end(today + timedelta(days=365)),
    )
    service.draft(draft, actor=who)
    service.record_signature(
        signature_command(draft.lease_id, draft.primary_signer_id, 1), actor=who
    )
    paid_by = payment(url, human, deposit, 5_000)
    with psycopg.connect(url) as holder:
        holder.execute(
            "SELECT app.sign_lease_with_reservation(%s,%s,%s,%s,%s,2,%s,%s,%s,%s)",
            (
                prop,
                uuid4(),
                "e" * 64,
                uuid4(),
                draft.lease_id,
                database_now(),
                "Lease signed",
                human,
                case["reservation"],
            ),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting_receipt = pool.submit(attempt, prop, human, deposit, paid_by, 5_000)
            wait_until_blocked_by(url, holder)
            holder.commit()
            assert waiting_receipt.result(timeout=30) == (None, None)
    assert value(url, "SELECT lease_id FROM app.deposits WHERE id=%s", deposit) == draft.lease_id
    assert held(url, deposit) == 15_000
    assert one(
        url,
        "SELECT count(*) FROM app.audit_events WHERE action='deposit.receipt.recorded' "
        "AND lease_id=%s",
        draft.lease_id,
    ) == (1,)

    cancelled = reservation_case(url)
    human, prop, deposit = cancelled["human"], cancelled["prop"], cancelled["deposit"]
    paid_by = payment(url, human, deposit, 5_000)
    with psycopg.connect(url) as holder:
        holder.execute(
            "SELECT * FROM app.cancel_reservation_v3(%s,%s,%s,%s,%s,1,'CUSTOMER_WITHDREW',"
            "'CUSTOMER',true,'Approved cancellation reason',NULL,'reservations.cancel',%s)",
            (prop, uuid4(), "d" * 64, uuid4(), cancelled["reservation"], human),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting_receipt = pool.submit(attempt, prop, human, deposit, paid_by, 5_000)
            wait_until_blocked_by(url, holder)
            holder.commit()
            assert waiting_receipt.result(timeout=30) == ("55000", INACTIVE)
    assert (held(url, deposit), written(url, deposit)) == (10_000, (1, 0, 0))


def test_a_walk_in_lease_with_a_security_deposit_takes_no_reservation_deposit_at_move_in(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security should-fix 1): the old Reservation move-in reads no signing
    outcome, so a walk-in Lease that already has its Security Deposit could take a Reservation's
    Deposit too (a Unit set back to VACANT, a Reservation for the same Customer and Unit, then the
    move-in). The deferred source check refuses the link (23514, invalid in the move-in service):
    one Security Deposit per Lease; nothing changes."""
    url = migrated_database_url
    case = walk_in_lease(url)
    human, prop, unit, customer, lease = (
        case[key] for key in ("human", "prop", "unit", "customer", "lease")
    )
    case["service"].create_lease_security_deposit(
        create_command(lease, 30_000), actor=deposit_actor(human, prop)
    )
    number, floor, unit_type, version = one(
        url, "SELECT unit_number,floor,unit_type,version FROM app.units WHERE id=%s", unit
    )
    with psycopg.connect(runtime_database_url()) as connection:
        assert connection.execute(
            "SELECT status FROM app.update_unit(%s,%s,%s,%s,'VACANT',%s,%s)",
            (unit, number, floor, unit_type, version, human),
        ).fetchone() == ("VACANT",)
    with psycopg.connect(url) as connection:
        _, ids = create_reservation(
            connection,
            actor_id=human,
            property_id=prop,
            unit_id=unit,
            customer_id=customer,
            expiration_days=10,
        )
    reserved = ids["deposit_id"]
    case["service"].record_receipt(
        receipt_command(reserved, payment(url, human, reserved, 40_000), 40_000),
        actor=allocator(human, prop),
    )
    command = CompleteMoveInCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        reservation_id=ids["reservation_id"],
        lease_id=lease,
        expected_reservation_version=1,
        expected_lease_version=int(value(url, "SELECT version FROM app.leases WHERE id=%s", lease)),
        expected_unit_version=int(value(url, "SELECT version FROM app.units WHERE id=%s", unit)),
        actual_move_in_date=business_date(url, prop),
        occupants=(MoveInOccupant(uuid4(), customer),),
        reason="All move-in prerequisites verified",
        authorization_reference=MOVE_IN_CAPABILITY,
    )
    with pytest.raises(MoveInInvalidError) as refused:
        PostgresMoveInService(runtime_database_url(), prop, human).complete(
            command, actor=move_in_actor(human, prop)
        )
    cause = refused.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.message_primary) == (
        "23514",
        "Security Deposit sources do not match",
    )
    assert security_deposits(url, lease) == 1
    assert value(url, "SELECT lease_id FROM app.deposits WHERE id=%s", reserved) is None


def test_a_reversed_extra_receipt_is_not_shown_as_received(migrated_database_url: str) -> None:
    """Review round 2 (independent S1): with 10,000 accepted, 20,000 and 5,000 more paid and the
    20,000 receipt reversed, the cancellation reports (and its command result stores) 15,000
    received, the Reservation read API shows 15,000, and the forfeiture keeps 15,000; before
    sub-slice 10e-2b-4c the reversed 20,000 were counted as received."""
    url = migrated_database_url
    case = reservation_case(url)
    human, prop, deposit = case["human"], case["prop"], case["deposit"]
    service: PostgresDepositService = case["service"]
    bounced = service.record_receipt(
        receipt_command(deposit, payment(url, human, deposit, 20_000), 20_000),
        actor=allocator(human, prop),
    )
    service.record_receipt(
        receipt_command(deposit, payment(url, human, deposit, 5_000), 5_000),
        actor=allocator(human, prop),
    )
    reverse_receipt_through_draft(financial_database_url(), prop, human, bounced.deposit_receipt_id)
    cancelled = cancel(case, CancellationResponsibility.CUSTOMER)
    assert (cancelled.deposit_received_usd_cents, cancelled.deposit_outcome_state) == (
        15_000,
        DepositOutcomeState.AWAITING_DECISION,
    )
    assert (
        value(
            url,
            "SELECT (command.result_snapshot->>'deposit_received_usd_cents')::bigint "
            "FROM app.reservation_commands command "
            "WHERE command.action='reservation.cancel' "
            "AND command.result_snapshot->>'reservation_id'=%s",
            str(case["reservation"]),
        )
        == 15_000
    )
    resource = PostgresReservationResourceFlow(runtime_database_url()).get(case["reservation"])
    assert resource.deposit_received_usd_cents == 15_000
    outcome = forfeit(human, prop, case["reservation"], "Customer withdrew before move-in")
    assert value(url, DISPOSED, outcome) == 15_000
