# ruff: noqa: E501
"""V1.1 Business rules (owner 31/10/2026; General Ledger phase 6 step 1, owner 03/11/2026 L2).

The Owner's business rules live in the database with their full history, never in the program
(DESIGN.md 0.42 "Business rules and Application settings"). The shape is the one the owner agreed
on 31/10/2026 with the V1.1 rework thread, which builds the other Business settings (part 2) on
top of these two tables:

1. ``app.business_rule_names``: one row per rule. ``code`` is stable upper snake case and the
   program looks a rule up by it; ``value_unit`` says how to read the whole-number value;
   ``used_by_app`` false is the screen's "Not used yet" (the Owner may add a rule before the
   program uses it). ``area`` groups the rules on the Settings page.
2. ``app.business_rules``: append-only values. A change is a new row with a later
   ``effective_from``; the rule in force on a date is the latest row on or before that date.
   One row per rule and date. A reason is required on every row after a rule's first.
3. ``app.business_rule_value(code, on)`` reads the value in force; ``app.set_business_rule`` and
   ``app.add_business_rule_name`` are the only writers (SECURITY DEFINER, one audit event each).
   The runtime login only reads the tables.
4. The ledger rules the owner decided (01-02/11/2026, PRD v2, mock-up v66) are seeded, in force
   from 01/01/2026: Expense limit $100, Fixed asset smallest cost $500, Petty cash amount $200,
   Expense report due 3 days after spending, Budget warning 10% and $50, Supplier bill due 30 days
   after the bill date.

Downgrade drops the two tables and the functions only while no rule was changed after the seed.
"""

from alembic import op

revision = "20270413_263"
down_revision = "20270412_262"
branch_labels = None
depends_on = None

UNITS = (
    "USD_CENTS",
    "PERCENT",
    "DAYS",
    "DAY_OF_MONTH",
    "COUNT",
    "MINUTES",
    "HOURS",
    "METRES",
    "YES_NO",
    "TIME_OF_DAY",
)
AREAS = (
    "BILLING",
    "RESERVATIONS",
    "PRICES",
    "QUOTATIONS",
    "RIEL_RATE",
    "LEDGER",
    "STAFF",
    "ATTENDANCE",
    "OTHER",
)

