"""Tests for the single Property's authoritative business-date boundary."""

from datetime import UTC, datetime

import pytest

from property_rental.business_time import property_business_date


def test_property_business_date_changes_at_phnom_penh_midnight() -> None:
    assert property_business_date(datetime(2026, 8, 17, 16, 59, 59, tzinfo=UTC)).isoformat() == (
        "2026-08-17"
    )
    assert property_business_date(datetime(2026, 8, 17, 17, 0, tzinfo=UTC)).isoformat() == (
        "2026-08-18"
    )


def test_property_business_date_normalizes_aware_non_utc_instants() -> None:
    instant = datetime.fromisoformat("2026-08-18T00:00:00+07:00")

    assert property_business_date(instant).isoformat() == "2026-08-18"


def test_property_business_date_rejects_an_instant_without_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        property_business_date(datetime(2026, 8, 18, 0, 0))
