# ruff: noqa: E501
"""Telegram bots, step 4a: the Staff bot joins staff, and takes check-in and card scans (DL-174).

Owner rules: the staff join with Start and their own Telegram phone, and the Owner or a Manager
approves them and gives the report roles (24 Oct 2026, HR screens); staff check in and out by
scanning the place QR with Location on, and a caretaker scans the card of a person with no phone,
with a reason and a photo (3 Nov 2026, HR plan PR-HR-060 to 068). Staff see Khmer only.

The HR thread owns the staff tables and the scan rules (migrations 20270430_300 to
20270503_303). Its bot functions take only a service actor. The Telegram jobs run as an Owner or
Manager account with the Telegram rights, so each call below checks that account first and then
calls the HR function with the service actor the job was given:

1. ``telegram_staff_who``: who a Telegram user is (name, report roles, shift).
2. ``telegram_staff_join``: a Start with the person's own phone becomes a request for the Owner
   or a Manager (HR > Staff requests).
3. ``telegram_staff_check`` and ``telegram_staff_card``: a check-in or check-out scan, by phone
   or by card, with the answer's time in the Property's time.
4. ``telegram_staff_form_data``: who may open the Staff forms (linked staff today, with their
   name, roles and shift) and what the forms show; the pull job sends it to the relay.
5. The person hears the Owner's or Manager's answer to a join request from the Staff bot
   (a trigger on ``telegram_staff_request_decisions``).

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270620_331"
down_revision: str | None = "20270619_330"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = """
    -- The time of a scan as staff read it (Property time, 24 hours).
    CREATE FUNCTION app.telegram_staff_time(p_at text) RETURNS text
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN p_at IS NULL THEN NULL
            ELSE to_char(timezone(app.hr_zone(), p_at::timestamptz), 'HH24:MI') END
    $$;

    -- An HR answer with the staff words added: the time, the shift start and the shift name.
    CREATE FUNCTION app.telegram_staff_answer(p_result jsonb) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT p_result || jsonb_strip_nulls(jsonb_build_object(
            'time', app.telegram_staff_time(p_result ->> 'at'),
            'starts', app.telegram_staff_time(p_result ->> 'shift_starts_at'),
            'shift_km', (SELECT shift.name_km FROM app.work_shifts AS shift
                WHERE shift.code = p_result ->> 'shift_code')))
    $$;

    CREATE FUNCTION app.telegram_staff_who(p_property uuid, p_user bigint, p_service uuid,
        p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_who jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_who := app.hr_telegram_staff(p_property, p_user, p_service);
        IF NOT coalesce((v_who ->> 'linked')::boolean, false) THEN
            RETURN jsonb_build_object('linked', false, 'waiting', EXISTS (
                SELECT 1 FROM app.telegram_staff_requests AS request
                WHERE request.property_id = p_property AND request.telegram_user_id = p_user
                  AND NOT EXISTS (SELECT 1 FROM app.telegram_staff_request_decisions AS decision
                      WHERE decision.request_id = request.id)));
        END IF;
        RETURN v_who;
    END $$;

    CREATE FUNCTION app.telegram_staff_join(p_property uuid, p_user bigint, p_name text,
        p_phone text, p_received_at timestamptz, p_service uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        RETURN app.hr_record_staff_request(p_property, p_user, p_name, p_phone, p_received_at,
            p_service);
    END $$;

    CREATE FUNCTION app.telegram_staff_check(p_property uuid, p_user bigint, p_scan jsonb,
        p_at timestamptz, p_service uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        RETURN app.telegram_staff_answer(
            app.record_staff_check_scan(p_property, p_user, p_scan, p_at, p_service));
    END $$;

    CREATE FUNCTION app.telegram_staff_card(p_property uuid, p_user bigint, p_scan jsonb,
        p_at timestamptz, p_service uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        RETURN app.telegram_staff_answer(
            app.record_card_check_scan(p_property, p_user, p_scan, p_at, p_service));
    END $$;

    -- Card photos older than the rule, for the job to delete (and then record).
    CREATE FUNCTION app.telegram_staff_photos_due(p_property uuid, p_service uuid, p_actor uuid)
    RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        RETURN app.hr_photos_due(p_property, p_service);
    END $$;

    CREATE FUNCTION app.telegram_staff_photo_removed(p_property uuid, p_file uuid,
        p_service uuid, p_actor uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        PERFORM app.hr_record_photo_removal(p_property, p_file, p_service);
    END $$;

    -- Who may open the Staff forms on the relay, and what the forms show. A person is on the
    -- list while one of their links works today; the list is sent again when it changes.
    CREATE FUNCTION app.telegram_staff_form_data(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date;
        v_users jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT timezone(property.timezone_name, statement_timestamp())::date INTO v_today
        FROM app.properties AS property WHERE property.id = p_property;
        SELECT coalesce(jsonb_agg(jsonb_build_object('id', person.telegram_user_id,
                'role', 'STAFF', 'data', jsonb_build_object('name_km', person.name_km,
                    'name_en', person.name_en, 'roles', person.roles,
                    'shift_code', person.shift_code, 'shift_km', person.shift_km))
                ORDER BY person.telegram_user_id), '[]'::jsonb)
        INTO v_users
        FROM (
            SELECT link.telegram_user_id, employee.name_km, employee.name_en,
                jsonb_agg(DISTINCT link.report_role) AS roles, job.shift_code,
                (SELECT shift.name_km FROM app.work_shifts AS shift
                 WHERE shift.code = job.shift_code) AS shift_km
            FROM app.employee_telegram_links AS link
            JOIN app.employees AS employee ON employee.id = link.employee_id
            LEFT JOIN LATERAL app.hr_job_on(employee.id, v_today) AS job ON true
            WHERE employee.property_id = p_property AND app.hr_link_live(link.id, v_today)
            GROUP BY link.telegram_user_id, employee.id, employee.name_km, employee.name_en,
                job.shift_code
        ) AS person;
        RETURN jsonb_build_object('users', v_users, 'choices',
            -- Report a problem (step 4b) uses the same types and places as the Tenant bot.
            app.telegram_tenant_form_data(p_property, p_actor) -> 'choices');
    END $$;

    -- The Owner's or Manager's answer to a join request, to the person in the Staff bot.
    CREATE FUNCTION app.telegram_staff_request_answered() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_request app.telegram_staff_requests%ROWTYPE;
    BEGIN
        SELECT request.* INTO v_request FROM app.telegram_staff_requests AS request
        WHERE request.id = NEW.request_id;
        INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
            details, keyboard, created_by)
        VALUES (v_request.property_id, 'STAFF', v_request.telegram_user_id,
            CASE NEW.decision WHEN 'LINKED' THEN 'staff.approved' ELSE 'staff.refused' END,
            'km', '{}'::jsonb,
            CASE NEW.decision WHEN 'LINKED' THEN 'staff.open' END, NEW.decided_by);
        RETURN NULL;
    END $$;

    CREATE TRIGGER telegram_staff_request_answered
        AFTER INSERT ON app.telegram_staff_request_decisions
        FOR EACH ROW EXECUTE FUNCTION app.telegram_staff_request_answered();
"""

RUNTIME = (
    "app.telegram_staff_who(uuid, bigint, uuid, uuid)",
    "app.telegram_staff_join(uuid, bigint, text, text, timestamptz, uuid, uuid)",
    "app.telegram_staff_check(uuid, bigint, jsonb, timestamptz, uuid, uuid)",
    "app.telegram_staff_card(uuid, bigint, jsonb, timestamptz, uuid, uuid)",
    "app.telegram_staff_photos_due(uuid, uuid, uuid)",
    "app.telegram_staff_photo_removed(uuid, uuid, uuid, uuid)",
    "app.telegram_staff_form_data(uuid, uuid)",
)
INTERNAL = (
    "app.telegram_staff_time(text)",
    "app.telegram_staff_answer(jsonb)",
    "app.telegram_staff_request_answered()",
)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Staff bot migration is forward-only")
