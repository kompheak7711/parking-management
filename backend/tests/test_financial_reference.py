"""Financial visibility and provisional exact FX over existing source selection."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, Inexact, Rounded, localcontext
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from property_rental.configuration_api import ExchangeRateSourceUnavailable
from property_rental.financial_reference import (
    FINANCIAL_CAPABILITIES,
    FinancialReferenceService,
    ReferencePage,
    capabilities,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.khr_payment_confirmation import KhrPaymentConfirmationService
from property_rental.payment_confirmation import (
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationUnavailableError,
)
from property_rental.payment_read import PaymentReadAuthorizationError, PaymentReadInvalidError
from test_credit_migration import actor
from test_khr_payment_confirmation import manual, provider


@pytest.mark.parametrize("capability", FINANCIAL_CAPABILITIES)
def test_financial_reference_capabilities_project_only_exact_existing_grants(
    capability: str,
) -> None:
    prop, human = uuid4(), uuid4()
    result = capabilities(actor(human, prop, capability), prop)
    assert result[capability] and sum(result.values()) == 1
    assert not any(capabilities(actor(human, uuid4(), capability), prop).values())
    assert not any(
        capabilities(
            AuthenticatedActor(str(human), frozenset({CapabilityGrant(capability)})), prop
        ).values()
    )


@pytest.mark.parametrize("value", [0, 101, -1, True, 1.2, "2"])
def test_financial_reference_page_rejects_invalid_limits(value: int) -> None:
    with pytest.raises(PaymentReadInvalidError):
        ReferencePage(value)


def test_financial_reference_queries_bound_selection_and_recheck_fresh_actor() -> None:
    prop, human, first, second = uuid4(), uuid4(), UUID(int=1), UUID(int=2)
    connection = MagicMock()
    connection.execute.return_value.fetchone.side_effect = [(True,), (1,)]
    connection.execute.return_value.fetchall.return_value = [
        (first, "Cash", "Cash method"),
        (second, "Bank", "Bank method"),
    ]
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        result = FinancialReferenceService("synthetic").methods(
            prop, ReferencePage(1), actor=actor(human, prop, "payments.record")
        )
    assert result == {
        "items": [
            {
                "id": str(first),
                "property_id": str(prop),
                "code": "Cash",
                "display_name": "Cash method",
            }
        ],
        "next_cursor": str(first),
    }
    calls = connection.execute.call_args_list
    assert calls[0].args == ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",)
    assert "identity_kind='HUMAN'" in calls[4].args[0]
    assert "ORDER BY id LIMIT %s" in calls[-1].args[0] and calls[-1].args[1] == (None, None, 2)
    connection.execute.return_value.fetchone.side_effect = [(False,)]
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        with pytest.raises(PaymentReadAuthorizationError):
            FinancialReferenceService("synthetic").methods(
                prop, ReferencePage(), actor=actor(human, prop, "payments.record")
            )


def test_financial_reference_workspace_uses_financial_scopes_and_fresh_read_even_when_empty() -> (
    None
):
    human, prop, unrelated = uuid4(), uuid4(), uuid4()
    current = AuthenticatedActor(
        str(human),
        frozenset(
            {
                CapabilityGrant("payments.record", frozenset({str(prop), "malformed"})),
                CapabilityGrant("property.manage", frozenset({str(unrelated)})),
                CapabilityGrant("receipts.read"),
            }
        ),
    )
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (True,)
    connection.execute.return_value.fetchall.return_value = [
        (prop, "Synthetic workspace", "Asia/Phnom_Penh")
    ]
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        result = FinancialReferenceService("synthetic").workspaces(ReferencePage(2), actor=current)
    assert connection.execute.call_args.args[1] == ([prop], None, None, 3)
    assert result["items"] == [
        {
            "property_id": str(prop),
            "name": "Synthetic workspace",
            "timezone": "Asia/Phnom_Penh",
            "capabilities": capabilities(current, prop),
        }
    ]
    assert result["next_cursor"] is None


@pytest.mark.parametrize(
    "rate,usd,system,payable,unrounded",
    [
        ("4062", 1001, 4083, 40871, "40870.83"),
        ("0.000001", 1, 1, 1, "0.01"),
        ("200", 100, 201, 201, "201.00"),
        ("200.000001", 100, 202, 202, "202.00"),
        ("0.000001", 9_000_000_000_000_000, 1, 90_000_000_000_000, "90000000000000.00"),
    ],
)
def test_financial_reference_preview_exact_two_ceilings_ignore_decimal_context(
    rate: str, usd: int, system: int, payable: int, unrounded: str
) -> None:
    prop, human = uuid4(), uuid4()
    source = provider(rate=Decimal(rate))
    service = FinancialReferenceService("synthetic", source)
    with patch.object(FinancialReferenceService, "_read") as read, localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = context.traps[Rounded] = True
        result = service.preview(prop, usd, None, actor=actor(human, prop, "payments.record"))
    read.assert_called_once()
    assert source.calls == 1
    assert result["system_rate_khr_per_usd"] == system
    assert result["payable_khr_amount"] == payable and result["unrounded_khr_amount"] == unrounded
    assert result["usd_amount_cents"] == usd and result["provisional"] is True
    assert result["markup_basis_points"] == 50 and result["rate_source"] == "ABA_AUTOMATIC"


@pytest.mark.parametrize("fallback", [False, True])
def test_financial_reference_preview_only_explicit_unavailable_admits_fallback(
    fallback: bool,
) -> None:
    prop, human = uuid4(), uuid4()
    source = provider()
    source.error = ExchangeRateSourceUnavailable("private upstream detail")
    grants = ("payments.record", "exchange_rates.manage") if fallback else ("payments.record",)
    with patch.object(FinancialReferenceService, "_read"):
        result = FinancialReferenceService("synthetic", source).preview(
            prop, 1001, None, actor=actor(human, prop, *grants)
        )
    assert result == {
        "property_id": str(prop),
        "usd_amount_cents": 1001,
        "provisional": True,
        "status": "source_unavailable",
        "manual_fallback_allowed": fallback,
    }
    source.error = RuntimeError("private transport failure")
    with (
        patch.object(FinancialReferenceService, "_read"),
        pytest.raises(PaymentConfirmationUnavailableError),
    ):
        FinancialReferenceService("synthetic", source).preview(
            prop, 1001, None, actor=actor(human, prop, *grants)
        )


def test_financial_reference_manual_preview_requires_grant_unavailability_and_retains_source() -> (
    None
):
    prop, human = uuid4(), uuid4()
    source = provider()
    service = FinancialReferenceService("synthetic", source)
    with patch.object(FinancialReferenceService, "_read") as read:
        with pytest.raises(PaymentReadAuthorizationError):
            service.preview(prop, 1001, manual(), actor=actor(human, prop, "payments.record"))
        read.assert_not_called()
        assert source.calls == 0
        with pytest.raises(PaymentConfirmationConflictError):
            service.preview(
                prop,
                1001,
                manual(),
                actor=actor(human, prop, "payments.record", "exchange_rates.manage"),
            )
        source.error = ExchangeRateSourceUnavailable("synthetic outage")
        result = service.preview(
            prop,
            1001,
            manual(),
            actor=actor(human, prop, "payments.record", "exchange_rates.manage"),
        )
    assert (
        result["rate_source"] == "ABA_EQUIVALENT_MANUAL"
        and result["automatic_source_unavailable"] is True
    )
    assert (
        result["fallback_reason"] == manual().fallback_reason
        and result["payable_khr_amount"] == 40871
    )
    assert (
        KhrPaymentConfirmationService("synthetic", source)._selection(manual())[
            "reference_rate_khr_per_usd"
        ]
        == result["reference_rate_khr_per_usd"]
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1", 9_000_000_000_000_001])
def test_financial_reference_preview_invalid_amount_never_queries_or_calls_provider(
    value: int,
) -> None:
    source = provider()
    prop = uuid4()
    with (
        patch.object(FinancialReferenceService, "_read") as read,
        pytest.raises(PaymentConfirmationInvalidError),
    ):
        FinancialReferenceService("synthetic", source).preview(
            prop, value, None, actor=actor(uuid4(), prop, "payments.record")
        )
    read.assert_not_called()
    assert source.calls == 0


def test_financial_reference_preview_rejects_future_sources_and_payable_overflow() -> None:
    prop, human = uuid4(), uuid4()
    current = actor(human, prop, "payments.record", "exchange_rates.manage")
    source = provider(datetime.now(UTC) + timedelta(days=1))
    service = FinancialReferenceService("synthetic", source)
    with patch.object(FinancialReferenceService, "_read"):
        with pytest.raises(PaymentConfirmationUnavailableError):
            service.preview(prop, 1, None, actor=current)
        source.error = ExchangeRateSourceUnavailable("outage")
        with pytest.raises(PaymentConfirmationInvalidError):
            service.preview(
                prop,
                1,
                replace(manual(), applicable_at=datetime.now(UTC) + timedelta(days=1)),
                actor=current,
            )
        source.error = None
        source.quote = provider().quote
        with pytest.raises(PaymentConfirmationInvalidError):
            service.preview(prop, 9_000_000_000_000_000, None, actor=current)


def test_financial_reference_denied_or_stale_actor_prevents_provider_access() -> None:
    prop, human = uuid4(), uuid4()
    source = provider()
    service = FinancialReferenceService("synthetic", source)
    with patch.object(FinancialReferenceService, "_read") as read:
        with pytest.raises(PaymentReadAuthorizationError):
            service.preview(prop, 100, None, actor=actor(human, prop, "payments.read"))
        read.assert_not_called()
        read.side_effect = PaymentReadAuthorizationError("disabled")
        with pytest.raises(PaymentReadAuthorizationError):
            service.preview(prop, 100, None, actor=actor(human, prop, "payments.record"))
    assert source.calls == 0
