# ruff: noqa: E501
"""Returned Payment: a Refund already paid from its value (V1-056 sub-slice 10e-1c).

BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042, BR-CREDIT-014, BR-REFUND-015, BR-AUTH-010; DB-REFUND-002
(amended), DB-PAY-009, DB-SETTLE-005; owner answer (a) to Q-2026-10-10-72 point 1 and its detail,
owner answers A, B and C to Q-2026-10-11-78, owner answer (a) to Q-2026-10-11-79 and the owner
check of 2026-10-11 on the correction's own receipt reversal:

- A Refund paid from a returned Payment's value (a Refund of the Payment, of one of its Credits or
  of a Deposit it funded) no longer blocks the return. The return writes, before its reversals,
  one RECOVERED_BY_CHARGE Refund correction per Refund that is not fully returned (its whole net
  amount back to the Refund's source on paper; the Refund itself stays, because the money really
  left) and one charge of the same amount to the person who received the refund money: a
  Miscellaneous one-time charge issued in the same confirm, on the Lease the money came from when
  that person is its signed Customer (a Deposit Refund: the Deposit's Lease; a Credit Refund: the
  Lease of the Invoice or Late-payment Charge whose release created the Credit, else the Lease the
  Payment names; a Payment Refund: the Lease the Payment names), otherwise with no Lease. With a
  closed Final Settlement of that Lease the charge is written inside that Settlement's
  RETURNED_PAYMENT correction and linked to it (an EXTRA_CHARGE); every record the correction
  writes is linked.
- Refused (55000): a Refund whose charge Lease has a closed Final Settlement this return cannot
  correct (no correction, or another Settlement's: the Q-2026-10-10-72 point 3 known limit); a
  Reservation outcome Refund (Q-2026-10-11-81); a Refund of a Deposit that also holds another
  Payment's receipt.
- The EXTRA_CHARGE writes of app.confirm_settlement_extra_charge (sub-slice 10b) move unchanged
  into the shared helper app.write_correction_one_time_charge.
- The correction's own receipt reversal moves into a shared writer with the explicit "Deposit
  belongs to this Property" check; the PAYMENT_RETURN confirm uses it for a Deposit whose Refund it
  recovered (the reversal function stamps the statement time, which would date the receipt
  reversal before the recovery). The RETURNED_PAYMENT write helper now runs the correction's source
  and refusal check itself (the sub-slice 10e-1b optional hardening).

Relaxing changes: app.refund_corrections gains the kind RECOVERED_BY_CHARGE and the nullable
unique column recovery_obligation_id (required exactly for that kind); the refusal of a Refund
that is not fully returned ends for the cases above; the Credit ledger cursor accepts the new
event kind. The whole-row reads of a Refund correction (the financial action context and the Refund
resource) leave the new column out, so their shape is unchanged. A waiting draft that names a
Refund the return recovers counts as a waiting draft. New functions otherwise.
"""

from alembic import op
from sqlalchemy import text

revision = "20261122_118"
down_revision = "20261121_117"
branch_labels = None
depends_on = None

