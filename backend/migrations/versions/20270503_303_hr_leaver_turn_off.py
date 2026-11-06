"""HRIS phase 6 step 4: a leaver's app user is turned off after the last working day (PR-HR-009).

The billing worker calls app.hr_turn_off_leavers on every pass, as its service actor, under its
lock. An employee whose last working day has passed (the day after it, Property time, the same
day hr_works_on stops) and whose linked app user is still active gets that user turned off:

1. The account becomes disabled, the same permanent change as Settings > Users and sign-in >
   Turn off: a disabled account cannot sign in, and no path makes it active again.
2. Its live sign-in sessions end (reason account_disabled).
3. The account history (app.user_account_changes) records the change, by the person who
   recorded the leaving, with provenance hr-left-turn-off; the audit trail records the service
   actor, source SCHEDULED, with the employee code and the last working day.

The Owner account is never turned off this way. A leaving cannot be undone, so the turn-off
follows a recorded fact. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270503_303"
down_revision: str | None = "20270502_302"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGNATURE = "app.hr_turn_off_leavers(uuid, uuid, timestamptz)"

FUNCTION = """
CREATE FUNCTION app.hr_turn_off_leavers(p_property uuid, p_actor uuid, p_at timestamptz)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_zone text;
    v_day date;
    v_leaver record;
    v_version integer;
    v_previous jsonb;
    v_resulting jsonb;
    v_revoked integer;
    v_done jsonb := '[]'::jsonb;
    v_correlation uuid := gen_random_uuid();
    v_at timestamptz := statement_timestamp();
BEGIN
    IF p_at IS NULL OR abs(extract(epoch FROM p_at - v_at)) > 3600 THEN
        RAISE EXCEPTION 'The leaver pass runs at the real time' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.actor_identities AS identity
            WHERE identity.actor_id = p_actor AND identity.identity_kind = 'SERVICE') THEN
        RAISE EXCEPTION 'Only the scheduled worker turns off a leaver''s app user'
            USING ERRCODE = '42501';
    END IF;
    PERFORM app.assert_active_financial_actor(p_actor, p_property);
    SELECT property.timezone_name INTO STRICT v_zone FROM app.properties AS property
    WHERE property.id = p_property;
    v_day := timezone(v_zone, p_at)::date;
    FOR v_leaver IN
        SELECT employee.id AS employee_id, employee.employee_code, account.actor_id,
            event.effective_date AS left_on, event.created_by AS recorded_by
        FROM app.employees AS employee
        JOIN app.employment_events AS event
          ON event.employee_id = employee.id AND event.event_type = 'LEFT'
        JOIN app.user_accounts AS account ON account.actor_id = employee.user_actor_id
        -- The account history names a person: the one who recorded the leaving.
        JOIN app.user_accounts AS recorder ON recorder.actor_id = event.created_by
        WHERE employee.property_id = p_property
          AND event.effective_date < v_day
          AND account.lifecycle_state = 'active'
          AND NOT EXISTS (SELECT 1 FROM app.user_account_classes AS classification
              WHERE classification.actor_id = account.actor_id
                AND classification.account_class = 'owner')
        ORDER BY event.effective_date, employee.employee_code
        FOR UPDATE OF account
    LOOP
        v_version := app.user_account_version(v_leaver.actor_id);
        SELECT jsonb_build_object('display_name', account.display_name,
                'audit_name', account.audit_name, 'lifecycle_state', account.lifecycle_state,
                'mfa_policy_class', account.mfa_policy_class, 'version', v_version)
        INTO STRICT v_previous
        FROM app.user_accounts AS account WHERE account.actor_id = v_leaver.actor_id;
        UPDATE app.user_accounts SET lifecycle_state = 'disabled'
        WHERE actor_id = v_leaver.actor_id;
        v_revoked := app.revoke_live_sessions(v_leaver.actor_id, v_leaver.recorded_by,
            'account_disabled', 'hr-left-turn-off');
        v_resulting := v_previous || jsonb_build_object('lifecycle_state', 'disabled',
            'version', v_version + 1);
        INSERT INTO app.user_account_changes (actor_id, version, changed_by_actor_id,
            previous_state, resulting_state, provenance)
        VALUES (v_leaver.actor_id, v_version + 1, v_leaver.recorded_by, v_previous,
            v_resulting, 'hr-left-turn-off');
        INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
            entity_type, entity_id, reason, authorization_reference, property_id,
            previous_state, resulting_state, correlation_id, source, outcome)
        VALUES (gen_random_uuid(), v_at, timezone(v_zone, v_at)::date, p_actor,
            'identity.account.disabled', 'user_account', v_leaver.actor_id,
            format('Employee %s left: the last working day was %s',
                v_leaver.employee_code, to_char(v_leaver.left_on, 'DD/MM/YYYY')),
            'hr.employees.manage', p_property, v_previous,
            v_resulting || jsonb_build_object('sessions_revoked', v_revoked,
                'employee_id', v_leaver.employee_id, 'last_working_day', v_leaver.left_on,
                'leaving_recorded_by', v_leaver.recorded_by),
            v_correlation, 'SCHEDULED', 'SUCCEEDED');
        v_done := v_done || jsonb_build_object('employee_id', v_leaver.employee_id,
            'actor_id', v_leaver.actor_id, 'sessions_revoked', v_revoked);
    END LOOP;
    RETURN jsonb_build_object('business_date', v_day, 'turned_off', v_done);
END $$;
"""


def upgrade() -> None:
    op.execute(FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("HRIS leaver turn-off migration is forward-only")
