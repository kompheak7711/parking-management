# ruff: noqa: E501
"""Post-settlement correction: Refund of a Deposit-paid charge (V1-056 sub-slice 10c-2a-3).

DL-032, BR-SETTLE-008, BR-SETTLE-013, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014, BR-DEP-027,
BR-REFUND-014, BR-REFUND-015, BR-AUTH-010; owner answers 1 to 3 to Q-2026-10-07-41, 1 and 2 to
Q-2026-10-07-42, 3 and 4 to Q-2026-10-07-44, and the answer to Q-2026-10-07-46.

The REFUND correction of sub-slice 10c-1b is extended in place (same signatures):

- The release takes whole sources newest first across Deposit applications, Payment allocations
  and Credit applications (Q-41 answer 2). A released Deposit application is reversed (sub-slice
  10c-2a-1) and its value goes back to its Deposit; it never becomes Customer Credit. The rest of a
  partly released Deposit application is paid again only as a step of the correction's plan.
- Every REFUND correction runs the shared DL-032 step of sub-slice 10c-2a-2 after its release:
  released Credit first pays its own Customer's open debt on this Lease (Q-42 answer 2), released
  or held Deposit value then pays the Lease's open debt in the DL-032 order, and only the rest is
  refunded. A Customer with no open debt on this Lease gets the Refund as before. The draft keeps
  the staff's plan, the overlay of the release and the plan check's result.
- A remaining Pet Deposit step at a BR-DEP-027 termination needs a Customer choice given for this
  correction; the Final Settlement's choice is not reused (Q-44 answer 3).
- The confirm locks the Lease row FOR UPDATE right after the two draft locks, in the 8e-3 order
  (Q-44 answer 4), and then takes the step's locks. For a REFUND draft the step's lock function
  (patched here, same signature) also takes the released sources' Payments and Credits in its own
  id-ordered Payment and Credit passes (security review round 2) and the corrected Invoice FOR
  UPDATE in its Invoice pass, after the Charges (security review round 1).
- Relaxing (Q-46): the 8a-1 refusal lets through an Invoice Adjustment linked to a correction of
  that Invoice's own Settlement, confirmed in this transaction by that correction's approver.
  Every unlinked Adjustment stays refused. No line is paid more than its new amount: the deferred
  Adjustment check already refuses a line whose outstanding value, Deposit applications included,
  is below zero at the Adjustment's time.
"""

from alembic import op
from sqlalchemy import text

revision = "20261107_103"
down_revision = "20261106_102"
branch_labels = None
depends_on = None

RELEASE_REASON = "Invoice adjustment credit excess"

INTERNAL = (
    "app.settlement_correction_adjustment_allowed(uuid,uuid,uuid)",
    "app.settlement_refund_overlay(jsonb,uuid)",
)

DEPOSIT_APPLIED = "app.refuse_deposit_applied_obligation_change()"
DEPOSIT_APPLIED_REPLACEMENTS = (
    (
        "        BEGIN\n"
        "            -- Separate branches: each table's row has only its own target column.\n",
        "        BEGIN\n"
        "            -- Sub-slice 10c-2a-3 (owner answer to Q-2026-10-07-46): an Adjustment linked to a\n"
        "            -- post-settlement correction of its Invoice's own Settlement, confirmed in this\n"
        "            -- transaction by that correction's approver, passes; every other one stays refused.\n"
        "            IF TG_TABLE_NAME='invoice_adjustments' THEN\n"
        "                IF app.settlement_correction_adjustment_allowed(NEW.invoice_id,NEW.id,NEW.actor_id) THEN\n"
        "                    RETURN NEW; END IF;\n"
        "            END IF;\n"
        "            -- Separate branches: each table's row has only its own target column.\n",
    ),
)

LOCK_PLAN = "app.lock_settlement_correction_plan(uuid)"
LOCK_PLAN_REPLACEMENTS = (
    (
        "        v_target_charges uuid[]; v_target_invoices uuid[]; v_credit_invoices uuid[]; v_id uuid; v_flag boolean;\n",
        "        v_target_charges uuid[]; v_target_invoices uuid[]; v_credit_invoices uuid[]; v_id uuid; v_flag boolean;\n"
        "        v_payments uuid[]:='{}';\n",
    ),
    (
        "        WHERE step->>'kind'='CUSTOMER_CREDIT';\n",
        "        WHERE step->>'kind'='CUSTOMER_CREDIT';\n"
        "        -- Sub-slice 10c-2a-3 (security review round 2): a REFUND correction's released sources\n"
        "        -- are locked in the same id-ordered passes as the Credit steps' (their Payments, then their\n"
        "        -- Credits), never in a pass of their own, so Payments are always locked in id order.\n"
        "        IF v_draft.payload->>'variant'='REFUND' AND jsonb_typeof(v_draft.payload->'released_sources')='array' THEN\n"
        "            SELECT v_credits||COALESCE(array_agg(DISTINCT credit.id),'{}') INTO v_credits\n"
        "            FROM jsonb_array_elements(v_draft.payload->'released_sources') source\n"
        "            JOIN app.customer_credits credit ON credit.id=app.final_settlement_plan_id(source->'credit_id')::uuid;\n"
        "            SELECT COALESCE(array_agg(DISTINCT app.final_settlement_plan_id(source->'payment_id')::uuid),'{}')\n"
        "            INTO v_payments FROM jsonb_array_elements(v_draft.payload->'released_sources') source\n"
        "            WHERE app.final_settlement_plan_id(source->'payment_id') IS NOT NULL;\n"
        "        END IF;\n",
    ),
    (
        "        FOR v_id IN SELECT DISTINCT credit.source_payment_id FROM app.customer_credits credit\n"
        "            WHERE credit.id=ANY(v_credits) ORDER BY 1\n",
        "        FOR v_id IN SELECT payment.id FROM (SELECT credit.source_payment_id AS id\n"
        "                FROM app.customer_credits credit WHERE credit.id=ANY(v_credits)\n"
        "                UNION SELECT unnest(v_payments)) payment\n"
        "            WHERE payment.id IS NOT NULL ORDER BY 1\n",
    ),
    (
        "            FROM app.late_payment_charges charge WHERE charge.id=ANY(v_target_charges)),'{}');\n",
        "            FROM app.late_payment_charges charge WHERE charge.id=ANY(v_target_charges)),'{}');\n"
        "        -- Sub-slice 10c-2a-3 (security review round 1): a REFUND correction's own Invoice is\n"
        "        -- locked FOR UPDATE here, in the id-ordered Invoice pass after the Payments, Credits and\n"
        "        -- Charges, never before them.\n"
        "        IF v_draft.payload->>'variant'='REFUND' THEN\n"
        "            v_target_invoices:=v_target_invoices\n"
        "                ||ARRAY[app.final_settlement_plan_id(v_draft.payload->'refund'->'invoice_id')::uuid];\n"
        "        END IF;\n",
    ),
)

