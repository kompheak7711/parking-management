"""Incoming KHR intent, approved source selection, authority and exact safe transport."""

from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import Format

from property_rental.configuration_api import ExchangeRateQuote, ExchangeRateSourceUnavailable
from property_rental.khr_payment_confirmation import (
    ConfirmKhrPaymentCommand,
    KhrChannelEvidence,
    KhrPaymentConfirmationService,
    ManualKhrReference,
    _rate,
)
from property_rental.payment_confirmation import (
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationUnavailableError,
)
from test_payment_confirmation import database
from test_payment_read import staff


def command() -> ConfirmKhrPaymentCommand:
    return ConfirmKhrPaymentCommand(
        uuid4(),
        uuid4(),
        uuid4(),
        40871,
        1001,
        datetime(2026, 5, 1, tzinfo=UTC),
        "Verified original incoming KHR receipt",
    )


def manual() -> ManualKhrReference:
    return ManualKhrReference(
        Decimal("4062"),
        "Verified ABA reference",
        command().received_at,
        "Automatic source unavailable",
    )


@dataclass
class Provider:
    quote: ExchangeRateQuote
    error: Exception | None = None
    calls: int = 0

    def current_sell_rate(self) -> ExchangeRateQuote:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.quote


def provider(at: datetime | None = None, rate: Decimal = Decimal("4062")) -> Provider:
    return Provider(
        ExchangeRateQuote(rate, "Verified synthetic ABA quote", at or command().received_at)
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.25, "100", 9_000_000_000_000_001])
@pytest.mark.parametrize("field", ["received_amount_minor", "usd_amount_cents"])
def test_khr_confirmation_requires_exact_bounded_received_and_usd_amounts(
    field: str, value: int
) -> None:
    constructors = {
        "received_amount_minor": lambda: replace(command(), received_amount_minor=value),
        "usd_amount_cents": lambda: replace(command(), usd_amount_cents=value),
    }
    with pytest.raises(PaymentConfirmationInvalidError):
        constructors[field]()


@pytest.mark.parametrize(
    "value",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-1"),
        Decimal("0"),
        Decimal("0.0000001"),
        Decimal("100000000000000"),
        4062.0,
        "4062",
    ],
)
def test_khr_reference_rejects_nondecimal_nonfinite_and_invalid_precision(value: Decimal) -> None:
    with pytest.raises(PaymentConfirmationInvalidError):
        replace(manual(), reference_rate_khr_per_usd=value)


def test_khr_reference_is_exact_under_low_decimal_context_and_preserves_numeric_value() -> None:
    with localcontext() as context:
        context.prec = 3
        assert _rate(Decimal("99999999999999.999999")) == "99999999999999.999999"
        assert _rate(Decimal("4062.000000000")) == "4062.000000"
        assert _rate(Decimal("0.000001")) == "0.000001"


@pytest.mark.parametrize(
    "value", ["", "\t", "\n", "\u00a0padded", "padded\u3000", "\x00", "\ud800", "x" * 501]
)
def test_khr_manual_and_channel_reference_evidence_is_strict(value: str) -> None:
    for build in (
        lambda: replace(manual(), source_reference=value),
        lambda: replace(manual(), fallback_reason=value),
        lambda: KhrChannelEvidence(value, command().received_at, actual_currency="KHR"),
    ):
        with pytest.raises(PaymentConfirmationInvalidError):
            build()


def test_khr_intent_is_immutable_utc_and_contains_no_caller_derived_rate_or_status() -> None:
    source = replace(command(), manual_reference=manual())
    assert source.intent()["received_currency"] == "KHR"
    assert {
        "system_rate_khr_per_usd",
        "status",
        "usd_accounting_value_cents",
        "automatic_source_unavailable",
        "allocations",
    }.isdisjoint(source.intent())
    assert (
        replace(
            source, received_at=source.received_at.astimezone(timezone(timedelta(hours=7)))
        ).intent()
        == source.intent()
    )
    changed = source.intent()
    changed["received_currency"] = "USD"
    assert source.intent()["received_currency"] == "KHR"
    with pytest.raises(FrozenInstanceError):
        source.received_amount_minor = 1  # type: ignore[misc]
    object.__setattr__(source.manual_reference, "source_reference", "\n")
    with pytest.raises(PaymentConfirmationInvalidError):
        source.intent()


def test_khr_channel_requires_actual_facts_matching_reference_and_aware_timestamps() -> None:
    with pytest.raises(PaymentConfirmationInvalidError):
        KhrChannelEvidence("channel reference", command().received_at)
    with pytest.raises(PaymentConfirmationInvalidError):
        KhrChannelEvidence("channel reference", datetime(2026, 5, 1), actual_currency="KHR")
    evidence = KhrChannelEvidence(
        "channel reference", command().received_at, actual_amount_minor=40871
    )
    with pytest.raises(PaymentConfirmationInvalidError):
        replace(command(), channel_evidence=evidence)
    source = replace(
        command(),
        channel_evidence=evidence,
        channel_transaction_reference=evidence.transaction_reference,
    )
    assert source.intent()["channel_evidence"] == evidence.intent()
    assert evidence.intent()["actual_usd_value_cents"] is None
    object.__setattr__(evidence, "actual_amount_minor", True)
    with pytest.raises(PaymentConfirmationInvalidError):
        source.intent()


