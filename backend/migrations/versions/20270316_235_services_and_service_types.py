# ruff: noqa: E501
"""Add and rename Services, and Service types (V1-058 R7b-6a; DL-075; DESIGN.md 0.20).

DL-075 (owner, 2026-10-17): the Owner or a user ticked for Settings access may add a Service, give
it a name (English and Khmer), a type and a monthly rate; Service types are "Only one per Lease"
or "One or more per Lease". DESIGN.md "Rates and services": a type is removed only while it has no
Services; changing a Service's type, or a type to "Only one", is refused while a Lease holds two
Services of that type. Technical points decided by Claude under the owner's 2026-10-23 22:30 rule.

- `app.service_types`: per Property, English and optional Khmer name, `one_per_lease`, removed
  (never deleted), version. Every change is in the audit history.
- `app.property_services` gains the Khmer name, the Service type and a version.
- `app.add_property_service` records a new Service with its first monthly rate (from the 1st of a
  month) and its open approval period from that day, so a Lease may hold it from then on. Its code
  is made from the English name. The client chooses the id: the same id with the same values
  answers the same Service again.
- `app.update_property_service` changes the names or the type (the rate keeps its own history).
- `app.add_service_type`, `app.update_service_type`, `app.remove_service_type`.
- A Lease may not hold two Services of an "Only one per Lease" type at the same time: checked when
  a Lease Service term is recorded, when a Service changes type and when a type becomes "Only one".
  Only Leases that are drafted or signed count; an ended Lease keeps its history.
- `app.service_settings_read(property, today)` gives the Services (rate today, next change, Leases
  using it now) and the types (Services count) for Settings and the New Lease form, including each
  Service's approval periods.

Every writer needs `settings.manage` as its authorization reference and an active human actor.
Additive or relaxing only: one new table, three new columns, new functions and triggers; the
append-only guard of `app.property_services` is relaxed to allow a names or type change.
"""

from alembic import op

revision = "20270316_235"
down_revision = "20270315_234"
branch_labels = None
depends_on = None

TRIM = (
    r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
    r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"
)

WRITERS = (
    "app.add_property_service(uuid, uuid, uuid, text, text, uuid, bigint, date, text)",
    "app.update_property_service(uuid, uuid, uuid, text, text, uuid, integer, text)",
    "app.add_service_type(uuid, uuid, uuid, text, text, boolean, text)",
    "app.update_service_type(uuid, uuid, uuid, text, text, boolean, integer, text)",
    "app.remove_service_type(uuid, uuid, uuid, integer, text)",
)
READ = "app.service_settings_read(uuid, date)"


