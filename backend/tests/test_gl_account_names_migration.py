"""UI v81 (B5): migration 20270626_360 renames four Ledger accounts' English names only."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

VERSIONS = Path(__file__).parents[1] / "migrations" / "versions"


def _migration() -> ModuleType:
    path = VERSIONS / "20270626_360_gl_account_display_names.py"
    spec = importlib.util.spec_from_file_location("gl_account_names_360", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_360_follows_321_and_is_the_head() -> None:
    module = _migration()
    assert module.revision == "20270626_360"
    assert module.down_revision == "20270716_391"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_heads() == ["20270805_423"]


def test_360_changes_only_the_four_english_names(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _migration()
    assert module.NAMES == {
        "1100": ("Customer debt · Invoices", "Accounts receivable · Invoices"),
        "1110": (
            "Customer debt · late-payment charges",
            "Accounts receivable · late-payment charges",
        ),
        "2210": ("Money not used yet", "Unapplied payments"),
        "3900": ("Profit kept from past years", "Retained earnings"),
    }
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    updates = [s for s in statements if s.startswith("UPDATE")]
    assert len(updates) == 8
    assert all("SET name_en = " in s and "name_km" not in s for s in updates)
    # The template's read-only trigger is paused only around its own updates.
    assert "DISABLE TRIGGER gl_chart_template_reject_update_or_delete" in statements[0]
    assert "ENABLE TRIGGER gl_chart_template_reject_update_or_delete" in statements[5]
    assert all("gl_chart_template" in s for s in statements[1:5])
    assert all("gl_accounts" in s for s in statements[6:])
