"""Exact-money, original coverage, bounded-response and authorization regressions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import cast
from uuid import UUID

import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.termination_invoice import (
    OriginalRentCoverage,
    PostgresTerminationInvoiceReadService,
    TerminationInvoiceAuthorizationError,
    TerminationInvoiceReadiness,
    TerminationInvoiceUnavailableError,
    parse_termination_invoice_readiness,
)

LEASE, PROPERTY, CUSTOMER, EVENT, LINE, INVOICE = (UUID(int=n) for n in range(1, 7))


def payload() -> dict[str, object]:
    return {
        "lease_id": str(LEASE),
        "property_id": str(PROPERTY),
        "customer_id": str(CUSTOMER),
        "lease_status": "TERMINATED",
        "lease_start_date": "2026-01-01",
        "lease_end_date": "2026-12-31",
        "actual_termination_date": "2026-07-10",
        "termination_event_id": str(EVENT),
        "evidence_status": "VOLUNTARY_EARLY_VERIFIED",
        "observed_at": "2026-09-14T12:00:00+00:00",
        "contractual_monthly_usd_cents": 80000,
        "full_final_month_rent_usd_cents": 80000,
        "currency": "USD",
        "financial_completion_assessed": False,
        "financial_dependencies_fully_assessed": False,
        "next_cursor": None,
        "items": [
            {
                "invoice_line_id": str(LINE),
                "invoice_id": str(INVOICE),
                "customer_id": str(CUSTOMER),
                "invoice_version": 4,
                "invoice_status": "PARTIALLY_PAID",
                "issued": True,
                "rent_billing_kind": "RECURRING",
                "category": "RENT",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "source_type": "LEASE",
                "source_id": str(LEASE),
                "original_usd_cents": 80000,
                "adjusted_usd_cents": 75000,
                "payment_applied_usd_cents": 10000,
                "credit_applied_usd_cents": 20000,
                "outstanding_usd_cents": 45000,
                "active_adjustment_count": 1,
                "components": [],
            }
        ],
    }


def line(value: dict[str, object]) -> dict[str, object]:
    return cast(list[dict[str, object]], value["items"])[0]


def parse(value: object) -> TerminationInvoiceReadiness:
    return parse_termination_invoice_readiness(
        value, lease_id=LEASE, property_id=PROPERTY, limit=50
    )


def test_original_contractual_and_current_amounts_never_imply_a_posting() -> None:
    result = parse(payload())
    row = result.items[0]
    assert (
        result.full_final_month_rent_usd_cents,
        row.original_usd_cents,
        row.adjusted_usd_cents,
        row.payment_applied_usd_cents,
        row.credit_applied_usd_cents,
        row.outstanding_usd_cents,
    ) == (80000, 80000, 75000, 10000, 20000, 45000)
    assert (
        result.financial_completion_assessed
        is result.financial_dependencies_fully_assessed
        is False
    )
    assert row.original_rent_coverage is OriginalRentCoverage.FINAL_MONTH
    with pytest.raises(FrozenInstanceError):
        row.outstanding_usd_cents = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    "begin,end,expected",
    [
        ("2026-06-01", "2026-06-30", OriginalRentCoverage.BEFORE_FINAL_MONTH),
        ("2026-06-27", "2026-07-31", OriginalRentCoverage.FINAL_MONTH),
        ("2026-07-27", "2026-08-31", OriginalRentCoverage.FINAL_AND_LATER_MONTHS),
        ("2026-08-01", "2026-08-31", OriginalRentCoverage.LATER_MONTHS),
    ],
)
def test_original_period_classification_preserves_initial_overlap_and_future_coverage(
    begin: str, end: str, expected: OriginalRentCoverage
) -> None:
    value = payload()
    line(value).update(period_start=begin, period_end=end)
    assert parse(value).items[0].original_rent_coverage is expected


def test_separate_service_source_and_void_history_never_become_invalid_rent() -> None:
    value = payload()
    line(value).update(
        category="SERVICE_CHARGES", source_type="PROPERTY_SERVICE", source_id=str(UUID(int=20))
    )
    assert (
        parse(value).items[0].original_rent_coverage is OriginalRentCoverage.NON_RENT_SOURCE_REVIEW
    )
    line(value).update(
        invoice_status="VOID",
        payment_applied_usd_cents=0,
        credit_applied_usd_cents=0,
        outstanding_usd_cents=0,
    )
    assert parse(value).items[0].original_rent_coverage is OriginalRentCoverage.VOID_HISTORY


def test_original_components_are_detail_not_separate_adjusted_obligations() -> None:
    value = payload()
    row = line(value)
    row.update(period_start="2026-06-27", original_usd_cents=93333)
    row["components"] = [
        {
            "id": str(UUID(int=30)),
            "sequence": 1,
            "kind": "PRORATED_MOVE_IN_MONTH",
            "period_start": "2026-06-27",
            "period_end": "2026-06-30",
            "contractual_monthly_usd_cents": 80000,
            "service_monthly_rate_usd_cents": None,
            "amount_usd_cents": 13333,
        },
        {
            "id": str(UUID(int=31)),
            "sequence": 2,
            "kind": "FULL_FOLLOWING_MONTH",
            "period_start": "2026-07-01",
            "period_end": "2026-07-31",
            "contractual_monthly_usd_cents": 80000,
            "service_monthly_rate_usd_cents": None,
            "amount_usd_cents": 80000,
        },
    ]
    result = parse(value)
    assert len(result.items) == 1 and len(result.items[0].components) == 2
    assert result.items[0].adjusted_usd_cents == 75000
    broken = deepcopy(value)
    cast(list[dict[str, object]], line(broken)["components"])[1]["period_start"] = "2026-07-02"
    with pytest.raises(TerminationInvoiceUnavailableError):
        parse(broken)


@pytest.mark.parametrize(
    "key,bad",
    [
        ("lease_id", str(UUID(int=99))),
        ("property_id", str(UUID(int=99))),
        ("customer_id", str(UUID(int=99))),
        ("lease_status", []),
        ("lease_end_date", "2025-12-31"),
        ("actual_termination_date", None),
        ("actual_termination_date", "2026-12-31"),
        ("actual_termination_date", "20260710"),
        ("termination_event_id", None),
        ("termination_event_id", str(UUID(int=0))),
        ("evidence_status", "NO_TERMINATION"),
        ("evidence_status", []),
        ("observed_at", "2026-09-14T12:00:00"),
        ("observed_at", 1),
        ("contractual_monthly_usd_cents", True),
        ("full_final_month_rent_usd_cents", 79999),
        ("currency", "KHR"),
        ("financial_completion_assessed", True),
        ("financial_dependencies_fully_assessed", True),
        ("next_cursor", str(LINE)),
        ("items", None),
    ],
)
def test_malformed_or_overclaiming_observation_is_rejected(key: str, bad: object) -> None:
    value = payload()
    value[key] = bad
    with pytest.raises(TerminationInvoiceUnavailableError):
        parse(value)


@pytest.mark.parametrize(
    "key,bad",
    [
        ("invoice_version", True),
        ("invoice_version", 2**31),
        ("invoice_line_id", str(UUID(int=0))),
        ("customer_id", str(UUID(int=99))),
        ("issued", 1),
        ("issued", False),
        ("invoice_status", "DRAFT"),
        ("category", []),
        ("source_id", str(UUID(int=99))),
        ("source_type", "ARBITRARY"),
        ("rent_billing_kind", None),
        ("period_start", None),
        ("period_end", "2026-06-30"),
        ("original_usd_cents", 80000.0),
        ("adjusted_usd_cents", -1),
        ("payment_applied_usd_cents", 80000),
        ("credit_applied_usd_cents", True),
        ("outstanding_usd_cents", 0),
        ("active_adjustment_count", -1),
        ("components", [{}] * 101),
    ],
)
def test_invalid_financial_source_response_is_rejected(key: str, bad: object) -> None:
    value = payload()
    line(value)[key] = bad
    with pytest.raises(TerminationInvoiceUnavailableError):
        parse(value)


def test_bounded_cursor_is_last_returned_line_and_strictly_advances() -> None:
    value = payload()
    value["next_cursor"] = str(LINE)
    result = parse_termination_invoice_readiness(
        value, lease_id=LEASE, property_id=PROPERTY, limit=1
    )
    assert result.next_cursor == LINE
    with pytest.raises(TerminationInvoiceUnavailableError):
        parse_termination_invoice_readiness(
            value, lease_id=LEASE, property_id=PROPERTY, limit=1, after_line_id=LINE
        )
    value["items"] = [line(value), line(value)]
    with pytest.raises(TerminationInvoiceUnavailableError):
        parse(value)


@pytest.mark.parametrize(
    "capabilities,scope",
    [
        ((), PROPERTY),
        (("leases.read",), PROPERTY),
        (("invoices.read",), PROPERTY),
        (("leases.read", "invoices.read"), UUID(int=99)),
    ],
)
def test_both_read_capabilities_are_required_before_connection(
    monkeypatch: pytest.MonkeyPatch, capabilities: tuple[str, ...], scope: UUID
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Unauthorized reads must not connect")

    monkeypatch.setattr("property_rental.termination_invoice.psycopg.connect", forbidden)
    actor = AuthenticatedActor(
        str(UUID(int=10)),
        frozenset(CapabilityGrant(cap, frozenset({str(scope)})) for cap in capabilities),
    )
    with pytest.raises(TerminationInvoiceAuthorizationError):
        PostgresTerminationInvoiceReadService("unused", PROPERTY).page(LEASE, actor=actor)


@pytest.mark.parametrize("limit", [True, 0, 101, -1, 1.5])
def test_invalid_page_limit_never_connects(limit: object, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Invalid pages must not connect")

    monkeypatch.setattr("property_rental.termination_invoice.psycopg.connect", forbidden)
    with pytest.raises(ValueError):
        PostgresTerminationInvoiceReadService("unused", PROPERTY).page(
            LEASE, actor=AuthenticatedActor(str(UUID(int=10)), frozenset()), limit=cast(int, limit)
        )


def test_unverified_and_unterminated_sources_have_no_full_month_claim() -> None:
    value = payload()
    value.update(
        evidence_status="SIGNED_TERMS_REVIEW_REQUIRED", full_final_month_rent_usd_cents=None
    )
    assert (
        parse(value).items[0].original_rent_coverage
        is OriginalRentCoverage.SIGNED_TERMS_REVIEW_REQUIRED
    )
    value.update(
        evidence_status="NO_TERMINATION",
        lease_status="SIGNED",
        actual_termination_date=None,
        termination_event_id=None,
    )
    assert parse(value).items[0].original_rent_coverage is OriginalRentCoverage.NOT_TERMINATED
