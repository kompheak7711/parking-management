# ruff: noqa: E501
"""Post-settlement correction: the stricter Deposit count of HELD_VALUE_REFUND (V1-056 sub-slice 10c-2b-4).

BR-SETTLE-008, BR-SETTLE-013, DL-032, BR-AUTH-010; owner answer of 2026-10-09 to the Deposit
counting reported after sub-slice 10c-2b-3 (Q-2026-10-09-64, an approved tightening):

- A held-value correction uses, in each Deposit, at most what its earlier correction left there,
  the Lease debt it pays and the Refund together. A Deposit the earlier correction returned
  nothing to gives it nothing (for a Credit correction, no Deposit gives it anything).
- Owner answer (b) to Q-2026-10-09-65: at most, not exactly. The correction must use some of that
  value; the rest stays held for a later correction that names the same earlier correction. Other
  held money stays held until staff prepare a correction that names the earlier correction which
  returned it. BR-SETTLE-008 and the DL-032 order stay as they are.
- The DL-032 order stays: while a Pet Deposit keeps held money that the correction may not use and
  pet damage stays open after the Pet Deposit's step, no Security Deposit step pays pet damage.

Four functions are patched in place (no new function, table or column): the shared plan check
takes the limit as an overlay key, the recorder stores it, the step passes it and the confirm
treats a draft recorded without it as stale.
"""

from alembic import op
from sqlalchemy import text

revision = "20261116_112"
down_revision = "20261115_111"
branch_labels = None
depends_on = None

PLAN_RESULT = "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)"
PLAN_RESULT_REPLACEMENTS = (
    (
        "                    WHERE key NOT IN ('pet_damage','hold_deposits'))\n",
        "                    WHERE key NOT IN ('pet_damage','hold_deposits','held_left'))\n",
    ),
    (
        "            OR jsonb_typeof(COALESCE(p_overlay->'hold_deposits','false'::jsonb)) IS DISTINCT FROM 'boolean'\n",
        "            OR jsonb_typeof(COALESCE(p_overlay->'hold_deposits','false'::jsonb)) IS DISTINCT FROM 'boolean'\n"
        "            -- Sub-slice 10c-2b-4 (owner answer of 2026-10-09, Q-2026-10-09-64): a held-value\n"
        "            -- correction's limit per Deposit (a Deposit id to whole cents), never with the flag above.\n"
        "            OR jsonb_typeof(COALESCE(p_overlay->'held_left','{}'::jsonb)) IS DISTINCT FROM 'object'\n"
        "            OR (p_overlay ? 'held_left' AND p_overlay->'hold_deposits'='true'::jsonb)\n"
        "            OR EXISTS(SELECT 1 FROM jsonb_each(CASE WHEN jsonb_typeof(p_overlay->'held_left')='object'\n"
        "                    THEN p_overlay->'held_left' ELSE '{}'::jsonb END) item\n"
        "                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key\n"
        "                   OR NOT app.settlement_correction_overlay_amount(item.value))\n",
    ),
    (
        "        IF COALESCE((p_overlay->>'hold_deposits')::boolean,false) THEN\n",
        "        -- Sub-slice 10c-2b-4 (owner answer of 2026-10-09, Q-2026-10-09-64): a held-value\n"
        "        -- correction (overlay held_left) uses, in each Deposit, at most what its earlier\n"
        "        -- correction left there, the Lease debt it pays and the Refund together (nothing in a\n"
        "        -- Deposit it returned nothing to); the rest of that value and other held money stay held\n"
        "        -- until a correction names the earlier correction that returned them. BR-SETTLE-008 and\n"
        "        -- the DL-032 order hold for the money it uses (the rules below).\n"
        "        IF p_overlay ? 'held_left' THEN\n"
        "            IF EXISTS(SELECT 1 FROM jsonb_each_text(v_held) item\n"
        "                WHERE item.value::bigint-(v_left->>item.key)::bigint\n"
        "                    >COALESCE((p_overlay->'held_left'->>item.key)::bigint,0))\n"
        "            THEN RAISE EXCEPTION 'A held-value correction uses at most what its earlier correction left in each Deposit'\n"
        "                USING ERRCODE='55000'; END IF;\n"
        "            -- Owner answer (b) to Q-2026-10-09-65: at most, not exactly. Part of that value may stay\n"
        "            -- held for a later correction that names the same earlier correction, but a correction\n"
        "            -- whose limit reaches held money must use some of it.\n"
        "            IF EXISTS(SELECT 1 FROM jsonb_each_text(v_held) item\n"
        "                    WHERE LEAST(item.value::bigint,COALESCE((p_overlay->'held_left'->>item.key)::bigint,0))>0)\n"
        "                AND NOT EXISTS(SELECT 1 FROM jsonb_each_text(v_held) item\n"
        "                    WHERE COALESCE((p_overlay->'held_left'->>item.key)::bigint,0)>0\n"
        "                      AND item.value::bigint-(v_left->>item.key)::bigint>0)\n"
        "            THEN RAISE EXCEPTION 'Every remaining Deposit balance must be applied or refunded' USING ERRCODE='55000';\n"
        "            END IF;\n"
        "            -- DL-032 (owner answer 3 (ii) to Q-2026-10-05-20): the Pet Deposit pays open pet damage\n"
        "            -- first. While a Pet Deposit keeps held money this correction may not use and pet damage\n"
        "            -- stays open after the Pet Deposit's step, no Security Deposit step pays pet damage; the\n"
        "            -- correction that names the Pet Deposit's earlier correction pays it (review rounds 1\n"
        "            -- and 2). A Security Deposit Refund while that debt stays open is refused below.\n"
        "            IF COALESCE(v_pet_after_three,0)>0\n"
        "                AND EXISTS(SELECT 1 FROM jsonb_each_text(v_left) item\n"
        "                    WHERE v_type->>item.key='PET' AND item.value::bigint>0)\n"
        "                AND EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'steps') step\n"
        "                    WHERE step->>'kind'='SECURITY_DEPOSIT'\n"
        "                      AND (step->>'target_kind')||':'||app.final_settlement_plan_id(step->'target_id')\n"
        "                          =ANY(v_pet))\n"
        "            THEN RAISE EXCEPTION 'The Pet Deposit pays open pet damage before any other use or Refund'\n"
        "                USING ERRCODE='55000'; END IF;\n"
        "        ELSIF COALESCE((p_overlay->>'hold_deposits')::boolean,false) THEN\n",
    ),
)