SQL = r"""
    -- DB-REFUND-002 amendment (owner answer (a) to Q-2026-10-10-72 point 1): a Refund paid from a
    -- returned Payment's value is recovered by a charge. The row gives the Refund's whole net
    -- amount back to its source on paper and names that charge.
    ALTER TABLE app.refund_corrections
        ADD COLUMN recovery_obligation_id uuid UNIQUE
            REFERENCES app.authorized_nonrecurring_obligations(id) ON DELETE RESTRICT;
    ALTER TABLE app.refund_corrections DROP CONSTRAINT refund_corrections_correction_kind_check;
    ALTER TABLE app.refund_corrections ADD CONSTRAINT refund_corrections_correction_kind_check
        CHECK (correction_kind IN ('VALUE_CORRECTION','CORRECTION_REVERSAL','RECOVERED_BY_CHARGE'));
    ALTER TABLE app.refund_corrections DROP CONSTRAINT reservation_refund_correction_shape;
    ALTER TABLE app.refund_corrections ADD CONSTRAINT reservation_refund_correction_shape CHECK (
        (correction_kind='VALUE_CORRECTION' AND reverses_correction_id IS NULL
            AND source_balance_effect_usd_cents>0)
        OR (correction_kind='CORRECTION_REVERSAL' AND reverses_correction_id IS NOT NULL
            AND source_balance_effect_usd_cents<0)
        OR (correction_kind='RECOVERED_BY_CHARGE' AND reverses_correction_id IS NULL
            AND source_balance_effect_usd_cents>0));
    ALTER TABLE app.refund_corrections ADD CONSTRAINT refund_recovery_obligation_shape
        CHECK ((correction_kind='RECOVERED_BY_CHARGE')=(recovery_obligation_id IS NOT NULL));

    -- A RECOVERED_BY_CHARGE row passes only inside the confirmed return of the Refund's source
    -- Payment (directly, through one of its Credits, or through a receipt of the Refund's
    -- Deposit), written by that return's approver under financial.approve, naming the recovery
    -- charge of the same amount to the Refund's recipient; a Refund of a closed Final Settlement
    -- (its Deposit's Lease, or paid by a correction) passes only when the row is linked to a
    -- correction of that Settlement confirmed in this transaction.
    CREATE FUNCTION app.refund_recovery_allowed(p_correction app.refund_corrections)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT (p_correction).correction_kind='RECOVERED_BY_CHARGE'
                AND (p_correction).authorization_reference='financial.approve'
                AND EXISTS(SELECT 1 FROM app.payment_returns payment_return
                    JOIN app.financial_draft_decisions decision
                        ON decision.draft_id=payment_return.draft_id AND decision.decision='CONFIRMED'
                        AND decision.decided_by=payment_return.actor_id
                    WHERE payment_return.actor_id=(p_correction).actor_id
                      AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                      AND decision.decided_at>=transaction_timestamp()
                      AND (payment_return.payment_id=refund.source_payment_id
                        OR payment_return.payment_id=(SELECT credit.source_payment_id
                            FROM app.customer_credits credit
                            WHERE credit.id=refund.source_customer_credit_id)
                        -- A receipt not reversed: the return reverses it after this row (review
                        -- round 1).
                        OR payment_return.payment_id IN (SELECT receipt.payment_id
                            FROM app.deposit_receipts receipt
                            WHERE receipt.deposit_id=refund.source_deposit_id
                              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                                  WHERE reversal.deposit_receipt_id=receipt.id))))
                AND EXISTS(SELECT 1 FROM app.authorized_nonrecurring_obligations obligation
                    WHERE obligation.id=(p_correction).recovery_obligation_id
                      AND obligation.customer_id=refund.recipient_customer_id
                      AND obligation.category='MISCELLANEOUS_CHARGES'
                      AND obligation.authorized_amount_usd_cents=(p_correction).source_balance_effect_usd_cents
                      AND obligation.authorized_by=(p_correction).actor_id
                      AND obligation.authorized_at>=transaction_timestamp()
                      AND obligation.source_reference='refund-recovery:' || refund.id::text)
                -- Every closed Final Settlement the Refund belongs to links the row (review round 1).
                AND NOT EXISTS(SELECT 1 FROM app.final_settlements final_settlement
                    WHERE final_settlement.closed_at IS NOT NULL
                      AND (final_settlement.lease_id=(SELECT deposit.lease_id FROM app.deposits deposit
                            WHERE deposit.id=refund.source_deposit_id)
                        OR final_settlement.id IN (SELECT correction.final_settlement_id
                            FROM app.settlement_correction_effects effect
                            JOIN app.settlement_corrections correction
                                ON correction.id=effect.settlement_correction_id
                            WHERE effect.refund_id=refund.id))
                      AND app.settlement_correction_linked(final_settlement.id,'refund_corrections',
                          (p_correction).id) IS NOT TRUE)
            FROM app.refunds refund
            WHERE refund.id=(p_correction).refund_id),false)
    $$;

    -- Every Refund paid from the Payment's value that is not fully returned, with the person who
    -- received it (the Refund's recipient), its whole net amount and the Lease its charge goes on
    -- (owner answers A, B and C to Q-2026-10-11-78): the Lease the money came from when the
    -- recipient is its signed Customer, otherwise none.
    CREATE FUNCTION app.payment_return_recoveries(p_property uuid, p_payment uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog
    SET "TimeZone"='UTC' AS $$
        WITH payment AS (
            SELECT payment.* FROM app.payments payment
            WHERE payment.id=p_payment AND payment.property_id=p_property
        ), funded AS (
            SELECT DISTINCT receipt.deposit_id FROM app.deposit_receipts receipt
            JOIN payment ON payment.id=receipt.payment_id
            WHERE NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                WHERE reversal.deposit_receipt_id=receipt.id)
        ), paid AS (
            -- A Payment Refund: the Lease the Payment names.
            SELECT refund.id,'PAYMENT' AS source_kind,payment.id AS source_id,
                payment.lease_id AS used_lease_id
            FROM app.refunds refund JOIN payment ON payment.id=refund.source_payment_id
            -- A Credit Refund: the Lease of the Invoice or Late-payment Charge whose release
            -- created the Credit (none when that Invoice has no Lease); with no release, the
            -- Lease the Payment names (owner answer A; review round 1).
            UNION ALL SELECT refund.id,'CREDIT',credit.id,CASE WHEN EXISTS(
                    SELECT 1 FROM app.invoice_credit_excess_releases release
                    WHERE release.customer_credit_id=credit.id)
                THEN (SELECT invoice.lease_id
                    FROM app.invoice_credit_excess_releases release
                    LEFT JOIN app.invoice_adjustments adjustment
                        ON adjustment.id=release.invoice_adjustment_id
                    LEFT JOIN app.late_payment_charge_corrections charge_correction
                        ON charge_correction.id=release.late_payment_charge_correction_id
                    LEFT JOIN app.late_payment_charges charge
                        ON charge.id=charge_correction.late_payment_charge_id
                    JOIN app.invoices invoice
                        ON invoice.id=COALESCE(adjustment.invoice_id,charge.source_invoice_id)
                    WHERE release.customer_credit_id=credit.id
                    ORDER BY release.created_at,release.id LIMIT 1)
                ELSE payment.lease_id END
            FROM app.refunds refund
            JOIN app.customer_credits credit ON credit.id=refund.source_customer_credit_id
            JOIN payment ON payment.id=credit.source_payment_id
            -- A Deposit Refund of a Deposit the Payment funded: the Deposit's Lease.
            UNION ALL SELECT refund.id,'DEPOSIT',deposit.id,deposit.lease_id
            FROM app.refunds refund
            JOIN funded ON funded.deposit_id=refund.source_deposit_id
            JOIN app.deposits deposit ON deposit.id=funded.deposit_id
        ), outstanding AS (
            SELECT paid.id,paid.source_kind,paid.source_id,refund.refund_number,
                refund.recipient_customer_id,refund.processed_at,refund.source_lifecycle_event_id,
                app.refund_net_value_at(refund.id,'infinity') AS net,
                -- Owner answers B and C: the Lease only when the recipient is its signed Customer.
                CASE WHEN EXISTS(SELECT 1 FROM app.lease_signers signer
                    WHERE signer.lease_id=paid.used_lease_id
                      AND signer.customer_id=refund.recipient_customer_id
                      AND signer.signed_at IS NOT NULL) THEN paid.used_lease_id END AS lease_id
            FROM paid JOIN app.refunds refund ON refund.id=paid.id
        )
        SELECT COALESCE(jsonb_agg(jsonb_build_object('refund_id',outstanding.id,
                'refund_number',outstanding.refund_number,'source_kind',outstanding.source_kind,
                'source_id',outstanding.source_id,
                'recipient_customer_id',outstanding.recipient_customer_id,
                'amount_usd_cents',outstanding.net,'lease_id',outstanding.lease_id,
                'charge',CASE WHEN outstanding.lease_id IS NULL THEN 'NO_LEASE'
                    WHEN settlement.id IS NOT NULL THEN 'CLOSED_SETTLEMENT_LEASE' ELSE 'LEASE' END,
                'closed_final_settlement_id',settlement.id,
                'reservation_outcome',outstanding.source_lifecycle_event_id IS NOT NULL,
                'shared_deposit',outstanding.source_kind='DEPOSIT' AND EXISTS(
                    SELECT 1 FROM app.deposit_receipts receipt
                    WHERE receipt.deposit_id=outstanding.source_id AND receipt.payment_id<>p_payment
                      AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                          WHERE reversal.deposit_receipt_id=receipt.id)))
                ORDER BY outstanding.processed_at,outstanding.id),'[]'::jsonb)
        FROM outstanding
        LEFT JOIN app.final_settlements settlement
            ON settlement.lease_id=outstanding.lease_id AND settlement.closed_at IS NOT NULL
        WHERE outstanding.net>0
    $$;

    -- The recoveries a return may write; 55000 otherwise (the recorders and the confirms run it
    -- under the same locks, and the writer runs it again).
    CREATE FUNCTION app.assert_payment_return_recoveries_allowed(p_recoveries jsonb, p_settlement uuid)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        -- A Reservation outcome Refund is corrected only through the Reservation's own path
        -- (Q-2026-10-11-81; a known limit until the owner answers).
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_recoveries,'[]'::jsonb)) recovery
            WHERE (recovery->>'reservation_outcome')::boolean)
        THEN RAISE EXCEPTION 'A Reservation Deposit Refund paid from this Payment''s value is not fully returned'
            USING ERRCODE='55000'; END IF;
        -- Which Payment paid a Refund of a Deposit two Payments funded is not known.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_recoveries,'[]'::jsonb)) recovery
            WHERE (recovery->>'shared_deposit')::boolean)
        THEN RAISE EXCEPTION 'A Deposit this Payment funded also holds another Payment''s money and has a Refund that is not fully returned'
            USING ERRCODE='55000'; END IF;
        -- A charge on a Lease with a closed Final Settlement is written only by a correction of that
        -- Settlement (the Q-2026-10-10-72 point 3 known limit; plan choice for the owner).
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_recoveries,'[]'::jsonb)) recovery
            WHERE recovery->>'closed_final_settlement_id' IS NOT NULL
              AND recovery->>'closed_final_settlement_id' IS DISTINCT FROM p_settlement::text)
        THEN RAISE EXCEPTION 'A Refund paid from this Payment''s value would be charged on a Lease whose closed Final Settlement this return cannot correct'
            USING ERRCODE='55000'; END IF;
    END $$;

    -- The cross-check of the plan against the source (review round 1): every Refund paid from the
    -- returned value that is not fully returned has its planned recovery, so a Refund the plan
    -- missed is refused here, not later by a history check. 55000 otherwise.
    CREATE FUNCTION app.assert_payment_return_recoveries_planned(p_source jsonb)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF COALESCE((p_source->'payment'->>'refunded_usd_cents')::bigint,0)
                <>COALESCE((SELECT sum((recovery->>'amount_usd_cents')::bigint)
                    FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb)) recovery
                    WHERE recovery->>'source_kind'='PAYMENT'),0)
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'credits','[]'::jsonb)) credit
                WHERE COALESCE((credit->>'refunded_usd_cents')::bigint,0)
                    <>COALESCE((SELECT sum((recovery->>'amount_usd_cents')::bigint)
                        FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb)) recovery
                        WHERE recovery->>'source_kind'='CREDIT'
                          AND recovery->>'source_id'=credit->>'id'),0))
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'deposits','[]'::jsonb)) deposit
                WHERE (deposit->>'unresolved_refund')::boolean AND NOT EXISTS(
                    SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb)) recovery
                    WHERE recovery->>'source_kind'='DEPOSIT' AND recovery->>'source_id'=deposit->>'id'))
        THEN RAISE EXCEPTION 'A Refund paid from this Payment''s value has no planned recovery'
            USING ERRCODE='55000'; END IF;
    END $$;

    -- The charge, Invoice and issue of a post-settlement EXTRA_CHARGE (moved here unchanged from
    -- app.confirm_settlement_extra_charge, sub-slice 10b) and of a recovery charge (sub-slice
    -- 10e-1c). Every id is fresh, never derived from a draft; with a correction each record is
    -- linked before it is written. No begin and no SET CONSTRAINTS: the caller does both.
    CREATE FUNCTION app.write_correction_one_time_charge(p_property uuid, p_actor uuid,
        p_correction uuid, p_correlation uuid, p_customer uuid, p_lease uuid, p_category text,
        p_finding uuid, p_description text, p_amount bigint, p_due_date date,
        p_due_date_reason text, p_reason text, p_evidence_reference text, p_source_reference text,
        p_evidence jsonb, p_timezone text, p_now timestamptz, p_created_reason text,
        p_issued_reason text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog
    SET "TimeZone"='UTC' AS $$
    DECLARE v_business_date date; v_due date; v_obligation uuid; v_invoice uuid; v_line uuid;
        v_audit uuid; v_unit uuid; v_override boolean; v_draft_state jsonb; v_issued jsonb;
    BEGIN
        v_business_date:=timezone(p_timezone,p_now)::date;
        v_override:=p_due_date IS NOT NULL;
        -- The Due Date of a one-time charge: the issue date plus the Property's days, or the
        -- authorized override, never before the issue date.
        IF p_due_date<v_business_date THEN
            RAISE EXCEPTION 'The extra charge Due Date precedes the issue date' USING ERRCODE='55000'; END IF;
        SELECT COALESCE(p_due_date,v_business_date+property.one_time_charge_due_days)
        INTO STRICT v_due FROM app.properties property WHERE property.id=p_property;
        SELECT lease.unit_id INTO v_unit FROM app.leases lease WHERE lease.id=p_lease;
        -- The Lease of the Property, as the one-time charge recorder checks (review round 1).
        IF p_lease IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.units unit
            WHERE unit.id=v_unit AND unit.property_id=p_property)
        THEN RAISE EXCEPTION 'Lease was not found in Property scope' USING ERRCODE='P0002'; END IF;
        v_obligation:=gen_random_uuid();
        v_invoice:=gen_random_uuid();
        v_line:=gen_random_uuid();
        v_audit:=gen_random_uuid();

        IF p_correction IS NOT NULL THEN
            PERFORM app.link_settlement_correction_effect(p_correction,
                'authorized_nonrecurring_obligation_id',v_obligation);
        END IF;
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES(v_audit,p_now,v_business_date,
            p_actor,'invoice.one_time_charge.recorded','authorized_nonrecurring_obligation',v_obligation,
            p_reason,'financial.approve',p_property,'{}'::jsonb,
            jsonb_build_object('category',p_category,'amount_usd_cents',p_amount,
                'description',p_description,'evidence_reference',p_evidence_reference,
                'inspection_damage_finding_id',p_finding),
            p_correlation,'API','SUCCEEDED',p_evidence,p_customer,p_lease,v_unit);
        INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,lease_id,category,
            inspection_damage_finding_id,description,authorized_amount_usd_cents,governing_due_date,
            due_date_source,source_reference,authorized_at,authorized_by,authorization_reference,
            due_date_rule,reason,evidence_reference,audit_event_id)
        VALUES(v_obligation,p_customer,p_lease,p_category,p_finding,p_description,p_amount,NULL,
            'BR-INV-018',p_source_reference,p_now,p_actor,'financial.approve',
            'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS',p_reason,p_evidence_reference,v_audit);

        IF p_correction IS NOT NULL THEN
            PERFORM app.link_settlement_correction_effect(p_correction,'invoice_id',v_invoice);
        END IF;
        INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,
            invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,created_at,
            created_by,updated_at,updated_by)
        VALUES (v_invoice,'INV-' || to_char(v_business_date,'YYYYMMDD') || '-'
                || upper(substr(replace(v_invoice::text,'-',''),1,12)),
            p_customer,p_lease,p_category,'DRAFT',v_business_date,NULL,p_amount,'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS',
            'BR-INV-018',p_now,p_actor,p_now,p_actor);
        INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,amount_usd_cents,
            authorized_obligation_id,calculation_trace,created_at,last_changed_at,created_by,last_changed_by)
        VALUES (v_line,v_invoice,1,p_category,p_description,p_amount,v_obligation,
            jsonb_build_object('formula','authorized_source_exact_amount',
                'authorized_obligation_id',v_obligation,'authorized_amount_usd_cents',p_amount,
                'source_reference',p_source_reference),
            p_now,p_now,p_actor,p_actor);
        v_draft_state:=app.invoice_resource_snapshot(v_invoice);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,customer_id,lease_id)
        VALUES (gen_random_uuid(),p_now,
            v_business_date,p_actor,'invoice.created','invoice',v_invoice,
            p_created_reason,'financial.approve',p_property,
            '{}'::jsonb,v_draft_state,p_correlation,'API','SUCCEEDED',
            p_evidence || jsonb_build_object('authorized_obligation_id',v_obligation),p_customer,p_lease);
        -- Issued in the same call: a linked Invoice never stays DRAFT (writer notes, 10a).
        UPDATE app.invoices SET status='UNPAID',issued_at=p_now,issued_by=p_actor,due_date=v_due,
            due_date_override_reason=CASE WHEN v_override THEN p_due_date_reason END,
            due_date_set_by=CASE WHEN v_override THEN p_actor END,
            due_date_set_at=CASE WHEN v_override THEN p_now END,
            version=version+1,updated_at=p_now,updated_by=p_actor
        WHERE id=v_invoice;
        v_issued:=app.invoice_resource_snapshot(v_invoice);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,customer_id,lease_id)
        VALUES (gen_random_uuid(),p_now,
            v_business_date,p_actor,'invoice.issued','invoice',v_invoice,
            COALESCE(p_due_date_reason,p_issued_reason),
            'financial.approve',p_property,v_draft_state,v_issued,p_correlation,'API','SUCCEEDED',
            p_evidence || jsonb_build_object('due_date',v_due,'due_date_override',v_override),
            p_customer,p_lease);
        RETURN jsonb_build_object('obligation_id',v_obligation,'invoice_id',v_invoice,'due_date',v_due);
    END $$;

    -- Each recovery the return planned (app.payment_return_recoveries, read under the return's
    -- locks): the charge to the person who received the refund money, then the
    -- RECOVERED_BY_CHARGE row naming it, each dated after every event of its Refund and source.
    -- With a correction every record is linked before it is written.
    CREATE FUNCTION app.write_payment_return_recoveries(p_property uuid, p_actor uuid, p_draft uuid,
        p_correction uuid, p_payment uuid, p_recoveries jsonb, p_reason text, p_evidence text,
        p_at timestamptz, p_authorization_evidence jsonb)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog
    SET "TimeZone"='UTC' AS $$
    DECLARE v_timezone text; v_settlement uuid; v_recovery jsonb; v_refund app.refunds%ROWTYPE;
        v_net bigint; v_latest timestamptz; v_at timestamptz; v_charge jsonb; v_row uuid;
        v_lease uuid;
    BEGIN
        v_at:=p_at;
        v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
        SELECT correction.final_settlement_id INTO v_settlement
        FROM app.settlement_corrections correction WHERE correction.id=p_correction;
        PERFORM app.assert_payment_return_recoveries_allowed(p_recoveries,v_settlement);
        FOR v_recovery IN SELECT recovery.value
            FROM jsonb_array_elements(COALESCE(p_recoveries,'[]'::jsonb)) WITH ORDINALITY recovery(value,position)
            ORDER BY recovery.position
        LOOP
            SELECT * INTO STRICT v_refund FROM app.refunds WHERE id=(v_recovery->>'refund_id')::uuid;
            v_net:=app.refund_net_value_at(v_refund.id,'infinity');
            -- The planned amount and recipient still hold (the caller's digest checked them).
            IF v_net IS DISTINCT FROM (v_recovery->>'amount_usd_cents')::bigint OR v_net<=0
                OR v_refund.recipient_customer_id::text IS DISTINCT FROM v_recovery->>'recipient_customer_id'
            THEN RAISE EXCEPTION 'The Refund to recover changed; the draft is stale' USING ERRCODE='P5S02'; END IF;
            v_lease:=(v_recovery->>'lease_id')::uuid;
            IF v_lease IS NOT NULL THEN
                PERFORM pg_advisory_xact_lock(hashtextextended('invoice-lease:' || v_lease::text,0));
            END IF;
            v_latest:=GREATEST(v_refund.processed_at,
                (SELECT max(correction.occurred_at) FROM app.refund_corrections correction
                    WHERE correction.refund_id=v_refund.id),
                CASE WHEN v_refund.source_deposit_id IS NOT NULL
                        THEN app.deposit_balance_latest_at(v_refund.source_deposit_id)
                    WHEN v_refund.source_payment_id IS NOT NULL
                        THEN app.payment_proposal_dependency_at(v_refund.source_payment_id)
                    ELSE app.credit_latest_at(v_refund.source_customer_credit_id) END);
            v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp(),
                v_latest+interval '1 microsecond');
            -- Owner answers to Q-2026-10-11-78: the person who received the refund money pays it
            -- back, the exact net amount and nothing more, by a Miscellaneous one-time charge
            -- issued now.
            v_charge:=app.write_correction_one_time_charge(p_property,p_actor,p_correction,
                COALESCE(p_correction,p_draft),v_refund.recipient_customer_id,v_lease,
                'MISCELLANEOUS_CHARGES',NULL,
                'Recovery of Refund ' || v_refund.refund_number || ' paid from a returned Payment',
                v_net,NULL,NULL,'A Refund paid from a returned Payment is charged back to its recipient',
                p_evidence,'refund-recovery:' || v_refund.id::text,
                p_authorization_evidence || jsonb_build_object('refund_id',v_refund.id,
                    'payment_id',p_payment),
                v_timezone,v_at,'Invoice DRAFT created to recover a Refund paid from a returned Payment',
                'Invoice issued to recover a Refund paid from a returned Payment');
            -- The charge can be a new Invoice of the payer, which the Payment's chronology reads, so
            -- the recovery row is dated after it.
            v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp(),
                CASE WHEN v_refund.source_deposit_id IS NOT NULL
                        THEN app.deposit_balance_latest_at(v_refund.source_deposit_id)
                    WHEN v_refund.source_payment_id IS NOT NULL
                        THEN app.payment_proposal_dependency_at(v_refund.source_payment_id)
                    ELSE app.credit_latest_at(v_refund.source_customer_credit_id) END
                    +interval '1 microsecond');
            v_row:=gen_random_uuid();
            IF p_correction IS NOT NULL THEN
                PERFORM app.link_settlement_correction_effect(p_correction,'refund_correction_id',v_row);
            END IF;
            INSERT INTO app.refund_corrections(id,refund_id,correction_kind,reverses_correction_id,
                source_balance_effect_usd_cents,source_balance_effect_original_minor,
                previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,evidence_reference,
                occurred_at,actor_id,authorization_reference,recovery_obligation_id)
            VALUES (v_row,v_refund.id,'RECOVERED_BY_CHARGE',NULL,v_net,v_net,v_net,0,p_reason,
                p_evidence,v_at,p_actor,'financial.approve',(v_charge->>'obligation_id')::uuid);
        END LOOP;
        RETURN v_at;
    END $$;

    -- The receipt reversal a return writes itself (sub-slice 10e-1b choice (1)): the same record,
    -- command record and deposit.receipt.reversed audit event as the receipt reversal function,
    -- dated after the return's earlier records. The function's own checks: the Deposit belongs to
    -- this Property (owner check of 2026-10-11) and the reason is not blank; the state checks (an
    -- active forfeiture, a Refund not fully returned, an active Deposit application, a waiting
    -- draft, the closure link) are the shared BEFORE INSERT check of every receipt reversal.
    CREATE FUNCTION app.write_payment_return_receipt_reversal(p_property uuid, p_approver uuid,
        p_correction uuid, p_receipt uuid, p_reason text, p_key uuid, p_digest text,
        p_at timestamptz)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog
    SET "TimeZone"='UTC' AS $$
    DECLARE v_deposit uuid; v_receipt_at timestamptz; v_at timestamptz; v_new uuid;
    BEGIN
        SELECT receipt.deposit_id,receipt.occurred_at INTO v_deposit,v_receipt_at
        FROM app.deposit_receipts receipt WHERE receipt.id=p_receipt;
        IF NOT FOUND OR app.deposit_property_id(v_deposit) IS DISTINCT FROM p_property THEN
            RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='P0002'; END IF;
        IF COALESCE(btrim(p_reason),'')='' THEN
            RAISE EXCEPTION 'Deposit receipt reversal evidence is invalid' USING ERRCODE='22023'; END IF;
        v_at:=GREATEST(p_at+interval '1 microsecond',clock_timestamp(),v_receipt_at,
            COALESCE(app.deposit_balance_latest_at(v_deposit),'-infinity')
                +interval '1 microsecond');
        v_new:=gen_random_uuid();
        IF p_correction IS NOT NULL THEN
            PERFORM app.link_settlement_correction_effect(p_correction,'deposit_receipt_reversal_id',v_new);
        END IF;
        INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,actor_id,
            authorization_reference)
        VALUES (v_new,p_receipt,p_reason,v_at,p_approver,'deposits.correct');
        PERFORM app.record_deposit_command(p_property,p_approver,'deposit.receipt.reverse',
            p_key,p_digest,v_deposit,p_reason,'deposits.correct',app.deposit_snapshot(v_deposit));
        PERFORM app.record_deposit_audit(v_new,'deposit.receipt.reversed','deposit_receipt_reversal',
            v_new,v_deposit,p_reason,'deposits.correct',p_approver,p_key,
            app.deposit_resource_snapshot(v_deposit),p_receipt);
        RETURN v_at;
    END $$;

    -- One written recovery: the Refund, the person charged, the Lease (or none), the amount, the
    -- charge and its Invoice; an EXTRA_CHARGE when the charge is linked to a correction of its own
    -- Lease's Final Settlement.
    CREATE FUNCTION app.refund_recovery_json(p_refund_correction uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog
    SET "TimeZone"='UTC' AS $$
        SELECT jsonb_build_object('refund_correction_id',correction.id,'refund_id',correction.refund_id,
            'customer_id',obligation.customer_id,'lease_id',obligation.lease_id,
            'amount_usd_cents',correction.source_balance_effect_usd_cents,
            'charge',CASE WHEN obligation.lease_id IS NULL THEN 'NO_LEASE'
                WHEN EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                    JOIN app.settlement_corrections settlement_correction
                        ON settlement_correction.id=effect.settlement_correction_id
                    JOIN app.final_settlements settlement
                        ON settlement.id=settlement_correction.final_settlement_id
                    WHERE effect.authorized_nonrecurring_obligation_id=obligation.id
                      AND settlement.lease_id=obligation.lease_id) THEN 'EXTRA_CHARGE'
                ELSE 'LEASE' END,
            'authorized_nonrecurring_obligation_id',obligation.id,'invoice_id',line.invoice_id,
            'due_date',invoice.due_date,'occurred_at',correction.occurred_at)
        FROM app.refund_corrections correction
        JOIN app.authorized_nonrecurring_obligations obligation
            ON obligation.id=correction.recovery_obligation_id
        JOIN app.invoice_lines line ON line.authorized_obligation_id=obligation.id
        JOIN app.invoices invoice ON invoice.id=line.invoice_id
        WHERE correction.id=p_refund_correction
    $$;

    -- The recoveries one PAYMENT_RETURN draft wrote: each recovery charge's audit event carries the
    -- draft as its correlation (review round 1: not by the Payment, whose earlier reversed receipt
    -- could name another return's recovery).
    CREATE FUNCTION app.payment_return_recoveries_written(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog
    SET "TimeZone"='UTC' AS $$
        SELECT COALESCE(jsonb_agg(app.refund_recovery_json(correction.id)
                ORDER BY correction.occurred_at,correction.id),'[]'::jsonb)
        FROM app.refund_corrections correction
        JOIN app.authorized_nonrecurring_obligations obligation
            ON obligation.id=correction.recovery_obligation_id
        JOIN app.audit_events audit ON audit.id=obligation.audit_event_id
        WHERE correction.correction_kind='RECOVERED_BY_CHARGE' AND audit.correlation_id=p_draft
    $$;
"""

