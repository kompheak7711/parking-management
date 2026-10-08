# ruff: noqa: E501
"""Post-settlement correction: a returned Deposit Refund (V1-056 sub-slice 10c-2b-2a).

BR-SETTLE-008, BR-SETTLE-013, BR-REFUND-014, BR-REFUND-015, DL-032, BR-AUTH-010; owner answer 3 to
Q-2026-10-07-42, answers 3 and 5 to Q-2026-10-08-55 and the answer to Q-2026-10-08-56:

- The REFUND_RETURN correction of sub-slice 10c-2b-1 also returns a Deposit Refund of the
  Settlement: a Final Settlement Deposit Refund (sub-slice 8d) or a correction's Deposit Refund
  (sub-slice 10c-2a-2). The returned amount goes back to the Deposit (DB-DER-004), never to
  Customer Credit. A return-only correction leaves it held by the Deposit (Q-42 answer 3); with a
  new Refund the same correction runs the shared DL-032 step, so the Deposit value first pays this
  Lease's open debt in the DL-032 order, with every Settlement rule, and only the rest is refunded
  (Q-55 answer 3) by the plan's Deposit Refund step, which carries the recipient and agreement
  (BR-REFUND-015). Only a Deposit on the DL-032 path may pay debt or be refunded again.
- The Refund correction check lets that verified return through (the one-call paths stay
  refused) and now reads a Settlement Deposit Refund's own Deposit for its locks and chronology.
- Approved tightening (owner answer 5 to Q-2026-10-08-55, answer to Q-2026-10-08-56): after the
  Lease's Final Settlement closes, the receipt reversal draft of a Lease Deposit is refused at
  record, and a receipt reversal row is refused unless it is linked to a correction of that
  Settlement confirmed in the same transaction (P5S01, a conflict). Until the correction kinds
  RETURNED_PAYMENT (10e) and DEPOSIT_RECEIPT_CORRECTION (10e-2) exist, a wrong Deposit receipt has
  no fix after closure (docs/010 known gap).
- Review round 3 notes of 10c-2b-1: the relaxed return check also binds the row's reason to the
  draft's.
- Owner answers to Q-2026-10-08-59: (1) approved tightening: after closure a Lease Deposit
  forfeiture draft is refused at record and a forfeiture row at insert (P5S01) unless a correction
  of that Settlement links it (no kind does yet); (2) a return-only Credit correction may leave a
  Deposit holding returned money that no open debt can take (the plan check's hold rule; the
  returned Credit still pays its own Customer's open debt first); (4) approved tightening: a
  receipt reversal draft is recorded only at READ COMMITTED.

The 10c-2b-1 functions are replaced in place (CREATE OR REPLACE keeps owner and privileges); seven
functions are patched in place: the Refund correction check, the receipt reversal recorder and
trigger, the Lease forfeiture recorder, the disposition check, the plan check and the step.
"""

from alembic import op
from sqlalchemy import text

revision = "20261112_108"
down_revision = "20261111_107"
branch_labels = None
depends_on = None

GENERAL_CORRECTION = "app.validate_general_refund_correction()"
GENERAL_CORRECTION_REPLACEMENTS = (
    (
        "            IF v_refund.source_deposit_id IS NOT NULL AND v_refund.pet_refund_review_id IS NULL THEN\n"
        "                RAISE EXCEPTION 'A Final Settlement Refund is corrected only through a post-settlement correction'\n"
        "                    USING ERRCODE='23514'; END IF;\n",
        "            -- Sub-slice 10c-2b-2a: the verified return of its own REFUND_RETURN correction passes.\n"
        "            v_linked:=app.settlement_refund_return_allowed(NEW);\n"
        "            IF v_refund.source_deposit_id IS NOT NULL AND v_refund.pet_refund_review_id IS NULL\n"
        "                AND NOT v_linked THEN\n"
        "                RAISE EXCEPTION 'A Final Settlement Refund is corrected only through a post-settlement correction'\n"
        "                    USING ERRCODE='23514'; END IF;\n",
    ),
    (
        "            v_linked:=app.settlement_refund_return_allowed(NEW);\n"
        "            IF EXISTS(SELECT 1 FROM app.settlement_correction_refund_details detail\n",
        "            IF EXISTS(SELECT 1 FROM app.settlement_correction_refund_details detail\n",
    ),
    (
        "            IF v_refund.pet_refund_review_id IS NOT NULL THEN\n"
        "                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);\n",
        "            -- Every Deposit Refund (sub-slice 10c-2b-2a: a Settlement Deposit Refund too) locks\n"
        "            -- its Deposit; the others lock their Payment and Credit.\n"
        "            IF v_refund.source_deposit_id IS NOT NULL THEN\n"
        "                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);\n",
    ),
    (
        "                CASE WHEN v_refund.pet_refund_review_id IS NOT NULL THEN app.deposit_balance_latest_at(v_refund.source_deposit_id)\n",
        "                CASE WHEN v_refund.source_deposit_id IS NOT NULL THEN app.deposit_balance_latest_at(v_refund.source_deposit_id)\n",
    ),
)

