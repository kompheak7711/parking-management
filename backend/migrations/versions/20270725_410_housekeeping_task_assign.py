"""Owner's choices of 14 Nov 2026, DL-236: a Housekeeping task is given to one cleaner, who gets it
and ticks it in the Staff bot on Telegram.

The owner asked who a cleaning task is for and chose "Yes, assign to a person". Then, because the
cleaners do not use the office app, the owner chose "Telegram: get and tick tasks": the front desk
gives each task to a cleaner from the staff list (HR), the Staff bot sends the cleaner the task
with the buttons Cleaned and Not cleaned, and the tap finishes the task in the app.

What this migration adds:

- ``app.housekeeping_tasks`` gets ``assigned_to`` (an employee, ``app.employees``),
  ``assigned_at`` and ``assigned_by`` (the front desk), and ``done_by_employee`` (the cleaner who
  tapped in Telegram). Tasks made before are given to nobody; nothing is filled in for them.
- ``app.protect_short_stay_step`` (the guard that lets a task move forward once) also lets a task
  still to do change its assignment, and nothing else, with its version; finishing may also name
  ``done_by_employee``.
- ``app.housekeeping_staff_chats``: the Staff bot chats of an employee (live HR Telegram links).
- ``app.short_stay_cleaners``: the people a task may be given to: employees of the Property who
  work on the day and whose job is Cleaner or who report as Cleaner in the Staff bot, with
  ``telegram`` (the Staff bot can reach them).
- ``app.short_stay_housekeeping`` (the list of a day) also gives each task ``assigned_to``,
  ``assigned_name`` and ``done_by_name``, and the list gives ``cleaners``.
- ``app.assign_housekeeping_task``: the front desk (``short_stays.desk``) gives a task still to do
  to a cleaner, to another, or to nobody; the History keeps the person before and after. The Staff
  bot sends the cleaner ``staff.task_given`` (Khmer): a clean has the buttons Cleaned and
  Not cleaned; a room check is done on the booking page, so it has none.
- ``app.telegram_staff_task_tap``: a cleaner's tap. Cleaned finishes the task; Not cleaned asks why
  with three fixed reasons, and the reason finishes it as not cleaned. Only the cleaner the task
  is given to may tap; the bot answers each tap once.

Anyone with ``short_stays.housekeeping`` may still finish any task in the app. No money, Invoice
or Unit status changes.

Forward-only.

Revision ID: 20270725_410
Revises: 20270725_402
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270725_410"
down_revision: str | None = "20270725_402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = r"""
ALTER TABLE app.housekeeping_tasks
    ADD COLUMN assigned_to uuid REFERENCES app.employees (id) ON DELETE RESTRICT,
    ADD COLUMN assigned_at timestamptz,
    ADD COLUMN assigned_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    ADD COLUMN done_by_employee uuid REFERENCES app.employees (id) ON DELETE RESTRICT,
    -- A task given to a person says when and by whom; a task never given to anyone says neither.
    ADD CONSTRAINT housekeeping_tasks_assign_shape CHECK (
        (assigned_at IS NULL) = (assigned_by IS NULL)
        AND (assigned_to IS NULL OR assigned_at IS NOT NULL)),
    -- Only a finished task names the cleaner who finished it in Telegram.
    ADD CONSTRAINT housekeeping_tasks_done_employee CHECK (
        done_by_employee IS NULL OR status <> 'TO_DO');
CREATE INDEX housekeeping_tasks_assigned_idx ON app.housekeeping_tasks (assigned_to)
    WHERE assigned_to IS NOT NULL;
"""

FUNCTIONS = r"""
-- The step guard of migration 20270602_312, unchanged except that a Housekeeping task still to
-- do may also be given to a person (only its assignment and version change), and finishing a
-- task may name the cleaner who tapped in Telegram.
CREATE OR REPLACE FUNCTION app.protect_short_stay_step() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_old jsonb := to_jsonb(OLD);
    v_new jsonb := to_jsonb(NEW);
    v_open text := CASE TG_TABLE_NAME
        WHEN 'short_stay_deposits' THEN 'HELD'
        WHEN 'housekeeping_tasks' THEN 'TO_DO'
        ELSE 'WAITING' END;
    v_free text[] := CASE TG_TABLE_NAME
        WHEN 'short_stay_deposits' THEN ARRAY['status', 'kept_usd_cents', 'ended_at', 'ended_by',
            'end_note', 'version']
        WHEN 'housekeeping_tasks' THEN ARRAY['status', 'note', 'done_at', 'done_by',
            'done_by_employee', 'version']
        ELSE ARRAY['status', 'decided_at', 'decided_by', 'decision_note', 'version',
            'from_deposit_usd_cents', 'invoice_id'] END;
    v_assign text[] := ARRAY['assigned_to', 'assigned_at', 'assigned_by', 'version'];
