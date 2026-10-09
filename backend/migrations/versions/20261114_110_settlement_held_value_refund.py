# ruff: noqa: E501
"""Post-settlement correction: the refund-only form HELD_VALUE_REFUND (V1-056 sub-slice 10c-2b-3).

BR-SETTLE-008, BR-SETTLE-013, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014, BR-REFUND-014,
BR-REFUND-015, DL-032, BR-AUTH-010; owner answer 3 to Q-2026-10-07-42, answers 1, 2 and 4 to
Q-2026-10-08-55 and answer 2 to Q-2026-10-08-59:

- A later correction refunds value that an earlier return-only REFUND_RETURN correction of the
  same Final Settlement left, linked to that correction (the draft names it). Staff record it under
  final_settlements.prepare with a reason, the new Refund's method and reference note and the
  DL-032 plan; only a financial.approve holder confirms it.
- Credit form (the returned Refund had a Credit source): the Credit first pays its own Customer's
  open debt on this Lease through the shared DL-032 step (owner answer 1 to Q-2026-10-08-55); the
  new Refund is what is left in the Credit after the step, at most what the earlier correction
  left (its returned amount less the Credit applications its own step and the linked
  HELD_VALUE_REFUND corrections wrote from that Credit and less their Refunds from it), to the
  Credit's own Customer (BR-CREDIT-008, BR-CREDIT-014).
- Deposit form (the returned Refund had a Deposit source): only a Deposit on the DL-032 path that
  holds money (Q-2026-10-09-61 stays open for the others); the step applies the held money to the
  Lease's open debt in the DL-032 order and the plan's Deposit Refund steps refund the rest
  (owner answer 3 to Q-2026-10-07-42, BR-REFUND-015).
- Owner answer 1 to Q-2026-10-09-63: an earlier correction is named only while it still has value
  left (for a Deposit, its return less what the linked HELD_VALUE_REFUND corrections applied or
  refunded from that Deposit), and a Credit correction needs the Credit to hold value.

New functions only, plus two patched in place: the lock function takes the Credit in its
id-ordered passes, and the relaxed Credit Refund check counts what the earlier correction left.
"""

from alembic import op
from sqlalchemy import text

revision = "20261114_110"
down_revision = "20261113_109"
branch_labels = None
depends_on = None

LOCK_PLAN = "app.lock_settlement_correction_plan(uuid)"
LOCK_PLAN_REPLACEMENTS = (
    (
        "        SELECT COALESCE(array_agg(DISTINCT app.final_settlement_plan_id(step->'target_id')::uuid),'{}')\n"
        "        INTO v_target_charges FROM jsonb_array_elements(v_steps) step\n",
        "        -- Sub-slice 10c-2b-3: a HELD_VALUE_REFUND correction's Credit (and so its Payment) joins\n"
        "        -- the same id-ordered passes, never a pass of its own.\n"
        "        IF v_draft.payload->>'variant'='HELD_VALUE_REFUND'\n"
        "            AND jsonb_typeof(v_draft.payload->'customer_credit_id')='string' THEN\n"
        "            v_credits:=v_credits||ARRAY[app.final_settlement_plan_id(v_draft.payload->'customer_credit_id')::uuid];\n"
        "        END IF;\n"
        "        SELECT COALESCE(array_agg(DISTINCT app.final_settlement_plan_id(step->'target_id')::uuid),'{}')\n"
        "        INTO v_target_charges FROM jsonb_array_elements(v_steps) step\n",
    ),
)

REFUND_ALLOWED = "app.settlement_correction_refund_allowed(app.refunds)"
REFUND_ALLOWED_REPLACEMENTS = (
    (
        "                      AND origin.source_customer_credit_id=credit.id)\n",
        "                      AND origin.source_customer_credit_id=credit.id)\n"
        "                    -- Sub-slice 10c-2b-3: and what the earlier return-only correction a\n"
        "                    -- HELD_VALUE_REFUND correction names left in that Credit (BR-CREDIT-014).\n"
        "                    +app.settlement_held_credit_left(correction.id,credit.id)\n",
    ),
)

