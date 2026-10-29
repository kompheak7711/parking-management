"""Every server refusal has Khmer words on the screens (V1-061 Fix 4; owner bug list 29/10/2026).

The screens show a refusal in Khmer by its code (frontend/src/shell/serverText.ts). A new
refusal without Khmer words would show a plain Khmer line instead, so this test names it.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import property_rental
from property_rental.api_refusals import Refusal

SERVER_TEXT = Path(__file__).parents[2] / "frontend" / "src" / "shell" / "serverText.ts"


def refusal_codes() -> set[str]:
    codes: set[str] = set()
    for module in pkgutil.iter_modules(property_rental.__path__):
        loaded = importlib.import_module(f"property_rental.{module.name}")
        codes.update(value.code for value in vars(loaded).values() if isinstance(value, Refusal))
    return codes


def test_every_server_refusal_code_has_khmer_words_on_the_screens() -> None:
    text = SERVER_TEXT.read_text(encoding="utf-8")
    khmer = set(re.findall(r"^  ([A-Z][A-Z0-9_]+):", text, re.MULTILINE))
    codes = refusal_codes()
    assert len(codes) > 200
    assert sorted(codes - khmer) == []
    # The general answers of every route too.
    assert {"FORBIDDEN", "NOT_FOUND", "CONFLICT", "VALIDATION_ERROR"} <= khmer
