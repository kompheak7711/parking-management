# ruff: noqa: E501
"""A pet classification correction also takes a Damage line billed from an inspection superseded
before closure (V1-056 sub-slice 10c-2a-7).

BR-SETTLE-013, BR-SETTLE-008, BR-MOVEOUT-006, DL-032; DB-SETTLE-007, DB-SETTLE-005; owner answer (a) to
Q-2026-10-08-53, answers (a) to Q-2026-10-11-80 and Q-2026-10-11-85. A relaxing change:

- `app.settlement_pet_classification_line` (exact-text patch): a Damage line billed from a
  finding of any move-out inspection of the Lease may take a `PET_DAMAGE_RECLASSIFICATION`
  correction, also when that inspection was superseded. A superseded inspection was superseded
  before closure, because sub-slice 10c-2a-4 refuses every supersede once the Lease's Final
  Settlement is closed, and the function is used only on a closed Settlement (the recorder's plan
  and the classification insert check).
- Only the change to pet damage is new: on such a line `app.invoice_line_is_pet_damage` reads the
  finding's flag only while its inspection is current, so the line reads as not pet damage until a
  classification record says otherwise, and the existing same-classification refusal keeps the
  change to not pet damage refused. The to-pet reversal rule is unchanged (the line's Security
  Deposit applications are reversed only while a Pet Deposit on the DL-032 path holds money).
- `app.settlement_pet_classification_plan` (exact-text patch): its refusal of a line that may not
  take the correction no longer names "a current inspection" (same SQLSTATE, same case).

No table, column, constraint, trigger, lock or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20261216_142"
down_revision = "20261215_141"
branch_labels = None
depends_on = None

LINE = "app.settlement_pet_classification_line(uuid,uuid)"
LINE_REPLACEMENTS = (
    (
        "              AND line.category='DAMAGE_CHARGES' AND obligation.category='DAMAGE_CHARGES'\n"
        "              AND NOT EXISTS(SELECT 1 FROM app.move_out_inspections later\n"
        "                  WHERE later.supersedes_inspection_id=inspection.id))\n",
        "              AND line.category='DAMAGE_CHARGES' AND obligation.category='DAMAGE_CHARGES')\n"
        "        -- Sub-slice 10c-2a-7 (owner answer (a) to Q-2026-10-08-53): a finding of an\n"
        "        -- inspection of this Lease superseded before closure passes too (no inspection is\n"
        "        -- superseded once the Settlement is closed, sub-slice 10c-2a-4). Such a line reads\n"
        "        -- as not pet damage until a classification record says otherwise, so on a fresh\n"
        "        -- line the same-classification refusal leaves only the change to pet damage.\n",
        1,
    ),
)

PLAN = "app.settlement_pet_classification_plan(uuid,uuid,jsonb)"
PLAN_REPLACEMENTS = (
    (
        "            RAISE EXCEPTION 'A pet classification correction corrects only a Damage line billed from a finding of a current inspection'\n",
        "            RAISE EXCEPTION 'A pet classification correction corrects only a Damage line billed from a finding of a move-out inspection of this Lease'\n",
        1,
    ),
)

PATCHES = (
    (LINE, LINE_REPLACEMENTS),
    (PLAN, PLAN_REPLACEMENTS),
)


def _patch(signature: str, replacements: tuple[tuple[str, str, int], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after, count in replacements:
        if definition.count(before) != count:
            raise RuntimeError(
                f"Superseded inspection pet classification contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Superseded inspection pet classification migration is forward-only")
