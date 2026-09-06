"""Strict USD confirmation intent, scoped capability, exact transport and safe errors."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.adapt import AdaptersMap
from psycopg.pq import Format

from property_rental.payment_confirmation import (
    ConfirmUsdPaymentCommand,
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationService,
    PaymentConfirmationUnavailableError,
)
from test_payment_read import staff


def command() -> ConfirmUsdPaymentCommand:
    return ConfirmUsdPaymentCommand(
        uuid4(), uuid4(), uuid4(), 12345, datetime(2026, 5, 1, tzinfo=UTC), "Verified USD receipt"
    )


@pytest.mark.parametrize("amount", [0, -1, True, 1.25, "100", 9_000_000_000_000_001])
def test_confirmation_rejects_inexact_or_unbounded_received_usd(amount: int) -> None:
    with pytest.raises(PaymentConfirmationInvalidError):
        replace(command(), received_amount_minor=amount)


@pytest.mark.parametrize(
    "field",
    [
        "idempotency_key",
        "payer_customer_id",
        "payment_method_id",
        "lease_id",
        "identified_invoice_id",
        "identified_late_payment_charge_id",
    ],
)
@pytest.mark.parametrize("identity", [UUID(int=0), "not-a-uuid"])
def test_confirmation_requires_typed_non_nil_source_ids(field: str, identity: UUID) -> None:
    with pytest.raises(PaymentConfirmationInvalidError):
        replace(command(), **{field: identity})


@pytest.mark.parametrize(
    "field", ["evidence_reference", "payer_intent_memo", "channel_transaction_reference"]
)
@pytest.mark.parametrize("value", ["", " leading", "trailing ", "\x00", "\ud800", "x" * 2001])
def test_confirmation_evidence_is_normalized_bounded_and_valid(field: str, value: str) -> None:
    with pytest.raises(PaymentConfirmationInvalidError):
        replace(command(), **{field: value})


@pytest.mark.parametrize(
    "received",
    [
        datetime(2026, 5, 1),
        "infinity",
        datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=-1))),
    ],
)
def test_confirmation_received_timestamp_is_aware_and_representable(received: datetime) -> None:
    with pytest.raises(PaymentConfirmationInvalidError):
        replace(command(), received_at=received)


def test_confirmation_third_party_requires_explicit_designation_and_only_known_scope() -> None:
    for scope in ("THIRD_PARTY_IDENTIFIED", "UNKNOWN", None, True, []):
        with pytest.raises(PaymentConfirmationInvalidError):
            replace(command(), payment_scope_kind=scope)  # type: ignore[arg-type]
    identified = replace(command(), payment_scope_kind="THIRD_PARTY_IDENTIFIED", lease_id=uuid4())
    assert identified.intent()["lease_id"] == str(identified.lease_id)


def test_confirmation_intent_preserves_exact_amount_normalizes_utc_and_is_immutable() -> None:
    source = replace(command(), received_amount_minor=9_000_000_000_000_000)
    equivalent = replace(
        source, received_at=source.received_at.astimezone(timezone(timedelta(hours=7)))
    )
    assert source.intent() == equivalent.intent()
    assert source.intent()["received_at"] == "2026-05-01T00:00:00+00:00"
    assert source.intent()["received_amount_minor"] == 9_000_000_000_000_000
    assert source.intent()["received_currency"] == "USD"
    assert {
        "status",
        "usd_accounting_value_cents",
        "allocations",
        "payment_number",
        "exchange_rate_record_id",
    }.isdisjoint(source.intent())
    returned = source.intent()
    returned["received_amount_minor"] = 1
    assert source.intent()["received_amount_minor"] == 9_000_000_000_000_000
    with pytest.raises(FrozenInstanceError):
        source.received_amount_minor = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "cap",
    [
        "payments.read",
        "payments.reverse",
        "payments.allocate",
        "credits.recognize",
        "exchange_rates.manage",
    ],
)
def test_confirmation_requires_separate_exact_property_record_permission(cap: str) -> None:
    prop = uuid4()
    with patch("property_rental.payment_confirmation.psycopg.connect") as connect:
        for denied in (staff(prop, cap), staff(uuid4(), "payments.record")):
            with pytest.raises(PaymentConfirmationAuthorizationError):
                PaymentConfirmationService("unused").confirm_usd(prop, command(), actor=denied)
        connect.assert_not_called()


def test_confirmation_revalidates_intent_and_rejects_untyped_command_before_connection() -> None:
    prop, source = uuid4(), command()
    actor = staff(prop, "payments.record")
    object.__setattr__(source, "received_amount_minor", True)
    with patch("property_rental.payment_confirmation.psycopg.connect") as connect:
        for invalid in (source, {"received_currency": "KHR"}):
            with pytest.raises(PaymentConfirmationInvalidError):
                PaymentConfirmationService("unused").confirm_usd(prop, invalid, actor=actor)  # type: ignore[arg-type]
        connect.assert_not_called()


def database() -> MagicMock:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.adapters = AdaptersMap(psycopg.adapters)
    connection.execute.return_value.fetchone.return_value = ({"payment": {"id": str(uuid4())}},)
    return connection


def test_confirmation_uses_one_scoped_transaction_parameterized_exact_intent_and_safe_decoder() -> (
    None
):
    prop, source, connection = uuid4(), command(), database()
    actor = staff(prop, "payments.record")
    with patch(
        "property_rental.payment_confirmation.psycopg.connect", return_value=connection
    ) as connect:
        result = PaymentConfirmationService("financial-endpoint").confirm_usd(
            prop, source, actor=actor
        )
        assert "payment" in result
        connect.assert_called_once_with("financial-endpoint", connect_timeout=3)
        calls = connection.execute.call_args_list
        assert [call.args[0] for call in calls[:3]] == [
            "SET LOCAL lock_timeout='3000ms'",
            "SET LOCAL statement_timeout='5000ms'",
            "SET LOCAL TIME ZONE 'UTC'",
        ]
        assert calls[3].args[0] == "SELECT app.confirm_usd_payment(%s,%s,%s,%s)"
        params = calls[3].args[1]
        assert params[:3] == (prop, UUID(actor.actor_id), source.idempotency_key)
        assert params[3].obj == source.intent()
        loader = connection.adapters.get_loader(3802, Format.TEXT)
        assert loader is not None
        assert loader(3802).load(b'{"cents":9000000000000000,"rate":4080.123456}') == {
            "cents": 9_000_000_000_000_000,
            "rate": "4080.123456",
        }
        connection.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize(
    "code,expected",
    [
        ("P5301", PaymentConfirmationNotFoundError),
        ("P4501", PaymentConfirmationNotFoundError),
        ("P0002", PaymentConfirmationNotFoundError),
        ("P5305", PaymentConfirmationKeyReused),
        ("P4506", PaymentConfirmationAuthorizationError),
        ("42501", PaymentConfirmationAuthorizationError),
        ("P5302", PaymentConfirmationInvalidError),
        ("22003", PaymentConfirmationInvalidError),
        ("23514", PaymentConfirmationConflictError),
        ("40001", PaymentConfirmationConflictError),
        ("40P01", PaymentConfirmationConflictError),
        ("55000", PaymentConfirmationConflictError),
        ("55P03", PaymentConfirmationUnavailableError),
        ("08006", PaymentConfirmationUnavailableError),
    ],
)
def test_confirmation_errors_redact_database_details_and_preserve_unknown_outcomes(
    code: str, expected: type[Exception]
) -> None:
    prop, connection = uuid4(), database()

    class DatabaseError(psycopg.Error):
        sqlstate = code

    connection.execute.side_effect = DatabaseError("secret DSN SQL customer details")
    with patch("property_rental.payment_confirmation.psycopg.connect", return_value=connection):
        with pytest.raises(expected) as error:
            PaymentConfirmationService("unused").confirm_usd(
                prop, command(), actor=staff(prop, "payments.record")
            )
        assert "secret" not in str(error.value) and "customer details" not in str(error.value)


@pytest.mark.parametrize("row", [None, (None,), ([],), ("invalid",)])
def test_confirmation_missing_result_is_unknown_not_success(row: object) -> None:
    prop, connection = uuid4(), database()
    connection.execute.return_value.fetchone.return_value = row
    with patch("property_rental.payment_confirmation.psycopg.connect", return_value=connection):
        with pytest.raises(PaymentConfirmationUnavailableError):
            PaymentConfirmationService("unused").confirm_usd(
                prop, command(), actor=staff(prop, "payments.record")
            )
