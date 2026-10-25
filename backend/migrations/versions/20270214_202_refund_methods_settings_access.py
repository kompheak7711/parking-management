# ruff: noqa: E501
"""Add and turn off Refund methods with Settings access (V1-056 slice 11h; BR-REFUND-014).

Owner answer of 2026-10-25 01:32: Refund methods are managed with Settings access. Only the Owner
and people ticked for Settings access may add a Refund method or turn one off or on again, and at
least one Refund method always stays on.

The two writers of migration `20261013_78` had no caller yet. They are replaced with the same
signatures (grants kept):

1. They need the authorization reference `settings.manage` (it was `property.manage`).
2. Every change takes the Refund method list lock first, so changes run one at a time.
3. `app.create_refund_method` checks its input itself (22023, a zero id included) and refuses a
   code another method already has with its own message (23505), not the unique index's.
4. `app.set_refund_method_active` refuses to turn off the last method that is on (55000). The
   other methods that are on are locked `FOR SHARE` before the check, so two people turning off
   the last two methods at once cannot both succeed.
5. Each real change writes an audit event (`refund_method.added`, `refund_method.turned_off`,
   `refund_method.turned_on`, under `settings.manage`); a repeat that changes nothing writes
   none.

A Refund draft that names a method turned off later is refused at its confirm as before (the
method must be on); the list read is not changed.
"""

from alembic import op

revision = "20270214_202"
down_revision = "20270213_201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.create_refund_method(
            p_property_id uuid, p_actor_id uuid, p_method_id uuid, p_code text,
            p_display_name text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_method app.refund_methods%ROWTYPE; v_timezone text; v_now timestamptz;
        BEGIN
            v_timezone := app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS DISTINCT FROM 'settings.manage' THEN
                RAISE EXCEPTION 'Refund Method change needs settings.manage' USING ERRCODE = '42501';
            END IF;
            IF p_method_id IS NULL OR p_method_id = '00000000-0000-0000-0000-000000000000'
                OR p_code IS NULL OR p_code !~ '^[A-Z][A-Z0-9_]{1,39}$'
                OR p_display_name IS NULL OR p_display_name <> btrim(p_display_name)
                OR length(p_display_name) NOT BETWEEN 1 AND 120
            THEN
                RAISE EXCEPTION 'Refund Method input is invalid' USING ERRCODE = '22023';
            END IF;
            -- V1-056 slice 11h: Refund method changes run one at a time.
            PERFORM pg_advisory_xact_lock(hashtextextended('refund-method-list', 0));
            SELECT * INTO v_method FROM app.refund_methods WHERE id = p_method_id;
            IF FOUND THEN
                IF v_method.code = p_code AND v_method.display_name = p_display_name
                    AND v_method.created_by = p_actor_id
                THEN RETURN app.refund_method_json(v_method); END IF;
                RAISE EXCEPTION 'Refund Method identity was reused' USING ERRCODE = '23505';
            END IF;
            IF EXISTS (SELECT 1 FROM app.refund_methods AS method WHERE method.code = p_code) THEN
                RAISE EXCEPTION 'Refund Method code is already used' USING ERRCODE = '23505';
            END IF;
            v_now := clock_timestamp();
            INSERT INTO app.refund_methods(
                id, code, display_name, active, seeded, created_at, created_by, updated_at, updated_by
            ) VALUES (
                p_method_id, p_code, p_display_name, true, false, v_now, p_actor_id, v_now, p_actor_id
            ) RETURNING * INTO v_method;
            INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                authorization_evidence)
            VALUES (gen_random_uuid(), v_now, timezone(v_timezone, v_now)::date, p_actor_id,
                'refund_method.added', 'refund_method', p_method_id,
                'Refund method added in Settings', 'settings.manage', p_property_id, NULL,
                app.refund_method_json(v_method), gen_random_uuid(), 'API', 'SUCCEEDED',
                jsonb_build_object('capability', 'settings.manage'));
            RETURN app.refund_method_json(v_method);
        END $$;

        CREATE OR REPLACE FUNCTION app.set_refund_method_active(
            p_property_id uuid, p_actor_id uuid, p_method_id uuid, p_active boolean,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_method app.refund_methods%ROWTYPE; v_before jsonb; v_timezone text;
        DECLARE v_now timestamptz;
        BEGIN
            v_timezone := app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS DISTINCT FROM 'settings.manage' THEN
                RAISE EXCEPTION 'Refund Method change needs settings.manage' USING ERRCODE = '42501';
            END IF;
            IF p_method_id IS NULL OR p_active IS NULL THEN
                RAISE EXCEPTION 'Refund Method input is invalid' USING ERRCODE = '22023';
            END IF;
            -- V1-056 slice 11h: Refund method changes run one at a time.
            PERFORM pg_advisory_xact_lock(hashtextextended('refund-method-list', 0));
            SELECT * INTO v_method FROM app.refund_methods WHERE id = p_method_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Refund Method was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_method.active = p_active THEN RETURN app.refund_method_json(v_method); END IF;
            IF NOT p_active THEN
                -- At least one Refund method stays on (owner answer of 2026-10-25). Locking the
                -- others makes a concurrent change visible (READ COMMITTED) or a serialization
                -- failure (REPEATABLE READ), never a silent pass.
                PERFORM 1 FROM app.refund_methods AS method
                WHERE method.active AND method.id <> p_method_id
                ORDER BY method.id FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'At least one Refund Method stays on' USING ERRCODE = '55000';
                END IF;
            END IF;
            v_before := app.refund_method_json(v_method);
            v_now := GREATEST(clock_timestamp(), v_method.updated_at);
            UPDATE app.refund_methods
            SET active = p_active, updated_at = v_now, updated_by = p_actor_id
            WHERE id = p_method_id RETURNING * INTO v_method;
            INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                authorization_evidence)
            VALUES (gen_random_uuid(), v_now, timezone(v_timezone, v_now)::date, p_actor_id,
                CASE WHEN p_active THEN 'refund_method.turned_on' ELSE 'refund_method.turned_off' END,
                'refund_method', p_method_id,
                CASE WHEN p_active THEN 'Refund method turned on in Settings'
                    ELSE 'Refund method turned off in Settings' END,
                'settings.manage', p_property_id, v_before, app.refund_method_json(v_method),
                gen_random_uuid(), 'API', 'SUCCEEDED',
                jsonb_build_object('capability', 'settings.manage'));
            RETURN app.refund_method_json(v_method);
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Refund method Settings access migration is forward-only")
