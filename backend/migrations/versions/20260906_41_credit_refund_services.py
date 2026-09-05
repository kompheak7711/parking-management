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
            action text NOT NULL CHECK(action IN ('RECOGNIZE','REVERSE','APPLY','REVERSE_APPLICATION')),
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
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE
                (SELECT timezone_name FROM app.properties WHERE id=v_payment.property_id))::date,v_actor,v_action,
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
            IF p_action IS NULL OR p_action NOT IN ('RECOGNIZE','REVERSE','APPLY','REVERSE_APPLICATION')
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

    create_credit_application_storage()
    integrate_credit_applications()
    create_credit_application_services()


def create_credit_application_storage() -> None:
    """Add explicit Credit events; never masquerade as Payment Allocations."""
    op.execute("""
        CREATE TABLE app.customer_credit_applications (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            customer_credit_id uuid NOT NULL REFERENCES app.customer_credits(id) ON DELETE RESTRICT,
            target_kind text NOT NULL CHECK(target_kind IN ('INVOICE','LATE_PAYMENT_CHARGE')),
            invoice_id uuid REFERENCES app.invoices(id) ON DELETE RESTRICT,
            late_payment_charge_id uuid REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
            final_settlement_id uuid CHECK(final_settlement_id IS NULL),
            amount_usd_cents bigint NOT NULL CHECK(amount_usd_cents BETWEEN 1 AND 9000000000000000),
            within_invoice_basis text NOT NULL CHECK(within_invoice_basis IN
                ('RENT_THEN_RECURRING_SERVICES_PROPOSAL','CUSTOMER_DESIGNATED','OTHER_APPLICABLE_OBLIGATION','NOT_APPLICABLE')),
            customer_designation_reference text CHECK(customer_designation_reference=btrim(customer_designation_reference)
                AND length(customer_designation_reference) BETWEEN 1 AND 500),
            proposal_generated_at timestamptz CHECK(isfinite(proposal_generated_at)),
            proposal_trace jsonb CHECK(jsonb_typeof(proposal_trace)='object' AND octet_length(proposal_trace::text)<=200000),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK(authorization_reference='credits.apply'),
            CHECK((target_kind='INVOICE' AND invoice_id IS NOT NULL AND late_payment_charge_id IS NULL
                    AND within_invoice_basis<>'NOT_APPLICABLE')
                OR (target_kind='LATE_PAYMENT_CHARGE' AND invoice_id IS NULL AND late_payment_charge_id IS NOT NULL
                    AND within_invoice_basis IN ('NOT_APPLICABLE','CUSTOMER_DESIGNATED'))),
            CHECK((within_invoice_basis='RENT_THEN_RECURRING_SERVICES_PROPOSAL'
                    AND proposal_generated_at IS NOT NULL AND proposal_trace IS NOT NULL
                    AND customer_designation_reference IS NULL)
                OR (within_invoice_basis<>'RENT_THEN_RECURRING_SERVICES_PROPOSAL'
                    AND proposal_generated_at IS NULL AND proposal_trace IS NULL)),
            CHECK((within_invoice_basis='CUSTOMER_DESIGNATED')=(customer_designation_reference IS NOT NULL))
        );
        CREATE INDEX customer_credit_applications_source_idx
            ON app.customer_credit_applications(customer_credit_id,occurred_at,id);
        CREATE INDEX customer_credit_applications_invoice_idx
            ON app.customer_credit_applications(invoice_id,occurred_at) WHERE invoice_id IS NOT NULL;
        CREATE INDEX customer_credit_applications_charge_idx
            ON app.customer_credit_applications(late_payment_charge_id,occurred_at) WHERE late_payment_charge_id IS NOT NULL;
        CREATE TABLE app.customer_credit_application_reversals (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            credit_application_id uuid NOT NULL UNIQUE REFERENCES app.customer_credit_applications(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK(reason=btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK(authorization_reference='credits.applications.reverse')
        );
        CREATE TABLE app.customer_credit_application_details (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            customer_credit_application_id uuid NOT NULL REFERENCES app.customer_credit_applications(id) ON DELETE RESTRICT,
            invoice_line_id uuid REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            late_payment_charge_id uuid REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
            obligation_kind text NOT NULL CHECK(obligation_kind IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')),
            invoice_line_category_snapshot text,
            proposed_amount_usd_cents bigint CHECK(proposed_amount_usd_cents BETWEEN 1 AND 9000000000000000),
            applied_amount_usd_cents bigint NOT NULL CHECK(applied_amount_usd_cents BETWEEN 1 AND 9000000000000000),
            attribution_basis text NOT NULL CHECK(attribution_basis IN
                ('RENT_FIRST_PROPOSAL','SERVICE_PROPOSAL','CUSTOMER_DESIGNATED','OTHER_CONFIRMED','DIRECT_LATE_PAYMENT_CHARGE')),
            detail_sequence smallint NOT NULL CHECK(detail_sequence BETWEEN 1 AND 500),
            calculation_trace jsonb NOT NULL CHECK(jsonb_typeof(calculation_trace)='object'
                AND octet_length(calculation_trace::text)<=200000),
            UNIQUE(customer_credit_application_id,detail_sequence),
            UNIQUE(customer_credit_application_id,invoice_line_id),
            CHECK((obligation_kind='INVOICE_LINE' AND invoice_line_id IS NOT NULL
                    AND late_payment_charge_id IS NULL AND invoice_line_category_snapshot IS NOT NULL)
                OR (obligation_kind='LATE_PAYMENT_CHARGE' AND invoice_line_id IS NULL
                    AND late_payment_charge_id IS NOT NULL AND invoice_line_category_snapshot IS NULL))
        );
        CREATE INDEX customer_credit_application_details_line_idx
            ON app.customer_credit_application_details(invoice_line_id) WHERE invoice_line_id IS NOT NULL;

        CREATE FUNCTION app.credit_applied_value_at(p_credit_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(application.amount_usd_cents),0)::bigint
            FROM app.customer_credit_applications application
            LEFT JOIN app.customer_credit_application_reversals reversal ON reversal.credit_application_id=application.id
            WHERE application.customer_credit_id=p_credit_id AND application.occurred_at<=p_as_of
                AND (reversal.id IS NULL OR reversal.occurred_at>p_as_of)
        $$;
        CREATE FUNCTION app.credit_latest_at(p_credit_id uuid)
        RETURNS timestamptz LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT max(event_at) FROM (
                SELECT recognized_at AS event_at FROM app.customer_credits WHERE id=p_credit_id
                UNION ALL SELECT occurred_at FROM app.customer_credit_reversals WHERE customer_credit_id=p_credit_id
                UNION ALL SELECT occurred_at FROM app.customer_credit_applications WHERE customer_credit_id=p_credit_id
                UNION ALL SELECT reversal.occurred_at FROM app.customer_credit_application_reversals reversal
                    JOIN app.customer_credit_applications application ON application.id=reversal.credit_application_id
                    WHERE application.customer_credit_id=p_credit_id
            ) events
        $$;
        CREATE OR REPLACE FUNCTION app.credit_available_value(p_credit_id uuid)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT CASE WHEN EXISTS(SELECT 1 FROM app.customer_credit_reversals
                WHERE customer_credit_id=credit.id) THEN 0 ELSE credit.recognized_usd_cents
                    -app.credit_applied_value_at(credit.id,'infinity') END
            FROM app.customer_credits credit WHERE credit.id=p_credit_id
        $$;
        COMMENT ON FUNCTION app.credit_available_value(uuid) IS
            'Unpublished V1-051 recognition/application slice; net Credit Refund consumers remain to integrate before release.';
        CREATE FUNCTION app.invoice_line_credit_value_at(p_line_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(detail.applied_amount_usd_cents),0)::bigint
            FROM app.customer_credit_application_details detail
            JOIN app.customer_credit_applications application ON application.id=detail.customer_credit_application_id
            LEFT JOIN app.customer_credit_application_reversals reversal ON reversal.credit_application_id=application.id
            WHERE detail.invoice_line_id=p_line_id AND application.occurred_at<=p_as_of
                AND (reversal.id IS NULL OR reversal.occurred_at>p_as_of)
        $$;
        CREATE FUNCTION app.invoice_line_application_value_at(p_line_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT (app.invoice_line_payment_value_at(p_line_id,p_as_of)::numeric
                +app.invoice_line_credit_value_at(p_line_id,p_as_of))::bigint
        $$;

        CREATE FUNCTION app.validate_credit_application_source()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_credit app.customer_credits%ROWTYPE; v_payment app.payments%ROWTYPE;
        DECLARE v_customer uuid; v_property uuid; v_source_at timestamptz; v_balance bigint; v_invoice app.invoices%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT v_credit FROM app.customer_credits WHERE id=NEW.customer_credit_id;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,NULL);
            PERFORM app.serialize_payment_state(v_credit.source_payment_id);
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_credit.source_payment_id FOR UPDATE;
            PERFORM 1 FROM app.customer_credits WHERE id=v_credit.id FOR UPDATE;
            PERFORM app.lock_payment_allocation_target(NEW.target_kind,COALESCE(NEW.invoice_id,NEW.late_payment_charge_id));
            IF NEW.target_kind='INVOICE' THEN
                SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=NEW.invoice_id;
                v_customer:=v_invoice.customer_id; v_property:=app.invoice_property_id(v_invoice.id);
                v_source_at:=GREATEST(v_invoice.issued_at,v_invoice.updated_at);
                SELECT COALESCE(sum(app.invoice_line_outstanding(id)),0)::bigint INTO v_balance
                    FROM app.invoice_lines WHERE invoice_id=v_invoice.id;
                IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
                    RAISE EXCEPTION 'Credit requires an issued non-VOID Invoice' USING ERRCODE='23514';
                END IF;
                IF NEW.within_invoice_basis='OTHER_APPLICABLE_OBLIGATION' AND EXISTS(
                    SELECT 1 FROM app.invoice_lines WHERE invoice_id=v_invoice.id AND category IN ('RENT','SERVICE_CHARGES'))
                THEN RAISE EXCEPTION 'Rent and Service applications require proposal or designation' USING ERRCODE='23514'; END IF;
                IF NEW.proposal_trace IS NOT NULL AND (
                    NEW.amount_usd_cents IS DISTINCT FROM (NEW.proposal_trace->>'amount_usd_cents')::bigint
                    OR NEW.proposal_trace IS DISTINCT FROM app.credit_application_proposal(
                        v_payment.property_id,v_credit.id,v_invoice.id,
                        (NEW.proposal_trace->>'requested_amount_usd_cents')::bigint,NEW.proposal_generated_at))
                THEN RAISE EXCEPTION 'Credit proposal changed; obtain a fresh proposal' USING ERRCODE='P5104'; END IF;
            ELSE
                SELECT charge.customer_id,app.invoice_property_id(invoice.id),
                    GREATEST(charge.created_at,charge.payable_at),position.remaining_balance_usd_cents
                INTO STRICT v_customer,v_property,v_source_at,v_balance
                FROM app.late_payment_charges charge JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                JOIN app.late_payment_charge_financial_position position ON position.late_payment_charge_id=charge.id
                WHERE charge.id=NEW.late_payment_charge_id;
            END IF;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,v_property);
            IF v_payment.status<>'RECEIVED' OR EXISTS(SELECT 1 FROM app.customer_credit_reversals WHERE customer_credit_id=v_credit.id)
                OR v_customer IS DISTINCT FROM v_credit.customer_id OR v_property IS DISTINCT FROM v_payment.property_id
                OR NEW.amount_usd_cents>app.credit_available_value(v_credit.id) OR NEW.amount_usd_cents>v_balance
                OR NEW.occurred_at<v_source_at OR NEW.occurred_at<=app.credit_latest_at(v_credit.id)
                OR NEW.occurred_at<=app.allocation_target_latest_at(NEW.target_kind,COALESCE(NEW.invoice_id,NEW.late_payment_charge_id))
                OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
                OR NEW.proposal_generated_at>NEW.occurred_at
            THEN RAISE EXCEPTION 'Credit application source, target, amount or chronology is invalid' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER customer_credit_applications_validate BEFORE INSERT ON app.customer_credit_applications
            FOR EACH ROW EXECUTE FUNCTION app.validate_credit_application_source();

        CREATE FUNCTION app.validate_credit_application_complete()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_id uuid; v_header app.customer_credit_applications%ROWTYPE; v_total numeric; v_count integer;
        BEGIN
            IF TG_TABLE_NAME='customer_credit_applications' THEN v_id:=NEW.id;
            ELSE v_id:=NEW.customer_credit_application_id; END IF;
            SELECT * INTO STRICT v_header FROM app.customer_credit_applications WHERE id=v_id;
            SELECT sum(applied_amount_usd_cents),count(*) INTO v_total,v_count
                FROM app.customer_credit_application_details WHERE customer_credit_application_id=v_id;
            IF v_total IS DISTINCT FROM v_header.amount_usd_cents::numeric OR v_count NOT BETWEEN 1 AND 500 THEN
                RAISE EXCEPTION 'Credit application header and details must reconcile' USING ERRCODE='23514';
            END IF;
            IF TG_TABLE_NAME='customer_credit_application_details' THEN RETURN NULL; END IF;
            IF (v_header.target_kind='LATE_PAYMENT_CHARGE' AND v_count<>1)
                OR EXISTS(SELECT 1 FROM app.customer_credit_application_details detail
                    LEFT JOIN app.invoice_lines line ON line.id=detail.invoice_line_id
                    WHERE detail.customer_credit_application_id=v_id AND (
                        (v_header.target_kind='INVOICE' AND (detail.obligation_kind<>'INVOICE_LINE'
                            OR line.invoice_id IS DISTINCT FROM v_header.invoice_id
                            OR line.category IS DISTINCT FROM detail.invoice_line_category_snapshot))
                        OR (v_header.target_kind='LATE_PAYMENT_CHARGE' AND (detail.obligation_kind<>'LATE_PAYMENT_CHARGE'
                            OR detail.late_payment_charge_id IS DISTINCT FROM v_header.late_payment_charge_id))
                        OR ((v_header.proposal_trace IS NULL) IS DISTINCT FROM (detail.proposed_amount_usd_cents IS NULL))
                        OR (v_header.proposal_trace IS NOT NULL AND (
                            detail.applied_amount_usd_cents IS DISTINCT FROM detail.proposed_amount_usd_cents
                            OR detail.invoice_line_id IS DISTINCT FROM
                                (v_header.proposal_trace->'details'->(detail.detail_sequence-1)->>'invoice_line_id')::uuid
                            OR detail.proposed_amount_usd_cents IS DISTINCT FROM
                                (v_header.proposal_trace->'details'->(detail.detail_sequence-1)->>'amount_usd_cents')::bigint
                            OR detail.attribution_basis IS DISTINCT FROM
                                v_header.proposal_trace->'details'->(detail.detail_sequence-1)->>'attribution_basis'))
                        OR (v_header.within_invoice_basis='CUSTOMER_DESIGNATED' AND detail.attribution_basis<>'CUSTOMER_DESIGNATED')
                        OR (v_header.within_invoice_basis='NOT_APPLICABLE' AND detail.attribution_basis<>'DIRECT_LATE_PAYMENT_CHARGE')
                        OR (v_header.within_invoice_basis='OTHER_APPLICABLE_OBLIGATION' AND detail.attribution_basis<>'OTHER_CONFIRMED')))
                OR app.credit_available_value(v_header.customer_credit_id)<0
                OR EXISTS(SELECT 1 FROM app.customer_credit_application_details detail
                    WHERE detail.customer_credit_application_id=v_id AND detail.invoice_line_id IS NOT NULL
                        AND app.invoice_line_outstanding(detail.invoice_line_id)<0)
                OR EXISTS(SELECT 1 FROM app.late_payment_charge_financial_position position
                    WHERE position.late_payment_charge_id=v_header.late_payment_charge_id AND position.remaining_balance_usd_cents<0)
            THEN RAISE EXCEPTION 'Credit attribution and financial position must reconcile' USING ERRCODE='23514'; END IF;
            IF v_header.invoice_id IS NOT NULL THEN
                PERFORM app.refresh_allocated_invoice(v_header.invoice_id,v_header.actor_id,false);
            END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER customer_credit_applications_complete AFTER INSERT ON app.customer_credit_applications
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_credit_application_complete();
        CREATE CONSTRAINT TRIGGER customer_credit_application_details_complete AFTER INSERT ON app.customer_credit_application_details
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_credit_application_complete();

        CREATE FUNCTION app.validate_credit_application_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_application app.customer_credit_applications%ROWTYPE; v_credit app.customer_credits%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT v_application FROM app.customer_credit_applications WHERE id=NEW.credit_application_id;
            SELECT * INTO STRICT v_credit FROM app.customer_credits WHERE id=v_application.customer_credit_id;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,NULL);
            PERFORM app.serialize_payment_state(v_credit.source_payment_id);
            PERFORM 1 FROM app.payments WHERE id=v_credit.source_payment_id FOR UPDATE;
            PERFORM 1 FROM app.customer_credits WHERE id=v_credit.id FOR UPDATE;
            PERFORM app.lock_payment_allocation_target(v_application.target_kind,
                COALESCE(v_application.invoice_id,v_application.late_payment_charge_id));
            PERFORM app.assert_active_financial_actor(NEW.actor_id,
                (SELECT property_id FROM app.payments WHERE id=v_credit.source_payment_id));
            IF NEW.occurred_at<=app.credit_latest_at(v_credit.id)
                OR NEW.occurred_at<=app.allocation_target_latest_at(v_application.target_kind,
                    COALESCE(v_application.invoice_id,v_application.late_payment_charge_id))
                OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
                OR EXISTS(SELECT 1 FROM app.customer_credit_application_reversals WHERE credit_application_id=v_application.id)
                OR EXISTS(SELECT 1 FROM app.customer_credit_reversals WHERE customer_credit_id=v_credit.id)
            THEN RAISE EXCEPTION 'Credit application reversal chronology is invalid' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER customer_credit_application_reversals_validate BEFORE INSERT ON app.customer_credit_application_reversals
            FOR EACH ROW EXECUTE FUNCTION app.validate_credit_application_reversal();
        CREATE FUNCTION app.reconcile_credit_application_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_invoice uuid;
        BEGIN
            SELECT invoice_id INTO v_invoice FROM app.customer_credit_applications WHERE id=NEW.credit_application_id;
            IF v_invoice IS NOT NULL THEN PERFORM app.refresh_allocated_invoice(v_invoice,NEW.actor_id,true); END IF;
            RETURN NULL;
        END $$;
        CREATE TRIGGER customer_credit_application_reversals_reconcile AFTER INSERT ON app.customer_credit_application_reversals
            FOR EACH ROW EXECUTE FUNCTION app.reconcile_credit_application_reversal();

        CREATE FUNCTION app.validate_credit_history_budget()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_credit_id uuid; v_original bigint;
        BEGIN
            IF TG_TABLE_NAME='customer_credits' THEN v_credit_id:=NEW.id;
            ELSIF TG_TABLE_NAME='customer_credit_application_reversals' THEN
                SELECT customer_credit_id INTO STRICT v_credit_id FROM app.customer_credit_applications WHERE id=NEW.credit_application_id;
            ELSE v_credit_id:=NEW.customer_credit_id; END IF;
            SELECT recognized_usd_cents INTO STRICT v_original FROM app.customer_credits WHERE id=v_credit_id;
            IF EXISTS(WITH events AS (
                SELECT recognized_at AS event_at,recognized_usd_cents::numeric AS delta FROM app.customer_credits WHERE id=v_credit_id
                UNION ALL SELECT occurred_at,-v_original::numeric FROM app.customer_credit_reversals WHERE customer_credit_id=v_credit_id
                UNION ALL SELECT occurred_at,-amount_usd_cents::numeric FROM app.customer_credit_applications WHERE customer_credit_id=v_credit_id
                UNION ALL SELECT reversal.occurred_at,application.amount_usd_cents::numeric
                    FROM app.customer_credit_application_reversals reversal
                    JOIN app.customer_credit_applications application ON application.id=reversal.credit_application_id
                    WHERE application.customer_credit_id=v_credit_id
            ), positions AS (
                SELECT sum(sum(delta)) OVER (ORDER BY event_at) AS available FROM events GROUP BY event_at
            ) SELECT 1 FROM positions WHERE available<0 OR available>v_original)
            THEN RAISE EXCEPTION 'Credit historical availability exceeded' USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;
        CREATE FUNCTION app.audit_credit_application_event()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_application app.customer_credit_applications%ROWTYPE; v_credit app.customer_credits%ROWTYPE;
        DECLARE v_payment app.payments%ROWTYPE; v_action text; v_reason text; v_lease uuid;
        BEGIN
            IF TG_TABLE_NAME='customer_credit_applications' THEN
                v_application:=NEW; v_action:='credit.applied'; v_reason:='Confirmed Credit application';
            ELSE
                SELECT * INTO STRICT v_application FROM app.customer_credit_applications WHERE id=NEW.credit_application_id;
                v_action:='credit.application.reversed'; v_reason:=NEW.reason;
            END IF;
            SELECT * INTO STRICT v_credit FROM app.customer_credits WHERE id=v_application.customer_credit_id;
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_credit.source_payment_id;
            SELECT lease_id INTO v_lease FROM app.invoices WHERE id=COALESCE(v_application.invoice_id,
                (SELECT source_invoice_id FROM app.late_payment_charges WHERE id=v_application.late_payment_charge_id));
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,resulting_state,correlation_id,source,outcome,customer_id,lease_id)
            VALUES(gen_random_uuid(),NEW.occurred_at,(NEW.occurred_at AT TIME ZONE
                (SELECT timezone_name FROM app.properties WHERE id=v_payment.property_id))::date,
                NEW.actor_id,v_action,'customer_credit_application',v_application.id,v_reason,NEW.authorization_reference,
                v_payment.property_id,jsonb_build_object('customer_credit_id',v_credit.id,'source_payment_id',v_payment.id,
                    'amount_usd_cents',v_application.amount_usd_cents,'invoice_id',v_application.invoice_id,
                    'late_payment_charge_id',v_application.late_payment_charge_id,
                    'within_invoice_basis',v_application.within_invoice_basis,
                    'customer_designation_reference',v_application.customer_designation_reference,
                    'event',v_action),NEW.id,'API','SUCCESS',v_credit.customer_id,v_lease);
            RETURN NULL;
        END $$;
    """)
    for table in (
        "customer_credit_applications",
        "customer_credit_application_details",
        "customer_credit_application_reversals",
    ):
        op.execute(f"""
            CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.reject_payment_history_mutation();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION app.reject_payment_history_mutation();
            REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        """)
        if table != "customer_credit_application_details":
            op.execute(f"""
                CREATE TRIGGER {table}_audit AFTER INSERT ON app.{table}
                    FOR EACH ROW EXECUTE FUNCTION app.audit_credit_application_event();
            """)
    for table in (
        "customer_credits",
        "customer_credit_reversals",
        "customer_credit_applications",
        "customer_credit_application_reversals",
    ):
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER {table}_credit_history AFTER INSERT ON app.{table}
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_credit_history_budget();
        """)
    for signature in (
        "credit_applied_value_at(uuid,timestamptz)",
        "credit_latest_at(uuid)",
        "invoice_line_credit_value_at(uuid,timestamptz)",
        "invoice_line_application_value_at(uuid,timestamptz)",
        "validate_credit_application_source()",
        "validate_credit_application_complete()",
        "validate_credit_application_reversal()",
        "reconcile_credit_application_reversal()",
        "validate_credit_history_budget()",
        "audit_credit_application_event()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )


def integrate_credit_applications() -> None:
    """Extend published projections and chronology without replacing their guards."""
    for signature in (
        "app.invoice_line_outstanding_at(uuid,timestamptz)",
        "app.invoice_line_outstanding(uuid)",
        "app.invoice_application_status(uuid)",
        "app.invoice_resource_snapshot(uuid)",
        "app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,text,text,uuid,uuid)",
    ):
        replace_function(
            signature,
            "app.invoice_line_payment_value_at(",
            "app.invoice_line_application_value_at(",
        )
    op.execute("""
        CREATE OR REPLACE FUNCTION app.late_payment_charge_application_summary(p_charge_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            WITH active AS (
                SELECT 'PAYMENT_ALLOCATION'::text AS kind,allocation.id,allocation.payment_id,NULL::uuid AS credit_id,
                    allocation.amount_usd_cents,allocation.posted_at
                FROM app.payment_allocations allocation WHERE allocation.late_payment_charge_id=p_charge_id
                    AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal WHERE reversal.payment_allocation_id=allocation.id)
                UNION ALL SELECT 'CREDIT_APPLICATION',application.id,NULL::uuid,application.customer_credit_id,
                    application.amount_usd_cents,application.occurred_at
                FROM app.customer_credit_applications application WHERE application.late_payment_charge_id=p_charge_id
                    AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal WHERE reversal.credit_application_id=application.id)
            ) SELECT CASE WHEN EXISTS(SELECT 1 FROM app.late_payment_charges WHERE id=p_charge_id)
            THEN jsonb_build_object('active_total_usd_cents',COALESCE(sum(amount_usd_cents),0),
                'payment_total_usd_cents',COALESCE(sum(amount_usd_cents) FILTER(WHERE kind='PAYMENT_ALLOCATION'),0),
                'credit_total_usd_cents',COALESCE(sum(amount_usd_cents) FILTER(WHERE kind='CREDIT_APPLICATION'),0),
                'items',COALESCE(jsonb_agg(CASE WHEN kind='PAYMENT_ALLOCATION'
                    THEN jsonb_build_object('kind',kind,'id',id,'payment_id',payment_id,'amount_usd_cents',amount_usd_cents,'posted_at',posted_at)
                    ELSE jsonb_build_object('kind',kind,'id',id,'customer_credit_id',credit_id,'amount_usd_cents',amount_usd_cents,'posted_at',posted_at)
                    END ORDER BY posted_at,id),'[]'::jsonb)) ELSE NULL END FROM active
        $$;
    """)
    replace_function(
        "app.allocation_target_latest_at(text,uuid)",
        ") events",
        """
                UNION ALL SELECT occurred_at FROM app.customer_credit_applications
                    WHERE (p_kind='INVOICE' AND invoice_id=p_target_id)
                        OR (p_kind='LATE_PAYMENT_CHARGE' AND late_payment_charge_id=p_target_id)
                UNION ALL SELECT reversal.occurred_at FROM app.customer_credit_application_reversals reversal
                    JOIN app.customer_credit_applications application ON application.id=reversal.credit_application_id
                    WHERE (p_kind='INVOICE' AND application.invoice_id=p_target_id)
                        OR (p_kind='LATE_PAYMENT_CHARGE' AND application.late_payment_charge_id=p_target_id)
            ) events""",
    )
    replace_function(
        "app.serialize_invoice_adjustment_source()",
        ") AS financial_events;",
        """
                UNION ALL SELECT occurred_at FROM app.customer_credit_applications WHERE invoice_id=v_invoice_id
                UNION ALL SELECT reversal.occurred_at FROM app.customer_credit_application_reversals reversal
                    JOIN app.customer_credit_applications application ON application.id=reversal.credit_application_id
                    WHERE application.invoice_id=v_invoice_id
            ) AS financial_events;""",
    )
    replace_function(
        "app.validate_invoice_void_event()",
        "IF v_status<>'VOID'",
        """IF v_status<>'VOID'
                OR EXISTS(SELECT 1 FROM app.customer_credit_applications application
                    LEFT JOIN app.customer_credit_application_reversals reversal ON reversal.credit_application_id=application.id
                    WHERE application.invoice_id=NEW.invoice_id AND (reversal.id IS NULL
                        OR reversal.occurred_at>=NEW.occurred_at OR application.occurred_at>=NEW.occurred_at))""",
    )
    replace_function(
        "app.validate_late_payment_decision()",
        "OR NEW.assessed_at<v_invoice.issued_at",
        """OR NEW.assessed_at<v_invoice.issued_at
                OR EXISTS(SELECT 1 FROM app.customer_credit_applications application
                    LEFT JOIN app.customer_credit_application_reversals reversal ON reversal.credit_application_id=application.id
                    WHERE application.invoice_id=NEW.source_invoice_id
                        AND (application.occurred_at BETWEEN NEW.assessed_at AND NEW.finalized_at
                            OR reversal.occurred_at BETWEEN NEW.assessed_at AND NEW.finalized_at))""",
    )
    replace_function(
        "app.serialize_late_charge_correction()",
        "OR NEW.occurred_at<=COALESCE(v_latest_at,'-infinity'::timestamptz)",
        """
                OR NEW.occurred_at<=COALESCE(v_latest_at,'-infinity'::timestamptz)
                OR EXISTS(SELECT 1 FROM app.customer_credit_applications application
                    LEFT JOIN app.customer_credit_application_reversals reversal ON reversal.credit_application_id=application.id
                    WHERE application.late_payment_charge_id=NEW.late_payment_charge_id
                        AND (application.occurred_at>=NEW.occurred_at OR reversal.occurred_at>=NEW.occurred_at))""",
    )
    replace_function(
        "app.validate_credit_reversal()",
        "IF NEW.occurred_at<v_credit.recognized_at",
        """
            IF NEW.occurred_at<=app.credit_latest_at(v_credit.id) OR NEW.occurred_at<v_credit.recognized_at""",
    )
    replace_function(
        "app.assert_payment_excess_eligible(uuid)",
        "app.payment_allocation_reversals IN SHARE MODE NOWAIT;",
        """app.payment_allocation_reversals,app.customer_credit_applications,
                app.customer_credit_application_reversals IN SHARE MODE NOWAIT;""",
    )


def create_credit_application_services() -> None:
    """Bounded target proposals, separate application commands and exact replay."""
    op.execute("""
        CREATE FUNCTION app.credit_application_proposal(
            p_property_id uuid,p_credit_id uuid,p_invoice_id uuid,p_amount bigint,p_generated_at timestamptz
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_credit app.customer_credits%ROWTYPE; v_invoice app.invoices%ROWTYPE;
        DECLARE v_available bigint; v_outstanding numeric; v_remaining bigint; v_amount bigint;
        DECLARE v_details jsonb:='[]'; v_next jsonb; v_line record;
        BEGIN
            SELECT credit.* INTO v_credit FROM app.customer_credits credit
                JOIN app.payments payment ON payment.id=credit.source_payment_id
                WHERE credit.id=p_credit_id AND payment.property_id=p_property_id AND payment.status='RECEIVED';
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id AND customer_id=v_credit.customer_id
                AND app.invoice_property_id(id)=p_property_id AND status IN ('UNPAID','PARTIALLY_PAID');
            IF v_credit.id IS NULL OR v_invoice.id IS NULL
            THEN RAISE EXCEPTION 'Credit or eligible target not found' USING ERRCODE='P5101'; END IF;
            v_available:=app.credit_available_value(p_credit_id);
            SELECT COALESCE(sum(app.invoice_line_outstanding(id)),0) INTO v_outstanding
                FROM app.invoice_lines WHERE invoice_id=p_invoice_id;
            IF p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000 OR p_amount>v_available
                OR p_amount>v_outstanding OR p_generated_at IS NULL OR NOT isfinite(p_generated_at)
                OR p_generated_at>clock_timestamp()+interval '5 seconds'
            THEN RAISE EXCEPTION 'Credit proposal input or available amount is invalid' USING ERRCODE='P5102'; END IF;
            IF p_generated_at<GREATEST(app.credit_latest_at(p_credit_id),v_invoice.issued_at,v_invoice.updated_at,
                    app.allocation_target_latest_at('INVOICE',p_invoice_id))
            THEN RAISE EXCEPTION 'Credit proposal predates financial dependencies' USING ERRCODE='P5104'; END IF;
            v_remaining:=p_amount;
            FOR v_line IN SELECT line.*,app.invoice_line_outstanding(line.id) AS outstanding
                FROM app.invoice_lines line WHERE line.invoice_id=p_invoice_id
                ORDER BY CASE line.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,line.line_sequence,line.id
            LOOP
                EXIT WHEN v_remaining=0;
                IF v_line.outstanding<=0 THEN CONTINUE; END IF;
                EXIT WHEN jsonb_array_length(v_details)>=500;
                v_amount:=LEAST(v_remaining,v_line.outstanding);
                v_next:=v_details||jsonb_build_array(jsonb_build_object('invoice_line_id',v_line.id,
                    'category',v_line.category,'outstanding_usd_cents',v_line.outstanding,'amount_usd_cents',v_amount,
                    'attribution_basis',CASE v_line.category WHEN 'RENT' THEN 'RENT_FIRST_PROPOSAL'
                        WHEN 'SERVICE_CHARGES' THEN 'SERVICE_PROPOSAL' ELSE 'OTHER_CONFIRMED' END));
                -- Leave space for the bounded scalar proposal envelope.
                EXIT WHEN octet_length(v_next::text)>190000;
                v_details:=v_next; v_remaining:=v_remaining-v_amount;
            END LOOP;
            IF jsonb_array_length(v_details)=0
            THEN RAISE EXCEPTION 'Credit target cannot fit bounded proposal' USING ERRCODE='P5102'; END IF;
            RETURN jsonb_build_object('property_id',p_property_id,'credit_id',p_credit_id,'invoice_id',p_invoice_id,
                'customer_id',v_credit.customer_id,'invoice_version',v_invoice.version,
                'requested_amount_usd_cents',p_amount,'amount_usd_cents',p_amount-v_remaining,
                'remaining_requested_usd_cents',v_remaining,'available_usd_cents',v_available,
                'generated_at',p_generated_at,'details',v_details,
                'continuation_status',CASE WHEN v_remaining>0 THEN 'MORE_ELIGIBLE' ELSE 'COMPLETE' END,
                'continuation','CONFIRM_PAGE_THEN_REQUEST_FRESH_PROPOSAL','policy','RENT_SERVICE_SOURCE_ORDER');
        END $$;
        CREATE FUNCTION app.credit_application_proposal_for_actor(
            p_property_id uuid,p_credit_id uuid,p_invoice_id uuid,p_amount bigint,p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            RETURN app.credit_application_proposal(p_property_id,p_credit_id,p_invoice_id,p_amount,clock_timestamp());
        END $$;

        CREATE FUNCTION app.credit_application_resource(p_property_id uuid,p_application_id uuid,p_actor_id uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_application app.customer_credit_applications%ROWTYPE; v_credit app.customer_credits%ROWTYPE;
        DECLARE v_credit_position jsonb; v_invoice uuid; v_balance bigint; v_status text;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            SELECT application.* INTO v_application FROM app.customer_credit_applications application
                JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
                JOIN app.payments payment ON payment.id=credit.source_payment_id
                WHERE application.id=p_application_id AND payment.property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Credit application not found' USING ERRCODE='P5101'; END IF;
            v_credit_position:=app.credit_resource(p_property_id,v_application.customer_credit_id,p_actor_id);
            IF v_application.invoice_id IS NOT NULL THEN
                v_invoice:=v_application.invoice_id;
            ELSE
                SELECT source_invoice_id INTO v_invoice FROM app.late_payment_charges
                    WHERE id=v_application.late_payment_charge_id FOR SHARE;
            END IF;
            PERFORM 1 FROM app.invoices WHERE id=v_invoice FOR SHARE;
            IF v_application.invoice_id IS NOT NULL THEN
                SELECT COALESCE(sum(app.invoice_line_outstanding(id)),0)::bigint INTO v_balance
                    FROM app.invoice_lines WHERE invoice_id=v_invoice;
                SELECT status INTO v_status FROM app.invoices WHERE id=v_invoice;
                IF v_status='VOID' THEN v_balance:=0; END IF;
            ELSE
                SELECT remaining_balance_usd_cents INTO v_balance FROM app.late_payment_charge_financial_position
                    WHERE late_payment_charge_id=v_application.late_payment_charge_id;
                v_status:=NULL;
            END IF;
            RETURN jsonb_build_object('application',to_jsonb(v_application),
                'details',(SELECT jsonb_agg(to_jsonb(detail) ORDER BY detail.detail_sequence)
                    FROM app.customer_credit_application_details detail WHERE customer_credit_application_id=v_application.id),
                'reversal',(SELECT to_jsonb(reversal) FROM app.customer_credit_application_reversals reversal
                    WHERE credit_application_id=v_application.id),
                'credit_position',v_credit_position,'target_balance_usd_cents',v_balance,'target_invoice_status',v_status);
        END $$;

        CREATE FUNCTION app.post_credit_application(
            p_property_id uuid,p_credit_id uuid,p_actor_id uuid,p_key uuid,p_intent jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_request jsonb; v_result jsonb; v_credit app.customer_credits%ROWTYPE;
        DECLARE v_proposal jsonb; v_details jsonb; v_detail jsonb; v_invoice uuid; v_charge uuid;
        DECLARE v_reference text; v_generated_at timestamptz; v_amount bigint; v_amount_json jsonb;
        DECLARE v_id uuid:=gen_random_uuid(); v_now timestamptz; v_sequence smallint:=0; v_line app.invoice_lines%ROWTYPE;
        BEGIN
            v_request:=jsonb_build_object('credit_id',p_credit_id,'intent',p_intent);
            v_result:=app.credit_command_replay(p_property_id,p_actor_id,'APPLY',p_key,v_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_intent IS NULL OR jsonb_typeof(p_intent)<>'object' OR octet_length(p_intent::text)>250000
                OR p_intent->>'mode' IS NULL OR p_intent->>'mode' NOT IN ('PROPOSAL','DESIGNATED','DIRECT_CHARGE')
            THEN RAISE EXCEPTION 'Credit application intent is invalid' USING ERRCODE='P5102'; END IF;
            IF p_intent->>'mode'='PROPOSAL' THEN
                IF p_intent-ARRAY['mode','proposal']<>'{}' OR jsonb_typeof(p_intent->'proposal') IS DISTINCT FROM 'object'
                THEN RAISE EXCEPTION 'Credit proposal confirmation is invalid' USING ERRCODE='P5102'; END IF;
                v_proposal:=p_intent->'proposal'; v_invoice:=(v_proposal->>'invoice_id')::uuid;
                v_amount_json:=v_proposal->'amount_usd_cents'; v_details:=v_proposal->'details';
                v_generated_at:=(v_proposal->>'generated_at')::timestamptz;
            ELSE
                v_invoice:=(p_intent->>'invoice_id')::uuid; v_charge:=(p_intent->>'late_payment_charge_id')::uuid;
                v_amount_json:=p_intent->'amount_usd_cents'; v_details:=p_intent->'details';
                IF p_intent->>'mode'='DESIGNATED' THEN
                    v_reference:=p_intent->>'designation_reference';
                    IF v_reference IS NULL OR v_reference<>btrim(v_reference) OR length(v_reference) NOT BETWEEN 1 AND 500
                        OR p_intent-ARRAY['mode','invoice_id','late_payment_charge_id','amount_usd_cents','details','designation_reference']<>'{}'
                    THEN RAISE EXCEPTION 'Credit designation is invalid' USING ERRCODE='P5102'; END IF;
                ELSIF v_invoice IS NOT NULL OR v_charge IS NULL
                    OR p_intent-ARRAY['mode','late_payment_charge_id','amount_usd_cents']<>'{}'
                THEN RAISE EXCEPTION 'Direct Credit Charge intent is invalid' USING ERRCODE='P5102'; END IF;
            END IF;
            IF (v_invoice IS NULL)=(v_charge IS NULL) OR jsonb_typeof(v_amount_json) IS DISTINCT FROM 'number'
                OR v_amount_json::text !~ '^[1-9][0-9]{0,15}$'
            THEN RAISE EXCEPTION 'Exactly one Credit target and exact positive cents required' USING ERRCODE='P5102'; END IF;
            v_amount:=v_amount_json::text::bigint;
            IF v_amount>9000000000000000 THEN RAISE EXCEPTION 'Credit amount exceeds bound' USING ERRCODE='P5102'; END IF;
            IF (v_invoice IS NOT NULL AND (jsonb_typeof(v_details) IS DISTINCT FROM 'array'
                    OR jsonb_array_length(v_details) NOT BETWEEN 1 AND 500))
                OR (v_charge IS NOT NULL AND v_details IS NOT NULL)
            THEN RAISE EXCEPTION 'Credit attribution detail envelope is invalid' USING ERRCODE='P5102'; END IF;
            SELECT credit.* INTO v_credit FROM app.customer_credits credit
                JOIN app.payments payment ON payment.id=credit.source_payment_id
                WHERE credit.id=p_credit_id AND payment.property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Credit not found' USING ERRCODE='P5101'; END IF;
            PERFORM app.serialize_payment_state(v_credit.source_payment_id);
            PERFORM 1 FROM app.payments WHERE id=v_credit.source_payment_id FOR UPDATE;
            PERFORM 1 FROM app.customer_credits WHERE id=p_credit_id FOR UPDATE;
            PERFORM app.lock_payment_allocation_target(CASE WHEN v_invoice IS NULL THEN 'LATE_PAYMENT_CHARGE' ELSE 'INVOICE' END,
                COALESCE(v_invoice,v_charge));
            PERFORM 1 FROM app.invoice_lines WHERE invoice_id=v_invoice ORDER BY id FOR UPDATE;
            v_now:=clock_timestamp();
            SET CONSTRAINTS ALL DEFERRED;
            INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,late_payment_charge_id,
                amount_usd_cents,within_invoice_basis,customer_designation_reference,proposal_generated_at,proposal_trace,
                occurred_at,actor_id,authorization_reference)
            VALUES(v_id,p_credit_id,CASE WHEN v_invoice IS NULL THEN 'LATE_PAYMENT_CHARGE' ELSE 'INVOICE' END,v_invoice,v_charge,
                v_amount,CASE WHEN v_proposal IS NOT NULL THEN 'RENT_THEN_RECURRING_SERVICES_PROPOSAL'
                    WHEN v_reference IS NOT NULL THEN 'CUSTOMER_DESIGNATED' ELSE 'NOT_APPLICABLE' END,
                v_reference,v_generated_at,v_proposal,v_now,p_actor_id,'credits.apply');
            IF v_charge IS NOT NULL THEN
                INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,late_payment_charge_id,
                    obligation_kind,applied_amount_usd_cents,attribution_basis,detail_sequence,calculation_trace)
                VALUES(gen_random_uuid(),v_id,v_charge,'LATE_PAYMENT_CHARGE',v_amount,
                    CASE WHEN v_reference IS NULL THEN 'DIRECT_LATE_PAYMENT_CHARGE' ELSE 'CUSTOMER_DESIGNATED' END,
                    1,jsonb_build_object('designation_reference',v_reference));
            ELSE
                FOR v_detail IN SELECT value FROM jsonb_array_elements(v_details)
                LOOP
                    IF jsonb_typeof(v_detail)<>'object'
                        OR jsonb_typeof(v_detail->'amount_usd_cents') IS DISTINCT FROM 'number'
                        OR (v_detail->'amount_usd_cents')::text !~ '^[1-9][0-9]{0,15}$'
                        OR (v_proposal IS NULL AND v_detail-ARRAY['invoice_line_id','amount_usd_cents']<>'{}')
                    THEN RAISE EXCEPTION 'Credit detail must contain exact cents' USING ERRCODE='P5102'; END IF;
                    SELECT * INTO STRICT v_line FROM app.invoice_lines
                        WHERE id=(v_detail->>'invoice_line_id')::uuid AND invoice_id=v_invoice;
                    v_sequence:=v_sequence+1;
                    INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,invoice_line_id,
                        obligation_kind,invoice_line_category_snapshot,proposed_amount_usd_cents,applied_amount_usd_cents,
                        attribution_basis,detail_sequence,calculation_trace)
                    VALUES(gen_random_uuid(),v_id,v_line.id,'INVOICE_LINE',v_line.category,
                        CASE WHEN v_proposal IS NOT NULL THEN (v_detail->>'amount_usd_cents')::bigint END,
                        (v_detail->>'amount_usd_cents')::bigint,
                        CASE WHEN v_proposal IS NOT NULL THEN v_detail->>'attribution_basis' ELSE 'CUSTOMER_DESIGNATED' END,
                        v_sequence,jsonb_build_object('confirmed_detail',v_detail,'designation_reference',v_reference));
                END LOOP;
                PERFORM app.refresh_allocated_invoice(v_invoice,p_actor_id,true);
            END IF;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.credit_application_resource(p_property_id,v_id,p_actor_id);
            INSERT INTO app.credit_commands VALUES(p_property_id,p_actor_id,'APPLY',p_key,v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.reverse_credit_application(
            p_property_id uuid,p_application_id uuid,p_actor_id uuid,p_key uuid,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_request jsonb; v_result jsonb;
        BEGIN
            v_request:=jsonb_build_object('application_id',p_application_id,'reason',p_reason);
            v_result:=app.credit_command_replay(p_property_id,p_actor_id,'REVERSE_APPLICATION',p_key,v_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Credit application reversal reason required' USING ERRCODE='P5102'; END IF;
            PERFORM 1 FROM app.customer_credit_applications application
                JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
                JOIN app.payments payment ON payment.id=credit.source_payment_id
                WHERE application.id=p_application_id AND payment.property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Credit application not found' USING ERRCODE='P5101'; END IF;
            INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,occurred_at,actor_id,authorization_reference)
            VALUES(gen_random_uuid(),p_application_id,p_reason,clock_timestamp(),p_actor_id,'credits.applications.reverse');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.credit_application_resource(p_property_id,p_application_id,p_actor_id);
            INSERT INTO app.credit_commands VALUES(p_property_id,p_actor_id,'REVERSE_APPLICATION',p_key,v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
    """)
    for signature in (
        "credit_application_proposal(uuid,uuid,uuid,bigint,timestamptz)",
        "credit_application_proposal_for_actor(uuid,uuid,uuid,bigint,uuid)",
        "credit_application_resource(uuid,uuid,uuid)",
        "post_credit_application(uuid,uuid,uuid,uuid,jsonb)",
        "reverse_credit_application(uuid,uuid,uuid,uuid,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    for signature in (
        "credit_application_proposal_for_actor(uuid,uuid,uuid,bigint,uuid)",
        "credit_application_resource(uuid,uuid,uuid)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO prm_runtime,prm_financial")
    for signature in (
        "post_credit_application(uuid,uuid,uuid,uuid,jsonb)",
        "reverse_credit_application(uuid,uuid,uuid,uuid,text)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError(
        "Credit and Refund history is forward-only; use an approved forward migration"
    )
