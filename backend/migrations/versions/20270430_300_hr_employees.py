# ruff: noqa: E501
"""HRIS phase 6 step 1 (owner 2026-11-04 16:01 "start HR coding"): rights, Employees, Telegram staff.

The design is the HRIS plan the owner approved: PRD 6uyMRkwFWddDGLA8WtWo5y (PR-HR-001..068),
database plan VhZTNVv9QHrEF7JXVXVg6W (approved 02/11/2026 20:55, attendance and QR parts
03/11/2026 09:07) and mock-up v72 (DESIGN.md 0.56).

1. Rights (Administration group, mock-up "Office" permissions EMP, SALARY and ATT):
   - See employees (hr.employees.read): Owner, Manager.
   - Employees, add, change, leaving, Telegram link (hr.employees.manage): Owner, Manager.
   - See salaries, salary loans and payroll (hr.salaries.read, hr.salaries.manage,
     hr.loans.prepare, hr.payroll.prepare): Owner; the Owner gives it to an Accountant role.
   - Approve salary loans and payroll, and pay salaries (hr.loans.approve, hr.payroll.approve,
     hr.payroll.pay): Owner only.
   - Attendance, daily sheet, weekly plan, overtime (hr.attendance.read, hr.attendance.manage,
     hr.overtime.approve): Owner, Manager.
   Staff have none of them.
2. Number types SALARY_LOAN (SLyy000n), PAYROLL (PAYyy000n) and OVERTIME (OTyy000n).
3. Lookup lists: job titles and the three shifts (Morning 06:30-15:30, Afternoon 14:30-23:30,
   Night 22:30-07:30).
4. Employees (E-001), their employment history (hired, job or shift change, leaving), salary and
   payment method, ID details, documents (files on the office computer, the database keeps the
   SHA-256 and size only), the Telegram staff requests and the Telegram links with a report role.
   History is never typed over: a change is a new row.
5. The ledger link agreed with the General Ledger plan: gl_journal_lines.employee_id points to
   employees.
6. Business rules in the area Staff: Salary paid on day 5 of the next month and the Salary loan
   limit of 50% of one month's salary.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270430_300"
down_revision: str | None = "20270527_289"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "hris-phase-1"
CAPABILITIES = (
    ("hr.employees.read", "See employees, their jobs, shifts and Telegram links"),
    ("hr.employees.manage", "Add employees, change job or shift, leaving, Telegram links"),
    ("hr.salaries.read", "See salaries, payment methods, ID details, loans and payroll"),
    ("hr.salaries.manage", "Change a salary, payment method or ID details"),
    ("hr.loans.prepare", "Enter a salary loan request and mark a loan paid out"),
    ("hr.loans.approve", "Approve or refuse a salary loan"),
    ("hr.payroll.prepare", "Check the payroll list, add lines and send it for approval"),
    ("hr.payroll.approve", "Approve the payroll or send it back"),
    ("hr.payroll.pay", "Mark salaries paid"),
    ("hr.attendance.read", "See the attendance sheet, weekly plan and overtime"),
    ("hr.attendance.manage", "Enter and fix attendance, plan shifts, ask for overtime"),
    ("hr.overtime.approve", "Approve or refuse overtime"),
)
# code, English, Khmer (mock-up pm_EMP, pm_SALARY, pm_ATT; two new names need a Khmer check)
PERMISSIONS = (
    ("HR_EMPLOYEES_SEE", "See employees", "មើលបុគ្គលិក", ("hr.employees.read",)),
    (
        "HR_EMPLOYEES",
        "Employees (add, change, leaving, Telegram link)",
        "បុគ្គលិក (បន្ថែម កែ ចាកចេញ ភ្ជាប់ Telegram)",
        ("hr.employees.manage",),
    ),
    (
        "HR_SALARIES",
        "See salaries, salary loans and payroll",
        "មើលប្រាក់ខែ ប្រាក់កម្ចីប្រាក់ខែ និងបញ្ជីប្រាក់ខែ",
        ("hr.salaries.read", "hr.salaries.manage", "hr.loans.prepare", "hr.payroll.prepare"),
    ),
    (
        "HR_PAY_APPROVE",
        "Approve salary loans and payroll, and pay salaries",
        "អនុម័តប្រាក់កម្ចីប្រាក់ខែ និងបញ្ជីប្រាក់ខែ ហើយបើកប្រាក់ខែ",
        ("hr.loans.approve", "hr.payroll.approve", "hr.payroll.pay"),
    ),
    (
        "HR_ATTENDANCE",
        "Attendance (daily sheet, weekly plan, overtime)",
        "វត្តមាន (តារាងប្រចាំថ្ងៃ ផែនការប្រចាំសប្ដាហ៍ ម៉ោងបន្ថែម)",
        ("hr.attendance.read", "hr.attendance.manage", "hr.overtime.approve"),
    ),
)
OWNER = tuple(name for name, _ in CAPABILITIES)
MANAGER = (
    "hr.employees.read",
    "hr.employees.manage",
    "hr.attendance.read",
    "hr.attendance.manage",
    "hr.overtime.approve",
)
OWNER_ONLY = tuple(name for name in OWNER if name not in MANAGER)
REASON = "Owner 2026-11-04: HRIS rights (Employees, salaries, payroll, attendance)"
SEED_REASON = "First value: the owner's HR rules (02/11/2026)"

SEED = "app.seed_default_role_bundles(uuid)"
MANAGER_BEFORE = "'products.prices']::text[]"
RANGE = "app.business_rules_program_range()"
RANGE_BEFORE = "OR (v_code = 'TR_AUTO_CLOSE_DAYS' AND NEW.value NOT BETWEEN 1 AND 30)"
RANGE_AFTER = (
    RANGE_BEFORE
    + "\n                OR (v_code = 'PAY_DAY' AND NEW.value NOT BETWEEN 1 AND 28)"
    + "\n                OR (v_code = 'LOAN_PCT' AND NEW.value NOT BETWEEN 1 AND 10000)"
)
# code, unit, value, English, Khmer (mock-up brn_PAY_DAY and brn_LOAN_PCT)
RULES = (
    ("PAY_DAY", "DAY_OF_MONTH", 5, "Salary paid on (next month)", "បើកប្រាក់ខែនៅ (ខែបន្ទាប់)"),
    (
        "LOAN_PCT",
        "PERCENT",
        5000,
        "Salary loan limit (of one month's salary)",
        "កម្រិតប្រាក់កម្ចីប្រាក់ខែ (នៃប្រាក់ខែមួយខែ)",
    ),
)
# code, English, Khmer (DB plan seed; the Owner adds more later)
JOB_TITLES = (
    ("MANAGER", "Manager", "អ្នកគ្រប់គ្រង"),
    ("FRONT_DESK", "Front desk", "បុគ្គលិកទទួលភ្ញៀវ"),
    ("ACCOUNTANT", "Accountant", "គណនេយ្យករ"),
    ("TECHNICIAN", "Technician", "ជាងបច្ចេកទេស"),
    ("CLEANER", "Cleaner", "អ្នកសម្អាត"),
    ("CARETAKER", "Property Caretaker", "អ្នកថែរក្សាអគារ"),
)
# code, starts, ends, English, Khmer (DB plan; Night ends the next day)
SHIFTS = (
    ("MORNING", "06:30", "15:30", "Morning", "វេនព្រឹក"),
    ("AFTERNOON", "14:30", "23:30", "Afternoon", "វេនរសៀល"),
    ("NIGHT", "22:30", "07:30", "Night", "វេនយប់"),
)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(names: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(_text(name) for name in names) + "]::text[]"


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
    -- Lookup lists (never deleted, only turned off).
    CREATE TABLE app.job_titles (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z][A-Z_]{1,40}$'),
        name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 80),
        name_km text NOT NULL CHECK (name_km = btrim(name_km) AND length(name_km) BETWEEN 1 AND 80),
        sort_order smallint NOT NULL UNIQUE CHECK (sort_order > 0),
        active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT statement_timestamp()
    );
    CREATE UNIQUE INDEX job_titles_name_key ON app.job_titles (lower(name_en));
    CREATE TABLE app.work_shifts (
        code text PRIMARY KEY CHECK (code IN ('MORNING', 'AFTERNOON', 'NIGHT')),
        starts_at time NOT NULL,
        ends_at time NOT NULL,
        name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 40),
        name_km text NOT NULL CHECK (name_km = btrim(name_km) AND length(name_km) BETWEEN 1 AND 40),
        sort_order smallint NOT NULL UNIQUE CHECK (sort_order > 0)
    );

    -- One row per person. The names and phone change only through app.hr_employee_step, which
    -- keeps the old values in the History (audit_events); facts that change over time live in
    -- the tables below.
    CREATE TABLE app.employees (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        employee_code text NOT NULL CHECK (employee_code ~ '^E-[0-9]{3,6}$'),
        name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 120),
        name_km text NOT NULL CHECK (name_km = btrim(name_km) AND length(name_km) BETWEEN 1 AND 120),
        phone text CHECK (phone = btrim(phone) AND length(phone) BETWEEN 6 AND 30),
        user_actor_id uuid UNIQUE REFERENCES app.user_accounts (actor_id) ON DELETE RESTRICT,
        version integer NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT employees_code_key UNIQUE (property_id, employee_code)
    );
    COMMENT ON TABLE app.employees IS 'HRIS phase 1: one row per employee (PR-HR-010).';

    -- Hired, job or shift change, leaving. Every row but LEFT carries the job, shift and usual
    -- day off from that day on (ISO day: 1 Monday .. 7 Sunday); the newest row on a day wins.
    CREATE TABLE app.employment_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        event_type text NOT NULL CHECK (event_type IN ('HIRED', 'JOB_CHANGE', 'SHIFT_CHANGE', 'LEFT')),
        effective_date date NOT NULL,
        job_title_id uuid REFERENCES app.job_titles (id) ON DELETE RESTRICT,
        shift_code text REFERENCES app.work_shifts (code) ON DELETE RESTRICT,
        usual_day_off smallint CHECK (usual_day_off BETWEEN 1 AND 7),
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT employment_events_shape CHECK (
            (event_type = 'LEFT' AND job_title_id IS NULL AND shift_code IS NULL
                AND usual_day_off IS NULL)
            OR (event_type <> 'LEFT' AND job_title_id IS NOT NULL AND shift_code IS NOT NULL
                AND usual_day_off IS NOT NULL))
    );
    CREATE INDEX employment_events_employee_idx
        ON app.employment_events (employee_id, effective_date DESC, created_at DESC);
    CREATE UNIQUE INDEX employment_events_one_hired ON app.employment_events (employee_id)
        WHERE event_type = 'HIRED';
    CREATE UNIQUE INDEX employment_events_one_left ON app.employment_events (employee_id)
        WHERE event_type = 'LEFT';

    -- Salary and how it is paid (See salaries only). A change is a new row; the newest row on
    -- or before a day is the salary of that day.
    CREATE TABLE app.employee_pay_terms (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        effective_date date NOT NULL,
        monthly_salary_usd_cents bigint NOT NULL CHECK (monthly_salary_usd_cents BETWEEN 1 AND 99999999),
        payment_method text NOT NULL CHECK (payment_method IN ('CASH_USD', 'ABA')),
        aba_account_name text CHECK (aba_account_name = btrim(aba_account_name)
            AND length(aba_account_name) BETWEEN 1 AND 120),
        aba_account_number text CHECK (aba_account_number ~ '^[0-9 ]{6,30}$'),
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT employee_pay_terms_aba CHECK ((payment_method = 'ABA')
            = (aba_account_name IS NOT NULL AND aba_account_number IS NOT NULL))
    );
    CREATE INDEX employee_pay_terms_employee_idx
        ON app.employee_pay_terms (employee_id, effective_date DESC, created_at DESC);

    -- ID details (See salaries only). A change is a new row.
    CREATE TABLE app.employee_identity_records (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        id_type text NOT NULL CHECK (id_type IN ('NATIONAL_ID', 'PASSPORT', 'OTHER')),
        id_number text NOT NULL CHECK (id_number = btrim(id_number) AND length(id_number) BETWEEN 1 AND 40),
        date_of_birth date CHECK (date_of_birth BETWEEN DATE '1920-01-01' AND DATE '2100-01-01'),
        home_address text CHECK (home_address = btrim(home_address)
            AND length(home_address) BETWEEN 1 AND 300),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX employee_identity_records_employee_idx
        ON app.employee_identity_records (employee_id, created_at DESC);

    -- Files kept in the private folder on the office computer (Q4): the database keeps what the
    -- file is, its SHA-256 and where it is, never the bytes.
    CREATE TABLE app.stored_files (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        byte_size bigint NOT NULL CHECK (byte_size BETWEEN 1 AND 20971520),
        media_type text NOT NULL CHECK (media_type IN ('image/jpeg', 'image/png', 'application/pdf')),
        original_name text NOT NULL CHECK (original_name = btrim(original_name)
            AND length(original_name) BETWEEN 1 AND 200),
        storage_key text NOT NULL UNIQUE CHECK (storage_key ~ '^[a-z0-9][a-z0-9/_.-]{10,200}$'
            AND storage_key !~ '[.][.]'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE TABLE app.employee_documents (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        file_id uuid NOT NULL UNIQUE REFERENCES app.stored_files (id) ON DELETE RESTRICT,
        document_kind text NOT NULL CHECK (document_kind IN ('ID_CARD', 'CONTRACT', 'CERTIFICATE', 'OTHER')),
        title text NOT NULL CHECK (title = btrim(title) AND length(title) BETWEEN 1 AND 120),
        expires_on date,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX employee_documents_employee_idx ON app.employee_documents (employee_id, created_at);
    CREATE TABLE app.employee_document_removals (
        employee_document_id uuid PRIMARY KEY REFERENCES app.employee_documents (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        removed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        removed_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );

    -- New staff from the staff bot (Start), and the Owner's or Manager's answer. The Telegram
    -- user id is the key; the Telegram tables of the bots are linked later (Telegram thread).
    CREATE TABLE app.telegram_staff_requests (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        given_name text NOT NULL CHECK (given_name = btrim(given_name) AND length(given_name) BETWEEN 1 AND 120),
        phone text CHECK (phone = btrim(phone) AND length(phone) BETWEEN 6 AND 30),
        received_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX telegram_staff_requests_user_idx
        ON app.telegram_staff_requests (telegram_user_id, received_at DESC);
    CREATE TABLE app.telegram_staff_request_decisions (
        request_id uuid PRIMARY KEY REFERENCES app.telegram_staff_requests (id) ON DELETE RESTRICT,
        decision text NOT NULL CHECK (decision IN ('LINKED', 'REFUSED')),
        employee_id uuid REFERENCES app.employees (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        decided_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_staff_request_decisions_shape
            CHECK ((decision = 'LINKED') = (employee_id IS NOT NULL))
    );

    -- One row per report role; a person may hold two roles. Unlinked by a row of
    -- employee_telegram_unlinks; a Left employee's links stop on the day after the end date.
    CREATE TABLE app.employee_telegram_links (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        report_role text NOT NULL CHECK (report_role IN
            ('CLEANER', 'TECHNICIAN', 'CARETAKER', 'METER_READER', 'AUTHORIZER')),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX employee_telegram_links_employee_idx ON app.employee_telegram_links (employee_id);
    CREATE INDEX employee_telegram_links_user_idx ON app.employee_telegram_links (telegram_user_id);
    CREATE TABLE app.employee_telegram_unlinks (
        telegram_link_id uuid PRIMARY KEY REFERENCES app.employee_telegram_links (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        unlinked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        unlinked_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );

    -- History is never changed or emptied.
    CREATE FUNCTION app.reject_hr_change() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        RAISE EXCEPTION 'HR history is never changed' USING ERRCODE = '55000';
    END $$;
    REVOKE ALL ON FUNCTION app.reject_hr_change() FROM PUBLIC;

    CREATE FUNCTION app.protect_employee() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF TG_OP <> 'UPDATE' OR NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
            OR NEW.employee_code <> OLD.employee_code OR NEW.created_at <> OLD.created_at
            OR NEW.created_by <> OLD.created_by OR NEW.version <> OLD.version + 1
        THEN
            RAISE EXCEPTION 'An employee record is never deleted or renumbered'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION app.protect_employee() FROM PUBLIC;
    CREATE TRIGGER employees_protect BEFORE UPDATE OR DELETE ON app.employees
        FOR EACH ROW EXECUTE FUNCTION app.protect_employee();
    CREATE TRIGGER employees_no_truncate BEFORE TRUNCATE ON app.employees
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_hr_change();
"""

