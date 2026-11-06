# ruff: noqa: E501
"""HRIS phase 6 step 2: salary loans and payroll with their ledger entries (PR-HR-020..033).

1. Salary components (lookup): earnings Base salary, Bonus, Other plus and Overtime (6030);
   deductions Days not worked and Other minus (6030), Loan repayment (1210); Salary tax and
   NSSF are listed but off until a tax agent confirms them (PR-HR-033).
2. Salary loans (SLyy000n): amount at most LOAN_PCT of one month's salary and at most
   LOAN_OPEN_MAX open loans per person (business rules); the Owner approves (nobody approves
   their own request; the Owner's own record keeps a note); paid out in cash or from the joint
   ABA account with the entry 1210 up, 1010 or 1020 down. What is still owed is worked out from
   the approved payroll lines, never stored.
3. Payroll runs (PAYyy000n), one REGULAR run per salary month, made after the month ends:
   salary by calendar days (rounded half up to the cent), the loan repayment, and the lines from
   Attendance (step 3 fills them). Lines are added or removed with a reason until the run is
   sent; the Owner approves or sends it back. Approval writes one payslip and one entry per
   person dated the last day of the salary month (6030 up, 1210 down for the loan repayment,
   2300 Salaries to pay up). Mark paid writes 2300 down, 1010 or 1020 down; a mistake is
   reversed with a reason. A mistake found after approval goes into a CORRECTION run.
4. The Month-end close check "Payroll approved" now looks at the payroll.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270501_301"
down_revision: str | None = "20270430_300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_REASON = "First value: the owner's HR rules (02/11/2026)"
RANGE = "app.business_rules_program_range()"
RANGE_BEFORE = "OR (v_code = 'LOAN_PCT' AND NEW.value NOT BETWEEN 1 AND 10000)"
RANGE_AFTER = (
    RANGE_BEFORE + "\n                OR (v_code = 'LOAN_OPEN_MAX' AND NEW.value NOT BETWEEN 1 AND 5)"
)
CLOSE = "app.gl_month_close_checks(uuid)"
CLOSE_BEFORE = """    -- Round 23: payroll comes from the HRIS; until it is built there is no payroll to approve.
    RETURN QUERY SELECT 'PAYROLL_APPROVED', true, 0::bigint;"""
CLOSE_AFTER = """    -- HRIS (PR-HR-032): the month's REGULAR payroll is approved, when anyone worked that month.
    RETURN QUERY SELECT 'PAYROLL_APPROVED', app.hr_payroll_month_approved(v_period.property_id,
            v_period.starts_on),
        CASE WHEN app.hr_payroll_month_approved(v_period.property_id, v_period.starts_on)
            THEN 0::bigint ELSE 1::bigint END;"""

# code, direction, ledger account, in use, English, Khmer (mock-up round 23 payroll words)
COMPONENTS = (
    ("BASE_SALARY", "EARNING", "6030", True, "Salary", "ប្រាក់ខែ"),
    ("OVERTIME", "EARNING", "6030", True, "Overtime", "ម៉ោងបន្ថែម"),
    ("BONUS", "EARNING", "6030", True, "Bonus", "ប្រាក់រង្វាន់"),
    ("OTHER_PLUS", "EARNING", "6030", True, "Other plus", "បន្ថែមផ្សេងៗ"),
    ("DAYS_NOT_WORKED", "DEDUCTION", "6030", True, "Days not worked", "ថ្ងៃមិនបានធ្វើការ"),
    ("OTHER_MINUS", "DEDUCTION", "6030", True, "Other minus", "កាត់ផ្សេងៗ"),
    ("LOAN_REPAYMENT", "DEDUCTION", "1210", True, "Loan repayment", "សងប្រាក់កម្ចី"),
    ("SALARY_TAX", "DEDUCTION", "2400", False, "Salary tax", "ពន្ធលើប្រាក់ខែ"),
    ("NSSF_EMPLOYEE", "DEDUCTION", "2400", False, "NSSF", "ប.ស.ស"),
)


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
    CREATE TABLE app.salary_components (
        code text PRIMARY KEY CHECK (code ~ '^[A-Z][A-Z_]{2,31}$'),
        direction text NOT NULL CHECK (direction IN ('EARNING', 'DEDUCTION')),
        ledger_account_code text NOT NULL CHECK (ledger_account_code ~ '^[0-9]{4}$'),
        in_use boolean NOT NULL,
        name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 80),
        name_km text NOT NULL CHECK (name_km = btrim(name_km) AND length(name_km) BETWEEN 1 AND 80),
        sort_order smallint NOT NULL UNIQUE CHECK (sort_order > 0)
    );

    CREATE TABLE app.salary_loans (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        loan_number text NOT NULL UNIQUE CHECK (loan_number ~ '^[A-Z]{2,5}[0-9]{6,}$'),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents BETWEEN 1 AND 99999999),
        requested_on date NOT NULL,
        payout_method text NOT NULL CHECK (payout_method IN ('CASH_USD', 'ABA_JOINT')),
        repayment_plan text NOT NULL CHECK (repayment_plan IN ('NEXT_SALARY', 'MONTHLY_AMOUNT')),
        monthly_repayment_usd_cents bigint,
        request_channel text NOT NULL CHECK (request_channel IN ('APP', 'TELEGRAM')),
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT salary_loans_plan CHECK ((repayment_plan = 'MONTHLY_AMOUNT')
            = (monthly_repayment_usd_cents IS NOT NULL)),
        CONSTRAINT salary_loans_monthly CHECK (monthly_repayment_usd_cents IS NULL
            OR monthly_repayment_usd_cents BETWEEN 1 AND amount_usd_cents)
    );
    CREATE INDEX salary_loans_employee_idx ON app.salary_loans (employee_id, created_at);
    CREATE TABLE app.salary_loan_decisions (
        salary_loan_id uuid PRIMARY KEY REFERENCES app.salary_loans (id) ON DELETE RESTRICT,
        decision text NOT NULL CHECK (decision IN ('APPROVED', 'REFUSED')),
        reason text CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        own_request_note text CHECK (own_request_note = btrim(own_request_note)
            AND length(own_request_note) BETWEEN 1 AND 500),
        decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        decided_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT salary_loan_decisions_refusal CHECK (decision = 'APPROVED' OR reason IS NOT NULL)
    );
    CREATE TABLE app.salary_loan_payouts (
        salary_loan_id uuid PRIMARY KEY REFERENCES app.salary_loans (id) ON DELETE RESTRICT,
        paid_on date NOT NULL,
        entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );

    CREATE TABLE app.payroll_runs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        run_number text NOT NULL UNIQUE CHECK (run_number ~ '^[A-Z]{2,5}[0-9]{6,}$'),
        salary_month date NOT NULL CHECK (extract(day FROM salary_month) = 1),
        run_kind text NOT NULL CHECK (run_kind IN ('REGULAR', 'CORRECTION')),
        pay_date date NOT NULL CHECK (pay_date > salary_month),
        corrects_run_id uuid REFERENCES app.payroll_runs (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT payroll_runs_correction CHECK ((run_kind = 'CORRECTION')
            = (corrects_run_id IS NOT NULL))
    );
    CREATE UNIQUE INDEX payroll_runs_one_regular ON app.payroll_runs (property_id, salary_month)
        WHERE run_kind = 'REGULAR';
    CREATE TABLE app.payroll_run_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        payroll_run_id uuid NOT NULL REFERENCES app.payroll_runs (id) ON DELETE RESTRICT,
        event_type text NOT NULL CHECK (event_type IN
            ('LIST_MADE', 'SENT_FOR_APPROVAL', 'SENT_BACK', 'APPROVED')),
        reason text CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        own_request_note text CHECK (own_request_note = btrim(own_request_note)
            AND length(own_request_note) BETWEEN 1 AND 500),
        step_no integer NOT NULL CHECK (step_no > 0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT payroll_run_events_step UNIQUE (payroll_run_id, step_no),
        CONSTRAINT payroll_run_events_back CHECK (event_type <> 'SENT_BACK' OR reason IS NOT NULL)
    );
    CREATE UNIQUE INDEX payroll_run_events_one_approval ON app.payroll_run_events (payroll_run_id)
        WHERE event_type = 'APPROVED';
    CREATE TABLE app.payroll_lines (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        payroll_run_id uuid NOT NULL REFERENCES app.payroll_runs (id) ON DELETE RESTRICT,
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        component_code text NOT NULL REFERENCES app.salary_components (code) ON DELETE RESTRICT,
        amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents BETWEEN 1 AND 99999999),
        days_worked smallint,
        days_in_month smallint,
        hours numeric(7, 2) CHECK (hours > 0),
        salary_loan_id uuid REFERENCES app.salary_loans (id) ON DELETE RESTRICT,
        source text NOT NULL CHECK (source IN ('LIST', 'ATTENDANCE', 'MANUAL')),
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT payroll_lines_days CHECK ((days_in_month IS NULL) = (days_worked IS NULL)
            AND (days_in_month IS NULL OR (days_in_month BETWEEN 28 AND 31
                AND days_worked BETWEEN 0 AND days_in_month))),
        CONSTRAINT payroll_lines_loan CHECK ((component_code = 'LOAN_REPAYMENT')
            = (salary_loan_id IS NOT NULL))
    );
    CREATE INDEX payroll_lines_run_idx ON app.payroll_lines (payroll_run_id, employee_id);
    CREATE INDEX payroll_lines_loan_idx ON app.payroll_lines (salary_loan_id)
        WHERE salary_loan_id IS NOT NULL;
    CREATE TABLE app.payroll_line_removals (
        payroll_line_id uuid PRIMARY KEY REFERENCES app.payroll_lines (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        removed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        removed_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE TABLE app.payslips (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        payroll_run_id uuid NOT NULL REFERENCES app.payroll_runs (id) ON DELETE RESTRICT,
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        earnings_usd_cents bigint NOT NULL CHECK (earnings_usd_cents >= 0),
        deductions_usd_cents bigint NOT NULL CHECK (deductions_usd_cents >= 0),
        net_pay_usd_cents bigint NOT NULL CHECK (net_pay_usd_cents >= 0),
        payment_method text NOT NULL CHECK (payment_method IN ('CASH_USD', 'ABA')),
        aba_account_name text,
        aba_account_number text,
        entry_id uuid UNIQUE REFERENCES app.gl_journal_entries (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT payslips_net CHECK (net_pay_usd_cents = earnings_usd_cents - deductions_usd_cents),
        CONSTRAINT payslips_one_per_person UNIQUE (payroll_run_id, employee_id)
    );
    CREATE TABLE app.salary_payments (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        payslip_id uuid NOT NULL REFERENCES app.payslips (id) ON DELETE RESTRICT,
        paid_on date NOT NULL,
        method text NOT NULL CHECK (method IN ('CASH_USD', 'ABA_JOINT')),
        amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
        bank_reference text CHECK (bank_reference = btrim(bank_reference)
            AND length(bank_reference) BETWEEN 1 AND 80),
        own_request_note text CHECK (own_request_note = btrim(own_request_note)
            AND length(own_request_note) BETWEEN 1 AND 500),
        entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX salary_payments_payslip_idx ON app.salary_payments (payslip_id);
    CREATE TABLE app.salary_payment_reversals (
        salary_payment_id uuid PRIMARY KEY REFERENCES app.salary_payments (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );

    -- An approved payroll is final: its lines and removals never change after approval.
    CREATE FUNCTION app.hr_payroll_open_check() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE v_run uuid;
    BEGIN
        IF TG_TABLE_NAME = 'payroll_lines' THEN
            v_run := NEW.payroll_run_id;
        ELSE
            SELECT line.payroll_run_id INTO v_run FROM app.payroll_lines AS line
            WHERE line.id = NEW.payroll_line_id;
        END IF;
        IF app.hr_payroll_state(v_run) NOT IN ('LIST_MADE', 'SENT_BACK') THEN
            RAISE EXCEPTION 'This payroll is sent or approved: its lines do not change'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_payroll_open_check() FROM PUBLIC;
"""

