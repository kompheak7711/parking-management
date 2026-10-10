# ruff: noqa: E501
"""Returned Payment with no closed Final Settlement relied on (V1-056 sub-slice 10e-1a).

BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042, BR-CREDIT-014, BR-AUTH-010; DB-PAY-006, DB-PAY-009;
owner answers 1 and 5 to Q-2026-10-06-36 and answers 2, 3 and 5 to Q-2026-10-06-37:

- A returned Payment (a bounced transfer) is a draft of the new kind PAYMENT_RETURN: a
  payments.reverse holder records it with a reason and an evidence reference; only a
  financial.approve holder confirms it. The draft lists every active allocation, every Customer
  Credit recognized from the Payment with its active applications, and every active Deposit
  receipt, so the approver sees which debt comes back and on whose ledger.
- In one transaction the confirm writes the decision, one app.payment_returns row (DB-PAY-009),
  then the reversals of the Credit applications, the Credits, the allocations and the Deposit
  receipts, and the Payment reversal. The debt comes back on its obligations and stays with
  their Customers; the Payment row and its Receipt never change.
- The slice 7 refusals (a moved allocation; a Credit released from a moved allocation) and the
  sub-slice 8g refusal (a Credit released to a Customer other than the payer) let a reversal of
  that Payment's record through only while a payment_returns row of that Payment, confirmed in
  this transaction, exists (never a session setting). This ends both lasting blocks.
- Owner answer 5 to Q-2026-10-06-37: a record that a closed Final Settlement relied on (an
  allocation or Credit application on that Lease's obligations made at or before the closure, a
  Final Settlement Credit application, a record linked to a post-settlement correction, a Credit
  released by such a correction, a Credit that the Settlement or such a correction used also when
  that use was later reversed or released, a Deposit receipt of that Lease) is refused here
  (55000); it is returned through the RETURNED_PAYMENT correction of that Settlement (sub-slice
  10e-1b).
- Refused until the owner answers Q-2026-10-10-72: a Refund paid from the Payment's value that is
  not fully returned; a Deposit it funded with an active forfeiture (staff first reverse it).
  Refused as well: a Deposit it funded with an active Deposit application, and a waiting draft
  that names the Payment or one of its records.

Relaxing changes: the draft kind, preparer and WITHDRAWN checks gain PAYMENT_RETURN and
payments.reverse; three refusals gain the return pass. New table and functions otherwise.
"""

from alembic import op
from sqlalchemy import text

revision = "20261120_116"
down_revision = "20261119_115"
branch_labels = None
depends_on = None

TABLE = r"""
    -- DB-PAY-009: one row per returned Payment, written only by the confirm below.
    CREATE TABLE app.payment_returns (
        id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
        property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
        payment_id uuid NOT NULL UNIQUE REFERENCES app.payments(id) ON DELETE RESTRICT,
        draft_id uuid NOT NULL UNIQUE REFERENCES app.financial_drafts(id) ON DELETE RESTRICT,
        -- The RETURNED_PAYMENT correction (sub-slice 10e-1b); always NULL until then.
        settlement_correction_id uuid UNIQUE
            REFERENCES app.settlement_corrections(id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason=btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
        occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
        actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
        authorization_reference text NOT NULL CHECK (authorization_reference='financial.approve')
    );

    CREATE FUNCTION app.reject_payment_return_mutation()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        RAISE EXCEPTION 'Payment returns are append-only' USING ERRCODE='55000';
    END $$;

    -- The row names a received Payment of the Property and a PAYMENT_RETURN draft of that Payment
    -- with the same reason; the actor is an active financial actor; the time is not before the
    -- Payment and not later than the clock plus 5 seconds.
    CREATE FUNCTION app.validate_payment_return()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_payment app.payments%ROWTYPE; v_draft app.financial_drafts%ROWTYPE;
    BEGIN
        SELECT * INTO v_payment FROM app.payments WHERE id=NEW.payment_id;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=NEW.draft_id;
        IF v_payment.id IS NULL OR v_payment.property_id<>NEW.property_id
            OR v_payment.status<>'RECEIVED'
            OR v_draft.id IS NULL OR v_draft.property_id<>NEW.property_id
            OR v_draft.kind<>'PAYMENT_RETURN' OR v_draft.prepare_capability<>'payments.reverse'
            OR v_draft.payload->>'payment_id' IS DISTINCT FROM NEW.payment_id::text
            OR v_draft.reason<>NEW.reason
            OR NEW.settlement_correction_id IS NOT NULL
            OR NEW.occurred_at<v_payment.confirmed_at
            OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
        THEN RAISE EXCEPTION 'Payment return does not match its Payment and draft' USING ERRCODE='23514'; END IF;
        PERFORM app.assert_active_financial_actor(NEW.actor_id,NEW.property_id);
        RETURN NEW;
    END $$;

    -- At commit: the draft is CONFIRMED by the row's actor in this transaction (the decision's
    -- transaction id, sub-slice 10a) and the Payment is REVERSED.
    CREATE FUNCTION app.assert_payment_return_confirmed()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
            WHERE decision.draft_id=NEW.draft_id AND decision.decision='CONFIRMED'
              AND decision.decided_by=NEW.actor_id
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp())
        THEN RAISE EXCEPTION 'A Payment return needs its draft confirmed in the same transaction'
            USING ERRCODE='42501'; END IF;
        IF NOT EXISTS(SELECT 1 FROM app.payments WHERE id=NEW.payment_id AND status='REVERSED') THEN
            RAISE EXCEPTION 'A Payment return reverses its Payment' USING ERRCODE='23514'; END IF;
        RETURN NULL;
    END $$;

    CREATE TRIGGER payment_returns_validate BEFORE INSERT ON app.payment_returns
        FOR EACH ROW EXECUTE FUNCTION app.validate_payment_return();
    CREATE CONSTRAINT TRIGGER payment_returns_confirmed AFTER INSERT ON app.payment_returns
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.assert_payment_return_confirmed();
    CREATE TRIGGER payment_returns_immutable BEFORE UPDATE OR DELETE ON app.payment_returns
        FOR EACH ROW EXECUTE FUNCTION app.reject_payment_return_mutation();
    CREATE TRIGGER payment_returns_no_truncate BEFORE TRUNCATE ON app.payment_returns
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_payment_return_mutation();
"""

