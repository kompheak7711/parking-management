"""Add history-safe Customer deactivation without deleting identity."""

from hashlib import md5

from alembic import op
from sqlalchemy import text

revision = "20260824_16"
down_revision = "20260824_15"
branch_labels = None
depends_on = None

CUSTOMER_COMMAND_RETENTION_HOURS = 24
EMAIL_BACKFILL_BATCH_SIZE = 1_000


def _legacy_email_match_digest(value: str) -> str:
    """Return the application-equivalent technical key for a revision-15 email."""
    normalized = value.strip()
    if normalized.count("@") == 1:
        local, domain = normalized.rsplit("@", 1)
        try:
            ascii_domain = domain.encode("idna").decode("ascii").lower()
        except UnicodeError:
            # Revision 15 intentionally imposed no structural email constraint.
            # Preserve a deterministic key for malformed legacy source instead of
            # letting one historic value prevent the forward-only migration.
            pass
        else:
            normalized = f"{local}@{ascii_domain}"
    return md5(normalized.casefold().encode(), usedforsecurity=False).hexdigest()


def _backfill_legacy_email_match_keys(connection: object) -> None:
    """Stream revision-15 email source and persist bounded batches."""
    streaming_connection = connection.execution_options(
        stream_results=True,
        yield_per=EMAIL_BACKFILL_BATCH_SIZE,
    )
    try:
        legacy_emails = streaming_connection.execute(
            text("SELECT id, email_address FROM app.customers WHERE email_address IS NOT NULL")
        )
    finally:
        connection.execution_options(stream_results=False, yield_per=None)
    insert_match_keys = text(
        "INSERT INTO app.customer_email_match_keys (customer_id, match_digest) "
        "VALUES (:customer_id, :match_digest)"
    )
    try:
        while batch := legacy_emails.fetchmany(EMAIL_BACKFILL_BATCH_SIZE):
            connection.execute(
                insert_match_keys,
                [
                    {
                        "customer_id": customer_id,
                        "match_digest": _legacy_email_match_digest(str(email_address)),
                    }
                    for customer_id, email_address in batch
                ],
            )
    finally:
        legacy_emails.close()