APPEND_ONLY = (
    "job_titles",
    "work_shifts",
    "employment_events",
    "employee_pay_terms",
    "employee_identity_records",
    "stored_files",
    "employee_documents",
    "employee_document_removals",
    "telegram_staff_requests",
    "telegram_staff_request_decisions",
    "employee_telegram_links",
    "employee_telegram_unlinks",
)

FUNCTIONS = """
    CREATE FUNCTION app.hr_can(p_actor uuid, p_property uuid, p_capability text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT p_actor IS NOT NULL AND EXISTS (
            SELECT 1 FROM app.actor_capability_grants(p_actor) AS held
            WHERE held.capability_id = p_capability AND held.property_id = p_property)
    $$;
    REVOKE ALL ON FUNCTION app.hr_can(uuid, uuid, text) FROM PUBLIC;

    CREATE FUNCTION app.hr_is_owner(p_actor uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT EXISTS (SELECT 1 FROM app.user_account_classes AS classification
            WHERE classification.actor_id = p_actor AND classification.account_class = 'owner')
    $$;
    REVOKE ALL ON FUNCTION app.hr_is_owner(uuid) FROM PUBLIC;

    -- The bots run as a service actor (Telegram thread, 04/11/2026): no person's rights.
    CREATE FUNCTION app.hr_require_service(p_actor uuid, p_property uuid) RETURNS date
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_zone text;
    BEGIN
        SELECT property.timezone_name INTO v_zone FROM app.properties AS property
        WHERE property.id = p_property;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
        END IF;
        IF p_actor IS NULL OR NOT EXISTS (SELECT 1 FROM app.actor_identities AS actor
                WHERE actor.actor_id = p_actor AND actor.identity_kind = 'SERVICE') THEN
            RAISE EXCEPTION 'only the bot service may do this' USING ERRCODE = '42501';
        END IF;
        RETURN timezone(v_zone, statement_timestamp())::date;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_require_service(uuid, uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_audit(p_property uuid, p_actor uuid, p_action text, p_entity_type text,
        p_entity uuid, p_reason text, p_correlation uuid, p_before jsonb, p_after jsonb)
    RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_zone text;
        v_at timestamptz := statement_timestamp();
    BEGIN
        SELECT property.timezone_name INTO STRICT v_zone FROM app.properties AS property
        WHERE property.id = p_property;
        INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
            entity_type, entity_id, reason, property_id, previous_state, resulting_state,
            correlation_id, source, outcome)
        VALUES (gen_random_uuid(), v_at, timezone(v_zone, v_at)::date, p_actor, p_action,
            p_entity_type, p_entity, left(coalesce(nullif(btrim(p_reason), ''), p_action), 500),
            p_property, p_before, coalesce(p_after, '{}'::jsonb),
            coalesce(p_correlation, gen_random_uuid()), 'API', 'SUCCEEDED');
    END $$;
    REVOKE ALL ON FUNCTION app.hr_audit(uuid, uuid, text, text, uuid, text, uuid, jsonb, jsonb)
        FROM PUBLIC;

    -- The employee's job, shift and usual day off on a day (the newest row on or before it).
    CREATE FUNCTION app.hr_job_on(p_employee uuid, p_day date)
    RETURNS TABLE (job_title_id uuid, shift_code text, usual_day_off smallint)
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT event.job_title_id, event.shift_code, event.usual_day_off
        FROM app.employment_events AS event
        WHERE event.employee_id = p_employee AND event.event_type <> 'LEFT'
          AND event.effective_date <= p_day
        ORDER BY event.effective_date DESC, event.created_at DESC
        LIMIT 1
    $$;
    REVOKE ALL ON FUNCTION app.hr_job_on(uuid, date) FROM PUBLIC;

    CREATE FUNCTION app.hr_hired_on(p_employee uuid) RETURNS date
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT event.effective_date FROM app.employment_events AS event
        WHERE event.employee_id = p_employee AND event.event_type = 'HIRED'
    $$;
    REVOKE ALL ON FUNCTION app.hr_hired_on(uuid) FROM PUBLIC;

    -- The last working day, when a leaving was recorded.
    CREATE FUNCTION app.hr_left_on(p_employee uuid) RETURNS date
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT event.effective_date FROM app.employment_events AS event
        WHERE event.employee_id = p_employee AND event.event_type = 'LEFT'
    $$;
    REVOKE ALL ON FUNCTION app.hr_left_on(uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_works_on(p_employee uuid, p_day date) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT coalesce(app.hr_hired_on(p_employee) <= p_day, false)
            AND coalesce(app.hr_left_on(p_employee) >= p_day, true)
    $$;
    REVOKE ALL ON FUNCTION app.hr_works_on(uuid, date) FROM PUBLIC;

    CREATE FUNCTION app.hr_pay_on(p_employee uuid, p_day date) RETURNS app.employee_pay_terms
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT terms.* FROM app.employee_pay_terms AS terms
        WHERE terms.employee_id = p_employee AND terms.effective_date <= p_day
        ORDER BY terms.effective_date DESC, terms.created_at DESC
        LIMIT 1
    $$;
    REVOKE ALL ON FUNCTION app.hr_pay_on(uuid, date) FROM PUBLIC;

    -- A Telegram link works while it is not unlinked and the employee has not left.
    CREATE FUNCTION app.hr_link_live(p_link uuid, p_day date) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT NOT EXISTS (SELECT 1 FROM app.employee_telegram_unlinks AS unlink
                WHERE unlink.telegram_link_id = link.id)
            AND app.hr_works_on(link.employee_id, p_day)
        FROM app.employee_telegram_links AS link WHERE link.id = p_link
    $$;
    REVOKE ALL ON FUNCTION app.hr_link_live(uuid, date) FROM PUBLIC;

    CREATE FUNCTION app.hr_employee_json(p_employee uuid, p_day date, p_salaries boolean)
    RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object(
            'employee_id', employee.id,
            'employee_code', employee.employee_code,
            'name_en', employee.name_en,
            'name_km', employee.name_km,
            'phone', employee.phone,
            'version', employee.version,
            'user', CASE WHEN account.actor_id IS NULL THEN NULL ELSE jsonb_build_object(
                'actor_id', account.actor_id, 'username', account.normalized_username,
                'display_name', account.display_name, 'state', account.lifecycle_state) END,
            'hired_on', app.hr_hired_on(employee.id),
            'left_on', app.hr_left_on(employee.id),
            'state', CASE
                WHEN app.hr_hired_on(employee.id) > p_day THEN 'STARTS_LATER'
                WHEN app.hr_left_on(employee.id) < p_day THEN 'LEFT'
                WHEN app.hr_left_on(employee.id) IS NOT NULL THEN 'LEAVING'
                ELSE 'ACTIVE' END,
            'job_title', CASE WHEN title.id IS NULL THEN NULL ELSE jsonb_build_object(
                'id', title.id, 'code', title.code, 'name_en', title.name_en,
                'name_km', title.name_km) END,
            'shift_code', job.shift_code,
            'usual_day_off', job.usual_day_off,
            'telegram', coalesce((SELECT jsonb_agg(jsonb_build_object('link_id', link.id,
                    'telegram_user_id', link.telegram_user_id, 'report_role', link.report_role,
                    'linked_at', link.created_at) ORDER BY link.created_at)
                FROM app.employee_telegram_links AS link
                WHERE link.employee_id = employee.id AND app.hr_link_live(link.id, p_day)),
                '[]'::jsonb),
            'pay', CASE WHEN NOT p_salaries OR pay.id IS NULL THEN NULL ELSE jsonb_build_object(
                'monthly_salary_usd_cents', pay.monthly_salary_usd_cents,
                'payment_method', pay.payment_method,
                'aba_account_name', pay.aba_account_name,
                'aba_account_number', pay.aba_account_number,
                'effective_date', pay.effective_date) END
        )
        FROM app.employees AS employee
        LEFT JOIN app.user_accounts AS account ON account.actor_id = employee.user_actor_id
        LEFT JOIN LATERAL app.hr_job_on(employee.id, greatest(p_day,
            coalesce(app.hr_hired_on(employee.id), p_day))) AS job ON true
        LEFT JOIN app.job_titles AS title ON title.id = job.job_title_id
        LEFT JOIN LATERAL app.hr_pay_on(employee.id, greatest(p_day,
            coalesce(app.hr_hired_on(employee.id), p_day))) AS pay ON true
        WHERE employee.id = p_employee
    $$;
    REVOKE ALL ON FUNCTION app.hr_employee_json(uuid, date, boolean) FROM PUBLIC;

    CREATE FUNCTION app.hr_employees_read(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.employees.read', p_property);
        v_salaries boolean := app.hr_can(p_actor, p_property, 'hr.salaries.read');
    BEGIN
        RETURN coalesce((SELECT jsonb_agg(app.hr_employee_json(employee.id, v_day, v_salaries)
                ORDER BY employee.employee_code)
            FROM app.employees AS employee WHERE employee.property_id = p_property), '[]'::jsonb);
    END $$;

    CREATE FUNCTION app.hr_employee_read(p_property uuid, p_employee uuid, p_actor uuid,
        p_correlation uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.employees.read', p_property);
        v_salaries boolean := app.hr_can(p_actor, p_property, 'hr.salaries.read');
        v_result jsonb;
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.id = p_employee AND employee.property_id = p_property) THEN
            RAISE EXCEPTION 'The employee was not found' USING ERRCODE = '22023';
        END IF;
        v_result := app.hr_employee_json(p_employee, v_day, v_salaries) || jsonb_build_object(
            'can_see_salaries', v_salaries,
            'history', coalesce((SELECT jsonb_agg(jsonb_build_object('event_id', event.id,
                    'event_type', event.event_type, 'effective_date', event.effective_date,
                    'job_title_id', event.job_title_id, 'job_title_en', title.name_en,
                    'job_title_km', title.name_km, 'shift_code', event.shift_code,
                    'usual_day_off', event.usual_day_off, 'reason', event.reason,
                    'at', event.created_at, 'by', account.display_name)
                    ORDER BY event.effective_date DESC, event.created_at DESC)
                FROM app.employment_events AS event
                LEFT JOIN app.job_titles AS title ON title.id = event.job_title_id
                LEFT JOIN app.user_accounts AS account ON account.actor_id = event.created_by
                WHERE event.employee_id = p_employee), '[]'::jsonb),
            'pay_history', CASE WHEN v_salaries THEN coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'pay_term_id', terms.id, 'effective_date', terms.effective_date,
                    'monthly_salary_usd_cents', terms.monthly_salary_usd_cents,
                    'payment_method', terms.payment_method,
                    'aba_account_name', terms.aba_account_name,
                    'aba_account_number', terms.aba_account_number, 'reason', terms.reason,
                    'at', terms.created_at, 'by', account.display_name)
                    ORDER BY terms.effective_date DESC, terms.created_at DESC)
                FROM app.employee_pay_terms AS terms
                LEFT JOIN app.user_accounts AS account ON account.actor_id = terms.created_by
                WHERE terms.employee_id = p_employee), '[]'::jsonb) END,
            'identity', CASE WHEN v_salaries THEN (SELECT jsonb_build_object(
                    'id_type', record.id_type, 'id_number', record.id_number,
                    'date_of_birth', record.date_of_birth, 'home_address', record.home_address,
                    'at', record.created_at)
                FROM app.employee_identity_records AS record
                WHERE record.employee_id = p_employee
                ORDER BY record.created_at DESC LIMIT 1) END,
            'documents', coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'document_id', document.id, 'kind', document.document_kind,
                    'title', document.title, 'expires_on', document.expires_on,
                    'media_type', file.media_type, 'byte_size', file.byte_size,
                    'original_name', file.original_name, 'at', document.created_at)
                    ORDER BY document.created_at DESC)
                FROM app.employee_documents AS document
                JOIN app.stored_files AS file ON file.id = document.file_id
                WHERE document.employee_id = p_employee
                  AND (v_salaries OR document.document_kind <> 'ID_CARD')
                  AND NOT EXISTS (SELECT 1 FROM app.employee_document_removals AS removal
                      WHERE removal.employee_document_id = document.id)), '[]'::jsonb),
            'telegram_history', coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'link_id', link.id, 'telegram_user_id', link.telegram_user_id,
                    'report_role', link.report_role, 'linked_at', link.created_at,
                    'unlinked_at', unlink.unlinked_at, 'unlink_reason', unlink.reason)
                    ORDER BY link.created_at DESC)
                FROM app.employee_telegram_links AS link
                LEFT JOIN app.employee_telegram_unlinks AS unlink
                    ON unlink.telegram_link_id = link.id
                WHERE link.employee_id = p_employee), '[]'::jsonb));
        -- Every read of salaries and ID details by someone other than the Owner is in History.
        IF v_salaries AND NOT app.hr_is_owner(p_actor) THEN
            PERFORM app.hr_audit(p_property, p_actor, 'hr.employee.private_read', 'employee',
                p_employee, 'Opened salary and ID details', p_correlation, NULL,
                jsonb_build_object('employee_id', p_employee));
        END IF;
        RETURN v_result;
    END $$;

    CREATE FUNCTION app.hr_next_employee_code(p_property uuid) RETURNS text
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT 'E-' || lpad((coalesce(max(substr(employee.employee_code, 3)::integer), 0) + 1)::text,
            3, '0')
        FROM app.employees AS employee WHERE employee.property_id = p_property
    $$;
    REVOKE ALL ON FUNCTION app.hr_next_employee_code(uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_choices(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.employees.read', p_property);
    BEGIN
        RETURN jsonb_build_object(
            'today', v_day,
            'next_employee_code', app.hr_next_employee_code(p_property),
            'job_titles', coalesce((SELECT jsonb_agg(jsonb_build_object('id', title.id,
                    'code', title.code, 'name_en', title.name_en, 'name_km', title.name_km)
                    ORDER BY title.sort_order)
                FROM app.job_titles AS title WHERE title.active), '[]'::jsonb),
            'shifts', (SELECT jsonb_agg(jsonb_build_object('code', shift.code,
                    'starts_at', to_char(shift.starts_at, 'HH24:MI'),
                    'ends_at', to_char(shift.ends_at, 'HH24:MI'),
                    'name_en', shift.name_en, 'name_km', shift.name_km) ORDER BY shift.sort_order)
                FROM app.work_shifts AS shift),
            'free_users', coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'actor_id', account.actor_id, 'username', account.normalized_username,
                    'display_name', account.display_name) ORDER BY account.display_name)
                FROM app.user_accounts AS account
                WHERE account.lifecycle_state = 'active'
                  AND NOT EXISTS (SELECT 1 FROM app.employees AS employee
                      WHERE employee.user_actor_id = account.actor_id)), '[]'::jsonb),
            'can_manage', app.hr_can(p_actor, p_property, 'hr.employees.manage'),
            'can_see_salaries', app.hr_can(p_actor, p_property, 'hr.salaries.read'),
            'can_change_salaries', app.hr_can(p_actor, p_property, 'hr.salaries.manage'),
            'is_owner', app.hr_is_owner(p_actor),
            'pay_day', coalesce(app.business_rule_value('PAY_DAY', v_day), 5),
            'loan_pct', coalesce(app.business_rule_value('LOAN_PCT', v_day), 5000));
    END $$;

    CREATE FUNCTION app.hr_date(p_body jsonb, p_key text, p_message text) RETURNS date
    LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
    BEGIN
        IF p_body -> p_key IS NULL OR jsonb_typeof(p_body -> p_key) = 'null' THEN
            RETURN NULL;
        END IF;
        RETURN (p_body ->> p_key)::date;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION '%', p_message USING ERRCODE = '22023';
    END $$;
    REVOKE ALL ON FUNCTION app.hr_date(jsonb, text, text) FROM PUBLIC;

    CREATE FUNCTION app.hr_uuid(p_body jsonb, p_key text, p_message text) RETURNS uuid
    LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
    BEGIN
        IF p_body -> p_key IS NULL OR jsonb_typeof(p_body -> p_key) = 'null' THEN
            RETURN NULL;
        END IF;
        RETURN (p_body ->> p_key)::uuid;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION '%', p_message USING ERRCODE = '22023';
    END $$;
    REVOKE ALL ON FUNCTION app.hr_uuid(jsonb, text, text) FROM PUBLIC;

    CREATE FUNCTION app.hr_cents(p_body jsonb, p_key text, p_message text) RETURNS bigint
    LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
    BEGIN
        IF p_body -> p_key IS NULL OR jsonb_typeof(p_body -> p_key) = 'null' THEN
            RETURN NULL;
        END IF;
        IF jsonb_typeof(p_body -> p_key) <> 'number' OR (p_body ->> p_key)::numeric
                <> trunc((p_body ->> p_key)::numeric) OR (p_body ->> p_key)::numeric < 1
                OR (p_body ->> p_key)::numeric > 99999999 THEN
            RAISE EXCEPTION '%', p_message USING ERRCODE = '22023';
        END IF;
        RETURN (p_body ->> p_key)::bigint;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_cents(jsonb, text, text) FROM PUBLIC;

    -- Job, shift and day off from a form; the old values fill what the form leaves out.
    CREATE FUNCTION app.hr_job_from(p_body jsonb, p_old_title uuid, p_old_shift text,
        p_old_day smallint) RETURNS TABLE (job_title_id uuid, shift_code text, usual_day_off smallint)
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_title uuid := coalesce(app.hr_uuid(p_body, 'job_title_id', 'Choose the job'), p_old_title);
        v_shift text := coalesce(app.problem_text(p_body, 'shift_code', 20, 'Choose the shift'),
            p_old_shift);
        v_day smallint;
    BEGIN
        BEGIN
            v_day := coalesce((p_body ->> 'usual_day_off')::smallint, p_old_day);
        EXCEPTION WHEN data_exception THEN
            RAISE EXCEPTION 'Choose the usual day off' USING ERRCODE = '22023';
        END;
        IF v_title IS NULL OR NOT EXISTS (SELECT 1 FROM app.job_titles AS title
                WHERE title.id = v_title AND (title.active OR title.id = p_old_title)) THEN
            RAISE EXCEPTION 'Choose the job' USING ERRCODE = '22023';
        END IF;
        IF v_shift IS NULL OR NOT EXISTS (SELECT 1 FROM app.work_shifts AS shift
                WHERE shift.code = v_shift) THEN
            RAISE EXCEPTION 'Choose the shift' USING ERRCODE = '22023';
        END IF;
        IF v_day IS NULL OR v_day NOT BETWEEN 1 AND 7 THEN
            RAISE EXCEPTION 'Choose the usual day off' USING ERRCODE = '22023';
        END IF;
        RETURN QUERY SELECT v_title, v_shift, v_day;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_job_from(jsonb, uuid, text, smallint) FROM PUBLIC;

    CREATE FUNCTION app.hr_add_pay_terms(p_employee uuid, p_body jsonb, p_from date,
        p_reason text, p_actor uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_id uuid := gen_random_uuid();
        v_salary bigint := app.hr_cents(p_body, 'monthly_salary_usd_cents',
            'The salary is a whole number of cents from 1 to 99,999,999');
        v_method text := app.problem_text(p_body, 'payment_method', 20, 'Choose cash or ABA');
        v_name text := app.problem_text(p_body, 'aba_account_name', 120,
            'The ABA account name is at most 120 letters');
        v_number text := app.problem_text(p_body, 'aba_account_number', 30,
            'The ABA account number has 6 to 30 digits');
    BEGIN
        IF v_salary IS NULL THEN
            RAISE EXCEPTION 'Enter the monthly salary' USING ERRCODE = '22023';
        END IF;
        IF v_method IS NULL OR v_method NOT IN ('CASH_USD', 'ABA') THEN
            RAISE EXCEPTION 'Choose cash or ABA' USING ERRCODE = '22023';
        END IF;
        IF v_method = 'ABA' AND (v_name IS NULL OR v_number IS NULL
                OR v_number !~ '^[0-9 ]{6,30}$') THEN
            RAISE EXCEPTION 'Enter the ABA account name and number' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.employee_pay_terms (id, employee_id, effective_date,
            monthly_salary_usd_cents, payment_method, aba_account_name, aba_account_number,
            reason, created_by)
        VALUES (v_id, p_employee, p_from, v_salary, v_method,
            CASE WHEN v_method = 'ABA' THEN v_name END,
            CASE WHEN v_method = 'ABA' THEN v_number END, p_reason, p_actor);
        RETURN v_id;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_add_pay_terms(uuid, jsonb, date, text, uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_add_identity(p_employee uuid, p_body jsonb, p_actor uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_id uuid := gen_random_uuid();
        v_type text := app.problem_text(p_body, 'id_type', 20, 'Choose the ID type');
        v_number text := app.problem_text(p_body, 'id_number', 40, 'The ID number is at most 40 letters');
    BEGIN
        IF v_type IS NULL OR v_type NOT IN ('NATIONAL_ID', 'PASSPORT', 'OTHER') THEN
            RAISE EXCEPTION 'Choose the ID type' USING ERRCODE = '22023';
        END IF;
        IF v_number IS NULL THEN
            RAISE EXCEPTION 'Enter the ID number' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.employee_identity_records (id, employee_id, id_type, id_number,
            date_of_birth, home_address, created_by)
        VALUES (v_id, p_employee, v_type, v_number,
            app.hr_date(p_body, 'date_of_birth', 'The date of birth is not a date'),
            app.problem_text(p_body, 'home_address', 300, 'The address is at most 300 letters'),
            p_actor);
        RETURN v_id;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_add_identity(uuid, jsonb, uuid) FROM PUBLIC;

    -- Add an employee: names, job, shift, usual day off and start date; the salary and ID
    -- details only with the salary right (PR-HR-011; "Someone with See salaries adds the salary
    -- later").
    CREATE FUNCTION app.hr_add_employee(p_property uuid, p_body jsonb, p_actor uuid,
        p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.employees.manage', p_property);
        v_id uuid := gen_random_uuid();
        v_code text;
        v_name_en text;
        v_name_km text;
        v_phone text;
        v_user uuid;
        v_start date;
        v_job record;
        v_reason text;
    BEGIN
        IF p_body IS NULL OR jsonb_typeof(p_body) <> 'object' THEN
            RAISE EXCEPTION 'The employee is invalid' USING ERRCODE = '22023';
        END IF;
        v_name_en := app.problem_text(p_body, 'name_en', 120, 'The English name is at most 120 letters');
        v_name_km := app.problem_text(p_body, 'name_km', 120, 'The Khmer name is at most 120 letters');
        v_phone := app.problem_text(p_body, 'phone', 30, 'The phone number is 6 to 30 letters');
        v_user := app.hr_uuid(p_body, 'user_actor_id', 'Choose the app user');
        v_start := app.hr_date(p_body, 'start_date', 'The start date is not a date');
        v_reason := coalesce(app.problem_text(p_body, 'reason', 500, 'The note is at most 500 letters'),
            'New employee');
        IF v_name_en IS NULL OR v_name_km IS NULL THEN
            RAISE EXCEPTION 'Enter the name in English and in Khmer' USING ERRCODE = '22023';
        END IF;
        IF v_phone IS NOT NULL AND length(v_phone) < 6 THEN
            RAISE EXCEPTION 'The phone number is 6 to 30 letters' USING ERRCODE = '22023';
        END IF;
        IF v_start IS NULL THEN
            RAISE EXCEPTION 'Enter the start date' USING ERRCODE = '22023';
        END IF;
        SELECT * INTO v_job FROM app.hr_job_from(p_body, NULL, NULL, NULL);
        IF v_user IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.user_accounts AS account
                WHERE account.actor_id = v_user) THEN
            RAISE EXCEPTION 'Choose the app user' USING ERRCODE = '22023';
        END IF;
        IF v_user IS NOT NULL AND EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.user_actor_id = v_user) THEN
            RAISE EXCEPTION 'This app user already belongs to another employee'
                USING ERRCODE = '23505';
        END IF;
        IF (p_body ? 'pay' AND jsonb_typeof(p_body -> 'pay') = 'object'
                OR p_body ? 'identity' AND jsonb_typeof(p_body -> 'identity') = 'object')
            AND NOT app.hr_can(p_actor, p_property, 'hr.salaries.manage') THEN
            RAISE EXCEPTION 'Only someone with See salaries adds the salary and ID details'
                USING ERRCODE = '42501';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('hr-employee-code:' || p_property, 0));
        v_code := coalesce(app.problem_text(p_body, 'employee_code', 8, 'The code looks like E-001'),
            app.hr_next_employee_code(p_property));
        IF v_code !~ '^E-[0-9]{3,6}$' THEN
            RAISE EXCEPTION 'The code looks like E-001' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.property_id = p_property AND employee.employee_code = v_code) THEN
            RAISE EXCEPTION 'Employee code % is already used', v_code USING ERRCODE = '23505';
        END IF;
        INSERT INTO app.employees (id, property_id, employee_code, name_en, name_km, phone,
            user_actor_id, created_by)
        VALUES (v_id, p_property, v_code, v_name_en, v_name_km, v_phone, v_user, p_actor);
        INSERT INTO app.employment_events (employee_id, event_type, effective_date, job_title_id,
            shift_code, usual_day_off, reason, created_by)
        VALUES (v_id, 'HIRED', v_start, v_job.job_title_id, v_job.shift_code, v_job.usual_day_off,
            v_reason, p_actor);
        IF jsonb_typeof(p_body -> 'pay') = 'object' THEN
            PERFORM app.hr_add_pay_terms(v_id, p_body -> 'pay', v_start, v_reason, p_actor);
        END IF;
        IF jsonb_typeof(p_body -> 'identity') = 'object' THEN
            PERFORM app.hr_add_identity(v_id, p_body -> 'identity', p_actor);
        END IF;
        PERFORM app.hr_audit(p_property, p_actor, 'hr.employee.added', 'employee', v_id, v_reason,
            p_correlation, NULL, jsonb_build_object('employee_code', v_code, 'name_en', v_name_en,
                'start_date', v_start, 'job_title_id', v_job.job_title_id,
                'shift_code', v_job.shift_code, 'salary_added', p_body ? 'pay'));
        RETURN v_id;
    END $$;

    -- One change to an employee. DETAILS (names, phone, app user), JOB (job, shift, usual day off
    -- from a day), LEAVE (the last working day), PAY (salary and payment method from a day),
    -- IDENTITY, TELEGRAM_LINK, TELEGRAM_UNLINK and DOCUMENT_REMOVE.
    CREATE FUNCTION app.hr_employee_step(p_property uuid, p_employee uuid, p_version integer,
        p_step text, p_body jsonb, p_actor uuid, p_correlation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_right text := CASE WHEN p_step IN ('PAY', 'IDENTITY') THEN 'hr.salaries.manage'
            ELSE 'hr.employees.manage' END;
        v_day date := app.require_product_right(p_actor, v_right, p_property);
        v_employee app.employees%ROWTYPE;
        v_body jsonb := coalesce(p_body, '{}'::jsonb);
        v_reason text := app.problem_text(coalesce(p_body, '{}'::jsonb), 'reason', 500,
            'The reason is at most 500 letters');
        v_from date := app.hr_date(coalesce(p_body, '{}'::jsonb), 'effective_date',
            'The date is not a date');
        v_old record;
        v_job record;
        v_user uuid;
        v_link uuid;
        v_telegram bigint;
        v_role text;
        v_type text;
        v_left date;
        v_document uuid;
        v_before jsonb;
        v_after jsonb;
    BEGIN
        IF jsonb_typeof(v_body) <> 'object' THEN
            RAISE EXCEPTION 'The change is invalid' USING ERRCODE = '22023';
        END IF;
        SELECT employee.* INTO v_employee FROM app.employees AS employee
        WHERE employee.id = p_employee AND employee.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The employee was not found' USING ERRCODE = '22023';
        END IF;
        IF p_version IS NOT NULL AND v_employee.version <> p_version THEN
            RAISE EXCEPTION 'Someone else changed this employee: open it again'
                USING ERRCODE = '40001';
        END IF;
        IF v_reason IS NULL AND p_step <> 'DETAILS' THEN
            RAISE EXCEPTION 'Say why' USING ERRCODE = '22023';
        END IF;
        v_left := app.hr_left_on(p_employee);
        IF p_step = 'DETAILS' THEN
            v_user := CASE WHEN v_body ? 'user_actor_id' THEN app.hr_uuid(v_body, 'user_actor_id',
                'Choose the app user') ELSE v_employee.user_actor_id END;
            IF v_user IS NOT NULL AND v_user IS DISTINCT FROM v_employee.user_actor_id AND (
                    NOT EXISTS (SELECT 1 FROM app.user_accounts AS account
                        WHERE account.actor_id = v_user)
                    OR EXISTS (SELECT 1 FROM app.employees AS other
                        WHERE other.user_actor_id = v_user)) THEN
                RAISE EXCEPTION 'This app user already belongs to another employee'
                    USING ERRCODE = '23505';
            END IF;
            v_before := jsonb_build_object('name_en', v_employee.name_en, 'name_km',
                v_employee.name_km, 'phone', v_employee.phone, 'user_actor_id',
                v_employee.user_actor_id);
            UPDATE app.employees AS employee SET
                name_en = coalesce(app.problem_text(v_body, 'name_en', 120,
                    'The English name is at most 120 letters'), employee.name_en),
                name_km = coalesce(app.problem_text(v_body, 'name_km', 120,
                    'The Khmer name is at most 120 letters'), employee.name_km),
                phone = CASE WHEN v_body ? 'phone' THEN app.problem_text(v_body, 'phone', 30,
                    'The phone number is 6 to 30 letters') ELSE employee.phone END,
                user_actor_id = v_user,
                version = employee.version + 1
            WHERE employee.id = p_employee
            RETURNING jsonb_build_object('name_en', employee.name_en, 'name_km', employee.name_km,
                'phone', employee.phone, 'user_actor_id', employee.user_actor_id) INTO v_after;
            PERFORM app.hr_audit(p_property, p_actor, 'hr.employee.details_changed', 'employee',
                p_employee, coalesce(v_reason, 'Details changed'), p_correlation, v_before, v_after);
            RETURN;
        END IF;
        IF p_step = 'JOB' THEN
            IF v_from IS NULL THEN
                RAISE EXCEPTION 'Enter the date it starts' USING ERRCODE = '22023';
            END IF;
            IF v_from < app.hr_hired_on(p_employee) OR v_from > coalesce(v_left, v_from) THEN
                RAISE EXCEPTION 'The date is outside the employment' USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_old FROM app.hr_job_on(p_employee, v_from);
            SELECT * INTO v_job FROM app.hr_job_from(v_body, v_old.job_title_id, v_old.shift_code,
                v_old.usual_day_off);
            IF v_job.job_title_id = v_old.job_title_id AND v_job.shift_code = v_old.shift_code
                    AND v_job.usual_day_off = v_old.usual_day_off THEN
                RAISE EXCEPTION 'Nothing changed' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.employment_events (employee_id, event_type, effective_date,
                job_title_id, shift_code, usual_day_off, reason, created_by)
            VALUES (p_employee, CASE WHEN v_job.job_title_id = v_old.job_title_id
                    THEN 'SHIFT_CHANGE' ELSE 'JOB_CHANGE' END, v_from, v_job.job_title_id,
                v_job.shift_code, v_job.usual_day_off, v_reason, p_actor);
            v_before := to_jsonb(v_old);
            v_after := to_jsonb(v_job) || jsonb_build_object('effective_date', v_from);
        ELSIF p_step = 'LEAVE' THEN
            IF v_left IS NOT NULL THEN
                RAISE EXCEPTION 'The leaving is already recorded' USING ERRCODE = '55000';
            END IF;
            IF v_from IS NULL OR v_from < app.hr_hired_on(p_employee) THEN
                RAISE EXCEPTION 'Enter the last working day' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.employment_events (employee_id, event_type, effective_date, reason,
                created_by)
            VALUES (p_employee, 'LEFT', v_from, v_reason, p_actor);
            v_after := jsonb_build_object('last_working_day', v_from);
        ELSIF p_step = 'PAY' THEN
            IF v_from IS NULL THEN
                RAISE EXCEPTION 'Enter the date the salary starts' USING ERRCODE = '22023';
            END IF;
            IF v_from < app.hr_hired_on(p_employee) OR v_from > coalesce(v_left, v_from) THEN
                RAISE EXCEPTION 'The date is outside the employment' USING ERRCODE = '22023';
            END IF;
            v_before := to_jsonb(app.hr_pay_on(p_employee, v_from)) - 'created_by';
            PERFORM app.hr_add_pay_terms(p_employee, v_body, v_from, v_reason, p_actor);
            v_after := to_jsonb(app.hr_pay_on(p_employee, v_from)) - 'created_by';
        ELSIF p_step = 'IDENTITY' THEN
            PERFORM app.hr_add_identity(p_employee, v_body, p_actor);
            v_after := jsonb_build_object('id_type', v_body ->> 'id_type');
        ELSIF p_step = 'TELEGRAM_LINK' THEN
            IF NOT app.hr_works_on(p_employee, v_day) THEN
                RAISE EXCEPTION 'Only a working employee is linked to Telegram'
                    USING ERRCODE = '55000';
            END IF;
            BEGIN
                v_telegram := (v_body ->> 'telegram_user_id')::bigint;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'The Telegram user id is a number' USING ERRCODE = '22023';
            END;
            v_role := app.problem_text(v_body, 'report_role', 20, 'Choose the report role');
            PERFORM app.hr_link_telegram(p_property, p_employee, v_telegram, v_role, p_actor);
            v_after := jsonb_build_object('telegram_user_id', v_telegram, 'report_role', v_role);
        ELSIF p_step = 'TELEGRAM_UNLINK' THEN
            v_link := app.hr_uuid(v_body, 'link_id', 'Choose the Telegram link');
            IF NOT EXISTS (SELECT 1 FROM app.employee_telegram_links AS link
                    WHERE link.id = v_link AND link.employee_id = p_employee)
                OR EXISTS (SELECT 1 FROM app.employee_telegram_unlinks AS unlink
                    WHERE unlink.telegram_link_id = v_link) THEN
                RAISE EXCEPTION 'The Telegram link is not live' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.employee_telegram_unlinks (telegram_link_id, reason, unlinked_by)
            VALUES (v_link, v_reason, p_actor);
            v_after := jsonb_build_object('link_id', v_link);
        ELSIF p_step = 'DOCUMENT_REMOVE' THEN
            v_document := app.hr_uuid(v_body, 'document_id', 'Choose the document');
            SELECT document.document_kind INTO v_type FROM app.employee_documents AS document
            WHERE document.id = v_document AND document.employee_id = p_employee
              AND NOT EXISTS (SELECT 1 FROM app.employee_document_removals AS removal
                  WHERE removal.employee_document_id = document.id);
            IF NOT FOUND THEN
                RAISE EXCEPTION 'The document was not found' USING ERRCODE = '22023';
            END IF;
            IF v_type = 'ID_CARD' AND NOT app.hr_can(p_actor, p_property, 'hr.salaries.manage') THEN
                RAISE EXCEPTION 'Only someone with See salaries removes an ID document'
                    USING ERRCODE = '42501';
            END IF;
            INSERT INTO app.employee_document_removals (employee_document_id, reason, removed_by)
            VALUES (v_document, v_reason, p_actor);
            v_after := jsonb_build_object('document_id', v_document);
        ELSE
            RAISE EXCEPTION 'Unknown change' USING ERRCODE = '22023';
        END IF;
        UPDATE app.employees AS employee SET version = employee.version + 1
        WHERE employee.id = p_employee;
        PERFORM app.hr_audit(p_property, p_actor, 'hr.employee.' || lower(p_step), 'employee',
            p_employee, v_reason, p_correlation, v_before, v_after);
    END $$;

    -- A Telegram user belongs to one employee while linked; Authorizer only from the Owner
    -- (owner 24/10/2026).
    CREATE FUNCTION app.hr_link_telegram(p_property uuid, p_employee uuid, p_telegram bigint,
        p_role text, p_actor uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_id uuid := gen_random_uuid();
    BEGIN
        SELECT timezone(property.timezone_name, statement_timestamp())::date INTO STRICT v_day
        FROM app.properties AS property WHERE property.id = p_property;
        IF p_telegram IS NULL OR p_telegram <= 0 THEN
            RAISE EXCEPTION 'The Telegram user id is a number' USING ERRCODE = '22023';
        END IF;
        IF p_role IS NULL OR p_role NOT IN ('CLEANER', 'TECHNICIAN', 'CARETAKER', 'METER_READER',
                'AUTHORIZER') THEN
            RAISE EXCEPTION 'Choose the report role' USING ERRCODE = '22023';
        END IF;
        IF p_role = 'AUTHORIZER' AND NOT app.hr_is_owner(p_actor) THEN
            RAISE EXCEPTION 'Only the Owner gives the Authorizer role' USING ERRCODE = '42501';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('hr-telegram:' || p_telegram, 0));
        IF EXISTS (SELECT 1 FROM app.employee_telegram_links AS link
                WHERE link.telegram_user_id = p_telegram AND link.employee_id <> p_employee
                  AND app.hr_link_live(link.id, v_day)) THEN
            RAISE EXCEPTION 'This Telegram account is linked to another employee'
                USING ERRCODE = '23505';
        END IF;
        IF EXISTS (SELECT 1 FROM app.employee_telegram_links AS link
                WHERE link.telegram_user_id = p_telegram AND link.employee_id = p_employee
                  AND link.report_role = p_role AND app.hr_link_live(link.id, v_day)) THEN
            RAISE EXCEPTION 'The employee already has this report role' USING ERRCODE = '23505';
        END IF;
        INSERT INTO app.employee_telegram_links (id, employee_id, telegram_user_id, report_role,
            created_by)
        VALUES (v_id, p_employee, p_telegram, p_role, p_actor);
        RETURN v_id;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_link_telegram(uuid, uuid, bigint, text, uuid) FROM PUBLIC;

    -- A document file is saved by the API first; this keeps what it is (PR-HR-014).
    CREATE FUNCTION app.hr_add_employee_document(p_property uuid, p_employee uuid, p_body jsonb,
        p_actor uuid, p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.employees.manage', p_property);
        v_kind text := app.problem_text(p_body, 'kind', 20, 'Choose the document kind');
        v_title text := app.problem_text(p_body, 'title', 120, 'The title is at most 120 letters');
        v_file uuid := gen_random_uuid();
        v_id uuid := gen_random_uuid();
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.id = p_employee AND employee.property_id = p_property) THEN
            RAISE EXCEPTION 'The employee was not found' USING ERRCODE = '22023';
        END IF;
        IF v_kind IS NULL OR v_kind NOT IN ('ID_CARD', 'CONTRACT', 'CERTIFICATE', 'OTHER') THEN
            RAISE EXCEPTION 'Choose the document kind' USING ERRCODE = '22023';
        END IF;
        IF v_kind = 'ID_CARD' AND NOT app.hr_can(p_actor, p_property, 'hr.salaries.manage') THEN
            RAISE EXCEPTION 'Only someone with See salaries adds an ID document'
                USING ERRCODE = '42501';
        END IF;
        IF v_title IS NULL THEN
            RAISE EXCEPTION 'Enter the title' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.stored_files (id, property_id, sha256, byte_size, media_type,
            original_name, storage_key, created_by)
        VALUES (v_file, p_property, p_body ->> 'sha256', (p_body ->> 'byte_size')::bigint,
            p_body ->> 'media_type', p_body ->> 'original_name', p_body ->> 'storage_key', p_actor);
        INSERT INTO app.employee_documents (id, employee_id, file_id, document_kind, title,
            expires_on, created_by)
        VALUES (v_id, p_employee, v_file, v_kind, v_title,
            app.hr_date(p_body, 'expires_on', 'The end date is not a date'), p_actor);
        UPDATE app.employees AS employee SET version = employee.version + 1
        WHERE employee.id = p_employee;
        PERFORM app.hr_audit(p_property, p_actor, 'hr.employee.document_added', 'employee',
            p_employee, v_title, p_correlation, NULL, jsonb_build_object('document_id', v_id,
                'kind', v_kind, 'sha256', p_body ->> 'sha256'));
        RETURN v_id;
    END $$;

    -- Where a document file is, for the API to send it after the right check.
    CREATE FUNCTION app.hr_employee_document_file(p_property uuid, p_document uuid, p_actor uuid,
        p_correlation uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.employees.read', p_property);
        v_found record;
    BEGIN
        SELECT document.document_kind, document.employee_id, file.storage_key, file.media_type,
            file.original_name, file.sha256, file.byte_size INTO v_found
        FROM app.employee_documents AS document
        JOIN app.employees AS employee ON employee.id = document.employee_id
        JOIN app.stored_files AS file ON file.id = document.file_id
        WHERE document.id = p_document AND employee.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.employee_document_removals AS removal
              WHERE removal.employee_document_id = document.id);
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The document was not found' USING ERRCODE = '22023';
        END IF;
        IF v_found.document_kind = 'ID_CARD' THEN
            IF NOT app.hr_can(p_actor, p_property, 'hr.salaries.read') THEN
                RAISE EXCEPTION 'this account may not do this' USING ERRCODE = '42501';
            END IF;
            IF NOT app.hr_is_owner(p_actor) THEN
                PERFORM app.hr_audit(p_property, p_actor, 'hr.employee.private_read', 'employee',
                    v_found.employee_id, 'Opened an ID document', p_correlation, NULL,
                    jsonb_build_object('document_id', p_document));
            END IF;
        END IF;
        RETURN jsonb_build_object('storage_key', v_found.storage_key, 'media_type',
            v_found.media_type, 'original_name', v_found.original_name, 'sha256', v_found.sha256,
            'byte_size', v_found.byte_size);
    END $$;

    -- The staff bot: someone pressed Start (PR-HR-020). One open request per Telegram user.
    CREATE FUNCTION app.hr_record_staff_request(p_property uuid, p_telegram_user_id bigint,
        p_given_name text, p_phone text, p_received_at timestamptz, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.hr_require_service(p_actor, p_property);
        v_open uuid;
        v_link record;
    BEGIN
        IF p_telegram_user_id IS NULL OR p_telegram_user_id <= 0 THEN
            RAISE EXCEPTION 'The Telegram user id is a number' USING ERRCODE = '22023';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('hr-telegram:' || p_telegram_user_id, 0));
        SELECT link.employee_id INTO v_link FROM app.employee_telegram_links AS link
        WHERE link.telegram_user_id = p_telegram_user_id AND app.hr_link_live(link.id, v_day)
        LIMIT 1;
        IF FOUND THEN
            RETURN jsonb_build_object('ok', true, 'state', 'LINKED',
                'reply_key', 'staff_start_linked', 'employee_id', v_link.employee_id);
        END IF;
        SELECT request.id INTO v_open FROM app.telegram_staff_requests AS request
        WHERE request.property_id = p_property AND request.telegram_user_id = p_telegram_user_id
          AND NOT EXISTS (SELECT 1 FROM app.telegram_staff_request_decisions AS decision
              WHERE decision.request_id = request.id);
        IF v_open IS NULL THEN
            v_open := gen_random_uuid();
            INSERT INTO app.telegram_staff_requests (id, property_id, telegram_user_id,
                given_name, phone, received_at, created_by)
            VALUES (v_open, p_property, p_telegram_user_id,
                left(coalesce(nullif(btrim(p_given_name), ''), 'Telegram ' || p_telegram_user_id), 120),
                CASE WHEN length(btrim(p_phone)) BETWEEN 6 AND 30 THEN btrim(p_phone) END,
                coalesce(p_received_at, statement_timestamp()), p_actor);
        END IF;
        RETURN jsonb_build_object('ok', true, 'state', 'WAITING', 'reply_key',
            'staff_start_waiting', 'request_id', v_open);
    END $$;

    -- The bots ask who a Telegram user is (report roles), with the APP database URL.
    CREATE FUNCTION app.hr_telegram_staff(p_property uuid, p_telegram_user_id bigint,
        p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.hr_require_service(p_actor, p_property);
        v_employee uuid;
    BEGIN
        SELECT link.employee_id INTO v_employee FROM app.employee_telegram_links AS link
        JOIN app.employees AS employee ON employee.id = link.employee_id
        WHERE link.telegram_user_id = p_telegram_user_id AND employee.property_id = p_property
          AND app.hr_link_live(link.id, v_day)
        LIMIT 1;
        IF v_employee IS NULL THEN
            RETURN jsonb_build_object('linked', false);
        END IF;
        RETURN jsonb_build_object('linked', true, 'employee_id', v_employee,
            'employee_code', (SELECT employee.employee_code FROM app.employees AS employee
                WHERE employee.id = v_employee),
            'name_en', (SELECT employee.name_en FROM app.employees AS employee
                WHERE employee.id = v_employee),
            'name_km', (SELECT employee.name_km FROM app.employees AS employee
                WHERE employee.id = v_employee),
            'roles', (SELECT jsonb_agg(link.report_role ORDER BY link.report_role)
                FROM app.employee_telegram_links AS link
                WHERE link.employee_id = v_employee AND link.telegram_user_id = p_telegram_user_id
                  AND app.hr_link_live(link.id, v_day)));
    END $$;

    CREATE FUNCTION app.hr_staff_requests_read(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.employees.read', p_property);
    BEGIN
        RETURN coalesce((SELECT jsonb_agg(jsonb_build_object('request_id', request.id,
                'telegram_user_id', request.telegram_user_id, 'given_name', request.given_name,
                'phone', request.phone, 'received_at', request.received_at)
                ORDER BY request.received_at)
            FROM app.telegram_staff_requests AS request
            WHERE request.property_id = p_property
              AND NOT EXISTS (SELECT 1 FROM app.telegram_staff_request_decisions AS decision
                  WHERE decision.request_id = request.id)), '[]'::jsonb);
    END $$;

    -- Link a waiting request to an employee with one or more report roles, or refuse it.
    CREATE FUNCTION app.hr_decide_staff_request(p_property uuid, p_request uuid, p_body jsonb,
        p_actor uuid, p_correlation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.employees.manage', p_property);
        v_request app.telegram_staff_requests%ROWTYPE;
        v_decision text := app.problem_text(p_body, 'decision', 20, 'Choose link or refuse');
        v_employee uuid := app.hr_uuid(p_body, 'employee_id', 'Choose the employee');
        v_reason text := app.problem_text(p_body, 'reason', 500, 'The reason is at most 500 letters');
        v_role text;
    BEGIN
        SELECT request.* INTO v_request FROM app.telegram_staff_requests AS request
        WHERE request.id = p_request AND request.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The request was not found' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.telegram_staff_request_decisions AS decision
                WHERE decision.request_id = p_request) THEN
            RAISE EXCEPTION 'The request is already answered' USING ERRCODE = '55000';
        END IF;
        IF v_decision IS NULL OR v_decision NOT IN ('LINKED', 'REFUSED') THEN
            RAISE EXCEPTION 'Choose link or refuse' USING ERRCODE = '22023';
        END IF;
        IF v_decision = 'REFUSED' THEN
            IF v_reason IS NULL THEN
                RAISE EXCEPTION 'Say why' USING ERRCODE = '22023';
            END IF;
            v_employee := NULL;
        ELSE
            IF v_employee IS NULL OR NOT EXISTS (SELECT 1 FROM app.employees AS employee
                    WHERE employee.id = v_employee AND employee.property_id = p_property) THEN
                RAISE EXCEPTION 'Choose the employee' USING ERRCODE = '22023';
            END IF;
            IF NOT app.hr_works_on(v_employee, v_day) THEN
                RAISE EXCEPTION 'Only a working employee is linked to Telegram'
                    USING ERRCODE = '55000';
            END IF;
            IF jsonb_typeof(p_body -> 'roles') <> 'array' OR jsonb_array_length(p_body -> 'roles') = 0 THEN
                RAISE EXCEPTION 'Choose at least one report role' USING ERRCODE = '22023';
            END IF;
            FOR v_role IN SELECT DISTINCT value FROM jsonb_array_elements_text(p_body -> 'roles') LOOP
                PERFORM app.hr_link_telegram(p_property, v_employee, v_request.telegram_user_id,
                    v_role, p_actor);
            END LOOP;
        END IF;
        INSERT INTO app.telegram_staff_request_decisions (request_id, decision, employee_id,
            reason, decided_by)
        VALUES (p_request, v_decision, v_employee,
            coalesce(v_reason, 'Linked to the employee'), p_actor);
        IF v_employee IS NOT NULL THEN
            UPDATE app.employees AS employee SET version = employee.version + 1
            WHERE employee.id = v_employee;
        END IF;
        PERFORM app.hr_audit(p_property, p_actor, 'hr.telegram_request.' || lower(v_decision),
            'telegram_staff_request', p_request, coalesce(v_reason, 'Linked to the employee'),
            p_correlation, NULL, jsonb_build_object('employee_id', v_employee,
                'telegram_user_id', v_request.telegram_user_id, 'roles', p_body -> 'roles'));
    END $$;
"""

