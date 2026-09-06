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
    create_refund_source_storage()
    integrate_refund_source_budgets()
    create_refund_services()
    create_pet_refund_sources()
    create_credit_history_reads()


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


def create_refund_source_storage() -> None:
    """Extend retained Refund history; this private checkpoint supports USD only."""
    op.execute("""
        ALTER TABLE app.refunds
            ALTER COLUMN source_deposit_id DROP NOT NULL,
            ALTER COLUMN source_lifecycle_event_id DROP NOT NULL,
            ADD COLUMN source_payment_id uuid REFERENCES app.payments(id) ON DELETE RESTRICT,
            ADD COLUMN source_customer_credit_id uuid REFERENCES app.customer_credits(id) ON DELETE RESTRICT,
            ADD COLUMN pet_refund_review_id uuid REFERENCES app.pet_deposit_refund_reviews(id) ON DELETE RESTRICT,
            ADD CONSTRAINT refund_exactly_one_source CHECK (
                num_nonnulls(source_payment_id,source_customer_credit_id,source_deposit_id)=1),
            ADD CONSTRAINT refund_source_context CHECK (
                (source_deposit_id IS NOT NULL)=(num_nonnulls(source_lifecycle_event_id,pet_refund_review_id)=1)
                AND num_nonnulls(source_lifecycle_event_id,pet_refund_review_id)<=1);
        CREATE INDEX refunds_payment_history_idx ON app.refunds(source_payment_id,processed_at,id);
        CREATE INDEX refunds_credit_history_idx ON app.refunds(source_customer_credit_id,processed_at,id);
        ALTER TABLE app.refund_corrections
            ADD COLUMN source_balance_effect_original_minor bigint CHECK(source_balance_effect_original_minor<>0),
            ADD COLUMN verified_return_amount_minor bigint CHECK(verified_return_amount_minor>0),
            ADD COLUMN verified_return_currency text CHECK(verified_return_currency IN ('USD','KHR')),
            ADD COLUMN verified_returned_at timestamptz CHECK(isfinite(verified_returned_at)),
            ADD COLUMN return_method_reference text CHECK(return_method_reference=btrim(return_method_reference)
                AND length(return_method_reference) BETWEEN 1 AND 500),
            ADD CONSTRAINT refund_verified_return_shape CHECK(num_nonnulls(verified_return_amount_minor,
                verified_return_currency,verified_returned_at,return_method_reference) IN (0,4));

        CREATE FUNCTION app.refund_net_value_at(p_refund_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT CASE WHEN refund.processed_at>p_as_of THEN 0 ELSE refund.usd_accounting_value_cents
                -COALESCE((SELECT sum(source_balance_effect_usd_cents) FROM app.refund_corrections
                    WHERE refund_id=refund.id AND occurred_at<=p_as_of),0)::bigint END
            FROM app.refunds refund WHERE refund.id=p_refund_id
        $$;
        CREATE FUNCTION app.payment_refunded_value_at(p_payment_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(app.refund_net_value_at(id,p_as_of)),0)::bigint
            FROM app.refunds WHERE source_payment_id=p_payment_id
        $$;
        CREATE FUNCTION app.credit_refunded_value_at(p_credit_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(app.refund_net_value_at(id,p_as_of)),0)::bigint
            FROM app.refunds WHERE source_customer_credit_id=p_credit_id
        $$;
        CREATE FUNCTION app.lock_refund_payment_source(p_payment_id uuid,p_credit_id uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment uuid;
        BEGIN
            IF num_nonnulls(p_payment_id,p_credit_id)<>1 THEN
                RAISE EXCEPTION 'Refund requires one supported source' USING ERRCODE='23514';
            END IF;
            IF p_credit_id IS NOT NULL THEN
                SELECT source_payment_id INTO STRICT v_payment FROM app.customer_credits WHERE id=p_credit_id;
            ELSE v_payment:=p_payment_id; END IF;
            -- The shared MVCC guard rejects stale Repeatable Read consumers too.
            PERFORM app.serialize_payment_state(v_payment);
            PERFORM 1 FROM app.payments WHERE id=v_payment FOR UPDATE;
            IF p_credit_id IS NOT NULL THEN
                PERFORM 1 FROM app.customer_credits WHERE id=p_credit_id FOR UPDATE;
            END IF;
            RETURN v_payment;
        END $$;
        CREATE FUNCTION app.validate_general_refund_source()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_credit app.customer_credits%ROWTYPE;
        DECLARE v_root uuid; v_available bigint; v_latest timestamptz;
        BEGIN
            IF NEW.source_lifecycle_event_id IS NOT NULL THEN RETURN NEW; END IF;
            IF NEW.pet_refund_review_id IS NOT NULL THEN
                PERFORM app.assert_pet_refund_source(NEW);
                RETURN NEW;
            END IF;
            v_root:=app.lock_refund_payment_source(NEW.source_payment_id,NEW.source_customer_credit_id);
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_root;
            PERFORM app.assert_active_financial_actor(NEW.processed_by,NULL);
            PERFORM app.assert_active_financial_actor(NEW.processed_by,v_payment.property_id);
            IF NEW.source_payment_id IS NOT NULL THEN
                PERFORM app.assert_payment_excess_eligible(v_root);
                IF v_payment.received_currency<>'USD' THEN
                    RAISE EXCEPTION 'Original KHR excess requires the KHR Refund path' USING ERRCODE='23514';
                END IF;
                v_available:=app.payment_available_value(v_root);
                v_latest:=GREATEST(v_payment.confirmed_at,app.payment_proposal_dependency_at(v_root));
            ELSE
                SELECT * INTO STRICT v_credit FROM app.customer_credits WHERE id=NEW.source_customer_credit_id;
                v_available:=app.credit_available_value(v_credit.id);
                v_latest:=app.credit_latest_at(v_credit.id);
                IF NEW.recipient_customer_id IS DISTINCT FROM v_credit.customer_id THEN
                    RAISE EXCEPTION 'Refund Credit recipient mismatch' USING ERRCODE='23514';
                END IF;
            END IF;
            IF v_payment.status<>'RECEIVED' OR NEW.recipient_customer_id IS DISTINCT FROM v_payment.payer_customer_id
                OR NEW.usd_accounting_value_cents NOT BETWEEN 1 AND 9000000000000000
                OR NEW.usd_accounting_value_cents>v_available
                OR NOT isfinite(NEW.processed_at) OR NEW.processed_at<=v_latest
                OR NEW.processed_at>clock_timestamp()+interval '5 seconds'
                OR length(NEW.reason) NOT BETWEEN 1 AND 1000 OR NEW.authorization_reference<>'refunds.create'
            THEN RAISE EXCEPTION 'Refund source, amount, authorization or chronology is invalid' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER a_refunds_general_source BEFORE INSERT ON app.refunds
            FOR EACH ROW EXECUTE FUNCTION app.validate_general_refund_source();

        CREATE FUNCTION app.validate_general_refund_correction()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_refund app.refunds%ROWTYPE; v_original app.refund_corrections%ROWTYPE;
        DECLARE v_payment app.payments%ROWTYPE; v_root uuid; v_net bigint; v_available bigint; v_latest timestamptz;
        DECLARE v_property uuid;
        BEGIN
            SELECT * INTO STRICT v_refund FROM app.refunds WHERE id=NEW.refund_id;
            IF v_refund.source_lifecycle_event_id IS NOT NULL THEN
                -- Retained Reservation replacement events have no invented return evidence.
                IF num_nonnulls(NEW.source_balance_effect_original_minor,NEW.verified_return_amount_minor,
                    NEW.verified_return_currency,NEW.verified_returned_at,NEW.return_method_reference)<>0 THEN
                    RAISE EXCEPTION 'Reservation correction requires its coordinated lifecycle path' USING ERRCODE='23514';
                END IF;
                RETURN NEW;
            END IF;
            IF v_refund.pet_refund_review_id IS NOT NULL THEN
                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);
                v_property:=app.deposit_property_id(v_refund.source_deposit_id);
            ELSE
                v_root:=app.lock_refund_payment_source(v_refund.source_payment_id,v_refund.source_customer_credit_id);
                SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_root;
                v_property:=v_payment.property_id;
            END IF;
            PERFORM 1 FROM app.refunds WHERE id=v_refund.id FOR UPDATE;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,NULL);
            PERFORM app.assert_active_financial_actor(NEW.actor_id,v_property);
            v_net:=app.refund_net_value_at(v_refund.id,'infinity');
            v_latest:=GREATEST(v_refund.processed_at,
                (SELECT max(occurred_at) FROM app.refund_corrections WHERE refund_id=v_refund.id),
                CASE WHEN v_refund.pet_refund_review_id IS NOT NULL THEN app.deposit_balance_latest_at(v_refund.source_deposit_id)
                    WHEN v_refund.source_payment_id IS NOT NULL THEN app.payment_proposal_dependency_at(v_root)
                    ELSE app.credit_latest_at(v_refund.source_customer_credit_id) END);
            IF NEW.previous_net_refund_usd_cents<>v_net
                OR NEW.resulting_net_refund_usd_cents>v_refund.usd_accounting_value_cents
                OR NEW.source_balance_effect_original_minor IS DISTINCT FROM NEW.source_balance_effect_usd_cents
                OR NOT isfinite(NEW.occurred_at) OR NEW.occurred_at<=v_latest
                OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
                OR length(NEW.reason) NOT BETWEEN 1 AND 1000 OR length(NEW.evidence_reference) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Refund correction must continue exact source history' USING ERRCODE='23514'; END IF;
            IF NEW.correction_kind='VALUE_CORRECTION' THEN
                IF NEW.authorization_reference<>'refunds.correct'
                    OR NEW.source_balance_effect_usd_cents>v_net
                    OR NEW.verified_return_amount_minor IS DISTINCT FROM NEW.source_balance_effect_usd_cents
                    OR NEW.verified_return_currency IS DISTINCT FROM 'USD'
                    OR NEW.verified_returned_at IS NULL OR NEW.return_method_reference IS NULL
                    OR NEW.verified_returned_at<v_refund.processed_at OR NEW.verified_returned_at>NEW.occurred_at
                THEN RAISE EXCEPTION 'Refund correction requires exact demonstrated return evidence' USING ERRCODE='23514'; END IF;
            ELSE
                SELECT * INTO v_original FROM app.refund_corrections
                    WHERE id=NEW.reverses_correction_id AND refund_id=v_refund.id AND correction_kind='VALUE_CORRECTION';
                IF NOT FOUND OR NEW.authorization_reference<>'refunds.corrections.reverse'
                    OR NEW.source_balance_effect_usd_cents<>-v_original.source_balance_effect_usd_cents
                    OR NEW.source_balance_effect_original_minor<>-v_original.source_balance_effect_original_minor
                    OR EXISTS(SELECT 1 FROM app.refund_corrections WHERE reverses_correction_id=v_original.id)
                    OR num_nonnulls(NEW.verified_return_amount_minor,NEW.verified_return_currency,
                        NEW.verified_returned_at,NEW.return_method_reference)<>0
                THEN RAISE EXCEPTION 'Refund correction reversal must reverse one active exact correction' USING ERRCODE='23514'; END IF;
                v_available:=CASE WHEN v_refund.pet_refund_review_id IS NOT NULL THEN app.deposit_held_value_at(v_refund.source_deposit_id,'infinity')
                    WHEN v_refund.source_payment_id IS NOT NULL THEN app.payment_available_value(v_root)
                    ELSE app.credit_available_value(v_refund.source_customer_credit_id) END;
                IF (v_refund.pet_refund_review_id IS NULL AND v_payment.status<>'RECEIVED')
                    OR v_available< -NEW.source_balance_effect_usd_cents
                THEN RAISE EXCEPTION 'Returned Refund value is no longer available to reverse' USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER a_refund_corrections_general BEFORE INSERT ON app.refund_corrections
            FOR EACH ROW EXECUTE FUNCTION app.validate_general_refund_correction();

        CREATE FUNCTION app.audit_general_refund_event()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_refund app.refunds%ROWTYPE; v_payment app.payments%ROWTYPE;
        DECLARE v_actor uuid; v_at timestamptz; v_action text;
        DECLARE v_property uuid; v_lease uuid;
        BEGIN
            IF TG_TABLE_NAME='refunds' THEN
                v_refund:=NEW; v_actor:=NEW.processed_by; v_at:=NEW.processed_at; v_action:='refund.created';
            ELSE
                SELECT * INTO STRICT v_refund FROM app.refunds WHERE id=NEW.refund_id;
                v_actor:=NEW.actor_id; v_at:=NEW.occurred_at;
                v_action:=CASE WHEN NEW.correction_kind='VALUE_CORRECTION' THEN 'refund.value_corrected'
                    ELSE 'refund.correction_reversed' END;
            END IF;
            IF v_refund.source_lifecycle_event_id IS NOT NULL THEN RETURN NULL; END IF;
            IF v_refund.pet_refund_review_id IS NOT NULL THEN
                SELECT app.deposit_property_id(id),lease_id INTO STRICT v_property,v_lease
                    FROM app.deposits WHERE id=v_refund.source_deposit_id;
            ELSE
                SELECT * INTO STRICT v_payment FROM app.payments WHERE id=COALESCE(v_refund.source_payment_id,
                    (SELECT source_payment_id FROM app.customer_credits WHERE id=v_refund.source_customer_credit_id));
                v_property:=v_payment.property_id; v_lease:=v_payment.lease_id;
            END IF;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE
                (SELECT timezone_name FROM app.properties WHERE id=v_property))::date,v_actor,v_action,
                'refund',v_refund.id,NEW.reason,NEW.authorization_reference,v_property,
                jsonb_build_object('refund_id',v_refund.id,'source_payment_id',v_refund.source_payment_id,
                    'source_deposit_id',v_refund.source_deposit_id,'pet_refund_review_id',v_refund.pet_refund_review_id,
                    'source_customer_credit_id',v_refund.source_customer_credit_id,'source_event',to_jsonb(NEW)),
                NEW.id,'API','SUCCESS',v_refund.recipient_customer_id,v_lease);
            RETURN NULL;
        END $$;
        CREATE TRIGGER refunds_general_audit AFTER INSERT ON app.refunds
            FOR EACH ROW EXECUTE FUNCTION app.audit_general_refund_event();
        CREATE TRIGGER refund_corrections_general_audit AFTER INSERT ON app.refund_corrections
            FOR EACH ROW EXECUTE FUNCTION app.audit_general_refund_event();
    """)
    replace_function(
        "app.validate_reservation_financial_outcome()",
        "IF TG_TABLE_NAME = 'deposit_dispositions' THEN",
        """IF TG_TABLE_NAME = 'refunds' THEN
                IF NEW.source_lifecycle_event_id IS NULL THEN RETURN NEW; END IF;
            END IF;
            IF TG_TABLE_NAME = 'deposit_dispositions' THEN""",
    )
    replace_function(
        "app.validate_refund_correction()",
        "SELECT refund.usd_accounting_value_cents",
        """IF EXISTS(SELECT 1 FROM app.refunds WHERE id=NEW.refund_id AND source_lifecycle_event_id IS NULL)
            THEN RETURN NEW; END IF;
            SELECT refund.usd_accounting_value_cents""",
    )
    replace_function(
        "app.assert_reservation_financial_outcome_complete()",
        "IF TG_TABLE_NAME = 'reservations' THEN",
        """IF TG_TABLE_NAME = 'refunds' THEN
                IF NEW.source_lifecycle_event_id IS NULL THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'refund_corrections' THEN
                IF EXISTS(SELECT 1 FROM app.refunds WHERE id=NEW.refund_id AND source_lifecycle_event_id IS NULL)
                THEN RETURN NULL; END IF;
            END IF;
            IF TG_TABLE_NAME = 'reservations' THEN""",
    )
    for signature in (
        "refund_net_value_at(uuid,timestamptz)",
        "payment_refunded_value_at(uuid,timestamptz)",
        "credit_refunded_value_at(uuid,timestamptz)",
        "lock_refund_payment_source(uuid,uuid)",
        "validate_general_refund_source()",
        "validate_general_refund_correction()",
        "audit_general_refund_event()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )


def integrate_refund_source_budgets() -> None:
    """Direct Payment refunds consume Payment; Credit refunds consume only Credit."""
    replace_function(
        "app.payment_disposition_summary(uuid)",
        "'refund_usd_cents',0",
        "'refund_usd_cents',app.payment_refunded_value_at(p_payment_id,'infinity'::timestamptz)",
    )
    replace_function(
        "app.credit_available_value(uuid)",
        "-app.credit_applied_value_at(credit.id,'infinity') END",
        "-app.credit_applied_value_at(credit.id,'infinity')-app.credit_refunded_value_at(credit.id,'infinity') END",
    )
    replace_function(
        "app.credit_latest_at(uuid)",
        ") events",
        """UNION ALL SELECT processed_at FROM app.refunds WHERE source_customer_credit_id=p_credit_id
                UNION ALL SELECT correction.occurred_at FROM app.refund_corrections correction
                    JOIN app.refunds refund ON refund.id=correction.refund_id
                    WHERE refund.source_customer_credit_id=p_credit_id
            ) events""",
    )
    for domain, identity in (("payment", "v_payment_id"), ("credit", "v_credit_id")):
        source_column = "source_payment_id" if domain == "payment" else "source_customer_credit_id"
        first_branch = "IF TG_TABLE_NAME='customer_credits' THEN"
        replace_function(
            f"app.validate_{domain}_history_budget()",
            first_branch,
            f"""IF TG_TABLE_NAME='refunds' THEN
                {identity}:=NEW.{source_column};
                IF {identity} IS NULL THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME='refund_corrections' THEN
                SELECT {source_column} INTO STRICT {identity} FROM app.refunds WHERE id=NEW.refund_id;
                IF {identity} IS NULL THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME='customer_credits' THEN""",
        )
        refund_sign, correction_sign = ("", "-") if domain == "payment" else ("-", "")
        replace_function(
            f"app.validate_{domain}_history_budget()",
            "), positions AS (",
            f"""UNION ALL SELECT processed_at,{refund_sign}usd_accounting_value_cents::numeric
                    FROM app.refunds WHERE {source_column}={identity}
                UNION ALL SELECT correction.occurred_at,{correction_sign}correction.source_balance_effect_usd_cents::numeric
                    FROM app.refund_corrections correction JOIN app.refunds refund ON refund.id=correction.refund_id
                    WHERE refund.{source_column}={identity}
                ), positions AS (""",
        )
        for table in ("refunds", "refund_corrections"):
            op.execute(f"""
                CREATE CONSTRAINT TRIGGER {table}_{domain}_history_budget AFTER INSERT ON app.{table}
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_{domain}_history_budget();
            """)
    for signature, source_id, ending in (
        (
            "app.payment_proposal_dependency_at(uuid)",
            "p_payment_id",
            ") SELECT max(event_at) FROM events",
        ),
        ("app.validate_payment_reversal()", "NEW.payment_id", ") dependency_events;"),
    ):
        replace_function(
            signature,
            ending,
            f"""UNION ALL SELECT processed_at FROM app.refunds WHERE source_payment_id={source_id}
                UNION ALL SELECT correction.occurred_at FROM app.refund_corrections correction
                    JOIN app.refunds refund ON refund.id=correction.refund_id
                    WHERE refund.source_payment_id={source_id}
            {ending}""",
        )
    op.execute("""
        COMMENT ON FUNCTION app.credit_available_value(uuid) IS
            'Derived recognition less active applications and net Credit Refunds; source Payment is not consumed twice.';
    """)


def create_refund_services() -> None:
    """Expose exact USD commands and coherent bounded reads; HTTP remains V1-052."""
    op.execute("""
        CREATE TABLE app.refund_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            action text NOT NULL CHECK(action IN ('CREATE_USD','CREATE_PET_USD','VERIFY_RETURN_USD','REVERSE_CORRECTION')),
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            request jsonb NOT NULL CHECK(jsonb_typeof(request)='object' AND octet_length(request::text)<=16000),
            response jsonb NOT NULL CHECK(jsonb_typeof(response)='object'),
            completed_at timestamptz NOT NULL CHECK(isfinite(completed_at)),
            PRIMARY KEY(property_id,actor_id,action,idempotency_key)
        );
        CREATE TRIGGER refund_commands_immutable BEFORE UPDATE OR DELETE ON app.refund_commands
            FOR EACH ROW EXECUTE FUNCTION app.reject_payment_history_mutation();
        CREATE TRIGGER refund_commands_no_truncate BEFORE TRUNCATE ON app.refund_commands
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_payment_history_mutation();
        REVOKE ALL ON TABLE app.refund_commands FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;

        CREATE FUNCTION app.refund_property_id(p_refund_id uuid)
        RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(payment.property_id,credit_payment.property_id,app.deposit_property_id(refund.source_deposit_id))
            FROM app.refunds refund
            LEFT JOIN app.payments payment ON payment.id=refund.source_payment_id
            LEFT JOIN app.customer_credits credit ON credit.id=refund.source_customer_credit_id
            LEFT JOIN app.payments credit_payment ON credit_payment.id=credit.source_payment_id
            WHERE refund.id=p_refund_id
        $$;
        CREATE FUNCTION app.refund_summary(p_refund_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
            SELECT jsonb_build_object('refund',to_jsonb(refund),
                'source',jsonb_build_object('type',CASE WHEN source_payment_id IS NOT NULL THEN 'PAYMENT'
                    WHEN source_customer_credit_id IS NOT NULL THEN 'CREDIT' ELSE 'DEPOSIT' END,
                    'id',COALESCE(source_payment_id,source_customer_credit_id,source_deposit_id),
                    'property_id',app.refund_property_id(refund.id)),
                'net_refund_usd_cents',app.refund_net_value_at(refund.id,'infinity'))
            FROM app.refunds refund WHERE refund.id=p_refund_id
        $$;
        CREATE FUNCTION app.assert_refund_page(p_limit integer,p_after_at timestamptz,p_after_id uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR num_nonnulls(p_after_at,p_after_id) NOT IN (0,2)
                OR (p_after_at IS NOT NULL AND NOT isfinite(p_after_at))
                OR p_after_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Refund page is invalid' USING ERRCODE='P5202'; END IF;
        END $$;
        CREATE FUNCTION app.refund_resource(
            p_property_id uuid,p_refund_id uuid,p_actor_id uuid,p_limit integer,p_after_at timestamptz,p_after_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            PERFORM app.assert_refund_page(p_limit,p_after_at,p_after_id);
            -- The complete resource, net value and bounded correction page are
            -- captured in ONE SQL snapshot. No inverted Refund->source lock order.
            SELECT app.refund_summary(refund.id) || jsonb_build_object(
                'source_payment',to_jsonb(payment),'source_exchange_rate',to_jsonb(rate),
                -- Keep source links and typed qualification facts here. Full
                -- retained narratives belong to the existing review resource,
                -- not every bounded Refund command response/history page.
                'pet_refund_review',(SELECT jsonb_build_object('id',review.id,
                    'pet_departure_id',review.pet_departure_id,'pet_deposit_id',review.pet_deposit_id,
                    'obligations_reviewed_usd_cents',review.obligations_reviewed_usd_cents,
                    'all_pet_obligations_resolved',review.all_pet_obligations_resolved,
                    'reviewed_at',review.reviewed_at,'reviewed_by',review.reviewed_by)
                    FROM app.pet_deposit_refund_reviews review
                    WHERE review.id=refund.pet_refund_review_id),
                'pet_departure',(SELECT jsonb_build_object('id',departure.id,
                    'pet_approval_id',departure.pet_approval_id,'lease_id',departure.lease_id,
                    'permanently_left_date',departure.permanently_left_date,
                    'occurred_at',departure.occurred_at,'actor_id',departure.actor_id)
                    FROM app.lease_pet_departures departure
                    JOIN app.pet_deposit_refund_reviews review ON review.pet_departure_id=departure.id
                    WHERE review.id=refund.pet_refund_review_id),
                'corrections',(WITH page AS MATERIALIZED (
                    SELECT correction.*,row_number() OVER (ORDER BY occurred_at DESC,id DESC) AS page_row
                    FROM app.refund_corrections correction WHERE refund_id=refund.id
                        AND (p_after_at IS NULL OR (occurred_at,id)<(p_after_at,p_after_id))
                    ORDER BY occurred_at DESC,id DESC LIMIT p_limit+1
                ) SELECT jsonb_build_object(
                    'items',COALESCE(jsonb_agg(to_jsonb(page)-'page_row' ORDER BY page_row)
                        FILTER(WHERE page_row<=p_limit),'[]'::jsonb),
                    'next_cursor',CASE WHEN count(*)>p_limit THEN
                        (SELECT jsonb_build_object('occurred_at',occurred_at,'id',id) FROM page WHERE page_row=p_limit)
                        ELSE NULL END) FROM page))
            INTO v_result FROM app.refunds refund
            LEFT JOIN app.customer_credits credit ON credit.id=refund.source_customer_credit_id
            LEFT JOIN app.payments payment ON payment.id=COALESCE(refund.source_payment_id,credit.source_payment_id)
            LEFT JOIN app.exchange_rate_records rate ON rate.id=payment.exchange_rate_record_id
            WHERE refund.id=p_refund_id AND app.refund_property_id(refund.id)=p_property_id;
            IF v_result IS NULL THEN RAISE EXCEPTION 'Refund not found' USING ERRCODE='P5201'; END IF;
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.list_refunds(
            p_property_id uuid,p_actor_id uuid,p_customer_id uuid,p_limit integer,p_after_at timestamptz,p_after_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            PERFORM app.assert_refund_page(p_limit,p_after_at,p_after_id);
            IF p_customer_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Refund Customer filter is invalid' USING ERRCODE='P5202'; END IF;
            WITH page AS MATERIALIZED (
                SELECT refund.id,refund.processed_at,row_number() OVER (ORDER BY processed_at DESC,id DESC) AS page_row
                FROM app.refunds refund WHERE app.refund_property_id(refund.id)=p_property_id
                    AND (p_customer_id IS NULL OR recipient_customer_id=p_customer_id)
                    AND (p_after_at IS NULL OR (processed_at,id)<(p_after_at,p_after_id))
                ORDER BY processed_at DESC,id DESC LIMIT p_limit+1
            ) SELECT jsonb_build_object(
                'items',COALESCE(jsonb_agg(app.refund_summary(id) ORDER BY page_row)
                    FILTER(WHERE page_row<=p_limit),'[]'::jsonb),
                'next_cursor',CASE WHEN count(*)>p_limit THEN
                    (SELECT jsonb_build_object('occurred_at',processed_at,'id',id) FROM page WHERE page_row=p_limit)
                    ELSE NULL END) INTO v_result FROM page;
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.refund_command_replay(
            p_property_id uuid,p_actor_id uuid,p_action text,p_key uuid,p_request jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_command app.refund_commands%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            IF p_action IS NULL OR p_action NOT IN ('CREATE_USD','CREATE_PET_USD','VERIFY_RETURN_USD','REVERSE_CORRECTION')
                OR p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_request IS NULL OR jsonb_typeof(p_request)<>'object' OR octet_length(p_request::text)>16000
            THEN RAISE EXCEPTION 'Refund command identity is invalid' USING ERRCODE='P5202'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('refund-command:'||p_property_id::text
                ||':'||p_actor_id::text||':'||p_action||':'||p_key::text,0));
            SELECT * INTO v_command FROM app.refund_commands WHERE property_id=p_property_id
                AND actor_id=p_actor_id AND action=p_action AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_command.request IS DISTINCT FROM p_request
                THEN RAISE EXCEPTION 'Refund idempotency key reused' USING ERRCODE='P5205'; END IF;
                RETURN v_command.response;
            END IF;
            RETURN NULL;
        END $$;
        CREATE FUNCTION app.require_usd_refund_source(p_property_id uuid,p_kind text,p_source_id uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment uuid;
        BEGIN
            IF p_kind IS NULL OR p_kind NOT IN ('PAYMENT','CREDIT') OR p_source_id IS NULL
                OR p_source_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Unsupported USD Refund source' USING ERRCODE='P5202'; END IF;
            IF p_kind='PAYMENT' THEN
                SELECT id INTO v_payment FROM app.payments WHERE id=p_source_id AND property_id=p_property_id;
            ELSE
                SELECT payment.id INTO v_payment FROM app.customer_credits credit
                    JOIN app.payments payment ON payment.id=credit.source_payment_id
                    WHERE credit.id=p_source_id AND payment.property_id=p_property_id;
            END IF;
            IF v_payment IS NULL THEN RAISE EXCEPTION 'Refund source not found' USING ERRCODE='P5201'; END IF;
            RETURN v_payment;
        END $$;
        CREATE FUNCTION app.usd_refund_source(p_property_id uuid,p_actor_id uuid,p_kind text,p_source_id uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_payment_id uuid; v_payment app.payments%ROWTYPE; v_available bigint;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            v_payment_id:=app.require_usd_refund_source(p_property_id,p_kind,p_source_id);
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_payment_id FOR SHARE;
            IF p_kind='PAYMENT' THEN
                IF v_payment.received_currency<>'USD'
                THEN RAISE EXCEPTION 'Original KHR excess requires its KHR Refund path' USING ERRCODE='P5202'; END IF;
                PERFORM app.assert_payment_excess_eligible(v_payment_id);
                v_available:=app.payment_available_value(v_payment_id);
            ELSE
                PERFORM 1 FROM app.customer_credits WHERE id=p_source_id FOR SHARE;
                v_available:=app.credit_available_value(p_source_id);
            END IF;
            IF v_payment.status<>'RECEIVED' THEN v_available:=0; END IF;
            RETURN jsonb_build_object('source_type',p_kind,'source_id',p_source_id,
                'recipient_customer_id',v_payment.payer_customer_id,'property_id',p_property_id,
                'refund_currency','USD','available_usd_cents',v_available,'eligible',v_available>0);
        END $$;
        CREATE FUNCTION app.create_usd_refund(
            p_property_id uuid,p_actor_id uuid,p_key uuid,p_source_kind text,p_source_id uuid,p_amount bigint,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_request jsonb; v_result jsonb; v_payment uuid; v_customer uuid; v_id uuid:=gen_random_uuid();
        BEGIN
            v_request:=jsonb_build_object('source_kind',p_source_kind,'source_id',p_source_id,'amount_usd_cents',p_amount,'reason',p_reason);
            v_result:=app.refund_command_replay(p_property_id,p_actor_id,'CREATE_USD',p_key,v_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'USD Refund input is invalid' USING ERRCODE='P5202'; END IF;
            v_payment:=app.require_usd_refund_source(p_property_id,p_source_kind,p_source_id);
            PERFORM app.lock_refund_payment_source(CASE WHEN p_source_kind='PAYMENT' THEN p_source_id END,
                CASE WHEN p_source_kind='CREDIT' THEN p_source_id END);
            SELECT payer_customer_id INTO STRICT v_customer FROM app.payments WHERE id=v_payment;
            INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_payment_id,source_customer_credit_id,
                usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,processed_by,authorization_reference)
            VALUES(v_id,'REF-'||v_id::text,v_customer,CASE WHEN p_source_kind='PAYMENT' THEN p_source_id END,
                CASE WHEN p_source_kind='CREDIT' THEN p_source_id END,p_amount,'USD',p_amount,p_reason,clock_timestamp(),p_actor_id,'refunds.create');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.refund_resource(p_property_id,v_id,p_actor_id,50,NULL,NULL);
            INSERT INTO app.refund_commands VALUES(p_property_id,p_actor_id,'CREATE_USD',p_key,v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.require_correctable_usd_refund(p_property_id uuid,p_refund_id uuid)
        RETURNS app.refunds LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_refund app.refunds%ROWTYPE;
        BEGIN
            SELECT * INTO v_refund FROM app.refunds
                WHERE id=p_refund_id AND app.refund_property_id(id)=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Refund not found' USING ERRCODE='P5201'; END IF;
            IF v_refund.source_lifecycle_event_id IS NOT NULL OR v_refund.refund_currency<>'USD' THEN
                RAISE EXCEPTION 'Refund requires its source-specific coordinated correction path' USING ERRCODE='P5202';
            END IF;
            IF v_refund.pet_refund_review_id IS NOT NULL THEN
                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);
            ELSE
                PERFORM app.lock_refund_payment_source(v_refund.source_payment_id,v_refund.source_customer_credit_id);
            END IF;
            PERFORM 1 FROM app.refunds WHERE id=v_refund.id FOR UPDATE;
            RETURN v_refund;
        END $$;
        CREATE FUNCTION app.verify_usd_refund_return(
            p_property_id uuid,p_refund_id uuid,p_actor_id uuid,p_key uuid,p_amount bigint,
            p_returned_at timestamptz,p_method text,p_evidence text,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_request jsonb; v_result jsonb; v_refund app.refunds%ROWTYPE; v_net bigint; v_id uuid:=gen_random_uuid();
        BEGIN
            v_request:=jsonb_build_object('refund_id',p_refund_id,'returned_amount_minor',p_amount,'returned_currency','USD',
                'returned_at',p_returned_at,'return_method_reference',p_method,'evidence_reference',p_evidence,'reason',p_reason);
            v_result:=app.refund_command_replay(p_property_id,p_actor_id,'VERIFY_RETURN_USD',p_key,v_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_returned_at IS NULL OR NOT isfinite(p_returned_at)
                OR p_method IS NULL OR p_method<>btrim(p_method) OR length(p_method) NOT BETWEEN 1 AND 500
                OR p_evidence IS NULL OR p_evidence<>btrim(p_evidence) OR length(p_evidence) NOT BETWEEN 1 AND 500
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Verified USD return input is invalid' USING ERRCODE='P5202'; END IF;
            v_refund:=app.require_correctable_usd_refund(p_property_id,p_refund_id);
            v_net:=app.refund_net_value_at(v_refund.id,'infinity');
            INSERT INTO app.refund_corrections(id,refund_id,correction_kind,source_balance_effect_usd_cents,
                source_balance_effect_original_minor,previous_net_refund_usd_cents,resulting_net_refund_usd_cents,
                reason,evidence_reference,occurred_at,actor_id,authorization_reference,
                verified_return_amount_minor,verified_return_currency,verified_returned_at,return_method_reference)
            VALUES(v_id,v_refund.id,'VALUE_CORRECTION',p_amount,p_amount,v_net,v_net-p_amount,
                p_reason,p_evidence,clock_timestamp(),p_actor_id,'refunds.correct',p_amount,'USD',p_returned_at,p_method);
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.refund_resource(p_property_id,v_refund.id,p_actor_id,50,NULL,NULL);
            INSERT INTO app.refund_commands VALUES(p_property_id,p_actor_id,'VERIFY_RETURN_USD',p_key,v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.reverse_refund_correction(
            p_property_id uuid,p_refund_id uuid,p_correction_id uuid,p_actor_id uuid,p_key uuid,p_evidence text,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_request jsonb; v_result jsonb; v_refund app.refunds%ROWTYPE;
        DECLARE v_correction app.refund_corrections%ROWTYPE; v_net bigint;
        BEGIN
            v_request:=jsonb_build_object('refund_id',p_refund_id,'correction_id',p_correction_id,'evidence_reference',p_evidence,'reason',p_reason);
            v_result:=app.refund_command_replay(p_property_id,p_actor_id,'REVERSE_CORRECTION',p_key,v_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_evidence IS NULL OR p_evidence<>btrim(p_evidence) OR length(p_evidence) NOT BETWEEN 1 AND 500
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Refund correction reversal input is invalid' USING ERRCODE='P5202'; END IF;
            v_refund:=app.require_correctable_usd_refund(p_property_id,p_refund_id);
            SELECT * INTO v_correction FROM app.refund_corrections WHERE id=p_correction_id
                AND refund_id=v_refund.id AND correction_kind='VALUE_CORRECTION';
            IF NOT FOUND THEN RAISE EXCEPTION 'Refund correction not found' USING ERRCODE='P5201'; END IF;
            v_net:=app.refund_net_value_at(v_refund.id,'infinity');
            INSERT INTO app.refund_corrections(id,refund_id,correction_kind,reverses_correction_id,
                source_balance_effect_usd_cents,source_balance_effect_original_minor,
                previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,evidence_reference,
                occurred_at,actor_id,authorization_reference)
            VALUES(gen_random_uuid(),v_refund.id,'CORRECTION_REVERSAL',v_correction.id,
                -v_correction.source_balance_effect_usd_cents,-v_correction.source_balance_effect_original_minor,
                v_net,v_net+v_correction.source_balance_effect_usd_cents,p_reason,p_evidence,
                clock_timestamp(),p_actor_id,'refunds.corrections.reverse');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.refund_resource(p_property_id,v_refund.id,p_actor_id,50,NULL,NULL);
            INSERT INTO app.refund_commands VALUES(p_property_id,p_actor_id,'REVERSE_CORRECTION',p_key,v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
    """)
    reads = (
        "refund_resource(uuid,uuid,uuid,integer,timestamptz,uuid)",
        "list_refunds(uuid,uuid,uuid,integer,timestamptz,uuid)",
        "usd_refund_source(uuid,uuid,text,uuid)",
    )
    writes = (
        "create_usd_refund(uuid,uuid,uuid,text,uuid,bigint,text)",
        "verify_usd_refund_return(uuid,uuid,uuid,uuid,bigint,timestamptz,text,text,text)",
        "reverse_refund_correction(uuid,uuid,uuid,uuid,uuid,text,text)",
    )
    for signature in (
        "refund_property_id(uuid)",
        "refund_summary(uuid)",
        "assert_refund_page(integer,timestamptz,uuid)",
        "refund_command_replay(uuid,uuid,text,uuid,jsonb)",
        "require_usd_refund_source(uuid,text,uuid)",
        "require_correctable_usd_refund(uuid,uuid)",
        *reads,
        *writes,
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    for signature in reads:
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO prm_runtime,prm_financial")
    for signature in writes:
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO prm_financial")


def create_pet_refund_sources() -> None:
    """Reuse qualified Pet evidence and conserve every Deposit balance event."""
    op.execute("""
        CREATE TABLE app.deposit_serialization_guards (
            deposit_id uuid PRIMARY KEY REFERENCES app.deposits(id) ON DELETE RESTRICT,
            revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0)
        );
        REVOKE ALL ON TABLE app.deposit_serialization_guards FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        CREATE FUNCTION app.serialize_deposit_state(p_deposit_id uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            -- Existing Deposit commands already acquire this root row. Keep its
            -- order before the new MVCC guard; a row lock alone is not enough
            -- for a transaction retaining a Repeatable Read snapshot.
            PERFORM 1 FROM app.deposits WHERE id=p_deposit_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Deposit not found' USING ERRCODE='23503'; END IF;
            INSERT INTO app.deposit_serialization_guards(deposit_id,revision) VALUES(p_deposit_id,1)
                ON CONFLICT(deposit_id) DO UPDATE SET revision=app.deposit_serialization_guards.revision+1;
        END $$;
        CREATE FUNCTION app.deposit_balance_events(p_deposit_id uuid)
        RETURNS TABLE(event_at timestamptz,amount numeric)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT occurred_at,amount_usd_cents::numeric FROM app.deposit_receipts WHERE deposit_id=p_deposit_id
            UNION ALL SELECT reversal.occurred_at,-receipt.amount_usd_cents::numeric
                FROM app.deposit_receipt_reversals reversal JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                WHERE receipt.deposit_id=p_deposit_id
            UNION ALL SELECT occurred_at,-amount_usd_cents::numeric FROM app.deposit_dispositions WHERE deposit_id=p_deposit_id
            UNION ALL SELECT reversal.occurred_at,disposition.amount_usd_cents::numeric
                FROM app.deposit_disposition_reversals reversal JOIN app.deposit_dispositions disposition ON disposition.id=reversal.deposit_disposition_id
                WHERE disposition.deposit_id=p_deposit_id
            UNION ALL SELECT processed_at,-usd_accounting_value_cents::numeric FROM app.refunds WHERE source_deposit_id=p_deposit_id
            UNION ALL SELECT correction.occurred_at,correction.source_balance_effect_usd_cents::numeric
                FROM app.refund_corrections correction JOIN app.refunds refund ON refund.id=correction.refund_id
                WHERE refund.source_deposit_id=p_deposit_id
        $$;
        CREATE FUNCTION app.deposit_held_value_at(p_deposit_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(amount),0)::bigint FROM app.deposit_balance_events(p_deposit_id) WHERE event_at<=p_as_of
        $$;
        CREATE FUNCTION app.deposit_balance_latest_at(p_deposit_id uuid)
        RETURNS timestamptz LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT max(event_at) FROM app.deposit_balance_events(p_deposit_id)
        $$;
        CREATE FUNCTION app.serialize_deposit_balance_event()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_deposit uuid; v_original_at timestamptz;
        BEGIN
            IF TG_TABLE_NAME IN ('deposit_receipts','deposit_dispositions') THEN v_deposit:=NEW.deposit_id;
            ELSIF TG_TABLE_NAME='deposit_receipt_reversals' THEN
                SELECT deposit_id,occurred_at INTO STRICT v_deposit,v_original_at
                    FROM app.deposit_receipts WHERE id=NEW.deposit_receipt_id;
            ELSIF TG_TABLE_NAME='deposit_disposition_reversals' THEN
                SELECT deposit_id,occurred_at INTO STRICT v_deposit,v_original_at
                    FROM app.deposit_dispositions WHERE id=NEW.deposit_disposition_id;
            ELSIF TG_TABLE_NAME='refunds' THEN v_deposit:=NEW.source_deposit_id;
            ELSE SELECT source_deposit_id INTO STRICT v_deposit FROM app.refunds WHERE id=NEW.refund_id;
            END IF;
            IF v_deposit IS NOT NULL THEN PERFORM app.serialize_deposit_state(v_deposit); END IF;
            IF v_original_at IS NOT NULL THEN
                IF NEW.occurred_at<v_original_at
                THEN RAISE EXCEPTION 'Deposit reversal cannot predate its source' USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE FUNCTION app.validate_deposit_history_budget()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_deposit uuid;
        BEGIN
            IF TG_TABLE_NAME IN ('deposit_receipts','deposit_dispositions') THEN v_deposit:=NEW.deposit_id;
            ELSIF TG_TABLE_NAME='deposit_receipt_reversals' THEN
                SELECT deposit_id INTO STRICT v_deposit FROM app.deposit_receipts WHERE id=NEW.deposit_receipt_id;
            ELSIF TG_TABLE_NAME='deposit_disposition_reversals' THEN
                SELECT deposit_id INTO STRICT v_deposit FROM app.deposit_dispositions WHERE id=NEW.deposit_disposition_id;
            ELSIF TG_TABLE_NAME='refunds' THEN v_deposit:=NEW.source_deposit_id;
            ELSE SELECT source_deposit_id INTO STRICT v_deposit FROM app.refunds WHERE id=NEW.refund_id;
            END IF;
            IF v_deposit IS NULL THEN RETURN NULL; END IF;
            -- Validate every historical time group, not a zero-clamped current
            -- projection that could conceal a backdated transient overspend.
            IF EXISTS(SELECT 1 FROM (
                SELECT event_at,sum(amount) OVER (ORDER BY event_at RANGE UNBOUNDED PRECEDING) AS held
                FROM app.deposit_balance_events(v_deposit)
            ) positions WHERE held<0 OR NOT isfinite(event_at))
            THEN RAISE EXCEPTION 'Deposit historical held balance cannot be negative' USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;
        CREATE FUNCTION app.pet_refund_qualification(p_property_id uuid,p_deposit_id uuid,p_review_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
            SELECT jsonb_build_object('source_type','PET_DEPOSIT','source_id',deposit.id,
                'pet_refund_review_id',review.id,'pet_departure_id',departure.id,'pet_approval_id',approval.id,
                'lease_id',lease.id,'property_id',unit.property_id,'recipient_customer_id',deposit.customer_id,
                'qualified_at',GREATEST(review.reviewed_at,departure.occurred_at,approval.approved_at,lease.signed_at),
                'refund_currency','USD','available_usd_cents',app.deposit_held_value_at(deposit.id,'infinity'),
                'eligible',app.deposit_held_value_at(deposit.id,'infinity')>0)
            FROM app.deposits deposit
            JOIN app.pet_deposit_refund_reviews review ON review.pet_deposit_id=deposit.id AND review.id=p_review_id
            JOIN app.lease_pet_departures departure ON departure.id=review.pet_departure_id
                AND departure.pet_approval_id=deposit.pet_approval_id AND departure.lease_id=deposit.lease_id
            JOIN app.lease_pet_approvals approval ON approval.id=deposit.pet_approval_id AND approval.lease_id=deposit.lease_id
            JOIN app.leases lease ON lease.id=deposit.lease_id AND lease.primary_tenant_id=deposit.customer_id
            JOIN app.units unit ON unit.id=lease.unit_id
            WHERE deposit.id=p_deposit_id AND deposit.deposit_type='PET' AND lease.status='SIGNED'
                AND unit.property_id=p_property_id AND review.all_pet_obligations_resolved
                AND review.authorization_reference='deposits.refund.qualify'
                AND departure.permanently_left_date<=(clock_timestamp() AT TIME ZONE
                    (SELECT timezone_name FROM app.properties WHERE id=p_property_id))::date
        $$;
        CREATE FUNCTION app.lock_pet_refund_source(p_property_id uuid,p_deposit_id uuid,p_review_id uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_result jsonb;
        BEGIN
            -- Hold the Lease status through commit. Do not terminate it or
            -- invent Final Settlement merely to return a qualified Pet balance.
            PERFORM 1 FROM app.leases lease JOIN app.deposits deposit ON deposit.lease_id=lease.id
                JOIN app.units unit ON unit.id=lease.unit_id
                WHERE deposit.id=p_deposit_id AND unit.property_id=p_property_id AND lease.status='SIGNED'
                FOR SHARE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Qualified Pet Refund source not found' USING ERRCODE='P5201'; END IF;
            PERFORM app.serialize_deposit_state(p_deposit_id);
            v_result:=app.pet_refund_qualification(p_property_id,p_deposit_id,p_review_id);
            IF v_result IS NULL THEN RAISE EXCEPTION 'Qualified Pet Refund source not found' USING ERRCODE='P5201'; END IF;
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.assert_pet_refund_source(p_refund app.refunds)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_property uuid; v_source jsonb;
        BEGIN
            v_property:=app.deposit_property_id(p_refund.source_deposit_id);
            v_source:=app.lock_pet_refund_source(v_property,p_refund.source_deposit_id,p_refund.pet_refund_review_id);
            PERFORM app.assert_active_financial_actor(p_refund.processed_by,NULL);
            PERFORM app.assert_active_financial_actor(p_refund.processed_by,v_property);
            IF p_refund.recipient_customer_id IS DISTINCT FROM (v_source->>'recipient_customer_id')::uuid
                OR p_refund.usd_accounting_value_cents NOT BETWEEN 1 AND 9000000000000000
                OR p_refund.usd_accounting_value_cents>(v_source->>'available_usd_cents')::bigint
                OR NOT isfinite(p_refund.processed_at) OR p_refund.processed_at<=(v_source->>'qualified_at')::timestamptz
                OR p_refund.processed_at<=app.deposit_balance_latest_at(p_refund.source_deposit_id)
                OR p_refund.processed_at>clock_timestamp()+interval '5 seconds'
                OR length(p_refund.reason) NOT BETWEEN 1 AND 1000 OR p_refund.authorization_reference<>'refunds.create'
            THEN RAISE EXCEPTION 'Pet Refund source, amount, authorization or chronology is invalid' USING ERRCODE='23514'; END IF;
        END $$;
        CREATE FUNCTION app.pet_refund_source(p_property_id uuid,p_actor_id uuid,p_deposit_id uuid,p_review_id uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            v_result:=app.pet_refund_qualification(p_property_id,p_deposit_id,p_review_id);
            IF v_result IS NULL THEN RAISE EXCEPTION 'Qualified Pet Refund source not found' USING ERRCODE='P5201'; END IF;
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.create_pet_usd_refund(
            p_property_id uuid,p_actor_id uuid,p_key uuid,p_deposit_id uuid,p_review_id uuid,p_amount bigint,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_request jsonb; v_result jsonb; v_source jsonb; v_id uuid:=gen_random_uuid();
        BEGIN
            v_request:=jsonb_build_object('deposit_id',p_deposit_id,'pet_refund_review_id',p_review_id,
                'amount_usd_cents',p_amount,'reason',p_reason);
            v_result:=app.refund_command_replay(p_property_id,p_actor_id,'CREATE_PET_USD',p_key,v_request);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_deposit_id IS NULL OR p_review_id IS NULL
                OR p_deposit_id='00000000-0000-0000-0000-000000000000' OR p_review_id='00000000-0000-0000-0000-000000000000'
                OR p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Pet Refund input is invalid' USING ERRCODE='P5202'; END IF;
            v_source:=app.lock_pet_refund_source(p_property_id,p_deposit_id,p_review_id);
            INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_deposit_id,pet_refund_review_id,
                usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,processed_by,authorization_reference)
            VALUES(v_id,'REF-'||v_id::text,(v_source->>'recipient_customer_id')::uuid,p_deposit_id,p_review_id,
                p_amount,'USD',p_amount,p_reason,clock_timestamp(),p_actor_id,'refunds.create');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.refund_resource(p_property_id,v_id,p_actor_id,50,NULL,NULL);
            INSERT INTO app.refund_commands VALUES(p_property_id,p_actor_id,'CREATE_PET_USD',p_key,v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
    """)
    for table in (
        "deposit_receipts",
        "deposit_receipt_reversals",
        "deposit_dispositions",
        "deposit_disposition_reversals",
        "refunds",
        "refund_corrections",
    ):
        op.execute(f"""
            CREATE TRIGGER b_deposit_balance_source BEFORE INSERT ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.serialize_deposit_balance_event();
            CREATE CONSTRAINT TRIGGER {table}_deposit_history_budget AFTER INSERT ON app.{table}
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_deposit_history_budget();
        """)
    for signature in (
        "serialize_deposit_state(uuid)",
        "deposit_balance_events(uuid)",
        "deposit_held_value_at(uuid,timestamptz)",
        "deposit_balance_latest_at(uuid)",
        "serialize_deposit_balance_event()",
        "validate_deposit_history_budget()",
        "pet_refund_qualification(uuid,uuid,uuid)",
        "lock_pet_refund_source(uuid,uuid,uuid)",
        "assert_pet_refund_source(app.refunds)",
        "pet_refund_source(uuid,uuid,uuid,uuid)",
        "create_pet_usd_refund(uuid,uuid,uuid,uuid,uuid,bigint,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pet_refund_source(uuid,uuid,uuid,uuid) TO prm_runtime,prm_financial"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.create_pet_usd_refund(uuid,uuid,uuid,uuid,uuid,bigint,text) TO prm_financial"
    )


def create_credit_history_reads() -> None:
    """Bounded, coherent Credit-only reads; accepted mutation/replay contracts stay intact."""
    op.execute("""
        CREATE VIEW app.customer_credit_financial_position AS
        SELECT credit.id customer_credit_id,credit.customer_id,credit.source_payment_id,payment.property_id,
            credit.recognized_usd_cents,
            app.credit_applied_value_at(credit.id,'infinity') applied_usd_cents,
            app.credit_refunded_value_at(credit.id,'infinity') refunded_usd_cents,
            CASE WHEN reversal.id IS NOT NULL THEN credit.recognized_usd_cents ELSE 0 END reversed_usd_cents,
            app.credit_available_value(credit.id) available_usd_cents
        FROM app.customer_credits credit JOIN app.payments payment ON payment.id=credit.source_payment_id
        LEFT JOIN app.customer_credit_reversals reversal ON reversal.customer_credit_id=credit.id;
        REVOKE ALL ON TABLE app.customer_credit_financial_position FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;

        CREATE FUNCTION app.credit_read_summary(p_credit_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
            SELECT jsonb_build_object('credit',to_jsonb(credit),'position',to_jsonb(credit_position),
                'source_payment',jsonb_build_object('id',payment.id,'property_id',payment.property_id,
                    'payer_customer_id',payment.payer_customer_id,'received_currency',payment.received_currency,
                    'received_amount_minor',payment.received_amount_minor,
                    'usd_accounting_value_cents',payment.usd_accounting_value_cents,
                    'confirmed_at',payment.confirmed_at,'exchange_rate_record_id',payment.exchange_rate_record_id,
                    'channel_transaction_reference',payment.channel_transaction_reference),
                -- Unbounded original rate references/traces remain in the linked rate resource.
                'exchange_rate',CASE WHEN rate.id IS NOT NULL THEN jsonb_build_object('id',rate.id,
                    'reference_rate_khr_per_usd',rate.reference_rate_khr_per_usd,
                    'system_rate_khr_per_usd',rate.system_rate_khr_per_usd,'markup_basis_points',rate.markup_basis_points,
                    'rate_source',rate.rate_source,'applicable_at',rate.applicable_at,
                    'channel_actual_currency',rate.channel_actual_currency,
                    'channel_actual_amount_minor',rate.channel_actual_amount_minor,
                    'channel_actual_usd_value_cents',rate.channel_actual_usd_value_cents,
                    'channel_actual_rate_khr_per_usd',rate.channel_actual_rate_khr_per_usd,
                    'channel_confirmed_at',rate.channel_confirmed_at) END)
            FROM app.customer_credits credit JOIN app.customer_credit_financial_position credit_position
                ON credit_position.customer_credit_id=credit.id
            JOIN app.payments payment ON payment.id=credit.source_payment_id
            LEFT JOIN app.exchange_rate_records rate ON rate.id=payment.exchange_rate_record_id
            WHERE credit.id=p_credit_id
        $$;

        CREATE FUNCTION app.credit_history_events(p_credit_id uuid)
        RETURNS TABLE(event_kind text,event_id uuid,occurred_at timestamptz,
            balance_effect_usd_cents bigint,reason text,detail jsonb)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
            SELECT 'RECOGNITION',credit.id,credit.recognized_at,credit.recognized_usd_cents,credit.reason,
                jsonb_build_object('actor_id',credit.recognized_by,'authorization_reference',credit.authorization_reference,
                    'currency','USD','amount_minor',credit.recognized_usd_cents,
                    'source_kind','CREDIT','source_id',credit.id,'source_payment_id',credit.source_payment_id)
            FROM app.customer_credits credit WHERE credit.id=p_credit_id
            UNION ALL
            SELECT 'RECOGNITION_REVERSAL',reversal.id,reversal.occurred_at,-credit.recognized_usd_cents,reversal.reason,
                jsonb_build_object('actor_id',reversal.actor_id,'authorization_reference',reversal.authorization_reference,
                    'currency','USD','amount_minor',credit.recognized_usd_cents,
                    'source_kind','CREDIT_REVERSAL','source_id',reversal.id,
                    'reverses_event_kind','RECOGNITION','reverses_event_id',credit.id)
            FROM app.customer_credit_reversals reversal JOIN app.customer_credits credit
                ON credit.id=reversal.customer_credit_id WHERE credit.id=p_credit_id
            UNION ALL
            SELECT 'APPLICATION',application.id,application.occurred_at,-application.amount_usd_cents,NULL::text,
                jsonb_build_object('actor_id',application.actor_id,'authorization_reference',application.authorization_reference,
                    'currency','USD','amount_minor',application.amount_usd_cents,
                    'source_kind','CREDIT_APPLICATION','source_id',application.id,
                    'target_kind',application.target_kind,'target_id',COALESCE(application.invoice_id,application.late_payment_charge_id),
                    'within_invoice_basis',application.within_invoice_basis)
            FROM app.customer_credit_applications application WHERE application.customer_credit_id=p_credit_id
            UNION ALL
            SELECT 'APPLICATION_REVERSAL',reversal.id,reversal.occurred_at,application.amount_usd_cents,reversal.reason,
                jsonb_build_object('actor_id',reversal.actor_id,'authorization_reference',reversal.authorization_reference,
                    'currency','USD','amount_minor',application.amount_usd_cents,
                    'source_kind','CREDIT_APPLICATION_REVERSAL','source_id',reversal.id,
                    'reverses_event_kind','APPLICATION','reverses_event_id',application.id)
            FROM app.customer_credit_application_reversals reversal JOIN app.customer_credit_applications application
                ON application.id=reversal.credit_application_id WHERE application.customer_credit_id=p_credit_id
            UNION ALL
            SELECT 'REFUND',refund.id,refund.processed_at,-refund.usd_accounting_value_cents,refund.reason,
                jsonb_build_object('actor_id',refund.processed_by,'authorization_reference',refund.authorization_reference,
                    'currency',refund.refund_currency,'amount_minor',refund.refund_amount_minor,
                    'source_kind','REFUND','source_id',refund.id)
            FROM app.refunds refund WHERE refund.source_customer_credit_id=p_credit_id
            UNION ALL
            SELECT 'REFUND_'||correction.correction_kind,correction.id,correction.occurred_at,
                correction.source_balance_effect_usd_cents,correction.reason,
                jsonb_build_object('actor_id',correction.actor_id,'authorization_reference',correction.authorization_reference,
                    'currency',COALESCE(correction.verified_return_currency,refund.refund_currency),
                    'amount_minor',COALESCE(correction.verified_return_amount_minor,abs(correction.source_balance_effect_original_minor)),
                    'source_kind','REFUND_CORRECTION','source_id',correction.id,'refund_id',refund.id,
                    'correction_kind',correction.correction_kind,'reverses_event_id',correction.reverses_correction_id,
                    'reverses_event_kind',CASE WHEN correction.reverses_correction_id IS NOT NULL THEN 'REFUND_VALUE_CORRECTION' END,
                    'verified_returned_at',correction.verified_returned_at)
            FROM app.refund_corrections correction JOIN app.refunds refund ON refund.id=correction.refund_id
            WHERE refund.source_customer_credit_id=p_credit_id
        $$;

        CREATE FUNCTION app.assert_credit_read_actor(p_property_id uuid,p_actor_id uuid)
        RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.properties WHERE id=p_property_id)
            THEN RAISE EXCEPTION 'Credit Property not found' USING ERRCODE='P5101'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account JOIN app.actor_identities identity
                ON identity.actor_id=account.actor_id WHERE account.actor_id=p_actor_id
                AND account.lifecycle_state='active' AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Credit read requires an active human actor' USING ERRCODE='P4506'; END IF;
        END $$;
        CREATE FUNCTION app.assert_credit_read_page(p_limit integer,p_after_at timestamptz,p_after_id uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR num_nonnulls(p_after_at,p_after_id) NOT IN (0,2)
                OR (p_after_at IS NOT NULL AND NOT isfinite(p_after_at))
                OR p_after_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Credit page is invalid' USING ERRCODE='P5102'; END IF;
        END $$;
        CREATE FUNCTION app.list_customer_credits(
            p_property_id uuid,p_customer_id uuid,p_actor_id uuid,p_limit integer,p_after_at timestamptz,p_after_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM app.assert_credit_read_actor(p_property_id,p_actor_id);
            PERFORM app.assert_credit_read_page(p_limit,p_after_at,p_after_id);
            IF p_customer_id IS NULL OR p_customer_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Credit Customer is required' USING ERRCODE='P5102'; END IF;
            -- Page identities, immutable source facts and current positions share one snapshot.
            WITH page AS MATERIALIZED (
                SELECT credit.id,credit.recognized_at,
                    row_number() OVER(ORDER BY credit.recognized_at DESC,credit.id DESC) page_row
                FROM app.customer_credits credit JOIN app.payments payment ON payment.id=credit.source_payment_id
                WHERE credit.customer_id=p_customer_id AND payment.property_id=p_property_id
                    AND (p_after_at IS NULL OR (credit.recognized_at,credit.id)<(p_after_at,p_after_id))
                ORDER BY credit.recognized_at DESC,credit.id DESC LIMIT p_limit+1
            ) SELECT jsonb_build_object('items',COALESCE(jsonb_agg(app.credit_read_summary(id) ORDER BY page_row)
                    FILTER(WHERE page_row<=p_limit),'[]'::jsonb),
                'next_cursor',CASE WHEN count(*)>p_limit THEN (SELECT jsonb_build_object(
                    'occurred_at',recognized_at,'id',id) FROM page WHERE page_row=p_limit) ELSE NULL END)
            INTO v_result FROM page;
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.customer_credit_ledger(
            p_property_id uuid,p_credit_id uuid,p_actor_id uuid,p_limit integer,
            p_after_at timestamptz,p_after_kind text,p_after_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM app.assert_credit_read_actor(p_property_id,p_actor_id);
            PERFORM app.assert_credit_read_page(p_limit,p_after_at,p_after_id);
            IF num_nonnulls(p_after_at,p_after_kind,p_after_id) NOT IN (0,3)
                OR p_after_kind NOT IN ('RECOGNITION','RECOGNITION_REVERSAL','APPLICATION','APPLICATION_REVERSAL',
                    'REFUND','REFUND_VALUE_CORRECTION','REFUND_CORRECTION_REVERSAL')
            THEN RAISE EXCEPTION 'Credit ledger cursor is invalid' USING ERRCODE='P5102'; END IF;
            SELECT app.credit_read_summary(credit.id)||jsonb_build_object('history',(
                WITH history AS MATERIALIZED (
                    SELECT event.*,sum(balance_effect_usd_cents) OVER(ORDER BY occurred_at
                        RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)::bigint available_after_usd_cents
                    FROM app.credit_history_events(credit.id) event
                ), page AS MATERIALIZED (
                    SELECT history.*,row_number() OVER(ORDER BY occurred_at DESC,event_kind COLLATE "C" DESC,event_id DESC) page_row
                    FROM history WHERE p_after_at IS NULL OR
                        (occurred_at,event_kind COLLATE "C",event_id)<(p_after_at,p_after_kind COLLATE "C",p_after_id)
                    ORDER BY occurred_at DESC,event_kind COLLATE "C" DESC,event_id DESC LIMIT p_limit+1
                ) SELECT jsonb_build_object('items',COALESCE(jsonb_agg(detail||jsonb_build_object(
                        'event_kind',event_kind,'event_id',event_id,'occurred_at',occurred_at,
                        'balance_effect_usd_cents',balance_effect_usd_cents,
                        'available_after_usd_cents',available_after_usd_cents,
                        -- Explicitly link long historical narratives rather than truncate originals.
                        'reason',CASE WHEN octet_length(reason)<=4000 THEN reason END,
                        'reason_in_source',COALESCE(octet_length(reason)>4000,false)) ORDER BY page_row)
                        FILTER(WHERE page_row<=p_limit),'[]'::jsonb),
                    'next_cursor',CASE WHEN count(*)>p_limit THEN (SELECT jsonb_build_object(
                        'occurred_at',occurred_at,'event_kind',event_kind,'id',event_id)
                        FROM page WHERE page_row=p_limit) ELSE NULL END) FROM page))
            INTO v_result FROM app.customer_credits credit JOIN app.payments payment ON payment.id=credit.source_payment_id
            WHERE credit.id=p_credit_id AND payment.property_id=p_property_id;
            IF v_result IS NULL THEN RAISE EXCEPTION 'Credit not found' USING ERRCODE='P5101'; END IF;
            RETURN v_result;
        END $$;
    """)
    for signature in (
        "credit_read_summary(uuid)",
        "assert_credit_read_actor(uuid,uuid)",
        "credit_history_events(uuid)",
        "assert_credit_read_page(integer,timestamp with time zone,uuid)",
        "list_customer_credits(uuid,uuid,uuid,integer,timestamp with time zone,uuid)",
        "customer_credit_ledger(uuid,uuid,uuid,integer,timestamp with time zone,text,uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    for signature in (
        "list_customer_credits(uuid,uuid,uuid,integer,timestamp with time zone,uuid)",
        "customer_credit_ledger(uuid,uuid,uuid,integer,timestamp with time zone,text,uuid)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO prm_runtime,prm_financial")


def downgrade() -> None:
    raise RuntimeError(
        "Credit and Refund history is forward-only; use an approved forward migration"
    )
