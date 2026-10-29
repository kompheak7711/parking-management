"""Make Reservation and Receive Security Deposit save in one step (V1-061; DL-112).

Owner bug list of 2026-10-29: the money and the record that holds it are saved together in one
database transaction, or nothing is saved. The same request answers the same records again, and
a refusal at any step leaves no Payment behind.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import database_instant, seed_method
from property_rental.deposit import (
    CreateLeaseSecurityDepositCommand,
    DepositAuthorizationError,
    DepositConflictError,
    DepositIdempotencyKeyReused,
    DepositInvalidError,
    PostgresDepositService,
    RecordDepositReceiptCommand,
)
from property_rental.payment_confirmation import ConfirmUsdPaymentCommand
from property_rental.reservation import (
    PostgresReservationService,
    ReservationCommandConflictError,
    ReservationCreateCommand,
)
from test_credit_migration import actor
from test_deposit_migration import runtime_database_url
from test_invoice_migration import financial_database_url
from test_lease_security_deposit_migration import walk_in_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_reservation_migration import reservation_business_date, setup_reservation_sources

CREATE_RESERVATION = (
    "app.create_reservation(uuid,uuid,text,uuid,uuid,uuid,date,bigint,date,uuid,bigint,text,"
    "timestamp with time zone,text,text,jsonb,uuid,bigint,uuid,uuid,timestamp with time zone,uuid)"
)
RESERVE = (
    "app.create_reservation_with_payment(uuid,uuid,uuid,jsonb,uuid,text,uuid,uuid,uuid,date,"
    "bigint,date,uuid,bigint,text,text,text,jsonb,uuid,bigint,uuid)"
)
RECEIVE = (
    "app.receive_lease_security_deposit_with_payment(uuid,uuid,uuid,jsonb,uuid,text,uuid,uuid,"
    "bigint,text,uuid,text,uuid,bigint)"
)


def money(url: str, human: UUID, payer: UUID, cents: int) -> dict[str, object]:
    with psycopg.connect(url) as connection:
        method = seed_method(connection, human)
        at = database_instant(connection) - timedelta(seconds=1)
    return ConfirmUsdPaymentCommand(
        uuid4(), payer, method, cents, at.astimezone(UTC), "Cash received, Cash"
    ).intent()


def payments(url: str, payer: UUID) -> int:
    """The Customer's Payments (the test Property is shared by many tests)."""
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT count(*) FROM app.payments WHERE payer_customer_id=%s", (payer,)
        ).fetchone()
    assert row is not None
    return int(str(row[0]))


def booking(url: str) -> dict[str, Any]:
    with psycopg.connect(url) as connection:
        human, prop, unit, customer = setup_reservation_sources(connection)
        today = reservation_business_date(connection, prop)
    command = ReservationCreateCommand(
        idempotency_key=uuid4(),
        reservation_id=uuid4(),
        unit_id=unit,
        customer_id=customer,
        reservation_date=today,
        agreed_monthly_rent_usd_cents=50_000,
        original_expiration_date=today + timedelta(days=10),
        acceptance_id=uuid4(),
        accepted_required_amount_usd_cents=10_000,
        acceptance_kind="NORMAL_SUGGESTION",
        accepted_at=None,
        acceptance_reason="Suggested 20% of the agreed Rent",
        authorization_reference="reservations.create",
        calculation_trace={
            "agreed_monthly_rent_usd_cents": 50_000,
            "suggested_rate_basis_points": 2000,
            "suggested_amount_usd_cents": 10_000,
        },
        deposit_id=uuid4(),
        required_deposit_usd_cents=50_000,
        receipt_id=uuid4(),
        # A placeholder: the Payment confirmed in the same transaction replaces it.
        payment_id=uuid4(),
        received_at=None,
    )
    return {
        "human": human,
        "prop": prop,
        "unit": unit,
        "customer": customer,
        "command": command,
        "payment": money(url, human, customer, 10_000),
        "service": PostgresReservationService(
            runtime_database_url(), prop, human, financial_database_url()
        ),
    }


def test_make_reservation_saves_the_money_and_the_reservation_together(
    migrated_database_url: str,
) -> None:
    case = booking(migrated_database_url)
    service = case["service"]
    result, confirmed = service.create_with_payment(case["command"], case["payment"])
    assert (result.reservation_id, result.status, result.received_usd_cents) == (
        case["command"].reservation_id,
        "ACTIVE",
        10_000,
    )
    payment_id = UUID(str(confirmed["payment"]["id"]))
    assert confirmed["receipt"]["receipt_number"]
    with psycopg.connect(migrated_database_url) as connection:
        held = connection.execute(
            "SELECT receipt.payment_id, receipt.amount_usd_cents FROM app.deposit_receipts receipt "
            "WHERE receipt.deposit_id=%s",
            (case["command"].deposit_id,),
        ).fetchall()
    assert held == [(payment_id, 10_000)]

    # The same press again answers the same records and saves nothing more.
    again, replayed = service.create_with_payment(case["command"], case["payment"])
    assert again == result
    assert replayed["payment"]["id"] == confirmed["payment"]["id"]
    assert payments(migrated_database_url, case["customer"]) == 1
    # The same key with other money is refused.
    other = {**case["payment"], "evidence_reference": "Bank transfer 7781"}
    with pytest.raises(ReservationCommandConflictError):
        service.create_with_payment(case["command"], other)
    assert payments(migrated_database_url, case["customer"]) == 1


