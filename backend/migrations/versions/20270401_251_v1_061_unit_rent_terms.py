# ruff: noqa: E501
"""V1-061 (owner 2026-10-29, DL-110): a Unit's default Rent and its required Services.

Owner answers of 2026-10-29 04:17 (decision cards, both the recommendation):
- "How should the Unit's default Rent work?" -> "Lower Rent needs a Manager": a new Reservation
  or Lease draft for the Unit starts with this Rent; staff may raise it; a Rent below it needs a
  Manager or the Owner (the new right `rent.below_default`) and a reason. The application checks
  the right, as for every other right; the database keeps the Rent.
- "How should a Unit's required Services work?" -> "Ticked and locked": a new Lease draft for the
  Unit must hold every required Service; staff cannot untick them. Leases that already exist do
  not change.

New, additive only:
1. `app.units.default_monthly_rent_usd_cents` (integer cents, empty or above zero).
2. `app.unit_required_services`: the Services a Unit requires (its current set; each change is
   kept in the Unit's audit history by the application).
3. `app.unit_rent_terms(unit)`: the default Rent and the required Service ids.
4. `app.set_unit_rent_terms(unit, version, rent, services, actor)`: sets both at the expected
   Unit version and moves the version on; a Service must be one of the Unit's Property.
5. The right `rent.below_default` in the catalog, given to each Property's default Owner and
   Manager bundles through a new bundle version with one audit event each.
6. `app.create_lease_draft_with_terms` refuses ('Lease draft is missing a required Service of
   the Unit') a draft that leaves out a required Service.
"""

import re

from alembic import op
from sqlalchemy import text

revision = "20270401_251"
down_revision = "20270331_250"
branch_labels = None
depends_on = None