# The EXTRA_CHARGE confirm (sub-slice 10b): its linked one-time charge, Invoice and issue writes
# move unchanged into app.write_correction_one_time_charge. Replaced: the block from the first to
# the end of the last marker, each found exactly once.
EXTRA_CHARGE_START = (
    "        -- The Due Date of a one-time charge: the issue date plus the Property's days, or the\n"
)
EXTRA_CHARGE_END = (
    "            v_evidence || jsonb_build_object('due_date',v_due,'due_date_override',v_override),\n"
    "            v_customer,v_lease);\n"
)
EXTRA_CHARGE_BLOCK = (
    "        -- Sub-slice 10e-1c: the linked one-time charge, its Invoice and its issue are written by\n"
    "        -- the shared helper (the same records as before).\n"
    "        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,\n"
    "            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,\n"
    "            'variant','EXTRA_CHARGE');\n"
    "        v_issued:=app.write_correction_one_time_charge(p_property,p_actor,v_correction,v_correction,\n"
    "            v_customer,v_lease,v_category,(v_charge->>'inspection_damage_finding_id')::uuid,\n"
    "            v_charge->>'description',v_amount,(v_charge->>'due_date')::date,\n"
    "            v_charge->>'due_date_reason',v_draft.reason,v_charge->>'evidence_reference',\n"
    "            'settlement-correction:' || v_correction::text,v_evidence,v_timezone,v_now,\n"
    "            'Invoice DRAFT created from a post-settlement correction',\n"
    "            'Invoice issued by a post-settlement correction');\n"
    "        v_obligation:=(v_issued->>'obligation_id')::uuid;\n"
    "        v_invoice:=(v_issued->>'invoice_id')::uuid;\n"
    "        v_due:=(v_issued->>'due_date')::date;\n"
)

