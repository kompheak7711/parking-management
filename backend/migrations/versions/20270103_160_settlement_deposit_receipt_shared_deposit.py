# ruff: noqa: E501
"""A receipt correction gives back only a shared Deposit's shortfall (V1-056 sub-slice 10e-2b-4e-2b-2a).

BR-SETTLE-013, BR-SETTLE-016, DL-032, DL-053; DB-SETTLE-005, DB-DEP-007, DB-REFUND-002; owner answer
(a) to Q-2026-10-18-127 ("the receipt correction does the same") and owner answers (a) to
Q-2026-10-18-134 (newest first): after closure, when the corrected receipt's Deposit also holds
another Payment's active receipt (a shared Deposit), the DEPOSIT_RECEIPT_CORRECTION gives back only
the Deposit's shortfall (the corrected receipt less what the Deposit holds, never below 0) from its
uses still in force, newest first: a Refund that is not fully returned by the existing recovery
charge of its share to its recipient, and a Deposit application by its reversal (the debt comes
back on the obligation's Customer, BR-SETTLE-016) with its kept part written again, linked to the
correction. Then the receipt is reversed and the Deposit holds only the other Payments' money. The
freed value stays with the Payment, or the right receipts and the plan take it, as before. A
Deposit funded by one Payment is unchanged, and so are its source and digest.

- An active forfeiture of the Deposit stays refused (owner answer (a) to Q-2026-10-11-83 point 3:
  staff reverse it with a FORFEITURE_REVERSAL first), so no forfeiture is given back here.
- Known limits (fail closed): with right receipts, a shared Deposit that would still hold money
  after the correction is refused (staff first pay that money out with a HELD_VALUE_REFUND
  correction), and so is a right receipt into a shared Deposit with the Customer's pay-back money;
  a plan Deposit step whose DL-032 stage comes before a kept application part is refused at record
  time (the Deposit application check keeps the stage order within a correction), and so is a plan
  Deposit step equal to a kept part (review round 1: that check would count it as the kept part),
  and a plan Customer Credit step beside a kept part (review round 2: the correction's Credit order
  check refuses Credit after its Deposit applications).
- Review round 1 (security): the shared receipt reversal branch of this correction keeps the
  table's active-forfeiture refusal.

New internal function (no grant): app.settlement_deposit_receipt_correction_shared.
Exact-text patches (each replacement checked to match once):
app.settlement_deposit_receipt_correction_source,
app.assert_settlement_deposit_receipt_correction_allowed,
app.assert_settlement_deposit_receipt_targets_allowed,
app.record_settlement_deposit_receipt_correction_draft,
app.post_settlement_deposit_receipt_correction,
app.settlement_deposit_receipt_correction_overlay,
app.settlement_shared_deposit_kept_application_allowed,
app.payment_return_shortfall_recovery_amount and
app.payment_return_shared_receipt_reversal_allowed. No table, column, trigger, constraint or grant
changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20270103_160"
down_revision = "20270102_159"
branch_labels = None
depends_on = None

SQL = r"""
    -- The shared-Deposit plan of a receipt correction: when the corrected receipt's Deposit also
    -- holds another Payment's active receipt, the shared planner's recoveries (each Refund entry
    -- replaced by its share, a share of 0 left out) and its one plan entry for that Deposit (the
    -- planner also lists the other shared Deposits the same Payment funds; they are left out);
    -- otherwise nothing, so a one-Payment Deposit's source stays exactly as it was.
    CREATE FUNCTION app.settlement_deposit_receipt_correction_shared(p_property uuid, p_source jsonb)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        SELECT COALESCE((SELECT jsonb_build_object('recoveries',plan.value->'recoveries',
                'shared_deposits',COALESCE((SELECT jsonb_agg(shared.value ORDER BY shared.position)
                    FROM jsonb_array_elements(plan.value->'shared_deposits')
                        WITH ORDINALITY shared(value,position)
                    WHERE shared.value->>'deposit_id'=receipt.deposit_id::text),'[]'::jsonb))
            FROM app.deposit_receipts receipt
            CROSS JOIN LATERAL (SELECT app.settlement_returned_payment_shared(p_property,
                receipt.payment_id,p_source) AS value) plan
            WHERE receipt.id=(p_source->'receipt'->>'id')::uuid
              AND app.deposit_property_id(receipt.deposit_id)=p_property
              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                  WHERE reversal.deposit_receipt_id=receipt.id)
              AND EXISTS(SELECT 1 FROM app.deposit_receipts other
                  WHERE other.deposit_id=receipt.deposit_id AND other.payment_id<>receipt.payment_id
                    AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                        WHERE reversal.deposit_receipt_id=other.id))),'{}'::jsonb)
    $$;
