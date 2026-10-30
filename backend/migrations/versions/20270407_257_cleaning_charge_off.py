"""Parking Step 5: no cleaning charge at move-out (owner 2026-10-30).

Revision ID: 20270407_257
Revises: 20270406_256
Create Date: 2026-10-30

Property Rental's settlement preview (migration 89) refuses to close a move-out until a cleaning
charge sits on an issued Invoice or the Unit's current cleaning rate is exactly 0, and the Settings
rates by type must be at least 1 cent. Parking charges no cleaning when a customer leaves, so this
migration turns that one check off: the `IF` that adds the blocking issue `CLEANING_CHARGE_MISSING`
becomes `IF false AND ...`. Nothing else changes: the tables, the rate settings,
`app.record_unit_cleaning_charge`, the Invoice line and every amount stay as they are, and a
cleaning charge that already exists still counts as a normal debt of the Settlement.

The edit uses the `pg_get_functiondef` + `replace` pattern of migrations 238 and 247, so a later
Property Rental change to the preview that moves this text makes the migration refuse instead of
silently editing the wrong place. Forward-only.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270407_257"
down_revision: str | None = "20270406_256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"

CLEANING_BEFORE = (
    "            IF v_moved_in AND v_move_out.id IS NOT NULL AND NOT EXISTS(\n"
    "                SELECT 1 FROM app.unit_cleaning_charges cleaning\n"
)
CLEANING_AFTER = (
    "            -- Parking Step 5 (owner 2026-10-30): no cleaning charge at move-out on Parking.\n"
    "            IF false AND v_moved_in AND v_move_out.id IS NOT NULL AND NOT EXISTS(\n"
    "                SELECT 1 FROM app.unit_cleaning_charges cleaning\n"
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Settlement preview source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(PREVIEW, ((CLEANING_BEFORE, CLEANING_AFTER),))


def downgrade() -> None:
    raise RuntimeError("Parking cleaning-charge-off migration is forward-only")