# The RETURNED_PAYMENT write helper (sub-slice 10e-1b): its receipt reversal moves into the shared
# writer (the same records, with the explicit Property check).
RECEIPT_START = (
    "            v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp(),v_row.occurred_at,\n"
)
RECEIPT_END = "                app.deposit_resource_snapshot(v_row.deposit_id),v_row.id);\n"
RECEIPT_BLOCK = (
    "            v_key:='settlement-returned-payment-receipt:' || p_draft::text || ':' || v_row.id::text;\n"
    "            v_at:=app.write_payment_return_receipt_reversal(p_property,p_approver,p_correction,\n"
    "                v_row.id,v_reason,md5(v_key)::uuid,encode(sha256(convert_to(v_key,'UTF8')),'hex'),v_at);\n"
)

SPANS = (
    (
        "app.confirm_settlement_extra_charge(uuid,uuid,uuid,text)",
        EXTRA_CHARGE_START,
        EXTRA_CHARGE_END,
        EXTRA_CHARGE_BLOCK,
    ),
    (
        "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)",
        RECEIPT_START,
        RECEIPT_END,
        RECEIPT_BLOCK,
    ),
)

NOT_RETURNED_CHECK = (
    "        IF (p_source->'payment'->>'refunded_usd_cents')::bigint<>0\n"
    "            OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'credits') credit\n"
    "                WHERE (credit->>'refunded_usd_cents')::bigint<>0)\n"
    "            OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit\n"
    "                WHERE (deposit->>'unresolved_refund')::boolean)\n"
    "        THEN RAISE EXCEPTION 'A Refund paid from this Payment''s value is not fully returned'\n"
    "            USING ERRCODE='55000'; END IF;\n"
)

