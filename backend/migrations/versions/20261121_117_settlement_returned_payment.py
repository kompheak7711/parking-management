# ruff: noqa: E501
"""Post-settlement correction: RETURNED_PAYMENT (V1-056 sub-slice 10e-1b).

BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042, BR-CREDIT-014, BR-DEP-023, BR-AUTH-010; DB-PAY-009,
DB-SETTLE-003, DB-SETTLE-005, DB-DEP-006; owner answers 1 and 5 to Q-2026-10-06-36, answers 2, 3
and 5 to Q-2026-10-06-37, answers (a) to Q-2026-10-10-72 points 2 and 3 and (a) to Q-2026-10-10-77:

- A returned Payment (a bounced transfer) whose records a closed Final Settlement relied on is
  returned only through a correction of that Settlement. Staff record it under
  final_settlements.prepare with a reason and an evidence reference; only a financial.approve
  holder confirms it.
- In one transaction the confirm writes the decision, the correction header and the
  payment_returns row (DB-PAY-009) that names the correction, then, each linked to the correction
  before it is written: the Credit application reversals (the Settlement's and the corrections'
  pass the sub-slice 8e-2 refusals by the link), the Credit reversals, the allocation reversals,
  the reversals of the funded Deposits' forfeitures (Q-2026-10-10-72 point 2), the Deposit
  application reversals, the Deposit receipt reversals and the Payment reversal. The debt comes
  back on its obligations and stays with their Customers (BR-SETTLE-016). Each funded Deposit
  ends empty, so there is no DL-032 step, and the Customer does not owe the Deposit amount.
- Refused (55000): a Payment this Settlement did not rely on (the correction of the Settlement that
  did, or else the PAYMENT_RETURN draft, returns it); a record that another closed Final
  Settlement also relied on (Q-2026-10-10-72 point 3, a known limit); a Refund paid from the
  Payment's value that is not fully returned (sub-slice 10e-1c); a funded Deposit's forfeiture
  governed by another Lease; a funded Deposit's application of another Final Settlement; a funded
  Deposit that would still hold money after the return (a Refund paid and fully returned cancels
  out, Q-2026-10-10-77); a waiting draft that names the Payment or one of its records.

Relaxing changes: app.validate_payment_return accepts a RETURNED_PAYMENT correction draft with its
own correction. The correction lock function gains a RETURNED_PAYMENT branch and also locks the
targets and Deposits that branch adds outside the Lease. New functions otherwise.
"""

from alembic import op
from sqlalchemy import text

revision = "20261121_117"
down_revision = "20261120_116"
branch_labels = None
depends_on = None

