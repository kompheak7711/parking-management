"""Problem types: two short names and an order where the two long names share one row.

Owner 14/11/2026 (Property screen review): "Door and lock" becomes "Door/Lock" and "Furniture or
appliance" becomes "Furniture/appliance". On the New Problem report form the types are tiles,
2 a row on a phone, 3 on an iPad and 4 on a laptop; Furniture/appliance and Safety (fire, gas,
smoke) are the two tallest, so they move to places 5 and 6, which are in the same row at all
three widths. The Khmer names, codes, icons, Safety's "always urgent" and every report stay as
they are; a report keeps pointing at its type by id, so old reports show the new name.

``sort_order`` is UNIQUE (not deferrable), so every type first moves to a free number
(old + 100) and then takes its new place. Forward-only.

Revision ID: 20270725_411
Revises: 20270724_401
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270725_411"
down_revision: str | Sequence[str] | None = "20270724_401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORDER = (
    "WATER",
    "ELECTRICITY",
    "AIR_CONDITIONER",
    "DOOR_LOCK",
    "FURNITURE",
    "SAFETY",
    "WINDOW",
    "INTERNET",
    "PESTS",
    "CLEANING",
    "NOISE",
    "OTHER",
)


def upgrade() -> None:
    """Rename two types and put Furniture/appliance next to Safety."""
    op.execute(
        """
        UPDATE app.problem_types SET name_en = 'Door/Lock'
        WHERE code = 'DOOR_LOCK' AND name_en = 'Door and lock';
        UPDATE app.problem_types SET name_en = 'Furniture/appliance'
        WHERE code = 'FURNITURE' AND name_en = 'Furniture or appliance';
        UPDATE app.problem_types SET sort_order = sort_order + 100
        WHERE code IN ('WATER', 'ELECTRICITY', 'AIR_CONDITIONER', 'DOOR_LOCK', 'FURNITURE',
                       'SAFETY', 'WINDOW', 'INTERNET', 'PESTS', 'CLEANING', 'NOISE', 'OTHER');
        """
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
    raise NotImplementedError("20270725_411 problem type short names is forward-only")