def upgrade() -> None:
    op.execute(
        rf"""
        CREATE TABLE app.service_types (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            name_en text NOT NULL,
            name_km text,
            one_per_lease boolean NOT NULL,
            removed_at timestamptz,
            removed_by uuid REFERENCES app.user_accounts(actor_id),
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT service_types_name_en_normalized CHECK (
                name_en = btrim(name_en, {TRIM}) AND length(name_en) BETWEEN 1 AND 100
            ),
            CONSTRAINT service_types_name_km_normalized CHECK (
                name_km IS NULL
                OR (name_km = btrim(name_km, {TRIM}) AND length(name_km) BETWEEN 1 AND 100)
            ),
            CONSTRAINT service_types_removed_pair CHECK ((removed_at IS NULL) = (removed_by IS NULL))
        );
        CREATE INDEX service_types_property_idx ON app.service_types(property_id, created_at);
        REVOKE ALL ON TABLE app.service_types FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.service_types TO prm_runtime;

        ALTER TABLE app.property_services
            ADD COLUMN display_name_km text,
            ADD COLUMN service_type_id uuid REFERENCES app.service_types(id) ON DELETE RESTRICT,
            ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            ADD CONSTRAINT property_services_name_km_normalized CHECK (
                display_name_km IS NULL OR (
                    display_name_km = btrim(display_name_km, {TRIM})
                    AND length(display_name_km) BETWEEN 1 AND 100
                )
            );
        CREATE INDEX property_services_type_idx ON app.property_services(service_type_id);

        -- Relaxed from append-only (migration 17): a Service's names and type may change in
        -- Settings, one version at a time; its id, Property, code and provenance never change and
        -- it is never deleted. Issued Invoice lines keep the name they were billed with, and the
        -- audit history keeps every earlier name.
        CREATE FUNCTION app.guard_property_service_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.property_id IS DISTINCT FROM OLD.property_id
                OR NEW.service_code IS DISTINCT FROM OLD.service_code
                OR NEW.configured_at IS DISTINCT FROM OLD.configured_at
                OR NEW.configured_by IS DISTINCT FROM OLD.configured_by
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
            THEN
                RAISE EXCEPTION 'Effective-dated configuration history is append-only'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.guard_property_service_change() FROM PUBLIC;
        DROP TRIGGER property_services_reject_update_or_delete ON app.property_services;
        CREATE TRIGGER property_services_guard_change BEFORE UPDATE OR DELETE
            ON app.property_services
            FOR EACH ROW EXECUTE FUNCTION app.guard_property_service_change();

        CREATE FUNCTION app.protect_service_type() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.property_id IS DISTINCT FROM OLD.property_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
                OR (OLD.removed_at IS NOT NULL AND (
                    NEW.removed_at IS DISTINCT FROM OLD.removed_at
                    OR NEW.removed_by IS DISTINCT FROM OLD.removed_by
                ))
            THEN
                RAISE EXCEPTION 'Service type identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.protect_service_type() FROM PUBLIC;
        CREATE TRIGGER service_types_protect BEFORE UPDATE OR DELETE ON app.service_types
            FOR EACH ROW EXECUTE FUNCTION app.protect_service_type();
        CREATE FUNCTION app.reject_service_types_truncate() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Service types are never emptied' USING ERRCODE = '55000';
        END $$;
        REVOKE ALL ON FUNCTION app.reject_service_types_truncate() FROM PUBLIC;
        CREATE TRIGGER service_types_reject_truncate BEFORE TRUNCATE ON app.service_types
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_service_types_truncate();
        """
    )
    op.execute(
        """
        -- Two Services of one type held by one drafted or signed Lease at the same time. With
        -- p_service and p_type, that Service counts as being of that type (a type change). With
        -- p_lease only that Lease is looked at (a new term).
        CREATE FUNCTION app.lease_holds_two_of_type(
            p_type_id uuid, p_service uuid DEFAULT NULL, p_service_type uuid DEFAULT NULL,
            p_lease uuid DEFAULT NULL
        ) RETURNS boolean
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            WITH typed AS (
                SELECT term.lease_id, term.property_service_id, term.applicable_from,
                       coalesce(term.applicable_through, lease.end_date, 'infinity'::date) AS through
                FROM app.lease_service_terms AS term
                JOIN app.leases AS lease ON lease.id = term.lease_id
                JOIN app.property_services AS service ON service.id = term.property_service_id
                WHERE lease.status IN ('DRAFTED', 'SIGNED')
                  AND (p_lease IS NULL OR term.lease_id = p_lease)
                  AND CASE WHEN service.id = p_service THEN p_service_type
                           ELSE service.service_type_id END = p_type_id
            )
            SELECT EXISTS (
                SELECT 1 FROM typed AS one JOIN typed AS two
                  ON two.lease_id = one.lease_id
                 AND two.property_service_id <> one.property_service_id
                 AND two.applicable_from <= one.through
                 AND one.applicable_from <= two.through
            )
        $$;
        REVOKE ALL ON FUNCTION app.lease_holds_two_of_type(uuid, uuid, uuid, uuid) FROM PUBLIC;

        CREATE FUNCTION app.check_lease_service_one_per_type() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_type app.service_types%ROWTYPE;
        BEGIN
            SELECT type.* INTO v_type
            FROM app.property_services AS service
            JOIN app.service_types AS type ON type.id = service.service_type_id
            WHERE service.id = NEW.property_service_id
            FOR SHARE OF type;
            IF FOUND AND v_type.one_per_lease AND app.lease_holds_two_of_type(
                v_type.id, p_lease => NEW.lease_id
            ) THEN
                RAISE EXCEPTION 'A Lease holds only one Service of the type %', v_type.name_en
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.check_lease_service_one_per_type() FROM PUBLIC;
        CREATE TRIGGER lease_service_terms_one_per_type
            AFTER INSERT ON app.lease_service_terms
            FOR EACH ROW EXECUTE FUNCTION app.check_lease_service_one_per_type();

        CREATE FUNCTION app.service_type_json(p_type app.service_types) RETURNS jsonb
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'service_type_id', p_type.id,
                'property_id', p_type.property_id,
                'name_en', p_type.name_en,
                'name_km', p_type.name_km,
                'one_per_lease', p_type.one_per_lease,
                'removed', p_type.removed_at IS NOT NULL,
                'version', p_type.version,
                'services', (SELECT count(*) FROM app.property_services AS service
                             WHERE service.service_type_id = p_type.id)
            )
        $$;
        REVOKE ALL ON FUNCTION app.service_type_json(app.service_types) FROM PUBLIC;

        CREATE FUNCTION app.property_service_json(p_service app.property_services) RETURNS jsonb
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'service_id', p_service.id,
                'property_id', p_service.property_id,
                'service_code', p_service.service_code,
                'name_en', p_service.display_name,
                'name_km', p_service.display_name_km,
                'service_type_id', p_service.service_type_id,
                'version', p_service.version
            )
        $$;
        REVOKE ALL ON FUNCTION app.property_service_json(app.property_services) FROM PUBLIC;

        CREATE FUNCTION app.require_settings_actor(
            p_property_id uuid, p_actor_id uuid, p_authorization_reference text
        ) RETURNS text
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            v_timezone := app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS DISTINCT FROM 'settings.manage' THEN
                RAISE EXCEPTION 'A Settings change needs settings.manage' USING ERRCODE = '42501';
            END IF;
            RETURN v_timezone;
        END $$;
        REVOKE ALL ON FUNCTION app.require_settings_actor(uuid, uuid, text) FROM PUBLIC;

        CREATE FUNCTION app.audit_service_setting(
            p_property_id uuid, p_actor_id uuid, p_timezone text, p_action text,
            p_entity_type text, p_entity_id uuid, p_reason text, p_before jsonb, p_after jsonb
        ) RETURNS void
        LANGUAGE sql SET search_path = pg_catalog AS $$
            INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                authorization_evidence)
            VALUES (gen_random_uuid(), statement_timestamp(),
                timezone(p_timezone, statement_timestamp())::date, p_actor_id, p_action,
                p_entity_type, p_entity_id, p_reason, 'settings.manage', p_property_id,
                p_before, p_after, gen_random_uuid(), 'API', 'SUCCEEDED',
                jsonb_build_object('capability', 'settings.manage'))
        $$;
        REVOKE ALL ON FUNCTION
            app.audit_service_setting(uuid, uuid, text, text, text, uuid, text, jsonb, jsonb)
            FROM PUBLIC;

        -- A type the Property may pick now (not removed); locked so a removal waits.
        CREATE FUNCTION app.assert_service_type(p_property_id uuid, p_type_id uuid)
        RETURNS app.service_types
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_type app.service_types%ROWTYPE;
        BEGIN
            SELECT type.* INTO v_type FROM app.service_types AS type
            WHERE type.id = p_type_id FOR SHARE;
            IF NOT FOUND OR v_type.property_id <> p_property_id OR v_type.removed_at IS NOT NULL
            THEN
                RAISE EXCEPTION 'Service type is not in the list' USING ERRCODE = '22023';
            END IF;
            RETURN v_type;
        END $$;
        REVOKE ALL ON FUNCTION app.assert_service_type(uuid, uuid) FROM PUBLIC;
        """
    )
    op.execute(
        rf"""
        CREATE FUNCTION app.add_service_type(
            p_property_id uuid, p_actor_id uuid, p_type_id uuid, p_name_en text, p_name_km text,
            p_one_per_lease boolean, p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_type app.service_types%ROWTYPE;
            v_name_en text := btrim(p_name_en, {TRIM});
            v_name_km text := nullif(btrim(p_name_km, {TRIM}), '');
        BEGIN
            v_timezone := app.require_settings_actor(p_property_id, p_actor_id, p_authorization_reference);
            IF p_type_id IS NULL OR p_one_per_lease IS NULL THEN
                RAISE EXCEPTION 'Service type input is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('service-settings:' || p_property_id::text, 0));
            SELECT type.* INTO v_type FROM app.service_types AS type WHERE type.id = p_type_id;
            IF FOUND THEN
                IF v_type.property_id = p_property_id AND v_type.name_en = v_name_en
                    AND v_type.name_km IS NOT DISTINCT FROM v_name_km
                    AND v_type.one_per_lease = p_one_per_lease AND v_type.created_by = p_actor_id
                THEN RETURN app.service_type_json(v_type); END IF;
                RAISE EXCEPTION 'Service type identity was reused' USING ERRCODE = '23505';
            END IF;
            INSERT INTO app.service_types AS type (
                id, property_id, name_en, name_km, one_per_lease, created_by, updated_by
            ) VALUES (
                p_type_id, p_property_id, v_name_en, v_name_km, p_one_per_lease,
                p_actor_id, p_actor_id
            ) RETURNING type.* INTO v_type;
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                'service_type.added', 'service_type', v_type.id,
                'Service type added in Settings', NULL, app.service_type_json(v_type));
            RETURN app.service_type_json(v_type);
        END $$;

        -- Answers NULL when the version is not the one shown (the caller reads it again).
        CREATE FUNCTION app.update_service_type(
            p_property_id uuid, p_actor_id uuid, p_type_id uuid, p_name_en text, p_name_km text,
            p_one_per_lease boolean, p_expected_version integer, p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_before app.service_types%ROWTYPE;
            v_type app.service_types%ROWTYPE;
        BEGIN
            v_timezone := app.require_settings_actor(p_property_id, p_actor_id, p_authorization_reference);
            IF p_one_per_lease IS NULL
                OR coalesce(length(btrim(p_name_en, {TRIM})), 0) NOT BETWEEN 1 AND 100
            THEN
                RAISE EXCEPTION 'Service type input is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('service-settings:' || p_property_id::text, 0));
            SELECT type.* INTO v_before FROM app.service_types AS type
            WHERE type.id = p_type_id AND type.property_id = p_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Service type was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_before.version IS DISTINCT FROM p_expected_version THEN RETURN NULL; END IF;
            IF v_before.removed_at IS NOT NULL THEN
                RAISE EXCEPTION 'A removed Service type cannot be changed' USING ERRCODE = '22023';
            END IF;
            IF p_one_per_lease AND NOT v_before.one_per_lease
                AND app.lease_holds_two_of_type(p_type_id)
            THEN
                RAISE EXCEPTION 'A Lease holds two Services of this type' USING ERRCODE = 'P5V01';
            END IF;
            UPDATE app.service_types AS type
            SET name_en = btrim(p_name_en, {TRIM}),
                name_km = nullif(btrim(p_name_km, {TRIM}), ''),
                one_per_lease = p_one_per_lease,
                version = type.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE type.id = p_type_id
            RETURNING type.* INTO v_type;
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                'service_type.updated', 'service_type', v_type.id,
                'Service type changed in Settings', app.service_type_json(v_before),
                app.service_type_json(v_type));
            RETURN app.service_type_json(v_type);
        END $$;

        CREATE FUNCTION app.remove_service_type(
            p_property_id uuid, p_actor_id uuid, p_type_id uuid, p_expected_version integer,
            p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_before app.service_types%ROWTYPE;
            v_type app.service_types%ROWTYPE;
        BEGIN
            v_timezone := app.require_settings_actor(p_property_id, p_actor_id, p_authorization_reference);
            PERFORM pg_advisory_xact_lock(hashtextextended('service-settings:' || p_property_id::text, 0));
            SELECT type.* INTO v_before FROM app.service_types AS type
            WHERE type.id = p_type_id AND type.property_id = p_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Service type was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_before.version IS DISTINCT FROM p_expected_version THEN RETURN NULL; END IF;
            IF v_before.removed_at IS NOT NULL THEN
                RAISE EXCEPTION 'The Service type is already removed' USING ERRCODE = '22023';
            END IF;
            IF EXISTS (SELECT 1 FROM app.property_services AS service
                       WHERE service.service_type_id = p_type_id) THEN
                RAISE EXCEPTION 'A Service type with Services cannot be removed'
                    USING ERRCODE = 'P5V02';
            END IF;
            UPDATE app.service_types AS type
            SET removed_at = statement_timestamp(), removed_by = p_actor_id,
                version = type.version + 1, updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE type.id = p_type_id
            RETURNING type.* INTO v_type;
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                'service_type.removed', 'service_type', v_type.id,
                'Service type removed in Settings', app.service_type_json(v_before),
                app.service_type_json(v_type));
            RETURN app.service_type_json(v_type);
        END $$;
        """
    )
    op.execute(
        rf"""
        -- Billing (migration 30) knows only the code TRASH_COLLECTION. The first Service named
        -- "Trash Collection" in a Property gets it; every other Service gets a code from its id
        -- that no billing rule reads.
        CREATE FUNCTION app.next_service_code(
            p_property_id uuid, p_service_id uuid, p_name_en text
        ) RETURNS text
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT CASE
                WHEN lower(regexp_replace(btrim(p_name_en), '\s+', ' ', 'g')) = 'trash collection'
                    AND NOT EXISTS (SELECT 1 FROM app.property_services AS service
                                    WHERE service.property_id = p_property_id
                                      AND service.service_code = 'TRASH_COLLECTION')
                THEN 'TRASH_COLLECTION'
                ELSE 'SVC_' || upper(replace(p_service_id::text, '-', ''))
            END
        $$;
        REVOKE ALL ON FUNCTION app.next_service_code(uuid, uuid, text) FROM PUBLIC;

        CREATE FUNCTION app.add_property_service(
            p_property_id uuid, p_actor_id uuid, p_service_id uuid, p_name_en text,
            p_name_km text, p_type_id uuid, p_monthly_rate_usd_cents bigint, p_starts_on date,
            p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_service app.property_services%ROWTYPE;
            v_name_en text := btrim(p_name_en, {TRIM});
            v_name_km text := nullif(btrim(p_name_km, {TRIM}), '');
            v_rate app.service_rates%ROWTYPE;
            v_result jsonb;
        BEGIN
            v_timezone := app.require_settings_actor(p_property_id, p_actor_id, p_authorization_reference);
            IF p_service_id IS NULL OR p_service_id = '00000000-0000-0000-0000-000000000000'
                OR v_name_en IS NULL OR length(v_name_en) NOT BETWEEN 1 AND 100
                OR p_monthly_rate_usd_cents IS NULL
                OR p_monthly_rate_usd_cents NOT BETWEEN 1 AND 9000000000000000
                OR p_starts_on IS NULL OR extract(day FROM p_starts_on) <> 1
            THEN
                RAISE EXCEPTION 'Service input is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('service-settings:' || p_property_id::text, 0));
            SELECT service.* INTO v_service FROM app.property_services AS service
            WHERE service.id = p_service_id;
            IF FOUND THEN
                SELECT rate.* INTO v_rate FROM app.service_rates AS rate
                WHERE rate.property_service_id = p_service_id
                ORDER BY rate.effective_date, rate.id LIMIT 1;
                IF v_service.property_id = p_property_id AND v_service.display_name = v_name_en
                    AND v_service.display_name_km IS NOT DISTINCT FROM v_name_km
                    AND v_service.service_type_id IS NOT DISTINCT FROM p_type_id
                    AND v_service.created_by = p_actor_id
                    AND v_rate.monthly_rate_usd_cents = p_monthly_rate_usd_cents
                    AND v_rate.effective_date = p_starts_on
                THEN RETURN app.property_service_json(v_service); END IF;
                RAISE EXCEPTION 'Service identity was reused' USING ERRCODE = '23505';
            END IF;
            IF p_type_id IS NOT NULL THEN
                PERFORM app.assert_service_type(p_property_id, p_type_id);
            END IF;
            INSERT INTO app.property_services AS service (
                id, property_id, service_code, display_name, display_name_km, service_type_id,
                configured_by, created_by, updated_by
            ) VALUES (
                p_service_id, p_property_id, app.next_service_code(p_property_id, p_service_id, v_name_en),
                v_name_en, v_name_km, p_type_id, p_actor_id, p_actor_id, p_actor_id
            ) RETURNING service.* INTO v_service;
            INSERT INTO app.service_rates (
                id, property_service_id, monthly_rate_usd_cents, effective_date, source_memo,
                actor_id
            ) VALUES (
                gen_random_uuid(), p_service_id, p_monthly_rate_usd_cents, p_starts_on,
                'First rate, Service added in Settings', p_actor_id
            );
            INSERT INTO app.property_service_approval_periods (
                id, property_service_id, effective_from, effective_through, approval_reference,
                approved_at, approved_by, reason
            ) VALUES (
                gen_random_uuid(), p_service_id, p_starts_on, NULL, 'settings.manage',
                statement_timestamp(), p_actor_id, 'Service added in Settings'
            );
            v_result := app.property_service_json(v_service);
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                'property_service.added', 'property_service', p_service_id,
                'Service added in Settings', NULL,
                v_result || jsonb_build_object(
                    'monthly_rate_usd_cents', p_monthly_rate_usd_cents, 'starts_on', p_starts_on
                ));
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.update_property_service(
            p_property_id uuid, p_actor_id uuid, p_service_id uuid, p_name_en text,
            p_name_km text, p_type_id uuid, p_expected_version integer,
            p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_before app.property_services%ROWTYPE;
            v_service app.property_services%ROWTYPE;
            v_type app.service_types%ROWTYPE;
        BEGIN
            v_timezone := app.require_settings_actor(p_property_id, p_actor_id, p_authorization_reference);
            IF coalesce(length(btrim(p_name_en, {TRIM})), 0) NOT BETWEEN 1 AND 100 THEN
                RAISE EXCEPTION 'Service input is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('service-settings:' || p_property_id::text, 0));
            -- Every new Lease Service term takes this lock first (migration 30) and holds it to
            -- commit, so a term added at the same time either is committed and seen by the check
            -- below or waits for this change and is checked against it. Taken before any row
            -- lock, so the two never wait on each other in a circle.
            PERFORM pg_advisory_xact_lock(
                hashtextextended('invoice-property-service:' || p_property_id::text, 0)
            );
            SELECT service.* INTO v_before FROM app.property_services AS service
            WHERE service.id = p_service_id AND service.property_id = p_property_id
            FOR NO KEY UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Service was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_before.version IS DISTINCT FROM p_expected_version THEN RETURN NULL; END IF;
            IF p_type_id IS NOT NULL AND p_type_id IS DISTINCT FROM v_before.service_type_id THEN
                v_type := app.assert_service_type(p_property_id, p_type_id);
                IF v_type.one_per_lease
                    AND app.lease_holds_two_of_type(p_type_id, p_service_id, p_type_id)
                THEN
                    RAISE EXCEPTION 'A Lease holds two Services of this type'
                        USING ERRCODE = 'P5V01';
                END IF;
            END IF;
            UPDATE app.property_services AS service
            SET display_name = btrim(p_name_en, {TRIM}),
                display_name_km = nullif(btrim(p_name_km, {TRIM}), ''),
                service_type_id = p_type_id,
                version = service.version + 1,
                updated_at = greatest(statement_timestamp(), service.updated_at),
                updated_by = p_actor_id
            WHERE service.id = p_service_id
            RETURNING service.* INTO v_service;
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                'property_service.updated', 'property_service', p_service_id,
                'Service changed in Settings', app.property_service_json(v_before),
                app.property_service_json(v_service));
            RETURN app.property_service_json(v_service);
        END $$;
        """
    )
    op.execute(
        """
        -- Settings and the New Lease form: each Service with its rate today, its next change,
        -- its approval periods and the drafted or signed Leases holding it today or later; each
        -- type with its Services count.
        CREATE FUNCTION app.service_settings_read(p_property_id uuid, p_today date)
        RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'services', coalesce((
                    SELECT jsonb_agg(app.property_service_json(service) || jsonb_build_object(
                        'rate_today_usd_cents', (
                            SELECT rate.monthly_rate_usd_cents FROM app.service_rates AS rate
                            WHERE rate.property_service_id = service.id
                              AND rate.effective_date <= p_today
                            ORDER BY rate.effective_date DESC LIMIT 1),
                        'next_rate', (
                            SELECT jsonb_build_object(
                                'monthly_rate_usd_cents', rate.monthly_rate_usd_cents,
                                'effective_date', rate.effective_date)
                            FROM app.service_rates AS rate
                            WHERE rate.property_service_id = service.id
                              AND rate.effective_date > p_today
                            ORDER BY rate.effective_date LIMIT 1),
                        'approval_periods', coalesce((
                            SELECT jsonb_agg(jsonb_build_object(
                                'approval_period_id', approval.id,
                                'effective_from', approval.effective_from,
                                'effective_through', approval.effective_through)
                                ORDER BY approval.effective_from)
                            FROM app.property_service_approval_periods AS approval
                            WHERE approval.property_service_id = service.id), '[]'::jsonb),
                        'leases_using', (
                            SELECT count(DISTINCT term.lease_id)
                            FROM app.lease_service_terms AS term
                            JOIN app.leases AS lease ON lease.id = term.lease_id
                            WHERE term.property_service_id = service.id
                              AND lease.status IN ('DRAFTED', 'SIGNED')
                              AND coalesce(term.applicable_through, lease.end_date,
                                           'infinity'::date) >= p_today)
                    ) ORDER BY service.display_name, service.id)
                    FROM app.property_services AS service
                    WHERE service.property_id = p_property_id), '[]'::jsonb),
                'service_types', coalesce((
                    SELECT jsonb_agg(app.service_type_json(type) ORDER BY type.created_at, type.id)
                    FROM app.service_types AS type
                    WHERE type.property_id = p_property_id), '[]'::jsonb)
            )
            WHERE EXISTS (SELECT 1 FROM app.properties WHERE id = p_property_id)
        $$;
        """
    )
    for signature in (*WRITERS, READ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Services and Service types migration is forward-only")
