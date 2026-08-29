"""Deterministic coverage for V1-042 trusted Utility calculations."""

from datetime import UTC, datetime
from decimal import (
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    Inexact,
    InvalidOperation,
    Rounded,
    localcontext,
)
from uuid import UUID, uuid4

import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.utility import (
    UTILITY_CALCULATE_CAPABILITY,
    UTILITY_ESTIMATE_CAPABILITY,
    FinalizeActualConsumptionCommand,
    FinalizeBrokenMeterEstimateCommand,
    OpenBrokenMeterCaseCommand,
    PostgresUtilityService,
    UtilityAuthorizationError,
    actual_consumption_request_digest,
    broken_meter_estimate_request_digest,
    estimated_consumption,
    open_broken_meter_request_digest,
    utility_charge_usd_cents,
    weighted_daily_average,
)


def test_weighted_basis_never_averages_separately_rounded_periods() -> None:
    total = Decimal("10") + Decimal("10") + Decimal("11")
    with localcontext() as context:
        context.prec = 50
        expected_average = total / Decimal(91)
    assert weighted_daily_average(total, 30 + 31 + 30) == expected_average
    assert estimated_consumption(total, 91, 15) == Decimal("5.109890")
    with pytest.raises(ValueError, match="positive"):
        weighted_daily_average(total, 0)
    with pytest.raises(ValueError, match="nonnegative"):
        weighted_daily_average(Decimal("-1"), 30)


