# ruff: noqa: E501
"""Post-settlement correction: a returned Credit Refund of a correction (V1-056 sub-slice 10c-2b-1).

BR-SETTLE-013, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014, BR-REFUND-014, DL-032, BR-AUTH-010;
owner answer 4 to the sub-slice 10c-1b review record (approved tightening), owner answer 4 to
Q-2026-10-07-41, answers 1 and 2 to Q-2026-10-07-42 and answers 1, 2 and 4 to Q-2026-10-08-55:

- Approved tightening: a Refund that a post-settlement correction paid (a Refund with a
  settlement_correction_refund_details row) is corrected only through another post-settlement
  correction. The one-call verified return and the one-call reversal of a return refuse it
  (P5202), and the Refund correction check refuses every other row for it (23514).
- A new correction variant, REFUND_RETURN, for a correction's Credit Refund whose money came back.
  Staff record it under final_settlements.prepare with a reason, the returned amount (at most the
  Refund's net value), the return date, the return method reference and the evidence, and
  optionally a new Refund (method and reference note). Only a financial.approve holder confirms
  it. The confirm writes the verified return (a refund_corrections row, financial.approve), linked
  to the correction first (refund_correction_id); the returned value goes back to the Credit.
- The returned Credit first pays its own Customer's open debt on this Lease through the shared
  DL-032 step after closure (Rent first or the Customer's designation, BR-CREDIT-006), whether or
  not a new Refund is paid (owner answer 1 to Q-2026-10-08-55). Only the rest is refunded to the
  same Customer, at most the returned amount, or stays as that Customer's Credit (answer 2).
- Relaxing: the Refund correction check accepts the correction's own verified return (linked, its
  REFUND_RETURN draft naming that Refund, amount, date and references, one return per correction,
  confirmed in this transaction by the row's actor); the relaxed Credit Refund check of sub-slice 10c-1b also counts what the correction's own
  returns gave back to the Credit, so the new Refund may go to a Customer who did not make the
  Payment (BR-CREDIT-014), and nothing more.
- The step's lock function takes the returned Refund's Credit and its Payment in its id-ordered
  passes. A Deposit Refund return is sub-slice 10c-2b-2.
"""

from alembic import op
from sqlalchemy import text

revision = "20261111_107"
down_revision = "20261110_106"
branch_labels = None
depends_on = None

VARIANT = "REFUND_RETURN"

INTERNAL = (
    "app.settlement_refund_return_settlement(uuid)",
    "app.settlement_refund_return_allowed(app.refund_corrections)",
    "app.settlement_refund_return_input(jsonb)",
    "app.settlement_refund_return_source_state(uuid,uuid)",
    "app.settlement_refund_return_plan(uuid,uuid,jsonb)",
    "app.settlement_refund_return_overlay(jsonb)",
    "app.settlement_refund_return_result(uuid)",
)
RECORD = "app.record_settlement_refund_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_refund_return(uuid,uuid,uuid,text)"

CORRECTABLE = "app.require_correctable_usd_refund(uuid,uuid)"
CORRECTABLE_REPLACEMENTS = (
    (
        "                OR (v_refund.source_deposit_id IS NOT NULL AND v_refund.pet_refund_review_id IS NULL) THEN\n",
        "                OR (v_refund.source_deposit_id IS NOT NULL AND v_refund.pet_refund_review_id IS NULL)\n"
        "                -- Sub-slice 10c-2b-1 (owner answer 4 to the 10c-1b review record): a Refund a\n"
        "                -- post-settlement correction paid is corrected only through another correction.\n"
        "                OR EXISTS(SELECT 1 FROM app.settlement_correction_refund_details detail\n"
        "                    WHERE detail.refund_id=v_refund.id) THEN\n",
    ),
)

