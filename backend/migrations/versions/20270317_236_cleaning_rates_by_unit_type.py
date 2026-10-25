"""Move-out cleaning rates by Unit Type (V1-058 R7b-6d; DL-075; DESIGN.md "Rates and services").

Revision ID: 20270317_236
Revises: 20270316_235
Create Date: 2026-10-25

Settings keeps named move-out cleaning rates. One rate covers one or more Unit Types; each Unit
Type has at most one rate, and a Unit Type that has Units can never be left without one (moving
it to another rate is fine). The move-out cleaning charge still reads each Unit's own rate chain
(app.unit_cleaning_rates, migration 81): saving a rate here adds a new link to the chain of every
Unit of its types whose rate differs, and a new Unit, or a Unit whose type changes, gets its type's
rate the same way. Nothing already recorded changes: the chain is append-only and each charge
keeps the rate it used.

Decided by Claude under the owner's 2026-10-23 22:30 rule (no money rule changes; the amounts
are the Owner's to set): a cleaning rate is at least one cent, because a cleaning charge is made
on every move-out; a per-Unit rate set on the Unit page stays until its type's rate is saved again;
a Unit may still be given a Unit Type that has no rate yet (it keeps the amount it had, or none),
and Settings then names that type in its warning line and Unit setup shows "No cleaning rate".
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270317_236"
down_revision: str | None = "20270316_235"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIM = (
    r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
    r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"
)

SIGNATURES = (
    "app.save_cleaning_rate(uuid, uuid, uuid, text, text, bigint, text[], integer, text)",
    "app.remove_cleaning_rate(uuid, uuid, uuid, integer, text)",
    "app.cleaning_settings_read(uuid)",
)


def upgrade() -> None:
    op.execute(
        rf"""
        CREATE TABLE app.cleaning_rates (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            name_en text NOT NULL,
            name_km text,
            rate_usd_cents bigint NOT NULL CHECK (rate_usd_cents BETWEEN 1 AND 9000000000000000),
            removed_at timestamptz,
            removed_by uuid REFERENCES app.user_accounts(actor_id),
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT cleaning_rates_name_en_normalized CHECK (
                name_en = btrim(name_en, {TRIM}) AND length(name_en) BETWEEN 1 AND 100
            ),
            CONSTRAINT cleaning_rates_name_km_normalized CHECK (
                name_km IS NULL
                OR (name_km = btrim(name_km, {TRIM}) AND length(name_km) BETWEEN 1 AND 100)
            ),
            CONSTRAINT cleaning_rates_removed_pair CHECK (
                (removed_at IS NULL) = (removed_by IS NULL)
            )
        );
        COMMENT ON TABLE app.cleaning_rates IS
            'Named move-out cleaning rates of Settings (DL-075); each covers Unit Types';

        -- Which rate each Unit Type has: one row per Unit Type. Changes are audited.
        CREATE TABLE app.cleaning_rate_unit_types (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            unit_type text NOT NULL,
            cleaning_rate_id uuid NOT NULL REFERENCES app.cleaning_rates(id) ON DELETE RESTRICT,
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            PRIMARY KEY (property_id, unit_type)
        );
        CREATE INDEX cleaning_rate_unit_types_rate_idx
            ON app.cleaning_rate_unit_types(cleaning_rate_id);

        CREATE FUNCTION app.protect_cleaning_rate() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.property_id IS DISTINCT FROM OLD.property_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version IS DISTINCT FROM OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
                OR OLD.removed_at IS NOT NULL
            THEN
                RAISE EXCEPTION 'Cleaning rate identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.protect_cleaning_rate() FROM PUBLIC;
        CREATE TRIGGER cleaning_rates_protect BEFORE UPDATE OR DELETE ON app.cleaning_rates
            FOR EACH ROW EXECUTE FUNCTION app.protect_cleaning_rate();

        CREATE FUNCTION app.reject_cleaning_rates_truncate() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Cleaning rates are never emptied' USING ERRCODE = '55000';
        END $$;
        REVOKE ALL ON FUNCTION app.reject_cleaning_rates_truncate() FROM PUBLIC;
        CREATE TRIGGER cleaning_rates_reject_truncate BEFORE TRUNCATE ON app.cleaning_rates
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_cleaning_rates_truncate();
        CREATE TRIGGER cleaning_rate_unit_types_reject_truncate
            BEFORE TRUNCATE ON app.cleaning_rate_unit_types
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_cleaning_rates_truncate();

        -- Gives one Unit its type's rate: a new link in its own chain when the amount differs.
        CREATE FUNCTION app.sync_unit_cleaning_rate(
            p_unit_id uuid, p_actor_id uuid, p_timezone text, p_reason text, p_capability text
        ) RETURNS void
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_unit app.units%ROWTYPE;
            v_rate app.cleaning_rates%ROWTYPE;
            v_current app.unit_cleaning_rates%ROWTYPE;
            v_now timestamptz := clock_timestamp();
            v_audit uuid := gen_random_uuid();
            v_id uuid := gen_random_uuid();
        BEGIN
            SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = p_unit_id;
            IF NOT FOUND OR v_unit.unit_type IS NULL THEN RETURN; END IF;
            SELECT rate.* INTO v_rate
            FROM app.cleaning_rate_unit_types AS link
            JOIN app.cleaning_rates AS rate ON rate.id = link.cleaning_rate_id
            WHERE link.property_id = v_unit.property_id AND link.unit_type = v_unit.unit_type
              AND rate.removed_at IS NULL;
            IF NOT FOUND THEN RETURN; END IF;
            -- The same lock as a rate set on the Unit page (migration 81).
            PERFORM pg_advisory_xact_lock(
                hashtextextended('unit-cleaning-rate:' || p_unit_id::text, 0));
            SELECT rate.* INTO v_current FROM app.unit_cleaning_rates AS rate
            WHERE rate.unit_id = p_unit_id AND NOT EXISTS (
                SELECT 1 FROM app.unit_cleaning_rates AS later
                WHERE later.supersedes_rate_id = rate.id);
            IF FOUND AND v_current.rate_usd_cents = v_rate.rate_usd_cents THEN RETURN; END IF;
            INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                authorization_evidence, unit_id)
            VALUES (v_audit, v_now, timezone(p_timezone, v_now)::date, p_actor_id,
                'unit.cleaning_rate.set', 'unit_cleaning_rate', v_id, p_reason, p_capability,
                v_unit.property_id,
                coalesce(app.unit_cleaning_rate_snapshot(v_current.id), '{{}}'::jsonb),
                jsonb_build_object('rate_usd_cents', v_rate.rate_usd_cents,
                    'supersedes_rate_id', v_current.id, 'cleaning_rate_id', v_rate.id),
                v_id, 'API', 'SUCCEEDED', jsonb_build_object('capability', p_capability),
                p_unit_id);
            INSERT INTO app.unit_cleaning_rates(id, property_id, unit_id, rate_usd_cents,
                supersedes_rate_id, reason, recorded_by, recorded_at, audit_event_id)
            VALUES (v_id, v_unit.property_id, p_unit_id, v_rate.rate_usd_cents, v_current.id,
                p_reason, p_actor_id, v_now, v_audit);
        END $$;
        REVOKE ALL ON FUNCTION app.sync_unit_cleaning_rate(uuid, uuid, text, text, text)
            FROM PUBLIC;

        -- A new Unit, or a Unit whose type changes, gets its type's rate.
        CREATE FUNCTION app.unit_takes_type_cleaning_rate() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.unit_type IS NOT DISTINCT FROM OLD.unit_type THEN
                RETURN NEW;
            END IF;
            -- Waits for a cleaning rate being saved, so this Unit never keeps the old amount.
            PERFORM pg_advisory_xact_lock_shared(
                hashtextextended('cleaning-settings:' || NEW.property_id::text, 0));
            IF NOT EXISTS (
                SELECT 1 FROM app.cleaning_rate_unit_types AS link
                JOIN app.cleaning_rates AS rate ON rate.id = link.cleaning_rate_id
                WHERE link.property_id = NEW.property_id AND link.unit_type = NEW.unit_type
                  AND rate.removed_at IS NULL
            ) THEN
                RETURN NEW;
            END IF;
            SELECT property.timezone_name INTO v_timezone
            FROM app.properties AS property WHERE property.id = NEW.property_id;
            PERFORM app.sync_unit_cleaning_rate(NEW.id, NEW.updated_by, v_timezone,
                'Cleaning rate of the Unit Type in Settings', 'property.manage');
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.unit_takes_type_cleaning_rate() FROM PUBLIC;
        CREATE TRIGGER units_take_type_cleaning_rate
            AFTER INSERT OR UPDATE OF unit_type ON app.units
            FOR EACH ROW EXECUTE FUNCTION app.unit_takes_type_cleaning_rate();

        -- A Unit Type still in the Unit setup list (a removed one has no Units and is left out).
        CREATE FUNCTION app.cleaning_unit_type_listed(p_property_id uuid, p_code text)
        RETURNS boolean
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.unit_setup_items AS item
                WHERE item.property_id = p_property_id AND item.list_kind = 'UNIT_TYPE'
                  AND item.code = p_code AND item.removed_at IS NULL)
        $$;
        REVOKE ALL ON FUNCTION app.cleaning_unit_type_listed(uuid, text) FROM PUBLIC;

        CREATE FUNCTION app.cleaning_rate_json(p_rate app.cleaning_rates) RETURNS jsonb
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'cleaning_rate_id', p_rate.id,
                'name_en', p_rate.name_en,
                'name_km', p_rate.name_km,
                'rate_usd_cents', p_rate.rate_usd_cents,
                'removed', p_rate.removed_at IS NOT NULL,
                'version', p_rate.version,
                'unit_types', coalesce((
                    SELECT jsonb_agg(link.unit_type ORDER BY link.unit_type)
                    FROM app.cleaning_rate_unit_types AS link
                    WHERE link.cleaning_rate_id = p_rate.id
                      AND app.cleaning_unit_type_listed(link.property_id, link.unit_type)),
                    '[]'::jsonb)
            )
        $$;
        REVOKE ALL ON FUNCTION app.cleaning_rate_json(app.cleaning_rates) FROM PUBLIC;
        """
    )
    op.execute(
        rf"""
        CREATE FUNCTION app.save_cleaning_rate(
            p_property_id uuid, p_actor_id uuid, p_rate_id uuid, p_name_en text, p_name_km text,
            p_rate_usd_cents bigint, p_unit_types text[], p_expected_version integer,
            p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_name_en text := btrim(p_name_en, {TRIM});
            v_name_km text := nullif(btrim(p_name_km, {TRIM}), '');
            v_types text[];
            v_before app.cleaning_rates%ROWTYPE;
            v_rate app.cleaning_rates%ROWTYPE;
            v_before_json jsonb;
            v_needs text;
            v_unit uuid;
        BEGIN
            v_timezone := app.require_settings_actor(
                p_property_id, p_actor_id, p_authorization_reference);
            IF p_rate_id IS NULL OR p_rate_id = '00000000-0000-0000-0000-000000000000'
                OR v_name_en IS NULL OR length(v_name_en) NOT BETWEEN 1 AND 100
                OR (v_name_km IS NOT NULL AND length(v_name_km) > 100)
                OR p_rate_usd_cents IS NULL OR p_rate_usd_cents NOT BETWEEN 1 AND 9000000000000000
                OR p_unit_types IS NULL OR array_position(p_unit_types, NULL) IS NOT NULL
                OR cardinality(p_unit_types) > 200
            THEN
                RAISE EXCEPTION 'Cleaning rate input is invalid' USING ERRCODE = '22023';
            END IF;
            SELECT coalesce(array_agg(DISTINCT code ORDER BY code), ARRAY[]::text[])
            INTO v_types FROM unnest(p_unit_types) AS code;
            -- The Units of these types before the Settings lock: a Unit being changed holds its
            -- row and then waits for that lock, so taking the rows later could deadlock.
            PERFORM 1 FROM app.units AS unit
            WHERE unit.property_id = p_property_id AND unit.unit_type = ANY (v_types)
            ORDER BY unit.id FOR KEY SHARE;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('cleaning-settings:' || p_property_id::text, 0));
            SELECT rate.* INTO v_before FROM app.cleaning_rates AS rate
            WHERE rate.id = p_rate_id FOR UPDATE;
            IF p_expected_version IS NULL THEN
                IF FOUND THEN
                    -- The same form again after a lost answer answers the same rate.
                    IF v_before.property_id = p_property_id AND v_before.name_en = v_name_en
                        AND v_before.name_km IS NOT DISTINCT FROM v_name_km
                        AND v_before.rate_usd_cents = p_rate_usd_cents
                        AND v_before.created_by = p_actor_id AND v_before.version = 1
                        AND v_before.removed_at IS NULL
                        AND (SELECT coalesce(array_agg(link.unit_type ORDER BY link.unit_type),
                                             ARRAY[]::text[])
                             FROM app.cleaning_rate_unit_types AS link
                             WHERE link.cleaning_rate_id = p_rate_id) = v_types
                    THEN
                        RETURN app.cleaning_rate_json(v_before);
                    END IF;
                    RAISE EXCEPTION 'Cleaning rate identity was reused' USING ERRCODE = '23505';
                END IF;
                INSERT INTO app.cleaning_rates AS rate (id, property_id, name_en, name_km,
                    rate_usd_cents, created_by, updated_by)
                VALUES (p_rate_id, p_property_id, v_name_en, v_name_km, p_rate_usd_cents,
                    p_actor_id, p_actor_id)
                RETURNING rate.* INTO v_rate;
                v_before_json := NULL;
            ELSE
                IF NOT FOUND OR v_before.property_id <> p_property_id THEN
                    RAISE EXCEPTION 'Cleaning rate was not found' USING ERRCODE = 'P0002';
                END IF;
                -- A removed rate is gone for every form, whatever version it was opened at.
                IF v_before.removed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'The cleaning rate was removed' USING ERRCODE = 'P0002';
                END IF;
                IF v_before.version IS DISTINCT FROM p_expected_version THEN RETURN NULL; END IF;
                v_before_json := app.cleaning_rate_json(v_before);
                -- A Unit Type taken out must have no Units: they always need a rate.
                SELECT link.unit_type INTO v_needs
                FROM app.cleaning_rate_unit_types AS link
                WHERE link.cleaning_rate_id = p_rate_id
                  AND NOT (link.unit_type = ANY (v_types))
                  AND EXISTS (SELECT 1 FROM app.units AS unit
                              WHERE unit.property_id = p_property_id
                                AND unit.unit_type = link.unit_type)
                ORDER BY link.unit_type LIMIT 1;
                IF v_needs IS NOT NULL THEN
                    RAISE EXCEPTION 'The Unit Type % has Units and needs a cleaning rate', v_needs
                        USING ERRCODE = 'P5V03';
                END IF;
                DELETE FROM app.cleaning_rate_unit_types AS link
                WHERE link.cleaning_rate_id = p_rate_id
                  AND NOT (link.unit_type = ANY (v_types));
                UPDATE app.cleaning_rates AS rate
                SET name_en = v_name_en, name_km = v_name_km, rate_usd_cents = p_rate_usd_cents,
                    version = rate.version + 1,
                    updated_at = greatest(statement_timestamp(), rate.updated_at),
                    updated_by = p_actor_id
                WHERE rate.id = p_rate_id
                RETURNING rate.* INTO v_rate;
            END IF;
            -- Every Unit Type named is in the Unit setup list now (checked after a replay answered
            -- and after the version, so an old form hears that it is out of date).
            IF EXISTS (
                SELECT 1 FROM unnest(v_types) AS wanted(code)
                WHERE NOT EXISTS (
                    SELECT 1 FROM app.unit_setup_items AS item
                    WHERE item.property_id = p_property_id AND item.list_kind = 'UNIT_TYPE'
                      AND item.code = wanted.code AND item.removed_at IS NULL)
            ) THEN
                RAISE EXCEPTION 'A Unit Type is not in the list' USING ERRCODE = '22023';
            END IF;
            -- A rate that loses a Unit Type gets a new version, so its open form is out of date.
            UPDATE app.cleaning_rates AS rate
            SET version = rate.version + 1,
                updated_at = greatest(statement_timestamp(), rate.updated_at),
                updated_by = p_actor_id
            WHERE rate.id <> p_rate_id AND rate.id IN (
                SELECT link.cleaning_rate_id FROM app.cleaning_rate_unit_types AS link
                WHERE link.property_id = p_property_id AND link.unit_type = ANY (v_types));
            -- The Unit Types named move to this rate (from another one, if they had one).
            INSERT INTO app.cleaning_rate_unit_types AS link (property_id, unit_type,
                cleaning_rate_id, updated_by)
            SELECT p_property_id, code, p_rate_id, p_actor_id FROM unnest(v_types) AS code
            ON CONFLICT (property_id, unit_type) DO UPDATE
            SET cleaning_rate_id = EXCLUDED.cleaning_rate_id,
                updated_at = greatest(statement_timestamp(), link.updated_at),
                updated_by = EXCLUDED.updated_by
            WHERE link.cleaning_rate_id IS DISTINCT FROM EXCLUDED.cleaning_rate_id;
            -- Every Unit of these types gets this rate, in a fixed order.
            FOR v_unit IN
                SELECT unit.id FROM app.units AS unit
                WHERE unit.property_id = p_property_id AND unit.unit_type = ANY (v_types)
                ORDER BY unit.id
            LOOP
                PERFORM app.sync_unit_cleaning_rate(v_unit, p_actor_id, v_timezone,
                    'Cleaning rate ' || v_name_en || ' in Settings', 'settings.manage');
            END LOOP;
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                CASE WHEN v_before_json IS NULL THEN 'cleaning_rate.added'
                     ELSE 'cleaning_rate.changed' END,
                'cleaning_rate', p_rate_id, 'Move-out cleaning rate saved in Settings',
                v_before_json, app.cleaning_rate_json(v_rate));
            RETURN app.cleaning_rate_json(v_rate);
        END $$;

        CREATE FUNCTION app.remove_cleaning_rate(
            p_property_id uuid, p_actor_id uuid, p_rate_id uuid, p_expected_version integer,
            p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_before app.cleaning_rates%ROWTYPE;
            v_rate app.cleaning_rates%ROWTYPE;
            v_before_json jsonb;
            v_needs text;
        BEGIN
            v_timezone := app.require_settings_actor(
                p_property_id, p_actor_id, p_authorization_reference);
            PERFORM pg_advisory_xact_lock(
                hashtextextended('cleaning-settings:' || p_property_id::text, 0));
            SELECT rate.* INTO v_before FROM app.cleaning_rates AS rate
            WHERE rate.id = p_rate_id AND rate.property_id = p_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Cleaning rate was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_before.removed_at IS NOT NULL THEN
                RAISE EXCEPTION 'The cleaning rate is already removed' USING ERRCODE = 'P0002';
            END IF;
            IF v_before.version IS DISTINCT FROM p_expected_version THEN RETURN NULL; END IF;
            SELECT link.unit_type INTO v_needs
            FROM app.cleaning_rate_unit_types AS link
            WHERE link.cleaning_rate_id = p_rate_id
              AND EXISTS (SELECT 1 FROM app.units AS unit
                          WHERE unit.property_id = p_property_id
                            AND unit.unit_type = link.unit_type)
            ORDER BY link.unit_type LIMIT 1;
            IF v_needs IS NOT NULL THEN
                RAISE EXCEPTION 'The Unit Type % has Units and needs a cleaning rate', v_needs
                    USING ERRCODE = 'P5V03';
            END IF;
            v_before_json := app.cleaning_rate_json(v_before);
            DELETE FROM app.cleaning_rate_unit_types AS link
            WHERE link.cleaning_rate_id = p_rate_id;
            UPDATE app.cleaning_rates AS rate
            SET removed_at = statement_timestamp(), removed_by = p_actor_id,
                version = rate.version + 1,
                updated_at = greatest(statement_timestamp(), rate.updated_at),
                updated_by = p_actor_id
            WHERE rate.id = p_rate_id
            RETURNING rate.* INTO v_rate;
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                'cleaning_rate.removed', 'cleaning_rate', p_rate_id,
                'Move-out cleaning rate removed in Settings', v_before_json,
                app.cleaning_rate_json(v_rate));
            RETURN app.cleaning_rate_json(v_rate);
        END $$;

        -- The rates (not removed) and every Unit Type of the list with its Units and its rate.
        CREATE FUNCTION app.cleaning_settings_read(p_property_id uuid) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'cleaning_rates', coalesce((
                    SELECT jsonb_agg(app.cleaning_rate_json(rate) ORDER BY rate.created_at, rate.id)
                    FROM app.cleaning_rates AS rate
                    WHERE rate.property_id = p_property_id AND rate.removed_at IS NULL),
                    '[]'::jsonb),
                'unit_types', coalesce((
                    SELECT jsonb_agg(jsonb_build_object(
                        'code', item.code,
                        'name_en', item.name_en,
                        'name_km', item.name_km,
                        'units', (SELECT count(*) FROM app.units AS unit
                                  WHERE unit.property_id = p_property_id
                                    AND unit.unit_type = item.code),
                        'cleaning_rate_id', (
                            SELECT link.cleaning_rate_id FROM app.cleaning_rate_unit_types AS link
                            WHERE link.property_id = p_property_id AND link.unit_type = item.code))
                        ORDER BY item.sort_order, item.name_en, item.code)
                    FROM app.unit_setup_items AS item
                    WHERE item.property_id = p_property_id AND item.list_kind = 'UNIT_TYPE'
                      AND item.removed_at IS NULL), '[]'::jsonb)
            )
            WHERE EXISTS (SELECT 1 FROM app.properties WHERE id = p_property_id)
        $$;
        """
    )
    for signature in SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    op.execute(
        """
        REVOKE ALL ON app.cleaning_rates, app.cleaning_rate_unit_types
            FROM PUBLIC, prm_runtime, prm_bootstrap;
        """
    )


def downgrade() -> None:
    raise RuntimeError("V1-058 cleaning rates by Unit Type migration is forward-only")