SQL = r"""
    -- True only while a payment_returns row of that Payment exists whose draft was CONFIRMED in
    -- this transaction (the same test as app.settlement_correction_linked); never NULL.
    CREATE FUNCTION app.payment_return_in_transaction(p_payment uuid)
    RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT EXISTS(SELECT 1 FROM app.payment_returns payment_return
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=payment_return.draft_id AND decision.decision='CONFIRMED'
                AND decision.decided_by=payment_return.actor_id
            WHERE payment_return.payment_id=p_payment
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp())
    $$;

    -- What a returned Payment would undo, and what it depends on: the Payment; its active
    -- allocations; its Credits that are not reversed, with their active applications; its active
    -- Deposit receipts and their Deposits; the records a closed Final Settlement relied on; and the
    -- pending drafts (other than p_draft) whose payload names the Payment or one of those records.
    CREATE FUNCTION app.payment_return_source(p_property uuid,p_payment uuid,p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        WITH payment AS (
            SELECT payment.* FROM app.payments payment
            WHERE payment.id=p_payment AND payment.property_id=p_property
        ), allocations AS (
            SELECT allocation.*,COALESCE(allocation.invoice_id,charge.source_invoice_id) AS source_invoice_id
            FROM app.payment_allocations allocation
            JOIN payment ON payment.id=allocation.payment_id
            LEFT JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id
            WHERE NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                WHERE reversal.payment_allocation_id=allocation.id)
        ), credits AS (
            SELECT credit.* FROM app.customer_credits credit
            JOIN payment ON payment.id=credit.source_payment_id
            WHERE NOT EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                WHERE reversal.customer_credit_id=credit.id)
        ), applications AS (
            SELECT application.*,COALESCE(application.invoice_id,charge.source_invoice_id) AS source_invoice_id
            FROM app.customer_credit_applications application
            JOIN credits ON credits.id=application.customer_credit_id
            LEFT JOIN app.late_payment_charges charge ON charge.id=application.late_payment_charge_id
            WHERE NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                WHERE reversal.credit_application_id=application.id)
        ), receipts AS (
            SELECT receipt.* FROM app.deposit_receipts receipt
            JOIN payment ON payment.id=receipt.payment_id
            WHERE NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                WHERE reversal.deposit_receipt_id=receipt.id)
        ), relied_on AS (
            -- Owner answer 5 to Q-2026-10-06-37: what a closed Final Settlement relied on.
            SELECT 'PAYMENT_ALLOCATION' AS kind,allocation.id,settlement.id AS final_settlement_id
            FROM allocations allocation
            JOIN app.invoices invoice ON invoice.id=allocation.source_invoice_id
            JOIN app.final_settlements settlement
                ON settlement.lease_id=invoice.lease_id AND settlement.closed_at IS NOT NULL
            WHERE allocation.posted_at<=settlement.closed_at
            UNION SELECT 'PAYMENT_ALLOCATION',allocation.id,correction.final_settlement_id
            FROM allocations allocation
            JOIN app.settlement_correction_effects effect ON effect.payment_allocation_id=allocation.id
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            UNION SELECT 'CREDIT_APPLICATION',application.id,application.final_settlement_id
            FROM applications application WHERE application.final_settlement_id IS NOT NULL
            UNION SELECT 'CREDIT_APPLICATION',application.id,settlement.id
            FROM applications application
            JOIN app.invoices invoice ON invoice.id=application.source_invoice_id
            JOIN app.final_settlements settlement
                ON settlement.lease_id=invoice.lease_id AND settlement.closed_at IS NOT NULL
            WHERE application.occurred_at<=settlement.closed_at
            UNION SELECT 'CREDIT_APPLICATION',application.id,correction.final_settlement_id
            FROM applications application
            JOIN app.settlement_correction_effects effect
                ON effect.customer_credit_application_id=application.id
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            -- A Credit that a post-settlement correction released (sub-slices 10c-1b and 10c-3b).
            UNION SELECT 'CUSTOMER_CREDIT',credit.id,correction.final_settlement_id
            FROM credits credit
            JOIN app.invoice_credit_excess_releases release ON release.customer_credit_id=credit.id
            JOIN app.settlement_correction_effects effect
                ON effect.invoice_adjustment_id=release.invoice_adjustment_id
                OR effect.late_payment_charge_correction_id=release.late_payment_charge_correction_id
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            -- A Credit that a Final Settlement or a correction used, also when that use was later
            -- reversed or released: an application of the Settlement or linked to a correction, an
            -- application whose reversal or release a correction linked, and a Refund of the Credit
            -- or a Refund correction that a correction linked (review round 1 of sub-slice 10e-1a).
            UNION SELECT 'CUSTOMER_CREDIT',credit.id,application.final_settlement_id
            FROM credits credit
            JOIN app.customer_credit_applications application ON application.customer_credit_id=credit.id
            WHERE application.final_settlement_id IS NOT NULL
            UNION SELECT 'CUSTOMER_CREDIT',credit.id,correction.final_settlement_id
            FROM credits credit
            JOIN app.customer_credit_applications application ON application.customer_credit_id=credit.id
            JOIN app.settlement_correction_effects effect
                ON effect.customer_credit_application_id=application.id
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            UNION SELECT 'CUSTOMER_CREDIT',credit.id,correction.final_settlement_id
            FROM credits credit
            JOIN app.customer_credit_applications application ON application.customer_credit_id=credit.id
            JOIN app.customer_credit_application_reversals reversal
                ON reversal.credit_application_id=application.id
            JOIN app.settlement_correction_effects effect ON effect.credit_application_reversal_id=reversal.id
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            UNION SELECT 'CUSTOMER_CREDIT',credit.id,correction.final_settlement_id
            FROM credits credit
            JOIN app.customer_credit_applications application ON application.customer_credit_id=credit.id
            JOIN app.invoice_credit_excess_releases release
                ON release.reversed_credit_application_id=application.id
            JOIN app.settlement_correction_effects effect
                ON effect.invoice_adjustment_id=release.invoice_adjustment_id
                OR effect.late_payment_charge_correction_id=release.late_payment_charge_correction_id
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            UNION SELECT 'CUSTOMER_CREDIT',credit.id,correction.final_settlement_id
            FROM credits credit
            JOIN app.refunds refund ON refund.source_customer_credit_id=credit.id
            JOIN app.settlement_correction_effects effect ON effect.refund_id=refund.id
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            UNION SELECT 'CUSTOMER_CREDIT',credit.id,correction.final_settlement_id
            FROM credits credit
            JOIN app.refunds refund ON refund.source_customer_credit_id=credit.id
            JOIN app.refund_corrections refund_correction ON refund_correction.refund_id=refund.id
            JOIN app.settlement_correction_effects effect
                ON effect.refund_correction_id=refund_correction.id
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            UNION SELECT 'DEPOSIT_RECEIPT',receipt.id,settlement.id
            FROM receipts receipt
            JOIN app.deposits deposit ON deposit.id=receipt.deposit_id
            JOIN app.final_settlements settlement
                ON settlement.lease_id=deposit.lease_id AND settlement.closed_at IS NOT NULL
        ), named AS (
            SELECT p_payment AS id
            UNION SELECT id FROM allocations UNION SELECT id FROM credits
            UNION SELECT DISTINCT deposit_id FROM receipts
        )
        SELECT jsonb_build_object(
            'payment',(SELECT jsonb_build_object('id',payment.id,'status',payment.status,
                    'payer_customer_id',payment.payer_customer_id,
                    'payment_scope_kind',payment.payment_scope_kind,
                    'usd_accounting_value_cents',payment.usd_accounting_value_cents,
                    'refunded_usd_cents',app.payment_refunded_value_at(payment.id,'infinity'))
                FROM payment),
            'allocations',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',allocation.id,
                    'target_kind',allocation.target_kind,'invoice_id',allocation.invoice_id,
                    'late_payment_charge_id',allocation.late_payment_charge_id,
                    'customer_id',allocation.target_customer_id,
                    'amount_usd_cents',allocation.amount_usd_cents,
                    'between_invoice_basis',allocation.between_invoice_basis)
                    ORDER BY allocation.posted_at,allocation.id) FROM allocations allocation),'[]'::jsonb),
            'credits',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',credit.id,
                    'customer_id',credit.customer_id,'recognized_usd_cents',credit.recognized_usd_cents,
                    'available_usd_cents',app.credit_available_value(credit.id),
                    'refunded_usd_cents',app.credit_refunded_value_at(credit.id,'infinity'),
                    'applications',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',application.id,
                            'target_kind',application.target_kind,'invoice_id',application.invoice_id,
                            'late_payment_charge_id',application.late_payment_charge_id,
                            'amount_usd_cents',application.amount_usd_cents)
                            ORDER BY application.occurred_at,application.id)
                        FROM applications application WHERE application.customer_credit_id=credit.id),'[]'::jsonb))
                    ORDER BY credit.recognized_at,credit.id) FROM credits credit),'[]'::jsonb),
            'receipts',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',receipt.id,
                    'deposit_id',receipt.deposit_id,'amount_usd_cents',receipt.amount_usd_cents)
                    ORDER BY receipt.occurred_at,receipt.id) FROM receipts receipt),'[]'::jsonb),
            'deposits',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',deposit.id,
                    'held_usd_cents',app.deposit_held_value_at(deposit.id,'infinity'),
                    'latest_at',app.deposit_balance_latest_at(deposit.id),
                    'active_forfeiture',EXISTS(SELECT 1 FROM app.deposit_dispositions disposition
                        WHERE disposition.deposit_id=deposit.id AND NOT EXISTS(
                            SELECT 1 FROM app.deposit_disposition_reversals reversal
                            WHERE reversal.deposit_disposition_id=disposition.id)),
                    'unresolved_refund',app.deposit_has_unresolved_refund(deposit.id),
                    'active_application',app.deposit_has_active_application(deposit.id))
                    ORDER BY deposit.id)
                FROM app.deposits deposit WHERE deposit.id IN (SELECT deposit_id FROM receipts)),'[]'::jsonb),
            'relied_on',COALESCE((SELECT jsonb_agg(jsonb_build_object('kind',relied.kind,'id',relied.id,
                    'final_settlement_id',relied.final_settlement_id)
                    ORDER BY relied.kind,relied.id,relied.final_settlement_id)
                FROM relied_on relied),'[]'::jsonb),
            'pending_drafts',COALESCE((SELECT jsonb_agg(draft.id ORDER BY draft.id)
                FROM app.financial_drafts draft
                WHERE draft.property_id=p_property AND draft.id IS DISTINCT FROM p_draft
                  AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                      WHERE decision.draft_id=draft.id)
                  AND EXISTS(SELECT 1 FROM named WHERE strpos(draft.payload::text,named.id::text)>0)),'[]'::jsonb))
    $$;

    -- The refusals of a returned Payment on a source state. An unknown Payment P4901; a state the
    -- return does not allow 55000 (a conflict).
    CREATE FUNCTION app.assert_payment_return_allowed(p_source jsonb)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF p_source->'payment' IS NULL OR jsonb_typeof(p_source->'payment')<>'object' THEN
            RAISE EXCEPTION 'Payment not found' USING ERRCODE='P4901'; END IF;
        IF p_source->'payment'->>'status' IS DISTINCT FROM 'RECEIVED' THEN
            RAISE EXCEPTION 'Only a received Payment can be returned' USING ERRCODE='55000'; END IF;
        IF jsonb_array_length(p_source->'relied_on')>0 THEN
            RAISE EXCEPTION 'A closed Final Settlement relied on this Payment''s records; return it through a correction of that Final Settlement'
                USING ERRCODE='55000'; END IF;
        -- Q-2026-10-10-72 point 1: money paid out from the returned value is not undone here.
        IF (p_source->'payment'->>'refunded_usd_cents')::bigint<>0
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'credits') credit
                WHERE (credit->>'refunded_usd_cents')::bigint<>0)
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit
                WHERE (deposit->>'unresolved_refund')::boolean)
        THEN RAISE EXCEPTION 'A Refund paid from this Payment''s value is not fully returned'
            USING ERRCODE='55000'; END IF;
        -- Q-2026-10-10-72 point 2: before closure staff first reverse the forfeiture.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit
            WHERE (deposit->>'active_forfeiture')::boolean)
        THEN RAISE EXCEPTION 'A Deposit this Payment funded has an active forfeiture; reverse the forfeiture first'
            USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit
            WHERE (deposit->>'active_application')::boolean)
        THEN RAISE EXCEPTION 'A Deposit this Payment funded has an active Deposit application'
            USING ERRCODE='55000'; END IF;
        IF jsonb_array_length(p_source->'pending_drafts')>0 THEN
            RAISE EXCEPTION 'A draft that names this Payment or one of its records is waiting'
                USING ERRCODE='55000'; END IF;
    END $$;

    -- The command key of one receipt reversal written by a return confirm.
    CREATE FUNCTION app.payment_return_receipt_key(p_draft uuid,p_receipt uuid)
    RETURNS uuid LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT md5('payment-return:' || p_draft::text || ':' || p_receipt::text)::uuid
    $$;

    -- The result of a confirmed return: the row and the reversals its confirm wrote.
    CREATE FUNCTION app.payment_return_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object('payment_return_id',payment_return.id,'draft_id',payment_return.draft_id,
            'payment_id',payment_return.payment_id,'status',payment.status,'reason',payment_return.reason,
            'occurred_at',payment_return.occurred_at,'actor_id',payment_return.actor_id,
            'authorization_reference',payment_return.authorization_reference,
            'payment_reversal_id',(SELECT reversal.id FROM app.payment_reversals reversal
                WHERE reversal.payment_id=payment_return.payment_id),
            'allocation_reversal_ids',COALESCE((SELECT jsonb_agg(reversal.id ORDER BY reversal.occurred_at,reversal.id)
                FROM app.payment_allocation_reversals reversal
                JOIN app.payment_allocations allocation ON allocation.id=reversal.payment_allocation_id
                WHERE allocation.payment_id=payment_return.payment_id
                  AND reversal.occurred_at>=payment_return.occurred_at
                  AND reversal.actor_id=payment_return.actor_id),'[]'::jsonb),
            'credit_application_reversal_ids',COALESCE((SELECT jsonb_agg(reversal.id ORDER BY reversal.occurred_at,reversal.id)
                FROM app.customer_credit_application_reversals reversal
                JOIN app.customer_credit_applications application ON application.id=reversal.credit_application_id
                JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
                WHERE credit.source_payment_id=payment_return.payment_id
                  AND reversal.occurred_at>=payment_return.occurred_at
                  AND reversal.actor_id=payment_return.actor_id),'[]'::jsonb),
            'credit_reversal_ids',COALESCE((SELECT jsonb_agg(reversal.id ORDER BY reversal.occurred_at,reversal.id)
                FROM app.customer_credit_reversals reversal
                JOIN app.customer_credits credit ON credit.id=reversal.customer_credit_id
                WHERE credit.source_payment_id=payment_return.payment_id
                  AND reversal.occurred_at>=payment_return.occurred_at
                  AND reversal.actor_id=payment_return.actor_id),'[]'::jsonb),
            -- A receipt reversal is stamped with the confirm's statement time (as the 8r confirm),
            -- so it is found by its command key, not by time.
            'deposit_receipt_reversal_ids',COALESCE((SELECT jsonb_agg(reversal.id ORDER BY reversal.occurred_at,reversal.id)
                FROM app.deposit_receipt_reversals reversal
                JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                JOIN app.deposit_commands command
                    ON command.action='deposit.receipt.reverse' AND command.actor_id=payment_return.actor_id
                    AND command.idempotency_key=app.payment_return_receipt_key(payment_return.draft_id,receipt.id)
                WHERE receipt.payment_id=payment_return.payment_id),'[]'::jsonb))
        FROM app.payment_returns payment_return
        JOIN app.payments payment ON payment.id=payment_return.payment_id
        WHERE payment_return.draft_id=p_draft
    $$;

    -- Staff record a returned-Payment draft (payments.reverse); it has no financial effect until a
    -- financial.approve holder confirms it.
    CREATE FUNCTION app.record_payment_return_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_payment uuid,p_return jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_source jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'payments.reverse' THEN
            RAISE EXCEPTION 'Payment return draft authorization is invalid' USING ERRCODE='42501'; END IF;
        -- The one-draft-per-Payment lock and the source read rely on READ COMMITTED (as the receipt
        -- reversal and forfeiture recorders since sub-slices 10c-2b-2a and 10c-2b-2b).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A Payment return draft is recorded at READ COMMITTED' USING ERRCODE='55000'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_payment IS NULL
            OR app.lease_notice_text_valid(p_reason,1000) IS NOT TRUE
            OR p_return IS NULL OR jsonb_typeof(p_return) IS DISTINCT FROM 'object'
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_return) key)
                IS DISTINCT FROM ARRAY['evidence_reference']
            OR jsonb_typeof(p_return->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_return->>'evidence_reference',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Payment return draft input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=jsonb_build_object('payment_id',p_payment,
            'evidence_reference',p_return->>'evidence_reference');
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='PAYMENT_RETURN'
                AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                AND (v_existing.payload-'source')=v_input
            -- No result or replay shows the decision's transaction id (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Payment return draft identity was reused' USING ERRCODE='P5205';
        END IF;
        -- Drafts of one Payment are serialized, so only one may wait.
        PERFORM pg_advisory_xact_lock(hashtextextended('payment-return:' || p_payment::text,0));
        v_source:=app.payment_return_source(p_property,p_payment,p_draft);
        PERFORM app.assert_payment_return_allowed(v_source);
        v_payload:=v_input || jsonb_build_object('source',v_source);
        IF octet_length(v_payload::text)>16000 THEN
            RAISE EXCEPTION 'The return draft exceeds the stored draft size of 16000 bytes (the Payment''s records)'
                USING ERRCODE='22023'; END IF;
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'PAYMENT_RETURN','payments.reverse',
            v_payload,'payment-return:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex'),p_reason);
    END $$;

    -- A financial.approve holder confirms a returned-Payment draft: in one transaction the
    -- decision, the payment_returns row, then the reversals of the Credit applications, the
    -- Credits, the allocations, the Deposit receipts and the Payment. Refusals: an unknown
    -- Property or draft P0002/P4501; an unknown Payment P4901; an inactive or missing approver
    -- P4506 or 42501; business state 55000; a draft whose sources changed P5S02 (stale; it stays
    -- pending). Nothing is written unless everything succeeds.
    CREATE FUNCTION app.confirm_payment_return(p_property uuid,p_actor uuid,p_draft uuid,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_timezone text; v_draft app.financial_drafts%ROWTYPE; v_payment app.payments%ROWTYPE;
        v_source jsonb; v_return uuid; v_at timestamptz; v_row record; v_reversal uuid; v_result jsonb;
        v_charges uuid[]; v_invoices uuid[];
    BEGIN
        v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
        -- BR-AUTH-010: a person confirms; an inactive approver is refused above (P4506).
        IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
            WHERE identity.actor_id=p_actor AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'A Payment return is confirmed only by a human approver'
            USING ERRCODE='42501'; END IF;
        IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
            RAISE EXCEPTION 'Only financial.approve may confirm a Payment return' USING ERRCODE='42501'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' THEN
            RAISE EXCEPTION 'Payment return input is invalid' USING ERRCODE='22023'; END IF;
        -- The serialization of every decision on this draft, then the replay of an exact repeat.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND draft.kind='PAYMENT_RETURN'
              AND decision.decision='CONFIRMED' AND decision.decided_by=p_actor)
        THEN RETURN app.payment_return_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'PAYMENT_RETURN' OR v_draft.prepare_capability<>'payments.reverse'
            OR v_draft.payload->>'payment_id' IS NULL
            OR v_draft.payload->>'payment_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        THEN RAISE EXCEPTION 'Payment return draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks waited
        -- for (as the correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A Payment return is confirmed at READ COMMITTED' USING ERRCODE='55000'; END IF;
        -- Lock order: the draft lock (above); the drafts of this Payment; the Payment (its
        -- serialization row, then the row, as the allocation and Credit validators); its Credits
        -- in id order; the targets of its active allocations and Credit applications in two passes
        -- (as the Settlement confirm): first every Late-payment Charge in id order, then every
        -- Invoice in id order, the Invoice targets and the Charges' source Invoices together; then
        -- every Deposit it funded (the Deposit's forfeiture lock and row, as the 8r confirm). A
        -- detected deadlock (40P01) is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('payment-return:' || (v_draft.payload->>'payment_id'),0));
        PERFORM app.serialize_payment_state((v_draft.payload->>'payment_id')::uuid);
        SELECT * INTO v_payment FROM app.payments
        WHERE id=(v_draft.payload->>'payment_id')::uuid AND property_id=p_property FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'Payment not found' USING ERRCODE='P4901'; END IF;
        PERFORM 1 FROM app.customer_credits WHERE source_payment_id=v_payment.id ORDER BY id FOR UPDATE;
        SELECT COALESCE(array_agg(DISTINCT target.late_payment_charge_id)
                FILTER (WHERE target.late_payment_charge_id IS NOT NULL),'{}'),
            COALESCE(array_agg(DISTINCT target.invoice_id) FILTER (WHERE target.invoice_id IS NOT NULL),'{}')
        INTO v_charges,v_invoices FROM (
            SELECT allocation.invoice_id,allocation.late_payment_charge_id
            FROM app.payment_allocations allocation WHERE allocation.payment_id=v_payment.id
              AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                  WHERE reversal.payment_allocation_id=allocation.id)
            UNION ALL SELECT application.invoice_id,application.late_payment_charge_id
            FROM app.customer_credit_applications application
            JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
            WHERE credit.source_payment_id=v_payment.id
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                  WHERE reversal.credit_application_id=application.id)) target;
        PERFORM 1 FROM app.late_payment_charges WHERE id=ANY(v_charges) ORDER BY id FOR UPDATE;
        v_invoices:=v_invoices||COALESCE((SELECT array_agg(charge.source_invoice_id)
            FROM app.late_payment_charges charge WHERE charge.id=ANY(v_charges)),'{}');
        PERFORM 1 FROM app.invoices WHERE id=ANY(v_invoices) ORDER BY id FOR UPDATE;
        FOR v_row IN SELECT DISTINCT receipt.deposit_id FROM app.deposit_receipts receipt
            WHERE receipt.payment_id=v_payment.id ORDER BY receipt.deposit_id
        LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || v_row.deposit_id::text,0));
            PERFORM 1 FROM app.deposits WHERE id=v_row.deposit_id FOR UPDATE;
        END LOOP;
        -- Under the locks, the sources still have the digest the draft recorded; otherwise the
        -- draft is stale and stays pending. Then the recorder's refusals again.
        v_source:=app.payment_return_source(p_property,v_payment.id,p_draft);
        IF 'payment-return:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The Payment return draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        PERFORM app.assert_payment_return_allowed(v_source);

        -- The decision first (the payment_returns row needs it at commit), then the row; every id
        -- is fresh.
        v_return:=gen_random_uuid();
        PERFORM app.confirm_financial_draft_record(p_property,p_actor,p_draft,'PAYMENT_RETURN',
            jsonb_build_object('payment_return_id',v_return,'payment_id',v_payment.id,
                'transaction_id',pg_current_xact_id()::text),'financial.approve');
        v_at:=GREATEST(clock_timestamp(),v_payment.confirmed_at);
        INSERT INTO app.payment_returns(id,property_id,payment_id,draft_id,settlement_correction_id,
            reason,occurred_at,actor_id,authorization_reference)
        VALUES (v_return,p_property,v_payment.id,p_draft,NULL,v_draft.reason,v_at,p_actor,'financial.approve');
        -- Each reversal with the draft's reason, the approver as actor, its table's own
        -- authorization string and a strictly increasing instant (as app.credit_excess_instant).
        FOR v_row IN SELECT application.id,application.target_kind,application.customer_credit_id,
                COALESCE(application.invoice_id,application.late_payment_charge_id) AS target
            FROM app.customer_credit_applications application
            JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
            WHERE credit.source_payment_id=v_payment.id
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                  WHERE reversal.credit_application_id=application.id)
            ORDER BY application.occurred_at DESC,application.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_row.target_kind
                WHEN 'INVOICE' THEN app.credit_excess_instant(v_row.target,v_row.customer_credit_id)
                ELSE app.settlement_late_charge_instant(v_row.target,v_row.customer_credit_id) END);
            INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,
                occurred_at,actor_id,authorization_reference)
            VALUES (gen_random_uuid(),v_row.id,v_draft.reason,v_at,p_actor,'credits.applications.reverse');
        END LOOP;
        FOR v_row IN SELECT credit.id FROM app.customer_credits credit
            WHERE credit.source_payment_id=v_payment.id
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                  WHERE reversal.customer_credit_id=credit.id)
            ORDER BY credit.recognized_at DESC,credit.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp(),
                app.credit_latest_at(v_row.id)+interval '1 microsecond');
            INSERT INTO app.customer_credit_reversals(id,customer_credit_id,reason,occurred_at,actor_id,
                authorization_reference)
            VALUES (gen_random_uuid(),v_row.id,v_draft.reason,v_at,p_actor,'credits.reverse');
        END LOOP;
        FOR v_row IN SELECT allocation.id,allocation.target_kind,
                COALESCE(allocation.invoice_id,allocation.late_payment_charge_id) AS target
            FROM app.payment_allocations allocation
            WHERE allocation.payment_id=v_payment.id
              AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                  WHERE reversal.payment_allocation_id=allocation.id)
            ORDER BY allocation.posted_at DESC,allocation.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_row.target_kind
                WHEN 'INVOICE' THEN app.credit_excess_instant(v_row.target,NULL)
                ELSE app.settlement_late_charge_instant(v_row.target,NULL) END);
            INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,occurred_at,
                actor_id,authorization_reference)
            VALUES (gen_random_uuid(),v_row.id,v_draft.reason,v_at,p_actor,'payments.allocations.reverse');
        END LOOP;
        -- Each Deposit receipt through the existing reversal function (as the 8r confirm writes it:
        -- deposits.correct, the command record and the deposit.receipt.reversed audit event).
        FOR v_row IN SELECT receipt.id FROM app.deposit_receipts receipt
            WHERE receipt.payment_id=v_payment.id
              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                  WHERE reversal.deposit_receipt_id=receipt.id)
            ORDER BY receipt.occurred_at DESC,receipt.id DESC
        LOOP
            v_reversal:=gen_random_uuid();
            PERFORM app.reverse_deposit_receipt_v2(p_property,p_actor,
                app.payment_return_receipt_key(p_draft,v_row.id),
                encode(sha256(convert_to('payment-return:' || p_draft::text || ':' || v_row.id::text,'UTF8')),'hex'),
                v_reversal,v_row.id,v_draft.reason,'deposits.correct');
        END LOOP;
        -- The Payment last (DB-PAY-006: every use reversed first; dated after every one).
        v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp());
        INSERT INTO app.payment_reversals(id,payment_id,reason,occurred_at,actor_id,authorization_reference)
        VALUES (gen_random_uuid(),v_payment.id,v_draft.reason,v_at,p_actor,'financial.approve');
        -- Every record is written: the deferred checks run now, inside this definer function (as
        -- the existing writers run them).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.payment_return_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,'payment.return.confirmed',
            'payment_return',v_return,v_draft.reason,'financial.approve',p_property,
            jsonb_build_object('payment_id',v_payment.id,'status','RECEIVED'),
            v_result-'reason',p_draft,'API','SUCCEEDED',
            jsonb_build_object('capability','financial.approve','draft_id',p_draft,
                'prepare_capability','payments.reverse',
                'evidence_reference',v_draft.payload->>'evidence_reference'),
            v_payment.payer_customer_id,v_payment.lease_id);
        RETURN v_result;
    END $$;
"""

