# ruff: noqa: E501
"""V1.1 part 1 (owner 2026-10-29, DL-115 (I)): Regular services and the Services Invoice.

Revision ID: 20270407_257
Revises: 20270406_256
Create Date: 2026-10-29

Settings keeps a list of Regular services, each with a name and a set price. Only a user with
Settings access changes a name or a price, in Settings. Create Invoice has a Services kind: staff
pick a Regular service and How many, and the price comes from the list (it cannot be typed).

- app.regular_services: the list. A change gives the row a new version and is audited with the
  values before and after; a removed service stays (removed) for the Invoices that name it. As
  in the agreed mock-up (round 13), a service used on an Invoice this year (the Property's
  calendar year) cannot be removed until next year.
- app.create_services_invoice_draft makes the Draft as app.create_items_invoice_draft (DL-103):
  each item is its own approved Miscellaneous charge of How many times the price saved now, so a
  later price change never changes an Invoice already made. app.regular_service_charges links each
  charge to its Regular service (append-only).
- Reports (owner 2026-10-29 19:20, decision card): a Services Invoice line counts in the
  "Rent and Services" bar. app.report_income_facts names such a line REGULAR_SERVICE_CHARGES
  (the Invoice line itself stays MISCELLANEOUS_CHARGES), and the server puts that kind in the
  same bar as Rent and Monthly Services.
- Edit items cannot change a Draft made from Regular services (that would let a price be typed);
  staff remove the Draft and make a new one.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule (no money rule changes).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270407_257"
down_revision: str | None = "20270406_256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIM = (
    r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
    r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"
)

SETTINGS_SIGNATURES = (
    "app.save_regular_service(uuid, uuid, uuid, text, text, bigint, integer, text)",
    "app.remove_regular_service(uuid, uuid, uuid, integer, text)",
    "app.regular_services_read(uuid)",
)
CREATE = "app.create_services_invoice_draft(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,jsonb)"
INCOME_FACTS = "app.report_income_facts(uuid,uuid,uuid[])"
INCOME_BEFORE = "            SELECT line.id, line.invoice_id, line.category, line.amount_usd_cents, invoice.unit_id,\n"
INCOME_AFTER = (
    "            SELECT line.id, line.invoice_id,\n"
    "                   -- V1.1 (owner 2026-10-29): a Regular service counts with Rent and Services.\n"
    "                   CASE WHEN EXISTS(SELECT 1 FROM app.regular_service_charges link\n"
    "                       WHERE link.charge_id=line.authorized_obligation_id)\n"
    "                       THEN 'REGULAR_SERVICE_CHARGES' ELSE line.category END AS category,\n"
    "                   line.amount_usd_cents, invoice.unit_id,\n"
)
REPLACE = "app.replace_invoice_draft_items(uuid,uuid,uuid,uuid,text,integer,uuid,uuid,text,text,text,jsonb,uuid)"

TYPED_ONLY_BEFORE = (
    "                    WHERE line.invoice_id=p_invoice_id AND charge.quantity IS NULL)\n"
)
TYPED_ONLY_AFTER = (
    "                    WHERE line.invoice_id=p_invoice_id AND charge.quantity IS NULL)\n"
    "                -- V1.1 (DL-115 (I)): a Regular service price is never typed.\n"
    "                OR EXISTS (SELECT 1 FROM app.invoice_lines AS line\n"
    "                    JOIN app.regular_service_charges AS link\n"
    "                      ON link.charge_id=line.authorized_obligation_id\n"
    "                    WHERE line.invoice_id=p_invoice_id)\n"
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"{signature} does not have the expected text")
        definition = definition.replace(before, after)
    op.execute(text(definition))


def upgrade() -> None:
    op.execute(
        rf"""
        CREATE TABLE app.regular_services (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            name_en text NOT NULL,
            name_km text,
            price_usd_cents bigint NOT NULL CHECK (price_usd_cents BETWEEN 1 AND 999999999),
            removed_at timestamptz,
            removed_by uuid REFERENCES app.user_accounts(actor_id),
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT regular_services_name_en_normalized CHECK (
                name_en = btrim(name_en, {TRIM}) AND length(name_en) BETWEEN 1 AND 100
            ),
            CONSTRAINT regular_services_name_km_normalized CHECK (
                name_km IS NULL
                OR (name_km = btrim(name_km, {TRIM}) AND length(name_km) BETWEEN 1 AND 100)
            ),
            CONSTRAINT regular_services_removed_pair CHECK (
                (removed_at IS NULL) = (removed_by IS NULL)
            )
        );
        COMMENT ON TABLE app.regular_services IS
            'V1.1 Regular services of Settings with their set price (DL-115 (I))';
        CREATE UNIQUE INDEX regular_services_name_unique
            ON app.regular_services(property_id, lower(name_en)) WHERE removed_at IS NULL;

        CREATE FUNCTION app.protect_regular_service() RETURNS trigger
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
                RAISE EXCEPTION 'Regular service identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.protect_regular_service() FROM PUBLIC;
        CREATE TRIGGER regular_services_protect BEFORE UPDATE OR DELETE ON app.regular_services
            FOR EACH ROW EXECUTE FUNCTION app.protect_regular_service();

        -- Which Regular service each Services Invoice charge came from. Never changed.
        CREATE TABLE app.regular_service_charges (
            charge_id uuid PRIMARY KEY
                REFERENCES app.authorized_nonrecurring_obligations(id) ON DELETE RESTRICT,
            regular_service_id uuid NOT NULL
                REFERENCES app.regular_services(id) ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT statement_timestamp()
        );
        CREATE INDEX regular_service_charges_service_idx
            ON app.regular_service_charges(regular_service_id);

        CREATE FUNCTION app.reject_regular_service_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Regular services are never emptied and their charges never change'
                USING ERRCODE = '55000';
        END $$;
        REVOKE ALL ON FUNCTION app.reject_regular_service_change() FROM PUBLIC;
        CREATE TRIGGER regular_services_reject_truncate BEFORE TRUNCATE ON app.regular_services
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_regular_service_change();
        CREATE TRIGGER regular_service_charges_append_only
            BEFORE UPDATE OR DELETE ON app.regular_service_charges
            FOR EACH ROW EXECUTE FUNCTION app.reject_regular_service_change();
        CREATE TRIGGER regular_service_charges_reject_truncate
            BEFORE TRUNCATE ON app.regular_service_charges
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_regular_service_change();

        -- How many Invoice items named the service in the Property's calendar year now.
        CREATE FUNCTION app.regular_service_used_this_year(p_service app.regular_services)
        RETURNS bigint
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT count(*) FROM app.regular_service_charges AS link
            JOIN app.authorized_nonrecurring_obligations AS charge ON charge.id = link.charge_id
            JOIN app.properties AS property ON property.id = p_service.property_id
            WHERE link.regular_service_id = p_service.id
              AND extract(year FROM timezone(property.timezone_name, charge.authorized_at))
                  = extract(year FROM timezone(property.timezone_name, clock_timestamp()))
        $$;
        REVOKE ALL ON FUNCTION app.regular_service_used_this_year(app.regular_services)
            FROM PUBLIC;

        CREATE FUNCTION app.regular_service_json(p_service app.regular_services) RETURNS jsonb
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'regular_service_id', p_service.id,
                'name_en', p_service.name_en,
                'name_km', p_service.name_km,
                'price_usd_cents', p_service.price_usd_cents,
                'removed', p_service.removed_at IS NOT NULL,
                'version', p_service.version,
                'used_this_year', app.regular_service_used_this_year(p_service)
            )
        $$;
        REVOKE ALL ON FUNCTION app.regular_service_json(app.regular_services) FROM PUBLIC;

        CREATE FUNCTION app.save_regular_service(
            p_property_id uuid, p_actor_id uuid, p_service_id uuid, p_name_en text,
            p_name_km text, p_price_usd_cents bigint, p_expected_version integer,
            p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_name_en text := btrim(p_name_en, {TRIM});
            v_name_km text := nullif(btrim(p_name_km, {TRIM}), '');
            v_before app.regular_services%ROWTYPE;
            v_service app.regular_services%ROWTYPE;
            v_before_json jsonb;
        BEGIN
            v_timezone := app.require_settings_actor(
                p_property_id, p_actor_id, p_authorization_reference);
            IF p_service_id IS NULL OR p_service_id = '00000000-0000-0000-0000-000000000000'
                OR v_name_en IS NULL OR length(v_name_en) NOT BETWEEN 1 AND 100
                OR (v_name_km IS NOT NULL AND length(v_name_km) > 100)
                OR p_price_usd_cents IS NULL OR p_price_usd_cents NOT BETWEEN 1 AND 999999999
            THEN
                RAISE EXCEPTION 'Regular service input is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('regular-services:' || p_property_id::text, 0));
            SELECT service.* INTO v_before FROM app.regular_services AS service
            WHERE service.id = p_service_id FOR UPDATE;
            IF p_expected_version IS NULL THEN
                IF FOUND THEN
                    -- The same form again after a lost answer answers the same service.
                    IF v_before.property_id = p_property_id AND v_before.name_en = v_name_en
                        AND v_before.name_km IS NOT DISTINCT FROM v_name_km
                        AND v_before.price_usd_cents = p_price_usd_cents
                        AND v_before.created_by = p_actor_id AND v_before.version = 1
                        AND v_before.removed_at IS NULL
                    THEN
                        RETURN app.regular_service_json(v_before);
                    END IF;
                    RAISE EXCEPTION 'Regular service identity was reused' USING ERRCODE = '23505';
                END IF;
                IF EXISTS (SELECT 1 FROM app.regular_services AS other
                           WHERE other.property_id = p_property_id AND other.removed_at IS NULL
                             AND lower(other.name_en) = lower(v_name_en)) THEN
                    RAISE EXCEPTION 'A Regular service has this name' USING ERRCODE = 'P5V04';
                END IF;
                INSERT INTO app.regular_services AS service (id, property_id, name_en, name_km,
                    price_usd_cents, created_by, updated_by)
                VALUES (p_service_id, p_property_id, v_name_en, v_name_km, p_price_usd_cents,
                    p_actor_id, p_actor_id)
                RETURNING service.* INTO v_service;
                v_before_json := NULL;
            ELSE
                IF NOT FOUND OR v_before.property_id <> p_property_id
                    OR v_before.removed_at IS NOT NULL
                THEN
                    RAISE EXCEPTION 'Regular service was not found' USING ERRCODE = 'P0002';
                END IF;
                IF v_before.version IS DISTINCT FROM p_expected_version THEN RETURN NULL; END IF;
                IF EXISTS (SELECT 1 FROM app.regular_services AS other
                           WHERE other.property_id = p_property_id AND other.removed_at IS NULL
                             AND other.id <> p_service_id
                             AND lower(other.name_en) = lower(v_name_en)) THEN
                    RAISE EXCEPTION 'A Regular service has this name' USING ERRCODE = 'P5V04';
                END IF;
                v_before_json := app.regular_service_json(v_before);
                UPDATE app.regular_services AS service
                SET name_en = v_name_en, name_km = v_name_km, price_usd_cents = p_price_usd_cents,
                    version = service.version + 1,
                    updated_at = greatest(statement_timestamp(), service.updated_at),
                    updated_by = p_actor_id
                WHERE service.id = p_service_id
                RETURNING service.* INTO v_service;
            END IF;
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                CASE WHEN v_before_json IS NULL THEN 'regular_service.added'
                     ELSE 'regular_service.changed' END,
                'regular_service', p_service_id, 'Regular service saved in Settings',
                v_before_json, app.regular_service_json(v_service));
            RETURN app.regular_service_json(v_service);
        END $$;

        CREATE FUNCTION app.remove_regular_service(
            p_property_id uuid, p_actor_id uuid, p_service_id uuid, p_expected_version integer,
            p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_before app.regular_services%ROWTYPE;
            v_service app.regular_services%ROWTYPE;
        BEGIN
            v_timezone := app.require_settings_actor(
                p_property_id, p_actor_id, p_authorization_reference);
            PERFORM pg_advisory_xact_lock(
                hashtextextended('regular-services:' || p_property_id::text, 0));
            SELECT service.* INTO v_before FROM app.regular_services AS service
            WHERE service.id = p_service_id AND service.property_id = p_property_id FOR UPDATE;
            IF NOT FOUND OR v_before.removed_at IS NOT NULL THEN
                RAISE EXCEPTION 'Regular service was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_before.version IS DISTINCT FROM p_expected_version THEN RETURN NULL; END IF;
            IF app.regular_service_used_this_year(v_before) > 0 THEN
                RAISE EXCEPTION 'The Regular service was used on an Invoice this year'
                    USING ERRCODE = 'P5V05';
            END IF;
            UPDATE app.regular_services AS service
            SET removed_at = statement_timestamp(), removed_by = p_actor_id,
                version = service.version + 1,
                updated_at = greatest(statement_timestamp(), service.updated_at),
                updated_by = p_actor_id
            WHERE service.id = p_service_id
            RETURNING service.* INTO v_service;
            PERFORM app.audit_service_setting(p_property_id, p_actor_id, v_timezone,
                'regular_service.removed', 'regular_service', p_service_id,
                'Regular service removed in Settings', app.regular_service_json(v_before),
                app.regular_service_json(v_service));
            RETURN app.regular_service_json(v_service);
        END $$;

        -- The Regular services not removed, by name.
        CREATE FUNCTION app.regular_services_read(p_property_id uuid) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'regular_services', coalesce((
                    SELECT jsonb_agg(app.regular_service_json(service)
                        ORDER BY lower(service.name_en), service.id)
                    FROM app.regular_services AS service
                    WHERE service.property_id = p_property_id AND service.removed_at IS NULL),
                    '[]'::jsonb)
            )
            WHERE EXISTS (SELECT 1 FROM app.properties WHERE id = p_property_id)
        $$;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION app.create_services_invoice_draft(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_invoice_id uuid, p_audit_id uuid, p_correlation_id uuid, p_customer_id uuid,
            p_lease_id uuid, p_items jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_replay jsonb; v_result jsonb; v_item jsonb; v_items jsonb:='[]'::jsonb;
            v_links jsonb:='[]'::jsonb; v_service app.regular_services%ROWTYPE;
            v_quantity numeric; v_charge uuid; v_service_id uuid;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'create',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_items IS NULL OR jsonb_typeof(p_items)<>'array'
                OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 20
            THEN RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023'; END IF;
            -- The prices are read under the Settings lock, so a price saved at the same moment
            -- is either wholly before or wholly after this Invoice.
            PERFORM pg_advisory_xact_lock_shared(
                hashtextextended('regular-services:' || p_property_id::text, 0));
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
                IF jsonb_typeof(v_item)<>'object'
                    OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v_item) AS key)
                        IS DISTINCT FROM ARRAY['charge_id','quantity','regular_service_id']
                    OR jsonb_typeof(v_item->'charge_id')<>'string'
                    OR jsonb_typeof(v_item->'regular_service_id')<>'string'
                    OR jsonb_typeof(v_item->'quantity')<>'number'
                THEN RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023'; END IF;
                BEGIN
                    v_charge:=(v_item->>'charge_id')::uuid;
                    v_service_id:=(v_item->>'regular_service_id')::uuid;
                    v_quantity:=(v_item->>'quantity')::numeric;
                EXCEPTION WHEN data_exception THEN
                    RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE='22023';
                END;
                SELECT * INTO v_service FROM app.regular_services
                WHERE id=v_service_id AND property_id=p_property_id AND removed_at IS NULL;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Regular service was not found' USING ERRCODE='P0002';
                END IF;
                v_items:=v_items||jsonb_build_array(jsonb_build_object(
                    'charge_id',v_charge,'description',v_service.name_en,
                    'quantity',v_quantity,'unit_price_usd_cents',v_service.price_usd_cents));
                v_links:=v_links||jsonb_build_array(jsonb_build_object(
                    'charge_id',v_charge,'regular_service_id',v_service.id));
            END LOOP;
            v_result:=app.create_items_invoice_draft(p_property_id,p_actor_id,p_idempotency_key,
                p_request_digest,p_invoice_id,p_audit_id,p_correlation_id,p_customer_id,p_lease_id,
                'Regular services from Settings','Settings > Regular services price',v_items);
            INSERT INTO app.regular_service_charges(charge_id,regular_service_id)
            SELECT (link->>'charge_id')::uuid,(link->>'regular_service_id')::uuid
            FROM jsonb_array_elements(v_links) AS link;
            RETURN v_result;
        END $$;
        """
    )
    _patch(REPLACE, ((TYPED_ONLY_BEFORE, TYPED_ONLY_AFTER),))
    _patch(INCOME_FACTS, ((INCOME_BEFORE, INCOME_AFTER),))
    for signature in SETTINGS_SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    op.execute(
        f"REVOKE ALL ON FUNCTION {CREATE} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {CREATE} TO prm_financial")
    op.execute(
        """
        REVOKE ALL ON app.regular_services, app.regular_service_charges
            FROM PUBLIC, prm_runtime, prm_bootstrap;
        """
    )


def downgrade() -> None:
    raise RuntimeError("V1.1 Regular services migration is forward-only")
