"""Owner's choice of 16 Nov 2026, DL-242: Housekeeping tasks are given out by themselves, and the
cleaner reports every task, the Unit check too, in the Staff bot on Telegram.

The owner asked that the short-stay Unit check (until now "room check") be given to a cleaner by
itself, that staff may still change the cleaner, and that Cleaned and Not cleaned be reported by
the cleaner in the Telegram bot; the app shows only what happened. On the card "Choose how
cleaners get and report Housekeeping tasks" the owner chose "As I advise":

- Each new task goes to the cleaner with the fewest tasks that day. Staff can change it.
- The cleaner taps Cleaned or Not cleaned (a clean), Unit OK or Problem found (a Unit check).
- Problem found: the front desk writes the Problem report and the damage choice in the app, on the
  booking, as before (DL-222).

What this migration adds:

- ``app.housekeeping_tasks`` gets ``problem_found_at`` and ``problem_found_by`` (the cleaner who
  tapped Problem found on a Unit check still to do). Nothing is filled in for tasks made before.
- ``app.protect_short_stay_step`` also lets a task still to do take Problem found (only those two
  columns and its version change).
- ``app.housekeeping_task_buttons`` and ``app.housekeeping_send_task``: the Staff bot message of a
  task, with the buttons of its kind; a Unit check now has Unit OK and Problem found.
- ``app.assign_housekeeping_task`` (the front desk) sends the Unit check with its buttons.
- ``app.housekeeping_auto_assign`` (``telegram.operate``, run by the Telegram pull job): each task
  due today or late that was never given to anyone goes to the cleaner the Staff bot can reach
  who has the fewest tasks today (a tie goes by name), and the Staff bot tells them. A task staff
  gave to nobody stays with nobody. With no cleaner on Telegram the task waits for the desk.
- ``app.telegram_staff_task_tap``: Unit OK finishes the Unit check as the app's check with no
  problem does (the Unit is ready again, the booking History says Unit checked). Problem found
  keeps the task to do, marks it, and the booking History says so.
- ``app.short_stay_housekeeping`` gives ``problem_found_at`` and ``problem_found_by_name``.

No money, Invoice or Lease changes. Forward-only.

Revision ID: 20270804_415
Revises: 20270803_417
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270804_415"
down_revision: str | None = "20270803_417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = r"""
ALTER TABLE app.housekeeping_tasks
    ADD COLUMN problem_found_at timestamptz,
    ADD COLUMN problem_found_by uuid REFERENCES app.employees (id) ON DELETE RESTRICT,
    ADD CONSTRAINT housekeeping_tasks_problem_shape CHECK (
        (problem_found_at IS NULL) = (problem_found_by IS NULL)
        AND (problem_found_at IS NULL OR kind = 'ROOM_CHECK'));
"""

FUNCTIONS = r"""
-- The step guard of migration 20270725_410, unchanged except that a task still to do may also take
-- Problem found (only those columns and its version change).
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
    v_problem text[] := ARRAY['problem_found_at', 'problem_found_by', 'version'];
BEGIN
    IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'housekeeping_tasks'
        AND OLD.status = 'TO_DO' AND NEW.status = 'TO_DO'
        AND (v_new ->> 'version')::integer = (v_old ->> 'version')::integer + 1
        AND ((v_old - v_assign) = (v_new - v_assign)
             OR (v_old ->> 'problem_found_at' IS NULL
                 AND (v_old - v_problem) = (v_new - v_problem)))
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

-- The buttons of a task's Staff bot message: a clean has Cleaned and Not cleaned; a Unit check
-- has Unit OK and Problem found.
CREATE FUNCTION app.housekeeping_task_buttons(p_task uuid, p_kind text) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN p_kind = 'ROOM_CHECK' THEN jsonb_build_array(jsonb_build_array(
            jsonb_build_object('text', '✅ បន្ទប់ល្អ', 'callback_data', 'hk:ok:' || p_task),
            jsonb_build_object('text', '⚠️ មានបញ្ហា', 'callback_data', 'hk:bad:' || p_task)))
        ELSE jsonb_build_array(jsonb_build_array(
            jsonb_build_object('text', '✅ បានសម្អាត', 'callback_data', 'hk:done:' || p_task),
            jsonb_build_object('text', '❌ មិនបានសម្អាត', 'callback_data', 'hk:skip:' || p_task)))
        END
$$;
REVOKE ALL ON FUNCTION app.housekeeping_task_buttons(uuid, text) FROM PUBLIC;

