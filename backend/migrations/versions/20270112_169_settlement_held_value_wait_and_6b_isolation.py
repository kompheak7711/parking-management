# ruff: noqa: E501
"""A waiting held-value Refund draft in the preview, and the 6b draft at READ COMMITTED only (V1-056 sub-slice 10h-4a).

BR-SETTLE-002, BR-SETTLE-012, BR-SETTLE-013, BR-DEP-019, BR-CREDIT-008, BR-AUTH-010, DL-032.

- Owner answer 2 of 2026-10-20 to the 10h-3 report (the security reviewer's note, checked in the
  10h-4 pre-code design): the Final Settlement preview's pending-draft check also lists another
  Settlement's waiting SETTLEMENT_CORRECTION draft of the variant HELD_VALUE_REFUND whose Credit a
  person of the Lease holds, so the Lease does not close (and, once closed, takes no correction
  step) while that draft would pay the same Credit's money out. One exact-text replacement of the
  filter; a Settlement's own held-value draft is not listed for it.
- Owner answer 1 of 2026-10-20 to the 10h-2 report, the same way as the answer (a) to
  Q-2026-10-19-143: the 6b source app.lease_deposit_reversal_source refuses (55000) a call at an
  isolation level other than READ COMMITTED, before any read, so a 6b draft cannot be recorded
  after the closure from an older snapshot and a waiting one is not confirmed from one (one
  exact-text replacement). No app path or test records or confirms a 6b draft at a stricter level.

Fail-closed refusals the owner approved: two exact-text replacements; signatures, settings and
privileges are kept. No table, column, trigger, constraint or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270112_169"
down_revision = "20270111_168"
branch_labels = None
depends_on = None

PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
SOURCE = "app.lease_deposit_reversal_source(uuid,uuid)"

PREVIEW_REPLACEMENTS = (
    (
        "            -- draft on the Lease's sources.\n",
        "            -- draft on the Lease's sources; since sub-slice 10h-4a (owner answer 2 to the 10h-3\n"
        "            -- report) also another Settlement's held-value Refund correction draft of a Credit\n"
        "            -- a Lease person holds.\n",
    ),
    (
        "                      OR (draft.kind='ADJUSTMENT_REVERSAL' AND draft.payload->>'invoice_adjustment_id' IN (\n",
        "                      OR (draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='HELD_VALUE_REFUND'\n"
        "                          AND draft.payload->>'final_settlement_id' IS DISTINCT FROM p_settlement::text\n"
        "                          AND draft.payload->>'customer_credit_id' IN (SELECT credit.id::text\n"
        "                              FROM app.customer_credits credit WHERE credit.customer_id=ANY(v_people)))\n"
        "                      OR (draft.kind='ADJUSTMENT_REVERSAL' AND draft.payload->>'invoice_adjustment_id' IN (\n",
    ),
)

SOURCE_REPLACEMENTS = (
    (
        "        BEGIN\n"
        "            SELECT * INTO v_disposition FROM app.deposit_dispositions WHERE id=p_disposition;\n",
        "        BEGIN\n"
        "            -- Sub-slice 10h-4a (owner answer 1 to the 10h-2 report): a snapshot older than a\n"
        "            -- closure would not see it, so a 6b draft is recorded and confirmed only at READ\n"
        "            -- COMMITTED.\n"
        "            IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN\n"
        "                RAISE EXCEPTION 'A Lease Deposit forfeiture reversal draft is recorded and confirmed at READ COMMITTED'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            SELECT * INTO v_disposition FROM app.deposit_dispositions WHERE id=p_disposition;\n",
    ),
)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _replaced(signature: str, replacements: tuple[tuple[str, str], ...]) -> str:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Held-value wait and 6b isolation contract changed: {signature}")
        definition = definition.replace(before, after)
    return definition


def upgrade() -> None:
    # CREATE OR REPLACE keeps each function's identity, owner and privileges.
    op.execute(_replaced(PREVIEW, PREVIEW_REPLACEMENTS))
    op.execute(_replaced(SOURCE, SOURCE_REPLACEMENTS))


def downgrade() -> None:
    raise RuntimeError("Held-value wait and 6b isolation migration is forward-only")