def upgrade() -> None:
    """Add a protected lifecycle boundary that preserves Customer history."""
    op.execute(
        """
        CREATE TABLE app.customer_email_match_keys (
            customer_id uuid PRIMARY KEY,
            match_digest text NOT NULL CHECK (match_digest ~ '^[0-9a-f]{32}$')
        )
        """
    )
    connection = op.get_bind()
    # Revision 15 has no synchronization trigger. Hold Customer writers while
    # the streamed snapshot is materialized, then install the trigger in this
    # same migration transaction before releasing the lock at commit.
    op.execute("LOCK TABLE app.customers IN EXCLUSIVE MODE")
    _backfill_legacy_email_match_keys(connection)
    op.execute(
        "REVOKE ALL ON TABLE app.customer_email_match_keys FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.customer_email_match_keys TO prm_runtime")
    op.execute(
        "CREATE INDEX customer_email_match_keys_digest_idx "
        "ON app.customer_email_match_keys (match_digest)"
    )
    op.execute(
        """
        CREATE FUNCTION app.guard_customer_email_match_key()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.email_address IS NOT NULL
                AND (TG_OP = 'INSERT' OR NEW.email_address IS DISTINCT FROM OLD.email_address)
                AND octet_length(NEW.email_address) <> char_length(NEW.email_address)
            THEN
                RAISE EXCEPTION 'New Customer email input must use ASCII or an ASCII IDN form'
                    USING ERRCODE = '22023';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER customers_guard_email_match_key
        BEFORE INSERT OR UPDATE OF email_address ON app.customers
        FOR EACH ROW EXECUTE FUNCTION app.guard_customer_email_match_key()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.sync_customer_email_match_key()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.email_address IS NOT DISTINCT FROM OLD.email_address THEN
                RETURN NEW;
            END IF;
            IF NEW.email_address IS NULL THEN
                DELETE FROM app.customer_email_match_keys WHERE customer_id = NEW.id;
            ELSE
                INSERT INTO app.customer_email_match_keys (customer_id, match_digest)
                VALUES (NEW.id, md5(lower(NEW.email_address COLLATE "C")))
                ON CONFLICT (customer_id) DO UPDATE
                SET match_digest = EXCLUDED.match_digest;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER customers_sync_email_match_key
        AFTER INSERT OR UPDATE OF email_address ON app.customers
        FOR EACH ROW EXECUTE FUNCTION app.sync_customer_email_match_key()
        """
    )
    op.execute(
        """
        CREATE INDEX audit_events_customer_history_page_idx
        ON app.audit_events (
            property_id, customer_id, occurred_at DESC, id DESC
        )
        WHERE customer_id IS NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX customers_legal_name_search_prefix_idx "
        "ON app.customers ((left(lower(legal_name), 255)) text_pattern_ops)"
    )
    op.execute(
        "CREATE INDEX customers_email_search_prefix_idx "
        "ON app.customers ((left(lower(email_address), 320)) text_pattern_ops)"
    )
    op.execute(
        "CREATE INDEX customers_phone_search_prefix_idx ON app.customers "
        "((left(regexp_replace(phone_number, '[^0-9]', '', 'g'), 100)) "
        "text_pattern_ops)"
    )
    op.execute("ALTER TABLE app.customers ADD COLUMN deactivated_at timestamptz")
    op.execute("ALTER TABLE app.customers ADD COLUMN deactivation_reason text")
    op.execute(
        """
        ALTER TABLE app.customers
        ADD CONSTRAINT customers_deactivation_complete CHECK (
            (deactivated_at IS NULL AND deactivation_reason IS NULL)
            OR (
                deactivated_at IS NOT NULL
                AND deactivation_reason IS NOT NULL
                AND deactivation_reason ~ '[^[:space:]]'
                AND deactivation_reason !~ '^[[:space:]]'
                AND deactivation_reason !~ '[[:space:]]$'
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_deactivated_customer_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF OLD.deactivated_at IS NOT NULL THEN
                RAISE EXCEPTION 'Deactivated Customer source data is read-only'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER customers_reject_post_deactivation_update
        BEFORE UPDATE ON app.customers
        FOR EACH ROW EXECUTE FUNCTION app.reject_deactivated_customer_mutation()
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.reject_deactivated_customer_mutation() FROM PUBLIC")
    op.execute(
        """
        CREATE FUNCTION app.deactivate_customer(
            p_id uuid,
            p_reason text,
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
            version integer,
            deactivated_at timestamptz,
            deactivation_reason text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_previous app.customers%ROWTYPE;
            v_customer record;
            v_property_id uuid;
            v_reason text;
        BEGIN
            v_reason := regexp_replace(
                p_reason,
                '^[[:space:]]+|[[:space:]]+$',
                '',
                'g'
            );
            IF v_reason IS NULL OR v_reason !~ '[^[:space:]]' THEN
                RAISE EXCEPTION 'Customer deactivation reason must not be blank'
                    USING ERRCODE = '23514';
            END IF;
            SELECT customer.* INTO v_previous
            FROM app.customers AS customer
            WHERE customer.id = p_id
            FOR UPDATE;
            IF NOT FOUND
                OR p_expected_version IS NULL
                OR v_previous.version <> p_expected_version
            THEN
                RETURN;
            END IF;
            IF v_previous.deactivated_at IS NOT NULL THEN
                RAISE EXCEPTION 'Customer is already deactivated'
                    USING ERRCODE = '23514';
            END IF;
            SELECT property.id INTO STRICT v_property_id FROM app.properties AS property LIMIT 1;
            UPDATE app.customers AS customer
            SET deactivated_at = statement_timestamp(),
                deactivation_reason = v_reason,
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
                p_actor_id, 'customer.deactivated', 'customer', p_id,
                v_reason, v_property_id,
                jsonb_build_object(
                    'customer_id', v_previous.id,
                    'active', true,
                    'version', v_previous.version
                ),
                jsonb_build_object(
                    'customer_id', v_customer.id,
                    'active', false,
                    'deactivated_at', v_customer.deactivated_at,
                    'deactivation_reason', v_customer.deactivation_reason,
                    'version', v_customer.version
                ),
                p_event_id, 'API', 'SUCCEEDED', p_id
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version, v_customer.deactivated_at,
                v_customer.deactivation_reason;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "app.deactivate_customer(uuid, text, integer, uuid, uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.deactivate_customer(uuid, text, integer, uuid, uuid) TO prm_runtime"
    )
    op.execute(
        """
        CREATE TABLE app.customer_commands (
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            property_id uuid NOT NULL REFERENCES app.properties(id),
            action text NOT NULL CHECK (action IN ('create', 'update', 'deactivate')),
            idempotency_key uuid NOT NULL,
            event_id uuid NOT NULL UNIQUE,
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            customer_id uuid NOT NULL,
            result_state jsonb NOT NULL CHECK (jsonb_typeof(result_state) = 'object'),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            expires_at timestamptz NOT NULL DEFAULT (
                statement_timestamp() + interval '24 hours'
            ),
            CHECK (expires_at > created_at),
            PRIMARY KEY (actor_id, property_id, action, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX customer_commands_actor_lookup_idx ON app.customer_commands "
        "(actor_id, property_id, customer_id, action, idempotency_key)"
    )
    op.execute("CREATE INDEX customer_commands_expiry_idx ON app.customer_commands (expires_at)")
    op.execute("REVOKE ALL ON TABLE app.customer_commands FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute(
        """
        CREATE TABLE app.customer_command_tombstones (
            actor_id uuid NOT NULL,
            property_id uuid NOT NULL,
            action text NOT NULL CHECK (action IN ('create', 'update', 'deactivate')),
            idempotency_key uuid NOT NULL,
            customer_id uuid NOT NULL,
            event_id uuid NOT NULL UNIQUE,
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            expired_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (actor_id, property_id, action, idempotency_key)
        )
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE app.customer_command_tombstones "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.customer_command_tombstones TO prm_runtime")
    op.execute(
        """
        CREATE FUNCTION app.purge_expired_customer_commands(p_limit integer)
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_deleted integer;
        BEGIN
            IF p_limit < 1 OR p_limit > 1000 THEN
                RAISE EXCEPTION 'Invalid Customer command cleanup bound' USING ERRCODE = '22023';
            END IF;
            WITH expired AS MATERIALIZED (
                SELECT expired.ctid, expired.actor_id, expired.property_id,
                       expired.action, expired.idempotency_key, expired.customer_id,
                       expired.event_id, expired.request_digest, expired.expires_at
                FROM app.customer_commands AS expired
                WHERE expired.expires_at <= statement_timestamp()
                ORDER BY expired.expires_at
                LIMIT p_limit
                FOR UPDATE SKIP LOCKED
            ), archived AS (
                INSERT INTO app.customer_command_tombstones (
                    actor_id, property_id, action, idempotency_key, customer_id,
                    event_id, request_digest, expired_at
                )
                SELECT actor_id, property_id, action, idempotency_key, customer_id,
                       event_id, request_digest, expires_at
                FROM expired
                ON CONFLICT (actor_id, property_id, action, idempotency_key) DO UPDATE
                SET customer_id = EXCLUDED.customer_id,
                    event_id = EXCLUDED.event_id,
                    request_digest = EXCLUDED.request_digest,
                    expired_at = EXCLUDED.expired_at
                RETURNING 1
            )
            DELETE FROM app.customer_commands AS command
            USING expired
            WHERE command.ctid = expired.ctid;
            GET DIAGNOSTICS v_deleted = ROW_COUNT;
            RETURN v_deleted;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.purge_expired_customer_commands(integer) FROM PUBLIC")
    op.execute(
        """
        CREATE FUNCTION app.archive_expired_customer_command(
            p_actor_id uuid,
            p_property_id uuid,
            p_action text,
            p_idempotency_key uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            INSERT INTO app.customer_command_tombstones (
                actor_id, property_id, action, idempotency_key, customer_id,
                event_id, request_digest, expired_at
            )
            SELECT command.actor_id, command.property_id, command.action,
                   command.idempotency_key, command.customer_id, command.event_id,
                   command.request_digest, command.expires_at
            FROM app.customer_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = p_action
              AND command.idempotency_key = p_idempotency_key
              AND command.expires_at <= statement_timestamp()
            ON CONFLICT (actor_id, property_id, action, idempotency_key) DO UPDATE
            SET customer_id = EXCLUDED.customer_id,
                event_id = EXCLUDED.event_id,
                request_digest = EXCLUDED.request_digest,
                expired_at = EXCLUDED.expired_at;

            DELETE FROM app.customer_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = p_action
              AND command.idempotency_key = p_idempotency_key
              AND command.expires_at <= statement_timestamp();
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "app.archive_expired_customer_command(uuid, uuid, text, uuid) FROM PUBLIC"
    )
    op.execute(
        """
        CREATE FUNCTION app.get_customer_command(
            p_actor_id uuid,
            p_property_id uuid,
            p_action text,
            p_idempotency_key uuid,
            p_customer_id uuid,
            p_request_digest text DEFAULT NULL
        )
        RETURNS TABLE(
            id uuid,
            legal_name text,
            phone_number text,
            email_address text,
            contact_address text,
            memo text,
            version integer,
            deactivated_at timestamptz,
            deactivation_reason text,
            property_id uuid,
            event_id uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.customer_commands%ROWTYPE;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'customer-command:' || p_actor_id::text || ':'
                    || p_property_id::text || ':' || p_action || ':'
                    || p_idempotency_key::text,
                    0
                )
            );
            PERFORM app.archive_expired_customer_command(
                p_actor_id, p_property_id, p_action, p_idempotency_key
            );
            PERFORM app.purge_expired_customer_commands(1000);
            SELECT command.* INTO v_command
            FROM app.customer_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = p_action
              AND command.idempotency_key = p_idempotency_key
              AND command.expires_at > statement_timestamp();
            IF NOT FOUND THEN
                RETURN;
            END IF;
            IF v_command.customer_id <> p_customer_id
                OR (
                    p_request_digest IS NOT NULL
                    AND v_command.request_digest <> p_request_digest
                )
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
                (v_command.result_state ->> 'deactivated_at')::timestamptz,
                nullif(v_command.result_state ->> 'deactivation_reason', ''),
                v_command.property_id,
                v_command.event_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.execute_customer_create(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_id uuid,
            p_legal_name text,
            p_phone_number text,
            p_email_address text,
            p_contact_address text,
            p_memo text,
            p_actor_id uuid
        )
        RETURNS TABLE(
            id uuid, legal_name text, phone_number text, email_address text,
            contact_address text, memo text, version integer
        )
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
                    || p_property_id::text || ':create:' || p_idempotency_key::text,
                    0
                )
            );
            PERFORM app.archive_expired_customer_command(
                p_actor_id, p_property_id, 'create', p_idempotency_key
            );
            PERFORM app.purge_expired_customer_commands(1000);
            SELECT command.* INTO v_command FROM app.customer_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'create'
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
                    (v_command.result_state ->> 'version')::integer;
                RETURN;
            END IF;
            SELECT property.id INTO STRICT v_actual_property_id
            FROM app.properties AS property LIMIT 1;
            IF v_actual_property_id <> p_property_id THEN
                RAISE EXCEPTION 'Property does not match Customer command'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_customer FROM app.create_customer(
                p_id, p_legal_name, p_phone_number, p_email_address,
                p_contact_address, p_memo, p_actor_id, v_event_id
            );
            INSERT INTO app.customer_commands (
                actor_id, property_id, action, idempotency_key, event_id, request_digest,
                customer_id, result_state
            ) VALUES (
                p_actor_id, p_property_id, 'create', p_idempotency_key, v_event_id,
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
                    'deactivation_reason', NULL
                )
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
        CREATE FUNCTION app.execute_customer_update(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_id uuid,
            p_legal_name text,
            p_phone_number text,
            p_email_address text,
            p_contact_address text,
            p_memo text,
            p_expected_version integer,
            p_actor_id uuid
        )
        RETURNS TABLE(
            id uuid, legal_name text, phone_number text, email_address text,
            contact_address text, memo text, version integer
        )
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
                    || p_property_id::text || ':update:' || p_idempotency_key::text,
                    0
                )
            );
            PERFORM app.archive_expired_customer_command(
                p_actor_id, p_property_id, 'update', p_idempotency_key
            );
            PERFORM app.purge_expired_customer_commands(1000);
            SELECT command.* INTO v_command FROM app.customer_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'update'
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
                    (v_command.result_state ->> 'version')::integer;
                RETURN;
            END IF;
            SELECT property.id INTO STRICT v_actual_property_id
            FROM app.properties AS property LIMIT 1;
            IF v_actual_property_id <> p_property_id THEN
                RAISE EXCEPTION 'Property does not match Customer command'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_customer FROM app.update_customer(
                p_id, p_legal_name, p_phone_number, p_email_address,
                p_contact_address, p_memo, p_expected_version, p_actor_id,
                v_event_id
            );
            IF v_customer.id IS NULL THEN
                RETURN;
            END IF;
            INSERT INTO app.customer_commands (
                actor_id, property_id, action, idempotency_key, event_id, request_digest,
                customer_id, result_state
            ) VALUES (
                p_actor_id, p_property_id, 'update', p_idempotency_key, v_event_id,
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
                    'deactivation_reason', NULL
                )
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
        CREATE FUNCTION app.execute_customer_deactivate(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_id uuid,
            p_reason text,
            p_expected_version integer,
            p_actor_id uuid
        )
        RETURNS TABLE(
            id uuid, legal_name text, phone_number text, email_address text,
            contact_address text, memo text, version integer,
            deactivated_at timestamptz, deactivation_reason text
        )
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
                    || p_property_id::text || ':deactivate:' || p_idempotency_key::text,
                    0
                )
            );
            PERFORM app.archive_expired_customer_command(
                p_actor_id, p_property_id, 'deactivate', p_idempotency_key
            );
            PERFORM app.purge_expired_customer_commands(1000);
            SELECT command.* INTO v_command FROM app.customer_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'deactivate'
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
                    (v_command.result_state ->> 'deactivated_at')::timestamptz,
                    nullif(v_command.result_state ->> 'deactivation_reason', '');
                RETURN;
            END IF;
            SELECT property.id INTO STRICT v_actual_property_id
            FROM app.properties AS property LIMIT 1;
            IF v_actual_property_id <> p_property_id THEN
                RAISE EXCEPTION 'Property does not match Customer command'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_customer FROM app.deactivate_customer(
                p_id, p_reason, p_expected_version, p_actor_id, v_event_id
            );
            IF v_customer.id IS NULL THEN
                RETURN;
            END IF;
            INSERT INTO app.customer_commands (
                actor_id, property_id, action, idempotency_key, event_id, request_digest,
                customer_id, result_state
            ) VALUES (
                p_actor_id, p_property_id, 'deactivate', p_idempotency_key, v_event_id,
                p_request_digest, p_id, jsonb_build_object(
                    'customer_id', v_customer.id,
                    'legal_name', v_customer.legal_name,
                    'phone_number', v_customer.phone_number,
                    'email_address', v_customer.email_address,
                    'contact_address', v_customer.contact_address,
                    'memo', v_customer.memo,
                    'version', v_customer.version,
                    'deactivated_at', v_customer.deactivated_at,
                    'deactivation_reason', v_customer.deactivation_reason
                )
            );
            RETURN QUERY SELECT
                v_customer.id, v_customer.legal_name, v_customer.phone_number,
                v_customer.email_address, v_customer.contact_address,
                v_customer.memo, v_customer.version, v_customer.deactivated_at,
                v_customer.deactivation_reason;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TABLE app.customer_search_rate_windows (
            bucket_key text PRIMARY KEY CHECK (bucket_key ~ '^[0-9a-f]{64}$'),
            window_started_at timestamptz NOT NULL,
            request_count integer NOT NULL CHECK (request_count > 0),
            updated_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE app.customer_search_rate_windows "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(
        """
        CREATE FUNCTION app.consume_customer_search_rate(
            p_bucket_key text,
            p_maximum integer,
            p_window_seconds double precision
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_now timestamptz := clock_timestamp();
            v_window interval;
            v_rate app.customer_search_rate_windows%ROWTYPE;
            v_bucket_count integer;
        BEGIN
            IF p_bucket_key !~ '^[0-9a-f]{64}$'
                OR p_maximum < 1
                OR p_window_seconds <= 0
                OR p_window_seconds > 60
            THEN
                RAISE EXCEPTION 'Invalid Customer search-rate input' USING ERRCODE = '22023';
            END IF;
            v_window := pg_catalog.make_interval(secs => p_window_seconds);
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('customer-search-rate:' || p_bucket_key, 0)
            );
            SELECT rate.* INTO v_rate
            FROM app.customer_search_rate_windows AS rate
            WHERE rate.bucket_key = p_bucket_key;
            IF NOT FOUND THEN
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended('customer-search-rate:bucket-cap', 0)
                );
                DELETE FROM app.customer_search_rate_windows
                WHERE updated_at <= v_now - pg_catalog.make_interval(secs => 60);
                SELECT count(*) INTO v_bucket_count
                FROM app.customer_search_rate_windows;
                IF v_bucket_count >= 10000 THEN
                    RETURN false;
                END IF;
                INSERT INTO app.customer_search_rate_windows (
                    bucket_key, window_started_at, request_count, updated_at
                ) VALUES (p_bucket_key, v_now, 1, v_now);
                RETURN true;
            END IF;
            IF v_rate.window_started_at + v_window <= v_now THEN
                INSERT INTO app.customer_search_rate_windows AS rate (
                    bucket_key, window_started_at, request_count, updated_at
                ) VALUES (p_bucket_key, v_now, 1, v_now)
                ON CONFLICT (bucket_key) DO UPDATE SET
                    window_started_at = EXCLUDED.window_started_at,
                    request_count = 1,
                    updated_at = EXCLUDED.updated_at;
                RETURN true;
            END IF;
            IF v_rate.request_count >= p_maximum THEN
                UPDATE app.customer_search_rate_windows
                SET updated_at = v_now WHERE bucket_key = p_bucket_key;
                RETURN false;
            END IF;
            UPDATE app.customer_search_rate_windows
            SET request_count = request_count + 1, updated_at = v_now
            WHERE bucket_key = p_bucket_key;
            RETURN true;
        END;
        $$
        """
    )
    for signature in (
        "app.get_customer_command(uuid, uuid, text, uuid, uuid, text)",
        "app.execute_customer_create(uuid, uuid, text, uuid, text, text, text, text, text, uuid)",
        "app.execute_customer_update(uuid, uuid, text, uuid, text, text, text, "
        "text, text, integer, uuid)",
        "app.execute_customer_deactivate(uuid, uuid, text, uuid, text, integer, uuid)",
        "app.consume_customer_search_rate(text, integer, double precision)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback that could erase published Customer lifecycle history."""
    raise RuntimeError("Customer deactivation migration is forward-only")
