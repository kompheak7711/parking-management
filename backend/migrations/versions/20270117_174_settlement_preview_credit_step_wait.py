# ruff: noqa: E501
"""The preview lists another Settlement's waiting correction draft that uses a Lease person's Credit (V1-056 sub-slice 10i-4c).

BR-SETTLE-002, BR-SETTLE-012, BR-SETTLE-013, BR-CREDIT-008, DL-032; owner answer (a) to
Q-2026-10-20-146: the Final Settlement preview's pending-draft check also lists a closed
Settlement's waiting SETTLEMENT_CORRECTION draft (any variant, not the previewed Settlement's own)
whose plan has a CUSTOMER_CREDIT step on a Credit a person of the Lease holds, or whose REFUND
releases value into such a Credit (a key of its plan overlay's credits that is an existing Credit;
a released Payment allocation is keyed by its allocation and becomes a new Credit only at the
confirm). The other Lease's Settlement then waits until that draft is confirmed, rejected or
withdrawn; no amount rule changes, only the order. One exact-text replacement of the filter
(checked to match once, with its comment); same signature, settings and privileges. No table,
column, trigger, constraint or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270117_174"
down_revision = "20270116_173"
branch_labels = None
depends_on = None

PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"

PREVIEW_REPLACEMENTS = (
    (
        "            -- a Lease person holds.\n",
        "            -- a Lease person holds; since sub-slice 10i-4c (owner answer (a) to\n"
        "            -- Q-2026-10-20-146) also another Settlement's correction draft whose plan uses, or\n"
        "            -- whose REFUND releases value into, a Credit a Lease person holds.\n",
    ),
    (
        "                      OR (draft.kind='ADJUSTMENT_REVERSAL' AND draft.payload->>'invoice_adjustment_id' IN (\n",
        "                      OR (draft.kind='SETTLEMENT_CORRECTION'\n"
        "                          AND draft.payload->>'final_settlement_id' IS DISTINCT FROM p_settlement::text\n"
        "                          AND (EXISTS(SELECT 1 FROM jsonb_array_elements(CASE\n"
        "                                  WHEN jsonb_typeof(draft.payload->'plan'->'steps')='array'\n"
        "                                  THEN draft.payload->'plan'->'steps' ELSE '[]'::jsonb END) step\n"
        "                              JOIN app.customer_credits credit\n"
        "                                  ON credit.id::text=app.final_settlement_plan_id(step->'customer_credit_id')\n"
        "                              WHERE step->>'kind'='CUSTOMER_CREDIT' AND credit.customer_id=ANY(v_people))\n"
        "                          OR (draft.payload->>'variant'='REFUND' AND EXISTS(SELECT 1\n"
        "                              FROM jsonb_object_keys(CASE\n"
        "                                  WHEN jsonb_typeof(draft.payload->'plan_overlay'->'credits')='object'\n"
        "                                  THEN draft.payload->'plan_overlay'->'credits' ELSE '{}'::jsonb END) AS item(key)\n"
        "                              JOIN app.customer_credits credit ON credit.id::text=item.key\n"
        "                              WHERE credit.customer_id=ANY(v_people)))))\n"
        "                      OR (draft.kind='ADJUSTMENT_REVERSAL' AND draft.payload->>'invoice_adjustment_id' IN (\n",
    ),
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
            raise RuntimeError(f"Settlement preview credit step wait contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(PREVIEW, PREVIEW_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Settlement preview credit step wait migration is forward-only")