SQL = r"""
    -- The stored form of a returned-Payment correction: the Payment and an evidence reference (1 to
    -- 500 characters). 22023 otherwise.
    CREATE FUNCTION app.settlement_returned_payment_input(p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_payment text;
    BEGIN
        IF p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
            -- The byte order, whatever the database collation.
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input) key)
                IS DISTINCT FROM ARRAY['evidence_reference','payment_id']
            OR jsonb_typeof(p_input->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'evidence_reference',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Returned-Payment correction input is invalid' USING ERRCODE='22023'; END IF;
        v_payment:=app.final_settlement_plan_id(p_input->'payment_id');
        IF v_payment IS NULL THEN
            RAISE EXCEPTION 'Returned-Payment correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('payment_id',v_payment,
            'evidence_reference',p_input->>'evidence_reference');
    END $$;

    -- What a returned-Payment correction depends on: the sub-slice 10e-1a source of the Payment
    -- (other than p_draft's own waiting state), the Settlement, and the active Deposit applications
    -- and active forfeitures of every Deposit the Payment funded.
    CREATE FUNCTION app.settlement_returned_payment_source(p_property uuid,p_settlement uuid,
        p_payment uuid,p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        WITH funded AS (
            SELECT DISTINCT receipt.deposit_id FROM app.deposit_receipts receipt
            JOIN app.payments payment ON payment.id=receipt.payment_id AND payment.property_id=p_property
            WHERE receipt.payment_id=p_payment
              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                  WHERE reversal.deposit_receipt_id=receipt.id)
        )
        SELECT app.payment_return_source(p_property,p_payment,p_draft)||jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'lease_id',settlement.lease_id,
                    'closed_at',settlement.closed_at)
                FROM app.final_settlements settlement
                WHERE settlement.id=p_settlement AND settlement.property_id=p_property),
            'deposit_applications',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',application.id,
                    'deposit_id',application.deposit_id,
                    'final_settlement_id',application.final_settlement_id,
                    'target_kind',application.target_kind,'invoice_id',application.invoice_id,
                    'invoice_line_id',application.invoice_line_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents)
                    ORDER BY application.occurred_at,application.id)
                FROM app.deposit_applications application
                JOIN funded ON funded.deposit_id=application.deposit_id
                WHERE NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                    WHERE reversal.deposit_application_id=application.id)),'[]'::jsonb),
            'forfeitures',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',disposition.id,
                    'deposit_id',disposition.deposit_id,
                    'governing_lease_id',disposition.governing_lease_id,
                    'amount_usd_cents',disposition.amount_usd_cents)
                    ORDER BY disposition.occurred_at,disposition.id)
                FROM app.deposit_dispositions disposition
                JOIN funded ON funded.deposit_id=disposition.deposit_id
                WHERE NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                    WHERE reversal.deposit_disposition_id=disposition.id)),'[]'::jsonb))
    $$;

    -- The refusals of a returned-Payment correction of p_settlement (whose Lease is p_lease) on a
    -- source state. An unknown Payment P0002; a state the correction does not allow 55000.
    CREATE FUNCTION app.assert_settlement_returned_payment_allowed(p_settlement uuid,p_lease uuid,
        p_source jsonb)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF p_source->'payment' IS NULL OR jsonb_typeof(p_source->'payment')<>'object' THEN
            RAISE EXCEPTION 'Payment was not found' USING ERRCODE='P0002'; END IF;
        IF p_source->'payment'->>'status' IS DISTINCT FROM 'RECEIVED' THEN
            RAISE EXCEPTION 'Only a received Payment can be returned' USING ERRCODE='55000'; END IF;
        -- This Settlement must have relied on the Payment's records: if another closed Settlement
        -- did, its correction returns the Payment; if none did, the PAYMENT_RETURN draft does
        -- (review round 1: the known-limit message only when both relied on them).
        IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'relied_on') relied
            WHERE relied->>'final_settlement_id'=p_settlement::text)
        THEN
            IF jsonb_array_length(p_source->'relied_on')>0 THEN
                RAISE EXCEPTION 'This Final Settlement did not rely on this Payment''s records; return it through a correction of the Final Settlement that did'
                    USING ERRCODE='55000'; END IF;
            RAISE EXCEPTION 'This Final Settlement did not rely on this Payment''s records; return it with a Payment return draft'
                USING ERRCODE='55000';
        END IF;
        -- Owner answer (a) to Q-2026-10-10-72 point 3: one correction belongs to one Settlement, so
        -- a Payment that two closed Final Settlements relied on is refused (a known limit).
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'relied_on') relied
            WHERE relied->>'final_settlement_id' IS DISTINCT FROM p_settlement::text)
        THEN RAISE EXCEPTION 'Another closed Final Settlement relied on this Payment''s records; a Payment that two closed Final Settlements relied on cannot be returned'
            USING ERRCODE='55000'; END IF;
        -- Q-2026-10-10-72 point 1 (sub-slice 10e-1c): money paid out from the returned value.
        IF (p_source->'payment'->>'refunded_usd_cents')::bigint<>0
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'credits') credit
                WHERE (credit->>'refunded_usd_cents')::bigint<>0)
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit
                WHERE (deposit->>'unresolved_refund')::boolean)
        THEN RAISE EXCEPTION 'A Refund paid from this Payment''s value is not fully returned'
            USING ERRCODE='55000'; END IF;
        -- Q-2026-10-10-72 point 2: the correction reverses the forfeitures of this Lease only.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'forfeitures') forfeiture
            WHERE forfeiture->>'governing_lease_id' IS DISTINCT FROM p_lease::text)
        THEN RAISE EXCEPTION 'A Deposit this Payment funded has an active forfeiture outside this Final Settlement''s Lease; reverse the forfeiture first'
            USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposit_applications') application
            WHERE application->>'final_settlement_id' IS DISTINCT FROM p_settlement::text)
        THEN RAISE EXCEPTION 'A Deposit this Payment funded has a Deposit application of another Final Settlement'
            USING ERRCODE='55000'; END IF;
        -- Each funded Deposit ends empty: with its applications and forfeitures reversed it holds
        -- exactly the receipts this Payment funded, which are reversed too.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit
            WHERE (deposit->>'held_usd_cents')::bigint
                +COALESCE((SELECT sum((application->>'amount_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_source->'deposit_applications') application
                    WHERE application->>'deposit_id'=deposit->>'id'),0)
                +COALESCE((SELECT sum((forfeiture->>'amount_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_source->'forfeitures') forfeiture
                    WHERE forfeiture->>'deposit_id'=deposit->>'id'),0)
                <>COALESCE((SELECT sum((receipt->>'amount_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_source->'receipts') receipt
                    WHERE receipt->>'deposit_id'=deposit->>'id'),0))
        THEN RAISE EXCEPTION 'A Deposit this Payment funded would still hold money after the return'
            USING ERRCODE='55000'; END IF;
        IF jsonb_array_length(p_source->'pending_drafts')>0 THEN
            RAISE EXCEPTION 'A draft that names this Payment or one of its records is waiting'
                USING ERRCODE='55000'; END IF;
    END $$;

    -- The result of a confirmed returned-Payment correction: the header, the payment_returns row and
    -- every reversal the correction linked, in link order.
    CREATE FUNCTION app.settlement_returned_payment_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        WITH effects AS (
            SELECT effect.* FROM app.settlement_correction_effects effect
            WHERE effect.settlement_correction_id=app.settlement_correction_id(p_draft)
        )
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'payment_return',(SELECT jsonb_build_object('id',payment_return.id,
                    'payment_id',payment_return.payment_id,'status',payment.status,
                    'settlement_correction_id',payment_return.settlement_correction_id,
                    'reason',payment_return.reason,'occurred_at',payment_return.occurred_at,
                    'actor_id',payment_return.actor_id,
                    'authorization_reference',payment_return.authorization_reference)
                FROM app.payment_returns payment_return
                JOIN app.payments payment ON payment.id=payment_return.payment_id
                WHERE payment_return.draft_id=draft.id),
            'credit_application_reversal_ids',COALESCE((SELECT jsonb_agg(credit_application_reversal_id
                    ORDER BY effect_sequence) FROM effects
                WHERE credit_application_reversal_id IS NOT NULL),'[]'::jsonb),
            'credit_reversal_ids',COALESCE((SELECT jsonb_agg(customer_credit_reversal_id
                    ORDER BY effect_sequence) FROM effects
                WHERE customer_credit_reversal_id IS NOT NULL),'[]'::jsonb),
            'allocation_reversal_ids',COALESCE((SELECT jsonb_agg(payment_allocation_reversal_id
                    ORDER BY effect_sequence) FROM effects
                WHERE payment_allocation_reversal_id IS NOT NULL),'[]'::jsonb),
            'forfeiture_reversal_ids',COALESCE((SELECT jsonb_agg(deposit_disposition_reversal_id
                    ORDER BY effect_sequence) FROM effects
                WHERE deposit_disposition_reversal_id IS NOT NULL),'[]'::jsonb),
            'deposit_application_reversal_ids',COALESCE((SELECT jsonb_agg(deposit_application_reversal_id
                    ORDER BY effect_sequence) FROM effects
                WHERE deposit_application_reversal_id IS NOT NULL),'[]'::jsonb),
            'deposit_receipt_reversal_ids',COALESCE((SELECT jsonb_agg(deposit_receipt_reversal_id
                    ORDER BY effect_sequence) FROM effects
                WHERE deposit_receipt_reversal_id IS NOT NULL),'[]'::jsonb),
            'payment_reversal_id',(SELECT payment_reversal_id FROM effects
                WHERE payment_reversal_id IS NOT NULL))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- The write steps of a returned Payment inside the correction p_correction, under the
    -- confirm's locks and after its checks: the payment_returns row, then, each linked before it
    -- is written, with the draft's reason, the approver as actor and a strictly increasing
    -- instant, the reversals of the Credit applications (newest first), the Credits, the
    -- allocations (newest first), the funded Deposits' forfeitures, their Deposit applications
    -- (newest first), their receipts, and the Payment last. Returns the last instant.
    CREATE FUNCTION app.post_settlement_returned_payment(p_property uuid,p_approver uuid,p_draft uuid,
        p_correction uuid,p_payment uuid,p_evidence text)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_reason text; v_payment app.payments%ROWTYPE; v_at timestamptz; v_row record; v_new uuid;
        v_key text;
    BEGIN
        SELECT draft.reason INTO STRICT v_reason FROM app.financial_drafts draft WHERE draft.id=p_draft;
        SELECT * INTO STRICT v_payment FROM app.payments WHERE id=p_payment AND property_id=p_property;
        v_at:=GREATEST(clock_timestamp(),v_payment.confirmed_at);
        -- DB-PAY-009: the row names the correction; the slice 7 and sub-slice 8g refusals read it
        -- (app.payment_return_in_transaction).
        INSERT INTO app.payment_returns(id,property_id,payment_id,draft_id,settlement_correction_id,
            reason,occurred_at,actor_id,authorization_reference)
        VALUES (gen_random_uuid(),p_property,p_payment,p_draft,p_correction,v_reason,v_at,p_approver,
            'financial.approve');
        FOR v_row IN SELECT application.id,application.target_kind,application.customer_credit_id,
                COALESCE(application.invoice_id,application.late_payment_charge_id) AS target
            FROM app.customer_credit_applications application
            JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
            WHERE credit.source_payment_id=p_payment
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                  WHERE reversal.credit_application_id=application.id)
            ORDER BY application.occurred_at DESC,application.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_row.target_kind
                WHEN 'INVOICE' THEN app.credit_excess_instant(v_row.target,v_row.customer_credit_id)
                ELSE app.settlement_late_charge_instant(v_row.target,v_row.customer_credit_id) END);
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(p_correction,'credit_application_reversal_id',v_new);
            INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,
                occurred_at,actor_id,authorization_reference)
            VALUES (v_new,v_row.id,v_reason,v_at,p_approver,'credits.applications.reverse');
        END LOOP;
        FOR v_row IN SELECT credit.id FROM app.customer_credits credit
            WHERE credit.source_payment_id=p_payment
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                  WHERE reversal.customer_credit_id=credit.id)
            ORDER BY credit.recognized_at DESC,credit.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp(),
                app.credit_latest_at(v_row.id)+interval '1 microsecond');
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(p_correction,'customer_credit_reversal_id',v_new);
            INSERT INTO app.customer_credit_reversals(id,customer_credit_id,reason,occurred_at,actor_id,
                authorization_reference)
            VALUES (v_new,v_row.id,v_reason,v_at,p_approver,'credits.reverse');
        END LOOP;
        FOR v_row IN SELECT allocation.id,allocation.target_kind,
                COALESCE(allocation.invoice_id,allocation.late_payment_charge_id) AS target
            FROM app.payment_allocations allocation
            WHERE allocation.payment_id=p_payment
              AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                  WHERE reversal.payment_allocation_id=allocation.id)
            ORDER BY allocation.posted_at DESC,allocation.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_row.target_kind
                WHEN 'INVOICE' THEN app.credit_excess_instant(v_row.target,NULL)
                ELSE app.settlement_late_charge_instant(v_row.target,NULL) END);
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(p_correction,'payment_allocation_reversal_id',v_new);
            INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,occurred_at,
                actor_id,authorization_reference)
            VALUES (v_new,v_row.id,v_reason,v_at,p_approver,'payments.allocations.reverse');
        END LOOP;
        -- Q-2026-10-10-72 point 2: each forfeiture of a funded Deposit through the existing reversal
        -- function (as sub-slice 10d: the approver as actor, deposits.correct, the draft's reason and
        -- evidence reference, the command record keyed by this draft and the
        -- deposit.disposition.reversed audit); it is stamped with the statement time, before the
        -- Deposit application reversals below.
        FOR v_row IN SELECT disposition.id FROM app.deposit_dispositions disposition
            WHERE disposition.deposit_id IN (SELECT receipt.deposit_id FROM app.deposit_receipts receipt
                    WHERE receipt.payment_id=p_payment
                      AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                          WHERE reversal.deposit_receipt_id=receipt.id))
              AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                  WHERE reversal.deposit_disposition_id=disposition.id)
            ORDER BY disposition.occurred_at DESC,disposition.id DESC
        LOOP
            v_new:=gen_random_uuid();
            v_key:='settlement-returned-payment-forfeiture:' || p_draft::text || ':' || v_row.id::text;
            PERFORM app.link_settlement_correction_effect(p_correction,'deposit_disposition_reversal_id',v_new);
            PERFORM app.reverse_deposit_disposition_v2(p_property,p_approver,md5(v_key)::uuid,
                encode(sha256(convert_to(v_key,'UTF8')),'hex'),v_new,v_row.id,v_reason,p_evidence,
                'deposits.correct');
        END LOOP;
        -- Each Deposit application of a funded Deposit gives its value back to its Deposit
        -- (sub-slice 10c-2a-1), dated after the latest events of its target and of its Deposit.
        FOR v_row IN SELECT application.id,application.deposit_id,application.target_kind,
                COALESCE(application.invoice_id,application.late_payment_charge_id) AS target
            FROM app.deposit_applications application
            WHERE application.deposit_id IN (SELECT receipt.deposit_id FROM app.deposit_receipts receipt
                    WHERE receipt.payment_id=p_payment
                      AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                          WHERE reversal.deposit_receipt_id=receipt.id))
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
            VALUES (v_new,v_row.id,v_reason,v_at,p_approver,'financial.approve');
        END LOOP;
        -- Each receipt with the same record as the existing receipt reversal function writes
        -- (deposits.correct, the command record and the deposit.receipt.reversed audit event), but
        -- dated after the Deposit application reversals: that function stamps the statement time,
        -- which would put the receipt reversal first and make the Deposit's history negative.
        FOR v_row IN SELECT receipt.id,receipt.deposit_id,receipt.occurred_at
            FROM app.deposit_receipts receipt
            WHERE receipt.payment_id=p_payment
              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                  WHERE reversal.deposit_receipt_id=receipt.id)
            ORDER BY receipt.occurred_at DESC,receipt.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp(),v_row.occurred_at,
                COALESCE(app.deposit_balance_latest_at(v_row.deposit_id),'-infinity')
                    +interval '1 microsecond');
            v_new:=gen_random_uuid();
            v_key:='settlement-returned-payment-receipt:' || p_draft::text || ':' || v_row.id::text;
            PERFORM app.link_settlement_correction_effect(p_correction,'deposit_receipt_reversal_id',v_new);
            INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,actor_id,
                authorization_reference)
            VALUES (v_new,v_row.id,v_reason,v_at,p_approver,'deposits.correct');
            PERFORM app.record_deposit_command(p_property,p_approver,'deposit.receipt.reverse',
                md5(v_key)::uuid,encode(sha256(convert_to(v_key,'UTF8')),'hex'),v_row.deposit_id,
                v_reason,'deposits.correct',app.deposit_snapshot(v_row.deposit_id));
            PERFORM app.record_deposit_audit(v_new,'deposit.receipt.reversed','deposit_receipt_reversal',
                v_new,v_row.deposit_id,v_reason,'deposits.correct',p_approver,md5(v_key)::uuid,
                app.deposit_resource_snapshot(v_row.deposit_id),v_row.id);
        END LOOP;
        -- The Payment last (DB-PAY-006: every use reversed first; dated after every one).
        v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp());
        v_new:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(p_correction,'payment_reversal_id',v_new);
        INSERT INTO app.payment_reversals(id,payment_id,reason,occurred_at,actor_id,authorization_reference)
        VALUES (v_new,p_payment,v_reason,v_at,p_approver,'financial.approve');
        RETURN v_at;
    END $$;

    -- Staff record a returned-Payment correction draft (final_settlements.prepare); it has no
    -- financial effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_returned_payment_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_return jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_input jsonb; v_payment uuid; v_source jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The one-draft-per-Payment lock and the source read rely on READ COMMITTED (as the
        -- sub-slice 10e-1a recorder).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A returned-Payment correction draft is recorded at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The reason is at most 500 characters, as every correction's.
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Returned-Payment correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_returned_payment_input(p_return);
        v_payment:=(v_input->>'payment_id')::uuid;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='RETURNED_PAYMENT' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'returned_payment'=v_input
            -- No correction result or replay shows the decision's transaction id (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        -- Drafts that return one Payment are serialized with the PAYMENT_RETURN drafts of it, so only
        -- one may wait.
        PERFORM pg_advisory_xact_lock(hashtextextended('payment-return:' || v_payment::text,0));
        SELECT * INTO v_settlement FROM app.final_settlements WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        v_source:=app.settlement_returned_payment_source(p_property,v_settlement.id,v_payment,p_draft);
        PERFORM app.assert_settlement_returned_payment_allowed(v_settlement.id,v_settlement.lease_id,v_source);
        v_payload:=jsonb_build_object('variant','RETURNED_PAYMENT','final_settlement_id',v_settlement.id,
            'lease_id',v_settlement.lease_id,'payment_id',v_payment,'returned_payment',v_input,
            'source',v_source);
        IF octet_length(v_payload::text)>16000 THEN
            RAISE EXCEPTION 'The returned-Payment correction draft exceeds the stored draft size of 16000 bytes (the Payment''s records)'
                USING ERRCODE='22023'; END IF;
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,
            'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex'),p_reason);
    END $$;

    -- A financial.approve holder confirms a returned-Payment correction: in one transaction the
    -- decision and the header (sub-slice 10a), then the write steps above. Refusals: an unknown
    -- Property, draft, Settlement or Payment P0002/P4501; an inactive or missing approver P4506 or
    -- 42501; business state 55000; a draft whose sources changed P5S02 (stale; it stays pending).
    -- Nothing is written unless everything succeeds.
    CREATE FUNCTION app.confirm_settlement_returned_payment(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_timezone text; v_input jsonb; v_payment uuid; v_payer uuid; v_source jsonb; v_correction uuid;
        v_unit uuid; v_at timestamptz; v_result jsonb;
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
              AND draft.payload->>'variant'='RETURNED_PAYMENT' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_returned_payment_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'RETURNED_PAYMENT'
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
        v_input:=app.settlement_returned_payment_input(v_draft.payload->'returned_payment');
        IF v_input IS DISTINCT FROM v_draft.payload->'returned_payment'
            OR v_input->'payment_id' IS DISTINCT FROM v_draft.payload->'payment_id'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_payment:=(v_input->>'payment_id')::uuid;
        -- Lock order: the draft lock (above); the Payment's return lock (as the sub-slice 10e-1a
        -- recorder and confirm, before any row lock); then the 8e-3 order, as the other correction
        -- confirms: the Settlement's draft lock, the Lease row FOR UPDATE, the correction lock
        -- function (its RETURNED_PAYMENT branch: the Payment, then its Credits, then the targets'
        -- Charges and Invoices FOR UPDATE, also outside the Lease, then the Settlement row and the
        -- Deposits, the funded ones included); then the funded Deposits' active forfeitures FOR
        -- UPDATE in id order (the Deposit before the forfeiture, as the 6b confirm);
        -- app.begin_settlement_correction locks the draft row and the Settlement row. A detected
        -- deadlock (40P01) is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('payment-return:' || v_payment::text,0));
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        PERFORM 1 FROM app.deposit_dispositions disposition
        WHERE disposition.deposit_id IN (SELECT receipt.deposit_id FROM app.deposit_receipts receipt
                WHERE receipt.payment_id=v_payment
                  AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                      WHERE reversal.deposit_receipt_id=receipt.id))
          AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
              WHERE reversal.deposit_disposition_id=disposition.id)
        ORDER BY disposition.id FOR UPDATE;
        -- Under the locks, the sources still have the digest the draft recorded; otherwise the
        -- draft is stale and stays pending. Then the recorder's refusals again.
        v_source:=app.settlement_returned_payment_source(p_property,v_settlement.id,v_payment,p_draft);
        IF 'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        PERFORM app.assert_settlement_returned_payment_allowed(v_settlement.id,v_settlement.lease_id,v_source);
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_settlement.lease_id;
        v_payer:=(v_source->'payment'->>'payer_customer_id')::uuid;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_at:=app.post_settlement_returned_payment(p_property,p_actor,p_draft,v_correction,v_payment,
            v_input->>'evidence_reference');
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_returned_payment_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,
            'final_settlement.correction.confirmed','settlement_correction',v_correction,v_draft.reason,
            'financial.approve',p_property,
            jsonb_build_object('payment_id',v_payment,'status','RECEIVED'),
            (v_result-'draft'-'settlement_correction'-'payment_return')||jsonb_build_object(
                'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
                'variant','RETURNED_PAYMENT','payment_id',v_payment,
                'payment_return_id',v_result->'payment_return'->'id','status','REVERSED'),
            v_correction,'API','SUCCEEDED',
            jsonb_build_object('capability','financial.approve','draft_id',p_draft,
                'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
                'variant','RETURNED_PAYMENT','prepare_capability','final_settlements.prepare',
                'evidence_reference',v_input->>'evidence_reference'),
            v_payer,v_settlement.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    # Relaxing: a payment_returns row also names a RETURNED_PAYMENT correction draft with its own
    # correction (DB-PAY-009, settlement_correction_id).
    (
        "app.validate_payment_return()",
        (
            (
                "            OR v_draft.kind<>'PAYMENT_RETURN' OR v_draft.prepare_capability<>'payments.reverse'\n",
                "            -- Sub-slice 10e-1b: a PAYMENT_RETURN draft with no correction, or a\n"
                "            -- RETURNED_PAYMENT correction draft with the correction it confirms.\n"
                "            OR NOT ((v_draft.kind='PAYMENT_RETURN' AND v_draft.prepare_capability='payments.reverse'\n"
                "                    AND NEW.settlement_correction_id IS NULL)\n"
                "                OR (v_draft.kind='SETTLEMENT_CORRECTION'\n"
                "                    AND v_draft.prepare_capability='final_settlements.prepare'\n"
                "                    AND v_draft.payload->>'variant' IS NOT DISTINCT FROM 'RETURNED_PAYMENT'\n"
                "                    AND NEW.settlement_correction_id IS NOT DISTINCT FROM app.settlement_correction_id(v_draft.id)\n"
                "                    AND EXISTS(SELECT 1 FROM app.settlement_corrections correction\n"
                "                        WHERE correction.id=NEW.settlement_correction_id\n"
                "                          AND correction.correlation_id=v_draft.id)))\n",
            ),
            ("            OR NEW.settlement_correction_id IS NOT NULL\n", ""),
        ),
    ),
    # The correction lock function: a RETURNED_PAYMENT branch, and the Charge, Invoice and Deposit
    # passes also take the targets and Deposits that branch adds outside the Lease (other variants
    # name only the Lease's obligations, so their passes are unchanged).
    (
        "app.lock_settlement_correction_plan(uuid)",
        (
            (
                "        v_payments uuid[]:='{}';\n",
                "        v_payments uuid[]:='{}'; v_return_payment uuid; v_return_charges uuid[]:='{}';\n"
                "        v_return_deposits uuid[]:='{}';\n",
            ),
            (
                "        v_steps:=v_draft.payload->'plan'->'steps';\n",
                "        v_steps:=v_draft.payload->'plan'->'steps';\n"
                "        -- Sub-slice 10e-1b: a RETURNED_PAYMENT correction has no DL-032 plan.\n"
                "        IF v_draft.payload->>'variant'='RETURNED_PAYMENT' THEN v_steps:='[]'::jsonb; END IF;\n",
            ),
            (
                "        FOR v_id IN SELECT payment.id FROM (SELECT credit.source_payment_id AS id\n",
                "        -- Sub-slice 10e-1b: a RETURNED_PAYMENT correction's Payment and its Credits that are\n"
                "        -- not reversed join the id-ordered Payment and Credit passes; the targets of their\n"
                "        -- active records and of the active Deposit applications of the Deposits it funded\n"
                "        -- join the Charge and Invoice passes FOR UPDATE, also outside the Lease; those\n"
                "        -- Deposits join the Deposit pass. They are read before the Payment pass; a change\n"
                "        -- in between changes the confirm's source digest, so the draft is then stale.\n"
                "        IF v_draft.payload->>'variant'='RETURNED_PAYMENT' THEN\n"
                "            v_return_payment:=app.final_settlement_plan_id(v_draft.payload->'payment_id')::uuid;\n"
                "            v_payments:=v_payments||ARRAY[v_return_payment];\n"
                "            SELECT v_credits||COALESCE(array_agg(credit.id),'{}') INTO v_credits\n"
                "            FROM app.customer_credits credit WHERE credit.source_payment_id=v_return_payment\n"
                "              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal\n"
                "                  WHERE reversal.customer_credit_id=credit.id);\n"
                "            SELECT COALESCE(array_agg(DISTINCT receipt.deposit_id),'{}') INTO v_return_deposits\n"
                "            FROM app.deposit_receipts receipt WHERE receipt.payment_id=v_return_payment\n"
                "              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
                "                  WHERE reversal.deposit_receipt_id=receipt.id);\n"
                "            SELECT COALESCE(array_agg(DISTINCT target.charge) FILTER (WHERE target.charge IS NOT NULL),'{}'),\n"
                "                v_target_invoices||COALESCE(array_agg(DISTINCT target.invoice)\n"
                "                    FILTER (WHERE target.invoice IS NOT NULL),'{}')\n"
                "            INTO v_return_charges,v_target_invoices FROM (\n"
                "                SELECT allocation.late_payment_charge_id AS charge,allocation.invoice_id AS invoice\n"
                "                FROM app.payment_allocations allocation WHERE allocation.payment_id=v_return_payment\n"
                "                  AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal\n"
                "                      WHERE reversal.payment_allocation_id=allocation.id)\n"
                "                UNION ALL SELECT application.late_payment_charge_id,application.invoice_id\n"
                "                FROM app.customer_credit_applications application\n"
                "                JOIN app.customer_credits credit ON credit.id=application.customer_credit_id\n"
                "                WHERE credit.source_payment_id=v_return_payment\n"
                "                  AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal\n"
                "                      WHERE reversal.credit_application_id=application.id)\n"
                "                UNION ALL SELECT application.late_payment_charge_id,application.invoice_id\n"
                "                FROM app.deposit_applications application\n"
                "                WHERE application.deposit_id=ANY(v_return_deposits)\n"
                "                  AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal\n"
                "                      WHERE reversal.deposit_application_id=application.id)) target;\n"
                "            v_target_charges:=v_target_charges||v_return_charges;\n"
                "            v_target_invoices:=v_target_invoices||COALESCE((SELECT array_agg(charge.source_invoice_id)\n"
                "                FROM app.late_payment_charges charge WHERE charge.id=ANY(v_return_charges)),'{}');\n"
                "        END IF;\n"
                "        FOR v_id IN SELECT payment.id FROM (SELECT credit.source_payment_id AS id\n",
            ),
            (
                "            WHERE invoice.lease_id=v_lease ORDER BY charge.id\n",
                "            WHERE invoice.lease_id=v_lease OR charge.id=ANY(v_target_charges) ORDER BY charge.id\n",
            ),
            (
                "            WHERE invoice.lease_id=v_lease ORDER BY invoice.id\n",
                "            WHERE invoice.lease_id=v_lease OR invoice.id=ANY(v_target_invoices) ORDER BY invoice.id\n",
            ),
            (
                "        FOR v_id IN SELECT deposit.id FROM app.deposits deposit WHERE deposit.lease_id=v_lease ORDER BY deposit.id\n",
                "        FOR v_id IN SELECT deposit.id FROM app.deposits deposit\n"
                "            WHERE deposit.lease_id=v_lease OR deposit.id=ANY(v_return_deposits) ORDER BY deposit.id\n",
            ),
        ),
    ),
)

INTERNAL = (
    "app.settlement_returned_payment_input(jsonb)",
    "app.settlement_returned_payment_source(uuid,uuid,uuid,uuid)",
    "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)",
    "app.settlement_returned_payment_result(uuid)",
    "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)",
)
RECORD = "app.record_settlement_returned_payment_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_returned_payment(uuid,uuid,uuid,text)"


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
            raise RuntimeError(f"Returned-Payment correction contract changed: {signature}")
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
    raise RuntimeError("Returned-Payment correction migration is forward-only")
