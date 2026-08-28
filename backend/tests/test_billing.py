"""Deterministic coverage for V1-040 Rent and fixed-Service billing."""

from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from property_rental.billing import (
    BILLING_GENERATE_CAPABILITY,
    BillingAuthorizationError,
    FinalRentTreatment,
    GenerateRentInvoiceCommand,
    PostgresRentBillingService,
    RentBillingKind,
    billing_request_digest,
    final_rent_usd_cents,
    final_service_usd_cents,
    initial_billing_period,
    prorated_monthly_usd_cents,
    recurring_billing_period,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


def test_proration_uses_actual_calendar_days_and_one_half_up_rounding() -> None:
    assert prorated_monthly_usd_cents(80_000, date(2027, 7, 27), date(2027, 7, 31)) == 12_903
    assert prorated_monthly_usd_cents(1_000, date(2027, 7, 27), date(2027, 7, 31)) == 161
    assert prorated_monthly_usd_cents(1, date(2027, 4, 16), date(2027, 4, 30)) == 1
    assert prorated_monthly_usd_cents(29_000, date(2028, 2, 1), date(2028, 2, 29)) == 29_000
    with pytest.raises(ValueError, match="one calendar month"):
        prorated_monthly_usd_cents(80_000, date(2027, 1, 31), date(2027, 2, 1))


@pytest.mark.parametrize(
    ("move_in", "expected_end", "expected_due"),
    (
        (date(2027, 7, 10), date(2027, 7, 31), date(2027, 7, 17)),
        (date(2027, 7, 20), date(2027, 7, 31), date(2027, 7, 27)),
        (date(2027, 7, 21), date(2027, 8, 31), date(2027, 7, 28)),
        (date(2027, 7, 27), date(2027, 8, 31), date(2027, 8, 3)),
    ),
)
def test_initial_period_and_due_date_boundaries(
    move_in: date, expected_end: date, expected_due: date
) -> None:
    assert initial_billing_period(move_in) == (move_in, expected_end, expected_due)


def test_recurring_period_uses_prior_month_twenty_fifth_and_current_month_fifth() -> None:
    assert recurring_billing_period(date(2027, 3, 1)) == (
        date(2027, 3, 1),
        date(2027, 3, 31),
        date(2027, 2, 25),
        date(2027, 3, 5),
    )
    with pytest.raises(ValueError, match="first calendar day"):
        recurring_billing_period(date(2027, 3, 2))


def test_final_rent_distinguishes_approved_partial_from_voluntary_full_month() -> None:
    assert (
        final_rent_usd_cents(
            80_000,
            date(2027, 7, 1),
            date(2027, 7, 15),
            FinalRentTreatment.APPROVED_PARTIAL,
        )
        == 38_710
    )
    assert (
        final_rent_usd_cents(
            80_000,
            date(2027, 7, 1),
            date(2027, 7, 15),
            FinalRentTreatment.VOLUNTARY_FULL_MONTH,
        )
        == 80_000
    )
    with pytest.raises(ValueError, match="one calendar month"):
        final_rent_usd_cents(
            80_000,
            date(2027, 7, 31),
            date(2027, 8, 1),
            FinalRentTreatment.VOLUNTARY_FULL_MONTH,
        )
    with pytest.raises(ValueError, match="one calendar month"):
        final_rent_usd_cents(
            80_000,
            date(2027, 7, 2),
            date(2027, 7, 1),
            FinalRentTreatment.VOLUNTARY_FULL_MONTH,
        )
    with pytest.raises(ValueError, match="treatment"):
        final_rent_usd_cents(
            80_000,
            date(2027, 7, 1),
            date(2027, 7, 15),
            "UNKNOWN",  # type: ignore[arg-type]
        )


def test_final_service_uses_approved_partial_or_full_month_coverage() -> None:
    assert (
        final_service_usd_cents(
            1_200,
            date(2027, 7, 1),
            date(2027, 7, 15),
            FinalRentTreatment.APPROVED_PARTIAL,
        )
        == 581
    )
    assert (
        final_service_usd_cents(
            1_200,
            date(2027, 7, 1),
            date(2027, 7, 15),
            FinalRentTreatment.VOLUNTARY_FULL_MONTH,
        )
        == 1_200
    )


def command(**changes: object) -> GenerateRentInvoiceCommand:
    values: dict[str, object] = {
        "idempotency_key": uuid4(),
        "invoice_id": uuid4(),
        "invoice_number": "INV-2027-0001",
        "lease_id": uuid4(),
        "billing_kind": RentBillingKind.INITIAL,
        "period_start": date(2027, 7, 27),
        "issued_at": datetime(2027, 7, 27, 1, tzinfo=UTC),
        "source_occupancy_id": uuid4(),
    }
    values.update(changes)
    return GenerateRentInvoiceCommand(**values)  # type: ignore[arg-type]


def test_command_validates_shape_and_digest_binds_every_input() -> None:
    value = command()
    assert billing_request_digest(value) == billing_request_digest(value)
    assert billing_request_digest(value) != billing_request_digest(
        command(
            idempotency_key=value.idempotency_key,
            invoice_id=value.invoice_id,
            lease_id=value.lease_id,
            source_occupancy_id=value.source_occupancy_id,
            invoice_number="INV-2027-0002",
        )
    )
    with pytest.raises(ValueError, match="nil UUID"):
        command(invoice_id=UUID(int=0))
    with pytest.raises(ValueError, match="source_occupancy_id"):
        command(source_occupancy_id=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        command(issued_at=datetime(2027, 7, 27, 1))
    with pytest.raises(ValueError, match="RentBillingKind"):
        command(billing_kind="INITIAL")


def test_digest_canonicalizes_equivalent_issuance_instants() -> None:
    value = command()
    same_instant = command(
        idempotency_key=value.idempotency_key,
        invoice_id=value.invoice_id,
        invoice_number=value.invoice_number,
        lease_id=value.lease_id,
        period_start=value.period_start,
        source_occupancy_id=value.source_occupancy_id,
        issued_at=value.issued_at.astimezone(timezone(timedelta(hours=7))),
    )
    assert billing_request_digest(same_instant) == billing_request_digest(value)


def test_service_rejects_actor_and_property_scope_before_database() -> None:
    property_id = uuid4()
    actor_id = uuid4()
    service = PostgresRentBillingService("postgresql://unused", property_id, actor_id)
    value = command()
    missing_scope = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(BILLING_GENERATE_CAPABILITY, frozenset({str(uuid4())}))}
        ),
    )
    with pytest.raises(BillingAuthorizationError):
        service.generate(value, actor=missing_scope)
    wrong_actor = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            {CapabilityGrant(BILLING_GENERATE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    with pytest.raises(BillingAuthorizationError):
        service.generate(value, actor=wrong_actor)
