# ruff: noqa: E501
"""V1.1 part 7 (owner 2026-11-04 "Start part 7"; card answer 03:38 "Problem report flow").

The repair flow is the Problem report design the owner approved on 03/11/2026 (PRD
TgzDEoZYdvv4jAfHf1PBhC, flows 6CwwEf1ir63bq25Mnq6iJP, tech plan V4Z3MBAh2xbmA4ZXH9VjG4, mock-up
round 32 and DESIGN.md 0.59), not the Repair Quotation of the 01/11 plan:

1. One list ``problem_reports`` for every problem: a Unit Problem (UPyy000n) inside one Unit,
   with its Lease and Primary Tenant when the Unit has a signed Lease, or a Building problem
   (BPyy000n) in a shared place with an optional floor. Each has a problem type
   (``problem_types``, 12 with icons; Safety is always urgent), a text, Urgent, staff may enter,
   best time, how it came in and who reported it.
2. The steps, each a row of ``problem_report_events`` (append-only): Contacted (urgent),
   Planned (technician, day, time), Checked (cause, note, fixed at once for an urgent one),
   Who pays (CHETANA, or the tenant with the amount the Manager sets and a reason), Waiting for
   the tenant's OK, Repair planned, Waiting for parts, Done, Closed (the tenant's Fixed, the
   Manager's close, or by itself after TR_AUTO_CLOSE_DAYS with no reply), Not accepted (not a
   repair), and for a Building problem: make a repair job, give it to cleaning, or close with a
   note. Not fixed opens the repair again.
3. The tenant's answer (staff record it until the Tenant bot comes, with how: signed paper,
   Telegram, phone or in person). Agree makes the Damage Invoice draft at once, for exactly the
   amount the Manager set (owner rule 03/11/2026 04:32), due the one-time charge days after it
   is issued. Refuse: no charge; CHETANA pays the repair, or the problem is left for the
   move-out inspection.
4. Join: a report of the same problem joins its main report (``problem_report_joins``); an undo
   is a row of ``problem_report_join_endings``. "Same problem" when adding a report saves it
   joined at once; only a Manager joins two saved reports or undoes a join.
5. Late (urgent not contacted after TR_URGENT_HOURS, normal not planned after TR_PLAN_WORKDAYS
   working days, Sunday is not one) and Repeat (REPEAT_COUNT reports of one type in one Unit in
   REPEAT_DAYS) are worked out when a report is read. The five numbers are business rules in the
   new area "Problem reports".
6. Rights problem_reports.read, .add, .plan and .join in the Operations group: the Owner and
   Manager have all four, Staff see and add.

Waits for later steps (no file storage, Telegram or Employees yet): photos, voice notes and
receipts, repair cost lines and their Expense request, the inspection link, and messages to the
tenant. The technician is a typed name until Employees exist.
Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270426_276"
down_revision: str | None = "20270425_275"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-problem-reports"
CAPABILITIES = (
    ("problem_reports.read", "See Problem reports"),
    ("problem_reports.add", "Add a Problem report"),
    (
        "problem_reports.plan",
        "Plan, check and close Problem reports and record the tenant's answer",
    ),
    ("problem_reports.join", "Join Problem reports and undo a join"),
)
PERMISSIONS = (
    ("PROBLEM_REPORTS_SEE", "See Problem reports", "មើលរបាយការណ៍បញ្ហា", ("problem_reports.read",)),
    ("PROBLEM_REPORTS_ADD", "Add a Problem report", "បន្ថែមរបាយការណ៍បញ្ហា", ("problem_reports.add",)),
    (
        "PROBLEM_REPORTS_PLAN",
        "Plan and close Problem reports",
        "រៀបចំ និងបិទរបាយការណ៍បញ្ហា",
        ("problem_reports.plan",),
    ),
    (
        "PROBLEM_REPORTS_JOIN",
        "Join Problem reports and undo joins",
        "ភ្ជាប់របាយការណ៍បញ្ហា និងដកការភ្ជាប់",
        ("problem_reports.join",),
    ),
)
OWNER = (
    "problem_reports.read",
    "problem_reports.add",
    "problem_reports.plan",
    "problem_reports.join",
)
STAFF = ("problem_reports.read", "problem_reports.add")
REASON = "Owner 2026-11-04 part 7: Problem report rights"
SEED_REASON = "First value: the owner's Problem report rules (03/11/2026)"

SEED = "app.seed_default_role_bundles(uuid)"
STAFF_BEFORE = "'quotations.read']::text[]"
RANGE = "app.business_rules_program_range()"
RANGE_BEFORE = "OR (v_code = 'RESERVATION_DEPOSIT_PERCENT' AND NEW.value NOT BETWEEN 1 AND 10000)"
RANGE_AFTER = (
    RANGE_BEFORE
    + "\n                OR (v_code = 'REPEAT_COUNT' AND NEW.value NOT BETWEEN 2 AND 20)"
    + "\n                OR (v_code = 'REPEAT_DAYS' AND NEW.value NOT BETWEEN 1 AND 365)"
    + "\n                OR (v_code = 'TR_URGENT_HOURS' AND NEW.value NOT BETWEEN 1 AND 72)"
    + "\n                OR (v_code = 'TR_PLAN_WORKDAYS' AND NEW.value NOT BETWEEN 1 AND 30)"
    + "\n                OR (v_code = 'TR_AUTO_CLOSE_DAYS' AND NEW.value NOT BETWEEN 1 AND 30)"
)

# code, unit, value, English, Khmer (mock-up round 29 and 32 names)
RULES = (
    (
        "REPEAT_COUNT",
        "COUNT",
        3,
        "Repeat label: same problem this many times",
        "ស្លាកម្ដងទៀត៖ បញ្ហាដដែលចំនួនដងនេះ",
    ),
    (
        "REPEAT_DAYS",
        "DAYS",
        90,
        "Repeat label: within this many days",
        "ស្លាកម្ដងទៀត៖ ក្នុងរយៈពេលប៉ុន្មានថ្ងៃនេះ",
    ),
    (
        "TR_URGENT_HOURS",
        "HOURS",
        1,
        "Urgent: contact the tenant within",
        "បន្ទាន់៖ ទាក់ទងអ្នកជួលក្នុងរយៈពេល",
    ),
    (
        "TR_PLAN_WORKDAYS",
        "DAYS",
        1,
        "Normal: plan the visit within (working days)",
        "ធម្មតា៖ រៀបចំការមកពិនិត្យក្នុងរយៈពេល (ថ្ងៃធ្វើការ)",
    ),
    (
        "TR_AUTO_CLOSE_DAYS",
        "DAYS",
        3,
        "Done report closes by itself after",
        "របាយការណ៍រួចរាល់បិទដោយខ្លួនឯងក្រោយ",
    ),
)

# code, icon, always urgent, English, Khmer (PRD "Problem types"; mock-up TY37)
TYPES = (
    ("WATER", "drop", False, "Water", "ទឹក"),
    ("ELECTRICITY", "zap", False, "Electricity", "អគ្គិសនី"),
    ("AIR_CONDITIONER", "snow", False, "Air conditioner", "ម៉ាស៊ីនត្រជាក់"),
    ("DOOR_LOCK", "lock", False, "Door and lock", "ទ្វារ និងសោ"),
    ("WINDOW", "window", False, "Window", "បង្អួច"),
    ("FURNITURE", "sofa", False, "Furniture or appliance", "គ្រឿងសង្ហារឹម ឬឧបករណ៍"),
    ("INTERNET", "wifi", False, "Internet", "អ៊ីនធឺណិត"),
    ("PESTS", "bug", False, "Pests", "សត្វល្អិត"),
    ("CLEANING", "broom", False, "Cleaning", "ការសម្អាត"),
    ("NOISE", "volume", False, "Noise", "សំឡេងរំខាន"),
    ("SAFETY", "flame", True, "Safety (fire, gas, smoke)", "សុវត្ថិភាព (ភ្លើង ហ្គាស ផ្សែង)"),
    ("OTHER", "dots", False, "Other", "ផ្សេងៗ"),
)
PLACES = (
    ("STAIRS", "Stairs", "ជណ្ដើរ"),
    ("CORRIDOR", "Corridor", "ច្រករបៀង"),
    ("PARKING", "Parking", "ចំណតយានយន្ត"),
    ("LIFT", "Lift", "ជណ្ដើរយន្ត"),
    ("GATE", "Gate", "ទ្វារធំ"),
    ("RUBBISH", "Rubbish area", "កន្លែងសំរាម"),
    ("ROOF", "Roof", "ដំបូល"),
    ("OUTSIDE", "Outside", "ខាងក្រៅ"),
    ("OTHER", "Other", "ផ្សេងៗ"),
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
    -- 1. Problem types and shared places (edited in Settings later; never deleted, only turned off).
    CREATE TABLE app.problem_types (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z][A-Z_]{1,40}$'),
        name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 80),
        name_kh text NOT NULL CHECK (name_kh = btrim(name_kh) AND length(name_kh) BETWEEN 1 AND 80),
        icon text NOT NULL CHECK (icon ~ '^[a-z]{2,20}$'),
        always_urgent boolean NOT NULL DEFAULT false,
        sort_order smallint NOT NULL UNIQUE CHECK (sort_order > 0),
        active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT statement_timestamp()
    );
    CREATE TABLE app.problem_places (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z][A-Z_]{1,40}$'),
        name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 80),
        name_kh text NOT NULL CHECK (name_kh = btrim(name_kh) AND length(name_kh) BETWEEN 1 AND 80),
        sort_order smallint NOT NULL UNIQUE CHECK (sort_order > 0),
        active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT statement_timestamp()
    );

    -- 1 and 2. The reports. What was reported never changes; the state columns change only
    -- through the functions below, and every change is also a row of problem_report_events.
    CREATE TABLE app.problem_reports (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        report_number text NOT NULL UNIQUE CHECK (report_number ~ '^[A-Z]{2,5}[0-9]{6,}$'),
        kind text NOT NULL CHECK (kind IN ('UNIT', 'BUILDING')),
        unit_id uuid REFERENCES app.units (id) ON DELETE RESTRICT,
        lease_id uuid REFERENCES app.leases (id) ON DELETE RESTRICT,
        customer_id uuid REFERENCES app.customers (id) ON DELETE RESTRICT,
        place_item_id uuid REFERENCES app.unit_setup_items (id) ON DELETE RESTRICT,
        place_number smallint CHECK (place_number BETWEEN 1 AND 99),
        problem_place_id uuid REFERENCES app.problem_places (id) ON DELETE RESTRICT,
        floor_label text CHECK (floor_label = btrim(floor_label) AND length(floor_label) BETWEEN 1 AND 20),
        problem_type_id uuid NOT NULL REFERENCES app.problem_types (id) ON DELETE RESTRICT,
        description text NOT NULL CHECK (description = btrim(description)
            AND length(description) BETWEEN 1 AND 1000),
        urgent boolean NOT NULL,
        always_urgent boolean NOT NULL DEFAULT false,
        may_enter boolean NOT NULL DEFAULT false,
        best_time text NOT NULL DEFAULT 'ANY' CHECK (best_time IN ('AM', 'PM', 'ANY')),
        source text NOT NULL CHECK (source IN ('PHONE', 'WALKIN', 'SEEN', 'INSPECTION',
            'TENANT_BOT', 'STAFF_BOT')),
        reported_by text CHECK (reported_by = btrim(reported_by)
            AND length(reported_by) BETWEEN 1 AND 120),
        status text NOT NULL DEFAULT 'RECEIVED' CHECK (status IN ('RECEIVED', 'PLANNED', 'CHECKED',
            'WAITING_TENANT', 'REPAIR_PLANNED', 'WAITING_PARTS', 'DONE', 'CLOSED', 'NOT_ACCEPTED',
            'JOINED')),
        repair_job boolean NOT NULL DEFAULT false,
        contacted_at timestamptz,
        contacted_how text CHECK (contacted_how IN ('PHONE', 'VISIT')),
        technician text CHECK (technician = btrim(technician) AND length(technician) BETWEEN 1 AND 120),
        visit_on date,
        visit_at time,
        cause text CHECK (cause IN ('WEAR', 'DAMAGE', 'UNSURE')),
        cause_note text CHECK (cause_note = btrim(cause_note) AND length(cause_note) BETWEEN 1 AND 500),
        fixed_at_check boolean NOT NULL DEFAULT false,
        pays text CHECK (pays IN ('OWNER', 'TENANT')),
        tenant_amount_usd_cents bigint CHECK (tenant_amount_usd_cents BETWEEN 1 AND 999999999),
        tenant_reason text CHECK (tenant_reason = btrim(tenant_reason)
            AND length(tenant_reason) BETWEEN 1 AND 500),
        decided_on date,
        tenant_answer text CHECK (tenant_answer IN ('AGREED', 'REFUSED')),
        tenant_answer_how text CHECK (tenant_answer_how IN ('SIGNED', 'TELEGRAM', 'PHONE', 'IN_PERSON')),
        tenant_answer_on date,
        tenant_said text CHECK (tenant_said = btrim(tenant_said) AND length(tenant_said) BETWEEN 1 AND 500),
        parts_from text CHECK (parts_from IN ('REPAIR_PLANNED')),
        done_at timestamptz,
        closed_at timestamptz,
        close_note text CHECK (close_note = btrim(close_note) AND length(close_note) BETWEEN 1 AND 500),
        joined_to_id uuid REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        version integer NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT problem_reports_where CHECK (
            (kind = 'UNIT' AND unit_id IS NOT NULL AND problem_place_id IS NULL AND floor_label IS NULL)
            OR (kind = 'BUILDING' AND unit_id IS NULL AND lease_id IS NULL AND customer_id IS NULL
                AND place_item_id IS NULL AND problem_place_id IS NOT NULL)),
        CONSTRAINT problem_reports_place_pair CHECK ((place_item_id IS NULL) = (place_number IS NULL)),
        CONSTRAINT problem_reports_lease_customer CHECK ((lease_id IS NULL) = (customer_id IS NULL)),
        CONSTRAINT problem_reports_always_urgent CHECK (NOT always_urgent OR urgent),
        CONSTRAINT problem_reports_contacted CHECK ((contacted_at IS NULL) = (contacted_how IS NULL)),
        CONSTRAINT problem_reports_visit CHECK ((technician IS NULL) = (visit_on IS NULL)
            AND (visit_on IS NULL) = (visit_at IS NULL)),
        CONSTRAINT problem_reports_tenant_pays CHECK (
            (pays = 'TENANT') = (tenant_amount_usd_cents IS NOT NULL AND tenant_reason IS NOT NULL)
            AND (pays IS NULL) = (decided_on IS NULL)
            AND (pays <> 'TENANT' OR lease_id IS NOT NULL)),
        CONSTRAINT problem_reports_answer CHECK ((tenant_answer IS NULL) = (tenant_answer_how IS NULL)
            AND (tenant_answer IS NULL) = (tenant_answer_on IS NULL)
            AND (tenant_answer IS NULL OR tenant_amount_usd_cents IS NOT NULL)),
        CONSTRAINT problem_reports_joined CHECK ((status = 'JOINED') = (joined_to_id IS NOT NULL)
            AND joined_to_id IS DISTINCT FROM id)
    );
    CREATE INDEX problem_reports_property_idx ON app.problem_reports (property_id, created_at DESC);
    CREATE INDEX problem_reports_unit_idx ON app.problem_reports (unit_id, problem_type_id, created_at)
        WHERE unit_id IS NOT NULL;
    CREATE INDEX problem_reports_joined_idx ON app.problem_reports (joined_to_id)
        WHERE joined_to_id IS NOT NULL;
    CREATE INDEX problem_reports_lease_idx ON app.problem_reports (lease_id) WHERE lease_id IS NOT NULL;
    COMMENT ON TABLE app.problem_reports IS
        'V1.1 part 7 (DL-124): one list of Unit Problems (UP) and Building problems (BP).';

    CREATE TABLE app.problem_report_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        report_id uuid NOT NULL REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        step text NOT NULL CHECK (step ~ '^[A-Z][A-Z_]{1,40}$'),
        note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
        details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
        occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        actor_id uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX problem_report_events_report_idx ON app.problem_report_events (report_id, occurred_at);

    CREATE TABLE app.problem_report_joins (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        report_id uuid NOT NULL REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        main_id uuid NOT NULL REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        previous_status text NOT NULL,
        joined_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        joined_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT problem_report_joins_not_self CHECK (report_id <> main_id)
    );
    CREATE INDEX problem_report_joins_report_idx ON app.problem_report_joins (report_id, joined_at);
    CREATE INDEX problem_report_joins_main_idx ON app.problem_report_joins (main_id);
    CREATE TABLE app.problem_report_join_endings (
        join_id uuid PRIMARY KEY REFERENCES app.problem_report_joins (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
        ended_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        ended_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );

    -- History is never changed or emptied; a report keeps what was reported.
    CREATE FUNCTION app.reject_problem_report_change() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        RAISE EXCEPTION 'Problem report history is never changed' USING ERRCODE = '55000';
    END $$;
    REVOKE ALL ON FUNCTION app.reject_problem_report_change() FROM PUBLIC;
    CREATE TRIGGER problem_report_events_append_only BEFORE UPDATE OR DELETE ON app.problem_report_events
        FOR EACH ROW EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_joins_append_only BEFORE UPDATE OR DELETE ON app.problem_report_joins
        FOR EACH ROW EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_join_endings_append_only BEFORE UPDATE OR DELETE
        ON app.problem_report_join_endings
        FOR EACH ROW EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_reports_no_truncate BEFORE TRUNCATE ON app.problem_reports
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_events_no_truncate BEFORE TRUNCATE ON app.problem_report_events
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_joins_no_truncate BEFORE TRUNCATE ON app.problem_report_joins
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();
    CREATE TRIGGER problem_report_join_endings_no_truncate BEFORE TRUNCATE
        ON app.problem_report_join_endings
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_problem_report_change();

    CREATE FUNCTION app.protect_problem_report() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF TG_OP <> 'UPDATE'
            OR NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
            OR NEW.report_number <> OLD.report_number OR NEW.kind <> OLD.kind
            OR NEW.unit_id IS DISTINCT FROM OLD.unit_id OR NEW.lease_id IS DISTINCT FROM OLD.lease_id
            OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
            OR NEW.place_item_id IS DISTINCT FROM OLD.place_item_id
            OR NEW.place_number IS DISTINCT FROM OLD.place_number
            OR NEW.problem_place_id IS DISTINCT FROM OLD.problem_place_id
            OR NEW.floor_label IS DISTINCT FROM OLD.floor_label
            OR NEW.problem_type_id <> OLD.problem_type_id OR NEW.description <> OLD.description
            OR NEW.urgent <> OLD.urgent OR NEW.always_urgent <> OLD.always_urgent
            OR NEW.may_enter <> OLD.may_enter OR NEW.best_time <> OLD.best_time
            OR NEW.source <> OLD.source OR NEW.reported_by IS DISTINCT FROM OLD.reported_by
            OR NEW.created_at <> OLD.created_at OR NEW.created_by <> OLD.created_by
            OR NEW.version <> OLD.version + 1
        THEN
            RAISE EXCEPTION 'What was reported is never changed' USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION app.protect_problem_report() FROM PUBLIC;
    CREATE TRIGGER problem_reports_protect BEFORE UPDATE OR DELETE ON app.problem_reports
        FOR EACH ROW EXECUTE FUNCTION app.protect_problem_report();

    -- 3. A Damage charge comes from a move-out inspection finding or from one Problem report.
    ALTER TABLE app.authorized_nonrecurring_obligations
        ADD COLUMN problem_report_id uuid UNIQUE REFERENCES app.problem_reports (id) ON DELETE RESTRICT;
    ALTER TABLE app.authorized_nonrecurring_obligations
        DROP CONSTRAINT authorized_nonrecurring_source_shape;
    ALTER TABLE app.authorized_nonrecurring_obligations
        ADD CONSTRAINT authorized_nonrecurring_source_shape CHECK (
            (category = 'DAMAGE_CHARGES'
                AND (inspection_damage_finding_id IS NOT NULL) <> (problem_report_id IS NOT NULL))
            OR (category = 'MISCELLANEOUS_CHARGES' AND inspection_damage_finding_id IS NULL
                AND problem_report_id IS NULL));

    CREATE OR REPLACE FUNCTION app.validate_damage_obligation_source() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF NEW.category = 'DAMAGE_CHARGES' AND NEW.problem_report_id IS NOT NULL THEN
            -- V1.1 part 7 (DL-124): exactly the amount the Manager set, for the report's Lease
            -- and its Primary Tenant, after the tenant agreed.
            IF NOT EXISTS (
                SELECT 1 FROM app.problem_reports AS report
                JOIN app.leases AS lease ON lease.id = report.lease_id
                WHERE report.id = NEW.problem_report_id AND report.lease_id = NEW.lease_id
                  AND lease.primary_tenant_id = NEW.customer_id AND report.pays = 'TENANT'
                  AND report.tenant_amount_usd_cents = NEW.authorized_amount_usd_cents
            ) THEN
                RAISE EXCEPTION 'Damage charge must match the Problem report the tenant agreed to'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.category='DAMAGE_CHARGES' AND NOT EXISTS (
            SELECT 1 FROM app.inspection_damage_findings AS finding
            JOIN app.move_out_inspections AS inspection ON inspection.id=finding.inspection_id
            JOIN app.leases AS lease ON lease.id=inspection.lease_id
            WHERE finding.id=NEW.inspection_damage_finding_id
              AND inspection.lease_id=NEW.lease_id
              AND lease.primary_tenant_id=NEW.customer_id
              AND NOT EXISTS (SELECT 1 FROM app.move_out_inspections AS later
                  WHERE later.supersedes_inspection_id=inspection.id)
        ) THEN RAISE EXCEPTION 'Damage charge must match a current inspection finding'
            USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$;

    -- Numbers and rules.
    INSERT INTO app.number_rules (document_type, year, last_number, format)
    SELECT kind.document_type, years.year, 0, kind.format
    FROM (VALUES ('UNIT_PROBLEM', 'UPyy000n'), ('BUILDING_PROBLEM', 'BPyy000n'))
        AS kind (document_type, format)
    CROSS JOIN (SELECT DISTINCT date_part('year', timezone(property.timezone_name,
              statement_timestamp()))::smallint AS year
          FROM app.properties AS property
          UNION SELECT date_part('year', statement_timestamp())::smallint) AS years
    ON CONFLICT (document_type, year) DO NOTHING;
    ALTER TABLE app.business_rule_names DROP CONSTRAINT business_rule_names_area;
    ALTER TABLE app.business_rule_names ADD CONSTRAINT business_rule_names_area CHECK (area IN
        ('BILLING', 'RESERVATIONS', 'PRICES', 'QUOTATIONS', 'RIEL_RATE', 'LEDGER', 'STAFF',
         'ATTENDANCE', 'REPAIRS', 'OTHER'));

    -- Sunday is not a working day (mock-up round 29).
    CREATE FUNCTION app.add_working_days(p_day date, p_days integer) RETURNS date
    LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
    DECLARE v_day date := p_day; v_left integer := greatest(p_days, 0);
    BEGIN
        WHILE v_left > 0 LOOP
            v_day := v_day + 1;
            IF extract(dow FROM v_day) <> 0 THEN
                v_left := v_left - 1;
            END IF;
        END LOOP;
        RETURN v_day;
    END $$;
"""

