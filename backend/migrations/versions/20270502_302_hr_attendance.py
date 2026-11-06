# ruff: noqa: E501
"""HRIS phase 6 step 3: attendance, overtime and QR check-in (PR-HR-050..068).

1. Weekly plan: a shift or a day off per person per day (the newest row wins); without a row the
   usual shift and usual day off of the employment history apply.
2. Daily sheet: Worked (with check-in and check-out), Absent, Leave (Annual, Sick, Unpaid) or Day
   off. A fix is a new row that points to the row it replaces, with a reason. Late, No check-out
   and overtime hours are worked out when read, never stored, so a rule change counts from the
   next payroll. When the month's payroll is sent for approval, that month's sheet locks.
3. Overtime (OTyy000n) is asked before it is worked and decided by someone else.
4. QR check-in: printed QR codes at the Guard post and the Office (only their SHA-256 is kept),
   an employee card QR for each person, every accepted scan with its distance, Needs check and,
   for a card scan, the reason and the half-body photo. The staff bot calls
   app.record_staff_check_scan and app.record_card_check_scan as a service actor.
5. Thirteen business rules in the area Attendance (owner 02/11 21:06 and 03/11 04:09).
6. The payroll list takes "Days not worked" and "Overtime" from the sheet.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270502_302"
down_revision: str | None = "20270501_301"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_REASON = "First value: the owner's attendance rules (02/11 and 03/11/2026)"
RANGE = "app.business_rules_program_range()"
RANGE_BEFORE = "OR (v_code = 'LOAN_OPEN_MAX' AND NEW.value NOT BETWEEN 1 AND 5)"
# code, unit, value, lowest, highest, English, Khmer (mock-up brn_ATT_*; night hours are two rules)
RULES = (
    ("ATT_LATE_MIN", "MINUTES", 10, 0, 240, "Late after", "យឺតក្រោយ"),
    ("ATT_LATE_CUT", "YES_NO", 0, 0, 1, "Late cuts pay", "យឺតកាត់ប្រាក់ខែ"),
    ("ATT_ABS_CUT", "YES_NO", 1, 0, 1, "Absence cuts one day's pay", "អវត្តមានកាត់ប្រាក់ខែមួយថ្ងៃ"),
    ("ATT_OT_FIRST", "YES_NO", 1, 0, 1, "Overtime needs approval first", "ម៉ោងបន្ថែមត្រូវអនុម័តជាមុន"),
    ("ATT_OT_PCT", "PERCENT", 15000, 10000, 50000, "Overtime rate", "អត្រាម៉ោងបន្ថែម"),
    (
        "ATT_OT_NIGHT_PCT",
        "PERCENT",
        20000,
        10000,
        50000,
        "Night or day-off overtime rate",
        "អត្រាម៉ោងបន្ថែមពេលយប់ ឬថ្ងៃឈប់",
    ),
    ("ATT_NIGHT_START", "TIME_OF_DAY", 1320, 0, 1439, "Night hours start", "ម៉ោងយប់ចាប់ផ្ដើម"),
    ("ATT_NIGHT_END", "TIME_OF_DAY", 300, 0, 1439, "Night hours end", "ម៉ោងយប់បញ្ចប់"),
    ("ATT_HOURS", "HOURS", 208, 100, 400, "Hours for the hourly rate", "ម៉ោងសម្រាប់គិតអត្រាក្នុងមួយម៉ោង"),
    ("ATT_DAYS_OFF", "COUNT", 1, 0, 3, "Days off per week", "ថ្ងៃឈប់ក្នុងមួយសប្ដាហ៍"),
    ("ATT_QR_DIST", "METRES", 100, 10, 2000, "QR distance", "ចម្ងាយ QR"),
    ("ATT_QR_EARLY", "MINUTES", 30, 0, 240, "Earliest check-in", "ចុះចូលដំបូងបំផុត"),
    ("ATT_PHOTO_DAYS", "DAYS", 90, 1, 3650, "Card photos kept", "រក្សារូបថតកាត"),
)
RANGE_AFTER = RANGE_BEFORE + "".join(
    f"\n                OR (v_code = '{code}' AND NEW.value NOT BETWEEN {low} AND {high})"
    for code, _, _, low, high, _, _ in RULES
)
# code, English, Khmer (owner Q1 03/11/2026 04:09: Guard post and Office)
PLACES = (("GUARD_POST", "Guard post", "ប៉ុស្តិ៍យាម"), ("OFFICE", "Office", "ការិយាល័យ"))


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


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
    CREATE TABLE app.shift_plan_entries (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        work_date date NOT NULL,
        shift_code text REFERENCES app.work_shifts (code) ON DELETE RESTRICT,
        is_day_off boolean NOT NULL,
        reason text CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT shift_plan_entries_shape CHECK (is_day_off = (shift_code IS NULL))
    );
    CREATE INDEX shift_plan_entries_day_idx
        ON app.shift_plan_entries (employee_id, work_date, created_at DESC);

    -- Places with a printed QR. The pin is set later by the Owner (a new row of
    -- attendance_place_pins); without a pin every phone scan there shows Needs check.
    CREATE TABLE app.attendance_places (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z][A-Z_]{1,40}$'),
        name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 80),
        name_km text NOT NULL CHECK (name_km = btrim(name_km) AND length(name_km) BETWEEN 1 AND 80),
        sort_order smallint NOT NULL UNIQUE CHECK (sort_order > 0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE TABLE app.attendance_place_pins (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        place_id uuid NOT NULL REFERENCES app.attendance_places (id) ON DELETE RESTRICT,
        latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
        longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX attendance_place_pins_place_idx ON app.attendance_place_pins (place_id, created_at DESC);
    CREATE TABLE app.attendance_place_qr_codes (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        place_id uuid NOT NULL REFERENCES app.attendance_places (id) ON DELETE RESTRICT,
        code_sha256 bytea NOT NULL UNIQUE CHECK (length(code_sha256) = 32),
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX attendance_place_qr_codes_place_idx
        ON app.attendance_place_qr_codes (place_id, created_at DESC);
    CREATE TABLE app.employee_card_qr_codes (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        code_sha256 bytea NOT NULL UNIQUE CHECK (length(code_sha256) = 32),
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX employee_card_qr_codes_employee_idx
        ON app.employee_card_qr_codes (employee_id, created_at DESC);

    -- Every accepted scan. A refused scan (too early, old QR, Location off) is not saved.
    CREATE TABLE app.attendance_scans (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        work_date date NOT NULL,
        direction text NOT NULL CHECK (direction IN ('IN', 'OUT')),
        method text NOT NULL CHECK (method IN ('PHONE', 'CARD')),
        place_id uuid REFERENCES app.attendance_places (id) ON DELETE RESTRICT,
        scanned_at timestamptz NOT NULL,
        phone_time timestamptz,
        distance_m integer CHECK (distance_m >= 0),
        needs_check boolean NOT NULL,
        card_reason text CHECK (card_reason IN ('NO_PHONE', 'PHONE_BROKEN', 'PHONE_LOST',
            'PHONE_STOLEN', 'OTHER')),
        card_reason_text text CHECK (card_reason_text = btrim(card_reason_text)
            AND length(card_reason_text) BETWEEN 1 AND 300),
        photo_file_id uuid UNIQUE REFERENCES app.stored_files (id) ON DELETE RESTRICT,
        scanned_by_employee_id uuid REFERENCES app.employees (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT attendance_scans_phone CHECK (method = 'CARD' OR (place_id IS NOT NULL
            AND card_reason IS NULL AND photo_file_id IS NULL AND scanned_by_employee_id IS NULL)),
        CONSTRAINT attendance_scans_card CHECK (method = 'PHONE' OR (card_reason IS NOT NULL
            AND photo_file_id IS NOT NULL AND scanned_by_employee_id IS NOT NULL
            AND scanned_by_employee_id <> employee_id)),
        CONSTRAINT attendance_scans_other CHECK (card_reason IS DISTINCT FROM 'OTHER'
            OR card_reason_text IS NOT NULL)
    );
    CREATE INDEX attendance_scans_employee_idx ON app.attendance_scans (employee_id, work_date);
    CREATE TABLE app.attendance_scan_acceptances (
        scan_id uuid PRIMARY KEY REFERENCES app.attendance_scans (id) ON DELETE RESTRICT,
        note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );

    -- The daily sheet: the newest row for a person and a day wins; a fix points to the row it
    -- replaces and has a reason.
    CREATE TABLE app.attendance_entries (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        work_date date NOT NULL,
        shift_code text REFERENCES app.work_shifts (code) ON DELETE RESTRICT,
        status text NOT NULL CHECK (status IN ('WORKED', 'ABSENT', 'LEAVE_ANNUAL', 'LEAVE_SICK',
            'LEAVE_UNPAID', 'DAY_OFF')),
        check_in_at timestamptz,
        check_out_at timestamptz,
        source text NOT NULL CHECK (source IN ('MANUAL', 'QR_PHONE', 'QR_CARD')),
        check_in_scan_id uuid REFERENCES app.attendance_scans (id) ON DELETE RESTRICT,
        check_out_scan_id uuid REFERENCES app.attendance_scans (id) ON DELETE RESTRICT,
        replaces_id uuid UNIQUE REFERENCES app.attendance_entries (id) ON DELETE RESTRICT,
        reason text CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT attendance_entries_times CHECK ((status = 'WORKED') = (check_in_at IS NOT NULL)
            AND (check_out_at IS NULL OR (check_in_at IS NOT NULL AND check_out_at > check_in_at))),
        CONSTRAINT attendance_entries_fix CHECK (source <> 'MANUAL' OR reason IS NOT NULL)
    );
    CREATE INDEX attendance_entries_day_idx
        ON app.attendance_entries (employee_id, work_date, created_at DESC);

    CREATE TABLE app.overtime_requests (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        overtime_number text NOT NULL UNIQUE CHECK (overtime_number ~ '^[A-Z]{2,5}[0-9]{6,}$'),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        work_date date NOT NULL,
        starts_at timestamptz NOT NULL,
        ends_at timestamptz NOT NULL,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT overtime_requests_times CHECK (ends_at > starts_at
            AND ends_at <= starts_at + interval '16 hours')
    );
    CREATE INDEX overtime_requests_employee_idx ON app.overtime_requests (employee_id, work_date);
    CREATE TABLE app.overtime_decisions (
        overtime_request_id uuid PRIMARY KEY REFERENCES app.overtime_requests (id) ON DELETE RESTRICT,
        decision text NOT NULL CHECK (decision IN ('APPROVED', 'REFUSED')),
        reason text CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        own_request_note text CHECK (own_request_note = btrim(own_request_note)
            AND length(own_request_note) BETWEEN 1 AND 500),
        decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        decided_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT overtime_decisions_refusal CHECK (decision = 'APPROVED' OR reason IS NOT NULL)
    );

    -- A card photo's file is removed after the rule "Card photos kept"; the scan row stays.
    CREATE TABLE app.stored_file_removals (
        file_id uuid PRIMARY KEY REFERENCES app.stored_files (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        removed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        removed_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
"""

