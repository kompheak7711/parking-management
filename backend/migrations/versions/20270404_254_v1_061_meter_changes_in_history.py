"""Meter changes show in History (V1-061; DL-114).

Revision ID: 20270404_254
Revises: 20270403_253
Create Date: 2026-10-29

Owner bug list of 2026-10-29 ("Bugs first, then V1.1"): "Meter changes must show in History."
History reads app.audit_events, and a new Meter, a replaced Meter or a reported broken Meter
wrote no audit event, so History never showed them. Three triggers now write one audit event
for each, in the same transaction as the change:

- a new Meter (the INSTALL_METER command): ``utility.meter.installed``;
- a replaced Meter (app.utility_meter_replacements): ``utility.meter.replaced``, on the new
  Meter, with the failed Meter in the previous state and the staff reason;
- a broken Meter (app.utility_meter_failure_reports): ``utility.meter.failure_reported``, with
  the staff reason.

Each event names the Unit, so History's Unit filter finds it. Readings are not added: they are
the monthly work, not a change of the Meter.

Additive only: one trigger function and three triggers on append-only tables. SECURITY DEFINER
with a fixed search_path, so the runtime role keeps no right to write audit events itself.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270404_254"
down_revision: str | None = "20270403_253"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.audit_utility_meter_change() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_meter record;
            v_unit record;
            v_action text;
            v_actor uuid;
            v_at timestamptz;
            v_reason text;
            v_correlation uuid;
            v_previous jsonb;
        BEGIN
            IF TG_TABLE_NAME = 'utility_api_commands' THEN
                v_action := 'utility.meter.installed';
                SELECT * INTO STRICT v_meter FROM app.utility_meters WHERE id = NEW.resource_id;
                v_actor := NEW.actor_id;
                v_at := NEW.completed_at;
                v_reason := 'Meter added';
                v_correlation := NEW.idempotency_key;
            ELSIF TG_TABLE_NAME = 'utility_meter_replacements' THEN
                v_action := 'utility.meter.replaced';
                SELECT * INTO STRICT v_meter FROM app.utility_meters
                WHERE id = NEW.replacement_meter_id;
                v_actor := NEW.actor_id;
                v_at := NEW.occurred_at;
                v_reason := NEW.reason;
                v_correlation := coalesce(NEW.request_idempotency_key, NEW.id);
                SELECT jsonb_build_object('meter_id', failed.id,
                    'serial_number', failed.serial_number, 'failure_date', NEW.failure_date)
                INTO STRICT v_previous FROM app.utility_meters AS failed
                WHERE failed.id = NEW.failed_meter_id;
            ELSE
                v_action := 'utility.meter.failure_reported';
                SELECT * INTO STRICT v_meter FROM app.utility_meters WHERE id = NEW.meter_id;
                v_actor := NEW.actor_id;
                v_at := NEW.occurred_at;
                v_reason := NEW.reason;
                v_correlation := coalesce(NEW.request_idempotency_key, NEW.id);
            END IF;
            SELECT unit.id, unit.property_id, property.timezone_name INTO STRICT v_unit
            FROM app.units AS unit JOIN app.properties AS property ON property.id = unit.property_id
            WHERE unit.id = v_meter.unit_id;
            INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome, unit_id)
            VALUES (gen_random_uuid(), v_at, timezone(v_unit.timezone_name, v_at)::date, v_actor,
                v_action, 'utility_meter', v_meter.id, v_reason, 'utility_meters.manage',
                v_unit.property_id, v_previous,
                jsonb_build_object('serial_number', v_meter.serial_number,
                    'utility_type', v_meter.utility_type,
                    'installed_date', v_meter.installed_date,
                    'failure_date', v_meter.failure_date,
                    'deactivated_date', v_meter.deactivated_date,
                    'version', v_meter.version),
                v_correlation, 'API', 'SUCCEEDED', v_unit.id);
            RETURN NULL;
        END
        $$;
        REVOKE ALL ON FUNCTION app.audit_utility_meter_change() FROM PUBLIC;

        CREATE TRIGGER utility_api_commands_zz_meter_history
        AFTER INSERT ON app.utility_api_commands
        FOR EACH ROW WHEN (NEW.action = 'INSTALL_METER')
        EXECUTE FUNCTION app.audit_utility_meter_change();

        CREATE TRIGGER utility_meter_replacements_zz_history
        AFTER INSERT ON app.utility_meter_replacements
        FOR EACH ROW EXECUTE FUNCTION app.audit_utility_meter_change();

        CREATE TRIGGER utility_meter_failure_reports_zz_history
        AFTER INSERT ON app.utility_meter_failure_reports
        FOR EACH ROW EXECUTE FUNCTION app.audit_utility_meter_change();
        """
    )


def downgrade() -> None:
    raise RuntimeError("Migration 20270404_254 is forward-only")
