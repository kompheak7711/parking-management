"""Customer details: date of birth, gender and nationality (V1-058 R2, DL-078 answer 3).

DL-078 answer 3 (owner, 2026-10-20; the owner's confirmation is the SEC-006 approval for these
three fields), DB-CUST-001 and BR-CUST-003 as amended by DL-078; technical points decided by
Claude under the owner's 2026-10-23 22:30 rule.

- `app.customers.date_of_birth` (optional, from 01/01/1900 to today in Phnom Penh),
  `app.customers.gender` (optional, FEMALE or MALE) and `app.customers.nationality` (optional,
  trimmed, at most 64 characters).
- New overloads, with three last parameters, of `app.create_customer`,
  `app.execute_customer_create`, `app.update_customer` and `app.execute_customer_update`: the
  same steps as the 20270206_194 overloads they extend, with the three details stored, returned
  and kept in the command's replay result. The audit history records only whether each detail
  is recorded and whether it changed, never its value (SEC-006), as for the ID number.
- The earlier overloads stay; an update through them keeps the three details as they are.

Changing details never changes past records (BR-CUST-003). New columns, one new function and
four new overloads; no stored row changes.
"""

from alembic import op

revision = "20270215_203"
down_revision = "20270214_202"
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
            id_document_number text,
            date_of_birth date,
            gender text,
            nationality text
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
            p_id_document_number text,
            p_date_of_birth date,
            p_gender text,
            p_nationality text
        ) {RETURNS}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_customer app.customers%ROWTYPE;
            v_property_id uuid;
        BEGIN
            PERFORM app.assert_customer_details(p_date_of_birth, p_gender, p_nationality);
            IF nullif(btrim(p_id_document_number), '') IS NULL THEN
                RAISE EXCEPTION 'Customer ID number is required' USING ERRCODE = '22023';
            END IF;
            SELECT property.id INTO STRICT v_property_id FROM app.properties AS property LIMIT 1;
            INSERT INTO app.customers AS customer (
                id, legal_name, phone_number, email_address, contact_address, memo,
                id_document_number, date_of_birth, gender, nationality, created_by, updated_by
            ) VALUES (
                p_id,
                btrim(p_legal_name),
                nullif(btrim(p_phone_number), ''),
                nullif(btrim(p_email_address), ''),
                nullif(btrim(p_contact_address), ''),
                nullif(btrim(p_memo), ''),
                btrim(p_id_document_number),
                p_date_of_birth,
                p_gender,
                nullif(btrim(p_nationality), ''),
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
                    'id_document_number_recorded', true,
                    'date_of_birth_recorded', v_customer.date_of_birth IS NOT NULL,
                    'gender_recorded', v_customer.gender IS NOT NULL,
                    'nationality_recorded', v_customer.nationality IS NOT NULL
                ),
                p_event_id, 'API', 'SUCCEEDED', p_id
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version, v_customer.id_document_number,
                v_customer.date_of_birth, v_customer.gender, v_customer.nationality;
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
            p_id_document_number text,
            p_date_of_birth date,
            p_gender text,
            p_nationality text
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
            PERFORM app.assert_customer_details(p_date_of_birth, p_gender, p_nationality);
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
                date_of_birth = p_date_of_birth,
                gender = p_gender,
                nationality = nullif(btrim(p_nationality), ''),
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
                    'id_document_number_recorded', v_previous.id_document_number IS NOT NULL,
                    'date_of_birth_recorded', v_previous.date_of_birth IS NOT NULL,
                    'gender_recorded', v_previous.gender IS NOT NULL,
                    'nationality_recorded', v_previous.nationality IS NOT NULL
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
                            IS DISTINCT FROM v_previous.id_document_number,
                    'date_of_birth_recorded', v_customer.date_of_birth IS NOT NULL,
                    'date_of_birth_changed',
                        v_customer.date_of_birth IS DISTINCT FROM v_previous.date_of_birth,
                    'gender_recorded', v_customer.gender IS NOT NULL,
                    'gender_changed', v_customer.gender IS DISTINCT FROM v_previous.gender,
                    'nationality_recorded', v_customer.nationality IS NOT NULL,
                    'nationality_changed',
                        v_customer.nationality IS DISTINCT FROM v_previous.nationality
                ),
                p_event_id, 'API', 'SUCCEEDED', p_id
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version, v_customer.id_document_number,
                v_customer.date_of_birth, v_customer.gender, v_customer.nationality;
        END;
        $$
"""


def execute_command(action: str) -> str:
    """The idempotent command wrapper of one action, with the details in its replay result."""
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
            p_id_document_number text,
            p_date_of_birth date,
            p_gender text,
            p_nationality text
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
                    nullif(v_command.result_state ->> 'id_document_number', ''),
                    (v_command.result_state ->> 'date_of_birth')::date,
                    v_command.result_state ->> 'gender',
                    v_command.result_state ->> 'nationality';
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
                p_id_document_number, p_date_of_birth, p_gender, p_nationality
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
                    'id_document_number', v_customer.id_document_number,
                    'date_of_birth', v_customer.date_of_birth,
                    'gender', v_customer.gender,
                    'nationality', v_customer.nationality
                )
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version, v_customer.id_document_number,
                v_customer.date_of_birth, v_customer.gender, v_customer.nationality;
        END;
        $$
"""


SIGNATURES = (
    "app.create_customer(uuid, text, text, text, text, text, uuid, uuid, text, date, text, text)",
    "app.update_customer("
    "uuid, text, text, text, text, text, integer, uuid, uuid, text, date, text, text)",
    "app.execute_customer_create("
    "uuid, uuid, text, uuid, text, text, text, text, text, uuid, text, date, text, text)",
    "app.execute_customer_update("
    "uuid, uuid, text, uuid, text, text, text, text, text, integer, uuid, text, date, text, text)",
)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.customers
            ADD COLUMN date_of_birth date,
            ADD COLUMN gender text,
            ADD COLUMN nationality text,
            ADD CONSTRAINT customers_date_of_birth_range CHECK (
                date_of_birth IS NULL OR date_of_birth >= DATE '1900-01-01'
            ),
            ADD CONSTRAINT customers_gender_supported CHECK (
                gender IS NULL OR gender IN ('FEMALE', 'MALE')
            ),
            ADD CONSTRAINT customers_nationality_normalized CHECK (
                nationality IS NULL
                OR (nationality = btrim(nationality) AND length(nationality) BETWEEN 1 AND 64)
            );

        CREATE FUNCTION app.assert_customer_details(
            p_date_of_birth date,
            p_gender text,
            p_nationality text
        ) RETURNS void
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF p_date_of_birth IS NOT NULL AND (
                p_date_of_birth < DATE '1900-01-01'
                OR p_date_of_birth > timezone('Asia/Phnom_Penh', statement_timestamp())::date
            ) THEN
                RAISE EXCEPTION 'Customer date of birth is outside 01/01/1900 to today'
                    USING ERRCODE = '22023';
            END IF;
            IF p_gender IS NOT NULL AND p_gender NOT IN ('FEMALE', 'MALE') THEN
                RAISE EXCEPTION 'Customer gender is not supported' USING ERRCODE = '22023';
            END IF;
            IF p_nationality IS NOT NULL AND length(btrim(p_nationality)) > 64 THEN
                RAISE EXCEPTION 'Customer nationality is too long' USING ERRCODE = '22023';
            END IF;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.assert_customer_details(date, text, text) FROM PUBLIC;
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


def downgrade() -> None:
    """Forward-only: removing the columns would lose recorded Customer details."""
    raise RuntimeError("Customer details migration is forward-only")