RECEIPT_TRIGGER = "app.validate_deposit_receipt_reversal()"
RECEIPT_TRIGGER_REPLACEMENTS = (
    (
        "        DECLARE v_deposit_id uuid;\n",
        "        DECLARE v_deposit_id uuid; v_settlement uuid;\n",
    ),
    (
        "            PERFORM 1 FROM app.deposits WHERE id=v_deposit_id FOR UPDATE;\n",
        "            PERFORM 1 FROM app.deposits WHERE id=v_deposit_id FOR UPDATE;\n"
        "            -- Sub-slice 10c-2b-2a (owner answer 5 to Q-2026-10-08-55, approved tightening): once\n"
        "            -- the Lease's Final Settlement is closed, a receipt reversal passes only when it is\n"
        "            -- linked to a correction of that Settlement confirmed in this transaction.\n"
        "            SELECT settlement.id INTO v_settlement FROM app.final_settlements settlement\n"
        "            JOIN app.deposits deposit ON deposit.lease_id=settlement.lease_id\n"
        "            WHERE deposit.id=v_deposit_id AND settlement.closed_at IS NOT NULL;\n"
        "            IF v_settlement IS NOT NULL\n"
        "                AND app.settlement_correction_linked(v_settlement,'deposit_receipt_reversals',NEW.id) IS NOT TRUE\n"
        "            THEN RAISE EXCEPTION 'A closed Final Settlement''s Deposit receipt changes only through a post-settlement correction'\n"
        "                USING ERRCODE='P5S01'; END IF;\n",
    ),
)

RECEIPT_RECORDER = "app.record_deposit_receipt_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
RECEIPT_RECORDER_REPLACEMENTS = (
    (
        "            PERFORM 1 FROM app.deposits WHERE id=(v_source->>'deposit_id')::uuid FOR UPDATE;\n",
        "            PERFORM 1 FROM app.deposits WHERE id=(v_source->>'deposit_id')::uuid FOR UPDATE;\n"
        "            -- Sub-slice 10c-2b-2a (owner answer 4 to Q-2026-10-08-59, approved tightening, as\n"
        "            -- the answer to Q-2026-10-08-51): recorded only at READ COMMITTED, so the closure\n"
        "            -- read below sees every committed closure.\n"
        "            IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN\n"
        "                RAISE EXCEPTION 'A Deposit receipt reversal draft is recorded at READ COMMITTED'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            -- Sub-slice 10c-2b-2a (owner answer 5 to Q-2026-10-08-55, approved tightening): no\n"
        "            -- receipt reversal draft for a Lease Deposit once the Lease's Final Settlement is\n"
        "            -- closed; a wrong receipt is then fixed only through a post-settlement correction.\n"
        "            IF EXISTS(SELECT 1 FROM app.final_settlements settlement\n"
        "                JOIN app.deposits deposit ON deposit.lease_id=settlement.lease_id\n"
        "                WHERE deposit.id=(v_source->>'deposit_id')::uuid AND settlement.closed_at IS NOT NULL)\n"
        "            THEN RAISE EXCEPTION 'A closed Final Settlement''s Deposit receipt changes only through a post-settlement correction'\n"
        "                USING ERRCODE='P5S01'; END IF;\n",
    ),
)

FORFEITURE_RECORDER = (
    "app.record_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
)
FORFEITURE_RECORDER_REPLACEMENTS = (
    (
        "            v_source:=app.lease_deposit_forfeiture_source(p_property,p_deposit);\n",
        "            -- Sub-slice 10c-2b-2a (owner answer 1 to Q-2026-10-08-59, approved tightening): no\n"
        "            -- forfeiture draft for a Lease Deposit of this Property once the Lease's Final\n"
        "            -- Settlement is closed, before any other check of the Deposit.\n"
        "            IF EXISTS(SELECT 1 FROM app.final_settlements settlement\n"
        "                JOIN app.deposits deposit ON deposit.lease_id=settlement.lease_id\n"
        "                WHERE deposit.id=p_deposit AND settlement.property_id=p_property\n"
        "                  AND settlement.closed_at IS NOT NULL)\n"
        "            THEN RAISE EXCEPTION 'A closed Final Settlement''s Deposit is forfeited only through a post-settlement correction'\n"
        "                USING ERRCODE='P5S01'; END IF;\n"
        "            v_source:=app.lease_deposit_forfeiture_source(p_property,p_deposit);\n",
    ),
)

