"""Phone numbers in one format (+855...), as the bots plan decided: "012 345 678" and
"+855 12 345 678" are the same number. Telegram's shared contact sends the number with or
without the "+". A local Cambodian number starts with 0; any other number must carry its
country code.
"""

from __future__ import annotations

import re
from typing import Final

CAMBODIA: Final = "855"
E164: Final = re.compile(r"^\+[1-9][0-9]{6,14}$")


def normalize_phone(value: str) -> str | None:
    """The number as +<country><number>, or None when it is not a phone number."""
    text = value.strip()
    plus = text.startswith("+")
    digits = re.sub(r"[\s().-]", "", text.removeprefix("+"))
    if not digits.isdigit():
        return None
    if plus:
        result = "+" + digits
    elif digits.startswith("00"):
        result = "+" + digits[2:]
    elif digits.startswith("0"):
        result = "+" + CAMBODIA + digits[1:]
    else:
        # Telegram sends the full international number without "+".
        result = "+" + digits
    if result.startswith("+8550"):
        result = "+855" + result[5:]
    return result if E164.fullmatch(result) else None