FUNCTIONS = """
    -- A Done report a tenant can answer closes by itself after the auto close days.
    CREATE FUNCTION app.problem_report_state(p_report uuid) RETURNS text
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN report.status = 'DONE' AND report.customer_id IS NOT NULL
                AND report.source IN ('PHONE', 'WALKIN', 'TENANT_BOT')
                AND report.done_at + make_interval(days => COALESCE(app.business_rule_value(
                    'TR_AUTO_CLOSE_DAYS', timezone(property.timezone_name, statement_timestamp())::date),
                    3)::integer) < statement_timestamp()
            THEN 'CLOSED' ELSE report.status END
        FROM app.problem_reports AS report
        JOIN app.properties AS property ON property.id = report.property_id
        WHERE report.id = p_report
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_state(uuid) FROM PUBLIC;

    CREATE FUNCTION app.problem_report_json(p_report uuid, p_full boolean) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        WITH base AS (
            SELECT report.*, property.timezone_name,
                timezone(property.timezone_name, statement_timestamp())::date AS today,
                app.problem_report_state(report.id) AS state
            FROM app.problem_reports AS report
            JOIN app.properties AS property ON property.id = report.property_id
            WHERE report.id = p_report
        ), repeats AS (
            SELECT jsonb_agg(jsonb_build_object('report_id', other.id,
                    'report_number', other.report_number, 'created_at', other.created_at)
                ORDER BY other.created_at) AS found, count(*) AS how_many
            FROM base
            JOIN app.problem_reports AS other ON other.unit_id = base.unit_id
                AND other.problem_type_id = base.problem_type_id AND other.status <> 'JOINED'
                AND other.created_at <= base.created_at
                AND other.created_at >= base.created_at - make_interval(days => COALESCE(
                    app.business_rule_value('REPEAT_DAYS', base.today), 90)::integer)
            WHERE base.kind = 'UNIT'
        )
        SELECT jsonb_build_object(
            'report_id', base.id,
            'report_number', base.report_number,
            'kind', base.kind,
            'status', base.status,
            'state', base.state,
            'late', CASE
                WHEN base.state IN ('DONE', 'CLOSED', 'NOT_ACCEPTED', 'JOINED') THEN NULL
                WHEN base.urgent AND base.contacted_at IS NULL
                    AND statement_timestamp() > base.created_at + make_interval(hours => COALESCE(
                        app.business_rule_value('TR_URGENT_HOURS', base.today), 1)::integer)
                    THEN 'URGENT'
                WHEN NOT base.urgent AND base.status = 'RECEIVED'
                    AND timezone(base.timezone_name, statement_timestamp())
                        > app.add_working_days(timezone(base.timezone_name, base.created_at)::date,
                            COALESCE(app.business_rule_value('TR_PLAN_WORKDAYS', base.today), 1)::integer)
                          + timezone(base.timezone_name, base.created_at)::time
                    THEN 'NORMAL'
                END,
            'repeat', CASE WHEN repeats.how_many >= COALESCE(
                    app.business_rule_value('REPEAT_COUNT', base.today), 3) THEN repeats.found END,
            'unit_id', base.unit_id,
            'unit_number', unit.unit_number,
            'lease_id', base.lease_id,
            'customer_id', base.customer_id,
            'customer_name', customer.legal_name,
            'customer_phone', customer.phone_number,
            'place', CASE WHEN base.place_item_id IS NULL THEN NULL ELSE jsonb_build_object(
                'item_id', base.place_item_id, 'number', base.place_number,
                'name_en', item.name_en, 'name_kh', item.name_km) END,
            'problem_place', CASE WHEN base.problem_place_id IS NULL THEN NULL ELSE jsonb_build_object(
                'id', shared.id, 'code', shared.code, 'name_en', shared.name_en,
                'name_kh', shared.name_kh) END,
            'floor', base.floor_label,
            'problem_type', jsonb_build_object('id', kind.id, 'code', kind.code,
                'name_en', kind.name_en, 'name_kh', kind.name_kh, 'icon', kind.icon,
                'always_urgent', kind.always_urgent),
            'description', base.description,
            'urgent', base.urgent,
            'always_urgent', base.always_urgent,
            'may_enter', base.may_enter,
            'best_time', base.best_time,
            'source', base.source,
            'reported_by', base.reported_by,
            'repair_job', base.repair_job,
            'contacted_at', base.contacted_at,
            'contacted_how', base.contacted_how,
            'technician', base.technician,
            'visit_on', base.visit_on,
            'visit_at', to_char(base.visit_at, 'HH24:MI'),
            'cause', base.cause,
            'cause_note', base.cause_note,
            'fixed_at_check', base.fixed_at_check,
            'pays', base.pays,
            'tenant_amount_usd_cents', base.tenant_amount_usd_cents,
            'tenant_reason', base.tenant_reason,
            'decided_on', base.decided_on,
            'tenant_answer', base.tenant_answer,
            'tenant_answer_how', base.tenant_answer_how,
            'tenant_answer_on', base.tenant_answer_on,
            'tenant_said', base.tenant_said) || jsonb_build_object(
            'tenant_can_answer', base.customer_id IS NOT NULL
                AND base.source IN ('PHONE', 'WALKIN', 'TENANT_BOT'),
            'damage', (
                SELECT jsonb_build_object('charge_id', charge.id, 'invoice_id', invoice.id,
                    'invoice_number', invoice.invoice_number, 'invoice_status', invoice.status,
                    'amount_usd_cents', charge.authorized_amount_usd_cents)
                FROM app.authorized_nonrecurring_obligations AS charge
                LEFT JOIN app.invoice_lines AS line ON line.authorized_obligation_id = charge.id
                LEFT JOIN app.invoices AS invoice ON invoice.id = line.invoice_id
                WHERE charge.problem_report_id = base.id
                ORDER BY invoice.created_at DESC NULLS LAST LIMIT 1),
            'done_at', base.done_at,
            'closes_on', CASE WHEN base.status = 'DONE' AND base.customer_id IS NOT NULL
                AND base.source IN ('PHONE', 'WALKIN', 'TENANT_BOT')
                THEN (timezone(base.timezone_name, base.done_at) + make_interval(days => COALESCE(
                    app.business_rule_value('TR_AUTO_CLOSE_DAYS', base.today), 3)::integer))::date END,
            'closed_at', base.closed_at,
            'close_note', base.close_note,
            'joined_to', CASE WHEN base.joined_to_id IS NULL THEN NULL ELSE jsonb_build_object(
                'report_id', main.id, 'report_number', main.report_number, 'status', main.status,
                'state', app.problem_report_state(main.id)) END,
            'join', (
                SELECT jsonb_build_object('reason', joined.reason, 'joined_at', joined.joined_at,
                    'joined_by_name', joiner.display_name, 'previous_status', joined.previous_status)
                FROM app.problem_report_joins AS joined
                LEFT JOIN app.user_accounts AS joiner ON joiner.actor_id = joined.joined_by
                WHERE joined.report_id = base.id AND base.status = 'JOINED'
                  AND NOT EXISTS (SELECT 1 FROM app.problem_report_join_endings AS ended
                                  WHERE ended.join_id = joined.id)
                ORDER BY joined.joined_at DESC LIMIT 1),
            'joined', COALESCE((
                SELECT jsonb_agg(jsonb_build_object('report_id', kid.id,
                        'report_number', kid.report_number, 'source', kid.source,
                        'description', kid.description, 'reported_by', kid.reported_by,
                        'created_at', kid.created_at) ORDER BY kid.created_at)
                FROM app.problem_reports AS kid WHERE kid.joined_to_id = base.id), '[]'::jsonb),
            'created_at', base.created_at,
            'created_by_name', maker.display_name,
            'version', base.version,
            'history', CASE WHEN p_full THEN COALESCE((
                SELECT jsonb_agg(jsonb_build_object('step', event.step, 'note', event.note,
                        'details', event.details, 'at', event.occurred_at,
                        'by_name', actor.display_name) ORDER BY event.occurred_at, event.id)
                FROM app.problem_report_events AS event
                LEFT JOIN app.user_accounts AS actor ON actor.actor_id = event.actor_id
                WHERE event.report_id = base.id), '[]'::jsonb) END
        )
        FROM base
        CROSS JOIN repeats
        JOIN app.problem_types AS kind ON kind.id = base.problem_type_id
        LEFT JOIN app.units AS unit ON unit.id = base.unit_id
        LEFT JOIN app.customers AS customer ON customer.id = base.customer_id
        LEFT JOIN app.unit_setup_items AS item ON item.id = base.place_item_id
        LEFT JOIN app.problem_places AS shared ON shared.id = base.problem_place_id
        LEFT JOIN app.problem_reports AS main ON main.id = base.joined_to_id
        LEFT JOIN app.user_accounts AS maker ON maker.actor_id = base.created_by
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_json(uuid, boolean) FROM PUBLIC;

    CREATE FUNCTION app.problem_reports_read(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_product_right(p_actor, 'problem_reports.read', p_property);
        RETURN COALESCE((
            SELECT jsonb_agg(app.problem_report_json(recent.id, false)
                ORDER BY recent.created_at DESC, recent.report_number DESC)
            FROM (SELECT report.id, report.created_at, report.report_number
                  FROM app.problem_reports AS report
                  WHERE report.property_id = p_property
                  ORDER BY report.created_at DESC, report.report_number DESC
                  LIMIT 500) AS recent), '[]'::jsonb);
    END $$;

    CREATE FUNCTION app.problem_report_read(p_property uuid, p_report uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_product_right(p_actor, 'problem_reports.read', p_property);
        IF NOT EXISTS (SELECT 1 FROM app.problem_reports AS report
                       WHERE report.id = p_report AND report.property_id = p_property) THEN
            RAISE EXCEPTION 'the Problem report does not exist' USING ERRCODE = '22023';
        END IF;
        RETURN app.problem_report_json(p_report, true);
    END $$;

    -- What the forms choose from: types, shared places, Units with their places and tenant,
    -- and the rules the list shows.
    CREATE FUNCTION app.problem_report_choices(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_day date := app.require_product_right(p_actor, 'problem_reports.read', p_property);
    BEGIN
        RETURN jsonb_build_object(
            'types', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', kind.id, 'code', kind.code,
                    'name_en', kind.name_en, 'name_kh', kind.name_kh, 'icon', kind.icon,
                    'always_urgent', kind.always_urgent) ORDER BY kind.sort_order)
                FROM app.problem_types AS kind WHERE kind.active), '[]'::jsonb),
            'places', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', place.id,
                    'code', place.code, 'name_en', place.name_en, 'name_kh', place.name_kh)
                    ORDER BY place.sort_order)
                FROM app.problem_places AS place WHERE place.active), '[]'::jsonb),
            'units', COALESCE((SELECT jsonb_agg(jsonb_build_object('unit_id', unit.id,
                    'unit_number', unit.unit_number, 'floor', unit.floor,
                    'customer_name', (SELECT customer.legal_name
                        FROM app.problem_unit_lease(unit.id, v_day) AS current
                        JOIN app.customers AS customer ON customer.id = current.customer_id),
                    'places', COALESCE((SELECT jsonb_agg(jsonb_build_object('item_id', item.id,
                            'number', number, 'name_en', item.name_en, 'name_kh', item.name_km,
                            'count', feature.feature_count)
                            ORDER BY item.sort_order, item.name_en, number)
                        FROM app.unit_features AS feature
                        JOIN app.unit_setup_items AS item ON item.id = feature.item_id
                        CROSS JOIN generate_series(1, feature.feature_count) AS number
                        WHERE feature.unit_id = unit.id), '[]'::jsonb))
                    ORDER BY unit.unit_number)
                FROM app.units AS unit WHERE unit.property_id = p_property), '[]'::jsonb),
            'rules', jsonb_build_object(
                'repeat_count', COALESCE(app.business_rule_value('REPEAT_COUNT', v_day), 3),
                'repeat_days', COALESCE(app.business_rule_value('REPEAT_DAYS', v_day), 90),
                'urgent_hours', COALESCE(app.business_rule_value('TR_URGENT_HOURS', v_day), 1),
                'plan_workdays', COALESCE(app.business_rule_value('TR_PLAN_WORKDAYS', v_day), 1),
                'auto_close_days', COALESCE(app.business_rule_value('TR_AUTO_CLOSE_DAYS', v_day), 3)),
            'today', v_day);
    END $$;

    -- The signed Lease of a Unit on a day: the one running, else the next one to start.
    CREATE FUNCTION app.problem_unit_lease(p_unit uuid, p_day date)
    RETURNS TABLE (lease_id uuid, customer_id uuid)
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT lease.id, lease.primary_tenant_id
        FROM app.leases AS lease
        WHERE lease.unit_id = p_unit AND lease.status = 'SIGNED' AND lease.end_date >= p_day
        ORDER BY (lease.start_date <= p_day) DESC, lease.start_date
        LIMIT 1
    $$;
    REVOKE ALL ON FUNCTION app.problem_unit_lease(uuid, date) FROM PUBLIC;

    CREATE FUNCTION app.problem_report_event(p_report uuid, p_step text, p_note text,
        p_details jsonb, p_actor uuid) RETURNS void
    LANGUAGE sql SET search_path = pg_catalog AS $$
        INSERT INTO app.problem_report_events (report_id, step, note, details, actor_id)
        VALUES (p_report, p_step, NULLIF(btrim(p_note), ''), COALESCE(p_details, '{}'::jsonb), p_actor)
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_event(uuid, text, text, jsonb, uuid) FROM PUBLIC;

    -- A short text from a form: trimmed, empty is none, and never longer than allowed.
    CREATE FUNCTION app.problem_text(p_value jsonb, p_key text, p_most integer, p_message text)
    RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
    DECLARE v_text text;
    BEGIN
        IF p_value -> p_key IS NULL OR jsonb_typeof(p_value -> p_key) = 'null' THEN
            RETURN NULL;
        END IF;
        IF jsonb_typeof(p_value -> p_key) <> 'string' THEN
            RAISE EXCEPTION '%', p_message USING ERRCODE = '22023';
        END IF;
        v_text := NULLIF(btrim(p_value ->> p_key), '');
        IF v_text IS NOT NULL AND length(v_text) > p_most THEN
            RAISE EXCEPTION '%', p_message USING ERRCODE = '22023';
        END IF;
        RETURN v_text;
    END $$;
    REVOKE ALL ON FUNCTION app.problem_text(jsonb, text, integer, text) FROM PUBLIC;

    -- Join one report (and the reports already joined to it) to its main report.
    CREATE FUNCTION app.problem_report_join_to(p_report uuid, p_main uuid, p_reason text,
        p_actor uuid) RETURNS void
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE
        v_report app.problem_reports%ROWTYPE;
        v_main app.problem_reports%ROWTYPE;
        v_kid record;
    BEGIN
        SELECT report.* INTO v_report FROM app.problem_reports AS report WHERE report.id = p_report;
        SELECT report.* INTO v_main FROM app.problem_reports AS report
        WHERE report.id = p_main AND report.property_id = v_report.property_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the main report does not exist' USING ERRCODE = '22023';
        END IF;
        IF v_main.id = v_report.id OR v_main.kind <> v_report.kind
            OR (v_report.kind = 'UNIT' AND v_main.unit_id <> v_report.unit_id) THEN
            RAISE EXCEPTION 'A report joins an open report of the same kind and place'
                USING ERRCODE = '22023';
        END IF;
        IF app.problem_report_state(v_main.id) IN ('DONE', 'CLOSED', 'NOT_ACCEPTED', 'JOINED')
            OR app.problem_report_state(v_report.id) IN ('DONE', 'CLOSED', 'NOT_ACCEPTED', 'JOINED') THEN
            RAISE EXCEPTION 'Only open reports are joined' USING ERRCODE = '55000';
        END IF;
        INSERT INTO app.problem_report_joins (report_id, main_id, reason, previous_status, joined_by)
        VALUES (v_report.id, v_main.id, p_reason, v_report.status, p_actor);
        UPDATE app.problem_reports AS report
        SET status = 'JOINED', joined_to_id = v_main.id, version = report.version + 1
        WHERE report.id = v_report.id;
        PERFORM app.problem_report_event(v_report.id, 'JOINED', p_reason,
            jsonb_build_object('main_number', v_main.report_number), p_actor);
        PERFORM app.problem_report_event(v_main.id, 'JOINED_IN', NULL,
            jsonb_build_object('report_number', v_report.report_number), p_actor);
        -- Reports joined to this one now follow the main report too.
        FOR v_kid IN SELECT kid.id, kid.report_number FROM app.problem_reports AS kid
                     WHERE kid.joined_to_id = v_report.id ORDER BY kid.created_at FOR UPDATE LOOP
            UPDATE app.problem_reports AS report
            SET joined_to_id = v_main.id, version = report.version + 1 WHERE report.id = v_kid.id;
            INSERT INTO app.problem_report_joins (report_id, main_id, reason, previous_status, joined_by)
            VALUES (v_kid.id, v_main.id, p_reason, 'RECEIVED', p_actor);
            PERFORM app.problem_report_event(v_kid.id, 'MOVED', NULL,
                jsonb_build_object('main_number', v_main.report_number), p_actor);
            PERFORM app.problem_report_event(v_main.id, 'JOINED_IN', NULL,
                jsonb_build_object('report_number', v_kid.report_number), p_actor);
        END LOOP;
    END $$;
    REVOKE ALL ON FUNCTION app.problem_report_join_to(uuid, uuid, text, uuid) FROM PUBLIC;

    -- 1. A new report from the app (phone, walk-in or seen by staff).
    CREATE FUNCTION app.add_problem_report(p_property uuid, p_report jsonb, p_actor uuid,
        p_correlation uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'problem_reports.add', p_property);
        v_id uuid := gen_random_uuid();
        v_kind text := p_report ->> 'kind';
        v_type app.problem_types%ROWTYPE;
        v_unit uuid;
        v_lease uuid;
        v_customer uuid;
        v_item uuid;
        v_number integer;
        v_place uuid;
        v_floor text;
        v_text text;
        v_by text;
        v_source text := p_report ->> 'source';
        v_best text := COALESCE(p_report ->> 'best_time', 'ANY');
        v_urgent boolean;
        v_enter boolean;
        v_same uuid;
        v_report_number text;
    BEGIN
        IF p_report IS NULL OR jsonb_typeof(p_report) <> 'object' OR v_kind IS NULL
            OR v_kind NOT IN ('UNIT', 'BUILDING') THEN
            RAISE EXCEPTION 'Choose Unit Problem or Building problem' USING ERRCODE = '22023';
        END IF;
        IF v_source IS NULL OR v_source NOT IN ('PHONE', 'WALKIN', 'SEEN') THEN
            RAISE EXCEPTION 'Choose how the problem came in' USING ERRCODE = '22023';
        END IF;
        IF v_best NOT IN ('AM', 'PM', 'ANY') THEN
            RAISE EXCEPTION 'Choose the best time' USING ERRCODE = '22023';
        END IF;
        IF jsonb_typeof(p_report -> 'urgent') <> 'boolean' THEN
            RAISE EXCEPTION 'Choose if it is urgent' USING ERRCODE = '22023';
        END IF;
        v_urgent := (p_report ->> 'urgent')::boolean;
        v_enter := COALESCE((p_report ->> 'may_enter')::boolean, false);
        BEGIN
            SELECT kind.* INTO v_type FROM app.problem_types AS kind
            WHERE kind.id = (p_report ->> 'problem_type_id')::uuid AND kind.active;
            v_same := (p_report ->> 'same_as')::uuid;
            v_unit := (p_report ->> 'unit_id')::uuid;
            v_item := (p_report ->> 'place_item_id')::uuid;
            v_number := (p_report ->> 'place_number')::integer;
            v_place := (p_report ->> 'problem_place_id')::uuid;
        EXCEPTION WHEN data_exception THEN
            RAISE EXCEPTION 'The Problem report is invalid' USING ERRCODE = '22023';
        END;
        IF v_type.id IS NULL THEN
            RAISE EXCEPTION 'Choose the problem type' USING ERRCODE = '22023';
        END IF;
        v_text := app.problem_text(p_report, 'description', 1000, 'Say what is wrong, at most 1000 letters');
        IF v_text IS NULL THEN
            RAISE EXCEPTION 'Say what is wrong, at most 1000 letters' USING ERRCODE = '22023';
        END IF;
        v_by := app.problem_text(p_report, 'reported_by', 120, 'Who reported it is at most 120 letters');
        IF v_kind = 'UNIT' THEN
            IF v_unit IS NULL OR NOT EXISTS (SELECT 1 FROM app.units AS unit
                    WHERE unit.id = v_unit AND unit.property_id = p_property) THEN
                RAISE EXCEPTION 'the Unit does not exist' USING ERRCODE = '22023';
            END IF;
            IF (v_item IS NULL) <> (v_number IS NULL) THEN
                RAISE EXCEPTION 'This place is not in the Unit' USING ERRCODE = '22023';
            END IF;
            IF v_item IS NOT NULL THEN
                PERFORM app.assert_place(p_property, v_unit, v_item, v_number);
            END IF;
            IF v_place IS NOT NULL OR p_report ? 'floor' AND jsonb_typeof(p_report -> 'floor') <> 'null' THEN
                RAISE EXCEPTION 'A Unit Problem has no shared place or floor' USING ERRCODE = '22023';
            END IF;
            SELECT current.lease_id, current.customer_id INTO v_lease, v_customer
            FROM app.problem_unit_lease(v_unit, v_day) AS current;
        ELSE
            IF v_unit IS NOT NULL OR v_item IS NOT NULL THEN
                RAISE EXCEPTION 'A Building problem is in a shared place, not in a Unit'
                    USING ERRCODE = '22023';
            END IF;
            IF v_place IS NULL OR NOT EXISTS (SELECT 1 FROM app.problem_places AS place
                    WHERE place.id = v_place AND place.active) THEN
                RAISE EXCEPTION 'Choose where in the building' USING ERRCODE = '22023';
            END IF;
            v_floor := app.problem_text(p_report, 'floor', 20, 'The floor is at most 20 letters');
            v_enter := false;
            v_best := 'ANY';
        END IF;
        v_report_number := app.take_document_number(
            CASE v_kind WHEN 'UNIT' THEN 'UNIT_PROBLEM' ELSE 'BUILDING_PROBLEM' END,
            date_part('year', v_day)::integer);
        INSERT INTO app.problem_reports (id, property_id, report_number, kind, unit_id, lease_id,
            customer_id, place_item_id, place_number, problem_place_id, floor_label,
            problem_type_id, description, urgent, always_urgent, may_enter, best_time, source,
            reported_by, created_by)
        VALUES (v_id, p_property, v_report_number, v_kind, v_unit, v_lease, v_customer, v_item,
            v_number, v_place, v_floor, v_type.id, v_text, v_urgent OR v_type.always_urgent,
            v_type.always_urgent, v_enter, v_best, v_source, v_by, p_actor);
        PERFORM app.problem_report_event(v_id, 'RECEIVED', NULL,
            jsonb_build_object('source', v_source), p_actor);
        -- "Same problem" when reporting: saved with its own number and joined at once.
        IF v_same IS NOT NULL THEN
            PERFORM 1 FROM app.problem_reports AS report WHERE report.id = v_id FOR UPDATE;
            PERFORM app.problem_report_join_to(v_id, v_same, 'Same problem (picked when reporting)', p_actor);
        END IF;
        PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.added', 'problem_report',
            v_id, 'Problem report added', 'problem_reports.add', NULL,
            jsonb_build_object('report_number', v_report_number, 'kind', v_kind,
                'same_as', v_same), p_correlation);
        RETURN v_id;
    END $$;

    -- 2. One step of a report, at the version that was read.
    CREATE FUNCTION app.problem_report_step(p_property uuid, p_report uuid,
        p_expected_version integer, p_step text, p_input jsonb, p_actor uuid, p_correlation uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'problem_reports.read', p_property);
        v_report app.problem_reports%ROWTYPE;
        v_state text;
        v_input jsonb := COALESCE(p_input, '{}'::jsonb);
        v_note text;
        v_name text;
        v_on date;
        v_at time;
        v_amount numeric;
        v_main uuid;
        v_join app.problem_report_joins%ROWTYPE;
        v_now timestamptz := statement_timestamp();
        v_local timestamp;
    BEGIN
        IF jsonb_typeof(v_input) <> 'object' THEN
            RAISE EXCEPTION 'The step is invalid' USING ERRCODE = '22023';
        END IF;
        PERFORM app.require_product_right(p_actor,
            CASE WHEN p_step IN ('JOIN', 'UNJOIN') THEN 'problem_reports.join'
                 ELSE 'problem_reports.plan' END, p_property);
        SELECT report.* INTO v_report FROM app.problem_reports AS report
        WHERE report.id = p_report AND report.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Problem report does not exist' USING ERRCODE = '22023';
        END IF;
        IF p_expected_version IS DISTINCT FROM v_report.version THEN
            RAISE EXCEPTION 'the Problem report changed since it was read' USING ERRCODE = '40001';
        END IF;
        v_state := app.problem_report_state(p_report);
        SELECT timezone(property.timezone_name, v_now) INTO v_local
        FROM app.properties AS property WHERE property.id = p_property;
        v_note := app.problem_text(v_input, 'note', 500, 'The note is at most 500 letters');
        IF p_step = 'CONTACTED' THEN
            IF v_state <> 'RECEIVED' OR NOT v_report.urgent OR v_report.contacted_at IS NOT NULL THEN
                RAISE EXCEPTION 'Only a new urgent report is marked contacted' USING ERRCODE = '55000';
            END IF;
            IF COALESCE(v_input ->> 'how', '') NOT IN ('PHONE', 'VISIT') THEN
                RAISE EXCEPTION 'Choose phone or visit' USING ERRCODE = '22023';
            END IF;
            UPDATE app.problem_reports SET contacted_at = v_now, contacted_how = v_input ->> 'how',
                version = version + 1 WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'CONTACTED', v_note,
                jsonb_build_object('how', v_input ->> 'how'), p_actor);
        ELSIF p_step = 'PLAN' THEN
            IF v_state NOT IN ('RECEIVED', 'PLANNED')
                OR (v_report.kind = 'BUILDING' AND NOT v_report.repair_job) THEN
                RAISE EXCEPTION 'Only a new or planned repair is planned' USING ERRCODE = '55000';
            END IF;
            v_name := app.problem_text(v_input, 'technician', 120, 'Type the technician''s name');
            BEGIN
                v_on := (v_input ->> 'visit_on')::date;
                v_at := (v_input ->> 'visit_at')::time;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'Choose the day and the time' USING ERRCODE = '22023';
            END;
            IF v_name IS NULL THEN
                RAISE EXCEPTION 'Type the technician''s name' USING ERRCODE = '22023';
            END IF;
            IF v_on IS NULL OR v_at IS NULL OR v_on < v_day OR v_on > v_day + 60
                OR v_at < time '07:00' OR v_at > time '16:30'
                OR extract(minute FROM v_at) NOT IN (0, 30) OR extract(second FROM v_at) <> 0
                OR (v_on = v_day AND v_at <= v_local::time) THEN
                RAISE EXCEPTION 'Choose a day from today and a time from 07:00 to 16:30, every 30 minutes'
                    USING ERRCODE = '22023';
            END IF;
            UPDATE app.problem_reports SET status = 'PLANNED', technician = v_name, visit_on = v_on,
                visit_at = v_at, version = version + 1 WHERE id = p_report;
            PERFORM app.problem_report_event(p_report,
                CASE WHEN v_state = 'PLANNED' THEN 'REPLANNED' ELSE 'PLANNED' END, v_note,
                jsonb_build_object('technician', v_name, 'visit_on', v_on,
                    'visit_at', to_char(v_at, 'HH24:MI')), p_actor);
        ELSIF p_step = 'NOT_A_REPAIR' THEN
            IF v_state <> 'RECEIVED' OR v_report.kind <> 'UNIT' THEN
                RAISE EXCEPTION 'Only a new Unit Problem is marked not a repair' USING ERRCODE = '55000';
            END IF;
            IF v_note IS NULL THEN
                RAISE EXCEPTION 'Say why it is not a repair' USING ERRCODE = '22023';
            END IF;
            UPDATE app.problem_reports SET status = 'NOT_ACCEPTED', closed_at = v_now,
                close_note = v_note, version = version + 1 WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'NOT_ACCEPTED', v_note, NULL, p_actor);
        ELSIF p_step IN ('MAKE_JOB', 'CLEANING', 'CLOSE_NOTE') THEN
            IF v_state <> 'RECEIVED' OR v_report.kind <> 'BUILDING' OR v_report.repair_job THEN
                RAISE EXCEPTION 'Only a new Building problem is sent on' USING ERRCODE = '55000';
            END IF;
            IF p_step = 'MAKE_JOB' THEN
                UPDATE app.problem_reports SET repair_job = true, version = version + 1
                WHERE id = p_report;
                PERFORM app.problem_report_event(p_report, 'REPAIR_JOB', v_note, NULL, p_actor);
            ELSIF p_step = 'CLEANING' THEN
                v_name := app.problem_text(v_input, 'cleaner', 120, 'Type the cleaner''s name');
                IF v_name IS NULL THEN
                    RAISE EXCEPTION 'Type the cleaner''s name' USING ERRCODE = '22023';
                END IF;
                UPDATE app.problem_reports SET status = 'DONE', done_at = v_now,
                    version = version + 1 WHERE id = p_report;
                PERFORM app.problem_report_event(p_report, 'CLEANING', v_note,
                    jsonb_build_object('cleaner', v_name), p_actor);
            ELSE
                IF v_note IS NULL THEN
                    RAISE EXCEPTION 'Write a note to close it' USING ERRCODE = '22023';
                END IF;
                UPDATE app.problem_reports SET status = 'CLOSED', closed_at = v_now,
                    close_note = v_note, version = version + 1 WHERE id = p_report;
                PERFORM app.problem_report_event(p_report, 'CLOSED_NOTE', v_note, NULL, p_actor);
            END IF;
        ELSIF p_step = 'CHECKED' THEN
            IF v_state <> 'PLANNED' THEN
                RAISE EXCEPTION 'Only a planned visit is checked' USING ERRCODE = '55000';
            END IF;
            IF COALESCE(v_input ->> 'cause', '') NOT IN ('WEAR', 'DAMAGE', 'UNSURE') THEN
                RAISE EXCEPTION 'Choose what caused it' USING ERRCODE = '22023';
            END IF;
            IF COALESCE((v_input ->> 'fixed')::boolean, false) AND NOT v_report.urgent THEN
                RAISE EXCEPTION 'Only an urgent repair is fixed at the check' USING ERRCODE = '22023';
            END IF;
            UPDATE app.problem_reports SET status = 'CHECKED', cause = v_input ->> 'cause',
                cause_note = v_note, fixed_at_check = COALESCE((v_input ->> 'fixed')::boolean, false),
                version = version + 1 WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'CHECKED', v_note,
                jsonb_build_object('cause', v_input ->> 'cause',
                    'fixed', COALESCE((v_input ->> 'fixed')::boolean, false)), p_actor);
        ELSIF p_step = 'DECIDE' THEN
            IF v_state <> 'CHECKED' THEN
                RAISE EXCEPTION 'Who pays is decided after the check' USING ERRCODE = '55000';
            END IF;
            IF COALESCE(v_input ->> 'pays', '') = 'OWNER' THEN
                UPDATE app.problem_reports SET pays = 'OWNER', decided_on = v_day,
                    status = CASE WHEN fixed_at_check THEN 'DONE' ELSE 'REPAIR_PLANNED' END,
                    done_at = CASE WHEN fixed_at_check THEN v_now END, version = version + 1
                WHERE id = p_report;
                PERFORM app.problem_report_event(p_report, 'OWNER_PAYS', v_note, NULL, p_actor);
            ELSIF COALESCE(v_input ->> 'pays', '') = 'TENANT' THEN
                IF v_report.lease_id IS NULL THEN
                    RAISE EXCEPTION 'Only a Unit with a signed Lease has a tenant who pays'
                        USING ERRCODE = '55000';
                END IF;
                BEGIN
                    v_amount := (v_input ->> 'amount_usd_cents')::numeric;
                EXCEPTION WHEN data_exception THEN
                    v_amount := NULL;
                END;
                IF jsonb_typeof(v_input -> 'amount_usd_cents') <> 'number' OR v_amount IS NULL
                    OR v_amount <> trunc(v_amount) OR v_amount NOT BETWEEN 1 AND 999999999 THEN
                    RAISE EXCEPTION 'Type the amount the tenant pays' USING ERRCODE = '22023';
                END IF;
                v_name := app.problem_text(v_input, 'reason', 500, 'Say why the tenant pays');
                IF v_name IS NULL THEN
                    RAISE EXCEPTION 'Say why the tenant pays' USING ERRCODE = '22023';
                END IF;
                UPDATE app.problem_reports SET pays = 'TENANT', decided_on = v_day,
                    tenant_amount_usd_cents = v_amount::bigint, tenant_reason = v_name,
                    status = 'WAITING_TENANT', version = version + 1 WHERE id = p_report;
                PERFORM app.problem_report_event(p_report, 'TENANT_PAYS', v_name,
                    jsonb_build_object('amount_usd_cents', v_amount::bigint), p_actor);
            ELSE
                RAISE EXCEPTION 'Choose who pays' USING ERRCODE = '22023';
            END IF;
        ELSIF p_step = 'PARTS' THEN
            IF v_state <> 'REPAIR_PLANNED' THEN
                RAISE EXCEPTION 'Only a planned repair waits for parts' USING ERRCODE = '55000';
            END IF;
            UPDATE app.problem_reports SET status = 'WAITING_PARTS', parts_from = 'REPAIR_PLANNED',
                version = version + 1 WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'WAITING_PARTS', v_note, NULL, p_actor);
        ELSIF p_step = 'PARTS_ARRIVED' THEN
            IF v_state <> 'WAITING_PARTS' THEN
                RAISE EXCEPTION 'Only a report waiting for parts gets them' USING ERRCODE = '55000';
            END IF;
            UPDATE app.problem_reports SET status = COALESCE(parts_from, 'REPAIR_PLANNED'),
                parts_from = NULL, version = version + 1 WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'PARTS_ARRIVED', v_note, NULL, p_actor);
        ELSIF p_step = 'DONE' THEN
            IF v_state <> 'REPAIR_PLANNED' THEN
                RAISE EXCEPTION 'Only a planned repair is marked done' USING ERRCODE = '55000';
            END IF;
            UPDATE app.problem_reports SET status = 'DONE', done_at = v_now, version = version + 1
            WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'DONE', v_note, NULL, p_actor);
        ELSIF p_step IN ('TENANT_FIXED', 'TENANT_NOT_FIXED') THEN
            IF v_state <> 'DONE' OR v_report.customer_id IS NULL THEN
                RAISE EXCEPTION 'Only a done repair with a tenant gets the tenant''s check'
                    USING ERRCODE = '55000';
            END IF;
            IF p_step = 'TENANT_FIXED' THEN
                UPDATE app.problem_reports SET status = 'CLOSED', closed_at = v_now,
                    version = version + 1 WHERE id = p_report;
                PERFORM app.problem_report_event(p_report, 'FIXED', v_note, NULL, p_actor);
            ELSE
                UPDATE app.problem_reports SET status = 'REPAIR_PLANNED', done_at = NULL,
                    version = version + 1 WHERE id = p_report;
                PERFORM app.problem_report_event(p_report, 'NOT_FIXED', v_note, NULL, p_actor);
            END IF;
        ELSIF p_step = 'CLOSE' THEN
            IF v_state <> 'DONE' THEN
                RAISE EXCEPTION 'Only a done report is closed' USING ERRCODE = '55000';
            END IF;
            UPDATE app.problem_reports SET status = 'CLOSED', closed_at = v_now,
                close_note = v_note, version = version + 1 WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'MANAGER_CLOSED', v_note, NULL, p_actor);
        ELSIF p_step = 'JOIN' THEN
            BEGIN
                v_main := (v_input ->> 'main_id')::uuid;
            EXCEPTION WHEN data_exception THEN
                v_main := NULL;
            END;
            IF v_main IS NULL THEN
                RAISE EXCEPTION 'Choose the main report' USING ERRCODE = '22023';
            END IF;
            v_name := app.problem_text(v_input, 'reason', 500, 'Say why it is the same problem');
            IF v_name IS NULL THEN
                RAISE EXCEPTION 'Say why it is the same problem' USING ERRCODE = '22023';
            END IF;
            PERFORM app.problem_report_join_to(p_report, v_main, v_name, p_actor);
            UPDATE app.problem_reports SET version = version + 1 WHERE id = v_main;
        ELSIF p_step = 'UNJOIN' THEN
            IF v_report.status <> 'JOINED' THEN
                RAISE EXCEPTION 'Only a joined report is taken out of the join' USING ERRCODE = '55000';
            END IF;
            IF v_note IS NULL THEN
                RAISE EXCEPTION 'Say why the join is undone' USING ERRCODE = '22023';
            END IF;
            SELECT joined.* INTO v_join FROM app.problem_report_joins AS joined
            WHERE joined.report_id = p_report
              AND NOT EXISTS (SELECT 1 FROM app.problem_report_join_endings AS ended
                              WHERE ended.join_id = joined.id)
            ORDER BY joined.joined_at DESC LIMIT 1;
            INSERT INTO app.problem_report_join_endings (join_id, reason, ended_by)
            VALUES (v_join.id, v_note, p_actor);
            UPDATE app.problem_reports SET status = v_join.previous_status, joined_to_id = NULL,
                version = version + 1 WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'UNJOINED', v_note,
                jsonb_build_object('main_number', (SELECT main.report_number
                    FROM app.problem_reports AS main WHERE main.id = v_report.joined_to_id)), p_actor);
            PERFORM app.problem_report_event(v_report.joined_to_id, 'UNJOINED_OUT', v_note,
                jsonb_build_object('report_number', v_report.report_number), p_actor);
        ELSE
            RAISE EXCEPTION 'The step is invalid' USING ERRCODE = '22023';
        END IF;
        PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.step', 'problem_report',
            p_report, COALESCE(v_note, p_step),
            CASE WHEN p_step IN ('JOIN', 'UNJOIN') THEN 'problem_reports.join'
                 ELSE 'problem_reports.plan' END,
            jsonb_build_object('status', v_report.status), jsonb_build_object('step', p_step),
            p_correlation);
        RETURN v_report.version + 1;
    END $$;

    -- 3. The tenant's answer. Agree makes the Damage Invoice draft at once, for exactly the
    -- amount the Manager set; Refuse charges nothing.
    CREATE FUNCTION app.record_problem_tenant_answer(p_property uuid, p_report uuid,
        p_expected_version integer, p_answer text, p_how text, p_answered_on date, p_said text,
        p_after_refusal text, p_actor uuid, p_correlation uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'problem_reports.plan', p_property);
        v_report app.problem_reports%ROWTYPE;
        v_said text := NULLIF(btrim(p_said), '');
        v_type text;
        v_charge uuid := gen_random_uuid();
        v_audit uuid := gen_random_uuid();
        v_now timestamptz := clock_timestamp();
        v_customer uuid;
        v_unit uuid;
        v_draft jsonb;
        v_how_words text;
    BEGIN
        SELECT report.* INTO v_report FROM app.problem_reports AS report
        WHERE report.id = p_report AND report.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Problem report does not exist' USING ERRCODE = '22023';
        END IF;
        IF p_expected_version IS DISTINCT FROM v_report.version THEN
            RAISE EXCEPTION 'the Problem report changed since it was read' USING ERRCODE = '40001';
        END IF;
        IF v_report.status <> 'WAITING_TENANT' THEN
            RAISE EXCEPTION 'Only a report waiting for the tenant gets the tenant''s answer'
                USING ERRCODE = '55000';
        END IF;
        IF p_answer IS NULL OR p_answer NOT IN ('AGREED', 'REFUSED')
            OR p_how IS NULL OR p_how NOT IN ('SIGNED', 'TELEGRAM', 'PHONE', 'IN_PERSON') THEN
            RAISE EXCEPTION 'Choose the answer and how the tenant gave it' USING ERRCODE = '22023';
        END IF;
        IF p_answered_on IS NULL OR p_answered_on < v_report.decided_on OR p_answered_on > v_day THEN
            RAISE EXCEPTION 'The tenant answered between the day the amount was set and today'
                USING ERRCODE = '22023';
        END IF;
        IF v_said IS NOT NULL AND length(v_said) > 500 THEN
            RAISE EXCEPTION 'What the tenant said is at most 500 letters' USING ERRCODE = '22023';
        END IF;
        IF p_answer = 'REFUSED' AND (v_said IS NULL OR p_after_refusal IS NULL
                OR p_after_refusal NOT IN ('OWNER_PAYS', 'MOVE_OUT')) THEN
            RAISE EXCEPTION 'Write what the tenant said and choose what happens next'
                USING ERRCODE = '22023';
        END IF;
        v_how_words := CASE p_how WHEN 'SIGNED' THEN 'signed' WHEN 'TELEGRAM' THEN 'by Telegram'
            WHEN 'PHONE' THEN 'by phone' ELSE 'in person' END;
        IF p_answer = 'AGREED' THEN
            SELECT lease.primary_tenant_id, lease.unit_id INTO v_customer, v_unit
            FROM app.leases AS lease WHERE lease.id = v_report.lease_id;
            SELECT kind.name_en INTO v_type FROM app.problem_types AS kind
            WHERE kind.id = v_report.problem_type_id;
            PERFORM app.require_invoice_command_actor(p_property, p_actor);
            UPDATE app.problem_reports SET tenant_answer = 'AGREED', tenant_answer_how = p_how,
                tenant_answer_on = p_answered_on, tenant_said = v_said,
                status = CASE WHEN fixed_at_check THEN 'DONE' ELSE 'REPAIR_PLANNED' END,
                done_at = CASE WHEN fixed_at_check THEN statement_timestamp() END,
                version = version + 1
            WHERE id = p_report;
            INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                authorization_evidence, customer_id, lease_id, unit_id)
            VALUES (v_audit, v_now, v_day, p_actor, 'invoice.one_time_charge.recorded',
                'authorized_nonrecurring_obligation', v_charge, v_report.tenant_reason,
                'problem_reports.plan', p_property, '{}'::jsonb,
                jsonb_build_object('category', 'DAMAGE_CHARGES',
                    'amount_usd_cents', v_report.tenant_amount_usd_cents,
                    'problem_report_id', p_report, 'report_number', v_report.report_number),
                COALESCE(p_correlation, gen_random_uuid()), 'API', 'SUCCEEDED',
                jsonb_build_object('capability', 'problem_reports.plan'), v_customer,
                v_report.lease_id, v_unit);
            INSERT INTO app.authorized_nonrecurring_obligations (id, customer_id, lease_id, category,
                problem_report_id, description, authorized_amount_usd_cents, governing_due_date,
                due_date_source, source_reference, authorized_at, authorized_by,
                authorization_reference, due_date_rule, reason, evidence_reference, audit_event_id)
            VALUES (v_charge, v_customer, v_report.lease_id, 'DAMAGE_CHARGES', p_report,
                left('Damage: ' || v_type || ' (' || v_report.report_number || ')', 1000),
                v_report.tenant_amount_usd_cents, NULL, 'BR-INV-018',
                'problem-report:' || p_report::text, v_now, p_actor, 'problem_reports.plan',
                'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS', v_report.tenant_reason,
                left('Problem report ' || v_report.report_number || ': the tenant agreed '
                    || v_how_words || ' on ' || to_char(p_answered_on, 'DD/MM/YYYY'), 500),
                v_audit);
            v_draft := app.create_invoice_draft(p_property, v_charge, p_actor, gen_random_uuid(),
                encode(sha256(convert_to('problem-damage:' || p_report::text, 'UTF8')), 'hex'),
                gen_random_uuid(), gen_random_uuid(), gen_random_uuid(),
                COALESCE(p_correlation, gen_random_uuid()));
            PERFORM app.problem_report_event(p_report, 'TENANT_AGREED', v_said,
                jsonb_build_object('how', p_how, 'on', p_answered_on,
                    'amount_usd_cents', v_report.tenant_amount_usd_cents,
                    'invoice_id', v_draft ->> 'invoice_id'), p_actor);
        ELSE
            UPDATE app.problem_reports SET tenant_answer = 'REFUSED', tenant_answer_how = p_how,
                tenant_answer_on = p_answered_on, tenant_said = v_said,
                status = CASE WHEN p_after_refusal = 'MOVE_OUT' THEN 'CLOSED'
                              WHEN fixed_at_check THEN 'DONE' ELSE 'REPAIR_PLANNED' END,
                done_at = CASE WHEN p_after_refusal = 'OWNER_PAYS' AND fixed_at_check
                               THEN statement_timestamp() END,
                closed_at = CASE WHEN p_after_refusal = 'MOVE_OUT' THEN statement_timestamp() END,
                close_note = CASE WHEN p_after_refusal = 'MOVE_OUT'
                                  THEN 'Left for the move-out inspection' END,
                version = version + 1
            WHERE id = p_report;
            PERFORM app.problem_report_event(p_report, 'TENANT_REFUSED', v_said,
                jsonb_build_object('how', p_how, 'on', p_answered_on, 'next', p_after_refusal),
                p_actor);
        END IF;
        PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.tenant_answer',
            'problem_report', p_report, COALESCE(v_said, p_answer), 'problem_reports.plan',
            jsonb_build_object('status', 'WAITING_TENANT'),
            jsonb_build_object('answer', p_answer, 'how', p_how), p_correlation);
        RETURN v_report.version + 1;
    END $$;
"""