DISPOSITION_TRIGGER = "app.validate_lease_deposit_disposition()"
DISPOSITION_TRIGGER_REPLACEMENTS = (
    (
        "        DECLARE v_termination_date date; v_held bigint;\n",
        "        DECLARE v_termination_date date; v_held bigint; v_settlement uuid;\n",
    ),
    (
        "                RAISE EXCEPTION 'Lease Deposit disposition source is invalid'\n"
        "                    USING ERRCODE = '23514';\n"
        "            END IF;\n",
        "                RAISE EXCEPTION 'Lease Deposit disposition source is invalid'\n"
        "                    USING ERRCODE = '23514';\n"
        "            END IF;\n"
        "            -- Sub-slice 10c-2b-2a (owner answer 1 to Q-2026-10-08-59, approved tightening): once\n"
        "            -- the Lease's Final Settlement is closed, a forfeiture passes only when a correction\n"
        "            -- of that Settlement confirmed in this transaction links it (no kind does yet).\n"
        "            SELECT settlement.id INTO v_settlement FROM app.final_settlements settlement\n"
        "            WHERE settlement.lease_id=NEW.governing_lease_id AND settlement.closed_at IS NOT NULL;\n"
        "            IF v_settlement IS NOT NULL\n"
        "                AND app.settlement_correction_linked(v_settlement,'deposit_dispositions',NEW.id) IS NOT TRUE\n"
        "            THEN RAISE EXCEPTION 'A closed Final Settlement''s Deposit is forfeited only through a post-settlement correction'\n"
        "                USING ERRCODE='P5S01'; END IF;\n",
    ),
)

PLAN_RESULT = "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)"
PLAN_RESULT_REPLACEMENTS = (
    (
        "                    WHERE key<>'pet_damage')\n"
        "                IS DISTINCT FROM ARRAY['credits','deposits','obligations']\n",
        "                    WHERE key NOT IN ('pet_damage','hold_deposits'))\n"
        "                IS DISTINCT FROM ARRAY['credits','deposits','obligations']\n"
        "            -- Sub-slice 10c-2b-2a (owner answer 2 to Q-2026-10-08-59): a return-only Credit\n"
        "            -- correction's flag, true or false.\n"
        "            OR jsonb_typeof(COALESCE(p_overlay->'hold_deposits','false'::jsonb)) IS DISTINCT FROM 'boolean'\n",
    ),
    (
        "        IF EXISTS(SELECT 1 FROM jsonb_each_text(v_left) item WHERE item.value::bigint<>0) THEN\n"
        "            RAISE EXCEPTION 'Every remaining Deposit balance must be applied or refunded' USING ERRCODE='55000';\n"
        "        END IF;\n",
        "        -- Sub-slice 10c-2b-2a (owner answer 2 to Q-2026-10-08-59): a return-only Credit\n"
        "        -- correction (overlay hold_deposits) pays nothing out, so a Deposit may keep returned money\n"
        "        -- that no open debt can take; it stays held until a later correction refunds it. Money\n"
        "        -- that open debt can take is still applied: no Security Deposit balance while debt stays\n"
        "        -- open; no Pet Deposit balance while pet damage stays open after the Pet Deposit's own\n"
        "        -- step (review round 2: not paid by the Security Deposit instead), or while other debt\n"
        "        -- stays open that the remaining Pet Deposit may pay by a staff decision.\n"
        "        IF COALESCE((p_overlay->>'hold_deposits')::boolean,false) THEN\n"
        "            IF EXISTS(SELECT 1 FROM jsonb_each_text(v_left) item WHERE item.value::bigint>0\n"
        "                AND ((v_type->>item.key='SECURITY'\n"
        "                        AND (SELECT COALESCE(sum(owed.value::bigint),0) FROM jsonb_each_text(v_open) owed)>0)\n"
        "                    OR (v_type->>item.key='PET'\n"
        "                        AND (v_pet_after_three>0\n"
        "                            OR ((SELECT COALESCE(sum(owed.value::bigint),0) FROM jsonb_each_text(v_open) owed)>0\n"
        "                                AND v_chosen_by='CUSTOMER_OR_STAFF_WITH_REASON')))))\n"
        "            THEN RAISE EXCEPTION 'A Deposit keeps returned money only when no open debt can take it'\n"
        "                USING ERRCODE='55000'; END IF;\n"
        "        ELSIF EXISTS(SELECT 1 FROM jsonb_each_text(v_left) item WHERE item.value::bigint<>0) THEN\n"
        "            RAISE EXCEPTION 'Every remaining Deposit balance must be applied or refunded' USING ERRCODE='55000';\n"
        "        END IF;\n",
    ),
)

STEP = "app.post_settlement_correction_plan(uuid,uuid,uuid)"
STEP_REPLACEMENTS = (
    (
        "            jsonb_build_object('obligations','{}'::jsonb,'credits',v_overlay,'deposits','{}'::jsonb));\n",
        "            jsonb_build_object('obligations','{}'::jsonb,'credits',v_overlay,'deposits','{}'::jsonb)\n"
        "            -- Sub-slice 10c-2b-2a (owner answer 2 to Q-2026-10-08-59): a return-only Credit\n"
        "            -- correction keeps the flag it was recorded with.\n"
        "            ||CASE WHEN v_draft.payload->>'variant'='REFUND_RETURN'\n"
        "                AND v_draft.payload->'plan_overlay'->'hold_deposits'='true'::jsonb\n"
        "                THEN jsonb_build_object('hold_deposits',true) ELSE '{}'::jsonb END);\n",
    ),
)