GENERAL_CORRECTION = "app.validate_general_refund_correction()"
GENERAL_CORRECTION_REPLACEMENTS = (
    (
        "        DECLARE v_property uuid;\n",
        "        DECLARE v_property uuid; v_linked boolean;\n",
    ),
    (
        "                RAISE EXCEPTION 'A Final Settlement Refund is corrected only through a post-settlement correction'\n"
        "                    USING ERRCODE='23514'; END IF;\n",
        "                RAISE EXCEPTION 'A Final Settlement Refund is corrected only through a post-settlement correction'\n"
        "                    USING ERRCODE='23514'; END IF;\n"
        "            -- Sub-slice 10c-2b-1 (owner answer 4 to the 10c-1b review record, approved tightening):\n"
        "            -- a Refund a post-settlement correction paid is corrected only through another\n"
        "            -- correction: the verified return of a REFUND_RETURN correction of the Refund's own\n"
        "            -- Final Settlement, linked to it and confirmed in this transaction by this row's actor\n"
        "            -- under financial.approve; never a one-call row and never a reversal.\n"
        "            v_linked:=app.settlement_refund_return_allowed(NEW);\n"
        "            IF EXISTS(SELECT 1 FROM app.settlement_correction_refund_details detail\n"
        "                WHERE detail.refund_id=v_refund.id) AND NOT v_linked THEN\n"
        "                RAISE EXCEPTION 'A post-settlement correction Refund is corrected only through a post-settlement correction'\n"
        "                    USING ERRCODE='23514'; END IF;\n",
    ),
    (
        "                IF NEW.authorization_reference<>'refunds.correct'\n",
        "                -- A correction's own verified return carries financial.approve (sub-slice 10c-2b-1).\n"
        "                IF NEW.authorization_reference<>(CASE WHEN v_linked THEN 'financial.approve'\n"
        "                        ELSE 'refunds.correct' END)\n",
    ),
)

REFUND_ALLOWED = "app.settlement_correction_refund_allowed(app.refunds)"
REFUND_ALLOWED_REPLACEMENTS = (
    (
        "                    WHERE effect.settlement_correction_id=correction.id\n"
        "                      AND (release.customer_credit_id=credit.id\n"
        "                          OR application.customer_credit_id=credit.id))\n",
        "                    WHERE effect.settlement_correction_id=correction.id\n"
        "                      AND (release.customer_credit_id=credit.id\n"
        "                          OR application.customer_credit_id=credit.id))\n"
        "                    -- Sub-slice 10c-2b-1: and what the correction's own verified returns gave\n"
        "                    -- back to that Credit (a returned Credit Refund, BR-CREDIT-014).\n"
        "                    +(SELECT COALESCE(sum(returned.source_balance_effect_usd_cents),0)\n"
        "                    FROM app.settlement_correction_effects effect\n"
        "                    JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id\n"
        "                    JOIN app.refunds origin ON origin.id=returned.refund_id\n"
        "                    WHERE effect.settlement_correction_id=correction.id\n"
        "                      AND origin.source_customer_credit_id=credit.id)\n",
    ),
)

LOCK_PLAN = "app.lock_settlement_correction_plan(uuid)"
LOCK_PLAN_REPLACEMENTS = (
    (
        "        SELECT COALESCE(array_agg(DISTINCT app.final_settlement_plan_id(step->'target_id')::uuid),'{}')\n"
        "        INTO v_target_charges FROM jsonb_array_elements(v_steps) step\n",
        "        -- Sub-slice 10c-2b-1: a REFUND_RETURN correction's returned Credit Refund; its Credit\n"
        "        -- (and so its Payment) joins the same id-ordered passes, never a pass of its own.\n"
        "        IF v_draft.payload->>'variant'='REFUND_RETURN' THEN\n"
        "            SELECT v_credits||COALESCE(array_agg(refund.source_customer_credit_id),'{}') INTO v_credits\n"
        "            FROM app.refunds refund\n"
        "            WHERE refund.id=app.final_settlement_plan_id(v_draft.payload->'refund_return'->'refund_id')::uuid\n"
        "              AND refund.source_customer_credit_id IS NOT NULL;\n"
        "        END IF;\n"
        "        SELECT COALESCE(array_agg(DISTINCT app.final_settlement_plan_id(step->'target_id')::uuid),'{}')\n"
        "        INTO v_target_charges FROM jsonb_array_elements(v_steps) step\n",
    ),
)