BEGIN
    IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'housekeeping_tasks'
        AND OLD.status = 'TO_DO' AND NEW.status = 'TO_DO'
        AND (v_new ->> 'version')::integer = (v_old ->> 'version')::integer + 1
        AND (v_old - v_assign) = (v_new - v_assign)
    THEN
        RETURN NEW;
    END IF;
    IF TG_OP <> 'UPDATE' OR OLD.status <> v_open OR NEW.status = v_open
        OR (v_new ->> 'version')::integer <> (v_old ->> 'version')::integer + 1
        OR (v_old - v_free) <> (v_new - v_free)
    THEN
        RAISE EXCEPTION '% rows move forward once and are never removed', TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;

-- The Staff bot chats of an employee: their live Telegram links on the day (HR, migration
-- 20270430_300).
CREATE FUNCTION app.housekeeping_staff_chats(p_employee uuid, p_day date)
RETURNS SETOF bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT DISTINCT link.telegram_user_id
    FROM app.employee_telegram_links AS link
    WHERE link.employee_id = p_employee AND app.hr_link_live(link.id, p_day)
$$;
REVOKE ALL ON FUNCTION app.housekeeping_staff_chats(uuid, date) FROM PUBLIC;

-- The people a Housekeeping task may be given to: employees of the Property who work on the day
-- and whose job is Cleaner or who report as Cleaner in the Staff bot. ``telegram`` says whether
-- the Staff bot can reach them.
CREATE FUNCTION app.short_stay_cleaners(p_property uuid, p_day date)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT COALESCE(jsonb_agg(jsonb_build_object('employee_id', employee.id,
            'name', employee.name_en, 'name_km', employee.name_km, 'telegram', EXISTS (
                SELECT 1 FROM app.housekeeping_staff_chats(employee.id, p_day)))
            ORDER BY lower(employee.name_en), employee.id),
        '[]'::jsonb)
    FROM app.employees AS employee
    WHERE employee.property_id = p_property
      AND app.hr_works_on(employee.id, p_day)
      AND (EXISTS (SELECT 1 FROM app.hr_job_on(employee.id, p_day) AS job
              JOIN app.job_titles AS title ON title.id = job.job_title_id
              WHERE title.code = 'CLEANER')
           OR EXISTS (SELECT 1 FROM app.employee_telegram_links AS link
              WHERE link.employee_id = employee.id AND link.report_role = 'CLEANER'
                AND app.hr_link_live(link.id, p_day)))
$$;
REVOKE ALL ON FUNCTION app.short_stay_cleaners(uuid, date) FROM PUBLIC;