APPEND_ONLY = (
    "shift_plan_entries",
    "attendance_places",
    "attendance_place_pins",
    "attendance_place_qr_codes",
    "employee_card_qr_codes",
    "attendance_scans",
    "attendance_scan_acceptances",
    "attendance_entries",
    "overtime_requests",
    "overtime_decisions",
    "stored_file_removals",
)

FUNCTIONS = """
    -- One-row helpers say so, so the planner does not expect 1000 rows per call and turn on JIT.
    ALTER FUNCTION app.hr_job_on(uuid, date) ROWS 1;

    CREATE FUNCTION app.hr_rule(p_code text, p_day date, p_default numeric) RETURNS numeric
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT coalesce(app.business_rule_value(p_code, p_day)::numeric, p_default)
    $$;
    REVOKE ALL ON FUNCTION app.hr_rule(text, date, numeric) FROM PUBLIC;

    CREATE FUNCTION app.hr_zone() RETURNS text
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT coalesce((SELECT property.timezone_name FROM app.properties AS property LIMIT 1),
            'Asia/Phnom_Penh')
    $$;
    REVOKE ALL ON FUNCTION app.hr_zone() FROM PUBLIC;

    -- PR-HR-059: a month locks when its REGULAR payroll is sent for approval.
    CREATE FUNCTION app.hr_month_locked(p_property uuid, p_day date) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT EXISTS (SELECT 1 FROM app.payroll_runs AS run
            WHERE run.property_id = p_property AND run.run_kind = 'REGULAR'
              AND run.salary_month = date_trunc('month', p_day)::date
              AND app.hr_payroll_state(run.id) IN ('SENT_FOR_APPROVAL', 'APPROVED'))
    $$;
    REVOKE ALL ON FUNCTION app.hr_month_locked(uuid, date) FROM PUBLIC;

    CREATE FUNCTION app.hr_attendance_lock() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE v_property uuid;
    BEGIN
        SELECT employee.property_id INTO STRICT v_property FROM app.employees AS employee
        WHERE employee.id = NEW.employee_id;
        IF app.hr_month_locked(v_property, NEW.work_date) THEN
            RAISE EXCEPTION 'The payroll for this month is sent: attendance is locked'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_attendance_lock() FROM PUBLIC;

    -- The planned shift of a day: the weekly plan, else the usual shift and usual day off.
    CREATE FUNCTION app.hr_shift_on(p_employee uuid, p_day date)
    RETURNS TABLE (shift_code text, is_day_off boolean, planned boolean) ROWS 1
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT coalesce(plan.shift_code, CASE WHEN plan.id IS NULL
                AND extract(isodow FROM p_day) <> job.usual_day_off THEN job.shift_code END),
            coalesce(plan.is_day_off, extract(isodow FROM p_day) = job.usual_day_off),
            plan.id IS NOT NULL
        FROM (SELECT 1) AS one
        LEFT JOIN LATERAL app.hr_job_on(p_employee, p_day) AS job ON true
        LEFT JOIN LATERAL (SELECT entry.* FROM app.shift_plan_entries AS entry
            WHERE entry.employee_id = p_employee AND entry.work_date = p_day
            ORDER BY entry.created_at DESC LIMIT 1) AS plan ON true
    $$;
    REVOKE ALL ON FUNCTION app.hr_shift_on(uuid, date) FROM PUBLIC;

    -- When a shift starts and ends on a day (a Night shift ends the next day).
    CREATE FUNCTION app.hr_shift_times(p_shift text, p_day date)
    RETURNS TABLE (starts_at timestamptz, ends_at timestamptz) ROWS 1
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT timezone(app.hr_zone(), p_day + shift.starts_at),
            timezone(app.hr_zone(), p_day + shift.ends_at
                + CASE WHEN shift.ends_at <= shift.starts_at THEN interval '1 day'
                    ELSE interval '0' END)
        FROM app.work_shifts AS shift WHERE shift.code = p_shift
    $$;
    REVOKE ALL ON FUNCTION app.hr_shift_times(text, date) FROM PUBLIC;

    CREATE FUNCTION app.hr_entry_on(p_employee uuid, p_day date) RETURNS app.attendance_entries
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT entry.* FROM app.attendance_entries AS entry
        WHERE entry.employee_id = p_employee AND entry.work_date = p_day
        ORDER BY entry.created_at DESC LIMIT 1
    $$;
    REVOKE ALL ON FUNCTION app.hr_entry_on(uuid, date) FROM PUBLIC;

    -- The day's line for one person: plan, sheet, Late, No check-out, Needs check (PR-HR-050).
    CREATE FUNCTION app.hr_day_json(p_employee uuid, p_day date, p_now timestamptz) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object(
            'employee_id', employee.id, 'employee_code', employee.employee_code,
            'name_en', employee.name_en, 'name_km', employee.name_km,
            'job_en', title.name_en, 'job_km', title.name_km,
            'planned_shift', plan.shift_code, 'day_off', plan.is_day_off,
            'entry_id', entry.id, 'shift_code', coalesce(entry.shift_code, plan.shift_code),
            'status', entry.status, 'check_in_at', entry.check_in_at,
            'check_out_at', entry.check_out_at, 'source', entry.source,
            'reason', entry.reason, 'fixed', entry.replaces_id IS NOT NULL,
            'late_minutes', CASE WHEN entry.status = 'WORKED' AND times.starts_at IS NOT NULL
                AND entry.check_in_at > times.starts_at + make_interval(mins =>
                    app.hr_rule('ATT_LATE_MIN', p_day, 10)::integer)
                THEN floor(extract(epoch FROM entry.check_in_at - times.starts_at) / 60)::integer END,
            'no_check_out', entry.status = 'WORKED' AND entry.check_out_at IS NULL
                AND times.ends_at IS NOT NULL AND p_now > times.ends_at,
            'scans', coalesce((SELECT jsonb_agg(jsonb_build_object('scan_id', scan.id,
                    'direction', scan.direction, 'method', scan.method,
                    'place_en', place.name_en, 'place_km', place.name_km,
                    'scanned_at', scan.scanned_at, 'distance_m', scan.distance_m,
                    'needs_check', scan.needs_check AND accepted.scan_id IS NULL,
                    'accepted', accepted.scan_id IS NOT NULL,
                    'card_reason', scan.card_reason, 'card_reason_text', scan.card_reason_text,
                    'has_photo', scan.photo_file_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM app.stored_file_removals AS removal
                        WHERE removal.file_id = scan.photo_file_id),
                    'scanned_by_en', scanner.name_en, 'scanned_by_km', scanner.name_km)
                    ORDER BY scan.scanned_at)
                FROM app.attendance_scans AS scan
                LEFT JOIN app.attendance_places AS place ON place.id = scan.place_id
                LEFT JOIN app.employees AS scanner ON scanner.id = scan.scanned_by_employee_id
                LEFT JOIN app.attendance_scan_acceptances AS accepted ON accepted.scan_id = scan.id
                WHERE scan.employee_id = employee.id AND scan.work_date = p_day), '[]'::jsonb))
        FROM app.employees AS employee
        LEFT JOIN LATERAL app.hr_job_on(employee.id, p_day) AS job ON true
        LEFT JOIN app.job_titles AS title ON title.id = job.job_title_id
        LEFT JOIN LATERAL app.hr_shift_on(employee.id, p_day) AS plan ON true
        LEFT JOIN LATERAL app.hr_entry_on(employee.id, p_day) AS entry ON true
        LEFT JOIN LATERAL app.hr_shift_times(coalesce(entry.shift_code, plan.shift_code), p_day)
            AS times ON true
        WHERE employee.id = p_employee
    $$;
    REVOKE ALL ON FUNCTION app.hr_day_json(uuid, date, timestamptz) FROM PUBLIC;

    CREATE FUNCTION app.hr_attendance_day(p_property uuid, p_day date, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog SET jit = off AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.read', p_property);
        v_day date := coalesce(p_day, v_today);
    BEGIN
        RETURN jsonb_build_object(
            'day', v_day, 'today', v_today,
            'locked', app.hr_month_locked(p_property, v_day),
            'can_manage', app.hr_can(p_actor, p_property, 'hr.attendance.manage'),
            'shifts', (SELECT jsonb_agg(jsonb_build_object('code', shift.code,
                    'starts_at', to_char(shift.starts_at, 'HH24:MI'),
                    'ends_at', to_char(shift.ends_at, 'HH24:MI'),
                    'name_en', shift.name_en, 'name_km', shift.name_km) ORDER BY shift.sort_order)
                FROM app.work_shifts AS shift),
            'people', coalesce((SELECT jsonb_agg(app.hr_day_json(employee.id, v_day,
                    statement_timestamp()) ORDER BY employee.employee_code)
                FROM app.employees AS employee
                WHERE employee.property_id = p_property AND app.hr_works_on(employee.id, v_day)),
                '[]'::jsonb));
    END $$;

    CREATE FUNCTION app.hr_attendance_week(p_property uuid, p_monday date, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog SET jit = off AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.read', p_property);
        v_monday date := coalesce(p_monday, v_today)
            - (extract(isodow FROM coalesce(p_monday, v_today))::integer - 1);
    BEGIN
        RETURN jsonb_build_object(
            'monday', v_monday,
            'days_off_per_week', app.hr_rule('ATT_DAYS_OFF', v_monday, 1),
            'people', coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'employee_id', employee.id, 'employee_code', employee.employee_code,
                    'name_en', employee.name_en, 'name_km', employee.name_km,
                    'days', (SELECT jsonb_agg(jsonb_build_object('work_date', day::date,
                            'works', app.hr_works_on(employee.id, day::date),
                            'shift_code', plan.shift_code, 'day_off', plan.is_day_off,
                            'planned', plan.planned) ORDER BY day)
                        FROM generate_series(v_monday, v_monday + 6, interval '1 day') AS day
                        CROSS JOIN LATERAL app.hr_shift_on(employee.id, day::date) AS plan))
                    ORDER BY employee.employee_code)
                FROM app.employees AS employee
                WHERE employee.property_id = p_property
                  AND app.hr_hired_on(employee.id) <= v_monday + 6
                  AND coalesce(app.hr_left_on(employee.id), v_monday) >= v_monday), '[]'::jsonb));
    END $$;

    -- Overtime hours of a request at the normal rate and at the night or day-off rate.
    CREATE FUNCTION app.hr_overtime_hours(p_request uuid)
    RETURNS TABLE (normal_hours numeric, night_hours numeric) ROWS 1
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        WITH request AS (
            SELECT ot.*, (SELECT plan.is_day_off FROM app.hr_shift_on(ot.employee_id,
                    ot.work_date) AS plan) AS day_off,
                app.hr_rule('ATT_NIGHT_START', ot.work_date, 1320)::integer AS night_start,
                app.hr_rule('ATT_NIGHT_END', ot.work_date, 300)::integer AS night_end
            FROM app.overtime_requests AS ot WHERE ot.id = p_request
        ), minutes AS (
            SELECT request.day_off, request.night_start, request.night_end,
                (extract(hour FROM timezone(app.hr_zone(), minute))::integer * 60
                    + extract(minute FROM timezone(app.hr_zone(), minute))::integer) AS clock
            FROM request,
                generate_series(request.starts_at, request.ends_at - interval '1 minute',
                    interval '1 minute') AS minute
        )
        SELECT round(count(*) FILTER (WHERE NOT is_night) / 60.0, 2),
            round(count(*) FILTER (WHERE is_night) / 60.0, 2)
        FROM (SELECT day_off OR CASE WHEN night_start > night_end
                    THEN clock >= night_start OR clock < night_end
                    ELSE clock >= night_start AND clock < night_end END AS is_night
              FROM minutes) AS counted
    $$;
    REVOKE ALL ON FUNCTION app.hr_overtime_hours(uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_overtime_counts(p_request uuid) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN app.hr_rule('ATT_OT_FIRST', request.work_date, 1) = 1
                THEN coalesce(decision.decision = 'APPROVED', false)
                ELSE coalesce(decision.decision, 'APPROVED') = 'APPROVED' END
        FROM app.overtime_requests AS request
        LEFT JOIN app.overtime_decisions AS decision
            ON decision.overtime_request_id = request.id
        WHERE request.id = p_request
    $$;
    REVOKE ALL ON FUNCTION app.hr_overtime_counts(uuid) FROM PUBLIC;

    -- PR-HR-058: the month summary per person.
    CREATE FUNCTION app.hr_attendance_month(p_property uuid, p_month date, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog SET jit = off AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.read', p_property);
        v_month date := date_trunc('month', coalesce(p_month, v_today))::date;
        v_end date := (date_trunc('month', coalesce(p_month, v_today)) + interval '1 month'
            - interval '1 day')::date;
    BEGIN
        RETURN jsonb_build_object(
            'month', v_month, 'locked', app.hr_month_locked(p_property, v_month),
            'people', coalesce((SELECT jsonb_agg(summary ORDER BY summary ->> 'employee_code')
                FROM (SELECT jsonb_build_object(
                        'employee_id', employee.id, 'employee_code', employee.employee_code,
                        'name_en', employee.name_en, 'name_km', employee.name_km,
                        'days_worked', count(*) FILTER (WHERE (day ->> 'status') = 'WORKED'),
                        'times_late', count(*) FILTER (WHERE (day ->> 'late_minutes') IS NOT NULL),
                        'days_absent', count(*) FILTER (WHERE (day ->> 'status') = 'ABSENT'),
                        'leave_annual', count(*) FILTER (WHERE (day ->> 'status') = 'LEAVE_ANNUAL'),
                        'leave_sick', count(*) FILTER (WHERE (day ->> 'status') = 'LEAVE_SICK'),
                        'leave_unpaid', count(*) FILTER (WHERE (day ->> 'status') = 'LEAVE_UNPAID'),
                        'days_off', count(*) FILTER (WHERE (day ->> 'status') = 'DAY_OFF'),
                        'no_entry', count(*) FILTER (WHERE (day ->> 'status') IS NULL
                            AND NOT coalesce((day ->> 'day_off')::boolean, false)),
                        'no_check_out', count(*) FILTER (WHERE (day ->> 'no_check_out')::boolean),
                        'overtime_hours', (SELECT coalesce(sum(hours.normal_hours), 0)
                            FROM app.overtime_requests AS request
                            CROSS JOIN LATERAL app.hr_overtime_hours(request.id) AS hours
                            WHERE request.employee_id = employee.id
                              AND request.work_date BETWEEN v_month AND v_end
                              AND app.hr_overtime_counts(request.id)),
                        'overtime_night_hours', (SELECT coalesce(sum(hours.night_hours), 0)
                            FROM app.overtime_requests AS request
                            CROSS JOIN LATERAL app.hr_overtime_hours(request.id) AS hours
                            WHERE request.employee_id = employee.id
                              AND request.work_date BETWEEN v_month AND v_end
                              AND app.hr_overtime_counts(request.id))) AS summary
                    FROM app.employees AS employee
                    CROSS JOIN LATERAL generate_series(greatest(v_month,
                        app.hr_hired_on(employee.id)), least(v_end, v_today,
                        coalesce(app.hr_left_on(employee.id), v_end)), interval '1 day') AS on_day
                    CROSS JOIN LATERAL app.hr_day_json(employee.id, on_day::date,
                        statement_timestamp()) AS day
                    WHERE employee.property_id = p_property
                    GROUP BY employee.id) AS people), '[]'::jsonb));
    END $$;

    -- PR-HR-053: the Owner or a Manager enters or fixes a day by hand, with a reason.
    CREATE FUNCTION app.hr_attendance_entry(p_property uuid, p_body jsonb, p_actor uuid,
        p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.manage', p_property);
        v_employee uuid := app.hr_uuid(p_body, 'employee_id', 'Choose the employee');
        v_day date := app.hr_date(p_body, 'work_date', 'The day is not a date');
        v_status text := app.problem_text(p_body, 'status', 20, 'Choose the status');
        v_reason text := app.problem_text(p_body, 'reason', 500, 'The reason is at most 500 letters');
        v_shift text := app.problem_text(p_body, 'shift_code', 20, 'Choose the shift');
        v_in timestamptz;
        v_out timestamptz;
        v_old app.attendance_entries%ROWTYPE;
        v_id uuid := gen_random_uuid();
    BEGIN
        IF v_employee IS NULL OR NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.id = v_employee AND employee.property_id = p_property) THEN
            RAISE EXCEPTION 'Choose the employee' USING ERRCODE = '22023';
        END IF;
        IF v_day IS NULL OR v_day > v_today THEN
            RAISE EXCEPTION 'The day is today or earlier' USING ERRCODE = '22023';
        END IF;
        IF NOT app.hr_works_on(v_employee, v_day) THEN
            RAISE EXCEPTION 'The employee did not work for us on that day' USING ERRCODE = '22023';
        END IF;
        IF v_status IS NULL OR v_status NOT IN ('WORKED', 'ABSENT', 'LEAVE_ANNUAL', 'LEAVE_SICK',
                'LEAVE_UNPAID', 'DAY_OFF') THEN
            RAISE EXCEPTION 'Choose the status' USING ERRCODE = '22023';
        END IF;
        IF v_reason IS NULL THEN
            RAISE EXCEPTION 'Say why' USING ERRCODE = '22023';
        END IF;
        v_shift := coalesce(v_shift, (SELECT plan.shift_code FROM app.hr_shift_on(v_employee,
            v_day) AS plan));
        BEGIN
            -- Times are the clock on the day (HH:MI); a check-out before the check-in is the
            -- next morning (Night shift).
            IF v_status = 'WORKED' THEN
                v_in := timezone(app.hr_zone(), v_day + (p_body ->> 'check_in')::time);
                IF p_body ->> 'check_out' IS NOT NULL THEN
                    v_out := timezone(app.hr_zone(), v_day + (p_body ->> 'check_out')::time);
                    IF v_out <= v_in THEN
                        v_out := v_out + interval '1 day';
                    END IF;
                END IF;
            END IF;
        EXCEPTION WHEN data_exception THEN
            RAISE EXCEPTION 'Times look like 06:30' USING ERRCODE = '22023';
        END;
        IF v_status = 'WORKED' AND v_in IS NULL THEN
            RAISE EXCEPTION 'Enter the check-in time' USING ERRCODE = '22023';
        END IF;
        v_old := app.hr_entry_on(v_employee, v_day);
        PERFORM pg_advisory_xact_lock(hashtextextended('hr-day:' || v_employee || v_day, 0));
        INSERT INTO app.attendance_entries (id, employee_id, work_date, shift_code, status,
            check_in_at, check_out_at, source, check_in_scan_id, check_out_scan_id, replaces_id,
            reason, created_by)
        VALUES (v_id, v_employee, v_day, v_shift, v_status, v_in, v_out, 'MANUAL',
            CASE WHEN v_old.check_in_at = v_in THEN v_old.check_in_scan_id END,
            CASE WHEN v_old.check_out_at = v_out THEN v_old.check_out_scan_id END,
            v_old.id, v_reason, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.attendance.entered', 'employee',
            v_employee, v_reason, p_correlation,
            CASE WHEN v_old.id IS NULL THEN NULL ELSE jsonb_build_object('status', v_old.status,
                'check_in_at', v_old.check_in_at, 'check_out_at', v_old.check_out_at) END,
            jsonb_build_object('work_date', v_day, 'status', v_status, 'check_in_at', v_in,
                'check_out_at', v_out));
        RETURN v_id;
    END $$;

    -- PR-HR-052: the weekly plan, one day at a time.
    CREATE FUNCTION app.hr_plan_day(p_property uuid, p_body jsonb, p_actor uuid,
        p_correlation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.manage', p_property);
        v_employee uuid := app.hr_uuid(p_body, 'employee_id', 'Choose the employee');
        v_day date := app.hr_date(p_body, 'work_date', 'The day is not a date');
        v_shift text := app.problem_text(p_body, 'shift_code', 20, 'Choose the shift');
        v_reason text := app.problem_text(p_body, 'reason', 500, 'The reason is at most 500 letters');
    BEGIN
        IF v_employee IS NULL OR NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.id = v_employee AND employee.property_id = p_property) THEN
            RAISE EXCEPTION 'Choose the employee' USING ERRCODE = '22023';
        END IF;
        IF v_day IS NULL OR NOT app.hr_works_on(v_employee, v_day) THEN
            RAISE EXCEPTION 'The employee does not work for us on that day' USING ERRCODE = '22023';
        END IF;
        IF v_shift IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.work_shifts AS shift
                WHERE shift.code = v_shift) THEN
            RAISE EXCEPTION 'Choose the shift' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.shift_plan_entries (employee_id, work_date, shift_code, is_day_off,
            reason, created_by)
        VALUES (v_employee, v_day, v_shift, v_shift IS NULL, v_reason, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.attendance.planned', 'employee',
            v_employee, coalesce(v_reason, 'Weekly plan'), p_correlation, NULL,
            jsonb_build_object('work_date', v_day, 'shift_code', v_shift));
    END $$;

    -- PR-HR-056: overtime is asked before it is worked.
    CREATE FUNCTION app.hr_request_overtime(p_property uuid, p_body jsonb, p_actor uuid,
        p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.manage', p_property);
        v_employee uuid := app.hr_uuid(p_body, 'employee_id', 'Choose the employee');
        v_day date := app.hr_date(p_body, 'work_date', 'The day is not a date');
        v_reason text := app.problem_text(p_body, 'reason', 500, 'The reason is at most 500 letters');
        v_from timestamptz;
        v_to timestamptz;
        v_id uuid := gen_random_uuid();
        v_number text;
    BEGIN
        IF v_employee IS NULL OR NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.id = v_employee AND employee.property_id = p_property) THEN
            RAISE EXCEPTION 'Choose the employee' USING ERRCODE = '22023';
        END IF;
        IF v_day IS NULL OR v_day < v_today THEN
            RAISE EXCEPTION 'Overtime is asked for before it is worked' USING ERRCODE = '22023';
        END IF;
        IF NOT app.hr_works_on(v_employee, v_day) THEN
            RAISE EXCEPTION 'The employee does not work for us on that day' USING ERRCODE = '22023';
        END IF;
        IF v_reason IS NULL THEN
            RAISE EXCEPTION 'Say why overtime is needed' USING ERRCODE = '22023';
        END IF;
        BEGIN
            v_from := timezone(app.hr_zone(), v_day + (p_body ->> 'starts_at')::time);
            v_to := timezone(app.hr_zone(), v_day + (p_body ->> 'ends_at')::time);
        EXCEPTION WHEN data_exception THEN
            RAISE EXCEPTION 'Times look like 18:00' USING ERRCODE = '22023';
        END;
        IF v_from IS NULL OR v_to IS NULL THEN
            RAISE EXCEPTION 'Enter the start and end times' USING ERRCODE = '22023';
        END IF;
        IF v_to <= v_from THEN
            v_to := v_to + interval '1 day';
        END IF;
        IF v_to > v_from + interval '16 hours' THEN
            RAISE EXCEPTION 'Overtime is at most 16 hours' USING ERRCODE = '22023';
        END IF;
        IF v_from < statement_timestamp() THEN
            RAISE EXCEPTION 'Overtime is asked for before it is worked' USING ERRCODE = '22023';
        END IF;
        v_number := app.next_document_number('OVERTIME', statement_timestamp());
        INSERT INTO app.overtime_requests (id, property_id, overtime_number, employee_id,
            work_date, starts_at, ends_at, reason, created_by)
        VALUES (v_id, p_property, v_number, v_employee, v_day, v_from, v_to, v_reason, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.overtime.requested', 'overtime_request',
            v_id, v_reason, p_correlation, NULL, jsonb_build_object('overtime_number', v_number,
                'employee_id', v_employee, 'starts_at', v_from, 'ends_at', v_to));
        RETURN v_id;
    END $$;

    CREATE FUNCTION app.hr_decide_overtime(p_property uuid, p_request uuid, p_body jsonb,
        p_actor uuid, p_correlation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.overtime.approve', p_property);
        v_request app.overtime_requests%ROWTYPE;
        v_decision text := app.problem_text(p_body, 'decision', 20, 'Choose approve or refuse');
        v_reason text := app.problem_text(p_body, 'reason', 500, 'The reason is at most 500 letters');
        v_note text;
    BEGIN
        SELECT request.* INTO v_request FROM app.overtime_requests AS request
        WHERE request.id = p_request AND request.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The overtime request was not found' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.overtime_decisions AS decision
                WHERE decision.overtime_request_id = p_request) THEN
            RAISE EXCEPTION 'The overtime is already decided' USING ERRCODE = '55000';
        END IF;
        IF v_decision IS NULL OR v_decision NOT IN ('APPROVED', 'REFUSED') THEN
            RAISE EXCEPTION 'Choose approve or refuse' USING ERRCODE = '22023';
        END IF;
        IF v_decision = 'REFUSED' AND v_reason IS NULL THEN
            RAISE EXCEPTION 'Say why it is refused' USING ERRCODE = '22023';
        END IF;
        IF v_decision = 'APPROVED' AND app.hr_rule('ATT_OT_FIRST', v_request.work_date, 1) = 1
                AND statement_timestamp() >= v_request.starts_at THEN
            RAISE EXCEPTION 'Overtime is approved before it starts' USING ERRCODE = '55000';
        END IF;
        v_note := app.hr_own_check(p_actor, v_request.created_by = p_actor OR EXISTS (
                SELECT 1 FROM app.employees AS employee
                WHERE employee.id = v_request.employee_id AND employee.user_actor_id = p_actor),
            p_body ->> 'own_request_note');
        INSERT INTO app.overtime_decisions (overtime_request_id, decision, reason,
            own_request_note, decided_by)
        VALUES (p_request, v_decision, v_reason, v_note, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.overtime.' || lower(v_decision),
            'overtime_request', p_request, coalesce(v_reason, v_note, 'Approved'), p_correlation,
            NULL, jsonb_build_object('decision', v_decision, 'own_request_note', v_note));
    END $$;

    CREATE FUNCTION app.hr_overtime_read(p_property uuid, p_month date, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog SET jit = off AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.read', p_property);
        v_month date := date_trunc('month', coalesce(p_month, v_today))::date;
    BEGIN
        RETURN jsonb_build_object(
            'month', v_month,
            'can_request', app.hr_can(p_actor, p_property, 'hr.attendance.manage'),
            'can_approve', app.hr_can(p_actor, p_property, 'hr.overtime.approve'),
            'requests', coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'request_id', request.id, 'overtime_number', request.overtime_number,
                    'employee_id', employee.id, 'employee_code', employee.employee_code,
                    'name_en', employee.name_en, 'name_km', employee.name_km,
                    'work_date', request.work_date, 'starts_at', request.starts_at,
                    'ends_at', request.ends_at, 'reason', request.reason,
                    'normal_hours', hours.normal_hours, 'night_hours', hours.night_hours,
                    'asked_by', asker.display_name, 'asked_at', request.created_at,
                    'decision', decision.decision, 'decision_reason', decision.reason,
                    'decided_by', decider.display_name, 'decided_at', decision.decided_at,
                    'counts', app.hr_overtime_counts(request.id))
                    ORDER BY request.starts_at DESC)
                FROM app.overtime_requests AS request
                JOIN app.employees AS employee ON employee.id = request.employee_id
                CROSS JOIN LATERAL app.hr_overtime_hours(request.id) AS hours
                LEFT JOIN app.user_accounts AS asker ON asker.actor_id = request.created_by
                LEFT JOIN app.overtime_decisions AS decision
                    ON decision.overtime_request_id = request.id
                LEFT JOIN app.user_accounts AS decider ON decider.actor_id = decision.decided_by
                WHERE request.property_id = p_property
                  AND request.work_date >= v_month
                  AND request.work_date < v_month + interval '1 month'), '[]'::jsonb));
    END $$;

    CREATE FUNCTION app.hr_accept_scan(p_property uuid, p_scan uuid, p_note text, p_actor uuid,
        p_correlation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.manage', p_property);
        v_scan record;
    BEGIN
        SELECT scan.*, employee.user_actor_id INTO v_scan FROM app.attendance_scans AS scan
        JOIN app.employees AS employee ON employee.id = scan.employee_id
        WHERE scan.id = p_scan AND employee.property_id = p_property AND scan.needs_check;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'There is no scan to check' USING ERRCODE = '22023';
        END IF;
        IF v_scan.user_actor_id = p_actor THEN
            RAISE EXCEPTION 'Nobody accepts their own scan' USING ERRCODE = '42501';
        END IF;
        IF EXISTS (SELECT 1 FROM app.attendance_scan_acceptances AS accepted
                WHERE accepted.scan_id = p_scan) THEN
            RAISE EXCEPTION 'The scan is already accepted' USING ERRCODE = '55000';
        END IF;
        INSERT INTO app.attendance_scan_acceptances (scan_id, note, created_by)
        VALUES (p_scan, nullif(btrim(p_note), ''), p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.attendance.scan_accepted', 'employee',
            v_scan.employee_id, coalesce(nullif(btrim(p_note), ''), 'Scan accepted'),
            p_correlation, NULL, jsonb_build_object('scan_id', p_scan));
    END $$;

    -- PR-HR-067: only roles with Attendance open a card photo.
    CREATE FUNCTION app.hr_scan_photo_file(p_property uuid, p_scan uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.read', p_property);
        v_file record;
    BEGIN
        SELECT file.storage_key, file.media_type, file.original_name, file.sha256,
            file.byte_size INTO v_file
        FROM app.attendance_scans AS scan
        JOIN app.employees AS employee ON employee.id = scan.employee_id
        JOIN app.stored_files AS file ON file.id = scan.photo_file_id
        WHERE scan.id = p_scan AND employee.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.stored_file_removals AS removal
              WHERE removal.file_id = file.id);
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The photo was not found or is removed' USING ERRCODE = '22023';
        END IF;
        RETURN to_jsonb(v_file);
    END $$;

    -- Places, their pins and QR codes (PR-HR-060). Only the Owner replaces a QR or a pin.
    CREATE FUNCTION app.hr_attendance_places(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.read', p_property);
    BEGIN
        RETURN jsonb_build_object(
            'is_owner', app.hr_is_owner(p_actor),
            'qr_distance_m', app.hr_rule('ATT_QR_DIST', v_today, 100),
            'places', (SELECT jsonb_agg(jsonb_build_object('place_id', place.id,
                    'code', place.code, 'name_en', place.name_en, 'name_km', place.name_km,
                    'latitude', pin.latitude, 'longitude', pin.longitude,
                    'pin_set_at', pin.created_at,
                    'qr_made_at', (SELECT max(qr.created_at) FROM app.attendance_place_qr_codes AS qr
                        WHERE qr.place_id = place.id),
                    'qr_count', (SELECT count(*) FROM app.attendance_place_qr_codes AS qr
                        WHERE qr.place_id = place.id)) ORDER BY place.sort_order)
                FROM app.attendance_places AS place
                LEFT JOIN LATERAL (SELECT spot.* FROM app.attendance_place_pins AS spot
                    WHERE spot.place_id = place.id ORDER BY spot.created_at DESC LIMIT 1) AS pin
                    ON true));
    END $$;

    CREATE FUNCTION app.hr_set_place_pin(p_property uuid, p_place uuid, p_latitude double precision,
        p_longitude double precision, p_reason text, p_actor uuid, p_correlation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.manage', p_property);
    BEGIN
        IF NOT app.hr_is_owner(p_actor) THEN
            RAISE EXCEPTION 'Only the Owner sets a place''s pin' USING ERRCODE = '42501';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM app.attendance_places AS place WHERE place.id = p_place) THEN
            RAISE EXCEPTION 'The place was not found' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.attendance_place_pins (place_id, latitude, longitude, reason, created_by)
        VALUES (p_place, p_latitude, p_longitude, coalesce(nullif(btrim(p_reason), ''),
            'Pin set'), p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.attendance.place_pin', 'attendance_place',
            p_place, coalesce(nullif(btrim(p_reason), ''), 'Pin set'), p_correlation, NULL,
            jsonb_build_object('latitude', p_latitude, 'longitude', p_longitude));
    END $$;

    -- A new printed QR: the code text is returned once to print and only its SHA-256 is kept,
    -- so the older code stops working at once.
    CREATE FUNCTION app.hr_new_qr_text(p_kind text) RETURNS text
    LANGUAGE sql VOLATILE SET search_path = pg_catalog AS $$
        SELECT 'CHETANA-' || p_kind || '-' || replace(gen_random_uuid()::text, '-', '')
            || replace(gen_random_uuid()::text, '-', '')
    $$;
    REVOKE ALL ON FUNCTION app.hr_new_qr_text(text) FROM PUBLIC;

    CREATE FUNCTION app.hr_qr_hash(p_code text) RETURNS bytea
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT sha256(convert_to(btrim(p_code), 'UTF8'))
    $$;
    REVOKE ALL ON FUNCTION app.hr_qr_hash(text) FROM PUBLIC;

    CREATE FUNCTION app.hr_new_place_qr(p_property uuid, p_place uuid, p_reason text,
        p_actor uuid, p_correlation uuid) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.manage', p_property);
        v_code text := app.hr_new_qr_text('P');
    BEGIN
        IF NOT app.hr_is_owner(p_actor) THEN
            RAISE EXCEPTION 'Only the Owner makes or replaces a place QR' USING ERRCODE = '42501';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM app.attendance_places AS place WHERE place.id = p_place) THEN
            RAISE EXCEPTION 'The place was not found' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.attendance_place_qr_codes (place_id, code_sha256, reason, created_by)
        VALUES (p_place, app.hr_qr_hash(v_code), coalesce(nullif(btrim(p_reason), ''),
            'New QR printed'), p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.attendance.place_qr', 'attendance_place',
            p_place, coalesce(nullif(btrim(p_reason), ''), 'New QR printed'), p_correlation, NULL,
            jsonb_build_object('place_id', p_place));
        RETURN v_code;
    END $$;

    -- PR-HR-064: an employee card QR; a new one replaces the lost card at once.
    CREATE FUNCTION app.hr_new_card_qr(p_property uuid, p_employee uuid, p_reason text,
        p_actor uuid, p_correlation uuid) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.require_product_right(p_actor, 'hr.attendance.manage', p_property);
        v_code text := app.hr_new_qr_text('E');
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.id = p_employee AND employee.property_id = p_property
                  AND app.hr_works_on(employee.id, v_today)) THEN
            RAISE EXCEPTION 'Only a working employee gets a card' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.employee_card_qr_codes (employee_id, code_sha256, reason, created_by)
        VALUES (p_employee, app.hr_qr_hash(v_code), coalesce(nullif(btrim(p_reason), ''),
            'New card printed'), p_actor);
        UPDATE app.employees AS employee SET version = employee.version + 1
        WHERE employee.id = p_employee;
        PERFORM app.hr_audit(p_property, p_actor, 'hr.attendance.card_qr', 'employee', p_employee,
            coalesce(nullif(btrim(p_reason), ''), 'New card printed'), p_correlation, NULL,
            jsonb_build_object('employee_id', p_employee));
        RETURN v_code;
    END $$;

    -- The Employee card box: every card printed, newest first; only the newest works, and only
    -- while the person works for us.
    CREATE FUNCTION app.hr_employee_card(p_property uuid, p_employee uuid, p_actor uuid)
    RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := timezone(app.hr_zone(), statement_timestamp())::date;
    BEGIN
        IF NOT (app.hr_can(p_actor, p_property, 'hr.attendance.read')
                OR app.hr_can(p_actor, p_property, 'hr.employees.read')) THEN
            RAISE EXCEPTION 'You cannot see employee cards' USING ERRCODE = '42501';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.id = p_employee AND employee.property_id = p_property) THEN
            RAISE EXCEPTION 'The employee was not found' USING ERRCODE = '22023';
        END IF;
        RETURN jsonb_build_object(
            'works', app.hr_works_on(p_employee, v_today),
            'left_on', app.hr_left_on(p_employee),
            'can_replace', app.hr_can(p_actor, p_property, 'hr.attendance.manage'),
            'cards', coalesce((SELECT jsonb_agg(jsonb_build_object('number', card.number,
                    'since', card.created_at, 'reason', card.reason, 'by', account.display_name)
                    ORDER BY card.number DESC)
                FROM (SELECT qr.*, row_number() OVER (ORDER BY qr.created_at) AS number
                      FROM app.employee_card_qr_codes AS qr
                      WHERE qr.employee_id = p_employee) AS card
                LEFT JOIN app.user_accounts AS account ON account.actor_id = card.created_by),
                '[]'::jsonb));
    END $$;

    CREATE FUNCTION app.hr_distance_m(p_lat1 double precision, p_lon1 double precision,
        p_lat2 double precision, p_lon2 double precision) RETURNS integer
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT round(2 * 6371000 * asin(sqrt(power(sin(radians(p_lat2 - p_lat1) / 2), 2)
            + cos(radians(p_lat1)) * cos(radians(p_lat2))
              * power(sin(radians(p_lon2 - p_lon1) / 2), 2))))::integer
    $$;
    REVOKE ALL ON FUNCTION app.hr_distance_m(double precision, double precision,
        double precision, double precision) FROM PUBLIC;

    -- The live link of a Telegram user to a working employee.
    CREATE FUNCTION app.hr_linked_employee(p_property uuid, p_telegram bigint, p_day date)
    RETURNS uuid
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT link.employee_id FROM app.employee_telegram_links AS link
        JOIN app.employees AS employee ON employee.id = link.employee_id
        WHERE link.telegram_user_id = p_telegram AND employee.property_id = p_property
          AND app.hr_link_live(link.id, p_day)
        LIMIT 1
    $$;
    REVOKE ALL ON FUNCTION app.hr_linked_employee(uuid, bigint, date) FROM PUBLIC;

    CREATE FUNCTION app.hr_refuse(p_reason text) RETURNS jsonb
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object('ok', false, 'reason', p_reason,
            'reply_key', 'check_refused_' || lower(p_reason))
    $$;
    REVOKE ALL ON FUNCTION app.hr_refuse(text) FROM PUBLIC;

    -- The shared part of a phone or card scan: which day and shift it belongs to, the early
    -- and double-scan checks, and the sheet row. Returns the refusal, or NULL when saved.
    CREATE FUNCTION app.hr_save_scan(p_property uuid, p_employee uuid, p_direction text,
        p_method text, p_place uuid, p_at timestamptz, p_phone_time timestamptz,
        p_distance integer, p_needs_check boolean, p_card_reason text, p_card_text text,
        p_photo uuid, p_scanner uuid, p_telegram bigint, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := timezone(app.hr_zone(), p_at)::date;
        v_day date;
        v_plan record;
        v_times record;
        v_entry app.attendance_entries%ROWTYPE;
        v_scan uuid := gen_random_uuid();
        v_late integer;
        v_shift text;
        v_source text := CASE p_method WHEN 'PHONE' THEN 'QR_PHONE' ELSE 'QR_CARD' END;
    BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended('hr-scan:' || p_employee, 0));
        IF p_direction = 'IN' THEN
            v_day := v_today;
            -- Just after midnight a Night shift check-in still belongs to the day before,
            -- unless today's own shift is already open for check-in.
            SELECT * INTO v_plan FROM app.hr_shift_on(p_employee, v_today - 1);
            IF v_plan.shift_code IS NOT NULL THEN
                SELECT * INTO v_times FROM app.hr_shift_times(v_plan.shift_code, v_today - 1);
                IF p_at < v_times.ends_at
                        AND (app.hr_entry_on(p_employee, v_today - 1)).id IS NULL
                        AND NOT coalesce((SELECT p_at >= today_times.starts_at - make_interval(
                                mins => app.hr_rule('ATT_QR_EARLY', v_today, 30)::integer)
                            FROM app.hr_shift_on(p_employee, v_today) AS today_plan
                            CROSS JOIN LATERAL app.hr_shift_times(today_plan.shift_code,
                                v_today) AS today_times), false) THEN
                    v_day := v_today - 1;
                END IF;
            END IF;
            IF NOT app.hr_works_on(p_employee, v_day) THEN
                RETURN app.hr_refuse('NOT_WORKING');
            END IF;
            v_entry := app.hr_entry_on(p_employee, v_day);
            IF v_entry.status = 'WORKED' THEN
                RETURN app.hr_refuse('ALREADY_IN');
            END IF;
            SELECT * INTO v_plan FROM app.hr_shift_on(p_employee, v_day);
            v_shift := v_plan.shift_code;
            IF v_shift IS NOT NULL THEN
                SELECT * INTO v_times FROM app.hr_shift_times(v_shift, v_day);
                IF p_at < v_times.starts_at - make_interval(mins =>
                        app.hr_rule('ATT_QR_EARLY', v_day, 30)::integer) THEN
                    RETURN app.hr_refuse('TOO_EARLY') || jsonb_build_object('shift_starts_at',
                        v_times.starts_at);
                END IF;
                IF p_at > v_times.starts_at + make_interval(mins =>
                        app.hr_rule('ATT_LATE_MIN', v_day, 10)::integer) THEN
                    v_late := floor(extract(epoch FROM p_at - v_times.starts_at) / 60)::integer;
                END IF;
            END IF;
        ELSE
            SELECT entry.* INTO v_entry FROM app.attendance_entries AS entry
            WHERE entry.employee_id = p_employee AND entry.work_date BETWEEN v_today - 1 AND v_today
              AND entry.id = (app.hr_entry_on(p_employee, entry.work_date)).id
              AND entry.status = 'WORKED' AND entry.check_out_at IS NULL
              AND entry.check_in_at < p_at
            ORDER BY entry.work_date DESC LIMIT 1;
            IF NOT FOUND THEN
                RETURN app.hr_refuse('NOT_CHECKED_IN');
            END IF;
            v_day := v_entry.work_date;
            v_shift := v_entry.shift_code;
        END IF;
        IF app.hr_month_locked(p_property, v_day) THEN
            RETURN app.hr_refuse('MONTH_LOCKED');
        END IF;
        INSERT INTO app.attendance_scans (id, employee_id, work_date, direction, method, place_id,
            scanned_at, phone_time, distance_m, needs_check, card_reason, card_reason_text,
            photo_file_id, scanned_by_employee_id, telegram_user_id, created_by)
        VALUES (v_scan, p_employee, v_day, p_direction, p_method, p_place, p_at, p_phone_time,
            p_distance, p_needs_check, p_card_reason, p_card_text, p_photo, p_scanner,
            p_telegram, p_actor);
        IF p_direction = 'IN' THEN
            INSERT INTO app.attendance_entries (employee_id, work_date, shift_code, status,
                check_in_at, source, check_in_scan_id, replaces_id, reason, created_by)
            VALUES (p_employee, v_day, v_shift, 'WORKED', p_at, v_source, v_scan,
                v_entry.id, NULL, p_actor);
        ELSE
            INSERT INTO app.attendance_entries (employee_id, work_date, shift_code, status,
                check_in_at, check_out_at, source, check_in_scan_id, check_out_scan_id,
                replaces_id, reason, created_by)
            VALUES (p_employee, v_day, v_entry.shift_code, 'WORKED', v_entry.check_in_at, p_at,
                v_source, v_entry.check_in_scan_id, v_scan, v_entry.id, NULL, p_actor);
        END IF;
        RETURN jsonb_build_object('ok', true, 'scan_id', v_scan, 'work_date', v_day,
            'direction', p_direction, 'at', p_at, 'needs_check', p_needs_check,
            'late_minutes', v_late, 'shift_code', v_shift,
            'reply_key', CASE WHEN p_direction = 'OUT' THEN 'check_out_ok'
                WHEN p_needs_check THEN 'check_in_needs_check'
                WHEN v_late IS NOT NULL THEN 'check_in_late' ELSE 'check_in_ok' END);
    END $$;
    REVOKE ALL ON FUNCTION app.hr_save_scan(uuid, uuid, text, text, uuid, timestamptz,
        timestamptz, integer, boolean, text, text, uuid, uuid, bigint, uuid) FROM PUBLIC;

    -- PR-HR-061..063: the staff bot's phone scan (contract agreed with the Telegram thread on
    -- 04/11/2026). p_scan: {"mode": "IN"|"OUT", "qr": "<code text>", "location": {"status":
    -- "OK"|"NOT_FOUND"|"OFF", "latitude": .., "longitude": ..}, "phone_time": ".."}.
    CREATE FUNCTION app.record_staff_check_scan(p_property uuid, p_telegram_user_id bigint,
        p_scan jsonb, p_scanned_at timestamptz, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_at timestamptz := coalesce(p_scanned_at, statement_timestamp());
        v_today date := app.hr_require_service(p_actor, p_property);
        v_employee uuid;
        v_mode text := upper(p_scan ->> 'mode');
        v_place record;
        v_status text := upper(coalesce(p_scan #>> '{location,status}', 'NOT_FOUND'));
        v_lat double precision;
        v_lon double precision;
        v_distance integer;
        v_phone timestamptz;
        v_result jsonb;
    BEGIN
        IF p_scan IS NULL OR jsonb_typeof(p_scan) <> 'object' OR v_mode IS NULL
                OR v_mode NOT IN ('IN', 'OUT') THEN
            RETURN app.hr_refuse('BAD_SCAN');
        END IF;
        v_employee := app.hr_linked_employee(p_property, p_telegram_user_id,
            timezone(app.hr_zone(), v_at)::date);
        IF v_employee IS NULL THEN
            RETURN app.hr_refuse('NOT_LINKED');
        END IF;
        IF v_status = 'OFF' THEN
            RETURN app.hr_refuse('LOCATION_OFF');
        END IF;
        SELECT place.id, place.name_en, place.name_km, qr.created_at,
            (SELECT newest.id FROM app.attendance_place_qr_codes AS newest
             WHERE newest.place_id = place.id ORDER BY newest.created_at DESC LIMIT 1) = qr.id
                AS live,
            pin.latitude, pin.longitude
        INTO v_place
        FROM app.attendance_place_qr_codes AS qr
        JOIN app.attendance_places AS place ON place.id = qr.place_id
        LEFT JOIN LATERAL (SELECT spot.* FROM app.attendance_place_pins AS spot
            WHERE spot.place_id = place.id ORDER BY spot.created_at DESC LIMIT 1) AS pin ON true
        WHERE qr.code_sha256 = app.hr_qr_hash(coalesce(p_scan ->> 'qr', ''));
        IF NOT FOUND THEN
            RETURN app.hr_refuse('QR_UNKNOWN');
        END IF;
        IF NOT v_place.live THEN
            RETURN app.hr_refuse('QR_REPLACED');
        END IF;
        BEGIN
            v_lat := (p_scan #>> '{location,latitude}')::double precision;
            v_lon := (p_scan #>> '{location,longitude}')::double precision;
            v_phone := (p_scan ->> 'phone_time')::timestamptz;
        EXCEPTION WHEN data_exception THEN
            v_lat := NULL;
            v_lon := NULL;
        END;
        IF v_status = 'OK' AND v_lat BETWEEN -90 AND 90 AND v_lon BETWEEN -180 AND 180
                AND v_place.latitude IS NOT NULL THEN
            v_distance := app.hr_distance_m(v_lat, v_lon, v_place.latitude, v_place.longitude);
        END IF;
        v_result := app.hr_save_scan(p_property, v_employee, v_mode, 'PHONE', v_place.id, v_at,
            v_phone, v_distance, v_distance IS NULL OR v_distance > app.hr_rule('ATT_QR_DIST',
                v_today, 100), NULL, NULL, NULL, NULL, p_telegram_user_id, p_actor);
        IF (v_result ->> 'ok')::boolean THEN
            v_result := v_result || jsonb_build_object('employee_id', v_employee,
                'place_en', v_place.name_en, 'place_km', v_place.name_km,
                'distance_m', v_distance);
        END IF;
        RETURN v_result;
    END $$;

    CREATE FUNCTION app.hr_card_employee(p_property uuid, p_code text, p_day date)
    RETURNS TABLE (employee_id uuid, live boolean) ROWS 1
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT card.employee_id,
            (SELECT newest.id FROM app.employee_card_qr_codes AS newest
             WHERE newest.employee_id = card.employee_id
             ORDER BY newest.created_at DESC LIMIT 1) = card.id
            AND app.hr_works_on(card.employee_id, p_day)
        FROM app.employee_card_qr_codes AS card
        JOIN app.employees AS employee ON employee.id = card.employee_id
        WHERE card.code_sha256 = app.hr_qr_hash(coalesce(p_code, ''))
          AND employee.property_id = p_property
    $$;
    REVOKE ALL ON FUNCTION app.hr_card_employee(uuid, text, date) FROM PUBLIC;

    -- PR-HR-065, PR-HR-066: the caretaker scans the card first and sees the name and shift.
    CREATE FUNCTION app.hr_card_lookup(p_property uuid, p_telegram_user_id bigint, p_card text,
        p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.hr_require_service(p_actor, p_property);
        v_scanner uuid := app.hr_linked_employee(p_property, p_telegram_user_id, v_today);
        v_card record;
        v_plan record;
    BEGIN
        IF v_scanner IS NULL OR NOT EXISTS (SELECT 1 FROM app.employee_telegram_links AS link
                WHERE link.employee_id = v_scanner AND link.telegram_user_id = p_telegram_user_id
                  AND link.report_role IN ('CARETAKER', 'AUTHORIZER')
                  AND app.hr_link_live(link.id, v_today)) THEN
            RETURN app.hr_refuse('NOT_CARETAKER');
        END IF;
        SELECT * INTO v_card FROM app.hr_card_employee(p_property, p_card, v_today);
        IF NOT FOUND THEN
            RETURN app.hr_refuse('CARD_UNKNOWN');
        END IF;
        IF NOT v_card.live THEN
            RETURN app.hr_refuse('CARD_STOPPED');
        END IF;
        IF v_card.employee_id = v_scanner THEN
            RETURN app.hr_refuse('OWN_CARD');
        END IF;
        SELECT * INTO v_plan FROM app.hr_shift_on(v_card.employee_id, v_today);
        RETURN (SELECT jsonb_build_object('ok', true, 'employee_id', employee.id,
                'employee_code', employee.employee_code, 'name_en', employee.name_en,
                'name_km', employee.name_km, 'shift_code', v_plan.shift_code,
                'day_off', v_plan.is_day_off)
            FROM app.employees AS employee WHERE employee.id = v_card.employee_id);
    END $$;

    -- The card scan itself: reason and half-body photo are required. p_scan: {"mode", "card",
    -- "reason", "reason_text", "photo": {"sha256", "byte_size", "media_type", "storage_key"},
    -- "location": {...} (optional), "phone_time"}.
    CREATE FUNCTION app.record_card_check_scan(p_property uuid, p_telegram_user_id bigint,
        p_scan jsonb, p_scanned_at timestamptz, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_at timestamptz := coalesce(p_scanned_at, statement_timestamp());
        v_found jsonb := app.hr_card_lookup(p_property, p_telegram_user_id, p_scan ->> 'card',
            p_actor);
        v_mode text := upper(p_scan ->> 'mode');
        v_reason text := upper(p_scan ->> 'reason');
        v_text text := nullif(btrim(p_scan ->> 'reason_text'), '');
        v_file uuid := gen_random_uuid();
        v_result jsonb;
        v_scanner uuid;
    BEGIN
        IF NOT (v_found ->> 'ok')::boolean THEN
            RETURN v_found;
        END IF;
        IF v_mode IS NULL OR v_mode NOT IN ('IN', 'OUT') THEN
            RETURN app.hr_refuse('BAD_SCAN');
        END IF;
        IF v_reason IS NULL OR v_reason NOT IN ('NO_PHONE', 'PHONE_BROKEN', 'PHONE_LOST',
                'PHONE_STOLEN', 'OTHER') OR (v_reason = 'OTHER' AND v_text IS NULL) THEN
            RETURN app.hr_refuse('NEED_REASON');
        END IF;
        IF coalesce(jsonb_typeof(p_scan -> 'photo'), '') <> 'object' THEN
            RETURN app.hr_refuse('NEED_PHOTO');
        END IF;
        v_scanner := app.hr_linked_employee(p_property, p_telegram_user_id,
            timezone(app.hr_zone(), v_at)::date);
        BEGIN
            INSERT INTO app.stored_files (id, property_id, sha256, byte_size, media_type,
                original_name, storage_key, created_by)
            VALUES (v_file, p_property, p_scan #>> '{photo,sha256}',
                (p_scan #>> '{photo,byte_size}')::bigint, p_scan #>> '{photo,media_type}',
                'card-photo.jpg', p_scan #>> '{photo,storage_key}', p_actor);
        EXCEPTION WHEN check_violation OR not_null_violation OR data_exception THEN
            RETURN app.hr_refuse('NEED_PHOTO');
        END;
        v_result := app.hr_save_scan(p_property, (v_found ->> 'employee_id')::uuid, v_mode,
            'CARD', NULL, v_at, NULL, NULL, false, v_reason, left(v_text, 300), v_file, v_scanner,
            p_telegram_user_id, p_actor);
        IF NOT (v_result ->> 'ok')::boolean THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'hr-card-refused:' || (v_result ->> 'reason');
        END IF;
        RETURN v_result || (v_found - 'ok');
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE 'hr-card-refused:%' THEN
            RETURN app.hr_refuse(substr(SQLERRM, 17));
        END IF;
        RAISE;
    END $$;

    -- PR-HR-067: photos older than the rule are listed for the daily job, which deletes the file
    -- and records the removal.
    CREATE FUNCTION app.hr_photos_due(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.hr_require_service(p_actor, p_property);
    BEGIN
        RETURN coalesce((SELECT jsonb_agg(jsonb_build_object('file_id', file.id,
                'storage_key', file.storage_key) ORDER BY file.created_at)
            FROM app.attendance_scans AS scan
            JOIN app.stored_files AS file ON file.id = scan.photo_file_id
            WHERE file.property_id = p_property
              AND timezone(app.hr_zone(), file.created_at)::date
                  + app.hr_rule('ATT_PHOTO_DAYS', v_today, 90)::integer < v_today
              AND NOT EXISTS (SELECT 1 FROM app.stored_file_removals AS removal
                  WHERE removal.file_id = file.id)), '[]'::jsonb);
    END $$;

    CREATE FUNCTION app.hr_record_photo_removal(p_property uuid, p_file uuid, p_actor uuid)
    RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date := app.hr_require_service(p_actor, p_property);
    BEGIN
        INSERT INTO app.stored_file_removals (file_id, reason, removed_by)
        SELECT file.id, 'Card photo kept ' || app.hr_rule('ATT_PHOTO_DAYS', v_today, 90)
            || ' days', p_actor
        FROM app.stored_files AS file
        WHERE file.id = p_file AND file.property_id = p_property
        ON CONFLICT (file_id) DO NOTHING;
        PERFORM app.hr_audit(p_property, p_actor, 'hr.attendance.photo_removed', 'stored_file',
            p_file, 'Card photo removed after the rule', NULL, NULL,
            jsonb_build_object('file_id', p_file));
    END $$;

    -- PR-HR-055..058: the payroll list takes Days not worked and Overtime from the sheet.
    CREATE OR REPLACE FUNCTION app.hr_payroll_attendance_lines(p_run uuid, p_actor uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog SET jit = off AS $$
    DECLARE
        v_run app.payroll_runs%ROWTYPE;
        v_end date;
        v_days integer;
        v_person record;
        v_cut numeric;
        v_count integer;
        v_pay numeric;
        v_hours numeric;
        v_request record;
    BEGIN
        SELECT run.* INTO STRICT v_run FROM app.payroll_runs AS run WHERE run.id = p_run;
        v_end := (v_run.salary_month + interval '1 month' - interval '1 day')::date;
        v_days := extract(day FROM v_end)::integer;
        FOR v_person IN
            SELECT DISTINCT line.employee_id FROM app.payroll_lines AS line
            WHERE line.payroll_run_id = p_run AND line.component_code = 'BASE_SALARY'
        LOOP
            -- Absent without leave (rule) and Unpaid leave: one day's pay each.
            SELECT count(*), sum((app.hr_pay_on(v_person.employee_id, day::date))
                    .monthly_salary_usd_cents::numeric / v_days)
            INTO v_count, v_cut
            FROM generate_series(v_run.salary_month, v_end, interval '1 day') AS day
            WHERE app.hr_works_on(v_person.employee_id, day::date)
              AND ((app.hr_entry_on(v_person.employee_id, day::date)).status = 'LEAVE_UNPAID'
                OR ((app.hr_entry_on(v_person.employee_id, day::date)).status = 'ABSENT'
                    AND app.hr_rule('ATT_ABS_CUT', day::date, 1) = 1));
            IF v_count > 0 AND round(v_cut) > 0 THEN
                INSERT INTO app.payroll_lines (payroll_run_id, employee_id, component_code,
                    amount_usd_cents, days_worked, days_in_month, source, reason, created_by)
                VALUES (p_run, v_person.employee_id, 'DAYS_NOT_WORKED', round(v_cut)::bigint,
                    v_count, v_days, 'ATTENDANCE', v_count || ' day(s) absent or unpaid leave',
                    p_actor);
            END IF;
            -- Approved overtime at the rule rates; hourly rate = monthly salary / rule hours.
            v_pay := 0;
            v_hours := 0;
            FOR v_request IN
                SELECT request.work_date, hours.normal_hours, hours.night_hours
                FROM app.overtime_requests AS request
                CROSS JOIN LATERAL app.hr_overtime_hours(request.id) AS hours
                WHERE request.employee_id = v_person.employee_id
                  AND request.work_date BETWEEN v_run.salary_month AND v_end
                  AND app.hr_overtime_counts(request.id)
            LOOP
                v_pay := v_pay + (app.hr_pay_on(v_person.employee_id, v_request.work_date))
                        .monthly_salary_usd_cents::numeric
                    / app.hr_rule('ATT_HOURS', v_request.work_date, 208)
                    * (v_request.normal_hours * app.hr_rule('ATT_OT_PCT', v_request.work_date, 15000)
                        + v_request.night_hours * app.hr_rule('ATT_OT_NIGHT_PCT',
                            v_request.work_date, 20000)) / 10000;
                v_hours := v_hours + v_request.normal_hours + v_request.night_hours;
            END LOOP;
            IF round(v_pay) > 0 THEN
                INSERT INTO app.payroll_lines (payroll_run_id, employee_id, component_code,
                    amount_usd_cents, hours, source, reason, created_by)
                VALUES (p_run, v_person.employee_id, 'OVERTIME', round(v_pay)::bigint, v_hours,
                    'ATTENDANCE', v_hours || ' approved overtime hour(s)', p_actor);
            END IF;
        END LOOP;
    END $$;
"""