RECORD = "app.record_settlement_held_value_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
RECORD_REPLACEMENTS = (
    (
        "                    'released_payment_allocation_id',NULL))\n"
        "                ELSE '{}'::jsonb END);\n",
        "                    'released_payment_allocation_id',NULL))\n"
        "                ELSE '{}'::jsonb END,\n"
        "            -- Sub-slice 10c-2b-4 (owner answer of 2026-10-09, Q-2026-10-09-64): the step uses, in\n"
        "            -- each Deposit, at most what the earlier correction left there: the value left in its\n"
        "            -- Deposit, nothing in any other (a Credit correction: nothing in any Deposit).\n"
        "            'held_left',CASE WHEN jsonb_typeof(v_plan->'deposit_id')='string'\n"
        "                THEN jsonb_build_object(v_plan->>'deposit_id',v_plan->'left_usd_cents')\n"
        "                ELSE '{}'::jsonb END);\n",
    ),
)

STEP = "app.post_settlement_correction_plan(uuid,uuid,uuid)"
STEP_REPLACEMENTS = (
    (
        "                THEN jsonb_build_object('hold_deposits',true) ELSE '{}'::jsonb END);\n",
        "                THEN jsonb_build_object('hold_deposits',true)\n"
        "                -- Sub-slice 10c-2b-4: a held-value correction keeps the Deposit limit it was\n"
        "                -- recorded with; a draft with none may use no Deposit money.\n"
        "                WHEN v_draft.payload->>'variant'='HELD_VALUE_REFUND'\n"
        "                THEN jsonb_build_object('held_left',COALESCE(v_draft.payload->'plan_overlay'->'held_left','{}'::jsonb))\n"
        "                ELSE '{}'::jsonb END);\n",
    ),
)

CONFIRM = "app.confirm_settlement_held_value_refund(uuid,uuid,uuid,text)"
CONFIRM_REPLACEMENTS = (
    (
        "            OR v_plan->'deposit_id' IS DISTINCT FROM v_draft.payload->'deposit_id'\n",
        "            OR v_plan->'deposit_id' IS DISTINCT FROM v_draft.payload->'deposit_id'\n"
        "            -- Sub-slice 10c-2b-4: the Deposit limit the draft was recorded with (a draft recorded\n"
        "            -- before the limit existed has none and stays pending).\n"
        "            OR v_draft.payload->'plan_overlay'->'held_left' IS DISTINCT FROM (CASE\n"
        "                WHEN jsonb_typeof(v_plan->'deposit_id')='string'\n"
        "                THEN jsonb_build_object(v_plan->>'deposit_id',v_plan->'left_usd_cents')\n"
        "                ELSE '{}'::jsonb END)\n",
    ),
    (
        "        -- Owner answer 1 to Q-2026-10-09-63: every Deposit balance the step settled, whichever\n"
        "        -- earlier correction returned the money (BR-SETTLE-008).\n",
        "        -- Owner answer 1 to Q-2026-10-09-63: every Deposit balance the step settled; since\n"
        "        -- sub-slice 10c-2b-4 only money the earlier correction left in its own Deposit.\n",
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
            raise RuntimeError(f"Held Deposit limit source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(PLAN_RESULT, PLAN_RESULT_REPLACEMENTS)
    _patch(RECORD, RECORD_REPLACEMENTS)
    _patch(STEP, STEP_REPLACEMENTS)
    _patch(CONFIRM, CONFIRM_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Held Deposit limit migration is forward-only")