@pytest.mark.parametrize("manual_source", [False, True])
def test_khr_permissions_fail_before_database_or_provider_and_manual_requires_separate_capability(
    manual_source: bool,
) -> None:
    prop, source, selected = uuid4(), command(), provider()
    if manual_source:
        source = replace(source, manual_reference=manual())
    denied = staff(prop, "payments.record" if manual_source else "payments.read")
    with patch("property_rental.khr_payment_confirmation.psycopg.connect") as connect:
        with pytest.raises(PaymentConfirmationAuthorizationError):
            KhrPaymentConfirmationService("unused", selected).confirm_khr(
                prop, source, actor=denied
            )
        with pytest.raises(PaymentConfirmationAuthorizationError):
            KhrPaymentConfirmationService("unused", selected).confirm_khr(
                prop, source, actor=staff(uuid4(), "payments.record")
            )
        connect.assert_not_called()
    assert selected.calls == 0


def test_khr_source_selection_uses_only_approved_provider_and_actual_outage_for_fallback() -> None:
    selected = provider()
    flow = KhrPaymentConfirmationService("unused", selected)
    automatic = flow._selection(None)
    assert (
        automatic["rate_source"] == "ABA_AUTOMATIC"
        and automatic["automatic_source_unavailable"] is False
    )
    assert automatic["reference_rate_khr_per_usd"] == "4062.000000"
    assert automatic["source_reference"] == selected.quote.source_reference
    with pytest.raises(PaymentConfirmationConflictError):
        flow._selection(manual())
    selected.error = ExchangeRateSourceUnavailable()
    with pytest.raises(PaymentConfirmationUnavailableError):
        flow._selection(None)
    fallback = flow._selection(manual())
    assert fallback == {
        **manual().intent(),
        "rate_source": "ABA_EQUIVALENT_MANUAL",
        "automatic_source_unavailable": True,
    }
    selected.error = RuntimeError("secret provider credential details")
    with pytest.raises(PaymentConfirmationUnavailableError) as failure:
        flow._selection(manual())
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize(
    "quote",
    [
        ExchangeRateQuote(Decimal("NaN"), "reference", command().received_at),
        ExchangeRateQuote(Decimal("4062"), "\t", command().received_at),
        ExchangeRateQuote(Decimal("4062"), "reference", datetime(2026, 5, 1)),
    ],
)
def test_khr_malformed_successful_provider_response_fails_closed(quote: ExchangeRateQuote) -> None:
    with pytest.raises(PaymentConfirmationUnavailableError):
        KhrPaymentConfirmationService("unused", Provider(quote))._selection(None)


def test_khr_replay_skips_source_lookup_and_new_command_parameters_preserve_exact_intent() -> None:
    prop, source, connection, selected = uuid4(), command(), database(), provider()
    connection.execute.return_value.fetchone.side_effect = [
        (None,),
        ({"payment": {"id": "original"}},),
    ]
    with patch(
        "property_rental.khr_payment_confirmation.psycopg.connect", return_value=connection
    ) as connect:
        flow = KhrPaymentConfirmationService("financial-endpoint", selected)
        assert flow.confirm_khr(prop, source, actor=staff(prop, "payments.record")) == {
            "payment": {"id": "original"}
        }
        connect.assert_called_once_with("financial-endpoint", connect_timeout=3)
        calls = connection.execute.call_args_list
        assert calls[3].args[0] == "SELECT app.replay_khr_payment_confirmation(%s,%s,%s,%s)"
        assert calls[4].args[0] == "SELECT app.confirm_khr_payment(%s,%s,%s,%s,%s)"
        assert calls[3].args[1][:3] == (
            prop,
            UUID(staff(prop, "payments.record").actor_id),
            source.idempotency_key,
        )
        assert calls[3].args[1][3].obj == calls[4].args[1][3].obj == source.intent()
        assert calls[4].args[1][4].obj["reference_rate_khr_per_usd"] == "4062.000000"
        loader = connection.adapters.get_loader(3802, Format.TEXT)
        assert loader is not None and loader(3802).load(b'{"rate":4083.123456}') == {
            "rate": "4083.123456"
        }
    assert selected.calls == 1
    connection = database()
    selected.error = AssertionError("Replay must not fetch a new quote")
    with patch("property_rental.khr_payment_confirmation.psycopg.connect", return_value=connection):
        assert "payment" in KhrPaymentConfirmationService("unused", selected).confirm_khr(
            prop, source, actor=staff(prop, "payments.record")
        )
    assert selected.calls == 1 and len(connection.execute.call_args_list) == 4


@pytest.mark.parametrize(
    "code,expected",
    [
        ("P5301", PaymentConfirmationNotFoundError),
        ("P4501", PaymentConfirmationNotFoundError),
        ("P5305", PaymentConfirmationKeyReused),
        ("P4506", PaymentConfirmationAuthorizationError),
        ("42501", PaymentConfirmationAuthorizationError),
        ("P5302", PaymentConfirmationInvalidError),
        ("22003", PaymentConfirmationInvalidError),
        ("23514", PaymentConfirmationConflictError),
        ("40001", PaymentConfirmationConflictError),
        ("40P01", PaymentConfirmationConflictError),
        ("55P03", PaymentConfirmationUnavailableError),
        ("08006", PaymentConfirmationUnavailableError),
    ],
)
def test_khr_database_errors_are_safe_and_unknown_outcomes_never_become_success(
    code: str, expected: type[Exception]
) -> None:
    prop, connection = uuid4(), database()

    class DatabaseError(psycopg.Error):
        sqlstate = code

    connection.execute.side_effect = DatabaseError("secret SQL and DSN details")
    with patch("property_rental.khr_payment_confirmation.psycopg.connect", return_value=connection):
        with pytest.raises(expected) as failure:
            KhrPaymentConfirmationService("unused").confirm_khr(
                prop, command(), actor=staff(prop, "payments.record")
            )
    assert "secret" not in str(failure.value)
