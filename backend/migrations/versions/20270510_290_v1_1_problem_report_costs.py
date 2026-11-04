# ruff: noqa: E501
"""Problem reports: the repair cost and its Expense report (DL-130).

The owner approved this in the Problem report design of 03/11/2026: PRD TgzDEoZYdvv4jAfHf1PBhC
Q1-Q5, the card "As already spent" (03/11 12:53), and tech plan V4Z3MBAh2xbmA4ZXH9VjG4 Q1
("USD or KHR per line"). The coding was asked for on 04/11/2026.

1. From Repair planned on, staff (``problem_reports.add``) type what it cost: parts and outside
   workers only (own staff are paid by payroll), each line in dollars (cents) or riel. "No cost"
   says the repair cost nothing. A new entry replaces the last one until it is checked; every
   entry is kept (``problem_report_cost_sets`` and ``problem_report_cost_lines``, append-only).
2. A Manager checks the entry and confirms the receipt was seen
   (``problem_report_cost_checks``). The right is the new ``problem_reports.costs`` ("Check
   repair costs", mock-up rights A9); the Owner and Manager roles get it. The check makes one Expense report (an Expense request
   already spent, ``URGENT_REPORT``) on account 6050 Repairs and maintenance for the Unit, one per
   currency, through ``app.gl_submit_expense_request``. It then follows the normal Expense
   approval. Riel uses today's riel rate, like every riel Expense request.
3. A checked entry is locked. Only when every Expense report it made was refused or voided can
   staff type the cost again.

Receipt photos wait for the shared media files of the Telegram base.
Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270510_290"
down_revision: str | None = "20270429_279"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-problem-reports"
COSTS = "problem_reports.costs"
COSTS_TEXT = "Check repair costs and make their Expense reports"
PERMISSION = ("PROBLEM_REPORTS_COSTS", "Check repair costs", "ពិនិត្យថ្លៃជួសជុល")
REASON = "Owner 2026-11-03 Problem report design: Check repair costs right"
READ_JSON = "app.problem_report_json(uuid, boolean)"
JSON_BEFORE = "'done_at', base.done_at,"
JSON_AFTER = (
    "'done_at', base.done_at,\n"
    "            'cost', CASE WHEN p_full THEN app.problem_report_cost_json(base.id) END,"
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
    -- 1. What a repair cost: each entry is a set of lines (or "no cost"); a new entry replaces
    -- the last one until a Manager checks it.
    CREATE TABLE app.problem_report_cost_sets (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        report_id uuid NOT NULL REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        set_no integer NOT NULL CHECK (set_no > 0),
        no_cost boolean NOT NULL DEFAULT false,
        note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
        entered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        entered_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        UNIQUE (report_id, set_no)
    );

    CREATE TABLE app.problem_report_cost_lines (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        set_id uuid NOT NULL REFERENCES app.problem_report_cost_sets (id) ON DELETE RESTRICT,
        line_no smallint NOT NULL CHECK (line_no BETWEEN 1 AND 20),
        kind text NOT NULL CHECK (kind IN ('PARTS', 'OUTSIDE_WORKER')),
        description text NOT NULL
            CHECK (description = btrim(description) AND length(description) BETWEEN 1 AND 200),
        currency text NOT NULL CHECK (currency IN ('USD', 'KHR')),
        -- Cents for dollars, whole riel for riel.
        amount_minor bigint NOT NULL CHECK (amount_minor BETWEEN 1 AND 9000000000000),
        UNIQUE (set_id, line_no)
    );

    -- 2. A Manager's check of one entry, with the receipt seen.
    CREATE TABLE app.problem_report_cost_checks (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        set_id uuid NOT NULL UNIQUE REFERENCES app.problem_report_cost_sets (id) ON DELETE RESTRICT,
        receipt_seen boolean NOT NULL CHECK (receipt_seen),
        spent_on date NOT NULL,
        paid_how text NOT NULL CHECK (paid_how IN ('OWN_MONEY', 'CASH')),
        checked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        checked_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );

    -- 3. The Expense reports a check made, one per currency.
    CREATE TABLE app.problem_report_cost_expense_requests (
        check_id uuid NOT NULL REFERENCES app.problem_report_cost_checks (id) ON DELETE RESTRICT,
        currency text NOT NULL CHECK (currency IN ('USD', 'KHR')),
        expense_request_id uuid NOT NULL UNIQUE
            REFERENCES app.gl_expense_requests (id) ON DELETE RESTRICT,
        PRIMARY KEY (check_id, currency)
    );

    CREATE TRIGGER problem_report_cost_sets_append_only BEFORE UPDATE OR DELETE
        ON app.problem_report_cost_sets
        FOR EACH ROW EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_cost_lines_append_only BEFORE UPDATE OR DELETE
        ON app.problem_report_cost_lines
        FOR EACH ROW EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_cost_checks_append_only BEFORE UPDATE OR DELETE
        ON app.problem_report_cost_checks
        FOR EACH ROW EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_cost_expense_requests_append_only BEFORE UPDATE OR DELETE
        ON app.problem_report_cost_expense_requests
        FOR EACH ROW EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_cost_sets_no_truncate BEFORE TRUNCATE
        ON app.problem_report_cost_sets
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_cost_lines_no_truncate BEFORE TRUNCATE
        ON app.problem_report_cost_lines
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_cost_checks_no_truncate BEFORE TRUNCATE
        ON app.problem_report_cost_checks
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_cost_expense_requests_no_truncate BEFORE TRUNCATE
        ON app.problem_report_cost_expense_requests
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();
"""