APPEND_ONLY = (
    "salary_components",
    "salary_loans",
    "salary_loan_decisions",
    "salary_loan_payouts",
    "payroll_runs",
    "payroll_run_events",
    "payroll_lines",
    "payroll_line_removals",
    "payslips",
    "salary_payments",
    "salary_payment_reversals",
)

FUNCTIONS = """
    CREATE FUNCTION app.hr_payroll_state(p_run uuid) RETURNS text
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT event.event_type FROM app.payroll_run_events AS event
        WHERE event.payroll_run_id = p_run ORDER BY event.step_no DESC LIMIT 1
    $$;
    REVOKE ALL ON FUNCTION app.hr_payroll_state(uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_line_live(p_line uuid) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT NOT EXISTS (SELECT 1 FROM app.payroll_line_removals AS removal
            WHERE removal.payroll_line_id = p_line)
    $$;
    REVOKE ALL ON FUNCTION app.hr_line_live(uuid) FROM PUBLIC;

    -- What a loan has taken back so far: its lines in approved payrolls.
    CREATE FUNCTION app.hr_loan_repaid(p_loan uuid) RETURNS bigint
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT coalesce(sum(line.amount_usd_cents), 0)::bigint FROM app.payroll_lines AS line
        WHERE line.salary_loan_id = p_loan AND app.hr_line_live(line.id)
          AND app.hr_payroll_state(line.payroll_run_id) = 'APPROVED'
    $$;
    REVOKE ALL ON FUNCTION app.hr_loan_repaid(uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_loan_state(p_loan uuid) RETURNS text
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE
            WHEN decision.decision IS NULL THEN 'WAITING'
            WHEN decision.decision = 'REFUSED' THEN 'REFUSED'
            WHEN payout.salary_loan_id IS NULL THEN 'APPROVED'
            WHEN app.hr_loan_repaid(loan.id) >= loan.amount_usd_cents THEN 'REPAID'
            ELSE 'PAID_OUT' END
        FROM app.salary_loans AS loan
        LEFT JOIN app.salary_loan_decisions AS decision ON decision.salary_loan_id = loan.id
        LEFT JOIN app.salary_loan_payouts AS payout ON payout.salary_loan_id = loan.id
        WHERE loan.id = p_loan
    $$;
    REVOKE ALL ON FUNCTION app.hr_loan_state(uuid) FROM PUBLIC;

    -- Nobody approves their own request (PR-HR-022, PR-HR-028): the one who entered or sent it,
    -- or the employee it is for. Only the Owner may go on, with a written note.
    CREATE FUNCTION app.hr_own_check(p_actor uuid, p_own boolean, p_note text) RETURNS text
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE v_note text := nullif(btrim(p_note), '');
    BEGIN
        IF NOT p_own THEN
            RETURN NULL;
        END IF;
        IF NOT app.hr_is_owner(p_actor) THEN
            RAISE EXCEPTION 'Nobody approves their own request' USING ERRCODE = '42501';
        END IF;
        IF v_note IS NULL THEN
            RAISE EXCEPTION 'This is your own request: write a note to go on'
                USING ERRCODE = '22023';
        END IF;
        RETURN left(v_note, 500);
    END $$;
    REVOKE ALL ON FUNCTION app.hr_own_check(uuid, boolean, text) FROM PUBLIC;

    CREATE FUNCTION app.hr_cash_code(p_method text) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN p_method = 'CASH_USD' THEN '1010' ELSE '1020' END
    $$;
    REVOKE ALL ON FUNCTION app.hr_cash_code(text) FROM PUBLIC;

    CREATE FUNCTION app.hr_loan_json(p_loan uuid) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object(
            'loan_id', loan.id, 'loan_number', loan.loan_number,
            'employee_id', loan.employee_id, 'employee_code', employee.employee_code,
            'name_en', employee.name_en, 'name_km', employee.name_km,
            'amount_usd_cents', loan.amount_usd_cents, 'requested_on', loan.requested_on,
            'payout_method', loan.payout_method, 'repayment_plan', loan.repayment_plan,
            'monthly_repayment_usd_cents', loan.monthly_repayment_usd_cents,
            'request_channel', loan.request_channel, 'reason', loan.reason,
            'state', app.hr_loan_state(loan.id),
            'repaid_usd_cents', app.hr_loan_repaid(loan.id),
            'owed_usd_cents', CASE WHEN payout.salary_loan_id IS NULL THEN 0
                ELSE loan.amount_usd_cents - app.hr_loan_repaid(loan.id) END,
            'created_at', loan.created_at, 'created_by', maker.display_name,
            'decision', CASE WHEN decision.salary_loan_id IS NULL THEN NULL ELSE jsonb_build_object(
                'decision', decision.decision, 'reason', decision.reason,
                'own_request_note', decision.own_request_note, 'at', decision.decided_at,
                'by', decider.display_name) END,
            'paid_on', payout.paid_on,
            'repayments', coalesce((SELECT jsonb_agg(jsonb_build_object('run_number', run.run_number,
                    'salary_month', run.salary_month, 'amount_usd_cents', line.amount_usd_cents)
                    ORDER BY run.salary_month)
                FROM app.payroll_lines AS line
                JOIN app.payroll_runs AS run ON run.id = line.payroll_run_id
                WHERE line.salary_loan_id = loan.id AND app.hr_line_live(line.id)
                  AND app.hr_payroll_state(run.id) = 'APPROVED'), '[]'::jsonb))
        FROM app.salary_loans AS loan
        JOIN app.employees AS employee ON employee.id = loan.employee_id
        LEFT JOIN app.user_accounts AS maker ON maker.actor_id = loan.created_by
        LEFT JOIN app.salary_loan_decisions AS decision ON decision.salary_loan_id = loan.id
        LEFT JOIN app.user_accounts AS decider ON decider.actor_id = decision.decided_by
        LEFT JOIN app.salary_loan_payouts AS payout ON payout.salary_loan_id = loan.id
        WHERE loan.id = p_loan
    $$;
    REVOKE ALL ON FUNCTION app.hr_loan_json(uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_loans_read(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.salaries.read', p_property);
    BEGIN
        RETURN jsonb_build_object(
            'today', v_day,
            'loan_pct', coalesce(app.business_rule_value('LOAN_PCT', v_day), 5000),
            'open_max', coalesce(app.business_rule_value('LOAN_OPEN_MAX', v_day), 1),
            'can_prepare', app.hr_can(p_actor, p_property, 'hr.loans.prepare'),
            'can_approve', app.hr_can(p_actor, p_property, 'hr.loans.approve'),
            'loans', coalesce((SELECT jsonb_agg(app.hr_loan_json(loan.id)
                    ORDER BY loan.created_at DESC)
                FROM app.salary_loans AS loan WHERE loan.property_id = p_property), '[]'::jsonb));
    END $$;

    -- PR-HR-020, PR-HR-021: limit and open loans are business rules, checked under a lock.
    CREATE FUNCTION app.hr_add_loan(p_property uuid, p_body jsonb, p_actor uuid,
        p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.loans.prepare', p_property);
        v_id uuid := gen_random_uuid();
        v_employee uuid := app.hr_uuid(p_body, 'employee_id', 'Choose the employee');
        v_amount bigint := app.hr_cents(p_body, 'amount_usd_cents',
            'The amount is a whole number of cents');
        v_on date := coalesce(app.hr_date(p_body, 'requested_on', 'The date is not a date'), v_day);
        v_method text := app.problem_text(p_body, 'payout_method', 20, 'Choose cash or ABA');
        v_plan text := coalesce(app.problem_text(p_body, 'repayment_plan', 20,
            'Choose how it is paid back'), 'NEXT_SALARY');
        v_monthly bigint := app.hr_cents(p_body, 'monthly_repayment_usd_cents',
            'The monthly repayment is a whole number of cents');
        v_channel text := coalesce(app.problem_text(p_body, 'request_channel', 20,
            'Choose how it was asked'), 'APP');
        v_reason text := app.problem_text(p_body, 'reason', 500, 'The reason is at most 500 letters');
        v_salary bigint;
        v_limit bigint;
        v_open integer;
        v_most integer;
        v_number text;
    BEGIN
        IF v_employee IS NULL OR NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.id = v_employee AND employee.property_id = p_property) THEN
            RAISE EXCEPTION 'Choose the employee' USING ERRCODE = '22023';
        END IF;
        IF NOT app.hr_works_on(v_employee, v_day) THEN
            RAISE EXCEPTION 'Only a working employee gets a salary loan' USING ERRCODE = '55000';
        END IF;
        IF v_amount IS NULL THEN
            RAISE EXCEPTION 'Enter the amount' USING ERRCODE = '22023';
        END IF;
        IF v_method IS NULL OR v_method NOT IN ('CASH_USD', 'ABA_JOINT') THEN
            RAISE EXCEPTION 'Choose cash or the joint ABA account' USING ERRCODE = '22023';
        END IF;
        IF v_plan NOT IN ('NEXT_SALARY', 'MONTHLY_AMOUNT') THEN
            RAISE EXCEPTION 'Choose how it is paid back' USING ERRCODE = '22023';
        END IF;
        IF (v_plan = 'MONTHLY_AMOUNT') <> (v_monthly IS NOT NULL) OR v_monthly > v_amount THEN
            RAISE EXCEPTION 'The amount each month is from 1 cent up to the loan'
                USING ERRCODE = '22023';
        END IF;
        IF v_channel NOT IN ('APP', 'TELEGRAM') THEN
            RAISE EXCEPTION 'Choose how it was asked' USING ERRCODE = '22023';
        END IF;
        IF v_reason IS NULL THEN
            RAISE EXCEPTION 'Say what the loan is for' USING ERRCODE = '22023';
        END IF;
        IF v_on > v_day THEN
            RAISE EXCEPTION 'The date is today or earlier' USING ERRCODE = '22023';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('hr-loan:' || v_employee, 0));
        v_salary := (app.hr_pay_on(v_employee, v_day)).monthly_salary_usd_cents;
        IF v_salary IS NULL THEN
            RAISE EXCEPTION 'The employee has no salary yet' USING ERRCODE = '55000';
        END IF;
        v_limit := floor(v_salary * coalesce(app.business_rule_value('LOAN_PCT', v_day), 5000)
            / 10000.0)::bigint;
        IF v_amount > v_limit THEN
            RAISE EXCEPTION 'The loan is more than the limit of % (% of one month''s salary)',
                to_char(v_limit / 100.0, 'FM$999,999,990.00'),
                to_char(coalesce(app.business_rule_value('LOAN_PCT', v_day), 5000) / 100.0,
                    'FM990.##') || '%' USING ERRCODE = '22023';
        END IF;
        v_most := coalesce(app.business_rule_value('LOAN_OPEN_MAX', v_day), 1)::integer;
        SELECT count(*) INTO v_open FROM app.salary_loans AS loan
        WHERE loan.employee_id = v_employee
          AND app.hr_loan_state(loan.id) IN ('WAITING', 'APPROVED', 'PAID_OUT');
        IF v_open >= v_most THEN
            RAISE EXCEPTION 'The employee already has % open loan(s), the most allowed', v_open
                USING ERRCODE = '55000';
        END IF;
        v_number := app.next_document_number('SALARY_LOAN', statement_timestamp());
        INSERT INTO app.salary_loans (id, property_id, loan_number, employee_id, amount_usd_cents,
            requested_on, payout_method, repayment_plan, monthly_repayment_usd_cents,
            request_channel, reason, created_by)
        VALUES (v_id, p_property, v_number, v_employee, v_amount, v_on, v_method, v_plan,
            v_monthly, v_channel, v_reason, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.loan.requested', 'salary_loan', v_id,
            v_reason, p_correlation, NULL, jsonb_build_object('loan_number', v_number,
                'employee_id', v_employee, 'amount_usd_cents', v_amount, 'plan', v_plan));
        RETURN v_id;
    END $$;

    CREATE FUNCTION app.hr_decide_loan(p_property uuid, p_loan uuid, p_body jsonb, p_actor uuid,
        p_correlation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.loans.approve', p_property);
        v_loan app.salary_loans%ROWTYPE;
        v_decision text := app.problem_text(p_body, 'decision', 20, 'Choose approve or refuse');
        v_reason text := app.problem_text(p_body, 'reason', 500, 'The reason is at most 500 letters');
        v_note text;
    BEGIN
        SELECT loan.* INTO v_loan FROM app.salary_loans AS loan
        WHERE loan.id = p_loan AND loan.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The loan was not found' USING ERRCODE = '22023';
        END IF;
        IF app.hr_loan_state(p_loan) <> 'WAITING' THEN
            RAISE EXCEPTION 'The loan is already decided' USING ERRCODE = '55000';
        END IF;
        IF v_decision IS NULL OR v_decision NOT IN ('APPROVED', 'REFUSED') THEN
            RAISE EXCEPTION 'Choose approve or refuse' USING ERRCODE = '22023';
        END IF;
        IF v_decision = 'REFUSED' AND v_reason IS NULL THEN
            RAISE EXCEPTION 'Say why it is refused' USING ERRCODE = '22023';
        END IF;
        v_note := app.hr_own_check(p_actor, v_loan.created_by = p_actor OR EXISTS (
                SELECT 1 FROM app.employees AS employee
                WHERE employee.id = v_loan.employee_id AND employee.user_actor_id = p_actor),
            p_body ->> 'own_request_note');
        INSERT INTO app.salary_loan_decisions (salary_loan_id, decision, reason, own_request_note,
            decided_by)
        VALUES (p_loan, v_decision, v_reason, v_note, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.loan.' || lower(v_decision), 'salary_loan',
            p_loan, coalesce(v_reason, v_note, 'Approved'), p_correlation, NULL,
            jsonb_build_object('decision', v_decision, 'own_request_note', v_note));
    END $$;

    -- PR-HR-023: paid out from cash (1010) or the joint ABA account (1020).
    CREATE FUNCTION app.hr_pay_out_loan(p_property uuid, p_loan uuid, p_paid_on date,
        p_actor uuid, p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.loans.prepare', p_property);
        v_loan app.salary_loans%ROWTYPE;
        v_code text;
        v_on date := coalesce(p_paid_on, v_day);
        v_entry uuid;
    BEGIN
        SELECT loan.* INTO v_loan FROM app.salary_loans AS loan
        WHERE loan.id = p_loan AND loan.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The loan was not found' USING ERRCODE = '22023';
        END IF;
        IF app.hr_loan_state(p_loan) <> 'APPROVED' THEN
            RAISE EXCEPTION 'Only an approved loan that is not paid out yet is paid out'
                USING ERRCODE = '55000';
        END IF;
        IF v_on < v_loan.requested_on THEN
            RAISE EXCEPTION 'The pay-out date is on or after the loan date' USING ERRCODE = '22023';
        END IF;
        PERFORM app.gl_check_record_day(p_property, v_on);
        v_code := (app.gl_money_account(p_property, app.hr_cash_code(v_loan.payout_method))).code;
        v_entry := app.gl_post_entry(p_property, v_on, 'AUTO',
            'Salary loan ' || v_loan.loan_number || ' paid out', 'SALARY_LOAN', p_loan,
            'salary_loan_payout:' || p_loan || '\\:paid', NULL, p_actor, NULL, coalesce(p_correlation, gen_random_uuid()),
            jsonb_build_array(
                jsonb_build_object('account', '1210', 'debit_cents', v_loan.amount_usd_cents,
                    'employee_id', v_loan.employee_id, 'memo', v_loan.loan_number),
                jsonb_build_object('account', v_code, 'credit_cents', v_loan.amount_usd_cents,
                    'employee_id', v_loan.employee_id, 'memo', v_loan.loan_number)));
        INSERT INTO app.salary_loan_payouts (salary_loan_id, paid_on, entry_id, created_by)
        VALUES (p_loan, v_on, v_entry, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.loan.paid_out', 'salary_loan', p_loan,
            'Loan paid out', p_correlation, NULL, jsonb_build_object('paid_on', v_on,
                'account', v_code, 'entry_id', v_entry));
        RETURN v_entry;
    END $$;

    -- Lines from Attendance (Days not worked, Overtime). Step 3 replaces this.
    CREATE FUNCTION app.hr_payroll_attendance_lines(p_run uuid, p_actor uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        RETURN;
    END $$;
    REVOKE ALL ON FUNCTION app.hr_payroll_attendance_lines(uuid, uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_next_step(p_run uuid) RETURNS integer
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT coalesce(max(event.step_no), 0) + 1 FROM app.payroll_run_events AS event
        WHERE event.payroll_run_id = p_run
    $$;
    REVOKE ALL ON FUNCTION app.hr_next_step(uuid) FROM PUBLIC;

    -- Earnings minus deductions of one person in one run so far.
    CREATE FUNCTION app.hr_person_net(p_run uuid, p_employee uuid) RETURNS bigint
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT coalesce(sum(CASE component.direction WHEN 'EARNING' THEN line.amount_usd_cents
                ELSE -line.amount_usd_cents END), 0)::bigint
        FROM app.payroll_lines AS line
        JOIN app.salary_components AS component ON component.code = line.component_code
        WHERE line.payroll_run_id = p_run AND line.employee_id = p_employee
          AND app.hr_line_live(line.id)
    $$;
    REVOKE ALL ON FUNCTION app.hr_person_net(uuid, uuid) FROM PUBLIC;

    -- PR-HR-025, PR-HR-026: the list for a month that has ended.
    CREATE FUNCTION app.hr_make_payroll(p_property uuid, p_month date, p_actor uuid,
        p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.payroll.prepare', p_property);
        v_month date := date_trunc('month', p_month)::date;
        v_end date := (date_trunc('month', p_month) + interval '1 month' - interval '1 day')::date;
        v_days integer;
        v_run uuid := gen_random_uuid();
        v_employee record;
        v_amount bigint;
        v_loan record;
        v_take bigint;
    BEGIN
        IF p_month IS NULL OR v_end >= v_day THEN
            RAISE EXCEPTION 'The payroll is made after the month ends' USING ERRCODE = '22023';
        END IF;
        v_days := extract(day FROM v_end)::integer;
        PERFORM pg_advisory_xact_lock(hashtextextended('hr-payroll:' || p_property, 0));
        IF EXISTS (SELECT 1 FROM app.payroll_runs AS run WHERE run.property_id = p_property
                AND run.salary_month = v_month AND run.run_kind = 'REGULAR') THEN
            RAISE EXCEPTION 'The payroll for % is already made', to_char(v_month, 'MM/YYYY')
                USING ERRCODE = '23505';
        END IF;
        INSERT INTO app.payroll_runs (id, property_id, run_number, salary_month, run_kind,
            pay_date, created_by)
        VALUES (v_run, p_property, app.next_document_number('PAYROLL', statement_timestamp()),
            v_month, 'REGULAR', v_end + coalesce(app.business_rule_value('PAY_DAY', v_day),
                5)::integer, p_actor);
        INSERT INTO app.payroll_run_events (payroll_run_id, event_type, step_no, created_by)
        VALUES (v_run, 'LIST_MADE', 1, p_actor);
        FOR v_employee IN
            SELECT employee.id, greatest(v_month, app.hr_hired_on(employee.id)) AS first_day,
                least(v_end, coalesce(app.hr_left_on(employee.id), v_end)) AS last_day
            FROM app.employees AS employee
            WHERE employee.property_id = p_property AND app.hr_hired_on(employee.id) <= v_end
              AND coalesce(app.hr_left_on(employee.id), v_end) >= v_month
            ORDER BY employee.employee_code
        LOOP
            -- Salary by calendar days, one day at a time so a raise in the month counts.
            SELECT round(sum((app.hr_pay_on(v_employee.id, day::date)).monthly_salary_usd_cents
                    ::numeric / v_days))::bigint
            INTO v_amount
            FROM generate_series(v_employee.first_day, v_employee.last_day, interval '1 day') AS day;
            IF coalesce(v_amount, 0) > 0 THEN
                INSERT INTO app.payroll_lines (payroll_run_id, employee_id, component_code,
                    amount_usd_cents, days_worked, days_in_month, source, reason, created_by)
                VALUES (v_run, v_employee.id, 'BASE_SALARY', v_amount,
                    v_employee.last_day - v_employee.first_day + 1, v_days, 'LIST',
                    'Salary for ' || to_char(v_month, 'MM/YYYY'), p_actor);
            END IF;
        END LOOP;
        PERFORM app.hr_payroll_attendance_lines(v_run, p_actor);
        -- PR-HR-020: a paid-out loan comes back from the next salary, never below zero pay.
        FOR v_loan IN
            SELECT loan.* FROM app.salary_loans AS loan
            JOIN app.salary_loan_payouts AS payout ON payout.salary_loan_id = loan.id
            WHERE loan.property_id = p_property AND payout.paid_on <= v_end
              AND app.hr_loan_state(loan.id) = 'PAID_OUT'
              AND EXISTS (SELECT 1 FROM app.payroll_lines AS line
                  WHERE line.payroll_run_id = v_run AND line.employee_id = loan.employee_id)
            ORDER BY loan.created_at
        LOOP
            v_take := v_loan.amount_usd_cents - app.hr_loan_repaid(v_loan.id);
            v_take := least(v_take, coalesce(v_loan.monthly_repayment_usd_cents, v_take),
                app.hr_person_net(v_run, v_loan.employee_id));
            IF v_take > 0 THEN
                INSERT INTO app.payroll_lines (payroll_run_id, employee_id, component_code,
                    amount_usd_cents, salary_loan_id, source, reason, created_by)
                VALUES (v_run, v_loan.employee_id, 'LOAN_REPAYMENT', v_take, v_loan.id, 'LIST',
                    'Repayment of ' || v_loan.loan_number, p_actor);
            END IF;
        END LOOP;
        PERFORM app.hr_audit(p_property, p_actor, 'hr.payroll.list_made', 'payroll_run', v_run,
            'Payroll list for ' || to_char(v_month, 'MM/YYYY'), p_correlation, NULL,
            jsonb_build_object('salary_month', v_month));
        RETURN v_run;
    END $$;

    -- PR-HR-059: a mistake after approval is fixed in a correction payroll for the same month.
    CREATE FUNCTION app.hr_make_correction(p_property uuid, p_run uuid, p_reason text,
        p_actor uuid, p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.payroll.prepare', p_property);
        v_first app.payroll_runs%ROWTYPE;
        v_run uuid := gen_random_uuid();
        v_reason text := nullif(btrim(p_reason), '');
    BEGIN
        SELECT run.* INTO v_first FROM app.payroll_runs AS run
        WHERE run.id = p_run AND run.property_id = p_property AND run.run_kind = 'REGULAR';
        IF NOT FOUND OR app.hr_payroll_state(p_run) <> 'APPROVED' THEN
            RAISE EXCEPTION 'A correction follows an approved payroll' USING ERRCODE = '55000';
        END IF;
        IF v_reason IS NULL OR length(v_reason) > 500 THEN
            RAISE EXCEPTION 'Say what the correction is for' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.payroll_runs (id, property_id, run_number, salary_month, run_kind,
            pay_date, corrects_run_id, created_by)
        VALUES (v_run, p_property, app.next_document_number('PAYROLL', statement_timestamp()),
            v_first.salary_month, 'CORRECTION', greatest(v_first.pay_date, v_day), p_run, p_actor);
        INSERT INTO app.payroll_run_events (payroll_run_id, event_type, reason, step_no,
            created_by)
        VALUES (v_run, 'LIST_MADE', v_reason, 1, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.payroll.correction_made', 'payroll_run',
            v_run, v_reason, p_correlation, NULL, jsonb_build_object('corrects', p_run));
        RETURN v_run;
    END $$;

    CREATE FUNCTION app.hr_payroll_json(p_run uuid) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        WITH run AS (
            SELECT run.*, app.hr_payroll_state(run.id) AS state,
                (run.salary_month + interval '1 month' - interval '1 day')::date AS month_end
            FROM app.payroll_runs AS run WHERE run.id = p_run
        ), lines AS (
            SELECT line.*, component.direction, component.name_en AS component_en,
                component.name_km AS component_km, component.sort_order
            FROM app.payroll_lines AS line
            JOIN app.salary_components AS component ON component.code = line.component_code
            WHERE line.payroll_run_id = p_run AND app.hr_line_live(line.id)
        ), people AS (
            SELECT DISTINCT lines.employee_id FROM lines
            UNION SELECT slip.employee_id FROM app.payslips AS slip WHERE slip.payroll_run_id = p_run
        )
        SELECT jsonb_build_object(
            'run_id', run.id, 'run_number', run.run_number, 'salary_month', run.salary_month,
            'run_kind', run.run_kind, 'pay_date', run.pay_date, 'corrects_run_id',
            run.corrects_run_id, 'state', run.state,
            'earnings_usd_cents', coalesce((SELECT sum(lines.amount_usd_cents) FROM lines
                WHERE lines.direction = 'EARNING'), 0),
            'deductions_usd_cents', coalesce((SELECT sum(lines.amount_usd_cents) FROM lines
                WHERE lines.direction = 'DEDUCTION'), 0),
            'net_pay_usd_cents', coalesce((SELECT sum(CASE lines.direction WHEN 'EARNING'
                THEN lines.amount_usd_cents ELSE -lines.amount_usd_cents END) FROM lines), 0),
            'events', (SELECT jsonb_agg(jsonb_build_object('event_type', event.event_type,
                    'reason', event.reason, 'own_request_note', event.own_request_note,
                    'at', event.created_at, 'by', account.display_name) ORDER BY event.step_no)
                FROM app.payroll_run_events AS event
                LEFT JOIN app.user_accounts AS account ON account.actor_id = event.created_by
                WHERE event.payroll_run_id = p_run),
            'people', coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'employee_id', employee.id, 'employee_code', employee.employee_code,
                    'name_en', employee.name_en, 'name_km', employee.name_km,
                    'payment_method', coalesce(slip.payment_method, pay.payment_method),
                    'aba_account_name', coalesce(slip.aba_account_name, pay.aba_account_name),
                    'aba_account_number', coalesce(slip.aba_account_number, pay.aba_account_number),
                    'lines', coalesce((SELECT jsonb_agg(jsonb_build_object('line_id', lines.id,
                            'component', lines.component_code, 'direction', lines.direction,
                            'name_en', lines.component_en, 'name_km', lines.component_km,
                            'amount_usd_cents', lines.amount_usd_cents,
                            'days_worked', lines.days_worked, 'days_in_month', lines.days_in_month,
                            'hours', lines.hours, 'salary_loan_id', lines.salary_loan_id,
                            'source', lines.source, 'reason', lines.reason)
                            ORDER BY lines.sort_order, lines.created_at)
                        FROM lines WHERE lines.employee_id = employee.id), '[]'::jsonb),
                    'earnings_usd_cents', coalesce((SELECT sum(lines.amount_usd_cents) FROM lines
                        WHERE lines.employee_id = employee.id AND lines.direction = 'EARNING'), 0),
                    'deductions_usd_cents', coalesce((SELECT sum(lines.amount_usd_cents)
                        FROM lines WHERE lines.employee_id = employee.id
                          AND lines.direction = 'DEDUCTION'), 0),
                    'net_pay_usd_cents', app.hr_person_net(p_run, employee.id),
                    'payslip', CASE WHEN slip.id IS NULL THEN NULL ELSE jsonb_build_object(
                        'payslip_id', slip.id, 'net_pay_usd_cents', slip.net_pay_usd_cents,
                        'earnings_usd_cents', slip.earnings_usd_cents,
                        'deductions_usd_cents', slip.deductions_usd_cents,
                        'entry_id', slip.entry_id,
                        'payment', (SELECT jsonb_build_object('payment_id', payment.id,
                                'paid_on', payment.paid_on, 'method', payment.method,
                                'amount_usd_cents', payment.amount_usd_cents,
                                'bank_reference', payment.bank_reference,
                                'own_request_note', payment.own_request_note)
                            FROM app.salary_payments AS payment
                            WHERE payment.payslip_id = slip.id AND NOT EXISTS (
                                SELECT 1 FROM app.salary_payment_reversals AS undo
                                WHERE undo.salary_payment_id = payment.id)
                            ORDER BY payment.created_at DESC LIMIT 1)) END)
                    ORDER BY employee.employee_code)
                FROM people
                JOIN app.employees AS employee ON employee.id = people.employee_id
                LEFT JOIN app.payslips AS slip ON slip.payroll_run_id = p_run
                    AND slip.employee_id = employee.id
                LEFT JOIN LATERAL app.hr_pay_on(employee.id, run.month_end) AS pay ON true),
                '[]'::jsonb))
        FROM run
    $$;
    REVOKE ALL ON FUNCTION app.hr_payroll_json(uuid) FROM PUBLIC;

    CREATE FUNCTION app.hr_payrolls_read(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.salaries.read', p_property);
    BEGIN
        RETURN jsonb_build_object(
            'today', v_day,
            'pay_day', coalesce(app.business_rule_value('PAY_DAY', v_day), 5),
            'next_month', (date_trunc('month', v_day) - interval '1 month')::date,
            'can_prepare', app.hr_can(p_actor, p_property, 'hr.payroll.prepare'),
            'can_approve', app.hr_can(p_actor, p_property, 'hr.payroll.approve'),
            'can_pay', app.hr_can(p_actor, p_property, 'hr.payroll.pay'),
            'components', (SELECT jsonb_agg(jsonb_build_object('code', component.code,
                    'direction', component.direction, 'in_use', component.in_use,
                    'name_en', component.name_en, 'name_km', component.name_km)
                    ORDER BY component.sort_order) FROM app.salary_components AS component),
            'runs', coalesce((SELECT jsonb_agg(app.hr_payroll_json(run.id) - 'people'
                    ORDER BY run.salary_month DESC, run.created_at DESC)
                FROM app.payroll_runs AS run WHERE run.property_id = p_property), '[]'::jsonb));
    END $$;

    CREATE FUNCTION app.hr_payroll_read(p_property uuid, p_run uuid, p_actor uuid,
        p_correlation uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.salaries.read', p_property);
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM app.payroll_runs AS run
                WHERE run.id = p_run AND run.property_id = p_property) THEN
            RAISE EXCEPTION 'The payroll was not found' USING ERRCODE = '22023';
        END IF;
        IF NOT app.hr_is_owner(p_actor) THEN
            PERFORM app.hr_audit(p_property, p_actor, 'hr.payroll.read', 'payroll_run', p_run,
                'Opened the payroll', p_correlation, NULL, jsonb_build_object('run_id', p_run));
        END IF;
        RETURN app.hr_payroll_json(p_run);
    END $$;

    -- ADD_LINE, REMOVE_LINE and SEND (prepare); SEND_BACK and APPROVE (approve).
    CREATE FUNCTION app.hr_payroll_step(p_property uuid, p_run uuid, p_step text, p_body jsonb,
        p_actor uuid, p_correlation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_right text := CASE WHEN p_step IN ('SEND_BACK', 'APPROVE') THEN 'hr.payroll.approve'
            ELSE 'hr.payroll.prepare' END;
        v_day date := app.require_product_right(p_actor, v_right, p_property);
        v_body jsonb := coalesce(p_body, '{}'::jsonb);
        v_run app.payroll_runs%ROWTYPE;
        v_state text;
        v_reason text := app.problem_text(coalesce(p_body, '{}'::jsonb), 'reason', 500,
            'The reason is at most 500 letters');
        v_employee uuid;
        v_component app.salary_components%ROWTYPE;
        v_amount bigint;
        v_line uuid;
        v_note text;
        v_bad text;
        v_sender uuid;
        v_person record;
        v_slip uuid;
        v_entry uuid;
        v_lines jsonb;
        v_month_end date;
        v_cost bigint;
        v_loan bigint;
    BEGIN
        SELECT run.* INTO v_run FROM app.payroll_runs AS run
        WHERE run.id = p_run AND run.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The payroll was not found' USING ERRCODE = '22023';
        END IF;
        v_state := app.hr_payroll_state(p_run);
        v_month_end := (v_run.salary_month + interval '1 month' - interval '1 day')::date;
        IF p_step IN ('ADD_LINE', 'REMOVE_LINE', 'SEND') AND v_state NOT IN ('LIST_MADE', 'SENT_BACK') THEN
            RAISE EXCEPTION 'This payroll is sent or approved' USING ERRCODE = '55000';
        END IF;
        IF p_step IN ('SEND_BACK', 'APPROVE') AND v_state <> 'SENT_FOR_APPROVAL' THEN
            RAISE EXCEPTION 'This payroll is not waiting for approval' USING ERRCODE = '55000';
        END IF;
        IF p_step = 'ADD_LINE' THEN
            v_employee := app.hr_uuid(v_body, 'employee_id', 'Choose the employee');
            SELECT component.* INTO v_component FROM app.salary_components AS component
            WHERE component.code = v_body ->> 'component' AND component.in_use
              AND component.code NOT IN ('BASE_SALARY', 'LOAN_REPAYMENT');
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Choose what the line is for' USING ERRCODE = '22023';
            END IF;
            v_amount := app.hr_cents(v_body, 'amount_usd_cents', 'The amount is a whole number of cents');
            IF v_amount IS NULL THEN
                RAISE EXCEPTION 'Enter the amount' USING ERRCODE = '22023';
            END IF;
            IF v_reason IS NULL THEN
                RAISE EXCEPTION 'Say why' USING ERRCODE = '22023';
            END IF;
            IF v_employee IS NULL OR NOT EXISTS (SELECT 1 FROM app.employees AS employee
                    WHERE employee.id = v_employee AND employee.property_id = p_property
                      AND app.hr_hired_on(employee.id) <= v_month_end
                      AND coalesce(app.hr_left_on(employee.id), v_month_end) >= v_run.salary_month)
            THEN
                RAISE EXCEPTION 'Choose an employee who worked that month' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.payroll_lines (id, payroll_run_id, employee_id, component_code,
                amount_usd_cents, source, reason, created_by)
            VALUES (gen_random_uuid(), p_run, v_employee, v_component.code, v_amount, 'MANUAL',
                v_reason, p_actor)
            RETURNING id INTO v_line;
            PERFORM app.hr_audit(p_property, p_actor, 'hr.payroll.line_added', 'payroll_run',
                p_run, v_reason, p_correlation, NULL, jsonb_build_object('line_id', v_line,
                    'employee_id', v_employee, 'component', v_component.code,
                    'amount_usd_cents', v_amount));
            RETURN;
        ELSIF p_step = 'REMOVE_LINE' THEN
            v_line := app.hr_uuid(v_body, 'line_id', 'Choose the line');
            IF v_reason IS NULL THEN
                RAISE EXCEPTION 'Say why' USING ERRCODE = '22023';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM app.payroll_lines AS line
                    WHERE line.id = v_line AND line.payroll_run_id = p_run
                      AND app.hr_line_live(line.id)) THEN
                RAISE EXCEPTION 'The line was not found' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.payroll_line_removals (payroll_line_id, reason, removed_by)
            VALUES (v_line, v_reason, p_actor);
            PERFORM app.hr_audit(p_property, p_actor, 'hr.payroll.line_removed', 'payroll_run',
                p_run, v_reason, p_correlation, NULL, jsonb_build_object('line_id', v_line));
            RETURN;
        END IF;
        -- Nobody is paid less than nothing.
        SELECT string_agg(employee.employee_code, ', ' ORDER BY employee.employee_code) INTO v_bad
        FROM app.employees AS employee
        WHERE EXISTS (SELECT 1 FROM app.payroll_lines AS line
                WHERE line.payroll_run_id = p_run AND line.employee_id = employee.id)
          AND app.hr_person_net(p_run, employee.id) < 0;
        IF v_bad IS NOT NULL AND p_step IN ('SEND', 'APPROVE') THEN
            RAISE EXCEPTION 'Net pay is below zero for %: lower a minus line', v_bad
                USING ERRCODE = '22023';
        END IF;
        IF p_step = 'SEND' THEN
            INSERT INTO app.payroll_run_events (payroll_run_id, event_type, reason, step_no,
                created_by)
            VALUES (p_run, 'SENT_FOR_APPROVAL', v_reason, app.hr_next_step(p_run), p_actor);
        ELSIF p_step = 'SEND_BACK' THEN
            IF v_reason IS NULL THEN
                RAISE EXCEPTION 'Say what to fix' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.payroll_run_events (payroll_run_id, event_type, reason, step_no,
                created_by)
            VALUES (p_run, 'SENT_BACK', v_reason, app.hr_next_step(p_run), p_actor);
        ELSIF p_step = 'APPROVE' THEN
            SELECT event.created_by INTO v_sender FROM app.payroll_run_events AS event
            WHERE event.payroll_run_id = p_run AND event.event_type = 'SENT_FOR_APPROVAL'
            ORDER BY event.step_no DESC LIMIT 1;
            v_note := app.hr_own_check(p_actor, v_sender = p_actor OR EXISTS (
                    SELECT 1 FROM app.payroll_lines AS line
                    JOIN app.employees AS employee ON employee.id = line.employee_id
                    WHERE line.payroll_run_id = p_run AND employee.user_actor_id = p_actor),
                v_body ->> 'own_request_note');
            PERFORM app.gl_check_record_day(p_property, v_month_end);
            INSERT INTO app.payroll_run_events (payroll_run_id, event_type, reason,
                own_request_note, step_no, created_by)
            VALUES (p_run, 'APPROVED', v_reason, v_note, app.hr_next_step(p_run), p_actor);
            -- PR-HR-029: one payslip and one entry per person, dated the last day of the month.
            FOR v_person IN
                SELECT line.employee_id,
                    sum(line.amount_usd_cents) FILTER (WHERE component.direction = 'EARNING')
                        AS earnings,
                    sum(line.amount_usd_cents) FILTER (WHERE component.direction = 'DEDUCTION')
                        AS deductions,
                    sum(line.amount_usd_cents) FILTER (WHERE component.code = 'LOAN_REPAYMENT')
                        AS loan_back,
                    sum(CASE WHEN component.ledger_account_code <> '6030' THEN 0
                        WHEN component.direction = 'EARNING' THEN line.amount_usd_cents
                        ELSE -line.amount_usd_cents END) AS cost
                FROM app.payroll_lines AS line
                JOIN app.salary_components AS component ON component.code = line.component_code
                WHERE line.payroll_run_id = p_run AND app.hr_line_live(line.id)
                GROUP BY line.employee_id
            LOOP
                IF coalesce(v_person.earnings, 0) - coalesce(v_person.deductions, 0) < 0 THEN
                    RAISE EXCEPTION 'Net pay is below zero' USING ERRCODE = '22023';
                END IF;
                IF v_person.cost < 0 THEN
                    RAISE EXCEPTION 'A correction only adds pay: take money back with a minus line in the next payroll'
                        USING ERRCODE = '22023';
                END IF;
                v_slip := gen_random_uuid();
                v_cost := coalesce(v_person.cost, 0);
                v_loan := coalesce(v_person.loan_back, 0);
                v_lines := '[]'::jsonb;
                IF v_cost > 0 THEN
                    v_lines := v_lines || jsonb_build_array(jsonb_build_object('account', '6030',
                        'debit_cents', v_cost, 'employee_id', v_person.employee_id));
                END IF;
                IF v_loan > 0 THEN
                    v_lines := v_lines || jsonb_build_array(jsonb_build_object('account', '1210',
                        'credit_cents', v_loan, 'employee_id', v_person.employee_id));
                END IF;
                IF v_cost - v_loan > 0 THEN
                    v_lines := v_lines || jsonb_build_array(jsonb_build_object('account', '2300',
                        'credit_cents', v_cost - v_loan, 'employee_id', v_person.employee_id));
                END IF;
                v_entry := NULL;
                IF jsonb_array_length(v_lines) >= 2 THEN
                    v_entry := app.gl_post_entry(p_property, v_month_end, 'AUTO',
                        'Salary ' || to_char(v_run.salary_month, 'MM/YYYY') || ' '
                            || (SELECT employee.employee_code FROM app.employees AS employee
                                WHERE employee.id = v_person.employee_id)
                            || ' (' || v_run.run_number || ')',
                        'PAYSLIP', v_slip, 'payslip:' || v_slip || '\\:approved', NULL, p_actor,
                        p_actor, coalesce(p_correlation, gen_random_uuid()), v_lines);
                END IF;
                INSERT INTO app.payslips (id, payroll_run_id, employee_id, earnings_usd_cents,
                    deductions_usd_cents, net_pay_usd_cents, payment_method, aba_account_name,
                    aba_account_number, entry_id)
                SELECT v_slip, p_run, v_person.employee_id, coalesce(v_person.earnings, 0),
                    coalesce(v_person.deductions, 0),
                    coalesce(v_person.earnings, 0) - coalesce(v_person.deductions, 0),
                    coalesce(pay.payment_method, 'CASH_USD'), pay.aba_account_name,
                    pay.aba_account_number, v_entry
                FROM (SELECT 1) AS one
                LEFT JOIN LATERAL app.hr_pay_on(v_person.employee_id, v_month_end) AS pay ON true;
            END LOOP;
        ELSE
            RAISE EXCEPTION 'Unknown step' USING ERRCODE = '22023';
        END IF;
        PERFORM app.hr_audit(p_property, p_actor, 'hr.payroll.' || lower(p_step), 'payroll_run',
            p_run, coalesce(v_reason, v_note, initcap(lower(replace(p_step, '_', ' ')))),
            p_correlation, jsonb_build_object('state', v_state),
            jsonb_build_object('state', app.hr_payroll_state(p_run), 'own_request_note', v_note));
    END $$;

    -- PR-HR-030: Mark paid writes 2300 down and cash or the joint ABA account down.
    CREATE FUNCTION app.hr_pay_salary(p_property uuid, p_payslip uuid, p_body jsonb,
        p_actor uuid, p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.payroll.pay', p_property);
        v_slip record;
        v_on date := coalesce(app.hr_date(p_body, 'paid_on', 'The date is not a date'), v_day);
        v_method text;
        v_code text;
        v_id uuid := gen_random_uuid();
        v_entry uuid;
        v_note text;
        v_reference text := app.problem_text(p_body, 'bank_reference', 80,
            'The bank reference is at most 80 letters');
    BEGIN
        SELECT slip.*, run.run_number, run.salary_month, employee.employee_code,
            employee.user_actor_id INTO v_slip
        FROM app.payslips AS slip
        JOIN app.payroll_runs AS run ON run.id = slip.payroll_run_id
        JOIN app.employees AS employee ON employee.id = slip.employee_id
        WHERE slip.id = p_payslip AND run.property_id = p_property
        FOR UPDATE OF slip;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The payslip was not found' USING ERRCODE = '22023';
        END IF;
        IF v_slip.net_pay_usd_cents = 0 THEN
            RAISE EXCEPTION 'There is nothing to pay on this payslip' USING ERRCODE = '55000';
        END IF;
        IF EXISTS (SELECT 1 FROM app.salary_payments AS payment WHERE payment.payslip_id = p_payslip
                AND NOT EXISTS (SELECT 1 FROM app.salary_payment_reversals AS undo
                    WHERE undo.salary_payment_id = payment.id)) THEN
            RAISE EXCEPTION 'This salary is already marked paid' USING ERRCODE = '55000';
        END IF;
        v_method := coalesce(app.problem_text(p_body, 'method', 20, 'Choose cash or ABA'),
            CASE WHEN v_slip.payment_method = 'ABA' THEN 'ABA_JOINT' ELSE 'CASH_USD' END);
        IF v_method NOT IN ('CASH_USD', 'ABA_JOINT') THEN
            RAISE EXCEPTION 'Choose cash or the joint ABA account' USING ERRCODE = '22023';
        END IF;
        v_note := app.hr_own_check(p_actor, v_slip.user_actor_id IS NOT DISTINCT FROM p_actor,
            p_body ->> 'own_request_note');
        PERFORM app.gl_check_record_day(p_property, v_on);
        v_code := (app.gl_money_account(p_property, app.hr_cash_code(v_method))).code;
        v_entry := app.gl_post_entry(p_property, v_on, 'AUTO',
            'Salary paid ' || to_char(v_slip.salary_month, 'MM/YYYY') || ' ' || v_slip.employee_code,
            'SALARY_PAYMENT', v_id, 'salary_payment:' || v_id || '\\:paid', NULL, p_actor, NULL,
            coalesce(p_correlation, gen_random_uuid()), jsonb_build_array(
                jsonb_build_object('account', '2300', 'debit_cents', v_slip.net_pay_usd_cents,
                    'employee_id', v_slip.employee_id, 'memo', v_slip.run_number),
                jsonb_build_object('account', v_code, 'credit_cents', v_slip.net_pay_usd_cents,
                    'employee_id', v_slip.employee_id, 'memo', v_reference)));
        INSERT INTO app.salary_payments (id, payslip_id, paid_on, method, amount_usd_cents,
            bank_reference, own_request_note, entry_id, created_by)
        VALUES (v_id, p_payslip, v_on, v_method, v_slip.net_pay_usd_cents, v_reference, v_note,
            v_entry, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.salary.paid', 'payslip', p_payslip,
            coalesce(v_note, 'Salary marked paid'), p_correlation, NULL,
            jsonb_build_object('payment_id', v_id, 'paid_on', v_on, 'method', v_method,
                'amount_usd_cents', v_slip.net_pay_usd_cents));
        RETURN v_id;
    END $$;

    CREATE FUNCTION app.hr_reverse_salary_payment(p_property uuid, p_payment uuid, p_reason text,
        p_actor uuid, p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'hr.payroll.pay', p_property);
        v_payment record;
        v_reason text := nullif(btrim(p_reason), '');
        v_entry uuid;
    BEGIN
        SELECT payment.* INTO v_payment FROM app.salary_payments AS payment
        JOIN app.payslips AS slip ON slip.id = payment.payslip_id
        JOIN app.payroll_runs AS run ON run.id = slip.payroll_run_id
        WHERE payment.id = p_payment AND run.property_id = p_property
        FOR UPDATE OF payment;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The payment was not found' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.salary_payment_reversals AS undo
                WHERE undo.salary_payment_id = p_payment) THEN
            RAISE EXCEPTION 'The payment is already reversed' USING ERRCODE = '55000';
        END IF;
        IF v_reason IS NULL OR length(v_reason) > 500 THEN
            RAISE EXCEPTION 'Say why' USING ERRCODE = '22023';
        END IF;
        PERFORM app.gl_check_record_day(p_property, v_day);
        v_entry := app.gl_reverse_entry(v_payment.entry_id, v_day, v_reason, p_actor,
            'salary_payment_reversal:' || p_payment, coalesce(p_correlation, gen_random_uuid()));
        INSERT INTO app.salary_payment_reversals (salary_payment_id, reason, entry_id, created_by)
        VALUES (p_payment, v_reason, v_entry, p_actor);
        PERFORM app.hr_audit(p_property, p_actor, 'hr.salary.payment_reversed', 'salary_payment',
            p_payment, v_reason, p_correlation, NULL, jsonb_build_object('entry_id', v_entry));
        RETURN v_entry;
    END $$;

    -- PR-HR-032: the month closes after its REGULAR payroll is approved (or nobody worked).
    CREATE FUNCTION app.hr_payroll_month_approved(p_property uuid, p_month date) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT EXISTS (SELECT 1 FROM app.payroll_runs AS run
                WHERE run.property_id = p_property AND run.run_kind = 'REGULAR'
                  AND run.salary_month = date_trunc('month', p_month)::date
                  AND app.hr_payroll_state(run.id) = 'APPROVED')
            OR NOT EXISTS (SELECT 1 FROM app.employees AS employee
                WHERE employee.property_id = p_property
                  AND app.hr_hired_on(employee.id) <= (date_trunc('month', p_month)
                      + interval '1 month' - interval '1 day')::date
                  AND coalesce(app.hr_left_on(employee.id), p_month) >= date_trunc('month', p_month)::date)
    $$;
    REVOKE ALL ON FUNCTION app.hr_payroll_month_approved(uuid, date) FROM PUBLIC;
"""