RUNTIME = (
    "app.hr_attendance_day(uuid, date, uuid)",
    "app.hr_attendance_week(uuid, date, uuid)",
    "app.hr_attendance_month(uuid, date, uuid)",
    "app.hr_attendance_entry(uuid, jsonb, uuid, uuid)",
    "app.hr_plan_day(uuid, jsonb, uuid, uuid)",
    "app.hr_request_overtime(uuid, jsonb, uuid, uuid)",
    "app.hr_decide_overtime(uuid, uuid, jsonb, uuid, uuid)",
    "app.hr_overtime_read(uuid, date, uuid)",
    "app.hr_accept_scan(uuid, uuid, text, uuid, uuid)",
    "app.hr_scan_photo_file(uuid, uuid, uuid)",
    "app.hr_attendance_places(uuid, uuid)",
    "app.hr_set_place_pin(uuid, uuid, double precision, double precision, text, uuid, uuid)",
    "app.hr_new_place_qr(uuid, uuid, text, uuid, uuid)",
    "app.hr_new_card_qr(uuid, uuid, text, uuid, uuid)",
    "app.hr_employee_card(uuid, uuid, uuid)",
    "app.record_staff_check_scan(uuid, bigint, jsonb, timestamptz, uuid)",
    "app.hr_card_lookup(uuid, bigint, text, uuid)",
    "app.record_card_check_scan(uuid, bigint, jsonb, timestamptz, uuid)",
    "app.hr_photos_due(uuid, uuid)",
    "app.hr_record_photo_removal(uuid, uuid, uuid)",
)


