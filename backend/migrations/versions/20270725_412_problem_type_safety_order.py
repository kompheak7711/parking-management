"""Problem types: Safety goes back after Cleaning and Noise, just before Other.

Owner 14/11/2026: on the New Problem report form a long type name now takes two boxes, so
Safety (fire, gas, smoke) no longer needs to sit beside Furniture/appliance (20270725_411
moved it to place 6). Safety goes back to place 11, after Noise and before Other; Window,
Internet, Pests, Cleaning and Noise move up one place. Names, Khmer names, codes, icons and
"always urgent" stay as they are.

``sort_order`` is UNIQUE (not deferrable), so every type first moves to a free number
(old + 100) and then takes its new place. Forward-only.

Revision ID: 20270725_412
Revises: 20270725_411
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270725_412"
down_revision: str | Sequence[str] | None = "20270725_411"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORDER = (
    "WATER",
    "ELECTRICITY",
    "AIR_CONDITIONER",
    "DOOR_LOCK",
    "FURNITURE",
    "WINDOW",
    "INTERNET",
    "PESTS",
    "CLEANING",
    "NOISE",
    "SAFETY",
    "OTHER",
)


def upgrade() -> None:
    """Put Safety back after Noise and before Other."""
    codes = ", ".join(f"'{code}'" for code in ORDER)
    op.execute(
        f"UPDATE app.problem_types SET sort_order = sort_order + 100 WHERE code IN ({codes})"
    )
    values = ", ".join(f"('{code}', {place})" for place, code in enumerate(ORDER, start=1))
    op.execute(
        f"""
        UPDATE app.problem_types AS kind SET sort_order = wanted.place
        FROM (VALUES {values}) AS wanted (code, place)
        WHERE kind.code = wanted.code;
        """
    )


def downgrade() -> None:
    raise NotImplementedError("20270725_412 problem type Safety order is forward-only")
