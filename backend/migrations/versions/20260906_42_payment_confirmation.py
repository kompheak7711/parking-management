# ruff: noqa: E501
"""Explicit USD Payment confirmation with immutable received facts and exact replay."""

from alembic import op

revision = "20260906_42"
down_revision = "20260906_41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the missing command boundary without rewriting any existing Payment."""
    op.execute(r"""
        CREATE TABLE app.payment_confirmation_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            payment_id uuid NOT NULL UNIQUE REFERENCES app.payments(id) ON DELETE RESTRICT,
            request jsonb NOT NULL CHECK(jsonb_typeof(request)='object' AND octet_length(request::text)<=16000),
            response jsonb NOT NULL CHECK(jsonb_typeof(response)='object'),
            recorded_at timestamptz NOT NULL CHECK(isfinite(recorded_at)),
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );
        COMMENT ON TABLE app.payment_confirmation_commands IS
            'Immutable confirmation intent and response, including actual received_at and payer evidence. No historical received timestamp is inferred; Payment.confirmed_at remains the server confirmation instant.';
        CREATE TRIGGER payment_confirmation_commands_immutable
            BEFORE UPDATE OR DELETE ON app.payment_confirmation_commands
            FOR EACH ROW EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        CREATE TRIGGER payment_confirmation_commands_no_truncate
            BEFORE TRUNCATE ON app.payment_confirmation_commands
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        REVOKE ALL ON app.payment_confirmation_commands FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;

        CREATE FUNCTION app.payment_confirmation_replay(
            p_property_id uuid,p_actor_id uuid,p_key uuid,p_request jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_command app.payment_confirmation_commands%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_request IS NULL OR jsonb_typeof(p_request)<>'object'
                OR octet_length(p_request::text)>16000
            THEN RAISE EXCEPTION 'Payment confirmation identity is invalid' USING ERRCODE='P5302'; END IF;
            -- All confirmation currencies share one actor/Property/key namespace.
            -- The lock is held until the Payment, Receipt, audit and response commit.
            PERFORM pg_advisory_xact_lock(hashtextextended('payment-confirmation:'
                ||p_property_id::text||':'||p_actor_id::text||':'||p_key::text,0));
            SELECT * INTO v_command FROM app.payment_confirmation_commands
                WHERE property_id=p_property_id AND actor_id=p_actor_id AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_command.request IS DISTINCT FROM p_request
                THEN RAISE EXCEPTION 'Payment confirmation key reused' USING ERRCODE='P5305'; END IF;
                RETURN v_command.response;
            END IF;
            RETURN NULL;
        END $$;

        CREATE FUNCTION app.confirm_usd_payment(
            p_property_id uuid,p_actor_id uuid,p_key uuid,p_request jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
          SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE
            v_result jsonb; v_payment app.payments%ROWTYPE; v_receipt app.receipts%ROWTYPE;
            v_id uuid:=gen_random_uuid(); v_customer uuid; v_method uuid; v_lease uuid;
            v_invoice uuid; v_charge uuid; v_received timestamptz; v_at timestamptz;
            v_amount bigint; v_key text; v_limit integer;
            v_keys text[]:=ARRAY['received_currency','payer_customer_id','payment_method_id',
                'received_amount_minor','received_at','evidence_reference','payer_intent_memo',
                'lease_id','payment_scope_kind','identified_invoice_id',
                'identified_late_payment_charge_id','channel_transaction_reference'];
        BEGIN
            v_result:=app.payment_confirmation_replay(p_property_id,p_actor_id,p_key,p_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF NOT (p_request ?& v_keys) OR p_request-v_keys<>'{}'::jsonb
                OR p_request->'received_currency' IS DISTINCT FROM '"USD"'::jsonb
                OR jsonb_typeof(p_request->'received_amount_minor') IS DISTINCT FROM 'number'
                OR p_request->>'received_amount_minor' !~ '^[0-9]+$'
                OR p_request->'payment_scope_kind' NOT IN ('"NORMAL_CUSTOMER"'::jsonb,'"THIRD_PARTY_IDENTIFIED"'::jsonb)
                OR jsonb_typeof(p_request->'received_at') IS DISTINCT FROM 'string'
                OR p_request->>'received_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'
            THEN RAISE EXCEPTION 'USD Payment intent is invalid' USING ERRCODE='P5302'; END IF;
            FOREACH v_key IN ARRAY ARRAY['payer_customer_id','payment_method_id','lease_id',
                'identified_invoice_id','identified_late_payment_charge_id'] LOOP
                IF p_request->v_key='null'::jsonb AND v_key NOT IN ('payer_customer_id','payment_method_id')
                THEN CONTINUE; END IF;
                IF jsonb_typeof(p_request->v_key) IS DISTINCT FROM 'string'
                    OR p_request->>v_key !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    OR p_request->>v_key='00000000-0000-0000-0000-000000000000'
                THEN RAISE EXCEPTION 'Payment source identity is invalid' USING ERRCODE='P5302'; END IF;
            END LOOP;
            FOREACH v_key IN ARRAY ARRAY['evidence_reference','payer_intent_memo','channel_transaction_reference'] LOOP
                IF p_request->v_key='null'::jsonb AND v_key<>'evidence_reference' THEN CONTINUE; END IF;
                v_limit:=CASE WHEN v_key='payer_intent_memo' THEN 2000 ELSE 500 END;
                IF jsonb_typeof(p_request->v_key) IS DISTINCT FROM 'string'
                    OR p_request->>v_key<>btrim(p_request->>v_key)
                    OR length(p_request->>v_key) NOT BETWEEN 1 AND v_limit
                THEN RAISE EXCEPTION 'Payment evidence is invalid' USING ERRCODE='P5302'; END IF;
            END LOOP;
            BEGIN
                v_received:=(p_request->>'received_at')::timestamptz;
                v_amount:=(p_request->>'received_amount_minor')::bigint;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'Payment amount or timestamp is invalid' USING ERRCODE='P5302';
            END;
            v_at:=clock_timestamp();
            IF v_amount NOT BETWEEN 1 AND 9000000000000000 OR NOT isfinite(v_received)
                OR extract(year FROM v_received) NOT BETWEEN 1 AND 9999 OR v_received>v_at
            THEN RAISE EXCEPTION 'Payment amount or received chronology is invalid' USING ERRCODE='P5302'; END IF;
            v_customer:=(p_request->>'payer_customer_id')::uuid;
            v_method:=(p_request->>'payment_method_id')::uuid;
            v_lease:=(p_request->>'lease_id')::uuid;
            v_invoice:=(p_request->>'identified_invoice_id')::uuid;
            v_charge:=(p_request->>'identified_late_payment_charge_id')::uuid;
            PERFORM 1 FROM app.customers WHERE id=v_customer FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Payment source not found' USING ERRCODE='P5301'; END IF;
            PERFORM 1 FROM app.payment_methods WHERE id=v_method FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Payment source not found' USING ERRCODE='P5301'; END IF;
            -- Published source validation supplies immutable method snapshots and
            -- verifies designation/Property relationships. Receipt and audits use
            -- their existing atomic triggers. This command moves no other value.
            INSERT INTO app.payments(id,payment_number,property_id,payer_customer_id,lease_id,
                payment_scope_kind,identified_invoice_id,identified_late_payment_charge_id,
                payment_date,payment_method_id,received_currency,received_amount_minor,
                usd_accounting_value_cents,channel_transaction_reference,payer_intent_memo,
                confirmed_at,confirmed_by,authorization_reference)
            VALUES(v_id,'PAY-'||v_id::text,p_property_id,v_customer,v_lease,
                p_request->>'payment_scope_kind',v_invoice,v_charge,
                (v_received AT TIME ZONE 'Asia/Phnom_Penh')::date,v_method,'USD',v_amount,v_amount,
                p_request->>'channel_transaction_reference',p_request->>'payer_intent_memo',
                v_at,p_actor_id,'payments.record') RETURNING * INTO v_payment;
            SET CONSTRAINTS ALL IMMEDIATE;
            SELECT * INTO STRICT v_receipt FROM app.receipts WHERE payment_id=v_id;
            v_result:=jsonb_build_object('payment',to_jsonb(v_payment),'received_at',v_received,
                'evidence_reference',p_request->>'evidence_reference',
                'receipt',jsonb_build_object('id',v_receipt.id,'receipt_number',v_receipt.receipt_number,
                    'payment_id',v_receipt.payment_id,'issued_at',v_receipt.issued_at),
                'property_timezone','Asia/Phnom_Penh');
            INSERT INTO app.payment_confirmation_commands
                VALUES(p_property_id,p_actor_id,p_key,v_id,p_request,v_result,v_at);
            RETURN v_result;
        END $$;
        REVOKE ALL ON FUNCTION app.payment_confirmation_replay(uuid,uuid,uuid,jsonb)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        REVOKE ALL ON FUNCTION app.confirm_usd_payment(uuid,uuid,uuid,jsonb)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.confirm_usd_payment(uuid,uuid,uuid,jsonb) TO prm_financial;
    """)


def downgrade() -> None:
    raise RuntimeError("Payment confirmation history is forward-only; downgrade is not supported")