# Relaxing: a reversal of the returned Payment's record passes the slice 7 and sub-slice 8g
# refusals only while its return is confirmed in this transaction.
PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.validate_wrong_unit_move_reversal()",
        (
            (
                "AND allocation.between_invoice_basis='WRONG_UNIT_MOVE')",
                "AND allocation.between_invoice_basis='WRONG_UNIT_MOVE'\n"
                "                      AND app.payment_return_in_transaction(allocation.payment_id) IS NOT TRUE)",
            ),
        ),
    ),
    (
        "app.validate_moved_credit_reversal()",
        (
            (
                # Inside the EXISTS: its last parenthesis closes the subquery.
                "OR payment.payment_scope_kind<>'NORMAL_CUSTOMER'))",
                "OR payment.payment_scope_kind<>'NORMAL_CUSTOMER')\n"
                "                  AND app.payment_return_in_transaction(credit.source_payment_id) IS NOT TRUE)",
            ),
        ),
    ),
    (
        "app.validate_credit_customer_credit_reversal()",
        (
            (
                "IF app.credit_customer_refund_basis(NEW.customer_credit_id) IS NOT NULL",
                "IF app.credit_customer_refund_basis(NEW.customer_credit_id) IS NOT NULL\n"
                "                AND app.payment_return_in_transaction((SELECT credit.source_payment_id\n"
                "                    FROM app.customer_credits credit WHERE credit.id=NEW.customer_credit_id)) IS NOT TRUE",
            ),
        ),
    ),
    # Relaxing: the capability-scoped draft reads take the reader's preparer capabilities, which
    # are now eight with payments.reverse (the bound was seven since migration 20261019_84).
    (
        "app.financial_draft_resource_by_capability(uuid,uuid,uuid,text[])",
        (
            (
                "cardinality(p_capabilities) NOT BETWEEN 1 AND 7",
                "cardinality(p_capabilities) NOT BETWEEN 1 AND 8",
            ),
        ),
    ),
    (
        "app.list_financial_drafts_by_capability(uuid,uuid,text[],text,integer,timestamp with time zone,uuid)",
        (
            (
                "cardinality(p_capabilities) NOT BETWEEN 1 AND 7",
                "cardinality(p_capabilities) NOT BETWEEN 1 AND 8",
            ),
        ),
    ),
)