SQL = r"""
    -- The closed Final Settlement a Refund that a REFUND_RETURN correction may return belongs to;
    -- NULL for every other Refund. Sub-slice 10c-2b-1: a correction's Credit Refund; sub-slice
    -- 10c-2b-2a: a correction's Deposit Refund and a Final Settlement Deposit Refund (8d).
    CREATE OR REPLACE FUNCTION app.settlement_refund_return_settlement(p_refund uuid)
    RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE(
            (SELECT correction.final_settlement_id FROM app.settlement_correction_refund_details detail
                JOIN app.settlement_corrections correction ON correction.id=detail.settlement_correction_id
                JOIN app.refunds refund ON refund.id=detail.refund_id
                WHERE detail.refund_id=p_refund
                  AND ((detail.deposit_id IS NULL AND refund.source_customer_credit_id IS NOT NULL)
                      OR (detail.deposit_id IS NOT NULL AND refund.source_deposit_id=detail.deposit_id))),
            (SELECT detail.final_settlement_id FROM app.final_settlement_refund_details detail
                JOIN app.final_settlements settlement ON settlement.id=detail.final_settlement_id
                JOIN app.refunds refund ON refund.id=detail.refund_id
                WHERE detail.refund_id=p_refund AND settlement.closed_at IS NOT NULL
                  AND refund.source_deposit_id=detail.deposit_id AND refund.pet_refund_review_id IS NULL))
    $$;

    -- Whether a Refund correction row is the verified return of a REFUND_RETURN correction: linked
    -- to that correction, which belongs to the Refund's own Final Settlement and was confirmed in
    -- this transaction; written by its approver under financial.approve; its draft names this
    -- Refund, the amount, the return date, the references and the reason; the correction writes no
    -- other return. Never NULL. Sub-slice 10c-2b-2a: the reason too (10c-2b-1 review round 3).
    CREATE OR REPLACE FUNCTION app.settlement_refund_return_allowed(p_correction app.refund_corrections)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT (p_correction).correction_kind='VALUE_CORRECTION'
                AND (p_correction).authorization_reference='financial.approve'
                AND (p_correction).actor_id=correction.actor_id
                AND (p_correction).source_balance_effect_usd_cents
                    =(draft.payload->'refund_return'->>'returned_amount_usd_cents')::bigint
                AND (p_correction).verified_returned_at
                    =(draft.payload->'refund_return'->>'returned_at')::timestamptz
                AND (p_correction).return_method_reference
                    =draft.payload->'refund_return'->>'return_method_reference'
                AND (p_correction).evidence_reference=draft.payload->'refund_return'->>'evidence_reference'
                AND (p_correction).reason=draft.reason
                AND NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects other
                    WHERE other.settlement_correction_id=correction.id
                      AND other.refund_correction_id<>(p_correction).id)
                AND app.settlement_correction_linked(correction.final_settlement_id,'refund_corrections',
                    (p_correction).id)
                AND app.settlement_refund_return_settlement((p_correction).refund_id)
                    =correction.final_settlement_id
            FROM app.settlement_correction_effects effect
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            JOIN app.financial_drafts draft
                ON draft.id=correction.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE effect.refund_correction_id=(p_correction).id
              AND draft.payload->>'variant'='REFUND_RETURN'
              AND draft.payload->'refund_return'->>'refund_id'=(p_correction).refund_id::text),false)
    $$;

    -- What a returned-Refund correction depends on: the Settlement, the Refund with its net value
    -- and its corrections, and the Credit or (sub-slice 10c-2b-2a) the Deposit it came from.
    CREATE OR REPLACE FUNCTION app.settlement_refund_return_source_state(p_settlement uuid,p_refund uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'closed_at',settlement.closed_at,
                    'lease_id',settlement.lease_id)
                FROM app.final_settlements settlement WHERE settlement.id=p_settlement),
            'refund',(SELECT jsonb_build_object('id',refund.id,
                    'recipient_customer_id',refund.recipient_customer_id,
                    'source_customer_credit_id',refund.source_customer_credit_id,
                    'source_deposit_id',refund.source_deposit_id,'processed_at',refund.processed_at,
                    'net_usd_cents',app.refund_net_value_at(refund.id,'infinity'),
                    'corrections',(SELECT COALESCE(jsonb_agg(correction.id
                            ORDER BY correction.occurred_at,correction.id),'[]'::jsonb)
                        FROM app.refund_corrections correction WHERE correction.refund_id=refund.id))
                FROM app.refunds refund WHERE refund.id=p_refund),
            'credit',(SELECT jsonb_build_object('id',credit.id,'customer_id',credit.customer_id,
                    'available_usd_cents',app.credit_available_value(credit.id))
                FROM app.refunds refund JOIN app.customer_credits credit
                    ON credit.id=refund.source_customer_credit_id
                WHERE refund.id=p_refund),
            'deposit',(SELECT jsonb_build_object('id',deposit.id,
                    'held_usd_cents',app.deposit_held_value_at(deposit.id,'infinity'),
                    'latest_at',app.deposit_balance_latest_at(deposit.id))
                FROM app.refunds refund JOIN app.deposits deposit ON deposit.id=refund.source_deposit_id
                WHERE refund.id=p_refund))
    $$;

    -- Checks a stored-form returned-Refund correction against the current state and returns what
    -- the draft records: the Lease, the Refund's recipient, its Credit or Deposit, the correction
    -- and the source revision. An unknown Settlement or Refund P0002; a state the correction does
    -- not allow 55000. Sub-slice 10c-2b-2a: a Deposit Refund of this Settlement too; a Deposit pays
    -- debt or is refunded again only on the DL-032 path.
    CREATE OR REPLACE FUNCTION app.settlement_refund_return_plan(p_property uuid,p_settlement uuid,p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_refund app.refunds%ROWTYPE;
        v_at timestamptz;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT * INTO v_refund FROM app.refunds
        WHERE id=(p_input->>'refund_id')::uuid AND app.refund_property_id(id)=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund was not found' USING ERRCODE='P0002'; END IF;
        -- A Refund this Settlement or one of its corrections paid.
        IF app.settlement_refund_return_settlement(v_refund.id) IS DISTINCT FROM v_settlement.id THEN
            RAISE EXCEPTION 'The returned Refund is not a Refund this correction may return'
                USING ERRCODE='55000'; END IF;
        IF (p_input->>'returned_amount_usd_cents')::bigint>app.refund_net_value_at(v_refund.id,'infinity') THEN
            RAISE EXCEPTION 'The returned amount exceeds the Refund''s net value' USING ERRCODE='55000'; END IF;
        v_at:=(p_input->>'returned_at')::timestamptz;
        IF v_at<v_refund.processed_at OR v_at>clock_timestamp() THEN
            RAISE EXCEPTION 'The return is dated before the Refund or in the future' USING ERRCODE='55000';
        END IF;
        IF jsonb_typeof(p_input->'new_refund')='object' THEN
            -- BR-REFUND-014: an active Refund method for the new Refund (as the Refund correction).
            PERFORM 1 FROM app.refund_methods
            WHERE id=(p_input->'new_refund'->>'refund_method_id')::uuid AND active;
            IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
            -- DL-032: only a Deposit on the DL-032 path pays debt or is refunded after its return.
            IF v_refund.source_deposit_id IS NOT NULL
                AND app.lease_deposit_settlement_path(p_property,v_refund.source_deposit_id)->>'path'
                    IS DISTINCT FROM 'DL_032'
            THEN RAISE EXCEPTION 'A returned Deposit pays debt or is refunded again only on the DL-032 path'
                USING ERRCODE='55000'; END IF;
        END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,
            'customer_id',v_refund.recipient_customer_id,
            'customer_credit_id',v_refund.source_customer_credit_id,
            'deposit_id',v_refund.source_deposit_id,'refund_return',p_input,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_refund_return_source_state(p_settlement,v_refund.id)::text,'UTF8')),'hex'));
    END $$;

    -- The overlay of a returned Refund for the shared DL-032 step (sub-slice 10c-2a-2): a returned
    -- Credit Refund gives the amount back to its Credit, which pays only its own Customer's debt;
    -- a returned Deposit Refund (sub-slice 10c-2b-2a) gives it back to its Deposit.
    CREATE OR REPLACE FUNCTION app.settlement_refund_return_overlay(p_plan jsonb)
    RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object('obligations','{}'::jsonb,
            'deposits',CASE WHEN jsonb_typeof(p_plan->'deposit_id')='string'
                THEN jsonb_build_object(p_plan->>'deposit_id',
                    p_plan->'refund_return'->'returned_amount_usd_cents')
                ELSE '{}'::jsonb END,
            'credits',CASE WHEN jsonb_typeof(p_plan->'customer_credit_id')='string'
                THEN jsonb_build_object(p_plan->>'customer_credit_id',jsonb_build_object(
                    'customer_id',p_plan->'customer_id',
                    'add_usd_cents',p_plan->'refund_return'->'returned_amount_usd_cents',
                    'released_payment_allocation_id',NULL))
                ELSE '{}'::jsonb END)
    $$;

    -- Staff record a returned-Refund correction draft (final_settlements.prepare); it has no
    -- financial effect until a financial.approve holder confirms it. Sub-slice 10c-2b-2a: a
    -- returned Deposit Refund without a new Refund stays held by the Deposit (owner answer 3 to
    -- Q-2026-10-07-42), so that form has no DL-032 step.
    CREATE OR REPLACE FUNCTION app.record_settlement_refund_return_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_return jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
        v_steps jsonb; v_overlay jsonb; v_result jsonb; v_choice text; v_step boolean;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters, as every correction's.
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
            OR p_return IS NULL OR jsonb_typeof(p_return) IS DISTINCT FROM 'object'
        THEN RAISE EXCEPTION 'Returned Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_refund_return_input(p_return-'plan');
        v_steps:=COALESCE(p_return->'plan',jsonb_build_object('steps','[]'::jsonb,'pet_remainder','null'::jsonb));
        IF jsonb_typeof(v_steps) IS DISTINCT FROM 'object' OR jsonb_typeof(v_steps->'steps') IS DISTINCT FROM 'array'
        THEN RAISE EXCEPTION 'Returned Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='REFUND_RETURN' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'refund_return'=v_input AND v_existing.payload->'plan'=v_steps
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_refund_return_plan(p_property,p_settlement,v_input);
        -- One Refund method and reference note per correction (as the Refund correction): every
        -- Deposit Refund step uses the new Refund's; without a new Refund there is none.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_steps->'steps') step
            WHERE step->>'kind'='DEPOSIT_REFUNDS'
              AND (jsonb_typeof(v_input->'new_refund') IS DISTINCT FROM 'object'
                  OR app.final_settlement_plan_id(step->'refund_method_id')
                      IS DISTINCT FROM v_input->'new_refund'->>'refund_method_id'
                  OR step->'reference_note' IS DISTINCT FROM v_input->'new_refund'->'reference_note'))
        THEN RAISE EXCEPTION 'A post-settlement correction has one Refund method, reference note, recipient and agreement'
            USING ERRCODE='22023'; END IF;
        -- Sub-slice 10c-2b-2a: a returned Deposit Refund without a new Refund stays held by the
        -- Deposit until a later correction (owner answer 3 to Q-2026-10-07-42): no step.
        v_step:=jsonb_typeof(v_plan->'deposit_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(v_input->'new_refund')='object';
        IF NOT v_step
            AND v_steps IS DISTINCT FROM jsonb_build_object('steps','[]'::jsonb,'pet_remainder','null'::jsonb)
        THEN RAISE EXCEPTION 'A return-only Deposit Refund correction has no DL-032 step'
            USING ERRCODE='22023'; END IF;
        -- Owner answer 3 to Q-2026-10-07-44: the remaining Pet Deposit is used by the Customer's
        -- choice given for this correction; neither the Final Settlement's nor an earlier
        -- confirmed correction's choice is reused (the recorded text is compared).
        IF v_steps->'pet_remainder'->>'basis'='CUSTOMER_CHOICE' THEN
            SELECT draft.payload->'pet_remainder'->>'customer_choice' INTO v_choice
            FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
            WHERE draft.kind='FINAL_SETTLEMENT' AND draft.payload->>'final_settlement_id'=p_settlement::text;
            IF v_choice IS NOT NULL AND v_choice=v_steps->'pet_remainder'->>'customer_choice' THEN
                RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; the Final Settlement''s choice is not reused'
                    USING ERRCODE='55000'; END IF;
            IF EXISTS(SELECT 1 FROM app.financial_drafts draft
                JOIN app.financial_draft_decisions decision
                    ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
                WHERE draft.kind='SETTLEMENT_CORRECTION'
                  AND draft.payload->>'final_settlement_id'=p_settlement::text
                  AND draft.payload->'plan'->'pet_remainder'->>'customer_choice'
                      =v_steps->'pet_remainder'->>'customer_choice')
            THEN RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; an earlier correction''s choice is not reused'
                USING ERRCODE='55000'; END IF;
        END IF;
        -- The shared step's check on the state after the return (sub-slice 10c-2a-2): a returned
        -- Credit first pays its own Customer's open debt on this Lease (owner answer 1 to
        -- Q-2026-10-08-55); returned Deposit value first pays the Lease's open debt in the DL-032
        -- order (answer 3).
        IF v_step THEN
            v_overlay:=app.settlement_refund_return_overlay(v_plan);
            -- Owner answer 2 to Q-2026-10-08-59: a return-only Credit correction may leave a
            -- Deposit holding returned money that no open debt can take (the step's hold rule).
            IF jsonb_typeof(v_input->'new_refund') IS DISTINCT FROM 'object' THEN
                v_overlay:=v_overlay||jsonb_build_object('hold_deposits',true);
            END IF;
            v_result:=app.settlement_correction_plan_result(p_property,p_actor,p_settlement,v_steps,v_overlay)
                -'source_revision';
        ELSE
            v_overlay:=jsonb_build_object('obligations','{}'::jsonb,'credits','{}'::jsonb,'deposits','{}'::jsonb);
        END IF;
        v_payload:=jsonb_build_object('variant','REFUND_RETURN','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id',
            'customer_credit_id',v_plan->'customer_credit_id','deposit_id',v_plan->'deposit_id',
            'refund_return',v_input,'runs_step',v_step,
            'plan',v_steps,'plan_overlay',v_overlay,'plan_result',COALESCE(v_result,'null'::jsonb));
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- A financial.approve holder confirms a returned-Refund correction: in one transaction the
    -- decision and the header (sub-slice 10a), then, each linked before it is written, the verified
    -- return (the value goes back to the Credit or the Deposit), the shared DL-032 step when the
    -- draft runs it, and for a Credit, when the draft asks for it, one Credit Refund of what is left
    -- of the returned amount (a Deposit's new Refund is the plan's Deposit Refund step). Refusals:
    -- an unknown Property, draft or Settlement P0002/P4501; an inactive or missing approver P4506
    -- or 42501; business state 55000; a draft whose sources changed P5S02 (stale; it stays
    -- pending). Nothing is written unless everything succeeds.
    CREATE OR REPLACE FUNCTION app.confirm_settlement_refund_return(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_refund app.refunds%ROWTYPE; v_timezone text; v_now timestamptz; v_business_date date;
        v_input jsonb; v_plan jsonb; v_correction uuid; v_unit uuid; v_evidence jsonb; v_result jsonb;
        v_step jsonb; v_method uuid; v_amount bigint; v_net bigint; v_return uuid; v_credit uuid;
        v_pay bigint; v_refund_id uuid; v_at timestamptz; v_refunds jsonb:='[]'::jsonb;
    BEGIN
        v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
        -- BR-AUTH-010: a person confirms; an inactive approver is refused above (P4506).
        IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
            WHERE identity.actor_id=p_actor AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'A post-settlement correction is confirmed only by a human approver'
            USING ERRCODE='42501'; END IF;
        IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
            RAISE EXCEPTION 'Only financial.approve may confirm a post-settlement correction'
                USING ERRCODE='42501'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' THEN
            RAISE EXCEPTION 'Post-settlement correction input is invalid' USING ERRCODE='22023'; END IF;
        -- The serialization of every decision on this draft, then the replay of an exact repeat.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND draft.kind='SETTLEMENT_CORRECTION'
              AND draft.payload->>'variant'='REFUND_RETURN' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_refund_return_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'REFUND_RETURN'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks
        -- waited for (as the other correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The stored correction passes the recorder's shape check again.
        v_input:=app.settlement_refund_return_input(v_draft.payload->'refund_return');
        IF v_input IS DISTINCT FROM v_draft.payload->'refund_return'
            OR jsonb_typeof(v_draft.payload->'runs_step') IS DISTINCT FROM 'boolean' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_amount:=(v_input->>'returned_amount_usd_cents')::bigint;
        -- Lock order, the 8e-3 order (as sub-slice 10c-2a-3): the draft lock (above); the
        -- Settlement's draft lock; the Lease row FOR UPDATE; then the shared step's locks
        -- (app.lock_settlement_correction_plan), which for this variant take a returned Credit
        -- Refund's Payment and Credit in their id-ordered passes, then the Lease's Charges and
        -- Invoices, the Settlement row and each Deposit's draft lock and row (a returned Deposit
        -- Refund's Deposit among them); then the Refund methods FOR SHARE;
        -- app.begin_settlement_correction locks the draft row and the Settlement row; the Refund
        -- correction check locks the returned Refund row FOR UPDATE last, at the return's insert.
        -- No other writer locks that row now: the one-call paths refuse such a Refund before any
        -- lock, and the confirms of one Settlement are serialized by its draft lock. A detected
        -- deadlock (40P01) is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same correction; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_refund_return_source_state(
                v_settlement.id,(v_input->>'refund_id')::uuid)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_refund_return_plan(p_property,v_settlement.id,v_input);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
            OR v_plan->'customer_credit_id' IS DISTINCT FROM v_draft.payload->'customer_credit_id'
            OR v_plan->'deposit_id' IS DISTINCT FROM v_draft.payload->'deposit_id'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        SELECT * INTO STRICT v_refund FROM app.refunds WHERE id=(v_input->>'refund_id')::uuid;
        v_credit:=v_refund.source_customer_credit_id;
        -- BR-REFUND-014: each Refund method stays active until its Refunds are written.
        FOR v_method IN SELECT DISTINCT method.id FROM (
                SELECT app.final_settlement_plan_id(step->'refund_method_id')::uuid AS id
                FROM jsonb_array_elements(v_draft.payload->'plan'->'steps') step
                WHERE step->>'kind'='DEPOSIT_REFUNDS'
                UNION SELECT app.final_settlement_plan_id(v_input->'new_refund'->'refund_method_id')::uuid) method
            WHERE method.id IS NOT NULL ORDER BY 1
        LOOP
            PERFORM 1 FROM app.refund_methods WHERE id=v_method AND active FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        END LOOP;
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_settlement.lease_id;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','REFUND_RETURN');
        -- The verified return (DB-REFUND-002 as the one-call return writes it, but financial.approve
        -- and linked first): later than the Refund, its corrections and the latest event of the
        -- Credit or the Deposit.
        v_now:=GREATEST(clock_timestamp(),v_refund.processed_at+interval '1 microsecond',
            COALESCE((SELECT max(correction.occurred_at) FROM app.refund_corrections correction
                WHERE correction.refund_id=v_refund.id),'-infinity')+interval '1 microsecond',
            COALESCE(app.credit_latest_at(v_credit),'-infinity')+interval '1 microsecond',
            COALESCE(app.deposit_balance_latest_at(v_refund.source_deposit_id),'-infinity')
                +interval '1 microsecond');
        v_business_date:=timezone(v_timezone,v_now)::date;
        v_net:=app.refund_net_value_at(v_refund.id,'infinity');
        v_return:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(v_correction,'refund_correction_id',v_return);
        INSERT INTO app.refund_corrections(id,refund_id,correction_kind,source_balance_effect_usd_cents,
            source_balance_effect_original_minor,previous_net_refund_usd_cents,resulting_net_refund_usd_cents,
            reason,evidence_reference,occurred_at,actor_id,authorization_reference,
            verified_return_amount_minor,verified_return_currency,verified_returned_at,return_method_reference)
        VALUES(v_return,v_refund.id,'VALUE_CORRECTION',v_amount,v_amount,v_net,v_net-v_amount,
            v_draft.reason,v_input->>'evidence_reference',v_now,p_actor,'financial.approve',v_amount,'USD',
            (v_input->>'returned_at')::timestamptz,v_input->>'return_method_reference');
        -- The shared DL-032 step (sub-slice 10c-2a-2; owner answers 1 and 3 to Q-2026-10-08-55),
        -- unless a returned Deposit Refund stays held (sub-slice 10c-2b-2a): under the same locks,
        -- the plan check again on the real state (stale P5S02 otherwise), then the Customer's
        -- Credit, the Deposit applications and the Deposit Refunds of the plan.
        IF (v_draft.payload->>'runs_step')::boolean THEN
            v_step:=app.post_settlement_correction_plan(p_property,p_actor,p_draft);
        END IF;
        -- A returned Credit's new Refund, when asked for: what is left in the Credit after the step,
        -- at most the returned amount, to the Credit's own Customer (BR-CREDIT-008, BR-CREDIT-014),
        -- with the draft's method and note in its own details row (BR-REFUND-014). Nothing left: no
        -- Refund, and with no new Refund the rest stays as that Customer's Credit.
        IF v_credit IS NOT NULL AND jsonb_typeof(v_input->'new_refund')='object' THEN
            v_pay:=LEAST(v_amount,app.credit_available_value(v_credit));
            IF v_pay>0 THEN
                v_refund_id:=gen_random_uuid();
                v_at:=GREATEST(clock_timestamp(),app.credit_latest_at(v_credit)+interval '1 microsecond');
                PERFORM app.link_settlement_correction_effect(v_correction,'refund_id',v_refund_id);
                INSERT INTO app.settlement_correction_refund_details(refund_id,settlement_correction_id,
                    draft_id,refund_method_id,reference_note,recorded_at)
                VALUES(v_refund_id,v_correction,p_draft,(v_input->'new_refund'->>'refund_method_id')::uuid,
                    v_input->'new_refund'->>'reference_note',v_at);
                INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_payment_id,
                    source_customer_credit_id,usd_accounting_value_cents,refund_currency,refund_amount_minor,
                    reason,processed_at,processed_by,authorization_reference)
                VALUES(v_refund_id,'REF-' || v_refund_id::text,v_refund.recipient_customer_id,NULL,v_credit,
                    v_pay,'USD',v_pay,v_draft.reason,v_at,p_actor,'refunds.create');
                v_refunds:=v_refunds||jsonb_build_array(jsonb_build_object('refund_id',v_refund_id,
                    'customer_credit_id',v_credit,'recipient_customer_id',v_refund.recipient_customer_id,
                    'amount_usd_cents',v_pay));
            END IF;
        END IF;
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_refund_return_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','REFUND_RETURN',
                'refund_id',v_refund.id,'refund_correction_id',v_return,'customer_credit_id',v_credit,
                'deposit_id',v_refund.source_deposit_id,
                'customer_id',v_refund.recipient_customer_id,'returned_amount_usd_cents',v_amount,
                'refunds',v_refunds,
                -- Every record the shared step wrote (sub-slice 10c-2a-3); none without a step.
                'credit_application_ids',COALESCE(v_step->'credit_application_ids','[]'::jsonb),
                'deposit_application_ids',COALESCE(v_step->'deposit_application_ids','[]'::jsonb),
                'deposit_refund_ids',COALESCE(v_step->'refund_ids','[]'::jsonb)),
            v_correction,'API','SUCCEEDED',v_evidence,v_refund.recipient_customer_id,v_settlement.lease_id,
            v_unit);
        RETURN v_result;
    END $$;
"""

