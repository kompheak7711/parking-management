# ruff: noqa: E501
"""Post-settlement correction: the Customer choice checked again in the shared step (V1-056 sub-slice 10c-2a-6).

BR-DEP-027, BR-SETTLE-013, BR-AUTH-010; owner answer 3 to Q-2026-10-07-44, owner answer 1 to
Q-2026-10-08-52 (approved tightening) and the owner answer to Q-2026-10-08-54 (option (a)):

- A correction that uses the remaining Pet Deposit by the Customer's choice (the CUSTOMER_CHOICE
  basis at a BR-DEP-027 termination) needs a choice given for that correction. The recorders
  compare the choice text with the Final Settlement's choice and with the choice of every earlier
  confirmed correction of that Settlement when the draft is recorded. Two drafts recorded while
  both were pending may carry the same text; the first confirm then left the second unchecked
  unless its variant's confirm checked again (only the pet classification confirm did).
- The shared DL-032 step after closure (app.post_settlement_correction_plan) now checks the choice
  again for every variant that runs it, the committed Refund correction included: under the
  Settlement's draft lock, right after the step's locks and before its stale comparison, a choice
  text equal to the Final Settlement's or to another confirmed correction's is refused (55000, the
  recorders' messages); the refusal rolls the confirm back, so the draft stays pending.
- The function is patched in place (same signature; CREATE OR REPLACE keeps the owner, SECURITY
  DEFINER, settings and privileges). Nothing else changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20261110_106"
down_revision = "20261109_105"
branch_labels = None
depends_on = None

STEP = "app.post_settlement_correction_plan(uuid,uuid,uuid)"
STEP_REPLACEMENTS = (
    (
        "        PERFORM app.lock_settlement_correction_plan(p_draft);\n"
        "        v_plan:=v_draft.payload->'plan';\n",
        "        PERFORM app.lock_settlement_correction_plan(p_draft);\n"
        "        -- Sub-slice 10c-2a-6 (owner answer 1 to Q-2026-10-08-52, owner answer 3 to\n"
        "        -- Q-2026-10-07-44): a Customer choice for the remaining Pet Deposit is checked again\n"
        "        -- here, for every variant, under the Settlement's draft lock and before the stale\n"
        "        -- comparison: neither the Final Settlement's choice nor that of another confirmed\n"
        "        -- correction of this Settlement (two pending drafts may carry the same text; this\n"
        "        -- draft's own decision, written by app.begin_settlement_correction, is left out by its\n"
        "        -- id). The recorded text is compared, as the recorders do.\n"
        "        IF v_draft.payload->'plan'->'pet_remainder'->>'basis'='CUSTOMER_CHOICE' THEN\n"
        "            IF EXISTS(SELECT 1 FROM app.financial_drafts draft\n"
        "                JOIN app.financial_draft_decisions decision\n"
        "                    ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'\n"
        "                WHERE draft.kind='FINAL_SETTLEMENT'\n"
        "                  AND draft.payload->>'final_settlement_id'=v_correction.final_settlement_id::text\n"
        "                  AND draft.payload->'pet_remainder'->>'customer_choice'\n"
        "                      =v_draft.payload->'plan'->'pet_remainder'->>'customer_choice')\n"
        "            THEN RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; the Final Settlement''s choice is not reused'\n"
        "                USING ERRCODE='55000'; END IF;\n"
        "            IF EXISTS(SELECT 1 FROM app.financial_drafts draft\n"
        "                JOIN app.financial_draft_decisions decision\n"
        "                    ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'\n"
        "                WHERE draft.kind='SETTLEMENT_CORRECTION' AND draft.id<>p_draft\n"
        "                  AND draft.payload->>'final_settlement_id'=v_correction.final_settlement_id::text\n"
        "                  AND draft.payload->'plan'->'pet_remainder'->>'customer_choice'\n"
        "                      =v_draft.payload->'plan'->'pet_remainder'->>'customer_choice')\n"
        "            THEN RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; an earlier correction''s choice is not reused'\n"
        "                USING ERRCODE='55000'; END IF;\n"
        "        END IF;\n"
        "        v_plan:=v_draft.payload->'plan';\n",
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
            raise RuntimeError(f"Settlement correction choice source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(STEP, STEP_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Settlement correction choice re-check migration is forward-only")