NEW_CAPABILITIES = (("rent.below_default", "Agree a Rent below the Unit's default Rent"),)
REASON = (
    "Owner answer 2026-10-29 (DL-110): a Rent below the default Rent of the Unit needs a Manager or "
    "the Owner"
)
DRAFT = (
    "app.create_lease_draft_with_terms(uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,date,date,bigint,"
    "uuid,jsonb,jsonb,jsonb,jsonb,uuid,text,uuid)"
)
DRAFT_ANCHOR = "SET CONSTRAINTS app.lease_service_terms_validate IMMEDIATE;\n"
DRAFT_CHECK = (
    DRAFT_ANCHOR
    + """            -- V1-061 (DL-110): a new draft holds every Service its Unit requires.
            IF EXISTS (
                SELECT 1 FROM app.unit_required_services AS required
                WHERE required.unit_id = p_unit_id
                  AND NOT EXISTS (
                    SELECT 1 FROM app.lease_service_terms AS term
                    WHERE term.lease_id = p_lease_id
                      AND term.property_service_id = required.property_service_id
                  )
            ) THEN
                RAISE EXCEPTION 'Lease draft is missing a required Service of the Unit'
                    USING ERRCODE = '23514';
            END IF;
"""
)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.units
            ADD COLUMN default_monthly_rent_usd_cents bigint
                CONSTRAINT units_default_rent_positive
                CHECK (default_monthly_rent_usd_cents IS NULL OR default_monthly_rent_usd_cents > 0);

        CREATE TABLE app.unit_required_services (
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            property_service_id uuid NOT NULL
                REFERENCES app.property_services(id) ON DELETE RESTRICT,
            added_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            added_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            PRIMARY KEY (unit_id, property_service_id)
        );
        CREATE INDEX unit_required_services_service_idx
            ON app.unit_required_services(property_service_id);
        REVOKE ALL ON TABLE app.unit_required_services FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.unit_required_services TO prm_runtime;

        CREATE FUNCTION app.unit_rent_terms(p_unit_id uuid)
        RETURNS TABLE(default_monthly_rent_usd_cents bigint, required_service_ids uuid[])
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT unit.default_monthly_rent_usd_cents,
                   coalesce(
                       (SELECT array_agg(required.property_service_id
                                         ORDER BY required.property_service_id)
                        FROM app.unit_required_services AS required
                        WHERE required.unit_id = unit.id),
                       ARRAY[]::uuid[]
                   )
            FROM app.units AS unit
            WHERE unit.id = p_unit_id
        $$;
        REVOKE ALL ON FUNCTION app.unit_rent_terms(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.unit_rent_terms(uuid) TO prm_runtime;

        -- Sets the default Rent and the required Services at the expected Unit version. Answers
        -- the new version, or NULL when the Unit is not there or its version moved on.
        CREATE FUNCTION app.set_unit_rent_terms(
            p_unit_id uuid,
            p_expected_version integer,
            p_default_monthly_rent_usd_cents bigint,
            p_required_service_ids uuid[],
            p_actor_id uuid
        ) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_unit app.units%ROWTYPE;
        BEGIN
            IF p_required_service_ids IS NULL
                OR array_position(p_required_service_ids, NULL) IS NOT NULL
                OR cardinality(p_required_service_ids) > 20
                OR cardinality(p_required_service_ids) <> (
                    SELECT count(DISTINCT value) FROM unnest(p_required_service_ids) AS value
                )
                OR (p_default_monthly_rent_usd_cents IS NOT NULL
                    AND p_default_monthly_rent_usd_cents <= 0)
            THEN
                RAISE EXCEPTION 'Unit Rent terms are invalid' USING ERRCODE = '22023';
            END IF;
            SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = p_unit_id FOR UPDATE;
            IF NOT FOUND OR v_unit.version <> p_expected_version THEN
                RETURN NULL;
            END IF;
            IF EXISTS (
                SELECT 1 FROM unnest(p_required_service_ids) AS wanted(id)
                LEFT JOIN app.property_services AS service
                  ON service.id = wanted.id AND service.property_id = v_unit.property_id
                WHERE service.id IS NULL
            ) THEN
                RAISE EXCEPTION 'Required Service was not found in Property scope'
                    USING ERRCODE = '22023';
            END IF;
            UPDATE app.units AS unit
            SET default_monthly_rent_usd_cents = p_default_monthly_rent_usd_cents,
                version = unit.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE unit.id = p_unit_id;
            DELETE FROM app.unit_required_services AS required
            WHERE required.unit_id = p_unit_id
              AND NOT required.property_service_id = ANY(p_required_service_ids);
            INSERT INTO app.unit_required_services(unit_id, property_service_id, added_by)
            SELECT p_unit_id, wanted.id, p_actor_id FROM unnest(p_required_service_ids) AS wanted(id)
            ON CONFLICT DO NOTHING;
            RETURN v_unit.version + 1;
        END $$;
        REVOKE ALL ON FUNCTION app.set_unit_rent_terms(uuid, integer, bigint, uuid[], uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.set_unit_rent_terms(uuid, integer, bigint, uuid[], uuid)
            TO prm_runtime;
        """
    )

    bind = op.get_bind()
    definition = bind.execute(
        text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
        {"signature": DRAFT},
    ).scalar_one()
    if definition.count(DRAFT_ANCHOR) != 1:
        raise RuntimeError(f"Lease draft source contract changed: {DRAFT}")
    op.execute(definition.replace(DRAFT_ANCHOR, DRAFT_CHECK, 1))

    assert all(re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", name) for name, _ in NEW_CAPABILITIES)
    for capability, description in NEW_CAPABILITIES:
        op.execute(
            "INSERT INTO app.capabilities "
            "(capability_id, family, description, grant_path, provenance) VALUES "
            f"('{capability}', pg_catalog.split_part('{capability}', '.', 1), "
            f"'{description.replace(chr(39), chr(39) * 2)}', 'bundle', 'v1-061-unit-rent')"
        )
    added = ", ".join(f"'{capability}'" for capability, _ in NEW_CAPABILITIES)
    op.execute(
        f"""
        DO $$
        DECLARE
            v_default record;
            v_owner uuid;
            v_timezone text;
            v_at timestamptz := pg_catalog.statement_timestamp();
        BEGIN
            SELECT classification.actor_id INTO v_owner
            FROM app.user_account_classes AS classification
            WHERE classification.account_class = 'owner';
            FOR v_default IN
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (seeded.owner_bundle_id, seeded.manager_bundle_id)
                ORDER BY seeded.property_id, bundle.role_bundle_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles SET version = v_default.version + 1
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, v_default.version + 1, given
                FROM (
                    SELECT held.capability_id AS given FROM app.role_bundle_capabilities AS held
                    WHERE held.role_bundle_id = v_default.role_bundle_id
                      AND held.version = v_default.version
                    UNION
                    SELECT listed FROM pg_catalog.unnest(ARRAY[{added}]::text[]) AS listed
                ) AS next_set;
                SELECT property.timezone_name INTO v_timezone
                FROM app.properties AS property WHERE property.id = v_default.property_id;
                IF v_owner IS NOT NULL THEN
                    INSERT INTO app.audit_events (
                        id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                        reason, authorization_reference, property_id, previous_state,
                        resulting_state, correlation_id, source, outcome
                    ) VALUES (
                        pg_catalog.gen_random_uuid(), v_at,
                        pg_catalog.timezone(v_timezone, v_at)::date, v_owner,
                        'identity.role_bundle.updated', 'role_bundle', v_default.role_bundle_id,
                        '{REASON}', 'identity.manage_access', v_default.property_id,
                        pg_catalog.jsonb_build_object('version', v_default.version),
                        pg_catalog.jsonb_build_object(
                            'version', v_default.version + 1,
                            'added_capability_ids', pg_catalog.to_jsonb(ARRAY[{added}]::text[])
                        ),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("V1-061 Unit Rent terms are forward-only")