REFUND_INPUT = "app.settlement_refund_input(jsonb)"
REFUND_INPUT_REPLACEMENTS = (
    (
        "                    'reference_note'))\n",
        "                    -- The DL-032 plan of sub-slice 10c-2a-3 (checked by the recorder).\n"
        "                    'reference_note','plan'))\n",
    ),
)

SQL = f"""
    -- Q-46: an Invoice Adjustment linked to a post-settlement correction of its Invoice's own
    -- (closed) Settlement, confirmed in this transaction by that correction's approver.
    CREATE FUNCTION app.settlement_correction_adjustment_allowed(p_invoice uuid,p_adjustment uuid,
        p_actor uuid)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT p_actor IS NOT NULL AND EXISTS(SELECT 1 FROM app.invoices invoice
            JOIN app.final_settlements settlement
                ON settlement.lease_id=invoice.lease_id AND settlement.closed_at IS NOT NULL
            JOIN app.settlement_correction_effects effect ON effect.invoice_adjustment_id=p_adjustment
            JOIN app.settlement_corrections correction
                ON correction.id=effect.settlement_correction_id AND correction.final_settlement_id=settlement.id
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=correction.correlation_id AND decision.decision='CONFIRMED'
            WHERE invoice.id=p_invoice AND correction.actor_id=p_actor AND decision.decided_by=p_actor
              AND decision.authorization_reference='financial.approve'
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp())
    $$;

    -- The sources that pay a line now, newest first across Deposit applications, Payment
    -- allocations and Credit applications (Q-41 answer 2; sub-slice 10c-2a-3): the Payment, the
    -- Credit or the Deposit, and the Customer the released value belongs to (the Invoice Customer
    -- for an allocation, BR-CREDIT-014; the Credit's Customer for an application, BR-CREDIT-008;
    -- the Deposit owner for a Deposit application, whose value goes back to the Deposit).
    CREATE OR REPLACE FUNCTION app.settlement_refund_line_sources(p_invoice uuid,p_line uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        -- Sub-slice 10c-2a-3: Deposit applications are sources too (whole, newest first).
        SELECT COALESCE(jsonb_agg(jsonb_build_object('kind',source.kind,'id',source.id,
                'on_line_usd_cents',source.on_line,'at',source.at,'payment_id',source.payment_id,
                'credit_id',source.credit_id,'recipient_customer_id',source.recipient,
                'payer_customer_id',payment.payer_customer_id)
                || CASE WHEN source.kind='DEPOSIT_APPLICATION'
                    THEN jsonb_build_object('deposit_id',source.deposit_id) ELSE '{{}}'::jsonb END
            ORDER BY source.at DESC,source.id DESC),'[]'::jsonb)
        FROM (
            SELECT 'PAYMENT_ALLOCATION'::text AS kind,allocation.id,
                detail.posted_amount_usd_cents AS on_line,allocation.posted_at AS at,
                allocation.payment_id,NULL::uuid AS credit_id,invoice.customer_id AS recipient,
                NULL::uuid AS deposit_id
            FROM app.payment_allocation_details detail
            JOIN app.payment_allocations allocation ON allocation.id=detail.payment_allocation_id
            JOIN app.invoices invoice ON invoice.id=allocation.invoice_id
            WHERE detail.invoice_line_id=p_line AND allocation.invoice_id=p_invoice
              AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                  WHERE reversal.payment_allocation_id=allocation.id)
            UNION ALL
            SELECT 'CREDIT_APPLICATION',application.id,detail.applied_amount_usd_cents,
                application.occurred_at,credit.source_payment_id,credit.id,credit.customer_id,NULL::uuid
            FROM app.customer_credit_application_details detail
            JOIN app.customer_credit_applications application
                ON application.id=detail.customer_credit_application_id
            JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
            WHERE detail.invoice_line_id=p_line AND application.invoice_id=p_invoice
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                  WHERE reversal.credit_application_id=application.id)
            UNION ALL
            SELECT 'DEPOSIT_APPLICATION',application.id,application.amount_usd_cents,
                application.occurred_at,NULL::uuid,NULL::uuid,deposit.customer_id,application.deposit_id
            FROM app.deposit_applications application
            JOIN app.deposits deposit ON deposit.id=application.deposit_id
            WHERE application.invoice_line_id=p_line AND application.invoice_id=p_invoice
              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                  WHERE reversal.deposit_application_id=application.id)
        ) source
        LEFT JOIN app.payments payment ON payment.id=source.payment_id
    $$;

    -- Checks a stored-form Refund correction against the current state and returns what the draft
    -- records: the Lease, the Invoice's Customer, the correction, the sources it releases (whole
    -- sources, newest first, each with its released amount; a Deposit application also with its
    -- whole amount, because it is reversed whole) and the source revision. Sub-slice 10c-2a-3: a
    -- line a Deposit application paid is no longer refused. An unknown Settlement, Invoice or line
    -- P0002; a state the correction does not allow 55000.
    CREATE OR REPLACE FUNCTION app.settlement_refund_plan(p_property uuid,p_settlement uuid,p_refund jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_invoice app.invoices%ROWTYPE; v_line uuid;
        v_amount bigint; v_remaining bigint; v_release bigint; v_source jsonb;
        v_released jsonb:='[]'::jsonb;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT * INTO v_invoice FROM app.invoices
        WHERE id=(p_refund->>'invoice_id')::uuid AND lease_id=v_settlement.lease_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The corrected Invoice is not an Invoice of this Final Settlement'
                USING ERRCODE='P0002'; END IF;
        IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
            RAISE EXCEPTION 'The corrected Invoice is not an issued obligation of this Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT line.id INTO v_line FROM app.invoice_lines line
        WHERE line.id=(p_refund->>'invoice_line_id')::uuid AND line.invoice_id=v_invoice.id;
        IF NOT FOUND THEN RAISE EXCEPTION 'Invoice line was not found' USING ERRCODE='P0002'; END IF;
        v_amount:=(p_refund->>'amount_usd_cents')::bigint;
        IF v_amount>app.invoice_adjusted_line_obligation(v_line) THEN
            RAISE EXCEPTION 'The Refund correction exceeds the charge on the line'
                USING ERRCODE='55000'; END IF;
        -- Design note: a REFUND always releases paid value; removing only unpaid value is a reduction.
        v_remaining:=v_amount-app.invoice_line_outstanding(v_line);
        IF v_remaining<=0 THEN
            RAISE EXCEPTION 'The Refund correction releases no paid value; an unpaid charge is removed by a charge reduction'
                USING ERRCODE='55000'; END IF;
        -- BR-REFUND-014: an active Refund method (as the Final Settlement draft).
        PERFORM 1 FROM app.refund_methods WHERE id=(p_refund->>'refund_method_id')::uuid AND active;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        -- Whole sources, newest first, until the paid part is covered (migration 67, Q-41 answer 2;
        -- a Deposit application too, sub-slice 10c-2a-3).
        FOR v_source IN SELECT value FROM jsonb_array_elements(
            app.settlement_refund_line_sources(v_invoice.id,v_line))
        LOOP
            EXIT WHEN v_remaining<=0;
            v_release:=LEAST((v_source->>'on_line_usd_cents')::bigint,v_remaining);
            v_released:=v_released||jsonb_build_array((v_source-'on_line_usd_cents'-'at')
                ||CASE WHEN v_source->>'kind'='DEPOSIT_APPLICATION'
                    THEN jsonb_build_object('application_usd_cents',v_source->'on_line_usd_cents')
                    ELSE '{{}}'::jsonb END
                ||jsonb_build_object('released_usd_cents',v_release));
            v_remaining:=v_remaining-v_release;
        END LOOP;
        IF v_remaining>0 THEN
            RAISE EXCEPTION 'Credit excess exceeds the applied value of the line' USING ERRCODE='23514';
        END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,'customer_id',v_invoice.customer_id,
            'refund',p_refund,'released_sources',v_released,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_refund_source_state(p_settlement,v_invoice.id,v_line)::text,
                'UTF8')),'hex'));
    END $$;

    -- The overlay of a Refund correction's release for the shared DL-032 step (sub-slice 10c-2a-2):
    -- the corrected line owes the rests of its released Deposit applications (a Deposit application
    -- is reversed whole; Payment and Credit rests are re-posted); each Deposit gets back the whole
    -- applications released from it; each released Payment allocation becomes Credit of the Invoice
    -- Customer, keyed by the allocation (BR-CREDIT-014); each released Credit application gives value
    -- back to its Credit (BR-CREDIT-008).
    CREATE FUNCTION app.settlement_refund_overlay(p_released jsonb,p_line uuid)
    RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object(
            'obligations',jsonb_build_object('INVOICE_LINE:' || p_line::text,
                COALESCE((SELECT sum((source->>'application_usd_cents')::bigint-(source->>'released_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_released) source
                    WHERE source->>'kind'='DEPOSIT_APPLICATION'),0)),
            'deposits',COALESCE((SELECT jsonb_object_agg(deposit.id,deposit.total) FROM (
                    SELECT source->>'deposit_id' AS id,sum((source->>'application_usd_cents')::bigint) AS total
                    FROM jsonb_array_elements(p_released) source
                    WHERE source->>'kind'='DEPOSIT_APPLICATION' GROUP BY 1) deposit),'{{}}'::jsonb),
            'credits',COALESCE((SELECT jsonb_object_agg(credit.key,jsonb_build_object(
                    'customer_id',credit.customer,'add_usd_cents',credit.total,
                    'released_payment_allocation_id',credit.allocation)) FROM (
                    SELECT CASE WHEN source->>'kind'='PAYMENT_ALLOCATION' THEN source->>'id'
                            ELSE source->>'credit_id' END AS key,
                        min(source->>'recipient_customer_id') AS customer,
                        sum((source->>'released_usd_cents')::bigint) AS total,
                        min(CASE WHEN source->>'kind'='PAYMENT_ALLOCATION' THEN source->>'id' END) AS allocation
                    FROM jsonb_array_elements(p_released) source
                    WHERE source->>'kind' IN ('PAYMENT_ALLOCATION','CREDIT_APPLICATION') GROUP BY 1) credit),
                '{{}}'::jsonb))
    $$;

    -- Staff record a Refund correction draft (final_settlements.prepare); it has no financial
    -- effect until a financial.approve holder confirms it. Sub-slice 10c-2a-3: the draft also keeps
    -- the staff's DL-032 plan, the overlay of the release and the plan check's result (10c-2a-2).
    CREATE OR REPLACE FUNCTION app.record_settlement_refund_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_refund jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
        v_steps jsonb; v_overlay jsonb; v_result jsonb; v_choice text;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters: the Adjustment keeps it (as app.adjust_invoice).
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_refund_input(p_refund);
        -- The plan (the Settlement plan format, sub-slice 10c-2a-3); none means nothing is paid
        -- before the Refunds.
        v_steps:=COALESCE(p_refund->'plan',jsonb_build_object('steps','[]'::jsonb,'pet_remainder','null'::jsonb));
        IF jsonb_typeof(v_steps) IS DISTINCT FROM 'object' OR jsonb_typeof(v_steps->'steps') IS DISTINCT FROM 'array'
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='REFUND' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'refund'=v_input AND v_existing.payload->'plan'=v_steps
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{{decision,result,transaction_id}}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_refund_plan(p_property,p_settlement,v_input);
        -- One Refund method and reference note per correction (owner answer 1 to the 10c-1b points,
        -- owner answer 3 to Q-2026-10-07-41): every Deposit Refund step uses the draft's.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_steps->'steps') step
            WHERE step->>'kind'='DEPOSIT_REFUNDS'
              AND (app.final_settlement_plan_id(step->'refund_method_id') IS DISTINCT FROM v_input->>'refund_method_id'
                  OR step->'reference_note' IS DISTINCT FROM v_input->'reference_note'))
        THEN RAISE EXCEPTION 'A post-settlement correction has one Refund method, reference note, recipient and agreement'
            USING ERRCODE='22023'; END IF;
        -- Owner answer 3 to Q-2026-10-07-44: the remaining Pet Deposit is used by the Customer's
        -- choice given for this correction; the Final Settlement's choice is not reused.
        IF v_steps->'pet_remainder'->>'basis'='CUSTOMER_CHOICE' THEN
            SELECT draft.payload->'pet_remainder'->>'customer_choice' INTO v_choice
            FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
            WHERE draft.kind='FINAL_SETTLEMENT' AND draft.payload->>'final_settlement_id'=p_settlement::text;
            IF v_choice IS NOT NULL AND v_choice=v_steps->'pet_remainder'->>'customer_choice' THEN
                RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; the Final Settlement''s choice is not reused'
                    USING ERRCODE='55000'; END IF;
            -- One agreement per correction (review round 1): nor the choice of an earlier confirmed
            -- correction of this Settlement. The database compares the recorded text only.
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
        -- The shared step's check on the state after the release (sub-slice 10c-2a-2).
        v_overlay:=app.settlement_refund_overlay(v_plan->'released_sources',(v_input->>'invoice_line_id')::uuid);
        v_result:=app.settlement_correction_plan_result(p_property,p_actor,p_settlement,v_steps,v_overlay)
            -'source_revision';
        v_payload:=jsonb_build_object('variant','REFUND','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id',
            'refund',v_plan->'refund','released_sources',v_plan->'released_sources',
            'plan',v_steps,'plan_overlay',v_overlay,'plan_result',v_result);
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- What the confirm returns, also for an exact repeat (rebuilt from the stored records). Sub-slice
    -- 10c-2a-3 adds the Deposit application reversals, the step's Credit and Deposit applications,
    -- and the Deposit and agreement of each Refund.
    CREATE OR REPLACE FUNCTION app.settlement_refund_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        -- Sub-slice 10c-2a-3: also the Deposit application reversals and the step's records.
        WITH adjustment AS (
            SELECT adjustment.* FROM app.settlement_correction_effects effect
            JOIN app.invoice_adjustments adjustment ON adjustment.id=effect.invoice_adjustment_id
            WHERE effect.settlement_correction_id=app.settlement_correction_id(p_draft))
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{{decision,result,transaction_id}}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'invoice_adjustment',(SELECT jsonb_build_object('id',adjustment.id,
                    'invoice_id',adjustment.invoice_id,'invoice_line_id',adjustment.invoice_line_id,
                    'adjustment_type',adjustment.adjustment_type,
                    'amount_usd_cents',adjustment.amount_usd_cents,
                    'source_reference',adjustment.source_reference,'reason',adjustment.reason,
                    'occurred_at',adjustment.occurred_at,'actor_id',adjustment.actor_id,
                    'authorization_reference',adjustment.authorization_reference)
                FROM adjustment),
            'released_sources',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'source_kind',release.source_kind,
                    'reversed_payment_allocation_id',release.reversed_payment_allocation_id,
                    'reversed_credit_application_id',release.reversed_credit_application_id,
                    'replacement_payment_allocation_id',release.replacement_payment_allocation_id,
                    'replacement_credit_application_id',release.replacement_credit_application_id,
                    'customer_credit_id',COALESCE(release.customer_credit_id,application.customer_credit_id),
                    'released_usd_cents',release.released_usd_cents)
                    ORDER BY release.created_at,release.id),'[]'::jsonb)
                FROM app.invoice_credit_excess_releases release
                LEFT JOIN app.customer_credit_applications application
                    ON application.id=release.reversed_credit_application_id
                WHERE release.invoice_adjustment_id=(SELECT id FROM adjustment)),
            'deposit_application_reversals',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'id',reversal.id,'deposit_application_id',reversal.deposit_application_id,
                    'deposit_id',application.deposit_id,'amount_usd_cents',application.amount_usd_cents,
                    'occurred_at',reversal.occurred_at) ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_application_reversals reversal ON reversal.id=effect.deposit_application_reversal_id
                JOIN app.deposit_applications application ON application.id=reversal.deposit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'credit_applications',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,
                    'customer_credit_id',application.customer_credit_id,'target_kind',application.target_kind,
                    'invoice_id',application.invoice_id,'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents,
                    'within_invoice_basis',application.within_invoice_basis) ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.customer_credit_applications application ON application.id=effect.customer_credit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)
                  AND application.final_settlement_id IS NOT NULL),
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
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'invoice',app.invoice_resource_snapshot((SELECT invoice_id FROM adjustment)))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- A financial.approve holder confirms a Refund correction. Refusals: an unknown Property,
    -- draft or Settlement P0002/P4501; an inactive or missing approver P4506 or 42501; business
    -- state (a decided draft, an open Settlement, an inactive Refund method) 55000; a draft whose
    -- sources changed since it was recorded P5S02 (stale; it stays pending). Nothing is written
    -- unless everything succeeds. Sub-slice 10c-2a-3: Deposit-paid lines, the Lease row lock and the
    -- shared DL-032 step after the release.
    CREATE OR REPLACE FUNCTION app.confirm_settlement_refund(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_timezone text; v_now timestamptz; v_business_date date;
        v_refund jsonb; v_plan jsonb; v_correction uuid; v_adjustment uuid; v_line uuid;
        v_amount bigint; v_method uuid; v_reference text; v_unit uuid; v_before jsonb;
        v_after jsonb; v_evidence jsonb; v_result jsonb; v_source jsonb;
        v_released bigint; v_new uuid; v_credit uuid; v_recipient uuid; v_batch uuid;
        v_at timestamptz; v_trace jsonb; v_rest bigint; v_refund_id uuid; v_step jsonb;
        v_left jsonb:='{{}}'::jsonb; v_pay bigint;
        v_allocation app.payment_allocations%ROWTYPE;
        v_application app.customer_credit_applications%ROWTYPE;
        v_paid jsonb:='[]'::jsonb; v_refunds jsonb:='[]'::jsonb;
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
              AND draft.payload->>'variant'='REFUND' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_refund_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'REFUND'
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
        -- The stored correction passes the recorder's shape check again (as sub-slice 10c-1a).
        v_refund:=app.settlement_refund_input(v_draft.payload->'refund');
        IF v_refund IS DISTINCT FROM v_draft.payload->'refund' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_line:=(v_refund->>'invoice_line_id')::uuid;
        v_amount:=(v_refund->>'amount_usd_cents')::bigint;
        v_method:=(v_refund->>'refund_method_id')::uuid;
        -- Lock order, the 8e-3 order (owner answer 4 to Q-2026-10-07-44; sub-slice 10c-2a-3): the
        -- draft lock (above); the Settlement's draft lock (as app.begin_settlement_correction takes
        -- it); the Lease row FOR UPDATE (10c-1b as committed took no Lease lock; every correction now
        -- takes it here, never FOR SHARE first); then the shared step's locks
        -- (app.lock_settlement_correction_plan), which for a REFUND draft take, each kind in one
        -- id-ordered pass, the Payments of the released sources and of the Credit steps, then their
        -- Credits (as the allocation, Credit application and Refund writers take a Payment, then its
        -- Credit; security review round 2: a separate pass for the released sources could lock
        -- Payments out of id order and deadlock with another Lease's correction or Settlement
        -- confirm that names a Credit of the same Customer), then the Lease's Charges, the Lease's
        -- Invoices in id order with the corrected Invoice FOR UPDATE (security review round 1: no
        -- Invoice before a Charge, as a one-call writer locks a Charge and then its source Invoice),
        -- the Settlement row, and each Deposit's draft lock and row. A source added after the draft
        -- is not locked here, but it changes the source revision, so the draft is stale below. A
        -- detected deadlock (40P01) is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        SELECT * INTO v_invoice FROM app.invoices WHERE id=(v_refund->>'invoice_id')::uuid FOR UPDATE;
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same release; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_refund_source_state(
                v_settlement.id,(v_refund->>'invoice_id')::uuid,v_line)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_refund_plan(p_property,v_settlement.id,v_refund);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
            OR v_plan->'released_sources' IS DISTINCT FROM v_draft.payload->'released_sources'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        -- BR-REFUND-014: the method stays active until the Refunds are written (as sub-slice 8d).
        PERFORM 1 FROM app.refund_methods WHERE id=v_method AND active FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_invoice.lease_id;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_reference:='settlement-correction:' || v_correction::text;
        v_before:=app.invoice_resource_snapshot(v_invoice.id);
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','REFUND');
        -- Phase 1: reverse each released source whole, newest first (migration 67; Q-41 answer 2).
        -- A Settlement Credit application's reversal passes the 8e-2 refusal because it is linked
        -- first; a Deposit application's reversal (sub-slice 10c-2a-1) gives its value back to its
        -- Deposit, dated after the latest events of the Invoice and of the Deposit.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_plan->'released_sources') LOOP
            v_new:=gen_random_uuid();
            IF v_source->>'kind'='PAYMENT_ALLOCATION' THEN
                PERFORM app.link_settlement_correction_effect(v_correction,
                    'payment_allocation_reversal_id',v_new);
                INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(v_new,(v_source->>'id')::uuid,'{RELEASE_REASON}',
                    app.credit_excess_instant(v_invoice.id,NULL),p_actor,'payments.allocations.reverse');
            ELSIF v_source->>'kind'='CREDIT_APPLICATION' THEN
                PERFORM app.link_settlement_correction_effect(v_correction,
                    'credit_application_reversal_id',v_new);
                INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(v_new,(v_source->>'id')::uuid,'{RELEASE_REASON}',
                    app.credit_excess_instant(v_invoice.id,(v_source->>'credit_id')::uuid),p_actor,
                    'credits.applications.reverse');
            ELSE
                PERFORM app.link_settlement_correction_effect(v_correction,
                    'deposit_application_reversal_id',v_new);
                INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(v_new,(v_source->>'id')::uuid,v_draft.reason,
                    GREATEST(app.credit_excess_instant(v_invoice.id,NULL),
                        COALESCE(app.deposit_balance_latest_at((v_source->>'deposit_id')::uuid),'-infinity')
                            +interval '1 microsecond'),
                    p_actor,'financial.approve');
            END IF;
        END LOOP;
        -- The credit Adjustment after the reversals, as app.adjust_invoice writes it; it passes the
        -- 8a-1 refusal only because it is linked to this correction first (owner answer to Q-46).
        v_now:=app.credit_excess_instant(v_invoice.id,NULL);
        v_business_date:=timezone(v_timezone,v_now)::date;
        v_adjustment:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(v_correction,'invoice_adjustment_id',v_adjustment);
        INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,
            amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference)
        VALUES (v_adjustment,v_invoice.id,v_line,'CREDIT',v_amount,v_reference,v_draft.reason,v_now,
            p_actor,'financial.approve');
        -- Phase 2 of migration 67: re-post each Payment allocation's and Credit application's
        -- unreleased rest; released Payment value becomes Customer Credit of the Invoice Customer
        -- (BR-CREDIT-014) and released Credit value returns to its Credit. A Deposit application's
        -- rest is paid again only by the plan's step below; it never becomes Credit.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_plan->'released_sources')
            WHERE value->>'kind' IN ('PAYMENT_ALLOCATION','CREDIT_APPLICATION')
        LOOP
            v_released:=(v_source->>'released_usd_cents')::bigint;
            IF v_source->>'kind'='PAYMENT_ALLOCATION' THEN
                SELECT * INTO STRICT v_allocation FROM app.payment_allocations
                WHERE id=(v_source->>'id')::uuid;
                v_rest:=v_allocation.amount_usd_cents-v_released;
                v_new:=CASE WHEN v_rest>0 THEN gen_random_uuid() END;
                v_credit:=gen_random_uuid();
                INSERT INTO app.invoice_credit_excess_releases(id,invoice_adjustment_id,source_kind,
                    reversed_payment_allocation_id,replacement_payment_allocation_id,customer_credit_id,
                    released_usd_cents,reason,actor_id,created_at)
                VALUES(gen_random_uuid(),v_adjustment,'PAYMENT_ALLOCATION',v_allocation.id,v_new,
                    v_credit,v_released,'{RELEASE_REASON}',p_actor,clock_timestamp());
                IF v_new IS NOT NULL THEN
                    v_at:=app.credit_excess_instant(v_invoice.id,NULL);
                    v_batch:=CASE WHEN v_allocation.proposal_batch_id IS NULL THEN NULL
                        ELSE gen_random_uuid() END;
                    PERFORM app.link_settlement_correction_effect(v_correction,'payment_allocation_id',v_new);
                    INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,proposal_batch_id,
                        between_invoice_sequence,target_kind,invoice_id,late_payment_charge_id,amount_usd_cents,
                        between_invoice_basis,within_invoice_basis,customer_designation_reference,
                        selected_invoice_due_date,selected_invoice_issued_at,selected_invoice_number_snapshot,
                        proposal_generated_at,proposal_trace,posted_at,posted_by,authorization_reference)
                    VALUES(v_new,v_allocation.payment_id,v_allocation.target_customer_id,v_batch,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE 1 END,'INVOICE',v_invoice.id,NULL,
                        v_rest,v_allocation.between_invoice_basis,v_allocation.within_invoice_basis,
                        v_allocation.customer_designation_reference,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.due_date END,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.issued_at END,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.invoice_number END,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE v_at END,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE jsonb_build_object(
                            'reason','{RELEASE_REASON}','replaces_payment_allocation_id',v_allocation.id,
                            'invoice_adjustment_id',v_adjustment) END,
                        v_at,p_actor,'payments.allocate');
                    INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,
                        late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                        proposed_amount_usd_cents,posted_amount_usd_cents,attribution_basis,detail_sequence,
                        calculation_trace)
                    SELECT gen_random_uuid(),v_new,kept.invoice_line_id,NULL,kept.obligation_kind,
                        kept.invoice_line_category_snapshot,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE kept.amount END,kept.amount,
                        kept.attribution_basis,
                        (row_number() OVER (ORDER BY kept.detail_sequence))::smallint,
                        jsonb_build_object('reason','{RELEASE_REASON}','replaces_detail_id',kept.id,
                            'invoice_adjustment_id',v_adjustment)
                    FROM (SELECT detail.*,detail.posted_amount_usd_cents
                            -CASE WHEN detail.invoice_line_id=v_line THEN v_released ELSE 0 END AS amount
                        FROM app.payment_allocation_details detail
                        WHERE detail.payment_allocation_id=v_allocation.id) kept
                    WHERE kept.amount>0;
                END IF;
                INSERT INTO app.customer_credits(id,customer_id,source_payment_id,recognized_usd_cents,
                    customer_authorization_reference,recognized_at,recognized_by,reason,authorization_reference)
                VALUES(v_credit,v_invoice.customer_id,v_allocation.payment_id,v_released,
                    'invoice-adjustment:' || v_adjustment::text,app.credit_excess_instant(v_invoice.id,NULL),
                    p_actor,'{RELEASE_REASON}','credits.recognize');
            ELSE
                SELECT * INTO STRICT v_application FROM app.customer_credit_applications
                WHERE id=(v_source->>'id')::uuid;
                v_rest:=v_application.amount_usd_cents-v_released;
                v_new:=CASE WHEN v_rest>0 THEN gen_random_uuid() END;
                INSERT INTO app.invoice_credit_excess_releases(id,invoice_adjustment_id,source_kind,
                    reversed_credit_application_id,replacement_credit_application_id,
                    released_usd_cents,reason,actor_id,created_at)
                VALUES(gen_random_uuid(),v_adjustment,'CREDIT_APPLICATION',v_application.id,v_new,
                    v_released,'{RELEASE_REASON}',p_actor,clock_timestamp());
                IF v_new IS NOT NULL THEN
                    v_at:=app.credit_excess_instant(v_invoice.id,v_application.customer_credit_id);
                    SELECT jsonb_build_object('reason','{RELEASE_REASON}',
                        'replaces_credit_application_id',v_application.id,
                        'invoice_adjustment_id',v_adjustment,'amount_usd_cents',v_rest,
                        'details',jsonb_agg(jsonb_build_object('invoice_line_id',kept.invoice_line_id,
                            'amount_usd_cents',kept.amount,'attribution_basis',kept.attribution_basis)
                            ORDER BY kept.detail_sequence))
                    INTO v_trace
                    FROM (SELECT detail.*,detail.applied_amount_usd_cents
                            -CASE WHEN detail.invoice_line_id=v_line THEN v_released ELSE 0 END AS amount
                        FROM app.customer_credit_application_details detail
                        WHERE detail.customer_credit_application_id=v_application.id) kept
                    WHERE kept.amount>0;
                    -- The rest is an ordinary Credit application (no Final Settlement link); when it
                    -- re-posts a Settlement Credit application, its one-call reversal stays refused.
                    PERFORM app.link_settlement_correction_effect(v_correction,
                        'customer_credit_application_id',v_new);
                    INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,
                        late_payment_charge_id,final_settlement_id,amount_usd_cents,within_invoice_basis,
                        customer_designation_reference,proposal_generated_at,proposal_trace,occurred_at,
                        actor_id,authorization_reference)
                    VALUES(v_new,v_application.customer_credit_id,'INVOICE',v_invoice.id,NULL,NULL,
                        v_rest,v_application.within_invoice_basis,
                        v_application.customer_designation_reference,
                        CASE WHEN v_application.proposal_trace IS NULL THEN NULL ELSE v_at END,
                        CASE WHEN v_application.proposal_trace IS NULL THEN NULL ELSE v_trace END,
                        v_at,p_actor,'credits.apply');
                    INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,
                        invoice_line_id,late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                        proposed_amount_usd_cents,applied_amount_usd_cents,attribution_basis,detail_sequence,
                        calculation_trace)
                    SELECT gen_random_uuid(),v_new,kept.invoice_line_id,NULL,kept.obligation_kind,
                        kept.invoice_line_category_snapshot,
                        CASE WHEN v_application.proposal_trace IS NULL THEN NULL ELSE kept.amount END,
                        kept.amount,kept.attribution_basis,
                        (row_number() OVER (ORDER BY kept.detail_sequence))::smallint,
                        jsonb_build_object('reason','{RELEASE_REASON}','replaces_detail_id',kept.id,
                            'invoice_adjustment_id',v_adjustment)
                    FROM (SELECT detail.*,detail.applied_amount_usd_cents
                            -CASE WHEN detail.invoice_line_id=v_line THEN v_released ELSE 0 END AS amount
                        FROM app.customer_credit_application_details detail
                        WHERE detail.customer_credit_application_id=v_application.id) kept
                    WHERE kept.amount>0;
                END IF;
                v_credit:=v_application.customer_credit_id;
            END IF;
            v_paid:=v_paid||jsonb_build_array(jsonb_build_object('customer_credit_id',v_credit,
                'released_usd_cents',v_released));
        END LOOP;
        -- The Invoice status, version and time follow, as app.adjust_invoice refreshes them.
        UPDATE app.invoices SET status=app.invoice_application_status(v_invoice.id),
            version=version+1,updated_at=GREATEST(v_now,updated_at),updated_by=p_actor
        WHERE id=v_invoice.id;
        -- The shared DL-032 step (sub-slice 10c-2a-2; owner answers 1 and 2 to Q-2026-10-07-42):
        -- under the same locks, the plan check again on the real state (stale P5S02 otherwise), then
        -- each Customer's Credit, the Deposit applications and the Deposit Refunds of the plan.
        v_step:=app.post_settlement_correction_plan(p_property,p_actor,p_draft);
        -- One Credit Refund per released Payment allocation or Credit application, paid to that
        -- Credit's Customer (BR-CREDIT-014) with the draft's method and note in its own details row
        -- (BR-REFUND-014), for the value left in its Credit after the step and at most what this
        -- correction released to it (owner answer 2 to Q-2026-10-07-42: released Credit first pays
        -- its own Customer's open debt; a Customer with no open debt gets the Refund as before).
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_paid) LOOP
            v_credit:=(v_source->>'customer_credit_id')::uuid;
            v_released:=(v_source->>'released_usd_cents')::bigint;
            IF NOT v_left ? v_credit::text THEN
                v_left:=v_left||jsonb_build_object(v_credit::text,app.credit_available_value(v_credit));
            END IF;
            v_pay:=LEAST(v_released,(v_left->>v_credit::text)::bigint);
            CONTINUE WHEN v_pay<=0;
            v_left:=jsonb_set(v_left,ARRAY[v_credit::text],to_jsonb((v_left->>v_credit::text)::bigint-v_pay));
            SELECT credit.customer_id INTO STRICT v_recipient FROM app.customer_credits credit
            WHERE credit.id=v_credit;
            v_refund_id:=gen_random_uuid();
            v_at:=GREATEST(clock_timestamp(),app.credit_latest_at(v_credit)+interval '1 microsecond');
            PERFORM app.link_settlement_correction_effect(v_correction,'refund_id',v_refund_id);
            INSERT INTO app.settlement_correction_refund_details(refund_id,settlement_correction_id,
                draft_id,refund_method_id,reference_note,recorded_at)
            VALUES(v_refund_id,v_correction,p_draft,v_method,v_refund->>'reference_note',v_at);
            INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_payment_id,
                source_customer_credit_id,usd_accounting_value_cents,refund_currency,refund_amount_minor,
                reason,processed_at,processed_by,authorization_reference)
            VALUES(v_refund_id,'REF-' || v_refund_id::text,v_recipient,NULL,v_credit,v_pay,'USD',
                v_pay,v_draft.reason,v_at,p_actor,'refunds.create');
            v_refunds:=v_refunds||jsonb_build_array(jsonb_build_object('refund_id',v_refund_id,
                'customer_credit_id',v_credit,'recipient_customer_id',v_recipient,
                'amount_usd_cents',v_pay));
        END LOOP;
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing Invoice writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_after:=app.invoice_resource_snapshot(v_invoice.id);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,linked_source_event_id,customer_id,
            lease_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'invoice.adjusted','invoice',
            v_invoice.id,v_draft.reason,'financial.approve',p_property,v_before,v_after,v_correction,
            'API','SUCCEEDED',v_evidence || jsonb_build_object('source_reference',v_reference,
                'invoice_line_id',v_line),
            v_adjustment,v_invoice.customer_id,v_invoice.lease_id);
        v_result:=app.settlement_refund_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{{}}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','REFUND',
                'invoice_adjustment_id',v_adjustment,'invoice_id',v_invoice.id,'invoice_line_id',v_line,
                'customer_id',v_invoice.customer_id,'amount_usd_cents',v_amount,
                'refund_method_id',v_method,'refunds',v_refunds,
                -- Every reversal, re-post and released Credit the generic audits record without
                -- the correction is named here (design note point 2; review round 1), and every
                -- record the shared step wrote (sub-slice 10c-2a-3).
                'released_sources',v_result->'released_sources',
                'deposit_application_reversals',v_result->'deposit_application_reversals',
                'credit_application_ids',v_step->'credit_application_ids',
                'deposit_application_ids',v_step->'deposit_application_ids',
                'deposit_refund_ids',v_step->'refund_ids'),
            v_correction,'API','SUCCEEDED',v_evidence,v_invoice.customer_id,v_invoice.lease_id,v_unit);
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
            raise RuntimeError(
                f"Settlement Deposit Refund correction source contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(DEPOSIT_APPLIED, DEPOSIT_APPLIED_REPLACEMENTS)
    _patch(REFUND_INPUT, REFUND_INPUT_REPLACEMENTS)
    _patch(LOCK_PLAN, LOCK_PLAN_REPLACEMENTS)
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement Deposit Refund correction migration is forward-only")