RUNTIME = (
    "app.hr_loans_read(uuid, uuid)",
    "app.hr_add_loan(uuid, jsonb, uuid, uuid)",
    "app.hr_decide_loan(uuid, uuid, jsonb, uuid, uuid)",
    "app.hr_payrolls_read(uuid, uuid)",
    "app.hr_payroll_read(uuid, uuid, uuid, uuid)",
    "app.hr_make_payroll(uuid, date, uuid, uuid)",
    "app.hr_make_correction(uuid, uuid, text, uuid, uuid)",
    "app.hr_payroll_step(uuid, uuid, text, jsonb, uuid, uuid)",
    # Ledger money records run on the runtime connection, like the General Ledger's own.
    "app.hr_pay_out_loan(uuid, uuid, date, uuid, uuid)",
    "app.hr_pay_salary(uuid, uuid, jsonb, uuid, uuid)",
    "app.hr_reverse_salary_payment(uuid, uuid, text, uuid, uuid)",
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
    component_rows = ",\n            ".join(
        f"({_text(code)}, {_text(direction)}, {_text(account)}, {str(used).lower()}, "
        f"{_text(en)}, {_text(km)}, {order})"
        for order, (code, direction, account, used, en, km) in enumerate(COMPONENTS, start=1)
    )
    op.execute(
        f"""
        INSERT INTO app.salary_components (code, direction, ledger_account_code, in_use, name_en,
            name_km, sort_order)
        VALUES
            {component_rows}
        """
    )
    op.execute(FUNCTIONS)
    op.execute(
        """
        CREATE TRIGGER payroll_lines_open BEFORE INSERT ON app.payroll_lines
            FOR EACH ROW EXECUTE FUNCTION app.hr_payroll_open_check();
        CREATE TRIGGER payroll_line_removals_open BEFORE INSERT ON app.payroll_line_removals
            FOR EACH ROW EXECUTE FUNCTION app.hr_payroll_open_check();
        """
    )
    _patch(RANGE, ((RANGE_BEFORE, RANGE_AFTER),))
    op.execute(
        f"""
        WITH named AS (
            INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                used_by_app)
            VALUES ('LOAN_OPEN_MAX', 'Open salary loans per person',
                'ប្រាក់កម្ចីប្រាក់ខែដែលមិនទាន់សងរួចក្នុងម្នាក់', 'COUNT', 'STAFF', true)
            RETURNING id
        )
        INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
        SELECT named.id, 1, DATE '2026-01-01', {_text(SEED_REASON)},
            (SELECT classification.actor_id FROM app.user_account_classes AS classification
             WHERE classification.account_class = 'owner')
        FROM named
        """
    )
    _patch(CLOSE, ((CLOSE_BEFORE, CLOSE_AFTER),))
    tables = ", ".join(f"app.{name}" for name in APPEND_ONLY)
    op.execute(
        f"""
        REVOKE ALL ON TABLE {tables} FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.salary_components TO prm_runtime;
        """
    )
    for signature in RUNTIME:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("HRIS payroll migration is forward-only")