# Exact-text patches, each anchor found exactly once in the stored function.
PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    # DB-REFUND-002 amendment: the new kind passes the general correction check only inside the
    # return of its Payment.
    (
        "app.validate_general_refund_correction()",
        (
            (
                "            v_linked:=app.settlement_refund_return_allowed(NEW);\n",
                "            v_linked:=app.settlement_refund_return_allowed(NEW)\n"
                "                -- Sub-slice 10e-1c: a recovery of the Refund inside its Payment's return.\n"
                "                OR app.refund_recovery_allowed(NEW);\n",
            ),
            (
                "            ELSE\n                SELECT * INTO v_original FROM app.refund_corrections\n",
                "            ELSIF NEW.correction_kind='RECOVERED_BY_CHARGE' THEN\n"
                "                -- Sub-slice 10e-1c (DB-REFUND-002 amendment): the whole net amount, inside the\n"
                "                -- confirmed return of the Refund's Payment, naming its charge; no return evidence.\n"
                "                IF NOT app.refund_recovery_allowed(NEW)\n"
                "                    OR NEW.source_balance_effect_usd_cents<>v_net\n"
                "                    OR NEW.reverses_correction_id IS NOT NULL\n"
                "                    OR num_nonnulls(NEW.verified_return_amount_minor,NEW.verified_return_currency,\n"
                "                        NEW.verified_returned_at,NEW.return_method_reference)<>0\n"
                "                THEN RAISE EXCEPTION 'A Refund is recovered by a charge only inside the return of its Payment'\n"
                "                    USING ERRCODE='23514'; END IF;\n"
                "            ELSE\n                SELECT * INTO v_original FROM app.refund_corrections\n",
            ),
        ),
    ),
    (
        "app.audit_general_refund_event()",
        (
            (
                "                v_action:=CASE WHEN NEW.correction_kind='VALUE_CORRECTION' THEN 'refund.value_corrected'\n"
                "                    ELSE 'refund.correction_reversed' END;\n",
                "                v_action:=CASE WHEN NEW.correction_kind='VALUE_CORRECTION' THEN 'refund.value_corrected'\n"
                "                    WHEN NEW.correction_kind='RECOVERED_BY_CHARGE' THEN 'refund.recovered_by_charge'\n"
                "                    ELSE 'refund.correction_reversed' END;\n",
            ),
        ),
    ),
    (
        "app.customer_credit_ledger(uuid,uuid,uuid,integer,timestamp with time zone,text,uuid)",
        (
            (
                "                    'REFUND','REFUND_VALUE_CORRECTION','REFUND_CORRECTION_REVERSAL')\n",
                "                    'REFUND','REFUND_VALUE_CORRECTION','REFUND_CORRECTION_REVERSAL',\n"
                "                    'REFUND_RECOVERED_BY_CHARGE')\n",
            ),
        ),
    ),
    # The planned recoveries are part of every return's source (so of its draft and digest).
    (
        "app.payment_return_source(uuid,uuid,uuid)",
        (
            (
                "            UNION SELECT DISTINCT deposit_id FROM receipts\n        )\n",
                "            UNION SELECT DISTINCT deposit_id FROM receipts\n"
                "            -- Sub-slice 10e-1c (review round 1): a waiting draft that names a Refund this\n"
                "            -- return recovers is a waiting draft too.\n"
                "            UNION SELECT (recovery->>'refund_id')::uuid\n"
                "            FROM jsonb_array_elements(app.payment_return_recoveries(p_property,p_payment)) recovery\n"
                "        )\n",
            ),
            (
                "            'pending_drafts',COALESCE((SELECT jsonb_agg(draft.id ORDER BY draft.id)\n",
                "            'recoveries',app.payment_return_recoveries(p_property,p_payment),\n"
                "            'pending_drafts',COALESCE((SELECT jsonb_agg(draft.id ORDER BY draft.id)\n",
            ),
        ),
    ),
    # The whole-row reads of a Refund correction keep their shape (review round 1: the staff
    # screens accept exactly the existing keys); the new column is read through the results.
    (
        "app.financial_action_context_page(uuid,uuid,text,uuid,uuid,text,uuid,integer,integer,uuid)",
        (
            (
                "                    v_context:=v_context||jsonb_build_object('correction',to_jsonb(v_correction),\n"
                "                        'reversal',(SELECT to_jsonb(r) FROM app.refund_corrections r\n",
                "                    v_context:=v_context||jsonb_build_object('correction',\n"
                "                        to_jsonb(v_correction)-'recovery_obligation_id',\n"
                "                        'reversal',(SELECT to_jsonb(r)-'recovery_obligation_id' FROM app.refund_corrections r\n",
            ),
        ),
    ),
    (
        "app.refund_resource(uuid,uuid,uuid,integer,timestamp with time zone,uuid)",
        (
            (
                "'items',COALESCE(jsonb_agg(to_jsonb(page)-'page_row' ORDER BY page_row)",
                "'items',COALESCE(jsonb_agg(to_jsonb(page)-'page_row'-'recovery_obligation_id' ORDER BY page_row)",
            ),
        ),
    ),
    (
        "app.assert_payment_return_allowed(jsonb)",
        (
            (
                "        -- Q-2026-10-10-72 point 1: money paid out from the returned value is not undone here.\n"
                + NOT_RETURNED_CHECK,
                "        -- Sub-slice 10e-1c (Q-2026-10-10-72 point 1, Q-2026-10-11-78): a Refund paid from the\n"
                "        -- returned value is recovered by a charge in the same confirm, except in these cases.\n"
                "        PERFORM app.assert_payment_return_recoveries_allowed(p_source->'recoveries',NULL);\n"
                "        PERFORM app.assert_payment_return_recoveries_planned(p_source);\n",
            ),
        ),
    ),
    (
        "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)",
        (
            (
                "        -- Q-2026-10-10-72 point 1 (sub-slice 10e-1c): money paid out from the returned value.\n"
                + NOT_RETURNED_CHECK,
                "        -- Sub-slice 10e-1c (Q-2026-10-10-72 point 1, Q-2026-10-11-78): a Refund paid from the\n"
                "        -- returned value is recovered by a charge in the same correction, except in these cases.\n"
                "        PERFORM app.assert_payment_return_recoveries_allowed(p_source->'recoveries',p_settlement);\n"
                "        PERFORM app.assert_payment_return_recoveries_planned(p_source);\n",
            ),
            (
                "                    WHERE forfeiture->>'deposit_id'=deposit->>'id'),0)\n"
                "                <>COALESCE((SELECT sum((receipt->>'amount_usd_cents')::bigint)\n",
                "                    WHERE forfeiture->>'deposit_id'=deposit->>'id'),0)\n"
                "                -- Sub-slice 10e-1c: a recovered Deposit Refund gives its amount back.\n"
                "                +COALESCE((SELECT sum((recovery->>'amount_usd_cents')::bigint)\n"
                "                    FROM jsonb_array_elements(p_source->'recoveries') recovery\n"
                "                    WHERE recovery->>'source_kind'='DEPOSIT'\n"
                "                      AND recovery->>'source_id'=deposit->>'id'),0)\n"
                "                <>COALESCE((SELECT sum((receipt->>'amount_usd_cents')::bigint)\n",
            ),
        ),
    ),
    (
        "app.confirm_payment_return(uuid,uuid,uuid,text)",
        (
            (
                "        PERFORM pg_advisory_xact_lock(hashtextextended('payment-return:' || (v_draft.payload->>'payment_id'),0));\n",
                "        PERFORM pg_advisory_xact_lock(hashtextextended('payment-return:' || (v_draft.payload->>'payment_id'),0));\n"
                "        -- Sub-slice 10e-1c (review round 1): the Lease key lock of the one-time charge recorder\n"
                "        -- for every Lease a recovery charge goes on, in one id-ordered pass before any row lock,\n"
                "        -- as the key-first writers take it; read without row locks, so a change after it makes\n"
                "        -- the source digest differ and the draft stale.\n"
                "        FOR v_row IN SELECT DISTINCT (recovery->>'lease_id')::uuid AS lease_id\n"
                "            FROM jsonb_array_elements(app.payment_return_recoveries(p_property,\n"
                "                (v_draft.payload->>'payment_id')::uuid)) recovery\n"
                "            WHERE recovery->>'lease_id' IS NOT NULL ORDER BY 1\n"
                "        LOOP\n"
                "            PERFORM pg_advisory_xact_lock(hashtextextended('invoice-lease:' || v_row.lease_id::text,0));\n"
                "        END LOOP;\n",
            ),
            (
                "        VALUES (v_return,p_property,v_payment.id,p_draft,NULL,v_draft.reason,v_at,p_actor,'financial.approve');\n",
                "        VALUES (v_return,p_property,v_payment.id,p_draft,NULL,v_draft.reason,v_at,p_actor,'financial.approve');\n"
                "        -- Sub-slice 10e-1c (Q-2026-10-10-72 point 1, Q-2026-10-11-78): each Refund paid from the\n"
                "        -- returned value is recovered by a charge to the person who received it, before the\n"
                "        -- reversals that need its value back.\n"
                "        v_at:=app.write_payment_return_recoveries(p_property,p_actor,p_draft,NULL,v_payment.id,\n"
                "            v_source->'recoveries',v_draft.reason,v_draft.payload->>'evidence_reference',v_at,\n"
                "            jsonb_build_object('capability','financial.approve','draft_id',p_draft,\n"
                "                'prepare_capability','payments.reverse','payment_return_id',v_return));\n",
            ),
            (
                "        FOR v_row IN SELECT receipt.id FROM app.deposit_receipts receipt\n"
                "            WHERE receipt.payment_id=v_payment.id\n",
                "        FOR v_row IN SELECT receipt.id,receipt.deposit_id FROM app.deposit_receipts receipt\n"
                "            WHERE receipt.payment_id=v_payment.id\n",
            ),
            (
                "            v_reversal:=gen_random_uuid();\n"
                "            PERFORM app.reverse_deposit_receipt_v2(p_property,p_actor,\n"
                "                app.payment_return_receipt_key(p_draft,v_row.id),\n"
                "                encode(sha256(convert_to('payment-return:' || p_draft::text || ':' || v_row.id::text,'UTF8')),'hex'),\n"
                "                v_reversal,v_row.id,v_draft.reason,'deposits.correct');\n",
                "            v_reversal:=gen_random_uuid();\n"
                "            -- Sub-slice 10e-1c: the receipt of a Deposit whose Refund this return recovered is\n"
                "            -- reversed by the shared writer, dated after the recovery (the reversal function\n"
                "            -- stamps the statement time, which would date it before the recovery and make the\n"
                "            -- Deposit's history negative); the same records and checks otherwise.\n"
                "            IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'recoveries') recovery\n"
                "                WHERE recovery->>'source_kind'='DEPOSIT'\n"
                "                  AND recovery->>'source_id'=v_row.deposit_id::text)\n"
                "            THEN\n"
                "                v_at:=app.write_payment_return_receipt_reversal(p_property,p_actor,NULL,v_row.id,\n"
                "                    v_draft.reason,app.payment_return_receipt_key(p_draft,v_row.id),\n"
                "                    encode(sha256(convert_to('payment-return:' || p_draft::text || ':' || v_row.id::text,'UTF8')),'hex'),\n"
                "                    v_at);\n"
                "            ELSE\n"
                "                PERFORM app.reverse_deposit_receipt_v2(p_property,p_actor,\n"
                "                    app.payment_return_receipt_key(p_draft,v_row.id),\n"
                "                    encode(sha256(convert_to('payment-return:' || p_draft::text || ':' || v_row.id::text,'UTF8')),'hex'),\n"
                "                    v_reversal,v_row.id,v_draft.reason,'deposits.correct');\n"
                "            END IF;\n",
            ),
        ),
    ),
    (
        "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)",
        (
            (
                "    DECLARE v_reason text; v_payment app.payments%ROWTYPE; v_at timestamptz; v_row record; v_new uuid;\n"
                "        v_key text;\n",
                "    DECLARE v_reason text; v_payment app.payments%ROWTYPE; v_at timestamptz; v_row record; v_new uuid;\n"
                "        v_key text; v_settlement uuid; v_lease uuid; v_source jsonb;\n",
            ),
            (
                "        SELECT * INTO STRICT v_payment FROM app.payments WHERE id=p_payment AND property_id=p_property;\n",
                "        SELECT * INTO STRICT v_payment FROM app.payments WHERE id=p_payment AND property_id=p_property;\n"
                "        -- Sub-slice 10e-1c (the sub-slice 10e-1b optional hardening): the helper runs the\n"
                "        -- correction's source and refusal check itself, so no caller writes without it.\n"
                "        SELECT settlement.id,settlement.lease_id INTO STRICT v_settlement,v_lease\n"
                "        FROM app.settlement_corrections correction\n"
                "        JOIN app.final_settlements settlement ON settlement.id=correction.final_settlement_id\n"
                "        WHERE correction.id=p_correction AND correction.correlation_id=p_draft\n"
                "          AND settlement.property_id=p_property;\n"
                "        v_source:=app.settlement_returned_payment_source(p_property,v_settlement,p_payment,p_draft);\n"
                "        -- The writes below follow this source, so it is still the one the draft recorded\n"
                "        -- (review round 1).\n"
                "        IF 'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')\n"
                "            IS DISTINCT FROM (SELECT draft.source_revision FROM app.financial_drafts draft\n"
                "                WHERE draft.id=p_draft)\n"
                "        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'\n"
                "            USING ERRCODE='P5S02'; END IF;\n"
                "        PERFORM app.assert_settlement_returned_payment_allowed(v_settlement,v_lease,v_source);\n",
            ),
            (
                "        VALUES (gen_random_uuid(),p_property,p_payment,p_draft,p_correction,v_reason,v_at,p_approver,\n"
                "            'financial.approve');\n",
                "        VALUES (gen_random_uuid(),p_property,p_payment,p_draft,p_correction,v_reason,v_at,p_approver,\n"
                "            'financial.approve');\n"
                "        -- Sub-slice 10e-1c (Q-2026-10-10-72 point 1, Q-2026-10-11-78): each Refund paid from the\n"
                "        -- returned value is recovered by a charge to the person who received it, linked.\n"
                "        v_at:=app.write_payment_return_recoveries(p_property,p_approver,p_draft,p_correction,\n"
                "            p_payment,v_source->'recoveries',v_reason,p_evidence,v_at,\n"
                "            jsonb_build_object('capability','financial.approve','draft_id',p_draft,\n"
                "                'settlement_correction_id',p_correction,'final_settlement_id',v_settlement,\n"
                "                'variant','RETURNED_PAYMENT'));\n",
            ),
        ),
    ),
    (
        "app.confirm_settlement_returned_payment(uuid,uuid,uuid,text)",
        (
            (
                "        v_unit uuid; v_at timestamptz; v_result jsonb;\n",
                "        v_unit uuid; v_at timestamptz; v_result jsonb; v_lock record;\n",
            ),
            (
                "        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));\n",
                "        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));\n"
                "        -- Sub-slice 10e-1c (review round 1): the Lease key lock of the one-time charge recorder\n"
                "        -- for the Settlement's Lease and every Lease a recovery charge goes on, in one\n"
                "        -- id-ordered pass after the Settlement's draft lock (as the EXTRA_CHARGE confirm) and\n"
                "        -- before any row lock; read without row locks, so a change after it makes the source\n"
                "        -- digest differ and the draft stale.\n"
                "        FOR v_lock IN SELECT lease.lease_id FROM (SELECT v_settlement.lease_id AS lease_id\n"
                "            UNION SELECT (recovery->>'lease_id')::uuid\n"
                "            FROM jsonb_array_elements(app.payment_return_recoveries(p_property,v_payment)) recovery\n"
                "            WHERE recovery->>'lease_id' IS NOT NULL) lease ORDER BY lease.lease_id\n"
                "        LOOP\n"
                "            PERFORM pg_advisory_xact_lock(hashtextextended('invoice-lease:' || v_lock.lease_id::text,0));\n"
                "        END LOOP;\n",
            ),
        ),
    ),
    (
        "app.payment_return_result(uuid)",
        (
            (
                "                WHERE receipt.payment_id=payment_return.payment_id),'[]'::jsonb))\n",
                "                WHERE receipt.payment_id=payment_return.payment_id),'[]'::jsonb),\n"
                "            -- Sub-slice 10e-1c: who is charged for each recovered Refund, on which Lease, how much.\n"
                "            'recoveries',app.payment_return_recoveries_written(payment_return.draft_id))\n",
            ),
        ),
    ),
    (
        "app.settlement_returned_payment_result(uuid)",
        (
            (
                "            'payment_reversal_id',(SELECT payment_reversal_id FROM effects\n"
                "                WHERE payment_reversal_id IS NOT NULL))\n",
                "            'payment_reversal_id',(SELECT payment_reversal_id FROM effects\n"
                "                WHERE payment_reversal_id IS NOT NULL),\n"
                "            -- Sub-slice 10e-1c: who is charged for each recovered Refund, on which Lease, how much.\n"
                "            'recoveries',COALESCE((SELECT jsonb_agg(app.refund_recovery_json(refund_correction_id)\n"
                "                    ORDER BY effect_sequence) FROM effects\n"
                "                WHERE refund_correction_id IS NOT NULL),'[]'::jsonb))\n",
            ),
        ),
    ),
)

