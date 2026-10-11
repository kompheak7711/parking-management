# ruff: noqa: E501
"""Correct a wrong Lease Deposit receipt after closure (V1-056 sub-slice 10e-2).

BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-002, BR-AUTH-010; DB-DEP-007, DB-SETTLE-005; owner answer
(a) to Q-2026-10-08-56, answers 1 and 3 to Q-2026-10-11-83, answer (a) to Q-2026-10-11-86, the
Q-2026-10-11-78 rule:

- A Lease Deposit receipt that is wrong while its Payment is real (meant for Rent, the wrong
  Deposit, the wrong amount) is fixed after closure only by a `DEPOSIT_RECEIPT_CORRECTION`, a
  variant of the `SETTLEMENT_CORRECTION` draft kind: staff record it under
  `final_settlements.prepare` with a reason and evidence; only `financial.approve` confirms.
- In one transaction, each record linked to the correction before it is written: each Refund paid
  from the Deposit that is not fully returned is recovered by a charge of its exact net amount to
  the person who received it (the sub-slice 10e-1c writer); the Deposit's applications are
  reversed, newest first, so the debt comes back on its obligations and stays with their
  Customers (BR-SETTLE-016); then the whole receipt is reversed and the Deposit ends empty.
- The freed amount stays unallocated with the Payment: it becomes Customer Credit only with the
  payer's authorization (BR-CREDIT-002, not amended; Q-83 point 1). No Payment reversal, no Credit
  and no DL-032 step. A Deposit with an active forfeiture is refused until a `FORFEITURE_REVERSAL`
  correction runs (Q-83 point 3). The right receipt (the right Deposit or amount) is sub-slice
  10e-2b (Q-2026-10-12-87).

Relaxing changes: the recovery check also accepts this correction; the recovery writer words the
charge for it; the correction lock function gains its branch; the Deposit-application reversal
loop of the returned-Payment helper moves unchanged into a shared internal writer.
"""

from alembic import op
from sqlalchemy import text

revision = "20261124_120"
down_revision = "20261123_119"
branch_labels = None
depends_on = None