CREATE OR REPLACE FUNCTION app.short_stay_housekeeping(p_property uuid, p_day date, p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v_today date := app.require_product_right(p_actor, 'short_stays.read', p_property);
BEGIN
    IF p_day IS NULL THEN
        RAISE EXCEPTION 'The day is invalid' USING ERRCODE = '22023';
    END IF;
    RETURN jsonb_build_object('day', p_day, 'today', v_today,
        'cleaners', app.short_stay_cleaners(p_property, v_today),
        'tasks', COALESCE((
        SELECT jsonb_agg(jsonb_build_object('task_id', task.id, 'kind', task.kind,
            'task_on', task.task_on, 'status', task.status, 'note', task.note,
            'done_at', task.done_at,
            'done_by_name', COALESCE(cleaner.name_en, done.display_name),
            'assigned_to', task.assigned_to, 'assigned_name', given.name_en,
            'unit_id', task.unit_id, 'unit_number', unit.unit_number,
            'booking_id', booking.id, 'booking_number', booking.booking_number,
            'guest_name', customer.legal_name, 'late', task.task_on < p_day,
            'version', task.version)
            ORDER BY task.status <> 'TO_DO', unit.unit_number, task.kind, task.task_on)
        FROM app.housekeeping_tasks AS task
        JOIN app.units AS unit ON unit.id = task.unit_id
        LEFT JOIN app.short_stay_bookings AS booking ON booking.id = task.booking_id
        LEFT JOIN app.customers AS customer ON customer.id = booking.customer_id
        LEFT JOIN app.user_accounts AS done ON done.actor_id = task.done_by
        LEFT JOIN app.employees AS cleaner ON cleaner.id = task.done_by_employee
        LEFT JOIN app.employees AS given ON given.id = task.assigned_to
        WHERE task.property_id = p_property
          AND (task.task_on = p_day
               OR (p_day = v_today AND task.task_on < p_day AND task.status = 'TO_DO'))),
        '[]'::jsonb));
END $$;

-- The Khmer name of a task kind, as the app's Khmer (frontend/src/shortstays/text.ts).
CREATE FUNCTION app.housekeeping_kind_km(p_kind text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT CASE p_kind
        WHEN 'DAILY_CLEAN' THEN 'សម្អាតប្រចាំថ្ងៃ'
        WHEN 'CHANGE_OVER' THEN 'សម្អាតពេលប្ដូរភ្ញៀវ'
        ELSE 'ពិនិត្យបន្ទប់' END
$$;
REVOKE ALL ON FUNCTION app.housekeeping_kind_km(text) FROM PUBLIC;

-- The front desk gives a task still to do to one cleaner, to another, or to nobody
-- ({"employee_id": null} or no employee_id). Answers with the list of the task's day.
CREATE FUNCTION app.assign_housekeeping_task(p_property uuid, p_task uuid, p_assign jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_task app.housekeeping_tasks;
    v_person uuid;
    v_chat bigint;
BEGIN
    IF p_assign IS NULL OR jsonb_typeof(p_assign) <> 'object'
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_assign) AS key WHERE key <> 'employee_id')
       OR jsonb_typeof(p_assign -> 'employee_id') NOT IN ('string', 'null') THEN
        RAISE EXCEPTION 'The task answer is invalid' USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_person := (p_assign ->> 'employee_id')::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'The task answer is invalid' USING ERRCODE = '22023';
    END;
    SELECT task.* INTO v_task FROM app.housekeeping_tasks AS task
    WHERE task.id = p_task AND task.property_id = p_property FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the task does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_task.status <> 'TO_DO' THEN
        RAISE EXCEPTION 'This task is already done' USING ERRCODE = '55000';
    END IF;
    IF v_person IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(app.short_stay_cleaners(p_property, v_today)) AS person
        WHERE (person ->> 'employee_id')::uuid = v_person) THEN
        RAISE EXCEPTION 'This person is not a cleaner here' USING ERRCODE = '22023';
    END IF;
    IF v_person IS NOT DISTINCT FROM v_task.assigned_to THEN
        RETURN app.short_stay_housekeeping(p_property, v_task.task_on, p_actor);
    END IF;
    UPDATE app.housekeeping_tasks AS task
    SET assigned_to = v_person, assigned_at = statement_timestamp(), assigned_by = p_actor,
        version = task.version + 1
    WHERE task.id = v_task.id;
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.task_assigned',
        'housekeeping_task', v_task.id,
        CASE WHEN v_person IS NULL THEN 'Housekeeping task given to nobody'
            ELSE 'Housekeeping task given to a cleaner' END,
        'short_stays.desk',
        jsonb_build_object('assigned_to', v_task.assigned_to),
        jsonb_build_object('assigned_to', v_person), p_correlation);
    -- The Staff bot tells the cleaner, once for this change (the key holds the new version).
    -- A clean has the buttons Cleaned and Not cleaned; a room check is done on the booking page.
    FOR v_chat IN SELECT chat FROM app.housekeeping_staff_chats(v_person, v_today) AS chat
    LOOP
        PERFORM app.telegram_queue_once(p_property, 'STAFF', v_chat, 'staff.task_given', 'km',
            jsonb_build_object(
                'unit', (SELECT unit.unit_number FROM app.units AS unit
                    WHERE unit.id = v_task.unit_id),
                'task', app.housekeeping_kind_km(v_task.kind),
                'day', to_char(v_task.task_on, 'DD/MM/YYYY')),
            CASE WHEN v_task.kind = 'ROOM_CHECK' THEN NULL ELSE jsonb_build_array(
                jsonb_build_array(
                    jsonb_build_object('text', '✅ បានសម្អាត',
                        'callback_data', 'hk:done:' || v_task.id),
                    jsonb_build_object('text', '❌ មិនបានសម្អាត',
                        'callback_data', 'hk:skip:' || v_task.id))) END,
            NULL, 'hk-task:' || v_task.id || ':' || (v_task.version + 1), p_actor);
    END LOOP;
    RETURN app.short_stay_housekeeping(p_property, v_task.task_on, p_actor);
END $$;