def test_utility_calculations_ignore_ambient_decimal_context() -> None:
    with localcontext() as trusted_context:
        trusted_context.prec = 50
        expected_average = Decimal("31") / Decimal(91)
        expected_estimate = (expected_average * Decimal(15)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

    with localcontext() as ambient_context:
        ambient_context.prec = 6
        ambient_context.rounding = ROUND_UP
        ambient_context.traps[Inexact] = True
        ambient_context.traps[Rounded] = True
        assert weighted_daily_average(Decimal("31"), 91) == expected_average
        assert estimated_consumption(Decimal("31"), 91, 15) == expected_estimate
        assert utility_charge_usd_cents(Decimal("1"), Decimal("0.005")) == 1


def test_utility_charge_applies_one_rate_then_rounds_half_up_cents() -> None:
    assert utility_charge_usd_cents(Decimal("10"), Decimal("0.255")) == 255
    assert utility_charge_usd_cents(Decimal("1"), Decimal("0.005")) == 1
    assert (
        utility_charge_usd_cents(Decimal("99999999999999.999999"), Decimal("900.00000001"))
        == 9_000_000_000_100_000_000
    )
    with pytest.raises(ValueError, match="whole-cent range"):
        utility_charge_usd_cents(Decimal("99999999999999.999999"), Decimal("1000.00000001"))
    with pytest.raises(ValueError, match="positive"):
        utility_charge_usd_cents(Decimal("1"), Decimal("0"))


@pytest.mark.parametrize("nonfinite", ["NaN", "sNaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("trap_invalid", [False, True])
def test_utility_calculations_reject_nonfinite_operands(
    nonfinite: str,
    trap_invalid: bool,
) -> None:
    value = Decimal(nonfinite)
    with localcontext() as ambient_context:
        ambient_context.traps[InvalidOperation] = trap_invalid
        with pytest.raises(ValueError, match="finite"):
            weighted_daily_average(value, 30)
        with pytest.raises(ValueError, match="finite"):
            estimated_consumption(value, 30, 10)
        with pytest.raises(ValueError, match="finite"):
            utility_charge_usd_cents(value, Decimal("1"))
        with pytest.raises(ValueError, match="finite"):
            utility_charge_usd_cents(Decimal("1"), value)


def actual_command(**changes: object) -> FinalizeActualConsumptionCommand:
    values: dict[str, object] = {
        "idempotency_key": uuid4(),
        "consumption_period_id": uuid4(),
        "unit_id": uuid4(),
        "utility_type": "ELECTRICITY",
        "start_reading_id": uuid4(),
        "end_reading_id": uuid4(),
        "finalized_at": datetime(2026, 8, 28, tzinfo=UTC),
    }
    values.update(changes)
    return FinalizeActualConsumptionCommand(**values)  # type: ignore[arg-type]


def open_case_command(**changes: object) -> OpenBrokenMeterCaseCommand:
    values: dict[str, object] = {
        "idempotency_key": uuid4(),
        "estimation_case_id": uuid4(),
        "failed_meter_id": uuid4(),
        "replacement_meter_id": uuid4(),
        "opened_reason": "Confirmed physical Meter failure",
        "opened_at": datetime(2026, 8, 28, tzinfo=UTC),
    }
    values.update(changes)
    return OpenBrokenMeterCaseCommand(**values)  # type: ignore[arg-type]


def estimate_command(**changes: object) -> FinalizeBrokenMeterEstimateCommand:
    values: dict[str, object] = {
        "idempotency_key": uuid4(),
        "estimation_case_id": uuid4(),
        "estimate_id": uuid4(),
        "consumption_period_id": uuid4(),
        "authorization_reason": "Approved confirmed broken-Meter estimate",
        "authorized_at": datetime(2026, 8, 28, tzinfo=UTC),
    }
    values.update(changes)
    return FinalizeBrokenMeterEstimateCommand(**values)  # type: ignore[arg-type]


def test_commands_validate_shapes_and_digests_bind_every_input() -> None:
    actual = actual_command()
    assert actual_consumption_request_digest(actual) == actual_consumption_request_digest(actual)
    assert actual_consumption_request_digest(actual) != actual_consumption_request_digest(
        actual_command(
            idempotency_key=actual.idempotency_key,
            consumption_period_id=actual.consumption_period_id,
            unit_id=actual.unit_id,
            start_reading_id=actual.start_reading_id,
            end_reading_id=actual.end_reading_id,
            utility_type="WATER",
        )
    )
    opened = open_case_command()
    assert open_broken_meter_request_digest(opened) != open_broken_meter_request_digest(
        open_case_command(
            idempotency_key=opened.idempotency_key,
            estimation_case_id=opened.estimation_case_id,
            failed_meter_id=opened.failed_meter_id,
            replacement_meter_id=opened.replacement_meter_id,
            opened_reason="Different authorized reason",
        )
    )
    assert open_broken_meter_request_digest(opened) != open_broken_meter_request_digest(
        open_case_command(
            idempotency_key=opened.idempotency_key,
            estimation_case_id=opened.estimation_case_id,
            failed_meter_id=opened.failed_meter_id,
            replacement_meter_id=opened.replacement_meter_id,
            unmeasured_start_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
            unmeasured_end_date=datetime(2026, 8, 15, tzinfo=UTC).date(),
        )
    )
    estimate = estimate_command()
    assert broken_meter_estimate_request_digest(estimate) != broken_meter_estimate_request_digest(
        estimate_command(
            idempotency_key=estimate.idempotency_key,
            estimation_case_id=estimate.estimation_case_id,
            estimate_id=estimate.estimate_id,
            consumption_period_id=estimate.consumption_period_id,
            authorization_reason="Different approval",
        )
    )
    with pytest.raises(ValueError, match="nil UUID"):
        actual_command(unit_id=UUID(int=0))
    with pytest.raises(ValueError, match="distinct Readings"):
        actual_command(start_reading_id=actual.end_reading_id, end_reading_id=actual.end_reading_id)
    with pytest.raises(ValueError, match="timezone-aware"):
        open_case_command(opened_at=datetime(2026, 8, 28))
    with pytest.raises(ValueError, match="supplied together"):
        open_case_command(unmeasured_start_date=datetime(2026, 8, 1, tzinfo=UTC).date())


def actor(actor_id: UUID, property_id: UUID, capability: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset({CapabilityGrant(capability, frozenset({str(property_id)}))}),
    )


def test_service_rejects_actor_property_and_capability_before_database() -> None:
    property_id = uuid4()
    actor_id = uuid4()
    service = PostgresUtilityService("postgresql://unused", property_id, actor_id)
    actual = actual_command()
    with pytest.raises(UtilityAuthorizationError):
        service.finalize_actual(
            actual,
            actor=actor(actor_id, uuid4(), UTILITY_CALCULATE_CAPABILITY),
        )
    with pytest.raises(UtilityAuthorizationError):
        service.finalize_actual(
            actual,
            actor=actor(uuid4(), property_id, UTILITY_CALCULATE_CAPABILITY),
        )
    with pytest.raises(UtilityAuthorizationError):
        service.open_broken_meter_case(
            open_case_command(),
            actor=actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY),
        )
    with pytest.raises(UtilityAuthorizationError):
        service.finalize_broken_meter_estimate(
            estimate_command(authorization_reference="utility.calculate"),
            actor=actor(actor_id, property_id, UTILITY_ESTIMATE_CAPABILITY),
        )
