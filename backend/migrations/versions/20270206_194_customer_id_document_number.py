"""The Customer ID number / Passport number, refused when another Customer has it (V1-059 B).

DL-071 answer 11 with the owner's 2026-10-21 answer (docs-only rules update 1c), SEC-006,
BR-CUST-002, DB-CUST-001, TCD-DB-001; technical points decided by Claude under the owner's
2026-10-23 22:30 rule; the owner's go-ahead for this tightening check: V1-059 part B.

- `app.customers.id_document_number`: the ID card or passport number as staff typed it (trimmed,
  at most 64 characters). Customers recorded before have none until staff add it (DL-071
  transition); once recorded it may be corrected but never cleared.
- `app.customer_id_document_match_key(text)`: the compared form: spaces and dashes removed and
  capital letters ignored. A unique index on it refuses a second Customer with the same number
  (deactivated Customers included), whichever commit comes second.
- New overloads with a last `p_id_document_number` parameter of `app.create_customer`,
  `app.execute_customer_create`, `app.update_customer` and `app.execute_customer_update`: the
  same steps as the overloads they extend, with the number stored, returned and kept in the
  command's replay result. Create needs the number. The audit history records only whether a
  number is recorded and whether it changed, never the number itself (SEC-006).

The ID number is not part of the top bar search or of any export (DL-071 answer 11, UI-010).
A new column, a new function, a new index and four new overloads; no stored row changes.
"""

from alembic import op

revision = "20270206_194"
down_revision = "20270205_193"
branch_labels = None
depends_on = None

RETURNS = """RETURNS TABLE (
            id uuid,
            legal_name text,
            phone_number text,
            email_address text,
            contact_address text,
            memo text,
            version integer,
            id_document_number text
        )"""

CREATE_CUSTOMER = f"""
        CREATE FUNCTION app.create_customer(
            p_id uuid,
            p_legal_name text,
            p_phone_number text,
            p_email_address text,
            p_contact_address text,
            p_memo text,
            p_actor_id uuid,
            p_event_id uuid,
            p_id_document_number text
        ) {RETURNS}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_customer app.customers%ROWTYPE;
            v_property_id uuid;
        BEGIN
            IF nullif(btrim(p_id_document_number), '') IS NULL THEN
                RAISE EXCEPTION 'Customer ID number is required' USING ERRCODE = '22023';
            END IF;
            SELECT property.id INTO STRICT v_property_id FROM app.properties AS property LIMIT 1;
            INSERT INTO app.customers AS customer (
                id, legal_name, phone_number, email_address, contact_address, memo,
                id_document_number, created_by, updated_by
            ) VALUES (
                p_id,
                btrim(p_legal_name),
                nullif(btrim(p_phone_number), ''),
                nullif(btrim(p_email_address), ''),
                nullif(btrim(p_contact_address), ''),
                nullif(btrim(p_memo), ''),
                btrim(p_id_document_number),
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
                    'version', v_customer.version,
                    'id_document_number_recorded', true
                ),
                p_event_id, 'API', 'SUCCEEDED', p_id
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version, v_customer.id_document_number;
        END;
        $$
"""

UPDATE_CUSTOMER = f"""
        CREATE FUNCTION app.update_customer(
            p_id uuid,
            p_legal_name text,
            p_phone_number text,
            p_email_address text,
            p_contact_address text,
            p_memo text,
            p_expected_version integer,
            p_actor_id uuid,
            p_event_id uuid,
            p_id_document_number text
        ) {RETURNS}
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
            IF v_previous.id_document_number IS NOT NULL
                AND nullif(btrim(p_id_document_number), '') IS NULL
            THEN
                RAISE EXCEPTION 'Customer ID number cannot be removed' USING ERRCODE = '22023';
            END IF;
            SELECT property.id INTO STRICT v_property_id FROM app.properties AS property LIMIT 1;
            UPDATE app.customers AS customer
            SET legal_name = btrim(p_legal_name),
                phone_number = nullif(btrim(p_phone_number), ''),
                email_address = nullif(btrim(p_email_address), ''),
                contact_address = nullif(btrim(p_contact_address), ''),
                memo = nullif(btrim(p_memo), ''),
                id_document_number = nullif(btrim(p_id_document_number), ''),
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
                    'version', v_previous.version,
                    'id_document_number_recorded', v_previous.id_document_number IS NOT NULL
                ),
                jsonb_build_object(
                    'customer_id', v_customer.id,
                    'legal_name', v_customer.legal_name,
                    'phone_number', v_customer.phone_number,
                    'email_address', v_customer.email_address,
                    'contact_address', v_customer.contact_address,
                    'memo', v_customer.memo,
                    'version', v_customer.version,
                    'id_document_number_recorded', v_customer.id_document_number IS NOT NULL,
                    'id_document_number_changed',
                        v_customer.id_document_number
                            IS DISTINCT FROM v_previous.id_document_number
                ),
                p_event_id, 'API', 'SUCCEEDED', p_id
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version, v_customer.id_document_number;
        END;
        $$
"""


