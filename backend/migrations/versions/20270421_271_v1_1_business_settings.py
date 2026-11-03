# ruff: noqa: E501
"""V1.1 rework part 2 (owner 2026-11-03 "resume automatically"): Settings > Business.

The plan of 01/11/2026 (owner agreed every part) and the owner's database decisions of 30/10 to
01/11/2026. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.

1. ``app.number_rules``: one table for every document number, one row per document type and
   year (id, document_type, year, last_number, format, updated_at, updated_by). The format is the
   letters plus ``yy000n``, so INVyy000n gives INV260001; past 9999 the number simply grows. The
   rows carry on from ``document_number_counters`` (Invoice, Receipt, Refund) and from
   ``gl_number_counters`` (the ledger's JE, ER, EX, SB, AJ, FA and MV), so no number is ever given
   twice. ``app.next_document_number`` and ``app.gl_next_number`` now take their numbers here;
   the two old counter tables stay, unused, until the database clean-up talk. The year is the
   Property's time zone year. The Owner changes the letters with
   ``app.set_number_rule_letters``; new letters are used for new numbers only, and no two
   documents share letters. The ledger number checks are relaxed to any 2 to 5 letters so a
   change of letters never blocks a ledger record.
2. ``app.invoice_types``: one row per kind of Invoice with ``late_payment`` Yes/No. Every type
   starts at Yes, the first Rent included (owner 01/11/2026 02:54). The automatic late-payment
   charge now asks the type instead of always leaving out the first Rent; a person's
   late-payment decision and its review follow the same switch (and keep the fixed 10%). The
   Owner changes it with ``app.set_invoice_type_late_payment`` (a reason is kept in History).
3. ``app.properties`` gets ``description`` and ``business_name`` (the business name can differ
   from the property name). ``app.update_property_details`` changes the name, description,
   address and business name at the expected version, with History. The time zone stays fixed:
   it comes from the business location (Cambodia), with no "same as this device" choice.
4. Business rules (tables from migration 263) for Billing, Reservations, Prices, Quotations and
   the Riel rate, with the values the app used before, in force from 01/01/2026. The program now
   reads two of them: the late-payment charge percent and the days after issue for other
   Invoices. The others show "Not used yet" until a later step wires them. Each rule the program
   reads keeps a safe range (a late charge of 0 to 100%, 1 to 90 days). The older "days after
   issue" setting (``app.set_one_time_charge_due_days``) now also writes the rule from today, so
   the two never disagree.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270421_271"
down_revision: str | None = "20270420_270"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_REASON = "First value: the value the app used before V1.1 (owner decisions 31/10/2026)"

# document_type, letters, ledger series (None for the V1 documents)
DOCUMENTS = (
    ("INVOICE", "INV", None),
    ("RECEIPT", "RCP", None),
    ("REFUND", "RFD", None),
    ("JOURNAL_ENTRY", "JE", "JE"),
    ("EXPENSE_REQUEST", "ER", "ER"),
    ("EXPENSE", "EX", "EX"),
    ("SUPPLIER_BILL", "SB", "SB"),
    ("ADJUSTING_ENTRY", "AJ", "AJ"),
    ("FIXED_ASSET", "FA", "FA"),
    ("MONEY_MOVEMENT", "MV", "MV"),
)

LEDGER_NUMBER_CHECKS = (
    ("gl_expense_requests", "gl_expense_requests_request_number_check", "request_number"),
    ("gl_journal_entries", "gl_journal_entries_entry_number_check", "entry_number"),
    ("gl_expenses", "gl_expenses_expense_number_check", "expense_number"),
    ("gl_supplier_bills", "gl_supplier_bills_bill_number_check", "bill_number"),
    ("gl_money_moves", "gl_money_moves_move_number_check", "move_number"),
    ("gl_fixed_assets", "gl_fixed_assets_asset_number_check", "asset_number"),
    ("gl_adjusting_entries", "gl_adjusting_entries_adjustment_number_check", "adjustment_number"),
)

# code, English name, Khmer name, sort order
INVOICE_TYPES = (
    ("FIRST_RENT", "First Rent", "ថ្លៃឈ្នួលដំបូង", 1),
    ("RENT", "Monthly Rent", "ថ្លៃឈ្នួលប្រចាំខែ", 2),
    ("UTILITIES", "Utilities", "ថ្លៃទឹកភ្លើង", 3),
    ("SERVICES", "Services", "សេវា", 4),
    ("DAMAGE", "Damage", "ការខូចខាត", 5),
    ("MISCELLANEOUS", "Miscellaneous", "ផ្សេងៗ", 6),
)

# code, area, unit, value (None = not set), used by the program, English name, Khmer name
RULES = (
    ("METER_READING_DAY", "BILLING", "DAY_OF_MONTH", 24, False, "Meters read on", "អានកុងទ័រនៅ"),
    (
        "INVOICE_ISSUE_DAY",
        "BILLING",
        "DAY_OF_MONTH",
        25,
        False,
        "Invoices issued on",
        "ចេញវិក្កយបត្រនៅ",
    ),
    (
        "RENT_DUE_DAY",
        "BILLING",
        "DAY_OF_MONTH",
        5,
        False,
        "Rent and Utilities due on",
        "ថ្ងៃផុតកំណត់ឈ្នួល និងទឹកភ្លើង",
    ),
    (
        "OTHER_INVOICE_DUE_DAYS",
        "BILLING",
        "DAYS",
        None,
        True,
        "Other Invoices due after issue",
        "វិក្កយបត្រផ្សេងផុតកំណត់ក្រោយចេញ",
    ),
    ("LATE_PAYMENT_PERCENT", "BILLING", "PERCENT", 1000, True, "Late-payment charge", "ថ្លៃបង់យឺត"),
    (
        "RESERVATION_DAYS",
        "RESERVATIONS",
        "DAYS",
        21,
        False,
        "Reservation expires after",
        "ការកក់ផុតកំណត់ក្រោយ",
    ),
    (
        "RESERVATION_EXTENSION_DAYS",
        "RESERVATIONS",
        "DAYS",
        14,
        False,
        "One extension of at most",
        "ការពន្យារម្ដងយ៉ាងច្រើន",
    ),
    (
        "RESERVATION_DEPOSIT_PERCENT",
        "RESERVATIONS",
        "PERCENT",
        2000,
        False,
        "Suggested deposit (of monthly Rent)",
        "ប្រាក់កក់ស្នើ (នៃឈ្នួលប្រចាំខែ)",
    ),
    (
        "PRODUCT_MARK_UP",
        "PRICES",
        "PERCENT",
        2000,
        False,
        "Default mark-up for a new product",
        "ការបូកបន្ថែមលំនាំដើមសម្រាប់ផលិតផលថ្មី",
    ),
    (
        "PRODUCT_MIN_MARK_UP",
        "PRICES",
        "PERCENT",
        1500,
        False,
        "Default minimum mark-up",
        "ការបូកបន្ថែមអប្បបរមាលំនាំដើម",
    ),
    (
        "PRODUCT_MAX_MARK_UP",
        "PRICES",
        "PERCENT",
        None,
        False,
        "Default maximum mark-up",
        "ការបូកបន្ថែមអតិបរមាលំនាំដើម",
    ),
    (
        "PRICE_ROUND_UP",
        "PRICES",
        "USD_CENTS",
        10,
        False,
        "Round new prices up to the next",
        "បង្គត់តម្លៃថ្មីឡើងទៅ",
    ),
    ("QUOTATION_DAYS", "QUOTATIONS", "DAYS", 7, False, "Quotation valid for", "សម្រង់តម្លៃមានសុពលភាព"),
    (
        "REPAIR_QUOTATION_DAYS",
        "QUOTATIONS",
        "DAYS",
        7,
        False,
        "Repair Quotation valid for",
        "សម្រង់តម្លៃជួសជុលមានសុពលភាព",
    ),
    (
        "RIEL_RATE_MARK_UP",
        "RIEL_RATE",
        "PERCENT",
        50,
        False,
        "Riel rate: ABA Sell rate plus",
        "អត្រារៀល៖ អត្រាលក់ ABA បូក",
    ),
)

ISSUE_INVOICE = "app.issue_invoice(uuid,uuid,uuid,uuid,text,integer,uuid,uuid,date,text)"
WRITE_CORRECTION_CHARGE = (
    "app.write_correction_one_time_charge(uuid,uuid,uuid,uuid,uuid,uuid,text,uuid,text,bigint,"
    "date,text,text,text,text,jsonb,text,timestamp with time zone,text,text)"
)
SCHEDULED_UTILITY_ITEM = (
    "app.record_scheduled_utility_item(uuid,uuid,text,uuid,uuid,text,uuid,timestamp with time zone)"
)
RECORD_AUTOMATIC_CHARGE = "app.record_automatic_late_payment_charge(uuid,uuid,uuid,uuid,uuid,uuid)"
VALIDATE_AUTOMATIC_CHARGE = "app.validate_automatic_late_payment_decision(uuid)"

DUE_DAYS_BEFORE = "v_business_date+property.one_time_charge_due_days"
DUE_DAYS_AFTER = "v_business_date+app.one_time_charge_due_days(property.id,v_business_date)"
UTILITY_DUE_BEFORE = "+property.one_time_charge_due_days)"
UTILITY_DUE_AFTER = "+app.one_time_charge_due_days(property.id,v_run.business_date))"
RECORD_INITIAL_BEFORE = (
    "IF v_invoice.rent_billing_kind IS NOT DISTINCT FROM 'INITIAL' THEN\n"
    "                RETURN jsonb_build_object('outcome','INITIAL_RENT'); END IF;"
)
RECORD_INITIAL_AFTER = (
    "-- V1.1 (owner 01/11/2026): the Invoice type says whether a late charge is added.\n"
    "            IF NOT app.invoice_type_late_payment(v_invoice.primary_category,\n"
    "                    v_invoice.rent_billing_kind) THEN\n"
    "                RETURN jsonb_build_object('outcome','LATE_PAYMENT_OFF'); END IF;"
)
VALIDATE_INITIAL_BEFORE = "OR v_invoice.rent_billing_kind IS NOT DISTINCT FROM 'INITIAL'"
VALIDATE_INITIAL_AFTER = (
    "OR NOT app.invoice_type_late_payment(v_invoice.primary_category,v_invoice.rent_billing_kind)"
)

SET_LETTERS = "app.set_number_rule_letters(uuid, text, text, uuid, uuid)"
SET_LATE_PAYMENT = "app.set_invoice_type_late_payment(uuid, text, boolean, text, uuid, uuid)"
UPDATE_DETAILS = "app.update_property_details(uuid, text, text, text, text, integer, uuid)"
# A person's late-payment decision follows the same Invoice type switch as the automatic charge.
MANUAL_TYPE_GATE = (
    "OR NOT app.invoice_type_late_payment(v_invoice.primary_category,v_invoice.rent_billing_kind)"
)
VALIDATE_MANUAL = "app.validate_late_payment_decision()"
FINALIZE_MANUAL = "app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,text,bigint,text,uuid,uuid,uuid)"
REVIEW_SNAPSHOT = "app.late_payment_review_snapshot(uuid)"
MANUAL_INITIAL_BEFORE = "OR v_invoice.rent_billing_kind='INITIAL'"
REVIEW_INITIAL_BEFORE = """            IF v_invoice.rent_billing_kind='INITIAL' THEN
                v_blockers:=v_blockers||jsonb_build_array('INITIAL_RENT_NO_LATE_PAYMENT');"""
REVIEW_INITIAL_AFTER = """            IF NOT app.invoice_type_late_payment(v_invoice.primary_category,
                v_invoice.rent_billing_kind) THEN
                v_blockers:=v_blockers||jsonb_build_array(CASE
                    WHEN v_invoice.rent_billing_kind='INITIAL' THEN 'INITIAL_RENT_NO_LATE_PAYMENT'
                    ELSE 'LATE_PAYMENT_OFF' END);"""
# The older "days after issue" setting now also writes the business rule, from today, so the
# two can never disagree.
SET_DUE_DAYS = "app.set_one_time_charge_due_days(uuid,uuid,integer,integer,text,uuid)"
SET_DUE_DAYS_BEFORE = """            RETURN QUERY
            UPDATE app.properties AS configuration
            SET one_time_charge_due_days=p_days"""
SET_DUE_DAYS_AFTER = """            PERFORM app.set_business_rule(p_property,'OTHER_INVOICE_DUE_DAYS',p_days::bigint,
                timezone(v_timezone,v_now)::date,p_reason,p_actor,p_audit_id);
            RETURN QUERY
            UPDATE app.properties AS configuration
            SET one_time_charge_due_days=p_days"""


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


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    documents = ",\n".join(
        f"({_q(kind)}, {_q(letters)}, {'NULL' if series is None else _q(series)})"
        for kind, letters, series in DOCUMENTS
    )
    op.execute(
        f"""
        -- 1. One table for every document number.
        CREATE TABLE app.number_rules (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_type text NOT NULL
                CONSTRAINT number_rules_document_type_shape CHECK (document_type ~ '^[A-Z][A-Z_]{{1,40}}$'),
            year smallint NOT NULL CONSTRAINT number_rules_year_range CHECK (year BETWEEN 2000 AND 2099),
            last_number bigint NOT NULL DEFAULT 0
                CONSTRAINT number_rules_last_number_not_negative CHECK (last_number >= 0),
            format text NOT NULL
                CONSTRAINT number_rules_format_shape CHECK (format ~ '^[A-Z]{{2,5}}yy000n$'),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT number_rules_one_per_year UNIQUE (document_type, year)
        );
        COMMENT ON TABLE app.number_rules IS
            'V1.1: one row per document type and year. format = letters + yy000n (INV260001).';
        COMMENT ON COLUMN app.number_rules.updated_by IS
            'Who last changed the letters; empty for a row the app made itself.';

        -- A row is never removed; its type and year never change and its count never goes back.
        CREATE FUNCTION app.number_rules_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'Document number rows are never removed' USING ERRCODE = '55000';
            END IF;
            IF NEW.id <> OLD.id OR NEW.document_type <> OLD.document_type OR NEW.year <> OLD.year
                OR NEW.last_number < OLD.last_number THEN
                RAISE EXCEPTION 'A document number never goes back' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER number_rules_guard_row BEFORE UPDATE OR DELETE ON app.number_rules
            FOR EACH ROW EXECUTE FUNCTION app.number_rules_guard();
        CREATE TRIGGER number_rules_guard_truncate BEFORE TRUNCATE ON app.number_rules
            FOR EACH STATEMENT EXECUTE FUNCTION app.number_rules_guard();
        REVOKE ALL ON TABLE app.number_rules FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.number_rules TO prm_runtime, prm_financial;
        REVOKE ALL ON FUNCTION app.number_rules_guard() FROM PUBLIC;

        -- Seed: every year already counted, and this year for each type.
        WITH documents (document_type, letters, series) AS (VALUES
        {documents}
        ), v1 AS (
            SELECT counter.document_type, counter.number_year AS year, counter.last_number
            FROM app.document_number_counters AS counter
        ), ledger AS (
            SELECT documents.document_type, counter.number_year AS year,
                max(counter.last_number)::bigint AS last_number
            FROM app.gl_number_counters AS counter
            JOIN documents ON documents.series = counter.series
            GROUP BY documents.document_type, counter.number_year
        ), this_year AS (
            SELECT documents.document_type,
                date_part('year', timezone(
                    coalesce((SELECT property.timezone_name FROM app.properties AS property
                              LIMIT 1), 'Asia/Phnom_Penh'),
                    statement_timestamp()))::smallint AS year,
                0::bigint AS last_number
            FROM documents
        ), rows AS (
            SELECT * FROM v1 UNION ALL SELECT * FROM ledger UNION ALL SELECT * FROM this_year
        )
        INSERT INTO app.number_rules (document_type, year, last_number, format)
        SELECT rows.document_type, rows.year, max(rows.last_number),
            coalesce(
                (SELECT series.letters FROM app.document_number_series AS series
                 WHERE series.document_type = rows.document_type),
                (SELECT documents.letters FROM documents
                 WHERE documents.document_type = rows.document_type)
            ) || 'yy000n'
        FROM rows
        JOIN documents ON documents.document_type = rows.document_type
        GROUP BY rows.document_type, rows.year;

        CREATE FUNCTION app.number_rule_letters(p_format text) RETURNS text
        LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT left(p_format, length(p_format) - 6)
        $$;

        -- Takes the next number of a type for a year. The row stays locked until the
        -- transaction ends, so a rolled-back document leaves no gap and no number is given twice.
        CREATE FUNCTION app.take_document_number(p_document_type text, p_year integer)
        RETURNS text LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_row app.number_rules%ROWTYPE;
            v_number bigint;
        BEGIN
            SELECT rule.* INTO v_row FROM app.number_rules AS rule
            WHERE rule.document_type = p_document_type AND rule.year = p_year FOR UPDATE;
            IF NOT FOUND THEN
                -- A new year starts at 0001 with the letters in use now.
                INSERT INTO app.number_rules (document_type, year, last_number, format)
                SELECT p_document_type, p_year, 0, latest.format
                FROM app.number_rules AS latest
                WHERE latest.document_type = p_document_type
                ORDER BY latest.year DESC
                LIMIT 1
                ON CONFLICT (document_type, year) DO NOTHING;
                SELECT rule.* INTO v_row FROM app.number_rules AS rule
                WHERE rule.document_type = p_document_type AND rule.year = p_year FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Unknown document type' USING ERRCODE = '22023';
                END IF;
            END IF;
            UPDATE app.number_rules AS rule SET last_number = rule.last_number + 1
            WHERE rule.id = v_row.id
            RETURNING rule.last_number INTO v_number;
            RETURN app.number_rule_letters(v_row.format)
                || pg_catalog.lpad((p_year % 100)::text, 2, '0')
                || CASE WHEN v_number < 10000 THEN pg_catalog.lpad(v_number::text, 4, '0')
                        ELSE v_number::text END;
        END $$;
        REVOKE ALL ON FUNCTION app.take_document_number(text, integer) FROM PUBLIC;

        CREATE OR REPLACE FUNCTION app.next_document_number(p_document_type text,
            p_at timestamp with time zone)
        RETURNS text LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            IF p_at IS NULL OR NOT pg_catalog.isfinite(p_at) THEN
                RAISE EXCEPTION 'A document number needs its issue time' USING ERRCODE = '22023';
            END IF;
            SELECT property.timezone_name INTO v_timezone FROM app.properties AS property LIMIT 1;
            RETURN app.take_document_number(p_document_type,
                pg_catalog.date_part('year', p_at AT TIME ZONE
                    coalesce(v_timezone, 'Asia/Phnom_Penh'))::integer);
        END $$;

        CREATE OR REPLACE FUNCTION app.gl_next_number(p_property uuid, p_series text, p_date date)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_type text;
        BEGIN
            v_type := CASE p_series
                WHEN 'JE' THEN 'JOURNAL_ENTRY' WHEN 'ER' THEN 'EXPENSE_REQUEST'
                WHEN 'EX' THEN 'EXPENSE' WHEN 'SB' THEN 'SUPPLIER_BILL'
                WHEN 'AJ' THEN 'ADJUSTING_ENTRY' WHEN 'FA' THEN 'FIXED_ASSET'
                WHEN 'MV' THEN 'MONEY_MOVEMENT' END;
            IF v_type IS NULL OR p_date IS NULL THEN
                RAISE EXCEPTION 'Unknown ledger number series' USING ERRCODE = '22023';
            END IF;
            RETURN app.take_document_number(v_type,
                pg_catalog.date_part('year', p_date)::integer);
        END $$;
        REVOKE ALL ON FUNCTION app.gl_next_number(uuid, text, date) FROM PUBLIC;

        -- The Owner changes the letters of one document; new numbers use them, printed ones
        -- never change. Answers the next number with the new letters.
        CREATE FUNCTION app.set_number_rule_letters(p_property uuid, p_document_type text,
            p_letters text, p_actor uuid, p_correlation uuid)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_year integer;
            v_row app.number_rules%ROWTYPE;
            v_before text;
        BEGIN
            SELECT property.timezone_name INTO v_timezone FROM app.properties AS property
            WHERE property.id = p_property;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
            END IF;
            IF p_letters IS NULL OR p_letters !~ '^[A-Z]{{2,5}}$' OR p_actor IS NULL THEN
                RAISE EXCEPTION 'Use 2 to 5 capital letters' USING ERRCODE = '22023';
            END IF;
            -- One change of letters at a time, so two documents never take the same letters.
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('app.number_rules'));
            v_year := pg_catalog.date_part('year', timezone(v_timezone, statement_timestamp()));
            INSERT INTO app.number_rules (document_type, year, last_number, format)
            SELECT p_document_type, v_year, 0, latest.format
            FROM app.number_rules AS latest
            WHERE latest.document_type = p_document_type
            ORDER BY latest.year DESC
            LIMIT 1
            ON CONFLICT (document_type, year) DO NOTHING;
            SELECT rule.* INTO v_row FROM app.number_rules AS rule
            WHERE rule.document_type = p_document_type AND rule.year = v_year FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unknown document type' USING ERRCODE = '22023';
            END IF;
            v_before := app.number_rule_letters(v_row.format);
            IF EXISTS (
                SELECT 1 FROM (
                    SELECT DISTINCT ON (rule.document_type) rule.document_type, rule.format
                    FROM app.number_rules AS rule
                    ORDER BY rule.document_type, rule.year DESC
                ) AS latest
                WHERE latest.document_type <> p_document_type
                  AND app.number_rule_letters(latest.format) = p_letters
            ) THEN
                RAISE EXCEPTION 'Another document uses these letters' USING ERRCODE = '23505';
            END IF;
            IF v_before <> p_letters THEN
                UPDATE app.number_rules AS rule
                SET format = p_letters || 'yy000n', updated_at = statement_timestamp(),
                    updated_by = p_actor
                WHERE rule.id = v_row.id;
                INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                    entity_type, entity_id, reason, authorization_reference, property_id,
                    previous_state, resulting_state, correlation_id, source, outcome)
                VALUES (gen_random_uuid(), statement_timestamp(),
                    timezone(v_timezone, statement_timestamp())::date, p_actor,
                    'settings.number_rule.changed', 'number_rule', v_row.id,
                    'Document letters changed', 'settings.manage', p_property,
                    jsonb_build_object('document_type', p_document_type,
                        'format', v_row.format),
                    jsonb_build_object('document_type', p_document_type,
                        'format', p_letters || 'yy000n'),
                    p_correlation, 'API', 'SUCCEEDED');
            END IF;
            RETURN p_letters || pg_catalog.lpad((v_year % 100)::text, 2, '0')
                || CASE WHEN v_row.last_number + 1 < 10000
                        THEN pg_catalog.lpad((v_row.last_number + 1)::text, 4, '0')
                        ELSE (v_row.last_number + 1)::text END;
        END $$;
        REVOKE ALL ON FUNCTION {SET_LETTERS} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {SET_LETTERS} TO prm_runtime;
        """
    )
    for table, constraint, column in LEDGER_NUMBER_CHECKS:
        op.execute(
            f"ALTER TABLE app.{table} DROP CONSTRAINT {constraint}, "
            f"ADD CONSTRAINT {constraint} CHECK ({column} ~ '^[A-Z]{{2,5}}[0-9]{{6,}}$')"
        )

    types = ",\n".join(
        f"({_q(code)}, {_q(en)}, {_q(kh)}, {order})" for code, en, kh, order in INVOICE_TYPES
    )
    op.execute(
        f"""
        -- 2. The kinds of Invoice, each with late-payment Yes/No.
        CREATE TABLE app.invoice_types (
            code text PRIMARY KEY CONSTRAINT invoice_types_code_shape CHECK (code ~ '^[A-Z][A-Z_]{{1,40}}$'),
            name_en text NOT NULL CONSTRAINT invoice_types_name_en_text
                CHECK (btrim(name_en) <> '' AND length(name_en) <= 120),
            name_kh text NOT NULL CONSTRAINT invoice_types_name_kh_text
                CHECK (btrim(name_kh) <> '' AND length(name_kh) <= 120),
            late_payment boolean NOT NULL DEFAULT true,
            sort_order smallint NOT NULL,
            version integer NOT NULL DEFAULT 1 CONSTRAINT invoice_types_version_positive CHECK (version > 0),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT
        );
        COMMENT ON COLUMN app.invoice_types.late_payment IS
            'V1.1 (owner 01/11/2026): Yes = an unpaid Invoice of this type gets the automatic '
            'late-payment charge after its Due Date.';
        INSERT INTO app.invoice_types (code, name_en, name_kh, sort_order) VALUES
        {types};

        CREATE FUNCTION app.invoice_types_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'Invoice types are never removed' USING ERRCODE = '55000';
            END IF;
            IF NEW.code <> OLD.code OR NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'An Invoice type keeps its code' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER invoice_types_guard_row BEFORE UPDATE OR DELETE ON app.invoice_types
            FOR EACH ROW EXECUTE FUNCTION app.invoice_types_guard();
        CREATE TRIGGER invoice_types_guard_truncate BEFORE TRUNCATE ON app.invoice_types
            FOR EACH STATEMENT EXECUTE FUNCTION app.invoice_types_guard();
        REVOKE ALL ON TABLE app.invoice_types FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.invoice_types TO prm_runtime, prm_financial;
        REVOKE ALL ON FUNCTION app.invoice_types_guard() FROM PUBLIC;

        -- The type of an Invoice from its category and Rent kind.
        CREATE FUNCTION app.invoice_type_code(p_category text, p_rent_kind text) RETURNS text
        LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT CASE
                WHEN p_category = 'RENT' AND p_rent_kind = 'INITIAL' THEN 'FIRST_RENT'
                WHEN p_category = 'RENT' THEN 'RENT'
                WHEN p_category = 'UTILITIES' THEN 'UTILITIES'
                WHEN p_category = 'SERVICE_CHARGES' THEN 'SERVICES'
                WHEN p_category = 'DAMAGE_CHARGES' THEN 'DAMAGE'
                WHEN p_category = 'MISCELLANEOUS_CHARGES' THEN 'MISCELLANEOUS'
            END
        $$;

        -- Yes when an Invoice of this type gets the late-payment charge (an unknown type: Yes).
        CREATE FUNCTION app.invoice_type_late_payment(p_category text, p_rent_kind text)
        RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT coalesce((SELECT kind.late_payment FROM app.invoice_types AS kind
                WHERE kind.code = app.invoice_type_code(p_category, p_rent_kind)), true)
        $$;

        CREATE FUNCTION app.set_invoice_type_late_payment(p_property uuid, p_code text,
            p_late_payment boolean, p_reason text, p_actor uuid, p_correlation uuid)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_type app.invoice_types%ROWTYPE;
        BEGIN
            SELECT property.timezone_name INTO v_timezone FROM app.properties AS property
            WHERE property.id = p_property;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
            END IF;
            IF p_late_payment IS NULL OR p_actor IS NULL OR p_reason IS NULL
                OR btrim(p_reason) = '' OR length(p_reason) > 500 THEN
                RAISE EXCEPTION 'Late payment Yes or No needs a reason' USING ERRCODE = '22023';
            END IF;
            SELECT kind.* INTO v_type FROM app.invoice_types AS kind
            WHERE kind.code = p_code FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'No Invoice type has this code' USING ERRCODE = '22023';
            END IF;
            IF v_type.late_payment = p_late_payment THEN
                RETURN v_type.version;
            END IF;
            UPDATE app.invoice_types AS kind
            SET late_payment = p_late_payment, version = kind.version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor
            WHERE kind.code = p_code;
            INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome)
            VALUES (gen_random_uuid(), statement_timestamp(),
                timezone(v_timezone, statement_timestamp())::date, p_actor,
                'settings.invoice_type.late_payment_changed', 'invoice_type', p_property,
                btrim(p_reason), 'settings.manage', p_property,
                jsonb_build_object('code', p_code, 'late_payment', v_type.late_payment),
                jsonb_build_object('code', p_code, 'late_payment', p_late_payment),
                p_correlation, 'API', 'SUCCEEDED');
            RETURN v_type.version + 1;
        END $$;
        REVOKE ALL ON FUNCTION {SET_LATE_PAYMENT} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {SET_LATE_PAYMENT} TO prm_runtime;

        -- 3. The Property's description and the business name.
        ALTER TABLE app.properties
            ADD COLUMN description text CONSTRAINT properties_description_text
                CHECK (description IS NULL OR (description = btrim(description)
                    AND description <> '' AND length(description) <= 500)),
            ADD COLUMN business_name text CONSTRAINT properties_business_name_text
                CHECK (business_name IS NULL OR (business_name = btrim(business_name)
                    AND business_name <> '' AND length(business_name) <= 255));
        CREATE OR REPLACE VIEW app.property_configuration AS
            SELECT singleton_key, id AS property_id, timezone_name, version, created_at, name,
                address_text, created_by, updated_at, updated_by, description, business_name
            FROM app.properties;

        CREATE FUNCTION app.update_property_details(p_property_id uuid, p_name text,
            p_description text, p_address_text text, p_business_name text,
            p_expected_version integer, p_actor_id uuid)
        RETURNS TABLE(property_id uuid, name text, address_text text, timezone_name text,
            version integer, description text, business_name text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_before app.properties%ROWTYPE;
            v_now timestamptz := statement_timestamp();
        BEGIN
            IF p_name IS NULL OR btrim(p_name) = '' OR length(btrim(p_name)) > 255
                OR length(btrim(coalesce(p_description, ''))) > 500
                OR length(btrim(coalesce(p_business_name, ''))) > 255
                OR length(btrim(coalesce(p_address_text, ''))) > 2000 OR p_actor_id IS NULL THEN
                RAISE EXCEPTION 'Property details are invalid' USING ERRCODE = '22023';
            END IF;
            SELECT property.* INTO v_before FROM app.properties AS property
            WHERE property.id = p_property_id FOR UPDATE;
            IF NOT FOUND OR v_before.version <> p_expected_version THEN
                RETURN;
            END IF;
            UPDATE app.properties AS property
            SET name = btrim(p_name),
                description = nullif(btrim(coalesce(p_description, '')), ''),
                address_text = nullif(btrim(coalesce(p_address_text, '')), ''),
                business_name = nullif(btrim(coalesce(p_business_name, '')), ''),
                updated_at = greatest(v_now, property.updated_at), updated_by = p_actor_id,
                version = property.version + 1
            WHERE property.id = p_property_id;
            INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome)
            VALUES (gen_random_uuid(), v_now, timezone(v_before.timezone_name, v_now)::date,
                p_actor_id, 'property.details_changed', 'property', p_property_id,
                'Property details changed', 'settings.manage', p_property_id,
                jsonb_build_object('name', v_before.name, 'description', v_before.description,
                    'address_text', v_before.address_text,
                    'business_name', v_before.business_name, 'version', v_before.version),
                jsonb_build_object('name', btrim(p_name),
                    'description', nullif(btrim(coalesce(p_description, '')), ''),
                    'address_text', nullif(btrim(coalesce(p_address_text, '')), ''),
                    'business_name', nullif(btrim(coalesce(p_business_name, '')), ''),
                    'version', v_before.version + 1),
                gen_random_uuid(), 'API', 'SUCCEEDED');
            RETURN QUERY
            SELECT property.id, property.name, property.address_text, property.timezone_name,
                property.version, property.description, property.business_name
            FROM app.properties AS property WHERE property.id = p_property_id;
        END $$;
        REVOKE ALL ON FUNCTION {UPDATE_DETAILS} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {UPDATE_DETAILS} TO prm_runtime;

        -- 4. The days after issue for other Invoices: the business rule, else the old value.
        CREATE FUNCTION app.one_time_charge_due_days(p_property uuid, p_on date)
        RETURNS integer LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT coalesce(app.business_rule_value('OTHER_INVOICE_DUE_DAYS', p_on)::integer,
                (SELECT property.one_time_charge_due_days FROM app.properties AS property
                 WHERE property.id = p_property))
        $$;
        REVOKE ALL ON FUNCTION app.one_time_charge_due_days(uuid, date) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.one_time_charge_due_days(uuid, date) TO prm_runtime;

        -- The late-payment charge percent: the business rule (hundredths of a percent).
        CREATE OR REPLACE FUNCTION app.late_payment_rate_basis_points(p_property_id uuid,
            p_charge_date date)
        RETURNS smallint LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT coalesce(app.business_rule_value('LATE_PAYMENT_PERCENT', p_charge_date),
                1000)::smallint
        $$;

        -- A rule the program reads keeps a safe range.
        CREATE FUNCTION app.business_rules_program_range() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_code text;
        BEGIN
            SELECT name.code INTO STRICT v_code FROM app.business_rule_names AS name
            WHERE name.id = NEW.rule_name_id;
            IF (v_code = 'LATE_PAYMENT_PERCENT' AND NEW.value > 10000)
                OR (v_code = 'OTHER_INVOICE_DUE_DAYS' AND NEW.value NOT BETWEEN 1 AND 90)
                OR (v_code IN ('METER_READING_DAY', 'INVOICE_ISSUE_DAY', 'RENT_DUE_DAY')
                    AND NEW.value NOT BETWEEN 1 AND 28) THEN
                RAISE EXCEPTION 'The business rule value is outside what the app allows'
                    USING ERRCODE = '22023';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER business_rules_program_range_row BEFORE INSERT ON app.business_rules
            FOR EACH ROW EXECUTE FUNCTION app.business_rules_program_range();
        REVOKE ALL ON FUNCTION app.business_rules_program_range() FROM PUBLIC;
        """
    )
    for code, area, unit, value, used, en, kh in RULES:
        if code == "OTHER_INVOICE_DUE_DAYS":
            # The days the Property used before (7 on a new database).
            amount = (
                "coalesce((SELECT property.one_time_charge_due_days "
                "FROM app.properties AS property LIMIT 1), 7)"
            )
        else:
            amount = "NULL" if value is None else str(value)
        op.execute(
            f"""
            WITH named AS (
                INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                    used_by_app)
                VALUES ({_q(code)}, {_q(en)}, {_q(kh)}, {_q(unit)}, {_q(area)},
                    {"true" if used else "false"})
                RETURNING id
            ), first_value (value) AS (SELECT ({amount})::bigint)
            INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
            SELECT named.id, first_value.value, DATE '2026-01-01', {_q(SEED_REASON)},
                (SELECT classification.actor_id FROM app.user_account_classes AS classification
                 WHERE classification.account_class = 'owner')
            FROM named, first_value
            WHERE first_value.value IS NOT NULL
            """
        )
    _patch(ISSUE_INVOICE, ((DUE_DAYS_BEFORE, DUE_DAYS_AFTER),))
    _patch(WRITE_CORRECTION_CHARGE, ((DUE_DAYS_BEFORE, DUE_DAYS_AFTER),))
    _patch(SCHEDULED_UTILITY_ITEM, ((UTILITY_DUE_BEFORE, UTILITY_DUE_AFTER),))
    _patch(RECORD_AUTOMATIC_CHARGE, ((RECORD_INITIAL_BEFORE, RECORD_INITIAL_AFTER),))
    _patch(VALIDATE_AUTOMATIC_CHARGE, ((VALIDATE_INITIAL_BEFORE, VALIDATE_INITIAL_AFTER),))
    _patch(SET_DUE_DAYS, ((SET_DUE_DAYS_BEFORE, SET_DUE_DAYS_AFTER),))
    _patch(VALIDATE_MANUAL, ((MANUAL_INITIAL_BEFORE, MANUAL_TYPE_GATE),))
    _patch(FINALIZE_MANUAL, ((MANUAL_INITIAL_BEFORE, MANUAL_TYPE_GATE),))
    _patch(REVIEW_SNAPSHOT, ((REVIEW_INITIAL_BEFORE, REVIEW_INITIAL_AFTER),))


def downgrade() -> None:
    raise RuntimeError("V1.1 rework part 2 migration is forward-only")