INTERNAL = (
    "app.reject_payment_return_mutation()",
    "app.validate_payment_return()",
    "app.assert_payment_return_confirmed()",
    "app.payment_return_in_transaction(uuid)",
    "app.payment_return_source(uuid,uuid,uuid)",
    "app.assert_payment_return_allowed(jsonb)",
    "app.payment_return_result(uuid)",
    "app.payment_return_receipt_key(uuid,uuid)",
)
RECORD = "app.record_payment_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_payment_return(uuid,uuid,uuid,text)"

PREPARERS = (
    "'refunds.create','deposits.dispose','reservation_deposits.dispose',"
    "'reservation_deposits.refund','payments.allocations.reverse',"
    "'final_settlements.prepare','deposits.correct','payments.reverse'"
)


def _single_check(pattern: str) -> str:
    names = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.financial_drafts'::regclass AND contype='c' "
                "AND pg_catalog.pg_get_constraintdef(oid) LIKE :pattern"
            ),
            {"pattern": pattern},
        )
        .scalars()
        .all()
    )
    if len(names) != 1:
        raise RuntimeError(f"Financial draft constraint is not unique: {pattern}")
    return str(names[0])


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
            raise RuntimeError(f"Payment return refusal contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    kind = _single_check("CHECK ((kind = ANY (ARRAY['REFUND'%")
    capability = _single_check("CHECK ((prepare_capability = ANY%")
    kind_capability = _single_check("%kind = 'DEPOSIT_FORFEITURE'%")
    # Relaxing: the draft kind PAYMENT_RETURN, prepared under payments.reverse (owner answer 3 to
    # Q-2026-10-06-37), and its withdrawal by that preparer.
    op.execute(f"""
        ALTER TABLE app.financial_drafts DROP CONSTRAINT {kind};
        ALTER TABLE app.financial_drafts ADD CONSTRAINT {kind} CHECK (kind IN (
            'REFUND','DEPOSIT_FORFEITURE','PAYMENT_MOVE','FINAL_SETTLEMENT','SETTLEMENT_CORRECTION',
            'PAYMENT_RETURN'));
        ALTER TABLE app.financial_drafts DROP CONSTRAINT {capability};
        ALTER TABLE app.financial_drafts ADD CONSTRAINT {capability} CHECK (prepare_capability IN (
            {PREPARERS}));
        ALTER TABLE app.financial_drafts DROP CONSTRAINT {kind_capability};
        ALTER TABLE app.financial_drafts ADD CONSTRAINT {kind_capability} CHECK (
            (kind = 'REFUND' AND prepare_capability IN ('refunds.create','reservation_deposits.refund'))
            OR (kind = 'DEPOSIT_FORFEITURE'
                AND prepare_capability IN ('deposits.dispose','reservation_deposits.dispose','deposits.correct'))
            OR (kind = 'PAYMENT_MOVE' AND prepare_capability = 'payments.allocations.reverse')
            OR (kind IN ('FINAL_SETTLEMENT','SETTLEMENT_CORRECTION')
                AND prepare_capability = 'final_settlements.prepare')
            OR (kind = 'PAYMENT_RETURN' AND prepare_capability = 'payments.reverse'));
        ALTER TABLE app.financial_draft_decisions DROP CONSTRAINT financial_draft_decision_shape;
        ALTER TABLE app.financial_draft_decisions ADD CONSTRAINT financial_draft_decision_shape CHECK (
            (decision = 'CONFIRMED' AND authorization_reference = 'financial.approve'
                AND result IS NOT NULL)
            OR (decision = 'REJECTED' AND authorization_reference = 'financial.approve'
                AND reason IS NOT NULL AND result IS NULL)
            OR (decision = 'WITHDRAWN' AND reason IS NOT NULL AND result IS NULL
                AND authorization_reference IN ({PREPARERS}))
        );
    """)
    op.execute(TABLE)
    op.execute(SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    op.execute(
        "REVOKE ALL ON TABLE app.payment_returns FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Payment return migration is forward-only")