def execute_command(action: str) -> str:
    """The idempotent command wrapper of one action, with the ID number in its replay result."""
    create = action == "create"
    version_parameter = "" if create else "\n            p_expected_version integer,"
    version_argument = "" if create else " p_expected_version,"
    event_argument = (
        "p_actor_id, v_event_id" if create else "p_actor_id,\n                v_event_id"
    )
    missing_result = (
        ""
        if create
        else """
            IF v_customer.id IS NULL THEN
                RETURN;
            END IF;"""
    )
    return f"""
        CREATE FUNCTION app.execute_customer_{action}(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_id uuid,
            p_legal_name text,
            p_phone_number text,
            p_email_address text,
            p_contact_address text,
            p_memo text,{version_parameter}
            p_actor_id uuid,
            p_id_document_number text
        ) {RETURNS}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.customer_commands%ROWTYPE;
            v_customer record;
            v_actual_property_id uuid;
            v_event_id uuid := pg_catalog.gen_random_uuid();
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'customer-command:' || p_actor_id::text || ':'
                    || p_property_id::text || ':{action}:' || p_idempotency_key::text,
                    0
                )
            );
            PERFORM app.archive_expired_customer_command(
                p_actor_id, p_property_id, '{action}', p_idempotency_key
            );
            PERFORM app.purge_expired_customer_commands(1000);
            SELECT command.* INTO v_command FROM app.customer_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = '{action}'
              AND command.idempotency_key = p_idempotency_key
              AND command.expires_at > statement_timestamp();
            IF FOUND THEN
                IF v_command.customer_id <> p_id
                    OR v_command.request_digest <> p_request_digest
                THEN
                    RAISE EXCEPTION 'Customer command identity was reused for different input'
                        USING ERRCODE = '22023';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_state ->> 'customer_id')::uuid,
                    v_command.result_state ->> 'legal_name',
                    nullif(v_command.result_state ->> 'phone_number', ''),
                    nullif(v_command.result_state ->> 'email_address', ''),
                    nullif(v_command.result_state ->> 'contact_address', ''),
                    nullif(v_command.result_state ->> 'memo', ''),
                    (v_command.result_state ->> 'version')::integer,
                    nullif(v_command.result_state ->> 'id_document_number', '');
                RETURN;
            END IF;
            SELECT property.id INTO STRICT v_actual_property_id
            FROM app.properties AS property LIMIT 1;
            IF v_actual_property_id <> p_property_id THEN
                RAISE EXCEPTION 'Property does not match Customer command'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_customer FROM app.{action}_customer(
                p_id, p_legal_name, p_phone_number, p_email_address,
                p_contact_address, p_memo,{version_argument} {event_argument},
                p_id_document_number
            );{missing_result}
            INSERT INTO app.customer_commands (
                actor_id, property_id, action, idempotency_key, event_id, request_digest,
                customer_id, result_state
            ) VALUES (
                p_actor_id, p_property_id, '{action}', p_idempotency_key, v_event_id,
                p_request_digest,
                p_id, jsonb_build_object(
                    'customer_id', v_customer.id,
                    'legal_name', v_customer.legal_name,
                    'phone_number', v_customer.phone_number,
                    'email_address', v_customer.email_address,
                    'contact_address', v_customer.contact_address,
                    'memo', v_customer.memo,
                    'version', v_customer.version,
                    'deactivated_at', NULL,
                    'deactivation_reason', NULL,
                    'id_document_number', v_customer.id_document_number
                )
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version, v_customer.id_document_number;
        END;
        $$
"""


SIGNATURES = (
    "app.create_customer(uuid, text, text, text, text, text, uuid, uuid, text)",
    "app.update_customer(uuid, text, text, text, text, text, integer, uuid, uuid, text)",
    "app.execute_customer_create(uuid, uuid, text, uuid, text, text, text, text, text, uuid, text)",
    "app.execute_customer_update("
    "uuid, uuid, text, uuid, text, text, text, text, text, integer, uuid, text)",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.customer_id_document_match_key(p_id_document_number text)
        RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
            SELECT pg_catalog.lower(
                pg_catalog.regexp_replace(p_id_document_number, '[[:space:]-]', '', 'g')
            )
        $$;
        REVOKE ALL ON FUNCTION app.customer_id_document_match_key(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.customer_id_document_match_key(text) TO prm_runtime;

        ALTER TABLE app.customers
            ADD COLUMN id_document_number text,
            ADD CONSTRAINT customers_id_document_number_normalized CHECK (
                id_document_number IS NULL
                OR (
                    id_document_number = btrim(id_document_number)
                    AND length(id_document_number) BETWEEN 1 AND 64
                    AND app.customer_id_document_match_key(id_document_number) <> ''
                )
            );

        CREATE UNIQUE INDEX customers_id_document_number_unique
            ON app.customers (app.customer_id_document_match_key(id_document_number))
            WHERE id_document_number IS NOT NULL;
        """
    )
    for statement in (
        CREATE_CUSTOMER,
        UPDATE_CUSTOMER,
        execute_command("create"),
        execute_command("update"),
    ):
        op.execute(statement)
    for signature in SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURES[2]}, {SIGNATURES[3]} TO prm_runtime")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURES[0]}, {SIGNATURES[1]} TO prm_runtime")
    # A new Customer needs the number: the runtime role can no longer call the earlier create
    # overloads (review round 1). The earlier update overloads keep the number as it is.
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "app.create_customer(uuid, text, text, text, text, text, uuid, uuid), "
        "app.execute_customer_create(uuid, uuid, text, uuid, text, text, text, text, text, uuid) "
        "FROM prm_runtime"
    )


def downgrade() -> None:
    """Forward-only: removing the column would lose recorded ID numbers."""
    raise RuntimeError("Customer ID number migration is forward-only")
