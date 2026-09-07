"""Narrow runtime Credit/Refund scope and immutable source-audit reads."""

from alembic import op

revision = "20260907_45"
down_revision = "20260907_44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app.credit_refund_http_scope(
            p_kind text,p_id uuid,p_actor_id uuid,p_properties uuid[]
        ) RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog AS $$
        DECLARE v_property uuid;
        BEGIN
            IF p_kind IS NULL OR p_kind NOT IN
                ('property','customer','payment','credit','credit_application','refund','deposit')
                OR p_id IS NULL OR p_id='00000000-0000-0000-0000-000000000000'
                OR array_ndims(p_properties)>1 OR array_position(p_properties,NULL) IS NOT NULL
                OR '00000000-0000-0000-0000-000000000000'=ANY(p_properties)
            THEN RAISE EXCEPTION 'Invalid financial scope' USING ERRCODE='22023'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
                JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                WHERE account.actor_id=p_actor_id AND account.lifecycle_state='active'
                    AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Financial actor is not active' USING ERRCODE='P4506'; END IF;
            IF COALESCE(cardinality(p_properties),0)=0
            THEN RAISE EXCEPTION 'Financial resource not found' USING ERRCODE='P4501'; END IF;
            CASE p_kind
                WHEN 'property' THEN
                    SELECT id INTO v_property FROM app.properties WHERE id=p_id;
                WHEN 'customer' THEN
                    -- Customers belong to the canonical singleton Property.
                    SELECT property.id INTO v_property FROM app.customers customer
                        CROSS JOIN app.properties property WHERE customer.id=p_id;
                WHEN 'payment' THEN
                    SELECT property_id INTO v_property FROM app.payments WHERE id=p_id;
                WHEN 'credit' THEN
                    SELECT payment.property_id INTO v_property FROM app.customer_credits credit
                        JOIN app.payments payment ON payment.id=credit.source_payment_id
                        WHERE credit.id=p_id;
                WHEN 'credit_application' THEN
                    SELECT payment.property_id INTO v_property
                        FROM app.customer_credit_applications application
                        JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
                        JOIN app.payments payment ON payment.id=credit.source_payment_id
                        WHERE application.id=p_id;
                WHEN 'refund' THEN
                    v_property:=app.refund_property_id(p_id);
                WHEN 'deposit' THEN
                    v_property:=app.deposit_property_id(p_id);
            END CASE;
            IF v_property IS NULL OR NOT(v_property=ANY(p_properties))
            THEN RAISE EXCEPTION 'Financial resource not found' USING ERRCODE='P4501'; END IF;
            RETURN v_property;
        END $$;

        CREATE FUNCTION app.credit_refund_http_source_audit(
            p_property_id uuid,p_kind text,p_source_id uuid,p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_payment_id uuid; v_result jsonb;
        BEGIN
            IF p_kind IS NULL OR p_kind NOT IN ('PAYMENT','CREDIT')
            THEN RAISE EXCEPTION 'Invalid financial source' USING ERRCODE='22023'; END IF;
            PERFORM app.credit_refund_http_scope(
                lower(p_kind),p_source_id,p_actor_id,ARRAY[p_property_id]);
            IF p_kind='PAYMENT' THEN v_payment_id:=p_source_id;
            ELSE
                SELECT source_payment_id INTO v_payment_id FROM app.customer_credits
                    WHERE id=p_source_id;
            END IF;
            SELECT jsonb_build_object('source_payment',to_jsonb(payment),
                'source_exchange_rate',app.credit_refund_exchange_rate_summary(
                    payment.exchange_rate_record_id),
                'receipt_evidence',jsonb_build_object('received_at',evidence.received_at,
                    'evidence_reference',evidence.evidence_reference))
            INTO v_result FROM app.payments payment
                LEFT JOIN app.payment_receipt_evidence evidence ON evidence.payment_id=payment.id
                WHERE payment.id=v_payment_id AND payment.property_id=p_property_id;
            IF v_result IS NULL
            THEN RAISE EXCEPTION 'Financial source not found' USING ERRCODE='P4501'; END IF;
            RETURN v_result;
        END $$;

        REVOKE ALL ON FUNCTION app.credit_refund_http_scope(text,uuid,uuid,uuid[])
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        REVOKE ALL ON FUNCTION app.credit_refund_http_source_audit(uuid,text,uuid,uuid)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.credit_refund_http_scope(text,uuid,uuid,uuid[])
            TO prm_runtime;
        GRANT EXECUTE ON FUNCTION app.credit_refund_http_source_audit(uuid,text,uuid,uuid)
            TO prm_runtime;
    """)


def downgrade() -> None:
    raise RuntimeError("Credit/Refund HTTP reads are forward-only")