def upgrade() -> None:
    capability_rows = ",\n            ".join(
        f"({_text(name)}, pg_catalog.split_part({_text(name)}, '.', 1), {_text(description)}, "
        f"'bundle', '{PROVENANCE}')"
        for name, description in CAPABILITIES
    )
    mapping_rows = ",\n            ".join(
        f"({_text(code)}, {_text(name)}, '{PROVENANCE}')"
        for code, _en, _kh, names in PERMISSIONS
        for name in names
    )
    op.execute(
        f"""
        -- 6. The rights and their permissions.
        INSERT INTO app.capabilities (capability_id, family, description, grant_path, provenance)
        VALUES
            {capability_rows};
        """
    )
    for code, en, kh, _names in PERMISSIONS:
        op.execute(
            "INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, "
            f"name_kh, provenance) VALUES ({_text(code)}, 'OPERATIONS', "
            "(SELECT max(sort_order) FROM app.permissions) + 1, "
            f"{_text(en)}, {_text(kh)}, '{PROVENANCE}')"
        )
    op.execute(
        f"""
        INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance)
        VALUES
            {mapping_rows};
        """
    )
    op.execute(TABLES)
    type_rows = ",\n            ".join(
        f"({_text(code)}, {_text(en)}, {_text(kh)}, {_text(icon)}, {'true' if always else 'false'}, {position})"
        for position, (code, icon, always, en, kh) in enumerate(TYPES, start=1)
    )
    place_rows = ",\n            ".join(
        f"({_text(code)}, {_text(en)}, {_text(kh)}, {position})"
        for position, (code, en, kh) in enumerate(PLACES, start=1)
    )
    op.execute(
        f"""
        INSERT INTO app.problem_types (code, name_en, name_kh, icon, always_urgent, sort_order)
        VALUES
            {type_rows};
        INSERT INTO app.problem_places (code, name_en, name_kh, sort_order)
        VALUES
            {place_rows};
        """
    )
    _patch(RANGE, ((RANGE_BEFORE, RANGE_AFTER),))
    for code, unit, value, en, kh in RULES:
        op.execute(
            f"""
            WITH named AS (
                INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                    used_by_app)
                VALUES ({_text(code)}, {_text(en)}, {_text(kh)}, {_text(unit)}, 'REPAIRS', true)
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
    op.execute(
        """
        REVOKE ALL ON TABLE app.problem_types, app.problem_places, app.problem_reports,
            app.problem_report_events, app.problem_report_joins, app.problem_report_join_endings
            FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.problem_types, app.problem_places, app.problem_reports,
            app.problem_report_events, app.problem_report_joins, app.problem_report_join_endings
            TO prm_runtime;
        """
    )
    for signature in (
        "app.problem_reports_read(uuid, uuid)",
        "app.problem_report_read(uuid, uuid, uuid)",
        "app.problem_report_choices(uuid, uuid)",
        "app.add_problem_report(uuid, jsonb, uuid, uuid)",
        "app.problem_report_step(uuid, uuid, integer, text, jsonb, uuid, uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    answer = (
        "app.record_problem_tenant_answer(uuid, uuid, integer, text, text, date, text, text, "
        "uuid, uuid)"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {answer} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {answer} TO prm_financial")

    # 6. New Properties: Staff see and add; the Owner and Manager get every right.
    _patch(
        SEED,
        (
            (
                STAFF_BEFORE,
                "'quotations.read', " + ", ".join(_text(name) for name in STAFF) + "]::text[]",
            ),
        ),
    )
    every = _array(OWNER)
    staff = _array(STAFF)
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
                        WHEN seeded.staff_bundle_id THEN {staff}
                        ELSE {every}
                    END AS added
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (
                      seeded.owner_bundle_id, seeded.manager_bundle_id, seeded.staff_bundle_id)
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
    raise RuntimeError("V1.1 part 7 migration is forward-only")
