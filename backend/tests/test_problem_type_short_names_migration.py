"""Migration 20270725_411 (owner 14/11/2026): two short Problem type names, and Furniture/appliance
next to Safety so the two longest names share one row of tiles on the New Problem report form."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_migrations import _run_alembic, _temporary_migration_database

REVISION = "20270725_411"
PREVIOUS = "20270724_401"
# Owner 14/11/2026: a long name takes two boxes, so 412 puts Safety back before Other.
SAFETY_BACK = "20270725_412"


def test_migrations_411_and_412_follow_401_and_are_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    safety = scripts.get_revision(SAFETY_BACK)
    assert safety is not None and safety.down_revision == REVISION
    assert scripts.get_heads() == ["20270806_430"]  # 430 (booking page names) follows 415
    for step in (revision, safety):
        with pytest.raises(NotImplementedError, match="forward-only"):
            step.module.downgrade()


def _types(url: str) -> list[tuple[int, str, str, str | None, bool]]:
    with psycopg.connect(url) as connection:
        return [
            (int(order), str(code), str(name), name_kh, bool(urgent))
            for order, code, name, name_kh, urgent in connection.execute(
                "SELECT sort_order, code, name_en, name_kh, always_urgent "
                "FROM app.problem_types ORDER BY sort_order"
            ).fetchall()
        ]


def test_the_types_have_the_short_names_and_the_new_order() -> None:
    """On a database of its own (other tests rebuild the shared one): before 411 the old names
    and order; after 412 the short names and Safety just before Other."""
    with _temporary_migration_database("prm_problem_types") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = _types(temporary)
        assert [(code, name) for _, code, name, _, _ in before][3:6] == [
            ("DOOR_LOCK", "Door and lock"),
            ("WINDOW", "Window"),
            ("FURNITURE", "Furniture or appliance"),
        ]
        assert _run_alembic("upgrade", SAFETY_BACK).returncode == 0
        rows = _types(temporary)
    assert [(order, code, name) for order, code, name, _, _ in rows] == [
        (1, "WATER", "Water"),
        (2, "ELECTRICITY", "Electricity"),
        (3, "AIR_CONDITIONER", "Air conditioner"),
        (4, "DOOR_LOCK", "Door/Lock"),
        (5, "FURNITURE", "Furniture/appliance"),
        (6, "WINDOW", "Window"),
        (7, "INTERNET", "Internet"),
        (8, "PESTS", "Pests"),
        (9, "CLEANING", "Cleaning"),
        (10, "NOISE", "Noise"),
        (11, "SAFETY", "Safety (fire, gas, smoke)"),
        (12, "OTHER", "Other"),
    ]
    # The Khmer names and Safety's "always urgent" stay as they were.
    khmer = {code: name_kh for _, code, _, name_kh, _ in rows}
    assert khmer["DOOR_LOCK"] == "ទ្វារ និងសោ"
    assert khmer["FURNITURE"] == "គ្រឿងសង្ហារឹម ឬឧបករណ៍"
    assert [code for _, code, _, _, urgent in rows if urgent] == ["SAFETY"]