# code, area, unit, value, English name, Khmer name
LEDGER_RULES = (
    (
        "EXPENSE_LIMIT",
        "LEDGER",
        "USD_CENTS",
        10000,
        "Expense limit: the Accountant approves up to this, the Owner above",
        "កម្រិតចំណាយ៖ គណនេយ្យករអនុម័តរហូតដល់ចំនួននេះ ម្ចាស់អនុម័តលើសនេះ",
    ),
    (
        "ASSET_LIMIT",
        "LEDGER",
        "USD_CENTS",
        50000,
        "A purchase from this amount is an asset",
        "ការទិញចាប់ពីចំនួននេះជាទ្រព្យសកម្ម",
    ),
    ("PETTY_CASH", "LEDGER", "USD_CENTS", 20000, "Petty cash amount", "ចំនួនសាច់ប្រាក់រាយ"),
    (
        "EXP_REPORT_DAYS",
        "LEDGER",
        "DAYS",
        3,
        "Expense report due after spending",
        "របាយការណ៍ចំណាយផុតកំណត់ក្រោយចំណាយ",
    ),
    (
        "BUDGET_PCT",
        "LEDGER",
        "PERCENT",
        1000,
        "Budget warning: percent off",
        "ការព្រមានថវិកា៖ ភាគរយខុស",
    ),
    (
        "BUDGET_MIN",
        "LEDGER",
        "USD_CENTS",
        5000,
        "Budget warning: smallest amount off",
        "ការព្រមានថវិកា៖ ចំនួនខុសតិចបំផុត",
    ),
    (
        "SUPPLIER_BILL_DAYS",
        "LEDGER",
        "DAYS",
        30,
        "Pay-later Supplier bill due after the bill date",
        "វិក្កយបត្រអ្នកផ្គត់ផ្គង់បង់ក្រោយ ផុតកំណត់ក្រោយថ្ងៃវិក្កយបត្រ",
    ),
)
SEED_REASON = "First value: owner decisions 01-02/11/2026 (General Ledger PRD v2)"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE app.business_rule_names (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE
                CONSTRAINT business_rule_names_code_shape CHECK (code ~ '^[A-Z][A-Z0-9_]{{1,62}}$'),
            name_en text NOT NULL CONSTRAINT business_rule_names_name_en_text
                CHECK (btrim(name_en) <> '' AND length(name_en) <= 200),
            name_kh text NOT NULL CONSTRAINT business_rule_names_name_kh_text
                CHECK (btrim(name_kh) <> '' AND length(name_kh) <= 200),
            value_unit text NOT NULL CONSTRAINT business_rule_names_value_unit
                CHECK (value_unit IN ({_sql_list(UNITS)})),
            area text NOT NULL CONSTRAINT business_rule_names_area
                CHECK (area IN ({_sql_list(AREAS)})),
            used_by_app boolean NOT NULL DEFAULT false
        );
        COMMENT ON COLUMN app.business_rule_names.value_unit IS
            'How the whole-number value reads: USD_CENTS money in US cents; PERCENT in hundredths '
            'of a percent (10% = 1000, 0.5% = 50); DAYS a number of days; DAY_OF_MONTH 1 to 31; '
            'COUNT a plain number; MINUTES, HOURS, METRES; YES_NO 1 = Yes, 0 = No; TIME_OF_DAY '
            'minutes after midnight (22:00 = 1320). New units are added to this list only.';
        COMMENT ON COLUMN app.business_rule_names.used_by_app IS
            'false = the program does not use this rule yet ("Not used yet" on the Settings page).';

        CREATE TABLE app.business_rules (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_name_id uuid NOT NULL REFERENCES app.business_rule_names(id) ON DELETE RESTRICT,
            value bigint NOT NULL CONSTRAINT business_rules_value_not_negative CHECK (value >= 0),
            effective_from date NOT NULL,
            reason text CONSTRAINT business_rules_reason_text
                CHECK (reason IS NULL OR (btrim(reason) <> '' AND length(reason) <= 500)),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT business_rules_one_per_date UNIQUE (rule_name_id, effective_from)
        );
        COMMENT ON COLUMN app.business_rules.created_by IS
            'Who made the change; empty only for a value the program seeded with no Owner yet.';

        -- A rule name keeps its code, unit and area; only its names and used_by_app change.
        CREATE FUNCTION app.business_rule_names_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'Business rule names are never removed' USING ERRCODE = '55000';
            END IF;
            IF NEW.id <> OLD.id OR NEW.code <> OLD.code OR NEW.value_unit <> OLD.value_unit
                OR NEW.area <> OLD.area THEN
                RAISE EXCEPTION 'A business rule keeps its code, unit and area'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER business_rule_names_guard_row BEFORE UPDATE OR DELETE
            ON app.business_rule_names FOR EACH ROW EXECUTE FUNCTION app.business_rule_names_guard();
        CREATE TRIGGER business_rule_names_guard_truncate BEFORE TRUNCATE
            ON app.business_rule_names FOR EACH STATEMENT
            EXECUTE FUNCTION app.business_rule_names_guard();

        CREATE FUNCTION app.business_rules_append_only() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Business rule values are append-only (% on %)', TG_OP, TG_TABLE_NAME
                USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER business_rules_append_only_row BEFORE UPDATE OR DELETE
            ON app.business_rules FOR EACH ROW EXECUTE FUNCTION app.business_rules_append_only();
        CREATE TRIGGER business_rules_append_only_truncate BEFORE TRUNCATE
            ON app.business_rules FOR EACH STATEMENT
            EXECUTE FUNCTION app.business_rules_append_only();

        -- A value fits its unit, and every row after a rule's first has a reason.
        CREATE FUNCTION app.business_rules_check() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_unit text;
        BEGIN
            SELECT name.value_unit INTO STRICT v_unit FROM app.business_rule_names AS name
            WHERE name.id = NEW.rule_name_id;
            IF (v_unit = 'DAY_OF_MONTH' AND NEW.value NOT BETWEEN 1 AND 31)
                OR (v_unit = 'PERCENT' AND NEW.value > 1000000)
                OR (v_unit = 'DAYS' AND NEW.value > 3660)
                OR (v_unit = 'USD_CENTS' AND NEW.value > 100000000000)
                OR (v_unit = 'YES_NO' AND NEW.value > 1)
                OR (v_unit = 'TIME_OF_DAY' AND NEW.value > 1439)
                OR (v_unit = 'MINUTES' AND NEW.value > 525600)
                OR (v_unit = 'HOURS' AND NEW.value > 8784) THEN
                RAISE EXCEPTION 'The business rule value does not fit its unit'
                    USING ERRCODE = '22023';
            END IF;
            IF NEW.reason IS NULL AND EXISTS (
                SELECT 1 FROM app.business_rules AS earlier
                WHERE earlier.rule_name_id = NEW.rule_name_id
            ) THEN
                RAISE EXCEPTION 'A business rule change needs a reason' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER business_rules_check_row BEFORE INSERT ON app.business_rules
            FOR EACH ROW EXECUTE FUNCTION app.business_rules_check();

        REVOKE ALL ON TABLE app.business_rule_names, app.business_rules
            FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.business_rule_names, app.business_rules
            TO prm_runtime, prm_financial;
        REVOKE ALL ON FUNCTION app.business_rule_names_guard(), app.business_rules_append_only(),
            app.business_rules_check() FROM PUBLIC;

        -- The value in force on a date: the latest row on or before it (NULL when none).
        CREATE FUNCTION app.business_rule_value(p_code text, p_on date)
        RETURNS bigint LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT rule.value
            FROM app.business_rules AS rule
            JOIN app.business_rule_names AS name ON name.id = rule.rule_name_id
            WHERE name.code = p_code AND rule.effective_from <= p_on
            ORDER BY rule.effective_from DESC
            LIMIT 1
        $$;
        REVOKE ALL ON FUNCTION app.business_rule_value(text, date) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.business_rule_value(text, date)
            TO prm_runtime, prm_financial;

        -- The Owner changes a rule from a date that is not in the past (Property time).
        CREATE FUNCTION app.set_business_rule(p_property uuid, p_code text, p_value bigint,
            p_effective_from date, p_reason text, p_actor uuid, p_correlation uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_name app.business_rule_names%ROWTYPE;
            v_timezone text;
            v_before bigint;
            v_id uuid;
        BEGIN
            SELECT property.timezone_name INTO v_timezone FROM app.properties AS property
            WHERE property.id = p_property;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
            END IF;
            SELECT name.* INTO v_name FROM app.business_rule_names AS name
            WHERE name.code = p_code FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'No business rule has this code' USING ERRCODE = '22023';
            END IF;
            IF p_effective_from IS NULL
                OR p_effective_from < timezone(v_timezone, statement_timestamp())::date THEN
                RAISE EXCEPTION 'A business rule change starts today or later'
                    USING ERRCODE = '22023';
            END IF;
            IF p_reason IS NULL OR btrim(p_reason) = '' THEN
                RAISE EXCEPTION 'A business rule change needs a reason' USING ERRCODE = '23514';
            END IF;
            v_before := app.business_rule_value(p_code, p_effective_from);
            INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
            VALUES (v_name.id, p_value, p_effective_from, btrim(p_reason), p_actor)
            RETURNING id INTO v_id;
            INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome)
            VALUES (gen_random_uuid(), statement_timestamp(),
                timezone(v_timezone, statement_timestamp())::date, p_actor,
                'settings.business_rule.changed', 'business_rule', v_name.id, btrim(p_reason),
                'settings.manage', p_property,
                CASE WHEN v_before IS NULL THEN NULL
                     ELSE jsonb_build_object('code', p_code, 'value', v_before) END,
                jsonb_build_object('code', p_code, 'value', p_value,
                    'effective_from', p_effective_from, 'business_rule_id', v_id),
                p_correlation, 'API', 'SUCCEEDED');
            RETURN v_id;
        END $$;
        REVOKE ALL ON FUNCTION app.set_business_rule(uuid, text, bigint, date, text, uuid, uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.set_business_rule(uuid, text, bigint, date, text, uuid, uuid)
            TO prm_runtime;

        -- The Owner adds a new rule; the program does not use it until a program change does.
        CREATE FUNCTION app.add_business_rule_name(p_property uuid, p_code text, p_name_en text,
            p_name_kh text, p_value_unit text, p_area text, p_value bigint, p_effective_from date,
            p_reason text, p_actor uuid, p_correlation uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_id uuid;
        BEGIN
            SELECT property.timezone_name INTO v_timezone FROM app.properties AS property
            WHERE property.id = p_property;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
            END IF;
            IF p_effective_from IS NULL
                OR p_effective_from < timezone(v_timezone, statement_timestamp())::date THEN
                RAISE EXCEPTION 'A business rule change starts today or later'
                    USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                used_by_app)
            VALUES (p_code, btrim(p_name_en), btrim(p_name_kh), p_value_unit, p_area, false)
            RETURNING id INTO v_id;
            INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
            VALUES (v_id, p_value, p_effective_from, nullif(btrim(p_reason), ''), p_actor);
            INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                resulting_state, correlation_id, source, outcome)
            VALUES (gen_random_uuid(), statement_timestamp(),
                timezone(v_timezone, statement_timestamp())::date, p_actor,
                'settings.business_rule.added', 'business_rule', v_id,
                coalesce(nullif(btrim(p_reason), ''), 'New business rule'), 'settings.manage',
                p_property,
                jsonb_build_object('code', p_code, 'value_unit', p_value_unit, 'area', p_area,
                    'value', p_value, 'effective_from', p_effective_from),
                p_correlation, 'API', 'SUCCEEDED');
            RETURN v_id;
        END $$;
        REVOKE ALL ON FUNCTION app.add_business_rule_name(uuid, text, text, text, text, text,
            bigint, date, text, uuid, uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.add_business_rule_name(uuid, text, text, text, text, text,
            bigint, date, text, uuid, uuid) TO prm_runtime;
        """
    )
    rows = ",\n".join(
        "('{0}', '{1}', '{2}', '{3}', '{4}', {5})".format(
            code, area, unit, en.replace("'", "''"), kh.replace("'", "''"), value
        )
        for code, area, unit, value, en, kh in LEDGER_RULES
    )
    op.execute(
        f"""
        WITH seeded (code, area, value_unit, name_en, name_kh, value) AS (VALUES
        {rows}
        ), named AS (
            INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                used_by_app)
            SELECT code, name_en, name_kh, value_unit, area, true FROM seeded
            RETURNING id, code
        )
        INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
        SELECT named.id, seeded.value, DATE '2026-01-01', '{SEED_REASON}',
            (SELECT classification.actor_id FROM app.user_account_classes AS classification
             WHERE classification.account_class = 'owner')
        FROM named JOIN seeded ON seeded.code = named.code
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.business_rules WHERE reason <> '{SEED_REASON}'
                       OR reason IS NULL) THEN
                RAISE EXCEPTION 'Business rules were changed; they are kept'
                    USING ERRCODE = '55000';
            END IF;
        END $$;
        DROP FUNCTION app.add_business_rule_name(uuid, text, text, text, text, text, bigint, date,
            text, uuid, uuid);
        DROP FUNCTION app.set_business_rule(uuid, text, bigint, date, text, uuid, uuid);
        DROP FUNCTION app.business_rule_value(text, date);
        ALTER TABLE app.business_rules DISABLE TRIGGER business_rules_append_only_row;
        ALTER TABLE app.business_rules DISABLE TRIGGER business_rules_append_only_truncate;
        DROP TABLE app.business_rules;
        ALTER TABLE app.business_rule_names DISABLE TRIGGER business_rule_names_guard_row;
        ALTER TABLE app.business_rule_names DISABLE TRIGGER business_rule_names_guard_truncate;
        DROP TABLE app.business_rule_names;
        DROP FUNCTION app.business_rules_check();
        DROP FUNCTION app.business_rules_append_only();
        DROP FUNCTION app.business_rule_names_guard();
        """
    )
