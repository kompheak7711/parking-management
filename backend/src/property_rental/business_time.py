"""Authoritative time semantics for the single Property."""

from datetime import date, datetime
from typing import Final
from zoneinfo import ZoneInfo

PROPERTY_TIMEZONE_NAME: Final = "Asia/Phnom_Penh"
PROPERTY_TIMEZONE: Final = ZoneInfo(PROPERTY_TIMEZONE_NAME)


def property_business_date(instant: datetime) -> date:
    """Return the Property-local date for one timezone-aware instant."""
    if instant.utcoffset() is None:
        raise ValueError("instant must be timezone-aware")
    return instant.astimezone(PROPERTY_TIMEZONE).date()