-- A cleaner's tap on a task message of the Staff bot (callback data "hk:done:<task>",
-- "hk:skip:<task>" or "hk:no1:<task>" to "hk:no3:<task>"). Cleaned finishes the task; Not cleaned
-- asks why with three fixed reasons; a reason finishes it as not cleaned. Only the cleaner the
-- task is given to may tap. Each answer goes once for the inbound tap.
CREATE FUNCTION app.telegram_staff_task_tap(p_property uuid, p_inbound text, p_user bigint,
    p_chat bigint, p_data text, p_service uuid, p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_day date;
    v_parts text[];
    v_task app.housekeeping_tasks;
    v_employee uuid;
    v_unit text;
    v_result text;
    v_code text;
    v_buttons jsonb;
    v_note text;
BEGIN
    PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
    v_day := app.hr_require_service(p_service, p_property);
    IF p_inbound IS NULL OR p_inbound !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'
        OR p_user IS NULL OR p_user <= 0 OR p_chat IS NULL OR p_chat = 0 THEN
        RAISE EXCEPTION 'the tap is not valid' USING ERRCODE = '22023';
    END IF;
    v_parts := regexp_match(COALESCE(p_data, ''),
        '^hk:(done|skip|no1|no2|no3):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$');
    IF v_parts IS NULL THEN
        RETURN jsonb_build_object('result', 'NOT_A_TASK');
    END IF;
    SELECT link.employee_id INTO v_employee
    FROM app.employee_telegram_links AS link
    JOIN app.employees AS employee ON employee.id = link.employee_id
    WHERE link.telegram_user_id = p_user AND employee.property_id = p_property
      AND app.hr_link_live(link.id, v_day)
    LIMIT 1;
    SELECT task.* INTO v_task FROM app.housekeeping_tasks AS task
    WHERE task.id = v_parts[2]::uuid AND task.property_id = p_property FOR UPDATE;
    SELECT unit.unit_number INTO v_unit FROM app.units AS unit WHERE unit.id = v_task.unit_id;
    IF v_task.id IS NULL OR v_employee IS NULL
        OR v_task.assigned_to IS DISTINCT FROM v_employee OR v_task.kind = 'ROOM_CHECK' THEN
        v_result := 'NOT_YOURS';
        v_code := 'staff.task_not_yours';
    ELSIF v_task.status <> 'TO_DO' THEN
        v_result := 'CLOSED';
        v_code := 'staff.task_closed';
    ELSIF v_task.task_on > v_day THEN
        v_result := 'NOT_DUE';
        v_code := 'staff.task_not_due';
    ELSIF v_parts[1] = 'skip' THEN
        v_result := 'ASKED_WHY';
        v_code := 'staff.task_why';
        v_buttons := jsonb_build_array(
            jsonb_build_array(jsonb_build_object('text', 'ភ្ញៀវមិនចង់ឱ្យសម្អាត',
                'callback_data', 'hk:no1:' || v_task.id)),
            jsonb_build_array(jsonb_build_object('text', 'ភ្ញៀវមិនបើកទ្វារ',
                'callback_data', 'hk:no2:' || v_task.id)),
            jsonb_build_array(jsonb_build_object('text', 'មានស្លាក «កុំរំខាន»',
                'callback_data', 'hk:no3:' || v_task.id)));
    ELSE
        -- The reason is kept in English for the office, as typed in the app.
        v_note := CASE v_parts[1]
            WHEN 'no1' THEN 'Guest asked: no cleaning today'
            WHEN 'no2' THEN 'Guest did not open the door'
            WHEN 'no3' THEN 'Do not disturb sign on the door' END;
        UPDATE app.housekeeping_tasks AS task
        SET status = CASE WHEN v_note IS NULL THEN 'DONE' ELSE 'SKIPPED' END, note = v_note,
            done_at = statement_timestamp(), done_by = p_service, done_by_employee = v_employee,
            version = task.version + 1
        WHERE task.id = v_task.id;
        PERFORM app.product_audit(p_property, p_service, v_day, 'short_stay.cleaned',
            'housekeeping_task', v_task.id, 'Housekeeping task finished in the Staff bot',
            'short_stays.housekeeping', jsonb_build_object('status', 'TO_DO'),
            jsonb_build_object('status', CASE WHEN v_note IS NULL THEN 'DONE' ELSE 'SKIPPED' END,
                'done_by_employee', v_employee), NULL);
        v_result := CASE WHEN v_note IS NULL THEN 'DONE' ELSE 'SKIPPED' END;
        v_code := CASE WHEN v_note IS NULL THEN 'staff.task_done' ELSE 'staff.task_skipped' END;
    END IF;
    PERFORM app.telegram_queue_once(p_property, 'STAFF', p_chat, v_code, 'km',
        jsonb_build_object('unit', COALESCE(v_unit, '')), v_buttons, NULL,
        'reply:' || p_inbound || ':' || 1, p_actor);
    RETURN jsonb_build_object('result', v_result, 'task_id', v_task.id);
END $$;
"""

ACTIONS = (
    "app.assign_housekeeping_task(uuid, uuid, jsonb, uuid, uuid)",
    "app.telegram_staff_task_tap(uuid, text, bigint, bigint, text, uuid, uuid)",
)


def upgrade() -> None:
    op.execute(TABLE)
    op.execute(FUNCTIONS)
    for signature in ACTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