READ_FUNCTIONS = (
    "app.hr_employees_read(uuid, uuid)",
    "app.hr_employee_read(uuid, uuid, uuid, uuid)",
    "app.hr_choices(uuid, uuid)",
    "app.hr_add_employee(uuid, jsonb, uuid, uuid)",
    "app.hr_employee_step(uuid, uuid, integer, text, jsonb, uuid, uuid)",
    "app.hr_add_employee_document(uuid, uuid, jsonb, uuid, uuid)",
    "app.hr_employee_document_file(uuid, uuid, uuid, uuid)",
    "app.hr_staff_requests_read(uuid, uuid)",
    "app.hr_decide_staff_request(uuid, uuid, jsonb, uuid, uuid)",
    "app.hr_record_staff_request(uuid, bigint, text, text, timestamptz, uuid)",
    "app.hr_telegram_staff(uuid, bigint, uuid)",
)


def upgrade() -> None:
    capability_rows = ",\n            ".join(
        f"({_text(name)}, 'hr', {_text(description)}, 'bundle', {_text(PROVENANCE)})"
        for name, description in CAPABILITIES
    )
    op.execute(
        f"""
        INSERT INTO app.capabilities (capability_id, family, description, grant_path, provenance)
        VALUES
            {capability_rows}
        """
    )
    for code, en, kh, _ in PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en,
                name_kh, provenance)
            SELECT {_text(code)}, 'ADMIN', max(permission.sort_order) + 1, {_text(en)},
                {_text(kh)}, {_text(PROVENANCE)}
            FROM app.permissions AS permission
            """
        )
    mapping_rows = ",\n            ".join(
        f"({_text(code)}, {_text(capability)}, {_text(PROVENANCE)})"
        for code, _, _, capabilities in PERMISSIONS
        for capability in capabilities
    )
    op.execute(
        f"""
        INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance)
        VALUES
            {mapping_rows}
        """
    )
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
    title_rows = ",\n            ".join(
        f"({_text(code)}, {_text(en)}, {_text(km)}, {order})"
        for order, (code, en, km) in enumerate(JOB_TITLES, start=1)
    )
    shift_rows = ",\n            ".join(
        f"({_text(code)}, TIME {_text(starts)}, TIME {_text(ends)}, {_text(en)}, {_text(km)}, {order})"
        for order, (code, starts, ends, en, km) in enumerate(SHIFTS, start=1)
    )
    op.execute(
        f"""
        INSERT INTO app.job_titles (code, name_en, name_km, sort_order)
        VALUES
            {title_rows};
        INSERT INTO app.work_shifts (code, starts_at, ends_at, name_en, name_km, sort_order)
        VALUES
            {shift_rows};
        INSERT INTO app.number_rules (document_type, year, last_number, format)
        SELECT kind.document_type, years.year, 0, kind.format
        FROM (VALUES ('SALARY_LOAN', 'SLyy000n'), ('PAYROLL', 'PAYyy000n'),
                ('OVERTIME', 'OTyy000n')) AS kind (document_type, format)
        CROSS JOIN (SELECT DISTINCT date_part('year', timezone(property.timezone_name,
                  statement_timestamp()))::smallint AS year
              FROM app.properties AS property
              UNION SELECT date_part('year', statement_timestamp())::smallint) AS years
        ON CONFLICT (document_type, year) DO NOTHING;
        ALTER TABLE app.gl_journal_lines ADD CONSTRAINT gl_journal_lines_employee_fkey
            FOREIGN KEY (employee_id) REFERENCES app.employees (id) ON DELETE RESTRICT;
        CREATE INDEX gl_journal_lines_employee_idx ON app.gl_journal_lines (employee_id)
            WHERE employee_id IS NOT NULL;
        """
    )
    _patch(RANGE, ((RANGE_BEFORE, RANGE_AFTER),))
    for code, unit, value, en, kh in RULES:
        op.execute(
            f"""
            WITH named AS (
                INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                    used_by_app)
                VALUES ({_text(code)}, {_text(en)}, {_text(kh)}, {_text(unit)}, 'STAFF', true)
                RETURNING id
            )
            INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
            SELECT named.id, {value}, DATE '2026-01-01', {_text(SEED_REASON)},
                (SELECT classification.actor_id FROM app.user_account_classes AS classification
                 WHERE classification.account_class = 'owner')
            FROM named
            """
        )
    op.execute(FUNCTIONS)
    tables = ", ".join(f"app.{name}" for name in ("employees", *APPEND_ONLY))
    op.execute(
        f"""
        REVOKE ALL ON TABLE {tables} FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.job_titles, app.work_shifts TO prm_runtime;
        """
    )
    for signature in READ_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")

    # New Properties: the Manager gets employees and attendance, not salaries or approvals.
    _patch(
        SEED,
        (
            (
                MANAGER_BEFORE,
                "'products.prices', " + ", ".join(_text(name) for name in OWNER_ONLY) + "]::text[]",
            ),
        ),
    )
    every = _array(OWNER)
    manager = _array(MANAGER)
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
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version,
                    CASE bundle.role_bundle_id
                        WHEN seeded.owner_bundle_id THEN {every}
                        ELSE {manager}
                    END AS added
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (seeded.owner_bundle_id, seeded.manager_bundle_id)
                ORDER BY seeded.property_id, bundle.role_bundle_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles SET version = v_default.version + 1
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, v_default.version + 1, held.capability_id
                FROM app.role_bundle_capabilities AS held
                WHERE held.role_bundle_id = v_default.role_bundle_id
                  AND held.version = v_default.version
                UNION
                SELECT v_default.role_bundle_id, v_default.version + 1, added
                FROM pg_catalog.unnest(v_default.added) AS added;
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
                        {_text(REASON)}, 'identity.manage_access', v_default.property_id,
                        pg_catalog.jsonb_build_object('version', v_default.version),
                        pg_catalog.jsonb_build_object(
                            'version', v_default.version + 1,
                            'capabilities_added', pg_catalog.to_jsonb(v_default.added)),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("HRIS phase 1 migration is forward-only")
