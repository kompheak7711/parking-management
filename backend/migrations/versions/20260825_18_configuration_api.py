"""Add atomic idempotent commands for configuration APIs."""

from alembic import op

revision = "20260825_18"
down_revision = "20260825_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create bounded runtime command entry points without mutable history."""
    op.execute(
        """
        CREATE TABLE app.configuration_commands (
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            action text NOT NULL CHECK (
                action IN ('service_rate.create', 'utility_rate.create', 'exchange_rate.confirm')
            ),
            idempotency_key uuid NOT NULL,
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            result_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (actor_id, property_id, action, idempotency_key)
        )
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE app.configuration_commands "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(
        """
        CREATE TRIGGER configuration_commands_reject_update_or_delete
        BEFORE UPDATE OR DELETE ON app.configuration_commands
        FOR EACH ROW EXECUTE FUNCTION app.reject_append_only_configuration_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER configuration_commands_reject_truncate
        BEFORE TRUNCATE ON app.configuration_commands
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_append_only_configuration_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.execute_service_rate(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_rate_id uuid,
            p_property_service_id uuid,
            p_monthly_rate_usd_cents bigint,
            p_effective_date date,
            p_source_memo text,
            p_actor_id uuid
        )
        RETURNS TABLE(
            id uuid, property_id uuid, property_service_id uuid,
            service_code text, display_name text,
            monthly_rate_usd_cents bigint, effective_date date,
            source_memo text, occurred_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.configuration_commands%ROWTYPE;
            v_service app.property_services%ROWTYPE;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'configuration-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/service_rate.create/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.configuration_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'service_rate.create'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Configuration idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY
                SELECT rate.id, service.property_id, service.id,
                       service.service_code, service.display_name,
                       rate.monthly_rate_usd_cents, rate.effective_date,
                       rate.source_memo, rate.occurred_at
                FROM app.service_rates AS rate
                JOIN app.property_services AS service
                  ON service.id = rate.property_service_id
                WHERE rate.id = v_command.result_id;
                RETURN;
            END IF;
            SELECT service.* INTO v_service
            FROM app.property_services AS service
            WHERE service.id = p_property_service_id
              AND service.property_id = p_property_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Configured Service was not found' USING ERRCODE = 'P0002';
            END IF;
            INSERT INTO app.service_rates (
                id, property_service_id, monthly_rate_usd_cents,
                effective_date, source_memo, actor_id
            ) VALUES (
                p_rate_id, p_property_service_id, p_monthly_rate_usd_cents,
                p_effective_date, NULLIF(btrim(p_source_memo), ''), p_actor_id
            );
            INSERT INTO app.configuration_commands (
                actor_id, property_id, action, idempotency_key,
                request_digest, result_id
            ) VALUES (
                p_actor_id, p_property_id, 'service_rate.create',
                p_idempotency_key, p_request_digest, p_rate_id
            );
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference,
                property_id, resulting_state, correlation_id, source, outcome
            ) VALUES (
                p_rate_id, statement_timestamp(),
                timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                p_actor_id, 'service_rate.created', 'ServiceRate', p_rate_id,
                'Authorized effective-dated Service rate configuration',
                'service_rates.manage', p_property_id,
                jsonb_build_object(
                    'property_service_id', p_property_service_id,
                    'effective_date', p_effective_date,
                    'monthly_rate_usd_cents', p_monthly_rate_usd_cents
                ),
                p_idempotency_key, 'API', 'SUCCEEDED'
            );
            RETURN QUERY
            SELECT rate.id, service.property_id, service.id,
                   service.service_code, service.display_name,
                   rate.monthly_rate_usd_cents, rate.effective_date,
                   rate.source_memo, rate.occurred_at
            FROM app.service_rates AS rate
            JOIN app.property_services AS service ON service.id = rate.property_service_id
            WHERE rate.id = p_rate_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.execute_utility_rate(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_rate_id uuid,
            p_utility_type text,
            p_measurement_unit_code text,
            p_rate_usd_per_unit numeric,
            p_effective_date date,
            p_notice_at timestamptz,
            p_notice_evidence text,
            p_source_memo text,
            p_actor_id uuid
        )
        RETURNS TABLE(
            id uuid, property_id uuid, utility_type text,
            measurement_unit_code text, rate_usd_per_unit numeric,
            effective_date date, notice_at timestamptz,
            notice_evidence text, source_memo text, occurred_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE v_command app.configuration_commands%ROWTYPE;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'configuration-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/utility_rate.create/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.configuration_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'utility_rate.create'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Configuration idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY
                SELECT rate.id, rate.property_id, rate.utility_type,
                       rate.measurement_unit_code, rate.rate_usd_per_unit,
                       rate.effective_date, rate.notice_at, rate.notice_evidence,
                       rate.source_memo, rate.occurred_at
                FROM app.utility_rates AS rate WHERE rate.id = v_command.result_id;
                RETURN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM app.properties WHERE app.properties.id = p_property_id) THEN
                RAISE EXCEPTION 'Property was not found' USING ERRCODE = 'P0002';
            END IF;
            INSERT INTO app.utility_rates (
                id, property_id, utility_type, measurement_unit_code,
                rate_usd_per_unit, effective_date, notice_at,
                notice_evidence, source_memo, actor_id
            ) VALUES (
                p_rate_id, p_property_id, p_utility_type,
                btrim(p_measurement_unit_code), p_rate_usd_per_unit,
                p_effective_date, p_notice_at, btrim(p_notice_evidence),
                NULLIF(btrim(p_source_memo), ''), p_actor_id
            );
            INSERT INTO app.configuration_commands (
                actor_id, property_id, action, idempotency_key,
                request_digest, result_id
            ) VALUES (
                p_actor_id, p_property_id, 'utility_rate.create',
                p_idempotency_key, p_request_digest, p_rate_id
            );
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference,
                property_id, resulting_state, correlation_id, source, outcome
            ) VALUES (
                p_rate_id, statement_timestamp(),
                timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                p_actor_id, 'utility_rate.created', 'UtilityRate', p_rate_id,
                'Authorized effective-dated Utility rate configuration',
                'utility_rates.manage', p_property_id,
                jsonb_build_object(
                    'utility_type', p_utility_type,
                    'effective_date', p_effective_date,
                    'measurement_unit_code', btrim(p_measurement_unit_code)
                ),
                p_idempotency_key, 'API', 'SUCCEEDED'
            );
            RETURN QUERY
            SELECT rate.id, rate.property_id, rate.utility_type,
                   rate.measurement_unit_code, rate.rate_usd_per_unit,
                   rate.effective_date, rate.notice_at, rate.notice_evidence,
                   rate.source_memo, rate.occurred_at
            FROM app.utility_rates AS rate WHERE rate.id = p_rate_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.execute_exchange_rate(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_rate_id uuid,
            p_reference_rate_khr_per_usd numeric,
            p_system_rate_khr_per_usd bigint,
            p_rate_source text,
            p_source_reference text,
            p_applicable_at timestamptz,
            p_actor_id uuid,
            p_calculation_trace jsonb
        )
        RETURNS TABLE(
            id uuid, reference_rate_khr_per_usd numeric,
            system_rate_khr_per_usd bigint, rate_source text,
            source_reference text, applicable_at timestamptz,
            calculation_trace jsonb
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE v_command app.configuration_commands%ROWTYPE;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'configuration-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/exchange_rate.confirm/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.configuration_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'exchange_rate.confirm'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Configuration idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY
                SELECT rate.id, rate.reference_rate_khr_per_usd,
                       rate.system_rate_khr_per_usd, rate.rate_source,
                       rate.source_reference, rate.applicable_at,
                       rate.calculation_trace
                FROM app.exchange_rate_records AS rate
                WHERE rate.id = v_command.result_id;
                RETURN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM app.properties WHERE app.properties.id = p_property_id) THEN
                RAISE EXCEPTION 'Property was not found' USING ERRCODE = 'P0002';
            END IF;
            INSERT INTO app.exchange_rate_records (
                id, reference_rate_khr_per_usd, markup_basis_points,
                system_rate_khr_per_usd, rate_source, source_reference,
                applicable_at, entered_by, calculation_trace
            ) VALUES (
                p_rate_id, p_reference_rate_khr_per_usd, 50,
                p_system_rate_khr_per_usd, p_rate_source,
                NULLIF(btrim(p_source_reference), ''), p_applicable_at,
                CASE WHEN p_rate_source = 'ABA_EQUIVALENT_MANUAL' THEN p_actor_id END,
                p_calculation_trace
            );
            INSERT INTO app.configuration_commands (
                actor_id, property_id, action, idempotency_key,
                request_digest, result_id
            ) VALUES (
                p_actor_id, p_property_id, 'exchange_rate.confirm',
                p_idempotency_key, p_request_digest, p_rate_id
            );
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference,
                property_id, resulting_state, correlation_id, source, outcome
            ) VALUES (
                p_rate_id, statement_timestamp(),
                timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                p_actor_id, 'exchange_rate.confirmed', 'ExchangeRateRecord', p_rate_id,
                'Authorized payment confirmation exchange-rate evidence',
                'exchange_rates.manage', p_property_id,
                jsonb_build_object(
                    'rate_source', p_rate_source,
                    'applicable_at', p_applicable_at,
                    'system_rate_khr_per_usd', p_system_rate_khr_per_usd
                ),
                p_idempotency_key, 'API', 'SUCCEEDED'
            );
            RETURN QUERY
            SELECT rate.id, rate.reference_rate_khr_per_usd,
                   rate.system_rate_khr_per_usd, rate.rate_source,
                   rate.source_reference, rate.applicable_at,
                   rate.calculation_trace
            FROM app.exchange_rate_records AS rate WHERE rate.id = p_rate_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.replay_exchange_rate_command(
            p_property_id uuid,
            p_actor_id uuid,
            p_idempotency_key uuid,
            p_request_digest text
        )
        RETURNS TABLE(
            id uuid, reference_rate_khr_per_usd numeric,
            system_rate_khr_per_usd bigint, rate_source text,
            source_reference text, applicable_at timestamptz,
            calculation_trace jsonb
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE v_command app.configuration_commands%ROWTYPE;
        BEGIN
            SELECT command.* INTO v_command
            FROM app.configuration_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'exchange_rate.confirm'
              AND command.idempotency_key = p_idempotency_key;
            IF NOT FOUND THEN
                RETURN;
            END IF;
            IF v_command.request_digest <> p_request_digest THEN
                RAISE EXCEPTION 'Configuration idempotency key was reused'
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN QUERY
            SELECT rate.id, rate.reference_rate_khr_per_usd,
                   rate.system_rate_khr_per_usd, rate.rate_source,
                   rate.source_reference, rate.applicable_at,
                   rate.calculation_trace
            FROM app.exchange_rate_records AS rate
            WHERE rate.id = v_command.result_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.list_exchange_rates_for_property(
            p_property_id uuid,
            p_limit integer,
            p_cursor_at timestamptz,
            p_cursor_id uuid
        )
        RETURNS TABLE(
            id uuid, reference_rate_khr_per_usd numeric,
            system_rate_khr_per_usd bigint, rate_source text,
            source_reference text, applicable_at timestamptz,
            calculation_trace jsonb
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF p_limit < 1 OR p_limit > 101 THEN
                RAISE EXCEPTION 'Exchange-rate page limit is invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM app.properties AS property
                WHERE property.id = p_property_id
            ) THEN
                RAISE EXCEPTION 'Property was not found' USING ERRCODE = 'P0002';
            END IF;
            RETURN QUERY
            SELECT rate.id, rate.reference_rate_khr_per_usd,
                   rate.system_rate_khr_per_usd, rate.rate_source,
                   rate.source_reference, rate.applicable_at,
                   rate.calculation_trace
            FROM app.exchange_rate_records AS rate
            WHERE (
                    EXISTS (
                        SELECT 1
                        FROM app.configuration_commands AS command
                        WHERE command.result_id = rate.id
                          AND command.action = 'exchange_rate.confirm'
                          AND command.property_id = p_property_id
                    )
                    OR NOT EXISTS (
                        SELECT 1
                        FROM app.configuration_commands AS command
                        WHERE command.result_id = rate.id
                          AND command.action = 'exchange_rate.confirm'
                    )
                  )
              AND (
                  p_cursor_at IS NULL
                  OR (rate.applicable_at, rate.id) < (p_cursor_at, p_cursor_id)
              )
            ORDER BY rate.applicable_at DESC, rate.id DESC
            LIMIT p_limit;
        END;
        $$
        """
    )
    signatures = (
        "app.execute_service_rate(uuid,uuid,text,uuid,uuid,bigint,date,text,uuid)",
        "app.execute_utility_rate(uuid,uuid,text,uuid,text,text,numeric,date,timestamptz,text,text,uuid)",
        "app.execute_exchange_rate(uuid,uuid,text,uuid,numeric,bigint,text,text,timestamptz,uuid,jsonb)",
        "app.replay_exchange_rate_command(uuid,uuid,uuid,text)",
        "app.list_exchange_rates_for_property(uuid,integer,timestamptz,uuid)",
    )
    for signature in signatures:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback of command and audit history."""
    raise RuntimeError("V1-028 configuration API persistence is forward-only")