INTERNAL = (
    "app.refund_recovery_allowed(app.refund_corrections)",
    "app.payment_return_recoveries(uuid,uuid)",
    "app.assert_payment_return_recoveries_allowed(jsonb,uuid)",
    "app.assert_payment_return_recoveries_planned(jsonb)",
    "app.write_correction_one_time_charge(uuid,uuid,uuid,uuid,uuid,uuid,text,uuid,text,bigint,date,"
    "text,text,text,text,jsonb,text,timestamp with time zone,text,text)",
    "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,"
    "timestamp with time zone,jsonb)",
    "app.write_payment_return_receipt_reversal(uuid,uuid,uuid,uuid,text,uuid,text,"
    "timestamp with time zone)",
    "app.refund_recovery_json(uuid)",
    "app.payment_return_recoveries_written(uuid)",
)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Refund recovery contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def _replace_span(signature: str, start: str, end: str, block: str) -> None:
    definition = _definition(signature)
    if definition.count(start) != 1 or definition.count(end) != 1:
        raise RuntimeError(f"Refund recovery contract changed: {signature}")
    first = definition.index(start)
    last = definition.index(end) + len(end)
    # The end marker follows the start marker without overlap (review round 1).
    if definition.index(end) < first + len(start):
        raise RuntimeError(f"Refund recovery contract changed: {signature}")
    op.execute(definition[:first] + block + definition[last:])


def upgrade() -> None:
    op.execute(SQL)
    for signature, start, end, block in SPANS:
        _replace_span(signature, start, end, block)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Refund recovery migration is forward-only")