REPLACED = (
    "app.settlement_refund_return_settlement(uuid)",
    "app.settlement_refund_return_allowed(app.refund_corrections)",
    "app.settlement_refund_return_source_state(uuid,uuid)",
    "app.settlement_refund_return_plan(uuid,uuid,jsonb)",
    "app.settlement_refund_return_overlay(jsonb)",
    "app.record_settlement_refund_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.confirm_settlement_refund_return(uuid,uuid,uuid,text)",
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
            raise RuntimeError(
                f"Returned Deposit Refund correction source contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    # CREATE OR REPLACE keeps the privileges migration 20261111_107 set on these functions.
    op.execute(SQL)
    _patch(GENERAL_CORRECTION, GENERAL_CORRECTION_REPLACEMENTS)
    _patch(RECEIPT_TRIGGER, RECEIPT_TRIGGER_REPLACEMENTS)
    _patch(RECEIPT_RECORDER, RECEIPT_RECORDER_REPLACEMENTS)
    _patch(FORFEITURE_RECORDER, FORFEITURE_RECORDER_REPLACEMENTS)
    _patch(DISPOSITION_TRIGGER, DISPOSITION_TRIGGER_REPLACEMENTS)
    _patch(PLAN_RESULT, PLAN_RESULT_REPLACEMENTS)
    _patch(STEP, STEP_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Returned Deposit Refund correction migration is forward-only")
