# ruff: noqa: E501
"""Immutable Payment Receipt identities and append-only authorized reprints."""

from alembic import op

revision = "20260906_40"
down_revision = "20260905_39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add receipts without inventing issuance evidence for existing Payments."""
    op.execute(r"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM app.payments) THEN
                RAISE EXCEPTION 'Receipt migration requires explicit reconciliation of existing Payment issuance evidence; no historical Receipt is inferred';
            END IF;
        END $$;
        CREATE TABLE app.receipts (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            receipt_number text NOT NULL UNIQUE CHECK(receipt_number='R-'||id::text),
            payment_id uuid NOT NULL UNIQUE REFERENCES app.payments(id) ON DELETE RESTRICT,
            payer_customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            issued_at timestamptz NOT NULL CHECK(isfinite(issued_at)),
            issued_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            identity_snapshot jsonb NOT NULL CHECK(jsonb_typeof(identity_snapshot)='object')
        );
        CREATE TABLE app.receipt_reprints (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            receipt_id uuid NOT NULL REFERENCES app.receipts(id) ON DELETE RESTRICT,
            reprinted_at timestamptz NOT NULL CHECK(isfinite(reprinted_at)),
            reprinted_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000 AND reason=btrim(reason)),
            delivery_reference text CHECK(delivery_reference IS NULL OR
                (length(delivery_reference) BETWEEN 1 AND 500 AND delivery_reference=btrim(delivery_reference))),
            authorization_reference text NOT NULL CHECK(authorization_reference='receipts.reprint'),
            correlation_id uuid NOT NULL CHECK(correlation_id<>'00000000-0000-0000-0000-000000000000')
        );
        CREATE INDEX receipt_reprints_history_idx ON app.receipt_reprints(receipt_id,reprinted_at,id);
        CREATE TABLE app.receipt_reprint_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            receipt_id uuid NOT NULL REFERENCES app.receipts(id) ON DELETE RESTRICT,
            reason text NOT NULL,
            delivery_reference text,
            reprint_id uuid NOT NULL UNIQUE REFERENCES app.receipt_reprints(id) ON DELETE RESTRICT,
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );

        CREATE FUNCTION app.validate_receipt_identity()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_name text;
        BEGIN
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=NEW.payment_id FOR SHARE;
            SELECT legal_name INTO STRICT v_name FROM app.customers WHERE id=v_payment.payer_customer_id FOR SHARE;
            PERFORM app.assert_active_financial_actor(NEW.issued_by,v_payment.property_id);
            IF NEW.payer_customer_id<>v_payment.payer_customer_id OR NEW.issued_by<>v_payment.confirmed_by
                OR NEW.issued_at<v_payment.confirmed_at OR NEW.issued_at>clock_timestamp()+interval '5 seconds'
                OR NEW.identity_snapshot IS DISTINCT FROM jsonb_build_object('payer_legal_name',v_name)
            THEN RAISE EXCEPTION 'Receipt identity or issuance is inconsistent' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER receipts_validate BEFORE INSERT ON app.receipts
            FOR EACH ROW EXECUTE FUNCTION app.validate_receipt_identity();

        CREATE FUNCTION app.issue_payment_receipt()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_id uuid:=gen_random_uuid(); v_name text;
        BEGIN
            SELECT legal_name INTO STRICT v_name FROM app.customers WHERE id=NEW.payer_customer_id FOR SHARE;
            INSERT INTO app.receipts(id,receipt_number,payment_id,payer_customer_id,issued_at,issued_by,identity_snapshot)
            VALUES(v_id,'R-'||v_id::text,NEW.id,NEW.payer_customer_id,
                greatest(clock_timestamp(),NEW.confirmed_at),NEW.confirmed_by,
                jsonb_build_object('payer_legal_name',v_name));
            RETURN NULL;
        END $$;
        CREATE TRIGGER payments_issue_receipt AFTER INSERT ON app.payments
            FOR EACH ROW EXECUTE FUNCTION app.issue_payment_receipt();

        CREATE FUNCTION app.validate_receipt_reprint()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_receipt app.receipts%ROWTYPE; v_property uuid;
        BEGIN
            SELECT * INTO STRICT v_receipt FROM app.receipts WHERE id=NEW.receipt_id;
            SELECT property_id INTO STRICT v_property FROM app.payments WHERE id=v_receipt.payment_id;
            PERFORM app.require_invoice_command_actor(v_property,NEW.reprinted_by);
            PERFORM app.assert_active_financial_actor(NEW.reprinted_by,v_property);
            IF NEW.reprinted_at<v_receipt.issued_at OR NEW.reprinted_at>clock_timestamp()+interval '5 seconds'
            THEN RAISE EXCEPTION 'Receipt reprint chronology is invalid' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER receipt_reprints_validate BEFORE INSERT ON app.receipt_reprints
            FOR EACH ROW EXECUTE FUNCTION app.validate_receipt_reprint();

        CREATE FUNCTION app.audit_receipt_event()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_receipt app.receipts%ROWTYPE; v_payment app.payments%ROWTYPE;
        DECLARE v_actor uuid; v_at timestamptz; v_reason text; v_action text; v_auth text; v_correlation uuid;
        BEGIN
            IF TG_TABLE_NAME='receipts' THEN
                v_receipt:=NEW; v_actor:=NEW.issued_by; v_at:=NEW.issued_at;
                v_reason:='Receipt of confirmed Payment'; v_action:='receipt.issued'; v_correlation:=NEW.id;
            ELSE
                SELECT * INTO STRICT v_receipt FROM app.receipts WHERE id=NEW.receipt_id;
                v_actor:=NEW.reprinted_by; v_at:=NEW.reprinted_at; v_reason:=NEW.reason;
                v_action:='receipt.reprinted'; v_auth:=NEW.authorization_reference; v_correlation:=NEW.correlation_id;
            END IF;
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_receipt.payment_id;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,v_actor,v_action,
                'receipt',v_receipt.id,v_reason,COALESCE(v_auth,v_payment.authorization_reference),v_payment.property_id,
                jsonb_build_object('receipt_id',v_receipt.id,'receipt_number',v_receipt.receipt_number,
                    'payment_id',v_payment.id,'event_id',NEW.id,'event',v_action),
                v_correlation,'API','SUCCESS',v_payment.payer_customer_id,v_payment.lease_id);
            RETURN NULL;
        END $$;
        CREATE TRIGGER receipts_audit AFTER INSERT ON app.receipts
            FOR EACH ROW EXECUTE FUNCTION app.audit_receipt_event();
        CREATE TRIGGER receipt_reprints_audit AFTER INSERT ON app.receipt_reprints
            FOR EACH ROW EXECUTE FUNCTION app.audit_receipt_event();

        CREATE FUNCTION app.receipt_resource(p_property_id uuid,p_receipt_id uuid,p_actor_id uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_receipt app.receipts%ROWTYPE; v_payment app.payments%ROWTYPE; v_fx app.exchange_rate_records%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            SELECT receipt.* INTO v_receipt FROM app.receipts receipt JOIN app.payments payment ON payment.id=receipt.payment_id
                WHERE receipt.id=p_receipt_id AND payment.property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Receipt not found' USING ERRCODE='P5001'; END IF;
            -- Serialize display with source financial writes; volatile projections must
            -- not observe different committed positions within the same resource.
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_receipt.payment_id FOR SHARE;
            SELECT * INTO v_fx FROM app.exchange_rate_records WHERE id=v_payment.exchange_rate_record_id;
            RETURN jsonb_build_object('receipt',to_jsonb(v_receipt),
                'payment',jsonb_build_object('id',v_payment.id,'payment_number',v_payment.payment_number,
                    'property_id',v_payment.property_id,'payer_customer_id',v_payment.payer_customer_id,
                    'payment_date',v_payment.payment_date,'payment_method',v_payment.payment_method_name_snapshot,
                    'status',v_payment.status,'received_currency',v_payment.received_currency,
                    'received_amount_minor',v_payment.received_amount_minor,
                    'usd_accounting_value_cents',v_payment.usd_accounting_value_cents),
                'fx',CASE WHEN v_fx.id IS NULL THEN NULL ELSE jsonb_build_object('record_id',v_fx.id,
                    'system_rate_khr_per_usd',v_fx.system_rate_khr_per_usd::text,
                    'channel_actual_rate_khr_per_usd',v_fx.channel_actual_rate_khr_per_usd::text,
                    'channel_actual_amount_minor',v_fx.channel_actual_amount_minor,
                    'channel_actual_usd_value_cents',v_fx.channel_actual_usd_value_cents) END,
                'financial_position',(SELECT to_jsonb(position) FROM app.payment_financial_position position WHERE position.payment_id=v_payment.id));
        END $$;
        CREATE FUNCTION app.receipt_for_payment(p_property_id uuid,p_payment_id uuid,p_actor_id uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_receipt_id uuid;
        BEGIN
            SELECT receipt.id INTO v_receipt_id FROM app.receipts receipt JOIN app.payments payment ON payment.id=receipt.payment_id
                WHERE payment.id=p_payment_id AND payment.property_id=p_property_id;
            RETURN app.receipt_resource(p_property_id,v_receipt_id,p_actor_id);
        END $$;

        CREATE FUNCTION app.receipt_reprint_history(p_property_id uuid,p_receipt_id uuid,p_actor_id uuid,p_after_id uuid,p_limit integer)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_after_at timestamptz; v_rows jsonb;
        BEGIN
            PERFORM app.receipt_resource(p_property_id,p_receipt_id,p_actor_id);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
                RAISE EXCEPTION 'Receipt history limit is invalid' USING ERRCODE='P5002'; END IF;
            IF p_after_id IS NOT NULL THEN
                SELECT reprinted_at INTO v_after_at FROM app.receipt_reprints WHERE id=p_after_id AND receipt_id=p_receipt_id;
                IF NOT FOUND THEN RAISE EXCEPTION 'Receipt history cursor is invalid' USING ERRCODE='P5002'; END IF;
            END IF;
            SELECT COALESCE(jsonb_agg(to_jsonb(event) ORDER BY event.reprinted_at,event.id),'[]'::jsonb)
                INTO v_rows FROM (SELECT * FROM app.receipt_reprints WHERE receipt_id=p_receipt_id
                    AND (p_after_id IS NULL OR (reprinted_at,id)>(v_after_at,p_after_id))
                    ORDER BY reprinted_at,id LIMIT p_limit+1) event;
            RETURN jsonb_build_object('events',CASE WHEN jsonb_array_length(v_rows)>p_limit THEN v_rows-p_limit ELSE v_rows END,
                'has_more',jsonb_array_length(v_rows)>p_limit);
        END $$;

        CREATE FUNCTION app.reprint_receipt(p_property_id uuid,p_receipt_id uuid,p_actor_id uuid,p_key uuid,p_reason text,p_delivery text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_command app.receipt_reprint_commands%ROWTYPE; v_receipt app.receipts%ROWTYPE; v_event app.receipt_reprints%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000' OR p_receipt_id IS NULL
                OR p_reason IS NULL OR length(p_reason) NOT BETWEEN 1 AND 1000 OR p_reason<>btrim(p_reason)
                OR (p_delivery IS NOT NULL AND (length(p_delivery) NOT BETWEEN 1 AND 500 OR p_delivery<>btrim(p_delivery)))
            THEN RAISE EXCEPTION 'Receipt reprint command is invalid' USING ERRCODE='P5002'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('receipt-reprint:'||p_property_id::text||':'||p_actor_id::text||':'||p_key::text,0));
            SELECT * INTO v_command FROM app.receipt_reprint_commands
                WHERE property_id=p_property_id AND actor_id=p_actor_id AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_command.receipt_id<>p_receipt_id OR v_command.reason<>p_reason OR v_command.delivery_reference IS DISTINCT FROM p_delivery
                THEN RAISE EXCEPTION 'Receipt reprint key reused' USING ERRCODE='P5005'; END IF;
                SELECT * INTO STRICT v_event FROM app.receipt_reprints WHERE id=v_command.reprint_id;
                SELECT * INTO STRICT v_receipt FROM app.receipts WHERE id=v_event.receipt_id;
            ELSE
                SELECT receipt.* INTO v_receipt FROM app.receipts receipt JOIN app.payments payment ON payment.id=receipt.payment_id
                    WHERE receipt.id=p_receipt_id AND payment.property_id=p_property_id;
                IF NOT FOUND THEN RAISE EXCEPTION 'Receipt not found' USING ERRCODE='P5001'; END IF;
                INSERT INTO app.receipt_reprints(id,receipt_id,reprinted_at,reprinted_by,reason,delivery_reference,authorization_reference,correlation_id)
                    VALUES(gen_random_uuid(),v_receipt.id,greatest(clock_timestamp(),v_receipt.issued_at),p_actor_id,p_reason,p_delivery,'receipts.reprint',p_key)
                    RETURNING * INTO v_event;
                INSERT INTO app.receipt_reprint_commands VALUES(p_property_id,p_actor_id,p_key,p_receipt_id,p_reason,p_delivery,v_event.id);
            END IF;
            RETURN jsonb_build_object('receipt_id',v_receipt.id,'receipt_number',v_receipt.receipt_number,
                'payment_id',v_receipt.payment_id,'reprint',to_jsonb(v_event));
        END $$;
    """)
    for table in ("receipts", "receipt_reprints", "receipt_reprint_commands"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_invoice_append_only_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_invoice_append_only_mutation()"
        )
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime,prm_financial")
    for signature in (
        "validate_receipt_identity()",
        "issue_payment_receipt()",
        "validate_receipt_reprint()",
        "audit_receipt_event()",
        "receipt_resource(uuid,uuid,uuid)",
        "receipt_for_payment(uuid,uuid,uuid)",
        "receipt_reprint_history(uuid,uuid,uuid,uuid,integer)",
        "reprint_receipt(uuid,uuid,uuid,uuid,text,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    for signature in (
        "receipt_resource(uuid,uuid,uuid)",
        "receipt_for_payment(uuid,uuid,uuid)",
        "receipt_reprint_history(uuid,uuid,uuid,uuid,integer)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO prm_runtime,prm_financial")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.reprint_receipt(uuid,uuid,uuid,uuid,text,text) TO prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("Receipt history is permanent and forward-only; downgrade is not supported")