-- The Staff bot tells the person a task is given to, once for this version of the task.
CREATE FUNCTION app.housekeeping_send_task(p_task uuid, p_day date, p_actor uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_task app.housekeeping_tasks;
    v_chat bigint;
    v_sent integer := 0;
BEGIN
    SELECT task.* INTO v_task FROM app.housekeeping_tasks AS task WHERE task.id = p_task;
    IF v_task.id IS NULL OR v_task.assigned_to IS NULL THEN
        RETURN 0;
    END IF;
    FOR v_chat IN SELECT chat FROM app.housekeeping_staff_chats(v_task.assigned_to, p_day) AS chat
    LOOP
        PERFORM app.telegram_queue_once(v_task.property_id, 'STAFF', v_chat, 'staff.task_given',
            'km', jsonb_build_object(
                'unit', (SELECT unit.unit_number FROM app.units AS unit
                    WHERE unit.id = v_task.unit_id),
                'task', app.housekeeping_kind_km(v_task.kind),
                'day', to_char(v_task.task_on, 'DD/MM/YYYY')),
            app.housekeeping_task_buttons(v_task.id, v_task.kind),
            NULL, 'hk-task:' || v_task.id || ':' || v_task.version, p_actor);
        v_sent := v_sent + 1;
    END LOOP;
    RETURN v_sent;
END $$;
REVOKE ALL ON FUNCTION app.housekeeping_send_task(uuid, date, uuid) FROM PUBLIC;

-- The Khmer name of a task kind, as the app's Khmer (frontend/src/shortstays/text.ts).
CREATE OR REPLACE FUNCTION app.housekeeping_kind_km(p_kind text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT CASE p_kind
        WHEN 'DAILY_CLEAN' THEN 'សម្អាតប្រចាំថ្ងៃ'
        WHEN 'CHANGE_OVER' THEN 'សម្អាតពេលប្ដូរភ្ញៀវ'
        ELSE 'ពិនិត្យបន្ទប់' END
$$;

-- The front desk gives a task still to do to one cleaner, to another, or to nobody, as in
-- migration 20270725_410; the Staff bot message now comes from app.housekeeping_send_task, so a
-- Unit check has its buttons too.
CREATE OR REPLACE FUNCTION app.assign_housekeeping_task(p_property uuid, p_task uuid,
    p_assign jsonb, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_task app.housekeeping_tasks;
    v_person uuid;
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
    PERFORM app.housekeeping_send_task(v_task.id, v_today, p_actor);
    RETURN app.short_stay_housekeeping(p_property, v_task.task_on, p_actor);
END $$;

-- DL-242: each task due today or late that was never given to anyone goes to the cleaner the
-- Staff bot can reach who has the fewest tasks today (to do or finished today, and late ones
-- still to do); a tie goes by name. Answers how many tasks were given.
CREATE FUNCTION app.housekeeping_auto_assign(p_property uuid, p_actor uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date;
    v_task app.housekeeping_tasks;
    v_person uuid;
    v_given integer := 0;
BEGIN
    PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
    v_today := app.gl_today(p_property);
    FOR v_task IN
        SELECT task.* FROM app.housekeeping_tasks AS task
        JOIN app.units AS unit ON unit.id = task.unit_id
        WHERE task.property_id = p_property AND task.status = 'TO_DO'
          AND task.assigned_at IS NULL AND task.task_on <= v_today
        ORDER BY task.task_on, unit.unit_number, task.kind, task.id
        FOR UPDATE OF task SKIP LOCKED
    LOOP
        SELECT (person.value ->> 'employee_id')::uuid INTO v_person
        FROM jsonb_array_elements(app.short_stay_cleaners(p_property, v_today))
            WITH ORDINALITY AS person (value, place)
        WHERE (person.value ->> 'telegram')::boolean
        ORDER BY (SELECT count(*) FROM app.housekeeping_tasks AS mine
                  WHERE mine.property_id = p_property
                    AND mine.assigned_to = (person.value ->> 'employee_id')::uuid
                    AND (mine.task_on = v_today
                         OR (mine.task_on < v_today AND mine.status = 'TO_DO'))),
            person.place
        LIMIT 1;
        IF v_person IS NULL THEN
            RETURN v_given;
        END IF;
        UPDATE app.housekeeping_tasks AS task
        SET assigned_to = v_person, assigned_at = statement_timestamp(), assigned_by = p_actor,
            version = task.version + 1
        WHERE task.id = v_task.id;
        PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.task_assigned',
            'housekeeping_task', v_task.id, 'Housekeeping task given to a cleaner by itself',
            'telegram.operate', jsonb_build_object('assigned_to', NULL),
            jsonb_build_object('assigned_to', v_person), NULL);
        PERFORM app.housekeeping_send_task(v_task.id, v_today, p_actor);
        v_given := v_given + 1;
    END LOOP;
    RETURN v_given;
END $$;

-- A cleaner's tap on a task message of the Staff bot. A clean: "hk:done:<task>",
-- "hk:skip:<task>", then "hk:no1:<task>" to "hk:no3:<task>" as in migration 20270725_410. A Unit
-- check (DL-242): "hk:ok:<task>" finishes it with no problem; "hk:bad:<task>" marks Problem found
-- and the front desk writes the problem on the booking. Only the cleaner the task is given to may
-- tap. Each answer goes once for the inbound tap.
CREATE OR REPLACE FUNCTION app.telegram_staff_task_tap(p_property uuid, p_inbound text,
    p_user bigint, p_chat bigint, p_data text, p_service uuid, p_actor uuid)
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
    v_check boolean;
BEGIN
    PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
    v_day := app.hr_require_service(p_service, p_property);
    IF p_inbound IS NULL OR p_inbound !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'
        OR p_user IS NULL OR p_user <= 0 OR p_chat IS NULL OR p_chat = 0 THEN
        RAISE EXCEPTION 'the tap is not valid' USING ERRCODE = '22023';
    END IF;
    v_parts := regexp_match(COALESCE(p_data, ''),
        '^hk:(done|skip|no1|no2|no3|ok|bad):'
        || '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$');
    IF v_parts IS NULL THEN
        RETURN jsonb_build_object('result', 'NOT_A_TASK');
    END IF;
    v_check := v_parts[1] IN ('ok', 'bad');
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
        OR v_task.assigned_to IS DISTINCT FROM v_employee
        OR (v_task.kind = 'ROOM_CHECK') <> v_check THEN
        v_result := 'NOT_YOURS';
        v_code := 'staff.task_not_yours';
    ELSIF v_task.status <> 'TO_DO' THEN
        v_result := 'CLOSED';
        v_code := 'staff.task_closed';
    ELSIF v_task.task_on > v_day THEN
        v_result := 'NOT_DUE';
        v_code := 'staff.task_not_due';
    ELSIF v_task.problem_found_at IS NOT NULL THEN
        -- Problem found is already with the front desk; they finish the Unit check.
        v_result := 'PROBLEM_FOUND';
        v_code := 'staff.unit_problem';
    ELSIF v_parts[1] = 'bad' THEN
        UPDATE app.housekeeping_tasks AS task
        SET problem_found_at = statement_timestamp(), problem_found_by = v_employee,
            version = task.version + 1
        WHERE task.id = v_task.id;
        IF v_task.booking_id IS NOT NULL THEN
            PERFORM app.short_stay_event(v_task.booking_id, 'UNIT_PROBLEM_FOUND', p_service, NULL,
                jsonb_build_object('employee_id', v_employee));
        END IF;
        PERFORM app.product_audit(p_property, p_service, v_day, 'short_stay.unit_problem_found',
            'housekeeping_task', v_task.id, 'Unit check: the cleaner found a problem',
            'short_stays.housekeeping', NULL,
            jsonb_build_object('problem_found_by', v_employee), NULL);
        v_result := 'PROBLEM_FOUND';
        v_code := 'staff.unit_problem';
    ELSIF v_parts[1] = 'ok' THEN
        IF v_task.booking_id IS NOT NULL THEN
            PERFORM 1 FROM app.short_stay_bookings AS booking
            WHERE booking.id = v_task.booking_id FOR UPDATE;
        END IF;
        UPDATE app.housekeeping_tasks AS task
        SET status = 'DONE', done_at = statement_timestamp(), done_by = p_service,
            done_by_employee = v_employee, version = task.version + 1
        WHERE task.id = v_task.id;
        -- As the app's Unit check with no problem: the Unit is ready again. A Unit names a user
        -- account as its last writer, so it is the Telegram jobs' account, not the HR service.
        UPDATE app.units AS unit
        SET status = 'VACANT', version = unit.version + 1, updated_at = statement_timestamp(),
            updated_by = p_actor
        WHERE unit.id = v_task.unit_id AND unit.status = 'CLEANING';
        IF v_task.booking_id IS NOT NULL THEN
            PERFORM app.short_stay_event(v_task.booking_id, 'ROOM_CHECKED', p_service, NULL,
                jsonb_build_object('employee_id', v_employee));
        END IF;
        PERFORM app.product_audit(p_property, p_service, v_day, 'short_stay.room_checked',
            'housekeeping_task', v_task.id, 'Unit checked in the Staff bot: no problem',
            'short_stays.housekeeping', NULL,
            jsonb_build_object('problems', 0, 'done_by_employee', v_employee), NULL);
        v_result := 'DONE';
        v_code := 'staff.unit_ok';
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
            'problem_found_at', task.problem_found_at, 'problem_found_by_name', finder.name_en,
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
        LEFT JOIN app.employees AS finder ON finder.id = task.problem_found_by
        WHERE task.property_id = p_property
          AND (task.task_on = p_day
               OR (p_day = v_today AND task.task_on < p_day AND task.status = 'TO_DO'))),
        '[]'::jsonb));
END $$;
"""


def upgrade() -> None:
    op.execute(TABLE)
    op.execute(FUNCTIONS)
    op.execute(
        "REVOKE ALL ON FUNCTION app.housekeeping_auto_assign(uuid, uuid) FROM PUBLIC; "
        "GRANT EXECUTE ON FUNCTION app.housekeeping_auto_assign(uuid, uuid) TO prm_runtime"
    )


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
