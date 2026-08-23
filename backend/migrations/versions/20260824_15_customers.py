"""Add canonical Customer identity and audited contact-history persistence."""

from alembic import op

revision = "20260824_15"
down_revision = "20260824_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the protected Customer store and its auditable write boundary."""
    op.execute(
        r"""
        CREATE TABLE app.customers (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            legal_name text NOT NULL,
            phone_number text,
            email_address text,
            contact_address text,
            memo text,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT customers_legal_name_nonblank CHECK (length(btrim(legal_name)) > 0),
            CONSTRAINT customers_legal_name_normalized CHECK (legal_name = btrim(legal_name)),
            CONSTRAINT customers_phone_normalized CHECK (
                phone_number IS NULL OR (
                    length(btrim(phone_number)) > 0 AND phone_number = btrim(phone_number)
                )
            ),
            CONSTRAINT customers_email_normalized CHECK (
                email_address IS NULL OR (
                    length(btrim(email_address)) > 0 AND email_address = btrim(email_address)
                )
            ),
            CONSTRAINT customers_address_normalized CHECK (
                contact_address IS NULL OR (
                    length(btrim(contact_address)) > 0 AND contact_address = btrim(contact_address)
                )
            ),
            CONSTRAINT customers_memo_normalized CHECK (
                memo IS NULL OR (length(btrim(memo)) > 0 AND memo = btrim(memo))
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX customers_email_match_idx ON app.customers (lower(email_address))"
    )
    op.execute(
        "CREATE INDEX customers_phone_match_idx ON app.customers "
        "((regexp_replace(phone_number, '[^0-9]', '', 'g')))"
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_customer_history_loss()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
            THEN
                RAISE EXCEPTION 'Customer identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER customers_protect_history
        BEFORE UPDATE OR DELETE ON app.customers
        FOR EACH ROW EXECUTE FUNCTION app.reject_customer_history_loss()
        """
    )
    op.execute(
        """
        CREATE TRIGGER customers_reject_truncate
        BEFORE TRUNCATE ON app.customers
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_customer_history_loss()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.create_customer(
            p_id uuid,
            p_legal_name text,
            p_phone_number text,
            p_email_address text,
            p_contact_address text,
            p_memo text,
            p_actor_id uuid,
            p_event_id uuid
        )
        RETURNS TABLE(
            id uuid,
            legal_name text,
            phone_number text,
            email_address text,
            contact_address text,
            memo text,
            version integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_customer app.customers%ROWTYPE;
            v_property_id uuid;
        BEGIN
            SELECT property.id INTO STRICT v_property_id FROM app.properties AS property LIMIT 1;
            INSERT INTO app.customers AS customer (
                id, legal_name, phone_number, email_address, contact_address, memo,
                created_by, updated_by
            ) VALUES (
                p_id,
                btrim(p_legal_name),
                nullif(btrim(p_phone_number), ''),
                nullif(btrim(p_email_address), ''),
                nullif(btrim(p_contact_address), ''),
                nullif(btrim(p_memo), ''),
                p_actor_id,
                p_actor_id
            ) RETURNING customer.* INTO v_customer;

            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, property_id, resulting_state, correlation_id,
                source, outcome, customer_id
            ) VALUES (
                p_event_id, statement_timestamp(),
                timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                p_actor_id, 'customer.created', 'customer', p_id,
                'Canonical Customer identity created', v_property_id,
                jsonb_build_object(
                    'customer_id', v_customer.id,
                    'legal_name', v_customer.legal_name,
                    'phone_number', v_customer.phone_number,
                    'email_address', v_customer.email_address,
                    'contact_address', v_customer.contact_address,
                    'memo', v_customer.memo,
                    'version', v_customer.version
                ),
                p_event_id, 'API', 'SUCCEEDED', p_id
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.update_customer(
            p_id uuid,
            p_legal_name text,
            p_phone_number text,
            p_email_address text,
            p_contact_address text,
            p_memo text,
            p_expected_version integer,
            p_actor_id uuid,
            p_event_id uuid
        )
        RETURNS TABLE(
            id uuid,
            legal_name text,
            phone_number text,
            email_address text,
            contact_address text,
            memo text,
            version integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_previous app.customers%ROWTYPE;
            v_customer app.customers%ROWTYPE;
            v_property_id uuid;
        BEGIN
            SELECT customer.* INTO v_previous
            FROM app.customers AS customer
            WHERE customer.id = p_id
            FOR UPDATE;
            IF NOT FOUND OR v_previous.version <> p_expected_version THEN
                RETURN;
            END IF;
            SELECT property.id INTO STRICT v_property_id FROM app.properties AS property LIMIT 1;
            UPDATE app.customers AS customer
            SET legal_name = btrim(p_legal_name),
                phone_number = nullif(btrim(p_phone_number), ''),
                email_address = nullif(btrim(p_email_address), ''),
                contact_address = nullif(btrim(p_contact_address), ''),
                memo = nullif(btrim(p_memo), ''),
                version = customer.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE customer.id = p_id
            RETURNING customer.* INTO v_customer;

            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, property_id, previous_state, resulting_state,
                correlation_id, source, outcome, customer_id
            ) VALUES (
                p_event_id, statement_timestamp(),
                timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                p_actor_id, 'customer.updated', 'customer', p_id,
                'Current Customer contact values updated without changing identity',
                v_property_id,
                jsonb_build_object(
                    'customer_id', v_previous.id,
                    'legal_name', v_previous.legal_name,
                    'phone_number', v_previous.phone_number,
                    'email_address', v_previous.email_address,
                    'contact_address', v_previous.contact_address,
                    'memo', v_previous.memo,
                    'version', v_previous.version
                ),
                jsonb_build_object(
                    'customer_id', v_customer.id,
                    'legal_name', v_customer.legal_name,
                    'phone_number', v_customer.phone_number,
                    'email_address', v_customer.email_address,
                    'contact_address', v_customer.contact_address,
                    'memo', v_customer.memo,
                    'version', v_customer.version
                ),
                p_event_id, 'API', 'SUCCEEDED', p_id
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.reject_customer_history_loss() FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON TABLE app.customers FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.customers TO prm_runtime")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "app.create_customer(uuid, text, text, text, text, text, uuid, uuid) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "app.update_customer(uuid, text, text, text, text, text, integer, uuid, uuid) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.create_customer(uuid, text, text, text, text, text, uuid, uuid) TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.update_customer(uuid, text, text, text, text, text, integer, uuid, uuid) "
        "TO prm_runtime"
    )


def downgrade() -> None:
    """Refuse destructive rollback of canonical Customer identity and history."""
    raise RuntimeError("Customer identity and history migration is forward-only")