FUNCTIONS = """
    -- The latest entry of a report, or NULL.
    CREATE FUNCTION app.problem_report_cost_latest(p_report uuid)
    RETURNS app.problem_report_cost_sets LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT cost_set.* FROM app.problem_report_cost_sets AS cost_set
        WHERE cost_set.report_id = p_report ORDER BY cost_set.set_no DESC LIMIT 1
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_cost_latest(uuid) FROM PUBLIC;

    -- Whether staff may type the cost (again): no entry yet, the last one is not checked, or
    -- every Expense report its check made was refused or voided.
    CREATE FUNCTION app.problem_report_cost_open(p_report uuid)
    RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT NOT EXISTS (
            SELECT 1 FROM app.problem_report_cost_sets AS cost_set
            JOIN app.problem_report_cost_checks AS checked ON checked.set_id = cost_set.id
            WHERE cost_set.report_id = p_report
              AND cost_set.set_no = (SELECT max(last_set.set_no)
                  FROM app.problem_report_cost_sets AS last_set
                  WHERE last_set.report_id = p_report)
              AND EXISTS (SELECT 1 FROM app.problem_report_cost_expense_requests AS made
                  JOIN app.gl_expense_requests AS request ON request.id = made.expense_request_id
                  WHERE made.check_id = checked.id
                    AND request.status NOT IN ('REFUSED', 'VOID')))
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_cost_open(uuid) FROM PUBLIC;

    -- The cost box of one report: the latest entry, its check and its Expense reports.
    CREATE FUNCTION app.problem_report_cost_json(p_report uuid)
    RETURNS jsonb LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN cost_set.id IS NULL THEN NULL ELSE jsonb_build_object(
            'set_no', cost_set.set_no,
            'no_cost', cost_set.no_cost,
            'note', cost_set.note,
            'entered_at', cost_set.entered_at,
            'entered_by_name', maker.display_name,
            'lines', COALESCE((
                SELECT jsonb_agg(jsonb_build_object('kind', line.kind,
                        'description', line.description, 'currency', line.currency,
                        'amount_minor', line.amount_minor) ORDER BY line.line_no)
                FROM app.problem_report_cost_lines AS line WHERE line.set_id = cost_set.id),
                '[]'::jsonb),
            'totals', COALESCE((
                SELECT jsonb_agg(jsonb_build_object('currency', total.currency,
                        'amount_minor', total.amount_minor) ORDER BY total.currency DESC)
                FROM (SELECT line.currency, sum(line.amount_minor)::bigint AS amount_minor
                      FROM app.problem_report_cost_lines AS line WHERE line.set_id = cost_set.id
                      GROUP BY line.currency) AS total), '[]'::jsonb),
            'check', CASE WHEN checked.id IS NULL THEN NULL ELSE jsonb_build_object(
                'checked_at', checked.checked_at, 'checked_by_name', checker.display_name,
                'receipt_seen', checked.receipt_seen, 'spent_on', checked.spent_on,
                'paid_how', checked.paid_how) END,
            'expense_requests', COALESCE((
                SELECT jsonb_agg(jsonb_build_object('request_number', request.request_number,
                        'status', request.status, 'currency', made.currency,
                        'amount_cents', request.amount_cents,
                        'original_amount_minor', request.original_amount_minor)
                        ORDER BY made.currency DESC)
                FROM app.problem_report_cost_expense_requests AS made
                JOIN app.gl_expense_requests AS request ON request.id = made.expense_request_id
                WHERE made.check_id = checked.id), '[]'::jsonb),
            'can_enter', app.problem_report_cost_open(p_report)) END
        FROM (SELECT 1) AS one
        LEFT JOIN app.problem_report_cost_latest(p_report) AS cost_set ON true
        LEFT JOIN app.user_accounts AS maker ON maker.actor_id = cost_set.entered_by
        LEFT JOIN app.problem_report_cost_checks AS checked ON checked.set_id = cost_set.id
        LEFT JOIN app.user_accounts AS checker ON checker.actor_id = checked.checked_by
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_cost_json(uuid) FROM PUBLIC;

    -- 1. Staff type what the repair cost, at the version that was read.
    CREATE FUNCTION app.record_problem_report_cost(p_property uuid, p_report uuid,
        p_expected_version integer, p_input jsonb, p_actor uuid, p_correlation uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'problem_reports.add', p_property);
        v_report app.problem_reports%ROWTYPE;
        v_input jsonb := COALESCE(p_input, '{}'::jsonb);
        v_no_cost boolean;
        v_note text;
        v_lines jsonb;
        v_line jsonb;
        v_kind text;
        v_description text;
        v_currency text;
        v_amount numeric;
        v_set uuid := gen_random_uuid();
        v_set_no integer;
        v_count integer := 0;
    BEGIN
        IF jsonb_typeof(v_input) <> 'object' THEN
            RAISE EXCEPTION 'The cost is invalid' USING ERRCODE = '22023';
        END IF;
        SELECT report.* INTO v_report FROM app.problem_reports AS report
        WHERE report.id = p_report AND report.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Problem report does not exist' USING ERRCODE = '22023';
        END IF;
        IF p_expected_version IS DISTINCT FROM v_report.version THEN
            RAISE EXCEPTION 'the Problem report changed since it was read' USING ERRCODE = '40001';
        END IF;
        IF NOT (app.problem_report_state(p_report) IN ('REPAIR_PLANNED', 'WAITING_PARTS', 'DONE')
                OR (app.problem_report_state(p_report) = 'CLOSED' AND v_report.done_at IS NOT NULL)) THEN
            RAISE EXCEPTION 'The cost is typed once the repair is planned' USING ERRCODE = '55000';
        END IF;
        IF NOT app.problem_report_cost_open(p_report) THEN
            RAISE EXCEPTION 'The cost is already checked' USING ERRCODE = '55000';
        END IF;
        IF jsonb_typeof(COALESCE(v_input -> 'no_cost', 'false'::jsonb)) <> 'boolean' THEN
            RAISE EXCEPTION 'The cost is invalid' USING ERRCODE = '22023';
        END IF;
        v_no_cost := COALESCE((v_input ->> 'no_cost')::boolean, false);
        v_note := app.problem_text(v_input, 'note', 500, 'The note is at most 500 letters');
        v_lines := COALESCE(v_input -> 'lines', '[]'::jsonb);
        IF jsonb_typeof(v_lines) <> 'array' THEN
            RAISE EXCEPTION 'The cost is invalid' USING ERRCODE = '22023';
        END IF;
        IF v_no_cost AND jsonb_array_length(v_lines) > 0 THEN
            RAISE EXCEPTION 'No cost has no lines' USING ERRCODE = '22023';
        END IF;
        IF NOT v_no_cost AND jsonb_array_length(v_lines) NOT BETWEEN 1 AND 20 THEN
            RAISE EXCEPTION 'Type 1 to 20 cost lines, or choose No cost' USING ERRCODE = '22023';
        END IF;
        SELECT COALESCE(max(cost_set.set_no), 0) + 1 INTO v_set_no
        FROM app.problem_report_cost_sets AS cost_set WHERE cost_set.report_id = p_report;
        INSERT INTO app.problem_report_cost_sets (id, report_id, set_no, no_cost, note, entered_by)
        VALUES (v_set, p_report, v_set_no, v_no_cost, v_note, p_actor);
        FOR v_line IN SELECT value FROM jsonb_array_elements(v_lines) LOOP
            v_count := v_count + 1;
            IF jsonb_typeof(v_line) <> 'object' THEN
                RAISE EXCEPTION 'Cost line % is invalid', v_count USING ERRCODE = '22023';
            END IF;
            v_kind := v_line ->> 'kind';
            IF v_kind IS NULL OR v_kind NOT IN ('PARTS', 'OUTSIDE_WORKER') THEN
                RAISE EXCEPTION 'Cost line %: choose parts or outside worker', v_count
                    USING ERRCODE = '22023';
            END IF;
            v_description := app.problem_text(v_line, 'description', 200,
                format('Cost line %s: say what it is, at most 200 letters', v_count));
            IF v_description IS NULL THEN
                RAISE EXCEPTION 'Cost line %: say what it is, at most 200 letters', v_count
                    USING ERRCODE = '22023';
            END IF;
            v_currency := v_line ->> 'currency';
            IF v_currency IS NULL OR v_currency NOT IN ('USD', 'KHR') THEN
                RAISE EXCEPTION 'Cost line %: choose dollars or riel', v_count USING ERRCODE = '22023';
            END IF;
            IF jsonb_typeof(v_line -> 'amount_minor') IS DISTINCT FROM 'number' THEN
                RAISE EXCEPTION 'Cost line %: type the amount', v_count USING ERRCODE = '22023';
            END IF;
            v_amount := (v_line ->> 'amount_minor')::numeric;
            IF v_amount <> trunc(v_amount) OR v_amount < 1 OR v_amount > 9000000000000 THEN
                RAISE EXCEPTION 'Cost line %: type an amount above zero', v_count
                    USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.problem_report_cost_lines (set_id, line_no, kind, description,
                currency, amount_minor)
            VALUES (v_set, v_count, v_kind, v_description, v_currency, v_amount::bigint);
        END LOOP;
        UPDATE app.problem_reports SET version = version + 1 WHERE id = p_report;
        PERFORM app.problem_report_event(p_report, 'COST_ENTERED', v_note,
            jsonb_build_object('set_no', v_set_no, 'no_cost', v_no_cost, 'totals', COALESCE((
                SELECT jsonb_object_agg(line.currency, line.total)
                FROM (SELECT cost_line.currency, sum(cost_line.amount_minor)::bigint AS total
                      FROM app.problem_report_cost_lines AS cost_line
                      WHERE cost_line.set_id = v_set GROUP BY cost_line.currency) AS line),
                '{}'::jsonb)), p_actor);
        PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.cost_entered',
            'problem_report', p_report, COALESCE(v_note, 'Repair cost typed'), 'problem_reports.add',
            NULL, jsonb_build_object('set_no', v_set_no, 'no_cost', v_no_cost, 'lines', v_count),
            p_correlation);
        RETURN v_report.version + 1;
    END $$;

    -- 2. A Manager checks the cost with the receipt; the check makes the Expense reports.
    CREATE FUNCTION app.check_problem_report_cost(p_property uuid, p_report uuid,
        p_expected_version integer, p_input jsonb, p_actor uuid, p_correlation uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'problem_reports.costs', p_property);
        v_report app.problem_reports%ROWTYPE;
        v_set app.problem_report_cost_sets%ROWTYPE;
        v_input jsonb := COALESCE(p_input, '{}'::jsonb);
        v_spent_on date;
        v_paid_how text;
        v_from text;
        v_check uuid := gen_random_uuid();
        v_total record;
        v_rate_id uuid;
        v_rate bigint;
        v_cents bigint;
        v_request uuid;
        v_place text;
        v_made jsonb := '[]'::jsonb;
        -- The ledger's audit rows need a correlation; one id ties the check to its reports.
        v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
    BEGIN
        IF jsonb_typeof(v_input) <> 'object' THEN
            RAISE EXCEPTION 'The check is invalid' USING ERRCODE = '22023';
        END IF;
        SELECT report.* INTO v_report FROM app.problem_reports AS report
        WHERE report.id = p_report AND report.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Problem report does not exist' USING ERRCODE = '22023';
        END IF;
        IF p_expected_version IS DISTINCT FROM v_report.version THEN
            RAISE EXCEPTION 'the Problem report changed since it was read' USING ERRCODE = '40001';
        END IF;
        v_set := app.problem_report_cost_latest(p_report);
        IF v_set.id IS NULL OR v_set.no_cost
            OR EXISTS (SELECT 1 FROM app.problem_report_cost_checks AS checked
                       WHERE checked.set_id = v_set.id) THEN
            RAISE EXCEPTION 'There is no cost waiting for a check' USING ERRCODE = '55000';
        END IF;
        IF v_input -> 'receipt_seen' IS DISTINCT FROM 'true'::jsonb THEN
            RAISE EXCEPTION 'Check the receipt first' USING ERRCODE = '22023';
        END IF;
        BEGIN
            v_spent_on := (v_input ->> 'spent_on')::date;
        EXCEPTION WHEN data_exception THEN
            RAISE EXCEPTION 'Choose the day the money was spent' USING ERRCODE = '22023';
        END;
        IF v_spent_on IS NULL THEN
            RAISE EXCEPTION 'Choose the day the money was spent' USING ERRCODE = '22023';
        END IF;
        v_paid_how := v_input ->> 'paid_how';
        IF v_paid_how IS NULL OR v_paid_how NOT IN ('OWN_MONEY', 'CASH') THEN
            RAISE EXCEPTION 'Choose staff''s own money or petty cash' USING ERRCODE = '22023';
        END IF;
        v_from := app.problem_text(v_input, 'paid_from_code', 20, 'Choose the petty cash account');
        IF (v_paid_how = 'CASH') <> (v_from IS NOT NULL) THEN
            RAISE EXCEPTION 'Only petty cash names the account it is paid from'
                USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.problem_report_cost_checks (id, set_id, receipt_seen, spent_on, paid_how,
            checked_by)
        VALUES (v_check, v_set.id, true, v_spent_on, v_paid_how, p_actor);
        v_place := CASE WHEN v_report.kind = 'UNIT' THEN (SELECT 'Unit ' || unit.unit_number
                FROM app.units AS unit WHERE unit.id = v_report.unit_id)
            ELSE 'the building' END;
        FOR v_total IN
            SELECT line.currency, sum(line.amount_minor)::bigint AS amount_minor,
                string_agg(line.description, ', ' ORDER BY line.line_no) AS what
            FROM app.problem_report_cost_lines AS line WHERE line.set_id = v_set.id
            GROUP BY line.currency ORDER BY line.currency DESC
        LOOP
            v_rate_id := NULL;
            IF v_total.currency = 'KHR' THEN
                SELECT rate.id, rate.system_rate_khr_per_usd INTO v_rate_id, v_rate
                FROM app.list_exchange_rates_for_property(p_property, 101, NULL, NULL) AS rate
                WHERE rate.applicable_at <= now()
                ORDER BY rate.applicable_at DESC LIMIT 1;
                IF v_rate_id IS NULL OR v_rate IS NULL OR v_rate <= 0 THEN
                    RAISE EXCEPTION 'There is no riel rate for today' USING ERRCODE = '55000';
                END IF;
                v_cents := round(v_total.amount_minor * 100.0 / v_rate)::bigint;
                IF v_cents < 1 THEN
                    RAISE EXCEPTION 'The riel cost is less than one cent' USING ERRCODE = '22023';
                END IF;
            ELSE
                v_cents := v_total.amount_minor;
            END IF;
            v_request := app.gl_submit_expense_request(p_property, p_actor, 'URGENT_REPORT',
                '6050', left(format('Repair %s, %s: %s', v_report.report_number, v_place,
                    v_total.what), 500),
                left(format('Repair cost of Problem report %s, checked with the receipt.',
                    v_report.report_number), 1000),
                v_cents, v_total.currency,
                CASE WHEN v_total.currency = 'KHR' THEN v_total.amount_minor END, v_rate_id, NULL,
                v_report.unit_id, v_spent_on, v_paid_how, v_from, v_correlation);
            INSERT INTO app.problem_report_cost_expense_requests (check_id, currency,
                expense_request_id)
            VALUES (v_check, v_total.currency, v_request);
            v_made := v_made || jsonb_build_array((SELECT request.request_number
                FROM app.gl_expense_requests AS request WHERE request.id = v_request));
        END LOOP;
        UPDATE app.problem_reports SET version = version + 1 WHERE id = p_report;
        PERFORM app.problem_report_event(p_report, 'COST_CHECKED', NULL,
            jsonb_build_object('set_no', v_set.set_no, 'expense_requests', v_made), p_actor);
        PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.cost_checked',
            'problem_report', p_report, 'Repair cost checked with the receipt',
            'problem_reports.costs', NULL,
            jsonb_build_object('set_no', v_set.set_no, 'expense_requests', v_made), v_correlation);
        RETURN v_report.version + 1;
    END $$;
"""