def test_a_refused_reservation_keeps_no_money(migrated_database_url: str) -> None:
    case = booking(migrated_database_url)
    case["service"].create_with_payment(case["command"], case["payment"])
    before = payments(migrated_database_url, case["customer"])
    # The Unit is Reserved now, so a second Reservation of it is refused after its Payment was
    # confirmed in the same transaction: that Payment is gone with it.
    second = replace(
        case["command"],
        idempotency_key=uuid4(),
        reservation_id=uuid4(),
        acceptance_id=uuid4(),
        deposit_id=uuid4(),
        receipt_id=uuid4(),
    )
    with pytest.raises(ReservationCommandConflictError):
        case["service"].create_with_payment(
            second, money(migrated_database_url, case["human"], case["customer"], 10_000)
        )
    assert payments(migrated_database_url, case["customer"]) == before


def receiving(url: str) -> dict[str, Any]:
    case = walk_in_lease(url)
    case["service"] = PostgresDepositService(financial_database_url(), case["prop"], case["human"])
    case["who"] = actor(
        case["human"], case["prop"], "payments.record", "payments.allocate", "deposits.manage"
    )
    return case


def test_receive_security_deposit_saves_the_money_the_deposit_and_the_receipt_together(
    migrated_database_url: str,
) -> None:
    case = receiving(migrated_database_url)
    key = uuid4()
    deposit = uuid4()
    create = CreateLeaseSecurityDepositCommand(uuid4(), deposit, case["lease"], 50_000, "Received")
    receipt = RecordDepositReceiptCommand(key, uuid4(), deposit, key, 20_000, "Received")
    payment = money(migrated_database_url, case["human"], case["customer"], 20_000)
    value, confirmed = case["service"].receive_with_payment(
        case["lease"], payment, create, receipt, actor=case["who"]
    )
    assert (value.deposit.deposit_id, value.amount_usd_cents) == (deposit, 20_000)
    assert value.payment_id == UUID(str(confirmed["payment"]["id"]))
    assert value.deposit.required_usd_cents == 50_000
    assert value.deposit.outstanding_required_usd_cents == 30_000
    assert payments(migrated_database_url, case["customer"]) == 1
    # The same press again answers the same records.
    again, _ = case["service"].receive_with_payment(
        case["lease"], payment, create, receipt, actor=case["who"]
    )
    assert again.deposit_receipt_id == value.deposit_receipt_id
    assert payments(migrated_database_url, case["customer"]) == 1

    # The rest into the Security Deposit that now exists.
    key = uuid4()
    rest = RecordDepositReceiptCommand(key, uuid4(), deposit, key, 30_000, "Received")
    later, _ = case["service"].receive_with_payment(
        case["lease"],
        money(migrated_database_url, case["human"], case["customer"], 30_000),
        None,
        rest,
        actor=case["who"],
    )
    assert later.deposit.outstanding_required_usd_cents == 0
    assert payments(migrated_database_url, case["customer"]) == 2


def test_a_refused_security_deposit_keeps_no_money(migrated_database_url: str) -> None:
    case = receiving(migrated_database_url)
    deposit = uuid4()
    key = uuid4()
    # More than the Security Deposit asks for: the receipt is refused after the Payment and the
    # new Security Deposit were saved in the same transaction, so neither stays.
    create = CreateLeaseSecurityDepositCommand(uuid4(), deposit, case["lease"], 10_000, "Received")
    receipt = RecordDepositReceiptCommand(key, uuid4(), deposit, key, 20_000, "Received")
    with pytest.raises((DepositConflictError, DepositInvalidError)):
        case["service"].receive_with_payment(
            case["lease"],
            money(migrated_database_url, case["human"], case["customer"], 20_000),
            create,
            receipt,
            actor=case["who"],
        )
    assert payments(migrated_database_url, case["customer"]) == 0
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.deposits WHERE id=%s", (deposit,)
        ).fetchone() == (0,)
    # Another request with the same key is refused, and every right is needed.
    payment = money(migrated_database_url, case["human"], case["customer"], 5_000)
    fine = RecordDepositReceiptCommand(key, uuid4(), deposit, key, 5_000, "Received")
    case["service"].receive_with_payment(case["lease"], payment, create, fine, actor=case["who"])
    with pytest.raises(DepositIdempotencyKeyReused):
        case["service"].receive_with_payment(
            case["lease"],
            {**payment, "evidence_reference": "Bank transfer 7781"},
            create,
            fine,
            actor=case["who"],
        )
    with pytest.raises(DepositAuthorizationError):
        case["service"].receive_with_payment(
            case["lease"],
            payment,
            None,
            fine,
            actor=actor(case["human"], case["prop"], "payments.allocate"),
        )


def test_only_the_financial_role_runs_the_one_step_commands_and_the_migration_is_forward_only(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        for signature in (RESERVE, RECEIVE):
            grants = connection.execute(
                "SELECT has_function_privilege('prm_financial', %s, 'EXECUTE'), "
                "has_function_privilege('prm_runtime', %s, 'EXECUTE')",
                (signature, signature),
            ).fetchone()
            assert grants == (True, False)
        # app.create_reservation itself stays the runtime role's only.
        assert connection.execute(
            "SELECT has_function_privilege('prm_financial', %s, 'EXECUTE')",
            (CREATE_RESERVATION,),
        ).fetchone() == (False,)
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    revision = script.get_revision("20270403_253")
    assert revision is not None
    assert revision.down_revision == "20270402_252"
