"""The fixed measurement unit of each Utility Type (DL-071 answer 9; DB-UTIL-001, TCD-DB-005).

Electricity is measured in kWh and water in cubic metres. New Meters and new Utility Rates use
these codes only; Meters and Rates recorded before keep their stored code (DL-071 transition).
"""

from __future__ import annotations

from typing import Final

MEASUREMENT_UNIT_CODES: Final[dict[str, str]] = {"ELECTRICITY": "KWH", "WATER": "M3"}


def measurement_unit_code_for(utility_type: str, given: str | None) -> str:
    """Return the fixed code for the Utility Type; a different given code is refused."""

    expected = MEASUREMENT_UNIT_CODES[utility_type]
    if given is not None and given.strip() != expected:
        raise ValueError(f"measurement_unit_code must be {expected} for {utility_type}")
    return expected


def fixed_measurement_unit_input(data: object) -> object:
    """Fill or check `measurement_unit_code` in a raw request body before field validation."""

    if not isinstance(data, dict):
        return data
    utility_type = data.get("utility_type")
    if utility_type not in MEASUREMENT_UNIT_CODES:
        return data
    given = data.get("measurement_unit_code")
    if given is not None and not isinstance(given, str):
        return data
    return {**data, "measurement_unit_code": measurement_unit_code_for(utility_type, given)}