RUNTIME = (
    "app.record_problem_report_cost(uuid, uuid, integer, jsonb, uuid, uuid)",
    "app.check_problem_report_cost(uuid, uuid, integer, jsonb, uuid, uuid)",
)


def upgrade() -> None:
    code, english, khmer = PERMISSION
    op.execute(
        f"""
        INSERT INTO app.capabilities (capability_id, family, description, grant_path, provenance)
        VALUES ({_text(COSTS)}, 'problem_reports', {_text(COSTS_TEXT)}, 'bundle', '{PROVENANCE}');
        INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, name_kh,
            provenance)
        VALUES ({_text(code)}, 'OPERATIONS', (SELECT max(sort_order) FROM app.permissions) + 1,
            {_text(english)}, {_text(khmer)}, '{PROVENANCE}');
        INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance)
        VALUES ({_text(code)}, {_text(COSTS)}, '{PROVENANCE}');
        """
    )
    # New Properties give the Owner and Manager every right already; the existing default
    # Owner and Manager roles get a new version with this one.
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
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version
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
                SELECT v_default.role_bundle_id, v_default.version + 1, {_text(COSTS)};
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
                            'capabilities_added', pg_catalog.jsonb_build_array({_text(COSTS)})),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    _patch(READ_JSON, ((JSON_BEFORE, JSON_AFTER),))
    op.execute(
        """
        REVOKE ALL ON TABLE app.problem_report_cost_sets, app.problem_report_cost_lines,
            app.problem_report_cost_checks, app.problem_report_cost_expense_requests
            FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.problem_report_cost_sets, app.problem_report_cost_lines,
            app.problem_report_cost_checks, app.problem_report_cost_expense_requests
            TO prm_runtime;
        """
    )
    for signature in RUNTIME:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("The Problem report cost migration is forward-only")
