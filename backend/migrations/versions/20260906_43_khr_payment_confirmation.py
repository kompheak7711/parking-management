# ruff: noqa: E501
"""Atomic incoming KHR confirmation using preserved reference and channel evidence."""

from alembic import op

revision = "20260906_43"
down_revision = "20260906_42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add KHR commands without altering accepted functions or historical records."""
    op.execute(r"""
        CREATE FUNCTION app.khr_confirmation_text(p_value jsonb,p_limit integer,p_nullable boolean DEFAULT false)
        RETURNS text LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_text text; v_whitespace text:=U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000';
        BEGIN
            IF p_nullable AND p_value='null'::jsonb THEN RETURN NULL; END IF;
            IF jsonb_typeof(p_value) IS DISTINCT FROM 'string'
            THEN RAISE EXCEPTION 'KHR evidence is invalid' USING ERRCODE='P5302'; END IF;
            v_text:=p_value#>>'{}';
            IF v_text<>btrim(v_text,v_whitespace) OR length(v_text) NOT BETWEEN 1 AND p_limit
            THEN RAISE EXCEPTION 'KHR evidence is invalid' USING ERRCODE='P5302'; END IF;
            RETURN v_text;
        END $$;

        CREATE FUNCTION app.khr_confirmation_money(p_value jsonb,p_nullable boolean DEFAULT false)
        RETURNS bigint LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_amount bigint;
        BEGIN
            IF p_nullable AND p_value='null'::jsonb THEN RETURN NULL; END IF;
            IF jsonb_typeof(p_value) IS DISTINCT FROM 'number' OR p_value#>>'{}' !~ '^[0-9]{1,16}$'
            THEN RAISE EXCEPTION 'KHR monetary input is invalid' USING ERRCODE='P5302'; END IF;
            v_amount:=(p_value#>>'{}')::bigint;
            IF v_amount NOT BETWEEN 1 AND 9000000000000000
            THEN RAISE EXCEPTION 'KHR monetary bounds are invalid' USING ERRCODE='P5302'; END IF;
            RETURN v_amount;
        END $$;

        CREATE FUNCTION app.khr_confirmation_rate(p_value jsonb,p_nullable boolean DEFAULT false)
        RETURNS numeric LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_rate numeric;
        BEGIN
            IF p_nullable AND p_value='null'::jsonb THEN RETURN NULL; END IF;
            IF jsonb_typeof(p_value) IS DISTINCT FROM 'string' OR p_value#>>'{}' !~ '^[0-9]{1,14}\.[0-9]{6}$'
            THEN RAISE EXCEPTION 'KHR reference precision is invalid' USING ERRCODE='P5302'; END IF;
            v_rate:=(p_value#>>'{}')::numeric;
            IF v_rate<=0 THEN RAISE EXCEPTION 'KHR reference must be positive' USING ERRCODE='P5302'; END IF;
            RETURN v_rate;
        END $$;

        CREATE FUNCTION app.khr_confirmation_instant(p_value jsonb,p_at timestamptz)
        RETURNS timestamptz LANGUAGE plpgsql SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_instant timestamptz;
        BEGIN
            IF jsonb_typeof(p_value) IS DISTINCT FROM 'string'
                OR p_value#>>'{}' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'
            THEN RAISE EXCEPTION 'KHR timestamp is invalid' USING ERRCODE='P5302'; END IF;
            BEGIN v_instant:=(p_value#>>'{}')::timestamptz;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'KHR timestamp is invalid' USING ERRCODE='P5302';
            END;
            IF NOT isfinite(v_instant) OR extract(year FROM v_instant) NOT BETWEEN 1 AND 9999 OR v_instant>p_at
            THEN RAISE EXCEPTION 'KHR timestamp chronology is invalid' USING ERRCODE='P5302'; END IF;
            RETURN v_instant;
        END $$;

        CREATE FUNCTION app.replay_khr_payment_confirmation(p_property_id uuid,p_actor_id uuid,p_key uuid,p_request jsonb)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            -- Same actor/Property/key lock as USD. A replay never looks up a new rate.
            IF p_request->'received_currency' IS DISTINCT FROM '"KHR"'::jsonb
            THEN RAISE EXCEPTION 'Incoming KHR command is required' USING ERRCODE='P5302'; END IF;
            RETURN app.payment_confirmation_replay(p_property_id,p_actor_id,p_key,p_request);
        END $$;

        CREATE FUNCTION app.confirm_khr_payment(p_property_id uuid,p_actor_id uuid,p_key uuid,p_request jsonb,p_selection jsonb)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE
            v_result jsonb; v_payment app.payments%ROWTYPE; v_receipt app.receipts%ROWTYPE;
            v_fx app.exchange_rate_records%ROWTYPE; v_channel jsonb; v_manual jsonb;
            v_id uuid:=gen_random_uuid(); v_fx_id uuid:=gen_random_uuid();
            v_customer uuid; v_method uuid; v_lease uuid; v_invoice uuid; v_charge uuid;
            v_received timestamptz; v_at timestamptz; v_applicable timestamptz; v_channel_at timestamptz;
            v_amount bigint; v_usd bigint; v_expected_usd bigint; v_actual_amount bigint; v_actual_usd bigint;
            v_reference numeric; v_system bigint; v_actual_rate numeric; v_used_rate numeric;
            v_numerator numeric; v_denominator numeric; v_unrounded numeric; v_payable numeric;
            v_key text; v_evidence text; v_memo text; v_payment_reference text;
            v_source text; v_source_reference text; v_fallback text; v_channel_reference text; v_currency text;
            v_keys text[]:=ARRAY['received_currency','payer_customer_id','payment_method_id',
                'received_amount_minor','usd_amount_cents','received_at','evidence_reference','payer_intent_memo',
                'lease_id','payment_scope_kind','identified_invoice_id','identified_late_payment_charge_id',
                'channel_transaction_reference','manual_reference','channel_evidence'];
            v_selection_keys text[]:=ARRAY['reference_rate_khr_per_usd','source_reference','applicable_at',
                'fallback_reason','rate_source','automatic_source_unavailable'];
            v_channel_keys text[]:=ARRAY['transaction_reference','confirmed_at','actual_currency',
                'actual_amount_minor','actual_usd_value_cents','actual_rate_khr_per_usd'];
        BEGIN
            v_result:=app.replay_khr_payment_confirmation(p_property_id,p_actor_id,p_key,p_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF NOT (p_request ?& v_keys) OR p_request-v_keys<>'{}'::jsonb
                OR p_request->'payment_scope_kind' NOT IN ('"NORMAL_CUSTOMER"'::jsonb,'"THIRD_PARTY_IDENTIFIED"'::jsonb)
                OR jsonb_typeof(p_selection) IS DISTINCT FROM 'object' OR octet_length(p_selection::text)>6000
                OR NOT (p_selection ?& v_selection_keys) OR p_selection-v_selection_keys<>'{}'::jsonb
            THEN RAISE EXCEPTION 'KHR confirmation envelope is invalid' USING ERRCODE='P5302'; END IF;
            FOREACH v_key IN ARRAY ARRAY['payer_customer_id','payment_method_id','lease_id',
                'identified_invoice_id','identified_late_payment_charge_id'] LOOP
                IF p_request->v_key='null'::jsonb AND v_key NOT IN ('payer_customer_id','payment_method_id') THEN CONTINUE; END IF;
                IF jsonb_typeof(p_request->v_key) IS DISTINCT FROM 'string'
                    OR p_request->>v_key !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    OR p_request->>v_key='00000000-0000-0000-0000-000000000000'
                THEN RAISE EXCEPTION 'Payment source identity is invalid' USING ERRCODE='P5302'; END IF;
            END LOOP;
            v_at:=clock_timestamp();
            v_received:=app.khr_confirmation_instant(p_request->'received_at',v_at);
            v_amount:=app.khr_confirmation_money(p_request->'received_amount_minor');
            v_usd:=app.khr_confirmation_money(p_request->'usd_amount_cents');
            v_evidence:=app.khr_confirmation_text(p_request->'evidence_reference',500);
            v_memo:=app.khr_confirmation_text(p_request->'payer_intent_memo',2000,true);
            v_payment_reference:=app.khr_confirmation_text(p_request->'channel_transaction_reference',500,true);
            v_reference:=app.khr_confirmation_rate(p_selection->'reference_rate_khr_per_usd');
            v_source_reference:=app.khr_confirmation_text(p_selection->'source_reference',500);
            v_applicable:=app.khr_confirmation_instant(p_selection->'applicable_at',v_at);
            v_manual:=p_request->'manual_reference'; v_source:=p_selection->>'rate_source';
            IF v_source='ABA_AUTOMATIC' THEN
                IF v_manual IS DISTINCT FROM 'null'::jsonb OR p_selection->'fallback_reason' IS DISTINCT FROM 'null'::jsonb
                    OR p_selection->'automatic_source_unavailable' IS DISTINCT FROM 'false'::jsonb
                THEN RAISE EXCEPTION 'Automatic reference evidence is server-owned' USING ERRCODE='P5302'; END IF;
            ELSIF v_source='ABA_EQUIVALENT_MANUAL' THEN
                IF jsonb_typeof(v_manual) IS DISTINCT FROM 'object'
                    OR v_manual IS DISTINCT FROM (p_selection-ARRAY['rate_source','automatic_source_unavailable'])
                    OR p_selection->'automatic_source_unavailable' IS DISTINCT FROM 'true'::jsonb
                THEN RAISE EXCEPTION 'Manual fallback source evidence is inconsistent' USING ERRCODE='P5302'; END IF;
                v_fallback:=app.khr_confirmation_text(p_selection->'fallback_reason',500);
            ELSE RAISE EXCEPTION 'Approved ABA-equivalent source is required' USING ERRCODE='P5302'; END IF;
            v_system:=ceil(v_reference*1.005)::bigint;
            v_channel:=p_request->'channel_evidence';
            IF v_channel IS DISTINCT FROM 'null'::jsonb THEN
                IF jsonb_typeof(v_channel) IS DISTINCT FROM 'object' OR NOT (v_channel ?& v_channel_keys)
                    OR v_channel-v_channel_keys<>'{}'::jsonb
                THEN RAISE EXCEPTION 'Actual channel envelope is invalid' USING ERRCODE='P5302'; END IF;
                v_channel_reference:=app.khr_confirmation_text(v_channel->'transaction_reference',500);
                v_channel_at:=app.khr_confirmation_instant(v_channel->'confirmed_at',v_at);
                v_currency:=app.khr_confirmation_text(v_channel->'actual_currency',3,true);
                v_actual_amount:=app.khr_confirmation_money(v_channel->'actual_amount_minor',true);
                v_actual_usd:=app.khr_confirmation_money(v_channel->'actual_usd_value_cents',true);
                v_actual_rate:=app.khr_confirmation_rate(v_channel->'actual_rate_khr_per_usd',true);
                IF v_channel_reference IS DISTINCT FROM v_payment_reference
                    OR (v_currency IS NOT NULL AND v_currency<>'KHR')
                    OR (v_currency IS NULL AND v_actual_amount IS NULL AND v_actual_usd IS NULL AND v_actual_rate IS NULL)
                    OR (v_actual_amount IS NOT NULL AND v_actual_amount<>v_amount)
                THEN RAISE EXCEPTION 'Actual channel evidence does not match receipt' USING ERRCODE='P5302'; END IF;
            END IF;
            v_used_rate:=COALESCE(v_actual_rate,v_system);
            IF v_actual_usd IS NOT NULL THEN v_expected_usd:=v_actual_usd;
            ELSIF v_actual_amount IS NOT NULL THEN
                v_numerator:=v_actual_amount::numeric*100*1000000;
                v_denominator:=v_used_rate*1000000;
                v_payable:=div(v_numerator,v_denominator)+CASE WHEN mod(v_numerator,v_denominator)*2>=v_denominator THEN 1 ELSE 0 END;
                IF v_payable NOT BETWEEN 1 AND 9000000000000000
                THEN RAISE EXCEPTION 'Actual channel USD value is outside bounds' USING ERRCODE='P5302'; END IF;
                v_expected_usd:=v_payable::bigint;
            ELSE v_expected_usd:=v_usd; END IF;
            IF v_usd<>v_expected_usd OR (v_actual_amount IS NULL AND v_amount<>ceil(v_usd::numeric*v_used_rate*0.01))
            THEN RAISE EXCEPTION 'KHR and USD receipt amounts must match confirmed conversion' USING ERRCODE='P5302'; END IF;
            v_customer:=(p_request->>'payer_customer_id')::uuid;
            v_method:=(p_request->>'payment_method_id')::uuid;
            v_lease:=(p_request->>'lease_id')::uuid;
            v_invoice:=(p_request->>'identified_invoice_id')::uuid;
            v_charge:=(p_request->>'identified_late_payment_charge_id')::uuid;
            PERFORM 1 FROM app.customers WHERE id=v_customer FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Payment source not found' USING ERRCODE='P5301'; END IF;
            PERFORM 1 FROM app.payment_methods WHERE id=v_method FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Payment source not found' USING ERRCODE='P5301'; END IF;
            v_unrounded:=v_usd::numeric*v_system*0.01;
            INSERT INTO app.exchange_rate_records(id,reference_rate_khr_per_usd,markup_basis_points,
                system_rate_khr_per_usd,rate_source,source_reference,applicable_at,entered_by,
                channel_actual_currency,channel_actual_amount_minor,channel_actual_usd_value_cents,
                channel_actual_rate_khr_per_usd,channel_transaction_reference,channel_confirmed_at,calculation_trace)
            VALUES(v_fx_id,v_reference,50,v_system,v_source,v_source_reference,v_applicable,
                CASE WHEN v_source='ABA_EQUIVALENT_MANUAL' THEN p_actor_id ELSE NULL END,
                v_currency,v_actual_amount,v_actual_usd,v_actual_rate,v_channel_reference,v_channel_at,
                jsonb_build_object('usd_amount_cents',v_usd,'unrounded_payable_khr',v_unrounded::text,
                    'payable_khr',ceil(v_unrounded),'markup_basis_points',50,'rounding','CEILING_WHOLE_KHR',
                    'automatic_source_unavailable',v_source='ABA_EQUIVALENT_MANUAL','fallback_reason',v_fallback,
                    'received_khr',v_amount,'settlement_rate_khr_per_usd',v_used_rate::text))
            RETURNING * INTO v_fx;
            INSERT INTO app.payments(id,payment_number,property_id,payer_customer_id,lease_id,
                payment_scope_kind,identified_invoice_id,identified_late_payment_charge_id,
                payment_date,payment_method_id,received_currency,received_amount_minor,
                usd_accounting_value_cents,exchange_rate_record_id,channel_transaction_reference,payer_intent_memo,
                confirmed_at,confirmed_by,authorization_reference)
            VALUES(v_id,'PAY-'||v_id::text,p_property_id,v_customer,v_lease,
                p_request->>'payment_scope_kind',v_invoice,v_charge,
                (v_received AT TIME ZONE 'Asia/Phnom_Penh')::date,v_method,'KHR',v_amount,v_usd,v_fx_id,
                v_payment_reference,v_memo,v_at,p_actor_id,'payments.record') RETURNING * INTO v_payment;
            SET CONSTRAINTS ALL IMMEDIATE;
            SELECT * INTO STRICT v_receipt FROM app.receipts WHERE payment_id=v_id;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,p_actor_id,
                'exchange_rate.confirmed','ExchangeRateRecord',v_fx_id,'Rate selected at explicit KHR Payment confirmation',
                CASE WHEN v_source='ABA_EQUIVALENT_MANUAL' THEN 'exchange_rates.manage' ELSE 'payments.record' END,
                p_property_id,to_jsonb(v_fx),v_id,'API','SUCCESS',v_customer,v_lease);
            v_result:=jsonb_build_object('payment',to_jsonb(v_payment),'exchange_rate_record',to_jsonb(v_fx),
                'received_at',v_received,'evidence_reference',v_evidence,
                'receipt',jsonb_build_object('id',v_receipt.id,'receipt_number',v_receipt.receipt_number,
                    'payment_id',v_receipt.payment_id,'issued_at',v_receipt.issued_at),'property_timezone','Asia/Phnom_Penh');
            INSERT INTO app.payment_confirmation_commands VALUES(p_property_id,p_actor_id,p_key,v_id,p_request,v_result,v_at);
            RETURN v_result;
        END $$;
        REVOKE ALL ON FUNCTION app.khr_confirmation_text(jsonb,integer,boolean),
            app.khr_confirmation_money(jsonb,boolean),app.khr_confirmation_rate(jsonb,boolean),
            app.khr_confirmation_instant(jsonb,timestamptz),
            app.replay_khr_payment_confirmation(uuid,uuid,uuid,jsonb),
            app.confirm_khr_payment(uuid,uuid,uuid,jsonb,jsonb)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.replay_khr_payment_confirmation(uuid,uuid,uuid,jsonb),
            app.confirm_khr_payment(uuid,uuid,uuid,jsonb,jsonb) TO prm_financial;
    """)


def downgrade() -> None:
    raise RuntimeError("KHR confirmation history is forward-only; downgrade is not supported")
