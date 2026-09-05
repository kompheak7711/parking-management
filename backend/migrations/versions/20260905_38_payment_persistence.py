# ruff: noqa: E501
"""Persist immutable Payment facts, confirmed FX and explicit reversals."""

from alembic import op

revision = "20260905_38"
down_revision = "20260831_37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add validated financial sources without fabricating historical receipts."""
    op.execute(
        r"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM app.deposit_receipts) THEN
                RAISE EXCEPTION 'Payment persistence requires operator reconciliation of existing Deposit receipt Payment evidence; no money facts can be inferred';
            END IF;
        END $$;

        CREATE TABLE app.payments (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'::uuid),
            payment_number text NOT NULL UNIQUE CHECK (
                length(payment_number) BETWEEN 1 AND 100 AND payment_number=btrim(payment_number)),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            payer_customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            lease_id uuid REFERENCES app.leases(id) ON DELETE RESTRICT,
            payment_scope_kind text NOT NULL CHECK (
                payment_scope_kind IN ('NORMAL_CUSTOMER','THIRD_PARTY_IDENTIFIED')),
            identified_invoice_id uuid REFERENCES app.invoices(id) ON DELETE RESTRICT,
            identified_late_payment_charge_id uuid REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
            payment_date date NOT NULL,
            payment_method_id uuid NOT NULL REFERENCES app.payment_methods(id) ON DELETE RESTRICT,
            payment_method_code_snapshot text NOT NULL,
            payment_method_name_snapshot text NOT NULL,
            received_currency text NOT NULL CHECK (received_currency IN ('USD','KHR')),
            received_amount_minor bigint NOT NULL CHECK (received_amount_minor BETWEEN 1 AND 9000000000000000),
            usd_accounting_value_cents bigint NOT NULL CHECK (usd_accounting_value_cents BETWEEN 1 AND 9000000000000000),
            exchange_rate_record_id uuid REFERENCES app.exchange_rate_records(id) ON DELETE RESTRICT,
            channel_transaction_reference text CHECK (
                channel_transaction_reference IS NULL OR (
                    length(channel_transaction_reference) BETWEEN 1 AND 500
                    AND channel_transaction_reference=btrim(channel_transaction_reference))),
            payer_intent_memo text CHECK (payer_intent_memo IS NULL OR (
                length(payer_intent_memo) BETWEEN 1 AND 2000 AND payer_intent_memo=btrim(payer_intent_memo))),
            status text NOT NULL DEFAULT 'RECEIVED' CHECK (status IN ('RECEIVED','REVERSED')),
            confirmed_at timestamptz NOT NULL,
            confirmed_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(authorization_reference) BETWEEN 1 AND 500
                AND authorization_reference=btrim(authorization_reference)),
            CONSTRAINT payment_currency_evidence CHECK (
                (received_currency='USD' AND exchange_rate_record_id IS NULL
                    AND received_amount_minor=usd_accounting_value_cents)
                OR (received_currency='KHR' AND exchange_rate_record_id IS NOT NULL)),
            CONSTRAINT payment_third_party_intent CHECK (
                payment_scope_kind='NORMAL_CUSTOMER' OR lease_id IS NOT NULL
                    OR identified_invoice_id IS NOT NULL OR identified_late_payment_charge_id IS NOT NULL)
        );
        CREATE INDEX payments_customer_date_idx ON app.payments(payer_customer_id,payment_date DESC,id);
        CREATE INDEX payments_received_idx ON app.payments(property_id,id) WHERE status='RECEIVED';
        CREATE INDEX payments_invoice_intent_idx ON app.payments(identified_invoice_id)
            WHERE identified_invoice_id IS NOT NULL;

        CREATE TABLE app.payment_serialization_guards (
            payment_id uuid PRIMARY KEY REFERENCES app.payments(id) ON DELETE RESTRICT,
            revision bigint NOT NULL DEFAULT 0 CHECK (revision>=0)
        );
        CREATE FUNCTION app.serialize_payment_state(p_payment_id uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            -- A real row version change is necessary: a lock alone cannot refresh
            -- a Repeatable Read snapshot. Conflicts fail with SQLSTATE40001.
            INSERT INTO app.payment_serialization_guards(payment_id,revision)
            VALUES(p_payment_id,1) ON CONFLICT(payment_id) DO UPDATE
                SET revision=app.payment_serialization_guards.revision+1;
        END $$;

        CREATE TABLE app.payment_reversals (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'::uuid),
            payment_id uuid NOT NULL UNIQUE REFERENCES app.payments(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 2000 AND reason=btrim(reason)),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(authorization_reference) BETWEEN 1 AND 500
                AND authorization_reference=btrim(authorization_reference))
        );
        ALTER TABLE app.deposit_receipts ADD CONSTRAINT deposit_receipts_payment_fk
            FOREIGN KEY(payment_id) REFERENCES app.payments(id) ON DELETE RESTRICT;
        COMMENT ON COLUMN app.deposit_receipts.payment_id IS
            'Validated authoritative Payment source. Legacy orphan receipts require operator reconciliation before this migration.';

        CREATE FUNCTION app.validate_payment_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_method app.payment_methods%ROWTYPE;
            v_fx app.exchange_rate_records%ROWTYPE;
            v_customer uuid; v_lease uuid; v_property uuid; v_beneficiary uuid;
            v_numerator numeric; v_denominator numeric; v_usd_cents numeric;
        BEGIN
            IF NEW.status<>'RECEIVED' THEN
                RAISE EXCEPTION 'Payment must begin RECEIVED' USING ERRCODE='23514';
            END IF;
            PERFORM app.assert_active_financial_actor(NEW.confirmed_by,NULL);
            IF NOT isfinite(NEW.confirmed_at) OR NOT isfinite(NEW.payment_date)
                OR NEW.confirmed_at>clock_timestamp()+interval '5 seconds'
                OR NEW.payment_date>(NEW.confirmed_at AT TIME ZONE 'Asia/Phnom_Penh')::date
            THEN RAISE EXCEPTION 'Payment confirmation chronology is invalid' USING ERRCODE='23514'; END IF;
            SELECT * INTO STRICT v_method FROM app.payment_methods
                WHERE id=NEW.payment_method_id FOR SHARE;
            IF NOT v_method.accepted THEN
                RAISE EXCEPTION 'Payment Method is not accepted' USING ERRCODE='23514';
            END IF;
            NEW.payment_method_code_snapshot:=v_method.code;
            NEW.payment_method_name_snapshot:=v_method.display_name;
            IF NEW.lease_id IS NOT NULL THEN
                SELECT unit.property_id INTO STRICT v_property
                FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id
                WHERE lease.id=NEW.lease_id;
                IF v_property<>NEW.property_id THEN
                    RAISE EXCEPTION 'Payment Lease is outside Property scope' USING ERRCODE='23514';
                END IF;
                IF NEW.payment_scope_kind='NORMAL_CUSTOMER' AND NOT EXISTS (
                    SELECT 1 FROM app.leases AS lease WHERE lease.id=NEW.lease_id
                    AND (lease.primary_tenant_id=NEW.payer_customer_id OR EXISTS (
                        SELECT 1 FROM app.lease_signers AS signer
                        WHERE signer.lease_id=lease.id AND signer.customer_id=NEW.payer_customer_id))
                ) THEN RAISE EXCEPTION 'Normal Payment Lease intent must belong to payer' USING ERRCODE='23514'; END IF;
            END IF;
            IF NEW.identified_invoice_id IS NOT NULL THEN
                SELECT customer_id,lease_id,app.invoice_property_id(id)
                INTO STRICT v_customer,v_lease,v_property
                FROM app.invoices WHERE id=NEW.identified_invoice_id FOR SHARE;
                PERFORM app.advance_invoice_serialization_guard('payment-invoice:' || NEW.identified_invoice_id::text);
                IF v_property IS DISTINCT FROM NEW.property_id
                    OR (NEW.lease_id IS NOT NULL AND v_lease IS DISTINCT FROM NEW.lease_id)
                    OR (v_beneficiary IS NOT NULL AND v_customer<>v_beneficiary)
                THEN RAISE EXCEPTION 'Payment Invoice intent is inconsistent' USING ERRCODE='23514'; END IF;
                v_beneficiary:=v_customer;
            END IF;
            IF NEW.identified_late_payment_charge_id IS NOT NULL THEN
                SELECT charge.customer_id,invoice.lease_id,app.invoice_property_id(invoice.id)
                INTO STRICT v_customer,v_lease,v_property
                FROM app.late_payment_charges AS charge
                JOIN app.invoices AS invoice ON invoice.id=charge.source_invoice_id
                WHERE charge.id=NEW.identified_late_payment_charge_id;
                IF v_property IS DISTINCT FROM NEW.property_id
                    OR (NEW.lease_id IS NOT NULL AND v_lease IS DISTINCT FROM NEW.lease_id)
                    OR (v_beneficiary IS NOT NULL AND v_customer<>v_beneficiary)
                    OR (NEW.identified_invoice_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM app.late_payment_charges
                        WHERE id=NEW.identified_late_payment_charge_id
                          AND source_invoice_id=NEW.identified_invoice_id))
                THEN RAISE EXCEPTION 'Payment Charge intent is inconsistent' USING ERRCODE='23514'; END IF;
                v_beneficiary:=v_customer;
            END IF;
            IF NEW.payment_scope_kind='NORMAL_CUSTOMER' AND v_beneficiary IS NOT NULL
                AND v_beneficiary<>NEW.payer_customer_id
            THEN RAISE EXCEPTION 'Normal Payment intent must belong to payer' USING ERRCODE='23514'; END IF;
            IF NEW.received_currency='KHR' THEN
                SELECT * INTO STRICT v_fx FROM app.exchange_rate_records WHERE id=NEW.exchange_rate_record_id;
                IF NOT isfinite(v_fx.applicable_at) OR v_fx.applicable_at>NEW.confirmed_at
                    OR (v_fx.channel_confirmed_at IS NOT NULL
                        AND (NOT isfinite(v_fx.channel_confirmed_at)
                            OR v_fx.channel_confirmed_at>NEW.confirmed_at))
                    OR (v_fx.channel_transaction_reference IS NOT NULL
                        AND v_fx.channel_transaction_reference IS DISTINCT FROM NEW.channel_transaction_reference)
                    OR (v_fx.channel_actual_currency IS NOT NULL AND v_fx.channel_actual_currency<>'KHR')
                    OR (v_fx.channel_actual_amount_minor IS NOT NULL
                        AND v_fx.channel_actual_amount_minor<>NEW.received_amount_minor)
                    OR (v_fx.channel_actual_usd_value_cents IS NOT NULL
                        AND v_fx.channel_actual_usd_value_cents<>NEW.usd_accounting_value_cents)
                THEN RAISE EXCEPTION 'Payment FX or channel evidence is inconsistent' USING ERRCODE='23514'; END IF;
                IF v_fx.rate_source='ABA_EQUIVALENT_MANUAL' AND (
                    NOT (v_fx.calculation_trace @> jsonb_build_object('automatic_source_unavailable',true))
                    OR COALESCE(btrim(v_fx.calculation_trace->>'fallback_reason'),'')=''
                    OR v_fx.source_reference IS NULL
                ) THEN RAISE EXCEPTION 'Manual FX requires recorded source failure and provenance' USING ERRCODE='23514'; END IF;
                -- Supplied channel values control their fields. Missing values
                -- still require deterministic exact conversion; never accept an
                -- arbitrary accounting amount merely because one channel field exists.
                IF v_fx.channel_actual_amount_minor IS NULL
                    AND NEW.received_amount_minor<>ceil(NEW.usd_accounting_value_cents::numeric
                        * COALESCE(v_fx.channel_actual_rate_khr_per_usd,v_fx.system_rate_khr_per_usd)*0.01)
                THEN RAISE EXCEPTION 'Payment KHR conversion must use confirmed rate and whole-KHR ceiling' USING ERRCODE='23514'; END IF;
                IF v_fx.channel_actual_amount_minor IS NOT NULL AND v_fx.channel_actual_usd_value_cents IS NULL THEN
                    v_numerator:=NEW.received_amount_minor::numeric*100*1000000;
                    v_denominator:=COALESCE(v_fx.channel_actual_rate_khr_per_usd,v_fx.system_rate_khr_per_usd)*1000000;
                    v_usd_cents:=div(v_numerator,v_denominator)
                        + CASE WHEN mod(v_numerator,v_denominator)*2>=v_denominator THEN 1 ELSE 0 END;
                    IF NEW.usd_accounting_value_cents<>v_usd_cents THEN
                        RAISE EXCEPTION 'Payment accounting value must use confirmed channel amount and exact half-up cents' USING ERRCODE='23514';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER payments_validate_source BEFORE INSERT ON app.payments
            FOR EACH ROW EXECUTE FUNCTION app.validate_payment_source();

        CREATE FUNCTION app.preserve_payment_invoice_intent()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF NEW.customer_id IS DISTINCT FROM OLD.customer_id
                OR NEW.lease_id IS DISTINCT FROM OLD.lease_id THEN
                -- UPDATE already holds the Invoice row; confirmation takes the
                -- same row before this shared MVCC guard, preserving lock order.
                PERFORM app.advance_invoice_serialization_guard('payment-invoice:' || OLD.id::text);
                IF EXISTS(SELECT 1 FROM app.payments WHERE identified_invoice_id=OLD.id) THEN
                    RAISE EXCEPTION 'Invoice relationships are preserved by immutable Payment intent' USING ERRCODE='55000';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER invoices_00_preserve_payment_intent BEFORE UPDATE ON app.invoices
            FOR EACH ROW EXECUTE FUNCTION app.preserve_payment_invoice_intent();

        CREATE FUNCTION app.reject_payment_history_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_TABLE_NAME='payments' AND TG_OP='UPDATE' THEN
                IF (to_jsonb(NEW)-'status')=(to_jsonb(OLD)-'status')
                    AND OLD.status='RECEIVED' AND NEW.status='REVERSED'
                    AND EXISTS (SELECT 1 FROM app.payment_reversals WHERE payment_id=OLD.id)
                THEN RETURN NEW; END IF;
            END IF;
            RAISE EXCEPTION 'Payment history is immutable; use a linked reversal' USING ERRCODE='55000';
        END $$;
        CREATE TRIGGER payments_immutable BEFORE UPDATE OR DELETE ON app.payments
            FOR EACH ROW EXECUTE FUNCTION app.reject_payment_history_mutation();
        CREATE TRIGGER payment_reversals_immutable BEFORE UPDATE OR DELETE ON app.payment_reversals
            FOR EACH ROW EXECUTE FUNCTION app.reject_payment_history_mutation();

        CREATE FUNCTION app.payment_disposition_summary(p_payment_id uuid)
        RETURNS jsonb LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT jsonb_build_object('deposit_usd_cents',COALESCE(sum(receipt.amount_usd_cents),0),
                'allocation_usd_cents',0,'credit_usd_cents',0,'refund_usd_cents',0)
            FROM app.deposit_receipts AS receipt
            WHERE receipt.payment_id=p_payment_id AND NOT EXISTS (
                SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                WHERE reversal.deposit_receipt_id=receipt.id)
        $$;
        COMMENT ON FUNCTION app.payment_disposition_summary(uuid) IS
            'V1-048 existing Deposit effects; V1-049 allocation and V1-051 Credit/Refund must extend this boundary before exposing their writes.';

        CREATE FUNCTION app.validate_payment_deposit_source()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_deposit app.deposits%ROWTYPE; v_used numeric;
        BEGIN
            PERFORM app.serialize_payment_state(NEW.payment_id);
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=NEW.payment_id FOR UPDATE;
            SELECT * INTO STRICT v_deposit FROM app.deposits WHERE id=NEW.deposit_id;
            IF v_payment.status<>'RECEIVED' OR NEW.occurred_at<v_payment.confirmed_at
                OR app.deposit_property_id(NEW.deposit_id) IS DISTINCT FROM v_payment.property_id
                OR (v_payment.payment_scope_kind='NORMAL_CUSTOMER' AND v_deposit.customer_id<>v_payment.payer_customer_id)
                OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                    AND (v_payment.lease_id IS NULL OR v_payment.lease_id IS DISTINCT FROM v_deposit.lease_id))
            THEN RAISE EXCEPTION 'Deposit receipt Payment source is ineligible' USING ERRCODE='23514'; END IF;
            SELECT COALESCE(sum(value::numeric),0) INTO v_used
            FROM jsonb_each_text(app.payment_disposition_summary(NEW.payment_id));
            IF v_used+NEW.amount_usd_cents>v_payment.usd_accounting_value_cents THEN
                RAISE EXCEPTION 'Deposit receipt exceeds Payment availability' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER a_deposit_receipts_payment_source BEFORE INSERT ON app.deposit_receipts
            FOR EACH ROW EXECUTE FUNCTION app.validate_payment_deposit_source();

        CREATE FUNCTION app.validate_payment_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_used numeric; v_last_dependency timestamptz;
        BEGIN
            PERFORM app.serialize_payment_state(NEW.payment_id);
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=NEW.payment_id FOR UPDATE;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,NULL);
            SELECT COALESCE(sum(value::numeric),0) INTO v_used
                FROM jsonb_each_text(app.payment_disposition_summary(NEW.payment_id));
            SELECT max(event_at) INTO v_last_dependency FROM (
                SELECT receipt.occurred_at AS event_at FROM app.deposit_receipts receipt
                    WHERE receipt.payment_id=NEW.payment_id
                UNION ALL SELECT reversal.occurred_at FROM app.deposit_receipt_reversals reversal
                    JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                    WHERE receipt.payment_id=NEW.payment_id
                UNION ALL SELECT correction.occurred_at FROM app.refund_corrections correction
                    JOIN app.refunds refund ON refund.id=correction.refund_id
                    WHERE EXISTS(SELECT 1 FROM app.deposit_receipts receipt
                        WHERE receipt.deposit_id=refund.source_deposit_id AND receipt.payment_id=NEW.payment_id)
            ) dependency_events;
            IF v_payment.status<>'RECEIVED' OR v_used<>0
                OR NOT isfinite(NEW.occurred_at) OR NEW.occurred_at<v_payment.confirmed_at
                OR NEW.occurred_at<v_last_dependency
                OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
            THEN RAISE EXCEPTION 'Payment reversal requires resolved dispositions and valid chronology' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER payment_reversals_validate BEFORE INSERT ON app.payment_reversals
            FOR EACH ROW EXECUTE FUNCTION app.validate_payment_reversal();
        CREATE FUNCTION app.apply_payment_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            UPDATE app.payments SET status='REVERSED' WHERE id=NEW.payment_id;
            RETURN NULL;
        END $$;
        CREATE TRIGGER payment_reversals_apply AFTER INSERT ON app.payment_reversals
            FOR EACH ROW EXECUTE FUNCTION app.apply_payment_reversal();

        CREATE FUNCTION app.audit_payment_event()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_actor uuid; v_at timestamptz; v_reason text; v_action text;
        BEGIN
            IF TG_TABLE_NAME='payments' THEN
                v_payment:=NEW; v_actor:=NEW.confirmed_by; v_at:=NEW.confirmed_at;
                v_reason:='Confirmed money received'; v_action:='payment.confirmed';
            ELSE
                SELECT * INTO STRICT v_payment FROM app.payments WHERE id=NEW.payment_id;
                v_actor:=NEW.actor_id; v_at:=NEW.occurred_at;
                v_reason:=NEW.reason; v_action:='payment.reversed';
            END IF;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,
                entity_type,entity_id,reason,authorization_reference,property_id,
                previous_state,resulting_state,correlation_id,source,outcome,customer_id,lease_id)
            VALUES (gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,
                v_actor,v_action,'payment',v_payment.id,v_reason,NEW.authorization_reference,
                v_payment.property_id,CASE WHEN v_action='payment.reversed'
                    THEN jsonb_build_object('status','RECEIVED') ELSE NULL END,
                jsonb_build_object('event_id',NEW.id,'payment_id',v_payment.id,
                    'status',CASE WHEN v_action='payment.reversed' THEN 'REVERSED' ELSE 'RECEIVED' END,
                    'received_currency',v_payment.received_currency,'received_amount_minor',v_payment.received_amount_minor,
                    'usd_accounting_value_cents',v_payment.usd_accounting_value_cents,
                    'event',v_action),
                NEW.id,'API','SUCCESS',v_payment.payer_customer_id,v_payment.lease_id);
            RETURN NULL;
        END $$;
        CREATE TRIGGER payments_audit AFTER INSERT ON app.payments
            FOR EACH ROW EXECUTE FUNCTION app.audit_payment_event();
        CREATE TRIGGER payment_reversals_audit AFTER INSERT ON app.payment_reversals
            FOR EACH ROW EXECUTE FUNCTION app.audit_payment_event();

        CREATE FUNCTION app.deposit_has_unresolved_refund(p_deposit_id uuid)
        RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.refunds AS refund
                WHERE refund.source_deposit_id=p_deposit_id
                  AND refund.usd_accounting_value_cents<>COALESCE((
                      SELECT sum(correction.source_balance_effect_usd_cents)
                      FROM app.refund_corrections AS correction WHERE correction.refund_id=refund.id),0)
            )
        $$;
        CREATE OR REPLACE FUNCTION app.validate_deposit_receipt_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_deposit_id uuid;
        BEGIN
            SELECT receipt.deposit_id INTO v_deposit_id
            FROM app.deposit_receipts AS receipt WHERE receipt.id=NEW.deposit_receipt_id
            FOR UPDATE OF receipt;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='23503';
            END IF;
            PERFORM 1 FROM app.deposits WHERE id=v_deposit_id FOR UPDATE;
            IF EXISTS (
                SELECT 1 FROM app.deposit_dispositions AS disposition
                WHERE disposition.deposit_id=v_deposit_id AND NOT EXISTS (
                    SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                    WHERE reversal.deposit_disposition_id=disposition.id)
            ) OR app.deposit_has_unresolved_refund(v_deposit_id) THEN
                RAISE EXCEPTION 'Deposit receipt has active dependent financial history' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE OR REPLACE FUNCTION app.reverse_deposit_receipt(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_reversal_id uuid, p_receipt_id uuid,
            p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_result jsonb; v_deposit_id uuid;
        BEGIN
            v_result:=app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.receipt.reverse',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference<>'deposits.correct' OR COALESCE(btrim(p_reason),'')=''
            THEN RAISE EXCEPTION 'Deposit receipt reversal evidence is invalid' USING ERRCODE='22023'; END IF;
            SELECT receipt.deposit_id INTO v_deposit_id FROM app.deposit_receipts AS receipt
            WHERE receipt.id=p_receipt_id FOR UPDATE OF receipt;
            IF NOT FOUND OR app.deposit_property_id(v_deposit_id)<>p_property_id
            THEN RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='P0002'; END IF;
            PERFORM 1 FROM app.deposits WHERE id=v_deposit_id FOR UPDATE;
            IF EXISTS(SELECT 1 FROM app.deposit_dispositions d WHERE d.deposit_id=v_deposit_id
                AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals r WHERE r.deposit_disposition_id=d.id))
                OR app.deposit_has_unresolved_refund(v_deposit_id)
            THEN RAISE EXCEPTION 'Deposit receipt has active dependent financial history' USING ERRCODE='55000'; END IF;
            INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,
                actor_id,authorization_reference) VALUES(p_reversal_id,p_receipt_id,btrim(p_reason),
                statement_timestamp(),p_actor_id,p_authorization_reference);
            v_result:=app.deposit_snapshot(v_deposit_id);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,'deposit.receipt.reverse',
                p_idempotency_key,p_request_digest,v_deposit_id,p_reason,p_authorization_reference,v_result);
            RETURN v_result;
        END $$;
        """
    )
    for table in ("payments", "payment_reversals", "payment_serialization_guards"):
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_invoice_storage_truncate()"
        )
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
        if table != "payment_serialization_guards":
            op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime,prm_financial")
    for function in (
        "validate_payment_source()",
        "reject_payment_history_mutation()",
        "payment_disposition_summary(uuid)",
        "validate_payment_deposit_source()",
        "validate_payment_reversal()",
        "apply_payment_reversal()",
        "audit_payment_event()",
        "deposit_has_unresolved_refund(uuid)",
        "serialize_payment_state(uuid)",
        "preserve_payment_invoice_intent()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.payment_disposition_summary(uuid) TO prm_runtime,prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("Payment financial history is forward-only; use an approved forward migration")