SQL = r"""
    -- The shared Deposit-application reversal writer (moved unchanged from the sub-slice 10e-1b
    -- helper): each active application of the given Deposits gives its value back to its Deposit
    -- (sub-slice 10c-2a-1), newest first, dated after the latest events of its target and of its
    -- Deposit, each linked to the correction before it is written.
    CREATE FUNCTION app.write_correction_deposit_application_reversals(p_correction uuid,
        p_approver uuid, p_reason text, p_deposits uuid[], p_at timestamptz)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_at timestamptz; v_row record; v_new uuid;
    BEGIN
        v_at:=p_at;
        FOR v_row IN SELECT application.id,application.deposit_id,application.target_kind,
                COALESCE(application.invoice_id,application.late_payment_charge_id) AS target
            FROM app.deposit_applications application
            WHERE application.deposit_id=ANY(p_deposits)
              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                  WHERE reversal.deposit_application_id=application.id)
            ORDER BY application.occurred_at DESC,application.application_order DESC,application.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_row.target_kind
                    WHEN 'INVOICE_LINE' THEN app.credit_excess_instant(v_row.target,NULL)
                    ELSE app.settlement_late_charge_instant(v_row.target,NULL) END,
                COALESCE(app.deposit_balance_latest_at(v_row.deposit_id),'-infinity')
                    +interval '1 microsecond');
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(p_correction,'deposit_application_reversal_id',v_new);
            INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,occurred_at,
                actor_id,authorization_reference)
            VALUES (v_new,v_row.id,p_reason,v_at,p_approver,'financial.approve');
        END LOOP;
        RETURN v_at;
    END $$;

    -- The correction's input: exactly the receipt and the evidence reference.
    CREATE FUNCTION app.settlement_deposit_receipt_correction_input(p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_receipt text;
    BEGIN
        IF p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
            -- The byte order, whatever the database collation.
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input) key)
                IS DISTINCT FROM ARRAY['deposit_receipt_id','evidence_reference']
            OR jsonb_typeof(p_input->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'evidence_reference',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Deposit receipt correction input is invalid' USING ERRCODE='22023'; END IF;
        v_receipt:=app.final_settlement_plan_id(p_input->'deposit_receipt_id');
        IF v_receipt IS NULL THEN
            RAISE EXCEPTION 'Deposit receipt correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('deposit_receipt_id',v_receipt,
            'evidence_reference',p_input->>'evidence_reference');
    END $$;

    -- What the correction reads: the receipt, its Payment and Deposit, the Deposit's active
    -- applications, the Refunds paid from the Deposit that are not fully returned with the charge
    -- each needs (the sub-slice 10e-1c recoveries of this Deposit only), and the waiting drafts
    -- that name the receipt, the Deposit, its Payment or a recovered Refund. Its digest is the
    -- draft's source revision.
    CREATE FUNCTION app.settlement_deposit_receipt_correction_source(p_property uuid, p_settlement uuid,
        p_receipt uuid, p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        WITH receipt AS (
            SELECT receipt.* FROM app.deposit_receipts receipt
            WHERE receipt.id=p_receipt AND app.deposit_property_id(receipt.deposit_id)=p_property
        ), recoveries AS (
            SELECT COALESCE(jsonb_agg(entry.value ORDER BY entry.position),'[]'::jsonb) AS list
            FROM receipt CROSS JOIN LATERAL jsonb_array_elements(
                app.payment_return_recoveries(p_property,receipt.payment_id))
                WITH ORDINALITY entry(value,position)
            WHERE entry.value->>'source_kind'='DEPOSIT'
              AND entry.value->>'source_id'=receipt.deposit_id::text
        ), named AS (
            SELECT p_receipt AS id
            UNION SELECT receipt.deposit_id FROM receipt
            UNION SELECT receipt.payment_id FROM receipt
            UNION SELECT (entry->>'refund_id')::uuid
            FROM recoveries CROSS JOIN LATERAL jsonb_array_elements(recoveries.list) entry
        )
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'lease_id',settlement.lease_id,
                    'closed_at',settlement.closed_at)
                FROM app.final_settlements settlement
                WHERE settlement.id=p_settlement AND settlement.property_id=p_property),
            'receipt',(SELECT jsonb_build_object('id',receipt.id,'deposit_id',receipt.deposit_id,
                    'payment_id',receipt.payment_id,'amount_usd_cents',receipt.amount_usd_cents,
                    'occurred_at',receipt.occurred_at,
                    'reversed',EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                        WHERE reversal.deposit_receipt_id=receipt.id))
                FROM receipt),
            'payment',(SELECT jsonb_build_object('id',payment.id,'status',payment.status,
                    'payer_customer_id',payment.payer_customer_id)
                FROM app.payments payment JOIN receipt ON receipt.payment_id=payment.id),
            'deposit',(SELECT jsonb_build_object('id',deposit.id,'deposit_type',deposit.deposit_type,
                    'customer_id',deposit.customer_id,'lease_id',deposit.lease_id,
                    'held_usd_cents',app.deposit_held_value_at(deposit.id,'infinity'),
                    'latest_at',app.deposit_balance_latest_at(deposit.id),
                    'active_forfeiture',EXISTS(SELECT 1 FROM app.deposit_dispositions disposition
                        WHERE disposition.deposit_id=deposit.id AND NOT EXISTS(
                            SELECT 1 FROM app.deposit_disposition_reversals reversal
                            WHERE reversal.deposit_disposition_id=disposition.id)),
                    'unresolved_refund',app.deposit_has_unresolved_refund(deposit.id))
                FROM app.deposits deposit JOIN receipt ON receipt.deposit_id=deposit.id),
            'deposit_applications',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',application.id,
                    'final_settlement_id',application.final_settlement_id,
                    'target_kind',application.target_kind,'invoice_id',application.invoice_id,
                    'invoice_line_id',application.invoice_line_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents)
                    ORDER BY application.occurred_at,application.id)
                FROM app.deposit_applications application
                JOIN receipt ON receipt.deposit_id=application.deposit_id
                WHERE NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                    WHERE reversal.deposit_application_id=application.id)),'[]'::jsonb),
            'recoveries',(SELECT recoveries.list FROM recoveries),
            'pending_drafts',COALESCE((SELECT jsonb_agg(draft.id ORDER BY draft.id)
                FROM app.financial_drafts draft
                WHERE draft.property_id=p_property AND draft.id IS DISTINCT FROM p_draft
                  AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                      WHERE decision.draft_id=draft.id)
                  AND EXISTS(SELECT 1 FROM named WHERE strpos(draft.payload::text,named.id::text)>0)),'[]'::jsonb))
    $$;

    -- The refusals (recorder, confirm and the write helper).
    CREATE FUNCTION app.assert_settlement_deposit_receipt_correction_allowed(p_settlement uuid,
        p_lease uuid, p_source jsonb)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF p_source->'receipt' IS NULL OR jsonb_typeof(p_source->'receipt')<>'object' THEN
            RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='P0002'; END IF;
        IF (p_source->'receipt'->>'reversed')::boolean THEN
            RAISE EXCEPTION 'This Deposit receipt is already reversed' USING ERRCODE='55000'; END IF;
        IF p_source->'deposit'->>'lease_id' IS DISTINCT FROM p_lease::text THEN
            RAISE EXCEPTION 'This Deposit receipt is not of a Deposit of this Final Settlement''s Lease'
                USING ERRCODE='55000'; END IF;
        IF p_source->'payment'->>'status' IS DISTINCT FROM 'RECEIVED' THEN
            RAISE EXCEPTION 'Only a received Payment''s Deposit receipt can be corrected'
                USING ERRCODE='55000'; END IF;
        -- Owner answer (a) to Q-2026-10-11-83 point 3: whether the Property still keeps the Deposit
        -- is its own decision (sub-slice 10d).
        IF (p_source->'deposit'->>'active_forfeiture')::boolean THEN
            RAISE EXCEPTION 'The Deposit has an active forfeiture; reverse it with a forfeiture reversal correction first'
                USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposit_applications') application
            WHERE application->>'final_settlement_id' IS DISTINCT FROM p_settlement::text)
        THEN RAISE EXCEPTION 'The Deposit has a Deposit application of another Final Settlement'
            USING ERRCODE='55000'; END IF;
        -- The Q-2026-10-11-78 rule (sub-slice 10e-1c): a Refund paid from the Deposit is recovered
        -- by a charge to the person who received it, except in these cases.
        PERFORM app.assert_payment_return_recoveries_allowed(p_source->'recoveries',p_settlement);
        IF (p_source->'deposit'->>'unresolved_refund')::boolean
            AND jsonb_array_length(p_source->'recoveries')=0
        THEN RAISE EXCEPTION 'A Refund paid from this Deposit has no planned recovery'
            USING ERRCODE='55000'; END IF;
        -- The Deposit ends empty: with its applications reversed and its Refunds recovered it holds
        -- exactly this receipt, which is reversed.
        IF (p_source->'deposit'->>'held_usd_cents')::bigint
                +COALESCE((SELECT sum((application->>'amount_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_source->'deposit_applications') application),0)
                +COALESCE((SELECT sum((recovery->>'amount_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_source->'recoveries') recovery),0)
            IS DISTINCT FROM (p_source->'receipt'->>'amount_usd_cents')::bigint
        THEN RAISE EXCEPTION 'The Deposit would not end empty after this receipt correction'
            USING ERRCODE='55000'; END IF;
        IF jsonb_array_length(p_source->'pending_drafts')>0 THEN
            RAISE EXCEPTION 'A draft that names this Deposit receipt, its Deposit or its Payment is waiting'
                USING ERRCODE='55000'; END IF;
    END $$;

    -- The confirm's and a replay's result. No result shows the decision's transaction id
    -- (sub-slice 10b).
    CREATE FUNCTION app.settlement_deposit_receipt_correction_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        WITH effects AS (
            SELECT effect.* FROM app.settlement_correction_effects effect
            WHERE effect.settlement_correction_id=app.settlement_correction_id(p_draft)
        ), receipt AS (
            SELECT receipt.* FROM app.deposit_receipts receipt
            JOIN app.financial_drafts draft ON draft.id=p_draft
            WHERE receipt.id=app.final_settlement_plan_id(draft.payload->'deposit_receipt_id')::uuid
        )
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'deposit_receipt',(SELECT jsonb_build_object('id',receipt.id,'deposit_id',receipt.deposit_id,
                    'payment_id',receipt.payment_id,'amount_usd_cents',receipt.amount_usd_cents)
                FROM receipt),
            'deposit_receipt_reversal_id',(SELECT deposit_receipt_reversal_id FROM effects
                WHERE deposit_receipt_reversal_id IS NOT NULL),
            'deposit_application_reversal_ids',COALESCE((SELECT jsonb_agg(deposit_application_reversal_id
                    ORDER BY effect_sequence) FROM effects
                WHERE deposit_application_reversal_id IS NOT NULL),'[]'::jsonb),
            'recoveries',COALESCE((SELECT jsonb_agg(app.refund_recovery_json(refund_correction_id)
                    ORDER BY effect_sequence) FROM effects
                WHERE refund_correction_id IS NOT NULL),'[]'::jsonb),
            'deposit',(SELECT jsonb_build_object('id',receipt.deposit_id,
                    'held_usd_cents',app.deposit_held_value_at(receipt.deposit_id,'infinity'))
                FROM receipt),
            'payment',(SELECT jsonb_build_object('id',payment.id,'status',payment.status,
                    'available_usd_cents',app.payment_available_value(payment.id))
                FROM app.payments payment JOIN receipt ON receipt.payment_id=payment.id))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- The write steps. The helper runs the source, digest and refusal check itself (as the
    -- hardened sub-slice 10e-1b helper), so no caller writes without it. Every record is linked to
    -- the correction before it is written, with the draft's reason and the approver as actor.
    CREATE FUNCTION app.post_settlement_deposit_receipt_correction(p_property uuid, p_approver uuid,
        p_draft uuid, p_correction uuid, p_receipt uuid, p_evidence text)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_reason text; v_settlement uuid; v_lease uuid; v_source jsonb; v_at timestamptz;
        v_key text;
    BEGIN
        SELECT draft.reason INTO STRICT v_reason FROM app.financial_drafts draft WHERE draft.id=p_draft;
        SELECT settlement.id,settlement.lease_id INTO STRICT v_settlement,v_lease
        FROM app.settlement_corrections correction
        JOIN app.final_settlements settlement ON settlement.id=correction.final_settlement_id
        WHERE correction.id=p_correction AND correction.correlation_id=p_draft
          AND settlement.property_id=p_property;
        v_source:=app.settlement_deposit_receipt_correction_source(p_property,v_settlement,p_receipt,p_draft);
        IF 'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')
            IS DISTINCT FROM (SELECT draft.source_revision FROM app.financial_drafts draft
                WHERE draft.id=p_draft)
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        PERFORM app.assert_settlement_deposit_receipt_correction_allowed(v_settlement,v_lease,v_source);
        v_at:=clock_timestamp();
        -- The Q-2026-10-11-78 rule: each Refund paid from the Deposit is recovered by a charge to the
        -- person who received it (an EXTRA_CHARGE on this Lease when that person is its signed
        -- Customer, else a charge with no Lease), linked.
        v_at:=app.write_payment_return_recoveries(p_property,p_approver,p_draft,p_correction,
            (v_source->'receipt'->>'payment_id')::uuid,v_source->'recoveries',v_reason,p_evidence,v_at,
            jsonb_build_object('capability','financial.approve','draft_id',p_draft,
                'settlement_correction_id',p_correction,'final_settlement_id',v_settlement,
                'variant','DEPOSIT_RECEIPT_CORRECTION','deposit_receipt_id',p_receipt));
        -- The Deposit's applications, newest first: the debt comes back on its obligations and stays
        -- with their Customers (BR-SETTLE-016).
        v_at:=app.write_correction_deposit_application_reversals(p_correction,p_approver,v_reason,
            ARRAY[(v_source->'receipt'->>'deposit_id')::uuid],v_at);
        -- The whole receipt, dated after the application reversals; the freed amount stays
        -- unallocated with the Payment (owner answer 1 to Q-2026-10-11-83).
        v_key:='settlement-deposit-receipt-correction:' || p_draft::text || ':' || p_receipt::text;
        v_at:=app.write_payment_return_receipt_reversal(p_property,p_approver,p_correction,p_receipt,
            v_reason,md5(v_key)::uuid,encode(sha256(convert_to(v_key,'UTF8')),'hex'),v_at);
        RETURN v_at;
    END $$;

    -- Recorder (final_settlements.prepare): the draft has no effect until confirmed.
    CREATE FUNCTION app.record_settlement_deposit_receipt_correction_draft(p_property uuid, p_actor uuid,
        p_draft uuid, p_settlement uuid, p_correction jsonb, p_reason text, p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_input jsonb; v_receipt uuid; v_payment uuid; v_source jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The one-draft-per-Payment lock and the source read rely on READ COMMITTED (as the
        -- sub-slice 10e-1a and 10e-1b recorders).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A Deposit receipt correction draft is recorded at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The reason is at most 500 characters, as every correction's.
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Deposit receipt correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_deposit_receipt_correction_input(p_correction);
        v_receipt:=(v_input->>'deposit_receipt_id')::uuid;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'deposit_receipt_correction'=v_input
            -- No correction result or replay shows the decision's transaction id (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        -- A receipt row never changes, so its Payment is read before the locks. Drafts that move
        -- one Payment's receipts are serialized with its PAYMENT_RETURN and RETURNED_PAYMENT
        -- drafts, so only one may wait.
        SELECT receipt.payment_id INTO v_payment FROM app.deposit_receipts receipt
        WHERE receipt.id=v_receipt AND app.deposit_property_id(receipt.deposit_id)=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='P0002'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('payment-return:' || v_payment::text,0));
        SELECT * INTO v_settlement FROM app.final_settlements WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        v_source:=app.settlement_deposit_receipt_correction_source(p_property,v_settlement.id,v_receipt,p_draft);
        PERFORM app.assert_settlement_deposit_receipt_correction_allowed(v_settlement.id,v_settlement.lease_id,v_source);
        v_payload:=jsonb_build_object('variant','DEPOSIT_RECEIPT_CORRECTION',
            'final_settlement_id',v_settlement.id,'lease_id',v_settlement.lease_id,
            'deposit_receipt_id',v_receipt,'deposit_id',v_source->'receipt'->'deposit_id',
            'payment_id',v_payment,'deposit_receipt_correction',v_input,'source',v_source);
        IF octet_length(v_payload::text)>16000 THEN
            RAISE EXCEPTION 'The Deposit receipt correction draft exceeds the stored draft size of 16000 bytes'
                USING ERRCODE='22023'; END IF;
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,
            'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex'),p_reason);
    END $$;

    -- Confirm (financial.approve, a person, READ COMMITTED).
    CREATE FUNCTION app.confirm_settlement_deposit_receipt_correction(p_property uuid, p_actor uuid,
        p_draft uuid, p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_timezone text; v_input jsonb; v_receipt uuid; v_payment uuid; v_source jsonb; v_correction uuid;
        v_unit uuid; v_at timestamptz; v_result jsonb; v_lock record;
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
              AND draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_deposit_receipt_correction_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'DEPOSIT_RECEIPT_CORRECTION'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks waited
        -- for (as the other correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The stored correction passes the recorder's shape check again.
        v_input:=app.settlement_deposit_receipt_correction_input(v_draft.payload->'deposit_receipt_correction');
        IF v_input IS DISTINCT FROM v_draft.payload->'deposit_receipt_correction'
            OR v_input->'deposit_receipt_id' IS DISTINCT FROM v_draft.payload->'deposit_receipt_id'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_receipt:=(v_input->>'deposit_receipt_id')::uuid;
        SELECT receipt.payment_id INTO v_payment FROM app.deposit_receipts receipt
        WHERE receipt.id=v_receipt AND app.deposit_property_id(receipt.deposit_id)=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='P0002'; END IF;
        -- Lock order: the draft lock (above); the receipt's Payment's return lock (as the sub-slice
        -- 10e-1a and 10e-1b recorders and confirms, before any row lock); then the 8e-3 order, as
        -- the other correction confirms: the Settlement's draft lock, the Lease key lock of the
        -- one-time charge recorder for the Settlement's Lease and every Lease a recovery charge goes
        -- on (one id-ordered pass, as sub-slice 10e-1c), the Lease row FOR UPDATE, then the
        -- correction lock function (its DEPOSIT_RECEIPT_CORRECTION branch: the receipt's Payment in
        -- the Payment pass, the targets of the Deposit's active applications FOR UPDATE in the
        -- Charge and Invoice passes, then the Settlement row and the Deposits);
        -- app.begin_settlement_correction locks the draft row and the Settlement row. A detected
        -- deadlock (40P01) is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('payment-return:' || v_payment::text,0));
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        FOR v_lock IN SELECT lease.lease_id FROM (SELECT v_settlement.lease_id AS lease_id
            UNION SELECT (recovery->>'lease_id')::uuid
            FROM jsonb_array_elements(app.settlement_deposit_receipt_correction_source(p_property,
                v_settlement.id,v_receipt,p_draft)->'recoveries') recovery
            WHERE recovery->>'lease_id' IS NOT NULL) lease ORDER BY lease.lease_id
        LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended('invoice-lease:' || v_lock.lease_id::text,0));
        END LOOP;
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        -- Under the locks, the sources still have the digest the draft recorded; otherwise the
        -- draft is stale and stays pending. Then the recorder's refusals again.
        v_source:=app.settlement_deposit_receipt_correction_source(p_property,v_settlement.id,v_receipt,p_draft);
        IF 'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        PERFORM app.assert_settlement_deposit_receipt_correction_allowed(v_settlement.id,v_settlement.lease_id,v_source);
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_settlement.lease_id;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_at:=app.post_settlement_deposit_receipt_correction(p_property,p_actor,p_draft,v_correction,
            v_receipt,v_input->>'evidence_reference');
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_deposit_receipt_correction_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,
            'final_settlement.correction.confirmed','settlement_correction',v_correction,v_draft.reason,
            'financial.approve',p_property,
            jsonb_build_object('deposit_receipt_id',v_receipt,'payment_id',v_payment,
                'deposit_id',v_source->'receipt'->'deposit_id','status','ACTIVE'),
            (v_result-'draft'-'settlement_correction')||jsonb_build_object(
                'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
                'variant','DEPOSIT_RECEIPT_CORRECTION','deposit_receipt_id',v_receipt,'status','REVERSED'),
            v_correction,'API','SUCCEEDED',
            jsonb_build_object('capability','financial.approve','draft_id',p_draft,
                'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
                'variant','DEPOSIT_RECEIPT_CORRECTION','prepare_capability','final_settlements.prepare',
                'evidence_reference',v_input->>'evidence_reference'),
            (v_source->'deposit'->>'customer_id')::uuid,v_settlement.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""

INTERNAL = (
    "app.write_correction_deposit_application_reversals(uuid,uuid,text,uuid[],timestamp with time zone)",
    "app.settlement_deposit_receipt_correction_input(jsonb)",
    "app.settlement_deposit_receipt_correction_source(uuid,uuid,uuid,uuid)",
    "app.assert_settlement_deposit_receipt_correction_allowed(uuid,uuid,jsonb)",
    "app.settlement_deposit_receipt_correction_result(uuid)",
    "app.post_settlement_deposit_receipt_correction(uuid,uuid,uuid,uuid,uuid,text)",
)
RECORD = "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_deposit_receipt_correction(uuid,uuid,uuid,text)"

RETURNED_PAYMENT_HELPER = "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)"
RETURNED_PAYMENT_HELPER_REPLACEMENTS = (
    (
        "        -- Each Deposit application of a funded Deposit gives its value back to its Deposit\n"
        "        -- (sub-slice 10c-2a-1), dated after the latest events of its target and of its Deposit.\n"
        "        FOR v_row IN SELECT application.id,application.deposit_id,application.target_kind,\n"
        "                COALESCE(application.invoice_id,application.late_payment_charge_id) AS target\n"
        "            FROM app.deposit_applications application\n"
        "            WHERE application.deposit_id IN (SELECT receipt.deposit_id FROM app.deposit_receipts receipt\n"
        "                    WHERE receipt.payment_id=p_payment\n"
        "                      AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                          WHERE reversal.deposit_receipt_id=receipt.id))\n"
        "              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal\n"
        "                  WHERE reversal.deposit_application_id=application.id)\n"
        "            ORDER BY application.occurred_at DESC,application.application_order DESC,application.id DESC\n"
        "        LOOP\n"
        "            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_row.target_kind\n"
        "                    WHEN 'INVOICE_LINE' THEN app.credit_excess_instant(v_row.target,NULL)\n"
        "                    ELSE app.settlement_late_charge_instant(v_row.target,NULL) END,\n"
        "                COALESCE(app.deposit_balance_latest_at(v_row.deposit_id),'-infinity')\n"
        "                    +interval '1 microsecond');\n"
        "            v_new:=gen_random_uuid();\n"
        "            PERFORM app.link_settlement_correction_effect(p_correction,'deposit_application_reversal_id',v_new);\n"
        "            INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,occurred_at,\n"
        "                actor_id,authorization_reference)\n"
        "            VALUES (v_new,v_row.id,v_reason,v_at,p_approver,'financial.approve');\n"
        "        END LOOP;\n",
        "        -- Each Deposit application of a funded Deposit gives its value back to its Deposit\n"
        "        -- (sub-slice 10c-2a-1), dated after the latest events of its target and of its Deposit\n"
        "        -- (the same loop, moved unchanged into the shared writer by sub-slice 10e-2).\n"
        "        v_at:=app.write_correction_deposit_application_reversals(p_correction,p_approver,v_reason,\n"
        "            ARRAY(SELECT DISTINCT receipt.deposit_id FROM app.deposit_receipts receipt\n"
        "                WHERE receipt.payment_id=p_payment\n"
        "                  AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                      WHERE reversal.deposit_receipt_id=receipt.id)),v_at);\n",
    ),
)

RECOVERY_CHECK = "app.refund_recovery_allowed(app.refund_corrections)"
RECOVERY_CHECK_REPLACEMENTS = (
    (
        "                AND EXISTS(SELECT 1 FROM app.payment_returns payment_return\n",
        "                AND (EXISTS(SELECT 1 FROM app.payment_returns payment_return\n",
    ),
    (
        "                                  WHERE reversal.deposit_receipt_id=receipt.id))))\n"
        "                AND EXISTS(SELECT 1 FROM app.authorized_nonrecurring_obligations obligation\n",
        "                                  WHERE reversal.deposit_receipt_id=receipt.id))))\n"
        "                    -- Sub-slice 10e-2: or inside a DEPOSIT_RECEIPT_CORRECTION confirmed by the same\n"
        "                    -- approver in this transaction whose receipt, not yet reversed, is in the\n"
        "                    -- Refund's Deposit; the row is linked to that correction.\n"
        "                    OR EXISTS(SELECT 1 FROM app.settlement_corrections settlement_correction\n"
        "                        JOIN app.financial_drafts draft ON draft.id=settlement_correction.correlation_id\n"
        "                            AND draft.kind='SETTLEMENT_CORRECTION'\n"
        "                            AND draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION'\n"
        "                        JOIN app.financial_draft_decisions decision\n"
        "                            ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'\n"
        "                            AND decision.decided_by=settlement_correction.actor_id\n"
        "                        JOIN app.deposit_receipts receipt\n"
        "                            ON receipt.id=app.final_settlement_plan_id(draft.payload->'deposit_receipt_id')::uuid\n"
        "                        JOIN app.settlement_correction_effects effect\n"
        "                            ON effect.settlement_correction_id=settlement_correction.id\n"
        "                            AND effect.refund_correction_id=(p_correction).id\n"
        "                        WHERE settlement_correction.actor_id=(p_correction).actor_id\n"
        "                          AND decision.result->>'transaction_id'=pg_current_xact_id()::text\n"
        "                          AND decision.decided_at>=transaction_timestamp()\n"
        "                          AND receipt.deposit_id=refund.source_deposit_id\n"
        "                          AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                              WHERE reversal.deposit_receipt_id=receipt.id)))\n"
        "                AND EXISTS(SELECT 1 FROM app.authorized_nonrecurring_obligations obligation\n",
    ),
)

RECOVERY_WRITER = (
    "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,"
    "timestamp with time zone,jsonb)"
)
RECOVERY_WRITER_REPLACEMENTS = (
    (
        "        v_lease uuid;\n    BEGIN\n        v_at:=p_at;\n",
        "        v_lease uuid; v_from text;\n    BEGIN\n        v_at:=p_at;\n"
        "        -- Sub-slice 10e-2: the charge names where the refund money came from.\n"
        "        v_from:=CASE WHEN p_authorization_evidence->>'variant'='DEPOSIT_RECEIPT_CORRECTION'\n"
        "            THEN 'a corrected Deposit receipt' ELSE 'a returned Payment' END;\n",
    ),
    (
        "                'Recovery of Refund ' || v_refund.refund_number || ' paid from a returned Payment',\n"
        "                v_net,NULL,NULL,'A Refund paid from a returned Payment is charged back to its recipient',\n",
        "                'Recovery of Refund ' || v_refund.refund_number || ' paid from ' || v_from,\n"
        "                v_net,NULL,NULL,'A Refund paid from ' || v_from || ' is charged back to its recipient',\n",
    ),
    (
        "                v_timezone,v_at,'Invoice DRAFT created to recover a Refund paid from a returned Payment',\n"
        "                'Invoice issued to recover a Refund paid from a returned Payment');\n",
        "                v_timezone,v_at,'Invoice DRAFT created to recover a Refund paid from ' || v_from,\n"
        "                'Invoice issued to recover a Refund paid from ' || v_from);\n",
    ),
)

LOCK = "app.lock_settlement_correction_plan(uuid)"
LOCK_REPLACEMENTS = (
    (
        "        IF v_draft.payload->>'variant'='RETURNED_PAYMENT' THEN v_steps:='[]'::jsonb; END IF;\n",
        "        IF v_draft.payload->>'variant'='RETURNED_PAYMENT' THEN v_steps:='[]'::jsonb; END IF;\n"
        "        -- Sub-slice 10e-2: nor has a DEPOSIT_RECEIPT_CORRECTION.\n"
        "        IF v_draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION' THEN v_steps:='[]'::jsonb; END IF;\n",
    ),
    (
        "        FOR v_id IN SELECT payment.id FROM (SELECT credit.source_payment_id AS id\n",
        "        -- Sub-slice 10e-2: a DEPOSIT_RECEIPT_CORRECTION's receipt Payment joins the id-ordered\n"
        "        -- Payment pass; the targets of its Deposit's active applications join the Charge and\n"
        "        -- Invoice passes FOR UPDATE; its Deposit joins the Deposit pass. They are read before the\n"
        "        -- Payment pass; a change in between changes the confirm's source digest, so the draft is\n"
        "        -- then stale.\n"
        "        IF v_draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION' THEN\n"
        "            SELECT receipt.payment_id,ARRAY[receipt.deposit_id] INTO v_return_payment,v_return_deposits\n"
        "            FROM app.deposit_receipts receipt\n"
        "            WHERE receipt.id=app.final_settlement_plan_id(v_draft.payload->'deposit_receipt_id')::uuid;\n"
        "            IF v_return_payment IS NOT NULL THEN v_payments:=v_payments||ARRAY[v_return_payment]; END IF;\n"
        "            v_return_deposits:=COALESCE(v_return_deposits,'{}');\n"
        "            SELECT COALESCE(array_agg(DISTINCT application.late_payment_charge_id)\n"
        "                    FILTER (WHERE application.late_payment_charge_id IS NOT NULL),'{}'),\n"
        "                v_target_invoices||COALESCE(array_agg(DISTINCT application.invoice_id)\n"
        "                    FILTER (WHERE application.invoice_id IS NOT NULL),'{}')\n"
        "            INTO v_return_charges,v_target_invoices\n"
        "            FROM app.deposit_applications application\n"
        "            WHERE application.deposit_id=ANY(v_return_deposits)\n"
        "              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal\n"
        "                  WHERE reversal.deposit_application_id=application.id);\n"
        "            v_target_charges:=v_target_charges||v_return_charges;\n"
        "            v_target_invoices:=v_target_invoices||COALESCE((SELECT array_agg(charge.source_invoice_id)\n"
        "                FROM app.late_payment_charges charge WHERE charge.id=ANY(v_return_charges)),'{}');\n"
        "        END IF;\n"
        "        FOR v_id IN SELECT payment.id FROM (SELECT credit.source_payment_id AS id\n",
    ),
)

PATCHES = (
    (RETURNED_PAYMENT_HELPER, RETURNED_PAYMENT_HELPER_REPLACEMENTS),
    (RECOVERY_CHECK, RECOVERY_CHECK_REPLACEMENTS),
    (RECOVERY_WRITER, RECOVERY_WRITER_REPLACEMENTS),
    (LOCK, LOCK_REPLACEMENTS),
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
            raise RuntimeError(f"Deposit receipt correction contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Deposit receipt correction migration is forward-only")
