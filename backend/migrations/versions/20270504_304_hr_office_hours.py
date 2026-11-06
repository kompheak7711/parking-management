# ruff: noqa: E501
"""HRIS: ID details at hiring, office hours, and days off per job (owner 2026-11-06).

1. Add employee needs the ID type (ID card or passport), the ID number, the date of birth, the
   home address and a photo or scan of the ID card or passport (owner 09:05). The API saves the
   file first and the employee, the ID details and the ID document are written in one
   transaction. Whoever may add an employee (hr.employees.manage) enters them; seeing them later
   and changing them stays with the salary right. An employee is at least 15 years old on the
   start date (Labour Law Art. 177). Owner 10:45: the place of birth is kept and asked for too.
2. Only the Property caretaker works shifts (app.shift_job_titles). Every other job works the
   new OFFICE hours, 07:00-11:00 and 13:00-17:00 (Late counts from 07:00).
3. Days off (owner 10:24): the Property caretaker and the cleaner have no usual day off; they
   take 2 days off a month when they ask, marked on the Weekly plan
   (app.monthly_day_off_job_titles). Every other job, the technician too, keeps one usual day
   off a week. The owner chose no warning for a week without a rest day (decision 10:13) and
   gets the Labour Ministry's written OK himself; the Weekly plan shows how many days off each
   month has, against the 2.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270504_304"
down_revision: str | None = "20270503_303"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


TABLES = """
    -- Owner 10:45: the place of birth, as on the ID card or passport. Older records have none.
    ALTER TABLE app.employee_identity_records ADD COLUMN place_of_birth text
        CHECK (place_of_birth = btrim(place_of_birth) AND length(place_of_birth) BETWEEN 1 AND 200);
    ALTER TABLE app.work_shifts DROP CONSTRAINT work_shifts_code_check;
    ALTER TABLE app.work_shifts ADD CONSTRAINT work_shifts_code_check
        CHECK (code IN ('MORNING', 'AFTERNOON', 'NIGHT', 'OFFICE'));
    ALTER TABLE app.work_shifts ADD COLUMN break_starts_at time, ADD COLUMN break_ends_at time,
        ADD CONSTRAINT work_shifts_break_check CHECK ((break_starts_at IS NULL) = (break_ends_at IS NULL)
            AND (break_starts_at IS NULL OR (break_starts_at > starts_at
                AND break_ends_at > break_starts_at AND ends_at > break_ends_at)));
    INSERT INTO app.work_shifts (code, starts_at, ends_at, break_starts_at, break_ends_at,
        name_en, name_km, sort_order)
    VALUES ('OFFICE', TIME '07:00', TIME '17:00', TIME '11:00', TIME '13:00', 'Office hours',
        'ម៉ោងការិយាល័យ', 4);
    COMMENT ON COLUMN app.work_shifts.break_starts_at IS
        'The unpaid break inside the hours (OFFICE: 11:00-13:00).';

    -- Only these jobs work shifts and have no usual day off; the others work OFFICE hours.
    CREATE TABLE app.shift_job_titles (
        job_title_id uuid PRIMARY KEY REFERENCES app.job_titles (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT statement_timestamp()
    );
    INSERT INTO app.shift_job_titles (job_title_id)
    SELECT title.id FROM app.job_titles AS title WHERE title.code = 'CARETAKER';
    CREATE TRIGGER shift_job_titles_append_only BEFORE UPDATE OR DELETE ON app.shift_job_titles
        FOR EACH ROW EXECUTE FUNCTION app.reject_hr_change();
    CREATE TRIGGER shift_job_titles_no_truncate BEFORE TRUNCATE ON app.shift_job_titles
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_hr_change();
    REVOKE ALL ON TABLE app.shift_job_titles FROM PUBLIC;
    GRANT SELECT ON TABLE app.shift_job_titles TO prm_runtime;

    CREATE FUNCTION app.hr_uses_shifts(p_title uuid) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT EXISTS (SELECT 1 FROM app.shift_job_titles AS shift_job
            WHERE shift_job.job_title_id = p_title)
    $$;
    REVOKE ALL ON FUNCTION app.hr_uses_shifts(uuid) FROM PUBLIC;

    -- These jobs have no usual day off: they take this many days off a month on request.
    CREATE TABLE app.monthly_day_off_job_titles (
        job_title_id uuid PRIMARY KEY REFERENCES app.job_titles (id) ON DELETE RESTRICT,
        days_off_per_month smallint NOT NULL CHECK (days_off_per_month BETWEEN 1 AND 15),
        created_at timestamptz NOT NULL DEFAULT statement_timestamp()
    );
    INSERT INTO app.monthly_day_off_job_titles (job_title_id, days_off_per_month)
    SELECT title.id, 2 FROM app.job_titles AS title WHERE title.code IN ('CARETAKER', 'CLEANER');
    CREATE TRIGGER monthly_day_off_job_titles_append_only
        BEFORE UPDATE OR DELETE ON app.monthly_day_off_job_titles
        FOR EACH ROW EXECUTE FUNCTION app.reject_hr_change();
    CREATE TRIGGER monthly_day_off_job_titles_no_truncate
        BEFORE TRUNCATE ON app.monthly_day_off_job_titles
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_hr_change();
    REVOKE ALL ON TABLE app.monthly_day_off_job_titles FROM PUBLIC;
    GRANT SELECT ON TABLE app.monthly_day_off_job_titles TO prm_runtime;

    CREATE FUNCTION app.hr_monthly_days_off(p_title uuid) RETURNS smallint
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT rule.days_off_per_month FROM app.monthly_day_off_job_titles AS rule
        WHERE rule.job_title_id = p_title
    $$;
    REVOKE ALL ON FUNCTION app.hr_monthly_days_off(uuid) FROM PUBLIC;

    -- A job with days off a month on request has no usual day off.
    ALTER TABLE app.employment_events DROP CONSTRAINT employment_events_shape;
    ALTER TABLE app.employment_events ADD CONSTRAINT employment_events_shape CHECK (
        (event_type = 'LEFT' AND job_title_id IS NULL AND shift_code IS NULL
            AND usual_day_off IS NULL)
        OR (event_type <> 'LEFT' AND job_title_id IS NOT NULL AND shift_code IS NOT NULL));
"""

FUNCTIONS = """
    -- Job, shift and day off from a form; the old values fill what the form leaves out. A job
    -- that works shifts takes one of the three shifts, any other job works OFFICE hours; a job
    -- with days off a month on request has no usual day off, any other job needs one.
    CREATE OR REPLACE FUNCTION app.hr_job_from(p_body jsonb, p_old_title uuid, p_old_shift text,
        p_old_day smallint) RETURNS TABLE (job_title_id uuid, shift_code text, usual_day_off smallint)
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_title uuid := coalesce(app.hr_uuid(p_body, 'job_title_id', 'Choose the job'), p_old_title);
        v_shift text := app.problem_text(p_body, 'shift_code', 20, 'Choose the shift');
        v_shifts boolean;
        v_monthly smallint;
        v_day smallint;
    BEGIN
        BEGIN
            v_day := coalesce((p_body ->> 'usual_day_off')::smallint, p_old_day);
        EXCEPTION WHEN data_exception THEN
            RAISE EXCEPTION 'Choose the usual day off' USING ERRCODE = '22023';
        END;
        SELECT app.hr_uses_shifts(title.id) INTO v_shifts FROM app.job_titles AS title
        WHERE title.id = v_title AND (title.active OR title.id = p_old_title);
        IF v_title IS NULL OR v_shifts IS NULL THEN
            RAISE EXCEPTION 'Choose the job' USING ERRCODE = '22023';
        END IF;
        v_monthly := app.hr_monthly_days_off(v_title);
        IF v_monthly IS NOT NULL THEN
            v_day := NULL;
        ELSIF v_day IS NULL OR v_day NOT BETWEEN 1 AND 7 THEN
            RAISE EXCEPTION 'Choose the usual day off' USING ERRCODE = '22023';
        END IF;
        IF NOT v_shifts THEN
            RETURN QUERY SELECT v_title, 'OFFICE'::text, v_day;
            RETURN;
        END IF;
        v_shift := coalesce(v_shift, CASE WHEN p_old_shift <> 'OFFICE' THEN p_old_shift END);
        IF v_shift IS NULL OR v_shift NOT IN ('MORNING', 'AFTERNOON', 'NIGHT') THEN
            RAISE EXCEPTION 'Choose the shift' USING ERRCODE = '22023';
        END IF;
        RETURN QUERY SELECT v_title, v_shift, v_day;
    END $$;

    -- The planned shift of a day: the weekly plan, else the usual shift and usual day off (a
    -- person without a usual day off works every day the plan does not mark).
    CREATE OR REPLACE FUNCTION app.hr_shift_on(p_employee uuid, p_day date)
    RETURNS TABLE (shift_code text, is_day_off boolean, planned boolean) ROWS 1
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT coalesce(plan.shift_code, CASE WHEN plan.id IS NULL
                AND job.usual_day_off IS DISTINCT FROM extract(isodow FROM p_day)
                THEN job.shift_code END),
            coalesce(plan.is_day_off, CASE WHEN job.job_title_id IS NOT NULL
                THEN job.usual_day_off IS NOT DISTINCT FROM extract(isodow FROM p_day) END),
            plan.id IS NOT NULL
        FROM (SELECT 1) AS one
        LEFT JOIN LATERAL app.hr_job_on(p_employee, p_day) AS job ON true
        LEFT JOIN LATERAL (SELECT entry.* FROM app.shift_plan_entries AS entry
            WHERE entry.employee_id = p_employee AND entry.work_date = p_day
            ORDER BY entry.created_at DESC LIMIT 1) AS plan ON true
    $$;

    -- The planned days off of one person in the month of p_month, while employed.
    CREATE FUNCTION app.hr_month_days_off(p_employee uuid, p_month date) RETURNS integer
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT count(*)::integer
        FROM generate_series(date_trunc('month', p_month)::date,
            (date_trunc('month', p_month) + interval '1 month - 1 day')::date,
            interval '1 day') AS day
        CROSS JOIN LATERAL app.hr_shift_on(p_employee, day::date) AS plan
        WHERE plan.is_day_off AND app.hr_works_on(p_employee, day::date)
    $$;
    REVOKE ALL ON FUNCTION app.hr_month_days_off(uuid, date) FROM PUBLIC;
"""

SHIFT_LIST_BEFORE = "'name_en', shift.name_en, 'name_km', shift.name_km) ORDER BY shift.sort_order)"
SHIFT_LIST_AFTER = (
    "'name_en', shift.name_en, 'name_km', shift.name_km,\n"
    "                    'break_starts_at', to_char(shift.break_starts_at, 'HH24:MI'),\n"
    "                    'break_ends_at', to_char(shift.break_ends_at, 'HH24:MI'))\n"
    "                    ORDER BY shift.sort_order)"
)

ADD_EMPLOYEE = "app.hr_add_employee(uuid, jsonb, uuid, uuid)"
ADD_EMPLOYEE_PATCHES = (
    (
        """        IF (p_body ? 'pay' AND jsonb_typeof(p_body -> 'pay') = 'object'
                OR p_body ? 'identity' AND jsonb_typeof(p_body -> 'identity') = 'object')
            AND NOT app.hr_can(p_actor, p_property, 'hr.salaries.manage') THEN
            RAISE EXCEPTION 'Only someone with See salaries adds the salary and ID details'
                USING ERRCODE = '42501';
        END IF;""",
        """        IF p_body ? 'pay' AND jsonb_typeof(p_body -> 'pay') = 'object'
            AND NOT app.hr_can(p_actor, p_property, 'hr.salaries.manage') THEN
            RAISE EXCEPTION 'Only someone with See salaries adds the salary'
                USING ERRCODE = '42501';
        END IF;
        -- Owner 06/11: the ID details and a photo of the ID come with every new employee.
        IF jsonb_typeof(p_body -> 'identity') IS DISTINCT FROM 'object'
                OR coalesce(p_body #>> '{identity,id_type}', '') NOT IN ('NATIONAL_ID', 'PASSPORT') THEN
            RAISE EXCEPTION 'Choose ID card or passport' USING ERRCODE = '22023';
        END IF;
        IF nullif(btrim(coalesce(p_body #>> '{identity,id_number}', '')), '') IS NULL THEN
            RAISE EXCEPTION 'Enter the ID number' USING ERRCODE = '22023';
        END IF;
        IF nullif(btrim(coalesce(p_body #>> '{identity,home_address}', '')), '') IS NULL THEN
            RAISE EXCEPTION 'Enter the home address' USING ERRCODE = '22023';
        END IF;
        IF nullif(btrim(coalesce(p_body #>> '{identity,place_of_birth}', '')), '') IS NULL THEN
            RAISE EXCEPTION 'Enter the place of birth' USING ERRCODE = '22023';
        END IF;
        v_birth := app.hr_date(p_body -> 'identity', 'date_of_birth', 'The date of birth is not a date');
        IF v_birth IS NULL THEN
            RAISE EXCEPTION 'Enter the date of birth' USING ERRCODE = '22023';
        END IF;
        IF v_birth > v_start - interval '15 years' THEN
            RAISE EXCEPTION 'An employee is at least 15 years old on the start date'
                USING ERRCODE = '22023';
        END IF;
        IF jsonb_typeof(p_body -> 'id_document') IS DISTINCT FROM 'object'
                OR coalesce(p_body #>> '{id_document,storage_key}', '') = '' THEN
            RAISE EXCEPTION 'Add a photo of the ID card or passport' USING ERRCODE = '22023';
        END IF;""",
    ),
    (
        """        v_reason text;
    BEGIN""",
        """        v_reason text;
        v_birth date;
        v_file uuid := gen_random_uuid();
    BEGIN""",
    ),
    (
        """            PERFORM app.hr_add_identity(v_id, p_body -> 'identity', p_actor);
        END IF;""",
        """            PERFORM app.hr_add_identity(v_id, p_body -> 'identity', p_actor);
        END IF;
        INSERT INTO app.stored_files (id, property_id, sha256, byte_size, media_type,
            original_name, storage_key, created_by)
        VALUES (v_file, p_property, p_body #>> '{id_document,sha256}',
            (p_body #>> '{id_document,byte_size}')::bigint, p_body #>> '{id_document,media_type}',
            p_body #>> '{id_document,original_name}', p_body #>> '{id_document,storage_key}', p_actor);
        INSERT INTO app.employee_documents (employee_id, file_id, document_kind, title, created_by)
        VALUES (v_id, v_file, 'ID_CARD', CASE p_body #>> '{identity,id_type}'
            WHEN 'PASSPORT' THEN 'Passport' ELSE 'ID card' END, p_actor);""",
    ),
)

ADD_IDENTITY = "app.hr_add_identity(uuid, jsonb, uuid)"
ADD_IDENTITY_PATCHES = (
    (
        "            date_of_birth, home_address, created_by)",
        "            date_of_birth, home_address, place_of_birth, created_by)",
    ),
    (
        "            app.problem_text(p_body, 'home_address', 300, 'The address is at most 300 letters'),",
        "            app.problem_text(p_body, 'home_address', 300, 'The address is at most 300 letters'),\n"
        "            app.problem_text(p_body, 'place_of_birth', 200,\n"
        "                'The place of birth is at most 200 letters'),",
    ),
)

EMPLOYEE_READ = "app.hr_employee_read(uuid, uuid, uuid, uuid)"
EMPLOYEE_READ_PATCHES = (
    (
        "'date_of_birth', record.date_of_birth, 'home_address', record.home_address,",
        "'date_of_birth', record.date_of_birth, 'home_address', record.home_address,\n"
        "                    'place_of_birth', record.place_of_birth,",
    ),
)

STEP = "app.hr_employee_step(uuid, uuid, integer, text, jsonb, uuid, uuid)"
STEP_PATCHES = (
    (
        """            IF v_job.job_title_id = v_old.job_title_id AND v_job.shift_code = v_old.shift_code
                    AND v_job.usual_day_off = v_old.usual_day_off THEN""",
        """            IF v_job.job_title_id = v_old.job_title_id AND v_job.shift_code = v_old.shift_code
                    AND v_job.usual_day_off IS NOT DISTINCT FROM v_old.usual_day_off THEN""",
    ),
)

CHOICES = "app.hr_choices(uuid, uuid)"
CHOICES_PATCHES = (
    (
        "'code', title.code, 'name_en', title.name_en, 'name_km', title.name_km)",
        "'code', title.code, 'name_en', title.name_en, 'name_km', title.name_km,\n"
        "                    'uses_shifts', app.hr_uses_shifts(title.id),\n"
        "                    'days_off_per_month', app.hr_monthly_days_off(title.id))",
    ),
    (SHIFT_LIST_BEFORE, SHIFT_LIST_AFTER),
)

DAY = "app.hr_attendance_day(uuid, date, uuid)"
DAY_JSON = "app.hr_day_json(uuid, date, timestamptz)"
DAY_JSON_PATCHES = (
    (
        "'job_en', title.name_en, 'job_km', title.name_km,",
        "'job_en', title.name_en, 'job_km', title.name_km,\n"
        "            'uses_shifts', app.hr_uses_shifts(job.job_title_id),",
    ),
)

WEEK = "app.hr_attendance_week(uuid, date, uuid)"
WEEK_PATCHES = (
    (
        "'name_en', employee.name_en, 'name_km', employee.name_km,\n"
        "                    'days', (SELECT",
        "'name_en', employee.name_en, 'name_km', employee.name_km,\n"
        "                    'uses_shifts', coalesce((SELECT app.hr_uses_shifts(job.job_title_id)\n"
        "                        FROM app.hr_job_on(employee.id, v_monday + 6) AS job), false),\n"
        "                    'days_off_per_month', (SELECT app.hr_monthly_days_off(job.job_title_id)\n"
        "                        FROM app.hr_job_on(employee.id, v_monday + 6) AS job),\n"
        "                    'month_days_off', (SELECT jsonb_agg(jsonb_build_object('month', month,\n"
        "                            'planned', app.hr_month_days_off(employee.id, month)) ORDER BY month)\n"
        "                        FROM (SELECT DISTINCT date_trunc('month', v_monday + offset_days)::date\n"
        "                            AS month FROM generate_series(0, 6) AS offset_days) AS months),\n"
        "                    'days', (SELECT",
    ),
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    _patch(ADD_IDENTITY, ADD_IDENTITY_PATCHES)
    _patch(EMPLOYEE_READ, EMPLOYEE_READ_PATCHES)
    _patch(ADD_EMPLOYEE, ADD_EMPLOYEE_PATCHES)
    _patch(STEP, STEP_PATCHES)
    _patch(CHOICES, CHOICES_PATCHES)
    _patch(DAY, ((SHIFT_LIST_BEFORE, SHIFT_LIST_AFTER),))
    _patch(DAY_JSON, DAY_JSON_PATCHES)
    _patch(WEEK, WEEK_PATCHES)


def downgrade() -> None:
    raise RuntimeError("HRIS office hours migration is forward-only")