"""

INTERNAL = ("app.settlement_deposit_receipt_correction_shared(uuid,jsonb)",)

SOURCE = "app.settlement_deposit_receipt_correction_source(uuid,uuid,uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        "        SELECT jsonb_build_object(\n            'settlement',",
        "        -- Sub-slice 10e-2b-4e-2b-2a (owner answer (a) to Q-2026-10-18-127): a shared\n"
        "        -- Deposit's plan and its recoveries' shares over the base source.\n"
        "        SELECT base.value||app.settlement_deposit_receipt_correction_shared(p_property,base.value)\n"
        "        FROM (SELECT jsonb_build_object(\n            'settlement',",
    ),
    (
        "named.id::text)>0)),'[]'::jsonb))\n",
        "named.id::text)>0)),'[]'::jsonb)) AS value) base\n",
    ),
)

ALLOWED_CHECK = "app.assert_settlement_deposit_receipt_correction_allowed(uuid,uuid,jsonb)"
ALLOWED_CHECK_REPLACEMENTS = (
    (
        "        IF (p_source->'deposit'->>'unresolved_refund')::boolean\n"
        "            AND jsonb_array_length(p_source->'recoveries')=0\n",
        "        IF (p_source->'deposit'->>'unresolved_refund')::boolean\n"
        "            AND jsonb_array_length(p_source->'recoveries')=0\n"
        "            -- Sub-slice 10e-2b-4e-2b-2a: a shared Deposit gives back only its shortfall (below).\n"
        "            AND p_source->'shared_deposits' IS NULL\n",
    ),
    (
        "        IF (p_source->'deposit'->>'held_usd_cents')::bigint\n",
        "        IF p_source->'shared_deposits' IS NULL AND (p_source->'deposit'->>'held_usd_cents')::bigint\n",
    ),
    (
        "        THEN RAISE EXCEPTION 'The Deposit would not end empty after this receipt correction'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        "        THEN RAISE EXCEPTION 'The Deposit would not end empty after this receipt correction'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- Sub-slice 10e-2b-4e-2b-2a (owner answers (a) to Q-2026-10-18-127 and\n"
        "        -- Q-2026-10-18-134): a shared Deposit gives back exactly its shortfall, newest use\n"
        "        -- first, so it then holds only the other Payments' money. One plan entry, for this\n"
        "        -- Deposit, checked on the live state (the receipt and the held value); only Refunds and\n"
        "        -- applications give back (an active forfeiture is refused above).\n"
        "        IF p_source->'shared_deposits' IS NOT NULL AND NOT COALESCE((SELECT count(*)=1\n"
        "                AND bool_and(COALESCE(shared->>'deposit_id'=p_source->'receipt'->>'deposit_id'\n"
        "                    AND (shared->>'give_back_usd_cents')::bigint\n"
        "                        =COALESCE((SELECT sum((used->>'undo_usd_cents')::bigint)\n"
        "                            FROM jsonb_array_elements(shared->'uses') used),0)\n"
        "                    AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(shared->'uses') used\n"
        "                        WHERE used->>'kind' IS DISTINCT FROM 'REFUND'\n"
        "                          AND used->>'kind' IS DISTINCT FROM 'APPLICATION')\n"
        "                    AND live.receipt IS NOT NULL\n"
        "                    AND (shared->>'receipt_usd_cents')::bigint=live.receipt\n"
        "                    AND (shared->>'held_usd_cents')::bigint=live.held\n"
        "                    AND (COALESCE((shared->>'plain')::boolean,false)\n"
        "                        OR COALESCE(jsonb_array_length(shared->'uses'),0)=0)\n"
        "                    AND (shared->>'shortfall_usd_cents')::bigint=GREATEST(live.receipt-live.held,0)\n"
        "                    AND (shared->>'give_back_usd_cents')::bigint=GREATEST(live.receipt-live.held,0),\n"
        "                    false))\n"
        "            FROM jsonb_array_elements(p_source->'shared_deposits') shared\n"
        "            CROSS JOIN LATERAL (SELECT (SELECT receipt.amount_usd_cents\n"
        "                        FROM app.deposit_receipts receipt\n"
        "                        WHERE receipt.id=(p_source->'receipt'->>'id')::uuid\n"
        "                          AND receipt.deposit_id=(shared->>'deposit_id')::uuid\n"
        "                          AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                              WHERE reversal.deposit_receipt_id=receipt.id)\n"
        "                          AND EXISTS(SELECT 1 FROM app.deposit_receipts other\n"
        "                              WHERE other.deposit_id=receipt.deposit_id\n"
        "                                AND other.payment_id<>receipt.payment_id\n"
        "                                AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                                    WHERE reversal.deposit_receipt_id=other.id))) AS receipt,\n"
        "                    app.deposit_held_value_at((shared->>'deposit_id')::uuid,'infinity') AS held) live),\n"
        "            false)\n"
        "        THEN RAISE EXCEPTION 'The Deposit would not end holding only the other Payments'' money after this receipt correction'\n"
        "            USING ERRCODE='55000'; END IF;\n",
    ),
)

TARGETS_CHECK = "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)"
TARGETS_CHECK_REPLACEMENTS = (
    (
        "        THEN RAISE EXCEPTION 'A new receipt would exceed the Deposit''s required amount'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        "        THEN RAISE EXCEPTION 'A new receipt would exceed the Deposit''s required amount'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- Sub-slice 10e-2b-4e-2b-2a (known limits, fail closed): a shared Deposit takes right\n"
        "        -- receipts only when it ends empty (otherwise the other Payments' money would join the\n"
        "        -- plan; staff first pay it out with a HELD_VALUE_REFUND correction), and no right\n"
        "        -- receipt goes into a shared Deposit with a pay-back count (the forfeiture list and the\n"
        "        -- plan count read the corrected Deposit's count without payouts, and a shared Deposit\n"
        "        -- keeps some of its payouts).\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'shared_deposits','[]'::jsonb)) shared\n"
        "            WHERE COALESCE((shared->>'held_usd_cents')::bigint+(shared->>'give_back_usd_cents')::bigint\n"
        "                -(shared->>'receipt_usd_cents')::bigint,1)<>0)\n"
        "        THEN RAISE EXCEPTION 'The corrected receipt''s Deposit would still hold other money after this correction; pay it out with a held-value Refund correction first'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        IF p_source->'shared_deposits' IS NOT NULL AND EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->>'deposit_id'=p_source->'receipt'->>'deposit_id'\n"
        "              AND COALESCE((target->>'payback_count')::bigint,1)<>0)\n"
        "        THEN RAISE EXCEPTION 'A new receipt into a Deposit that also holds another Payment''s money and the Customer''s pay-back money is not supported'\n"
        "            USING ERRCODE='55000'; END IF;\n",
    ),
)

RECORDER = (
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
)
RECORDER_REPLACEMENTS = (
    (
        "            PERFORM app.assert_settlement_deposit_receipt_targets_allowed(v_settlement.lease_id,v_source,\n"
        "                v_targets);\n",
        "            PERFORM app.assert_settlement_deposit_receipt_targets_allowed(v_settlement.lease_id,v_source,\n"
        "                v_targets);\n"
        "            -- Sub-slice 10e-2b-4e-2b-2a: a shared Deposit's kept application part is written\n"
        "            -- before the plan's Deposit steps, and the Deposit applications of a correction keep\n"
        "            -- the DL-032 stage order (app.validate_deposit_application would refuse it at the\n"
        "            -- confirm).\n"
        "            IF EXISTS(SELECT 1\n"
        "                FROM jsonb_array_elements(COALESCE(v_source->'shared_deposits','[]'::jsonb)) shared\n"
        "                CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "                CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(v_input->'plan'->'steps')='array'\n"
        "                    THEN v_input->'plan'->'steps' ELSE '[]'::jsonb END) step\n"
        "                WHERE used->>'kind'='APPLICATION' AND (used->>'kept_usd_cents')::bigint>0\n"
        "                  AND array_position(ARRAY['PET_DEPOSIT_PET_DAMAGE','SECURITY_DEPOSIT',\n"
        "                          'PET_DEPOSIT_REMAINDER'],step->>'kind')\n"
        "                      <COALESCE(array_position(ARRAY['PET_RELATED_FIRST','SECURITY_EXPLICIT'],\n"
        "                          used->>'application_stage'),3))\n"
        "            THEN RAISE EXCEPTION 'A Deposit step of this plan comes before, in the DL-032 order, a Deposit application this correction writes again'\n"
        "                USING ERRCODE='55000'; END IF;\n"
        "            -- Review round 1 (independent should-fix 1): a plan Deposit step equal to a kept\n"
        "            -- part (the same Deposit, stage, target and amount) is counted as that kept part by\n"
        "            -- the Deposit application check, which would refuse it at the confirm (23514).\n"
        "            IF EXISTS(SELECT 1\n"
        "                FROM jsonb_array_elements(COALESCE(v_source->'shared_deposits','[]'::jsonb)) shared\n"
        "                CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "                CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(v_input->'plan'->'steps')='array'\n"
        "                    THEN v_input->'plan'->'steps' ELSE '[]'::jsonb END) step\n"
        "                WHERE used->>'kind'='APPLICATION' AND (used->>'kept_usd_cents')::bigint>0\n"
        "                  AND app.final_settlement_plan_id(step->'deposit_id')=shared->>'deposit_id'\n"
        "                  AND step->>'target_kind'=used->>'target_kind'\n"
        "                  AND app.final_settlement_plan_id(step->'target_id')\n"
        "                      =COALESCE(used->>'invoice_line_id',used->>'late_payment_charge_id')\n"
        "                  AND step->>'amount_usd_cents'=used->>'kept_usd_cents'\n"
        "                  AND array_position(ARRAY['PET_DEPOSIT_PET_DAMAGE','SECURITY_DEPOSIT',\n"
        "                          'PET_DEPOSIT_REMAINDER'],step->>'kind')\n"
        "                      =COALESCE(array_position(ARRAY['PET_RELATED_FIRST','SECURITY_EXPLICIT'],\n"
        "                          used->>'application_stage'),3))\n"
        "            THEN RAISE EXCEPTION 'A Deposit step of this plan repeats a Deposit application this correction writes again; split the step'\n"
        "                USING ERRCODE='55000'; END IF;\n"
        "            -- Review round 2 (independent should-fix 1): a Customer Credit step after a kept\n"
        "            -- application part is refused at the confirm by the correction's Credit order check\n"
        "            -- (Credit before the correction's Deposit applications).\n"
        "            IF EXISTS(SELECT 1\n"
        "                FROM jsonb_array_elements(COALESCE(v_source->'shared_deposits','[]'::jsonb)) shared\n"
        "                CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "                WHERE used->>'kind'='APPLICATION' AND (used->>'kept_usd_cents')::bigint>0)\n"
        "              AND EXISTS(SELECT 1 FROM jsonb_array_elements(CASE\n"
        "                    WHEN jsonb_typeof(v_input->'plan'->'steps')='array'\n"
        "                    THEN v_input->'plan'->'steps' ELSE '[]'::jsonb END) step\n"
        "                WHERE step->>'kind'='CUSTOMER_CREDIT')\n"
        "            THEN RAISE EXCEPTION 'A Customer Credit step cannot follow a Deposit application this correction writes again; refund or apply the Customer''s Credit first, or correct the receipt without new receipts'\n"
        "                USING ERRCODE='55000'; END IF;\n",
    ),
)

POST = "app.post_settlement_deposit_receipt_correction(uuid,uuid,uuid,uuid,uuid,text)"
POST_REPLACEMENTS = (
    (
        "        v_at:=app.write_correction_deposit_application_reversals(p_correction,p_approver,v_reason,\n"
        "            ARRAY[(v_source->'receipt'->>'deposit_id')::uuid],v_at);\n",
        "        -- Sub-slice 10e-2b-4e-2b-2a: a shared Deposit gives back only its plan: the listed\n"
        "        -- applications are reversed and their kept parts written again, before the receipt.\n"
        "        v_at:=app.write_correction_deposit_application_reversals(p_correction,p_approver,v_reason,\n"
        "            CASE WHEN v_source->'shared_deposits' IS NULL\n"
        "                THEN ARRAY[(v_source->'receipt'->>'deposit_id')::uuid] ELSE '{}'::uuid[] END,v_at);\n"
        "        v_at:=app.write_settlement_shared_deposit_undo(p_property,p_approver,p_correction,\n"
        "            v_settlement,v_reason,v_source->'shared_deposits',v_at);\n",
    ),
)

OVERLAY = "app.settlement_deposit_receipt_correction_overlay(jsonb,jsonb)"
OVERLAY_REPLACEMENTS = (
    (
        "                    FROM jsonb_array_elements(p_source->'deposit_applications') application\n",
        "                    -- Sub-slice 10e-2b-4e-2b-2a: a shared Deposit's applications come back by\n"
        "                    -- what its plan gives back; the kept parts stay applied.\n"
        "                    FROM jsonb_array_elements(CASE WHEN p_source->'shared_deposits' IS NULL\n"
        "                        THEN p_source->'deposit_applications'\n"
        "                        ELSE COALESCE((SELECT jsonb_agg(used||jsonb_build_object('amount_usd_cents',\n"
        "                                (used->>'undo_usd_cents')::bigint))\n"
        "                            FROM jsonb_array_elements(p_source->'shared_deposits') shared\n"
        "                            CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "                            WHERE used->>'kind'='APPLICATION'),'[]'::jsonb) END) application\n",
    ),
)

KEPT_ALLOWED = "app.settlement_shared_deposit_kept_application_allowed(uuid,app.deposit_applications)"
KEPT_ALLOWED_REPLACEMENTS = (
    (
        "              AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURNED_PAYMENT'\n",
        "              AND draft.kind='SETTLEMENT_CORRECTION'\n"
        "              -- Sub-slice 10e-2b-4e-2b-2a: also a receipt correction's listed kept part.\n"
        "              AND draft.payload->>'variant' IN ('RETURNED_PAYMENT','DEPOSIT_RECEIPT_CORRECTION')\n",
    ),
)

SHORTFALL_AMOUNT = "app.payment_return_shortfall_recovery_amount(app.refund_corrections)"
SHORTFALL_AMOUNT_REPLACEMENTS = (
    (
        "        SELECT LEAST((p_correction).source_balance_effect_usd_cents,\n"
        "            returned.receipt_amount",
        "        SELECT COALESCE((SELECT LEAST((p_correction).source_balance_effect_usd_cents,\n"
        "            returned.receipt_amount",
    ),
    (
        "          AND returned.receipt_amount IS NOT NULL\n",
        "          AND returned.receipt_amount IS NOT NULL),\n"
        "            -- Sub-slice 10e-2b-4e-2b-2a: or the DEPOSIT_RECEIPT_CORRECTION confirmed in this\n"
        "            -- transaction that links the recovery, whose receipt, not reversed, is in the\n"
        "            -- Refund's Deposit beside another Payment's active receipt and whose stored source\n"
        "            -- lists that Deposit: at most the shortfall now.\n"
        "            (SELECT LEAST((p_correction).source_balance_effect_usd_cents,\n"
        "                receipt.amount_usd_cents-app.deposit_held_value_at(refund.source_deposit_id,'infinity'))\n"
        "            FROM app.refunds refund\n"
        "            JOIN app.settlement_correction_effects effect\n"
        "                ON effect.refund_correction_id=(p_correction).id\n"
        "            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id\n"
        "            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id\n"
        "                AND draft.kind='SETTLEMENT_CORRECTION'\n"
        "                AND draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION'\n"
        "            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id\n"
        "                AND decision.decision='CONFIRMED' AND decision.decided_by=correction.actor_id\n"
        "            JOIN app.deposit_receipts receipt ON receipt.id::text=draft.payload->>'deposit_receipt_id'\n"
        "                AND receipt.deposit_id=refund.source_deposit_id\n"
        "            WHERE refund.id=(p_correction).refund_id\n"
        "              AND decision.result->>'transaction_id'=pg_current_xact_id()::text\n"
        "              AND decision.decided_at>=transaction_timestamp()\n"
        "              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                  WHERE reversal.deposit_receipt_id=receipt.id)\n"
        "              AND EXISTS(SELECT 1 FROM app.deposit_receipts other\n"
        "                  WHERE other.deposit_id=receipt.deposit_id AND other.payment_id<>receipt.payment_id\n"
        "                    AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                        WHERE reversal.deposit_receipt_id=other.id))\n"
        "              AND EXISTS(SELECT 1 FROM jsonb_array_elements(CASE\n"
        "                      WHEN jsonb_typeof(draft.payload->'source'->'shared_deposits')='array'\n"
        "                      THEN draft.payload->'source'->'shared_deposits' ELSE '[]'::jsonb END) shared\n"
        "                  WHERE shared->>'deposit_id'=receipt.deposit_id::text)))\n",
    ),
)

SHARED_REVERSAL = (
    "app.payment_return_shared_receipt_reversal_allowed(app.deposit_receipt_reversals)"
)
SHARED_REVERSAL_REPLACEMENTS = (
    (
        "        SELECT COALESCE((SELECT EXISTS(SELECT 1 FROM app.payment_returns payment_return\n",
        "        SELECT COALESCE((SELECT (EXISTS(SELECT 1 FROM app.payment_returns payment_return\n",
    ),
    (
        "                      AND decision.decided_at>=transaction_timestamp())\n"
        "                AND EXISTS(SELECT 1 FROM app.deposit_receipts other\n",
        "                      AND decision.decided_at>=transaction_timestamp())\n"
        "                    -- Sub-slice 10e-2b-4e-2b-2a: or the reversal of its own receipt by the\n"
        "                    -- DEPOSIT_RECEIPT_CORRECTION confirmed in this transaction that links it,\n"
        "                    -- whose stored source lists this Deposit.\n"
        "                    OR EXISTS(SELECT 1 FROM app.settlement_correction_effects effect\n"
        "                        JOIN app.settlement_corrections correction\n"
        "                            ON correction.id=effect.settlement_correction_id\n"
        "                        JOIN app.financial_drafts draft ON draft.id=correction.correlation_id\n"
        "                            AND draft.kind='SETTLEMENT_CORRECTION'\n"
        "                            AND draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION'\n"
        "                            AND draft.payload->>'deposit_receipt_id'=receipt.id::text\n"
        "                        JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id\n"
        "                            AND decision.decision='CONFIRMED'\n"
        "                            AND decision.decided_by=correction.actor_id\n"
        "                        WHERE effect.deposit_receipt_reversal_id=(p_reversal).id\n"
        "                          AND decision.result->>'transaction_id'=pg_current_xact_id()::text\n"
        "                          AND decision.decided_at>=transaction_timestamp()\n"
        "                          -- Review round 1 (security S3): the table keeps the active-forfeiture\n"
        "                          -- refusal for this correction (owner answer (a) to Q-2026-10-11-83).\n"
        "                          AND NOT EXISTS(SELECT 1 FROM app.deposit_dispositions disposition\n"
        "                              WHERE disposition.deposit_id=receipt.deposit_id\n"
        "                                AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals undone\n"
        "                                    WHERE undone.deposit_disposition_id=disposition.id))\n"
        "                          AND EXISTS(SELECT 1 FROM jsonb_array_elements(CASE\n"
        "                                  WHEN jsonb_typeof(draft.payload->'source'->'shared_deposits')='array'\n"
        "                                  THEN draft.payload->'source'->'shared_deposits'\n"
        "                                  ELSE '[]'::jsonb END) shared\n"
        "                              WHERE shared->>'deposit_id'=receipt.deposit_id::text)))\n"
        "                AND EXISTS(SELECT 1 FROM app.deposit_receipts other\n",
    ),
)

PATCHES = (
    (SOURCE, SOURCE_REPLACEMENTS),
    (ALLOWED_CHECK, ALLOWED_CHECK_REPLACEMENTS),
    (TARGETS_CHECK, TARGETS_CHECK_REPLACEMENTS),
    (RECORDER, RECORDER_REPLACEMENTS),
    (POST, POST_REPLACEMENTS),
    (OVERLAY, OVERLAY_REPLACEMENTS),
    (KEPT_ALLOWED, KEPT_ALLOWED_REPLACEMENTS),
    (SHORTFALL_AMOUNT, SHORTFALL_AMOUNT_REPLACEMENTS),
    (SHARED_REVERSAL, SHARED_REVERSAL_REPLACEMENTS),
)


def upgrade() -> None:
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Receipt correction shared Deposit migration is forward-only")


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
            raise RuntimeError(f"Receipt correction shared Deposit contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)