def upgrade() -> None:
    op.execute(TABLES)
    for table in APPEND_ONLY:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.reject_hr_change();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION app.reject_hr_change();
            """
        )
    place_rows = ",\n            ".join(
        f"({_text(code)}, {_text(en)}, {_text(km)}, {order})"
        for order, (code, en, km) in enumerate(PLACES, start=1)
    )
    op.execute(
        f"""
        INSERT INTO app.attendance_places (code, name_en, name_km, sort_order)
        VALUES
            {place_rows}
        """
    )
    op.execute(FUNCTIONS)
    op.execute(
        """
        CREATE TRIGGER attendance_entries_month_lock BEFORE INSERT ON app.attendance_entries
            FOR EACH ROW EXECUTE FUNCTION app.hr_attendance_lock();
        CREATE TRIGGER attendance_scans_month_lock BEFORE INSERT ON app.attendance_scans
            FOR EACH ROW EXECUTE FUNCTION app.hr_attendance_lock();
        """
    )
    _patch(RANGE, ((RANGE_BEFORE, RANGE_AFTER),))
    for code, unit, value, _, _, en, kh in RULES:
        op.execute(
            f"""
            WITH named AS (
                INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                    used_by_app)
                VALUES ({_text(code)}, {_text(en)}, {_text(kh)}, {_text(unit)}, 'ATTENDANCE',
                    {"false" if code == "ATT_LATE_CUT" else "true"})
                RETURNING id
            )
            INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
            SELECT named.id, {value}, DATE '2026-01-01', {_text(SEED_REASON)},
                (SELECT classification.actor_id FROM app.user_account_classes AS classification
                 WHERE classification.account_class = 'owner')
            FROM named
            """
        )
    tables = ", ".join(f"app.{name}" for name in APPEND_ONLY)
    op.execute(
        f"""
        REVOKE ALL ON TABLE {tables} FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.attendance_places TO prm_runtime;
        """
    )
    for signature in RUNTIME:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("HRIS attendance migration is forward-only")