SQL = r"""
    -- The closed Final Settlement whose post-settlement correction paid a Refund that a
    -- REFUND_RETURN correction may return; NULL for every other Refund. Sub-slice 10c-2b-1: a
    -- correction's Credit Refund (its details name no Deposit).
    CREATE FUNCTION app.settlement_refund_return_settlement(p_refund uuid)
    RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT correction.final_settlement_id FROM app.settlement_correction_refund_details detail
        JOIN app.settlement_corrections correction ON correction.id=detail.settlement_correction_id
        JOIN app.refunds refund ON refund.id=detail.refund_id
        WHERE detail.refund_id=p_refund AND detail.deposit_id IS NULL
          AND refund.source_customer_credit_id IS NOT NULL
    $$;

    -- Whether a Refund correction row is the verified return of a REFUND_RETURN correction: linked
    -- to that correction, which belongs to the Refund's own Final Settlement and was confirmed in
    -- this transaction; written by its approver under financial.approve; its draft names this
    -- Refund, the amount, the return date and the references; the correction writes no other
    -- return. Never NULL.
    CREATE FUNCTION app.settlement_refund_return_allowed(p_correction app.refund_corrections)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT (p_correction).correction_kind='VALUE_CORRECTION'
                AND (p_correction).authorization_reference='financial.approve'
                AND (p_correction).actor_id=correction.actor_id
                AND (p_correction).source_balance_effect_usd_cents
                    =(draft.payload->'refund_return'->>'returned_amount_usd_cents')::bigint
                AND (p_correction).verified_returned_at
                    =(draft.payload->'refund_return'->>'returned_at')::timestamptz
                -- The draft's references too, and one return per correction (review round 2).
                AND (p_correction).return_method_reference
                    =draft.payload->'refund_return'->>'return_method_reference'
                AND (p_correction).evidence_reference=draft.payload->'refund_return'->>'evidence_reference'
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

    -- The stored form of a returned-Refund correction: the Refund, the returned amount in cents,
    -- the return date (UTC), the return method reference, the evidence, and the new Refund's
    -- method and reference note or null. Malformed input 22023.
    CREATE FUNCTION app.settlement_refund_return_input(p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_refund text; v_method text; v_new jsonb; v_at timestamptz;
    BEGIN
        IF p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
            -- The byte order, whatever the database collation.
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input) key)
                IS DISTINCT FROM ARRAY['evidence_reference','new_refund','refund_id','return_method_reference',
                    'returned_amount_usd_cents','returned_at']
        THEN RAISE EXCEPTION 'Returned Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_refund:=app.final_settlement_plan_id(p_input->'refund_id');
        IF v_refund IS NULL
            OR jsonb_typeof(p_input->'returned_amount_usd_cents') IS DISTINCT FROM 'number'
            OR (p_input->>'returned_amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
            OR (p_input->>'returned_amount_usd_cents')::bigint>9000000000000000
            OR jsonb_typeof(p_input->'returned_at') IS DISTINCT FROM 'string'
            OR (p_input->>'returned_at')
                !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'
            OR jsonb_typeof(p_input->'return_method_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'return_method_reference',500) IS NOT TRUE
            OR jsonb_typeof(p_input->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'evidence_reference',500) IS NOT TRUE
            OR jsonb_typeof(p_input->'new_refund') NOT IN ('null','object')
        THEN RAISE EXCEPTION 'Returned Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        IF jsonb_typeof(p_input->'new_refund')='object' THEN
            v_method:=app.final_settlement_plan_id(p_input->'new_refund'->'refund_method_id');
            IF (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input->'new_refund') key)
                    IS DISTINCT FROM ARRAY['reference_note','refund_method_id']
                OR v_method IS NULL
                OR jsonb_typeof(p_input->'new_refund'->'reference_note') IS DISTINCT FROM 'string'
                OR app.lease_notice_text_valid(p_input->'new_refund'->>'reference_note',500) IS NOT TRUE
            THEN RAISE EXCEPTION 'Returned Refund correction input is invalid' USING ERRCODE='22023'; END IF;
            v_new:=jsonb_build_object('refund_method_id',v_method,
                'reference_note',p_input->'new_refund'->>'reference_note');
        END IF;
        -- An impossible date or offset is invalid input, not a database error (review round 2).
        BEGIN
            v_at:=(p_input->>'returned_at')::timestamptz;
        EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format
            OR invalid_time_zone_displacement_value THEN
            RAISE EXCEPTION 'Returned Refund correction input is invalid' USING ERRCODE='22023';
        END;
        IF NOT isfinite(v_at) THEN
            RAISE EXCEPTION 'Returned Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('refund_id',v_refund,
            'returned_amount_usd_cents',(p_input->>'returned_amount_usd_cents')::bigint,
            'returned_at',to_jsonb(v_at),
            'return_method_reference',p_input->>'return_method_reference',
            'evidence_reference',p_input->>'evidence_reference',
            'new_refund',COALESCE(v_new,'null'::jsonb));
    END $$;

    -- What a returned-Refund correction depends on: the Settlement, the Refund with its net value
    -- and its corrections, and the Credit it came from.
    CREATE FUNCTION app.settlement_refund_return_source_state(p_settlement uuid,p_refund uuid)
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
                WHERE refund.id=p_refund))
    $$;

    -- Checks a stored-form returned-Refund correction against the current state and returns what
    -- the draft records: the Lease, the Refund's recipient, its Credit, the correction and the
    -- source revision. An unknown Settlement or Refund P0002; a state the correction does not
    -- allow 55000.
    CREATE FUNCTION app.settlement_refund_return_plan(p_property uuid,p_settlement uuid,p_input jsonb)
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
        -- Sub-slice 10c-2b-1: a Credit Refund that a correction of this Settlement paid.
        IF app.settlement_refund_return_settlement(v_refund.id) IS DISTINCT FROM v_settlement.id THEN
            RAISE EXCEPTION 'The returned Refund is not a Refund this correction may return'
                USING ERRCODE='55000'; END IF;
        IF (p_input->>'returned_amount_usd_cents')::bigint>app.refund_net_value_at(v_refund.id,'infinity') THEN
            RAISE EXCEPTION 'The returned amount exceeds the Refund''s net value' USING ERRCODE='55000'; END IF;
        v_at:=(p_input->>'returned_at')::timestamptz;
        IF v_at<v_refund.processed_at OR v_at>clock_timestamp() THEN
            RAISE EXCEPTION 'The return is dated before the Refund or in the future' USING ERRCODE='55000';
        END IF;
        -- BR-REFUND-014: an active Refund method for the new Refund (as the Refund correction).
        IF jsonb_typeof(p_input->'new_refund')='object' THEN
            PERFORM 1 FROM app.refund_methods
            WHERE id=(p_input->'new_refund'->>'refund_method_id')::uuid AND active;
            IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,
            'customer_id',v_refund.recipient_customer_id,
            'customer_credit_id',v_refund.source_customer_credit_id,'refund_return',p_input,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_refund_return_source_state(p_settlement,v_refund.id)::text,'UTF8')),'hex'));
    END $$;

    -- The overlay of a returned Credit Refund for the shared DL-032 step (sub-slice 10c-2a-2): the
    -- returned amount goes back to the Refund's Credit, which pays only its own Customer's debt.
    CREATE FUNCTION app.settlement_refund_return_overlay(p_plan jsonb)
    RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object('obligations','{}'::jsonb,'deposits','{}'::jsonb,
            'credits',jsonb_build_object(p_plan->>'customer_credit_id',jsonb_build_object(
                'customer_id',p_plan->'customer_id',
                'add_usd_cents',p_plan->'refund_return'->'returned_amount_usd_cents',
                'released_payment_allocation_id',NULL)))
    $$;

    -- Staff record a returned-Refund correction draft (final_settlements.prepare); it has no
    -- financial effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_refund_return_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_return jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
        v_steps jsonb; v_overlay jsonb; v_result jsonb; v_choice text;
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
        -- The shared step's check on the state after the return (sub-slice 10c-2a-2): the returned
        -- Credit first pays its own Customer's open debt on this Lease (owner answer 1 to
        -- Q-2026-10-08-55; the R2 rule of the step).
        v_overlay:=app.settlement_refund_return_overlay(v_plan);
        v_result:=app.settlement_correction_plan_result(p_property,p_actor,p_settlement,v_steps,v_overlay)
            -'source_revision';
        v_payload:=jsonb_build_object('variant','REFUND_RETURN','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id',
            'customer_credit_id',v_plan->'customer_credit_id','refund_return',v_input,
            'plan',v_steps,'plan_overlay',v_overlay,'plan_result',v_result);
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- What the confirm returns, also for an exact repeat (rebuilt from the stored records).
    CREATE FUNCTION app.settlement_refund_return_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'refund_corrections',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',returned.id,
                    'refund_id',returned.refund_id,'correction_kind',returned.correction_kind,
                    'returned_amount_usd_cents',returned.source_balance_effect_usd_cents,
                    'previous_net_refund_usd_cents',returned.previous_net_refund_usd_cents,
                    'resulting_net_refund_usd_cents',returned.resulting_net_refund_usd_cents,
                    'verified_returned_at',returned.verified_returned_at,
                    'return_method_reference',returned.return_method_reference,
                    'evidence_reference',returned.evidence_reference,'occurred_at',returned.occurred_at,
                    'actor_id',returned.actor_id,'authorization_reference',returned.authorization_reference)
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'credit_applications',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,
                    'customer_credit_id',application.customer_credit_id,'target_kind',application.target_kind,
                    'invoice_id',application.invoice_id,'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents,
                    'within_invoice_basis',application.within_invoice_basis) ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.customer_credit_applications application ON application.id=effect.customer_credit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'deposit_applications',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,
                    'deposit_id',application.deposit_id,'application_stage',application.application_stage,
                    'target_kind',application.target_kind,'invoice_line_id',application.invoice_line_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents,
                    'application_order',application.application_order) ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_applications application ON application.id=effect.deposit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'refunds',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',refund.id,
                    'refund_number',refund.refund_number,
                    'recipient_customer_id',refund.recipient_customer_id,
                    'source_customer_credit_id',refund.source_customer_credit_id,
                    'source_deposit_id',refund.source_deposit_id,
                    'amount_usd_cents',refund.usd_accounting_value_cents,
                    'refund_method_id',detail.refund_method_id,'reference_note',detail.reference_note,
                    'signer_agreement',detail.signer_agreement,
                    'reason',refund.reason,'processed_at',refund.processed_at,
                    'processed_by',refund.processed_by,
                    'authorization_reference',refund.authorization_reference)
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.refunds refund ON refund.id=effect.refund_id
                JOIN app.settlement_correction_refund_details detail ON detail.refund_id=refund.id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- A financial.approve holder confirms a returned-Refund correction: in one transaction the
    -- decision and the header (sub-slice 10a), then, each linked before it is written, the verified
    -- return (the value goes back to the Credit), the shared DL-032 step (the Credit first pays its
    -- own Customer's open debt on this Lease) and, when the draft asks for it, one Credit Refund of
    -- what is left of the returned amount. Refusals: an unknown Property, draft or Settlement
    -- P0002/P4501; an inactive or missing approver P4506 or 42501; business state 55000; a draft
    -- whose sources changed P5S02 (stale; it stays pending). Nothing is written unless everything
    -- succeeds.
    CREATE FUNCTION app.confirm_settlement_refund_return(p_property uuid,p_actor uuid,p_draft uuid,
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
        IF v_input IS DISTINCT FROM v_draft.payload->'refund_return' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_amount:=(v_input->>'returned_amount_usd_cents')::bigint;
        -- Lock order, the 8e-3 order (as sub-slice 10c-2a-3): the draft lock (above); the
        -- Settlement's draft lock; the Lease row FOR UPDATE; then the shared step's locks
        -- (app.lock_settlement_correction_plan), which for this variant take the returned Refund's
        -- Payment and Credit in their id-ordered passes, then the Lease's Charges and Invoices, the
        -- Settlement row and each Deposit's draft lock and row; then the Refund methods FOR SHARE;
        -- app.begin_settlement_correction locks the draft row and the Settlement row; the Refund
        -- correction check locks the returned Refund row FOR UPDATE last, at the return's insert.
        -- No other writer locks that row now: the one-call paths refuse a correction's Refund
        -- before any lock, and the confirms of one Settlement are serialized by its draft lock. A
        -- detected deadlock (40P01) is a conflict.
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
        -- and linked first): later than the Refund, its corrections and the Credit's latest event.
        v_now:=GREATEST(clock_timestamp(),v_refund.processed_at+interval '1 microsecond',
            COALESCE((SELECT max(correction.occurred_at) FROM app.refund_corrections correction
                WHERE correction.refund_id=v_refund.id),'-infinity')+interval '1 microsecond',
            COALESCE(app.credit_latest_at(v_credit),'-infinity')+interval '1 microsecond');
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
        -- The shared DL-032 step (sub-slice 10c-2a-2; owner answer 1 to Q-2026-10-08-55): under the
        -- same locks, the plan check again on the real state (stale P5S02 otherwise), then the
        -- Customer's Credit, the Deposit applications and the Deposit Refunds of the plan.
        v_step:=app.post_settlement_correction_plan(p_property,p_actor,p_draft);
        -- The new Refund, when asked for: what is left in the Credit after the step, at most the
        -- returned amount, to the Credit's own Customer (BR-CREDIT-008, BR-CREDIT-014), with the
        -- draft's method and note in its own details row (BR-REFUND-014). Nothing left: no Refund,
        -- and with no new Refund the rest stays as that Customer's Credit (owner answer 2).
        IF jsonb_typeof(v_input->'new_refund')='object' THEN
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
                'customer_id',v_refund.recipient_customer_id,'returned_amount_usd_cents',v_amount,
                'refunds',v_refunds,
                -- Every record the shared step wrote (sub-slice 10c-2a-3).
                'credit_application_ids',v_step->'credit_application_ids',
                'deposit_application_ids',v_step->'deposit_application_ids',
                'deposit_refund_ids',v_step->'refund_ids'),
            v_correction,'API','SUCCEEDED',v_evidence,v_refund.recipient_customer_id,v_settlement.lease_id,
            v_unit);
        RETURN v_result;
    END $$;
"""


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
            raise RuntimeError(f"Returned Refund correction source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    # The new helpers first: the patched Refund correction check calls one of them.
    op.execute(SQL)
    _patch(CORRECTABLE, CORRECTABLE_REPLACEMENTS)
    _patch(GENERAL_CORRECTION, GENERAL_CORRECTION_REPLACEMENTS)
    _patch(REFUND_ALLOWED, REFUND_ALLOWED_REPLACEMENTS)
    _patch(LOCK_PLAN, LOCK_PLAN_REPLACEMENTS)
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Returned Refund correction migration is forward-only")