SQL = r"""
    -- What an earlier return-only REFUND_RETURN correction left in a Credit: its verified return to
    -- that Credit, less the Credit applications from that Credit its own step and every confirmed
    -- HELD_VALUE_REFUND correction linked to it wrote, and less the Refunds from that Credit of those
    -- linked corrections; p_except (a correction) is left out. Never below 0.
    CREATE FUNCTION app.settlement_held_credit_value(p_earlier uuid,p_credit uuid,p_except uuid)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        WITH users AS (
            SELECT p_earlier AS id
            UNION ALL
            SELECT later.id FROM app.settlement_corrections later
            JOIN app.financial_drafts draft
                ON draft.id=later.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE draft.payload->>'variant'='HELD_VALUE_REFUND'
              AND draft.payload->>'held_from_settlement_correction_id'=p_earlier::text
              AND later.id IS DISTINCT FROM p_except)
        SELECT GREATEST(0,
            (SELECT COALESCE(sum(returned.source_balance_effect_usd_cents),0)
                FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id
                JOIN app.refunds origin ON origin.id=returned.refund_id
                WHERE effect.settlement_correction_id=p_earlier AND origin.source_customer_credit_id=p_credit)
            -(SELECT COALESCE(sum(application.amount_usd_cents),0) FROM users
                JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=users.id
                JOIN app.customer_credit_applications application
                    ON application.id=effect.customer_credit_application_id
                WHERE application.customer_credit_id=p_credit)
            -(SELECT COALESCE(sum(refund.usd_accounting_value_cents),0) FROM users
                JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=users.id
                JOIN app.refunds refund ON refund.id=effect.refund_id
                WHERE refund.source_customer_credit_id=p_credit AND users.id<>p_earlier))
    $$;

    -- For the relaxed Credit Refund check: what the earlier correction a HELD_VALUE_REFUND
    -- correction names left in this Credit, without that correction's own records; 0 for every
    -- other correction or Credit.
    CREATE FUNCTION app.settlement_held_credit_left(p_correction uuid,p_credit uuid)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT app.settlement_held_credit_value(
                app.final_settlement_plan_id(draft.payload->'held_from_settlement_correction_id')::uuid,
                p_credit,correction.id)
            FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft
                ON draft.id=correction.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE correction.id=p_correction AND draft.payload->>'variant'='HELD_VALUE_REFUND'
              AND draft.payload->>'customer_credit_id'=p_credit::text),0)
    $$;

    -- What an earlier return-only REFUND_RETURN correction left in a Deposit (owner answer 1 to
    -- Q-2026-10-09-63): its verified return to that Deposit, less the Deposit applications and the
    -- Refunds from that Deposit every confirmed HELD_VALUE_REFUND correction linked to it wrote (a
    -- return-only Deposit correction runs no step). Never below 0.
    CREATE FUNCTION app.settlement_held_deposit_value(p_earlier uuid,p_deposit uuid)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        WITH linked AS (
            SELECT later.id FROM app.settlement_corrections later
            JOIN app.financial_drafts draft
                ON draft.id=later.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE draft.payload->>'variant'='HELD_VALUE_REFUND'
              AND draft.payload->>'held_from_settlement_correction_id'=p_earlier::text)
        SELECT GREATEST(0,
            (SELECT COALESCE(sum(returned.source_balance_effect_usd_cents),0)
                FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id
                JOIN app.refunds origin ON origin.id=returned.refund_id
                WHERE effect.settlement_correction_id=p_earlier AND origin.source_deposit_id=p_deposit)
            -(SELECT COALESCE(sum(application.amount_usd_cents),0) FROM linked
                JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=linked.id
                JOIN app.deposit_applications application
                    ON application.id=effect.deposit_application_id
                WHERE application.deposit_id=p_deposit)
            -(SELECT COALESCE(sum(refund.usd_accounting_value_cents),0) FROM linked
                JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=linked.id
                JOIN app.refunds refund ON refund.id=effect.refund_id
                WHERE refund.source_deposit_id=p_deposit))
    $$;

    -- The stored form of a held-value Refund correction: the earlier correction and the new
    -- Refund's method and reference note (both required, BR-REFUND-014). 22023 otherwise.
    CREATE FUNCTION app.settlement_held_value_input(p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_earlier text; v_method text;
    BEGIN
        IF p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
            -- The byte order, whatever the database collation.
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input) key)
                IS DISTINCT FROM ARRAY['held_from_settlement_correction_id','new_refund']
            OR jsonb_typeof(p_input->'new_refund') IS DISTINCT FROM 'object'
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input->'new_refund') key)
                IS DISTINCT FROM ARRAY['reference_note','refund_method_id']
            OR jsonb_typeof(p_input->'new_refund'->'reference_note') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->'new_refund'->>'reference_note',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Held value Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_earlier:=app.final_settlement_plan_id(p_input->'held_from_settlement_correction_id');
        v_method:=app.final_settlement_plan_id(p_input->'new_refund'->'refund_method_id');
        IF v_earlier IS NULL OR v_method IS NULL THEN
            RAISE EXCEPTION 'Held value Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('held_from_settlement_correction_id',v_earlier,
            'new_refund',jsonb_build_object('refund_method_id',v_method,
                'reference_note',p_input->'new_refund'->>'reference_note'));
    END $$;

    -- What a held-value Refund correction depends on: the Settlement, the earlier correction, its
    -- returned Refund's Credit (available value, latest event, what is left) or Deposit (held
    -- value, latest event, path, what is left), and the linked HELD_VALUE_REFUND corrections.
    CREATE FUNCTION app.settlement_held_value_source_state(p_settlement uuid,p_earlier uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        WITH earlier AS (
            SELECT correction.id,correction.correlation_id,
                (draft.payload->'refund_return'->>'refund_id')::uuid AS refund_id
            FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
            WHERE correction.id=p_earlier AND correction.final_settlement_id=p_settlement
              AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='REFUND_RETURN')
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'closed_at',settlement.closed_at,
                    'lease_id',settlement.lease_id)
                FROM app.final_settlements settlement WHERE settlement.id=p_settlement),
            'held_from',(SELECT jsonb_build_object('id',earlier.id,'draft_id',earlier.correlation_id,
                    'refund_id',earlier.refund_id) FROM earlier),
            'credit',(SELECT jsonb_build_object('id',credit.id,'customer_id',credit.customer_id,
                    'available_usd_cents',app.credit_available_value(credit.id),
                    'latest_at',app.credit_latest_at(credit.id),
                    'left_usd_cents',app.settlement_held_credit_value(p_earlier,credit.id,NULL))
                FROM earlier JOIN app.refunds refund ON refund.id=earlier.refund_id
                JOIN app.customer_credits credit ON credit.id=refund.source_customer_credit_id),
            'deposit',(SELECT jsonb_build_object('id',deposit.id,
                    'held_usd_cents',app.deposit_held_value_at(deposit.id,'infinity'),
                    'latest_at',app.deposit_balance_latest_at(deposit.id),
                    'path',app.lease_deposit_settlement_path(app.deposit_property_id(deposit.id),deposit.id)->>'path',
                    'left_usd_cents',app.settlement_held_deposit_value(p_earlier,deposit.id))
                FROM earlier JOIN app.refunds refund ON refund.id=earlier.refund_id
                JOIN app.deposits deposit ON deposit.id=refund.source_deposit_id),
            'linked',(SELECT COALESCE(jsonb_agg(later.id ORDER BY later.id),'[]'::jsonb)
                FROM app.settlement_corrections later
                JOIN app.financial_drafts draft
                    ON draft.id=later.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
                WHERE draft.payload->>'variant'='HELD_VALUE_REFUND'
                  AND draft.payload->>'held_from_settlement_correction_id'=p_earlier::text))
    $$;

    -- Checks a stored-form held-value Refund correction against the current state and returns what
    -- the draft records: the Lease, the Customer, the Credit or the Deposit, the earlier correction,
    -- what it left in the Credit and the source revision. An unknown Settlement or earlier
    -- correction P0002; a state the correction does not allow 55000.
    CREATE FUNCTION app.settlement_held_value_plan(p_property uuid,p_settlement uuid,p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_earlier app.settlement_corrections%ROWTYPE;
        v_draft app.financial_drafts%ROWTYPE; v_refund app.refunds%ROWTYPE; v_left bigint;
        v_customer uuid;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT * INTO v_earlier FROM app.settlement_corrections
        WHERE id=(p_input->>'held_from_settlement_correction_id')::uuid AND final_settlement_id=v_settlement.id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Post-settlement correction was not found' USING ERRCODE='P0002'; END IF;
        -- Only an earlier return-only returned-Refund correction leaves value for a later Refund.
        SELECT * INTO v_draft FROM app.financial_drafts
        WHERE id=v_earlier.correlation_id AND kind='SETTLEMENT_CORRECTION';
        IF NOT FOUND OR v_draft.payload->>'variant' IS DISTINCT FROM 'REFUND_RETURN'
            OR v_draft.payload->'refund_return'->'new_refund' IS DISTINCT FROM 'null'::jsonb
        THEN RAISE EXCEPTION 'Only a return-only returned-Refund correction leaves value for a later Refund'
            USING ERRCODE='55000'; END IF;
        SELECT * INTO STRICT v_refund FROM app.refunds
        WHERE id=(v_draft.payload->'refund_return'->>'refund_id')::uuid;
        -- BR-REFUND-014: an active Refund method for the new Refund.
        PERFORM 1 FROM app.refund_methods
        WHERE id=(p_input->'new_refund'->>'refund_method_id')::uuid AND active;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        IF v_refund.source_customer_credit_id IS NOT NULL THEN
            v_left:=app.settlement_held_credit_value(v_earlier.id,v_refund.source_customer_credit_id,NULL);
            IF v_left<=0 THEN
                RAISE EXCEPTION 'Nothing the earlier correction returned is left to refund'
                    USING ERRCODE='55000'; END IF;
            -- Owner answer 1 to Q-2026-10-09-63: the Credit must still hold some of it, also when
            -- the plan has other steps.
            IF app.credit_available_value(v_refund.source_customer_credit_id)<=0 THEN
                RAISE EXCEPTION 'The Credit holds no returned value to refund' USING ERRCODE='55000'; END IF;
            SELECT credit.customer_id INTO STRICT v_customer FROM app.customer_credits credit
            WHERE credit.id=v_refund.source_customer_credit_id;
        ELSE
            -- DL-032: only a Deposit on the DL-032 path pays debt or is refunded after its return
            -- (Q-2026-10-09-61 is open for the others).
            IF app.lease_deposit_settlement_path(p_property,v_refund.source_deposit_id)->>'path'
                IS DISTINCT FROM 'DL_032'
            THEN RAISE EXCEPTION 'A returned Deposit pays debt or is refunded again only on the DL-032 path'
                USING ERRCODE='55000'; END IF;
            -- Owner answer 1 to Q-2026-10-09-63: the earlier correction is named only while it still
            -- has value left in the Deposit.
            v_left:=app.settlement_held_deposit_value(v_earlier.id,v_refund.source_deposit_id);
            IF v_left<=0 THEN
                RAISE EXCEPTION 'Nothing the earlier correction returned is left to refund'
                    USING ERRCODE='55000'; END IF;
            IF app.deposit_held_value_at(v_refund.source_deposit_id,'infinity')<=0 THEN
                RAISE EXCEPTION 'The Deposit holds no returned money to refund' USING ERRCODE='55000'; END IF;
            -- The Deposit's owner; the confirm's audit event names the Refund's recipient.
            SELECT deposit.customer_id INTO STRICT v_customer FROM app.deposits deposit
            WHERE deposit.id=v_refund.source_deposit_id;
        END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,'customer_id',v_customer,
            'customer_credit_id',v_refund.source_customer_credit_id,'deposit_id',v_refund.source_deposit_id,
            'held_from_settlement_correction_id',v_earlier.id,'left_usd_cents',v_left,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_held_value_source_state(p_settlement,v_earlier.id)::text,'UTF8')),'hex'));
    END $$;

    -- Staff record a held-value Refund correction draft (final_settlements.prepare); it has no
    -- financial effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_held_value_refund_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_held jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
        v_steps jsonb; v_overlay jsonb; v_result jsonb; v_choice text; v_pay bigint;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters, as every correction's.
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
            OR p_held IS NULL OR jsonb_typeof(p_held) IS DISTINCT FROM 'object'
        THEN RAISE EXCEPTION 'Held value Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_held_value_input(p_held-'plan');
        v_steps:=COALESCE(p_held->'plan',jsonb_build_object('steps','[]'::jsonb,'pet_remainder','null'::jsonb));
        IF jsonb_typeof(v_steps) IS DISTINCT FROM 'object' OR jsonb_typeof(v_steps->'steps') IS DISTINCT FROM 'array'
        THEN RAISE EXCEPTION 'Held value Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='HELD_VALUE_REFUND' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'held_value'=v_input AND v_existing.payload->'plan'=v_steps
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_held_value_plan(p_property,p_settlement,v_input);
        -- One Refund method and reference note per correction: every Deposit Refund step uses the
        -- new Refund's.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_steps->'steps') step
            WHERE step->>'kind'='DEPOSIT_REFUNDS'
              AND (app.final_settlement_plan_id(step->'refund_method_id')
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
        -- The shared step's check on the current state (sub-slice 10c-2a-2): a held Credit first
        -- pays its own Customer's open debt on this Lease (owner answer 1 to Q-2026-10-08-55), held
        -- Deposit value first pays the Lease's open debt in the DL-032 order (owner answer 3 to
        -- Q-2026-10-07-42). The money is already held, so nothing is added.
        v_overlay:=jsonb_build_object('obligations','{}'::jsonb,'deposits','{}'::jsonb,
            'credits',CASE WHEN jsonb_typeof(v_plan->'customer_credit_id')='string'
                THEN jsonb_build_object(v_plan->>'customer_credit_id',jsonb_build_object(
                    'customer_id',v_plan->'customer_id','add_usd_cents',0,
                    'released_payment_allocation_id',NULL))
                ELSE '{}'::jsonb END);
        v_result:=app.settlement_correction_plan_result(p_property,p_actor,p_settlement,v_steps,v_overlay)
            -'source_revision';
        -- A Credit correction that would pay no Refund and has no step writes nothing.
        IF jsonb_typeof(v_plan->'customer_credit_id')='string' THEN
            v_pay:=LEAST((v_plan->>'left_usd_cents')::bigint,
                COALESCE((v_result->'credit_left'->>(v_plan->>'customer_credit_id'))::bigint,0));
            IF v_pay<=0 AND jsonb_array_length(v_steps->'steps')=0 THEN
                RAISE EXCEPTION 'The held value Refund correction would write nothing' USING ERRCODE='55000';
            END IF;
        END IF;
        v_payload:=jsonb_build_object('variant','HELD_VALUE_REFUND','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id',
            'customer_credit_id',v_plan->'customer_credit_id','deposit_id',v_plan->'deposit_id',
            'held_from_settlement_correction_id',v_plan->'held_from_settlement_correction_id',
            'held_value',v_input,'plan',v_steps,'plan_overlay',v_overlay,'plan_result',v_result);
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- A financial.approve holder confirms a held-value Refund correction: in one transaction the
    -- decision and the header (sub-slice 10a), then, each linked before it is written, the shared
    -- DL-032 step and, for a Credit, one Credit Refund of what is left in the Credit after the step,
    -- at most what the earlier correction left (a Deposit's Refund is the plan's Deposit Refund
    -- step). Refusals: an unknown Property, draft or Settlement P0002/P4501; an inactive or missing
    -- approver P4506 or 42501; business state 55000; a draft whose sources changed P5S02 (stale;
    -- it stays pending). Nothing is written unless everything succeeds.
    CREATE FUNCTION app.confirm_settlement_held_value_refund(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_timezone text; v_now timestamptz; v_business_date date; v_input jsonb; v_plan jsonb;
        v_correction uuid; v_unit uuid; v_evidence jsonb; v_result jsonb; v_step jsonb; v_method uuid;
        v_credit uuid; v_deposit uuid; v_customer uuid; v_earlier uuid; v_pay bigint; v_refund_id uuid;
        v_at timestamptz; v_refunds jsonb:='[]'::jsonb; v_settled jsonb;
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
              AND draft.payload->>'variant'='HELD_VALUE_REFUND' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_refund_return_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'HELD_VALUE_REFUND'
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
        v_input:=app.settlement_held_value_input(v_draft.payload->'held_value');
        IF v_input IS DISTINCT FROM v_draft.payload->'held_value' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_earlier:=(v_input->>'held_from_settlement_correction_id')::uuid;
        -- Lock order, the 8e-3 order (as the returned-Refund confirm): the draft lock (above); the
        -- Settlement's draft lock; the Lease row FOR UPDATE; then the shared step's locks
        -- (app.lock_settlement_correction_plan), which for this variant take a held Credit's Payment
        -- and Credit in their id-ordered passes, then the Lease's Charges and Invoices, the
        -- Settlement row and each Deposit's draft lock and row; then the Refund methods FOR SHARE;
        -- app.begin_settlement_correction locks the draft row and the Settlement row. A detected
        -- deadlock (40P01) is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same correction; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_held_value_source_state(
                v_settlement.id,v_earlier)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_held_value_plan(p_property,v_settlement.id,v_input);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
            OR v_plan->'customer_credit_id' IS DISTINCT FROM v_draft.payload->'customer_credit_id'
            OR v_plan->'deposit_id' IS DISTINCT FROM v_draft.payload->'deposit_id'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_credit:=app.final_settlement_plan_id(v_plan->'customer_credit_id')::uuid;
        v_deposit:=app.final_settlement_plan_id(v_plan->'deposit_id')::uuid;
        v_customer:=app.final_settlement_plan_id(v_plan->'customer_id')::uuid;
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
            'variant','HELD_VALUE_REFUND','held_from_settlement_correction_id',v_earlier);
        v_now:=GREATEST(clock_timestamp(),
            COALESCE(app.credit_latest_at(v_credit),'-infinity')+interval '1 microsecond',
            COALESCE(app.deposit_balance_latest_at(v_deposit),'-infinity')+interval '1 microsecond');
        v_business_date:=timezone(v_timezone,v_now)::date;
        -- The shared DL-032 step (sub-slice 10c-2a-2): under the same locks, the plan check again on
        -- the real state (stale P5S02 otherwise), then the Customer's Credit, the Deposit
        -- applications and the Deposit Refunds of the plan.
        v_step:=app.post_settlement_correction_plan(p_property,p_actor,p_draft);
        -- A held Credit's Refund: what is left in the Credit after the step, at most what the earlier
        -- correction left, to the Credit's own Customer (BR-CREDIT-008, BR-CREDIT-014), with the
        -- draft's method and note in its own details row (BR-REFUND-014). Nothing left: no Refund.
        IF v_credit IS NOT NULL THEN
            v_pay:=LEAST(app.settlement_held_credit_value(v_earlier,v_credit,v_correction),
                app.credit_available_value(v_credit));
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
                VALUES(v_refund_id,'REF-' || v_refund_id::text,v_customer,NULL,v_credit,
                    v_pay,'USD',v_pay,v_draft.reason,v_at,p_actor,'refunds.create');
                v_refunds:=v_refunds||jsonb_build_array(jsonb_build_object('refund_id',v_refund_id,
                    'customer_credit_id',v_credit,'recipient_customer_id',v_customer,
                    'amount_usd_cents',v_pay));
            END IF;
        END IF;
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_refund_return_result(p_draft);
        -- A Deposit correction's audit event names the recipient of the Deposit Refund the step
        -- wrote (one recipient per correction), or the Deposit's owner when nothing was refunded
        -- (review round 1).
        IF v_deposit IS NOT NULL THEN
            v_customer:=COALESCE((SELECT refund.recipient_customer_id FROM app.refunds refund
                WHERE refund.id IN (SELECT listed::uuid
                    FROM jsonb_array_elements_text(COALESCE(v_step->'refund_ids','[]'::jsonb)) listed)
                ORDER BY refund.id LIMIT 1),v_customer);
        END IF;
        -- Owner answer 1 to Q-2026-10-09-63: every Deposit balance the step settled, whichever
        -- earlier correction returned the money (BR-SETTLE-008).
        SELECT COALESCE(jsonb_agg(jsonb_build_object('deposit_id',settled.deposit_id,
                'applied_usd_cents',settled.applied,'refunded_usd_cents',settled.refunded)
                ORDER BY settled.deposit_id),'[]'::jsonb)
        INTO v_settled
        FROM (SELECT moved.deposit_id,sum(moved.applied)::bigint AS applied,
                sum(moved.refunded)::bigint AS refunded
            FROM (SELECT application.deposit_id,application.amount_usd_cents AS applied,
                    0::bigint AS refunded
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_applications application
                    ON application.id=effect.deposit_application_id
                WHERE effect.settlement_correction_id=v_correction
                UNION ALL
                SELECT refund.source_deposit_id,0::bigint,refund.usd_accounting_value_cents
                FROM app.settlement_correction_effects effect
                JOIN app.refunds refund ON refund.id=effect.refund_id
                WHERE effect.settlement_correction_id=v_correction AND refund.source_deposit_id IS NOT NULL) moved
            GROUP BY moved.deposit_id) settled;
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','HELD_VALUE_REFUND',
                'held_from_settlement_correction_id',v_earlier,'customer_credit_id',v_credit,
                'deposit_id',v_deposit,'customer_id',v_customer,'refunds',v_refunds,
                -- Every record the shared step wrote (sub-slice 10c-2a-3).
                'credit_application_ids',COALESCE(v_step->'credit_application_ids','[]'::jsonb),
                'deposit_application_ids',COALESCE(v_step->'deposit_application_ids','[]'::jsonb),
                'deposit_refund_ids',COALESCE(v_step->'refund_ids','[]'::jsonb),
                'settled_deposits',v_settled),
            v_correction,'API','SUCCEEDED',v_evidence,v_customer,v_settlement.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""

INTERNAL = (
    "app.settlement_held_credit_value(uuid,uuid,uuid)",
    "app.settlement_held_credit_left(uuid,uuid)",
    "app.settlement_held_deposit_value(uuid,uuid)",
    "app.settlement_held_value_input(jsonb)",
    "app.settlement_held_value_source_state(uuid,uuid)",
    "app.settlement_held_value_plan(uuid,uuid,jsonb)",
)
RECORD = "app.record_settlement_held_value_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_held_value_refund(uuid,uuid,uuid,text)"


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
            raise RuntimeError(f"Held value Refund correction source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    # The new helpers first: the patched relaxed Credit Refund check calls one of them.
    op.execute(SQL)
    _patch(LOCK_PLAN, LOCK_PLAN_REPLACEMENTS)
    _patch(REFUND_ALLOWED, REFUND_ALLOWED_REPLACEMENTS)
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Held value Refund correction migration is forward-only")
