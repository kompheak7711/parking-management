# ruff: noqa: E501
"""Customer Credit recognition and permanent source history.

Unpublished V1-051 migration under construction; applications and Refund integration
must be completed and verified before the full product candidate is publishable.
"""

from alembic import op
from sqlalchemy import text

revision = "20260906_41"
down_revision = "20260906_40"
branch_labels = None
depends_on = None


def replace_function(signature: str, before: str, after: str) -> None:
    """Assert an existing financial integration point before extending it."""
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"Credit integration source contract changed: {signature}")
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.customer_credits (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            source_payment_id uuid NOT NULL REFERENCES app.payments(id) ON DELETE RESTRICT,
            recognized_usd_cents bigint NOT NULL CHECK(recognized_usd_cents BETWEEN 1 AND 9000000000000000),
            customer_authorization_reference text NOT NULL CHECK(
                customer_authorization_reference=btrim(customer_authorization_reference)
                AND length(customer_authorization_reference) BETWEEN 1 AND 500),
            recognized_at timestamptz NOT NULL CHECK(isfinite(recognized_at)),
            recognized_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK(reason=btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
            authorization_reference text NOT NULL CHECK(authorization_reference='credits.recognize')
        );
        CREATE INDEX customer_credits_source_idx ON app.customer_credits(source_payment_id,recognized_at,id);
        CREATE INDEX customer_credits_customer_idx ON app.customer_credits(customer_id,recognized_at,id);
        CREATE TABLE app.customer_credit_reversals (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            customer_credit_id uuid NOT NULL UNIQUE REFERENCES app.customer_credits(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK(reason=btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK(authorization_reference='credits.reverse')
        );
        CREATE TABLE app.credit_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            action text NOT NULL CHECK(action IN ('RECOGNIZE','REVERSE')),
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            request jsonb NOT NULL CHECK(jsonb_typeof(request)='object'),
            response jsonb NOT NULL CHECK(jsonb_typeof(response)='object'),
            completed_at timestamptz NOT NULL CHECK(isfinite(completed_at)),
            PRIMARY KEY(property_id,actor_id,action,idempotency_key)
        );

        CREATE FUNCTION app.payment_credit_value_at(p_payment_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(credit.recognized_usd_cents),0)::bigint
            FROM app.customer_credits credit
            LEFT JOIN app.customer_credit_reversals reversal ON reversal.customer_credit_id=credit.id
            WHERE credit.source_payment_id=p_payment_id AND credit.recognized_at<=p_as_of
                AND (reversal.id IS NULL OR reversal.occurred_at>p_as_of)
        $$;

        CREATE FUNCTION app.credit_available_value(p_credit_id uuid)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT CASE WHEN EXISTS(SELECT 1 FROM app.customer_credit_reversals
                WHERE customer_credit_id=credit.id) THEN 0 ELSE credit.recognized_usd_cents END
            FROM app.customer_credits credit WHERE id=p_credit_id
        $$;
        COMMENT ON FUNCTION app.credit_available_value(uuid) IS
            'Unpublished V1-051 recognition slice. Application and net Credit Refund consumers must be integrated before release.';

        CREATE FUNCTION app.assert_payment_excess_eligible(p_payment_id uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE;
        BEGIN
            -- A snapshot predating the obligation-set lock cannot classify excess.
            -- Service transactions use READ COMMITTED; reject unsafe direct callers.
            IF current_setting('transaction_isolation')<>'read committed' THEN
                RAISE EXCEPTION 'Excess disposition requires READ COMMITTED' USING ERRCODE='40001';
            END IF;
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=p_payment_id;
            -- Hold the obligation set stable while classifying true excess. These
            -- conservative short-lived locks also cover new Invoice/Charge rows.
            -- Never wait for a table lock while holding the Payment source lock:
            -- allocation/correction paths can hold a conflicting table lock first.
            LOCK TABLE app.invoices,app.invoice_lines,app.invoice_adjustments,
                app.invoice_adjustment_reversals,app.invoice_void_events,
                app.late_payment_charges,app.late_payment_charge_corrections,
                app.late_payment_decisions,app.payment_allocations,
                app.payment_allocation_reversals IN SHARE MODE NOWAIT;
            IF EXISTS(
                SELECT 1 FROM app.invoices invoice
                WHERE app.invoice_property_id(invoice.id)=v_payment.property_id
                    AND invoice.status IN ('UNPAID','PARTIALLY_PAID')
                    AND v_payment.identified_late_payment_charge_id IS NULL
                    AND (v_payment.identified_invoice_id IS NULL OR invoice.id=v_payment.identified_invoice_id)
                    AND ((v_payment.payment_scope_kind='NORMAL_CUSTOMER' AND invoice.customer_id=v_payment.payer_customer_id)
                        OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                            AND (v_payment.lease_id IS NULL OR invoice.lease_id=v_payment.lease_id)))
                    AND EXISTS(SELECT 1 FROM app.invoice_lines line WHERE line.invoice_id=invoice.id
                        AND app.invoice_line_outstanding(line.id)>0)
            ) OR EXISTS(
                SELECT 1 FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                JOIN app.late_payment_charge_financial_position position ON position.late_payment_charge_id=charge.id
                WHERE app.invoice_property_id(invoice.id)=v_payment.property_id
                    AND position.remaining_balance_usd_cents>0
                    AND (v_payment.identified_late_payment_charge_id IS NULL OR charge.id=v_payment.identified_late_payment_charge_id)
                    AND (v_payment.identified_invoice_id IS NULL OR invoice.id=v_payment.identified_invoice_id)
                    AND ((v_payment.payment_scope_kind='NORMAL_CUSTOMER' AND charge.customer_id=v_payment.payer_customer_id)
                        OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                            AND (v_payment.lease_id IS NULL OR invoice.lease_id=v_payment.lease_id)))
            ) THEN RAISE EXCEPTION 'Applicable obligations must be handled before excess disposition' USING ERRCODE='23514'; END IF;
        END $$;

        CREATE FUNCTION app.validate_credit_recognition()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE;
        BEGIN
            PERFORM app.serialize_payment_state(NEW.source_payment_id);
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=NEW.source_payment_id FOR UPDATE;
            PERFORM app.assert_active_financial_actor(NEW.recognized_by,NULL);
            PERFORM app.assert_active_financial_actor(NEW.recognized_by,v_payment.property_id);
            PERFORM app.assert_payment_excess_eligible(v_payment.id);
            IF v_payment.status<>'RECEIVED' OR NEW.customer_id IS DISTINCT FROM v_payment.payer_customer_id
                OR NEW.recognized_usd_cents>app.payment_available_value(v_payment.id)
                OR NEW.recognized_at<v_payment.confirmed_at
                OR NEW.recognized_at<app.payment_proposal_dependency_at(v_payment.id)
                OR NEW.recognized_at>clock_timestamp()+interval '5 seconds'
            THEN RAISE EXCEPTION 'Credit recognition source, amount or chronology is invalid' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER customer_credits_validate BEFORE INSERT ON app.customer_credits
            FOR EACH ROW EXECUTE FUNCTION app.validate_credit_recognition();

        CREATE FUNCTION app.validate_credit_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_credit app.customer_credits%ROWTYPE; v_property uuid;
        BEGIN
            SELECT * INTO STRICT v_credit FROM app.customer_credits WHERE id=NEW.customer_credit_id;
            PERFORM app.serialize_payment_state(v_credit.source_payment_id);
            PERFORM 1 FROM app.payments WHERE id=v_credit.source_payment_id FOR UPDATE;
            PERFORM 1 FROM app.customer_credits WHERE id=v_credit.id FOR UPDATE;
            SELECT property_id INTO STRICT v_property FROM app.payments WHERE id=v_credit.source_payment_id;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,NULL);
            PERFORM app.assert_active_financial_actor(NEW.actor_id,v_property);
            IF NEW.occurred_at<v_credit.recognized_at OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
                OR EXISTS(SELECT 1 FROM app.customer_credit_reversals WHERE customer_credit_id=v_credit.id)
                OR app.credit_available_value(v_credit.id)<>v_credit.recognized_usd_cents
            THEN RAISE EXCEPTION 'Credit reversal requires resolved dispositions and valid chronology' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER customer_credit_reversals_validate BEFORE INSERT ON app.customer_credit_reversals
            FOR EACH ROW EXECUTE FUNCTION app.validate_credit_reversal();

        CREATE FUNCTION app.audit_credit_event()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_credit app.customer_credits%ROWTYPE; v_payment app.payments%ROWTYPE;
        DECLARE v_actor uuid; v_at timestamptz; v_action text;
        BEGIN
            IF TG_TABLE_NAME='customer_credits' THEN
                v_credit:=NEW; v_actor:=NEW.recognized_by; v_at:=NEW.recognized_at; v_action:='credit.recognized';
            ELSE
                SELECT * INTO STRICT v_credit FROM app.customer_credits WHERE id=NEW.customer_credit_id;
                v_actor:=NEW.actor_id; v_at:=NEW.occurred_at; v_action:='credit.reversed';
            END IF;
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_credit.source_payment_id;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,v_actor,v_action,
                'customer_credit',v_credit.id,NEW.reason,NEW.authorization_reference,v_payment.property_id,
                jsonb_build_object('credit_id',v_credit.id,'source_payment_id',v_credit.source_payment_id,
                    'recognized_usd_cents',v_credit.recognized_usd_cents,'customer_authorization_reference',
                    v_credit.customer_authorization_reference,'event',v_action),
                NEW.id,'API','SUCCESS',v_credit.customer_id,v_payment.lease_id);
            RETURN NULL;
        END $$;
        CREATE TRIGGER customer_credits_audit AFTER INSERT ON app.customer_credits
            FOR EACH ROW EXECUTE FUNCTION app.audit_credit_event();
        CREATE TRIGGER customer_credit_reversals_audit AFTER INSERT ON app.customer_credit_reversals
            FOR EACH ROW EXECUTE FUNCTION app.audit_credit_event();

        CREATE FUNCTION app.credit_command_replay(
            p_property_id uuid,p_actor_id uuid,p_action text,p_key uuid,p_request jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_command app.credit_commands%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            IF p_action IS NULL OR p_action NOT IN ('RECOGNIZE','REVERSE')
                OR p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_request IS NULL OR jsonb_typeof(p_request)<>'object'
            THEN RAISE EXCEPTION 'Credit command identity is invalid' USING ERRCODE='P5102'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('credit-command:'||p_property_id::text
                ||':'||p_actor_id::text||':'||p_action||':'||p_key::text,0));
            SELECT * INTO v_command FROM app.credit_commands WHERE property_id=p_property_id
                AND actor_id=p_actor_id AND action=p_action AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_command.request IS DISTINCT FROM p_request
                THEN RAISE EXCEPTION 'Credit idempotency key reused' USING ERRCODE='P5105'; END IF;
                RETURN v_command.response;
            END IF;
            RETURN NULL;
        END $$;

        CREATE FUNCTION app.credit_resource(p_property_id uuid,p_credit_id uuid,p_actor_id uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_credit app.customer_credits%ROWTYPE; v_payment app.payments%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            SELECT credit.* INTO v_credit FROM app.customer_credits credit
                JOIN app.payments payment ON payment.id=credit.source_payment_id
                WHERE credit.id=p_credit_id AND payment.property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Credit not found' USING ERRCODE='P5101'; END IF;
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_credit.source_payment_id FOR SHARE;
            RETURN jsonb_build_object('credit',to_jsonb(v_credit),'available_usd_cents',app.credit_available_value(v_credit.id),
                'source_payment',to_jsonb(v_payment),'exchange_rate',(SELECT to_jsonb(rate)
                    FROM app.exchange_rate_records rate WHERE rate.id=v_payment.exchange_rate_record_id),
                'recognition_reversal',(SELECT to_jsonb(reversal) FROM app.customer_credit_reversals reversal
                    WHERE reversal.customer_credit_id=v_credit.id));
        END $$;

        CREATE FUNCTION app.recognize_customer_credit(
            p_property_id uuid,p_payment_id uuid,p_actor_id uuid,p_key uuid,p_amount bigint,
            p_payer_authorization text,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_request jsonb; v_result jsonb; v_id uuid:=gen_random_uuid();
        BEGIN
            v_request:=jsonb_build_object('payment_id',p_payment_id,'amount_usd_cents',p_amount,
                'payer_authorization',p_payer_authorization,'reason',p_reason);
            v_result:=app.credit_command_replay(p_property_id,p_actor_id,'RECOGNIZE',p_key,v_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_payer_authorization IS NULL OR p_payer_authorization<>btrim(p_payer_authorization)
                OR length(p_payer_authorization) NOT BETWEEN 1 AND 500
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Credit recognition input is invalid' USING ERRCODE='P5102'; END IF;
            SELECT * INTO v_payment FROM app.payments WHERE id=p_payment_id AND property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Payment not found' USING ERRCODE='P5101'; END IF;
            INSERT INTO app.customer_credits(id,customer_id,source_payment_id,recognized_usd_cents,
                customer_authorization_reference,recognized_at,recognized_by,reason,authorization_reference)
            VALUES(v_id,v_payment.payer_customer_id,p_payment_id,p_amount,p_payer_authorization,
                clock_timestamp(),p_actor_id,p_reason,'credits.recognize');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.credit_resource(p_property_id,v_id,p_actor_id);
            INSERT INTO app.credit_commands VALUES(p_property_id,p_actor_id,'RECOGNIZE',p_key,v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.reverse_customer_credit(
            p_property_id uuid,p_credit_id uuid,p_actor_id uuid,p_key uuid,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_request jsonb; v_result jsonb;
        BEGIN
            v_request:=jsonb_build_object('credit_id',p_credit_id,'reason',p_reason);
            v_result:=app.credit_command_replay(p_property_id,p_actor_id,'REVERSE',p_key,v_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Credit reversal input is invalid' USING ERRCODE='P5102'; END IF;
            PERFORM 1 FROM app.customer_credits credit JOIN app.payments payment ON payment.id=credit.source_payment_id
                WHERE credit.id=p_credit_id AND payment.property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Credit not found' USING ERRCODE='P5101'; END IF;
            INSERT INTO app.customer_credit_reversals(id,customer_credit_id,reason,occurred_at,actor_id,authorization_reference)
            VALUES(gen_random_uuid(),p_credit_id,p_reason,clock_timestamp(),p_actor_id,'credits.reverse');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.credit_resource(p_property_id,p_credit_id,p_actor_id);
            INSERT INTO app.credit_commands VALUES(p_property_id,p_actor_id,'REVERSE',p_key,v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
    """)
    replace_function(
        "app.payment_disposition_summary(uuid)",
        "'credit_usd_cents',0",
        "'credit_usd_cents',app.payment_credit_value_at(p_payment_id,'infinity'::timestamptz)",
    )
    replace_function(
        "app.validate_payment_history_budget()",
        "IF TG_TABLE_NAME IN ('payment_allocations','deposit_receipts') THEN",
        """IF TG_TABLE_NAME='customer_credits' THEN
                v_payment_id:=NEW.source_payment_id;
            ELSIF TG_TABLE_NAME='customer_credit_reversals' THEN
                SELECT source_payment_id INTO STRICT v_payment_id FROM app.customer_credits
                    WHERE id=NEW.customer_credit_id;
            ELSIF TG_TABLE_NAME IN ('payment_allocations','deposit_receipts') THEN""",
    )
    replace_function(
        "app.validate_payment_history_budget()",
        "), positions AS (",
        """UNION ALL SELECT recognized_at,recognized_usd_cents::numeric FROM app.customer_credits
                        WHERE source_payment_id=v_payment_id
                    UNION ALL SELECT reversal.occurred_at,-credit.recognized_usd_cents::numeric
                        FROM app.customer_credit_reversals reversal
                        JOIN app.customer_credits credit ON credit.id=reversal.customer_credit_id
                        WHERE credit.source_payment_id=v_payment_id
                ), positions AS (""",
    )
    credit_events = """
                UNION ALL SELECT recognized_at FROM app.customer_credits WHERE source_payment_id=NEW.payment_id
                UNION ALL SELECT reversal.occurred_at FROM app.customer_credit_reversals reversal
                    JOIN app.customer_credits credit ON credit.id=reversal.customer_credit_id
                    WHERE credit.source_payment_id=NEW.payment_id
            ) dependency_events;"""
    replace_function("app.validate_payment_reversal()", ") dependency_events;", credit_events)
    replace_function(
        "app.payment_proposal_dependency_at(uuid)",
        ") SELECT max(event_at) FROM events",
        """UNION ALL SELECT recognized_at FROM app.customer_credits WHERE source_payment_id=p_payment_id
                UNION ALL SELECT reversal.occurred_at FROM app.customer_credit_reversals reversal
                    JOIN app.customer_credits credit ON credit.id=reversal.customer_credit_id
                    WHERE credit.source_payment_id=p_payment_id
                UNION ALL SELECT GREATEST(charge.created_at,charge.payable_at,
                    app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',charge.id))
                    FROM app.late_payment_charges charge
                    JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id CROSS JOIN source
                    WHERE app.invoice_property_id(invoice.id)=source.property_id
                        AND (source.identified_late_payment_charge_id IS NULL OR charge.id=source.identified_late_payment_charge_id)
                        AND (source.identified_invoice_id IS NULL OR invoice.id=source.identified_invoice_id)
                        AND ((source.payment_scope_kind='NORMAL_CUSTOMER' AND charge.customer_id=source.payer_customer_id)
                            OR (source.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                                AND (source.lease_id IS NULL OR invoice.lease_id=source.lease_id)))
            ) SELECT max(event_at) FROM events""",
    )
    for table in ("customer_credits", "customer_credit_reversals", "credit_commands"):
        op.execute(f"""
            CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.reject_payment_history_mutation();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION app.reject_payment_history_mutation();
            REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        """)
        if table != "credit_commands":
            op.execute(f"""
                CREATE CONSTRAINT TRIGGER {table}_payment_history_budget AFTER INSERT ON app.{table}
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_payment_history_budget();
            """)
    for signature in (
        "payment_credit_value_at(uuid,timestamptz)",
        "credit_available_value(uuid)",
        "assert_payment_excess_eligible(uuid)",
        "validate_credit_recognition()",
        "validate_credit_reversal()",
        "audit_credit_event()",
        "credit_command_replay(uuid,uuid,text,uuid,jsonb)",
        "credit_resource(uuid,uuid,uuid)",
        "recognize_customer_credit(uuid,uuid,uuid,uuid,bigint,text,text)",
        "reverse_customer_credit(uuid,uuid,uuid,uuid,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.credit_resource(uuid,uuid,uuid) TO prm_runtime,prm_financial"
    )
    for signature in (
        "recognize_customer_credit(uuid,uuid,uuid,uuid,bigint,text,text)",
        "reverse_customer_credit(uuid,uuid,uuid,uuid,text)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError(
        "Credit and Refund history is forward-only; use an approved forward migration"
    )
