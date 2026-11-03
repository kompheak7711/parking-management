"""General Ledger core: accounts, fiscal years, periods, journal (V1.1 part 8; PR-GL).

Revision ID: 20270409_259
Revises: 20270408_258
Create Date: 2026-11-02

Owner approved the ledger database plan on 2026-11-02 21:08
(https://claude.ai/artifact/5nttjeU5y5SaNSHU1etyuK), with the recommended answers:
whole cents in ``bigint`` (Q1); a rollback that removes only the new ledger objects and
refuses once an entry is posted (Q2); a month is closed by the Owner or the Accountant when
every check is green and only the Owner closes the year (Q3); the ledger starts on
1 January 2027 (Q4).

This migration adds the ledger's core. Every table is new; no existing table changes.

- ``app.gl_number_counters`` and ``app.gl_next_number``: JE, ER, EX, SB, AJ, FA, MV numbers
  per Property and year (``document_number_series`` stays as it is).
- ``app.gl_accounts`` (PR-GL-001..005): code, English and Khmer names, type, parent,
  control source, tax lock, cash kind, balance-sheet section, cash-flow group, on/off.
  Code and type never change once the account has a line; an account is never deleted.
- ``app.gl_method_accounts`` (PR-GL-004): the cash or bank account of each Payment Method
  and Refund method, effective-dated and append-only.
- ``app.gl_suppliers``.
- ``app.gl_fiscal_years`` and ``app.gl_periods``: January to December, months 1 to 12 and
  a one-day period 13 on 31 December that only the year-end closing entry uses. A period
  closes in month order and never reopens (decisions 10 and 23).
- ``app.gl_journal_entries`` and ``app.gl_journal_lines`` (PR-GL-010..014): append-only;
  a line is debit or credit, never both, never negative; lines only in the transaction that
  made the entry; a deferred constraint trigger checks at commit that each entry has two or
  more lines, debits equal credits, and a reversal mirrors the entry it reverses; no entry in
  a closed period; the year-end closing entry only after every month of its year is closed;
  control accounts take only app-record entries (PR-GL-003); no line on a
  tax-locked, turned-off or heading account (PR-GL-005).
- Internal functions (no grant; the coding phase adds checked wrappers):
  ``app.gl_open_fiscal_year``, ``app.gl_post_entry`` (idempotent by posting key),
  ``app.gl_reverse_entry``, ``app.gl_close_period`` and ``app.gl_close_year``.

Downgrade removes only these objects and refuses once any journal entry exists.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270409_259"
down_revision: str | None = "20270408_258"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = ("gl_method_accounts", "gl_journal_entries", "gl_journal_lines")
READ_TABLES = (
    "gl_number_counters",
    "gl_accounts",
    "gl_method_accounts",
    "gl_suppliers",
    "gl_fiscal_years",
    "gl_periods",
    "gl_journal_entries",
    "gl_journal_lines",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.gl_reject_mutation() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'General ledger records are append-only (% on %)', TG_OP, TG_TABLE_NAME
                USING ERRCODE = '55000';
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_reject_mutation() FROM PUBLIC;

        CREATE TABLE app.gl_number_counters (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            series text NOT NULL CHECK (series IN ('JE','ER','EX','SB','AJ','FA','MV')),
            number_year smallint NOT NULL CHECK (number_year BETWEEN 2000 AND 2099),
            last_number integer NOT NULL CHECK (last_number > 0),
            PRIMARY KEY (property_id, series, number_year)
        );

        CREATE FUNCTION app.gl_next_number(p_property uuid, p_series text, p_date date)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_year smallint := pg_catalog.date_part('year', p_date)::smallint;
            v_number integer;
        BEGIN
            INSERT INTO app.gl_number_counters AS counter
                (property_id, series, number_year, last_number)
            VALUES (p_property, p_series, v_year, 1)
            ON CONFLICT (property_id, series, number_year)
            DO UPDATE SET last_number = counter.last_number + 1
            RETURNING counter.last_number INTO v_number;
            RETURN p_series || pg_catalog.lpad((v_year % 100)::text, 2, '0')
                || pg_catalog.lpad(v_number::text, 4, '0');
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_next_number(uuid, text, date) FROM PUBLIC;

        CREATE TABLE app.gl_accounts (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            code text NOT NULL CHECK (code ~ '^[1-6][0-9]{3}$'),
            name_en text NOT NULL CHECK (length(btrim(name_en)) BETWEEN 1 AND 120
                AND name_en = btrim(name_en)),
            name_km text NOT NULL CHECK (length(btrim(name_km)) BETWEEN 1 AND 120
                AND name_km = btrim(name_km)),
            account_type text NOT NULL CHECK (account_type IN
                ('ASSET','LIABILITY','EQUITY','INCOME','COST_OF_SALES','EXPENSE')),
            normal_side text GENERATED ALWAYS AS (CASE WHEN account_type IN
                ('ASSET','COST_OF_SALES','EXPENSE') THEN 'DEBIT' ELSE 'CREDIT' END) STORED,
            parent_account_id uuid REFERENCES app.gl_accounts(id) ON DELETE RESTRICT,
            is_postable boolean NOT NULL DEFAULT true,
            is_contra boolean NOT NULL DEFAULT false,
            control_source text CHECK (control_source IN ('INVOICES','LATE_CHARGES','STOCK',
                'RENT_IN_ADVANCE','SECURITY_DEPOSITS','PET_DEPOSITS','CUSTOMER_CREDIT',
                'MONEY_NOT_USED')),
            is_tax_locked boolean NOT NULL DEFAULT false,
            is_retained_earnings boolean NOT NULL DEFAULT false,
            allows_unit boolean NOT NULL DEFAULT false,
            bs_section text CHECK (bs_section IN ('CURRENT','NON_CURRENT')),
            cash_kind text CHECK (cash_kind IN ('CASH_USD','CASH_KHR','BANK','PETTY')),
            cash_flow_group text CHECK (cash_flow_group IN ('OPERATING','INVESTING','FINANCING')),
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT gl_accounts_code_key UNIQUE (property_id, code),
            CONSTRAINT gl_accounts_id_property_key UNIQUE (id, property_id),
            CONSTRAINT gl_accounts_section CHECK
                ((account_type IN ('ASSET','LIABILITY')) = (bs_section IS NOT NULL)),
            CONSTRAINT gl_accounts_cash_is_asset CHECK (cash_kind IS NULL OR account_type =
                'ASSET'),
            CONSTRAINT gl_accounts_retained_is_equity CHECK
                (NOT is_retained_earnings OR account_type = 'EQUITY'),
            CONSTRAINT gl_accounts_control_postable CHECK (control_source IS NULL OR is_postable),
            CONSTRAINT gl_accounts_not_own_parent CHECK (parent_account_id IS DISTINCT FROM id)
        );
        CREATE INDEX gl_accounts_parent_idx ON app.gl_accounts(parent_account_id)
            WHERE parent_account_id IS NOT NULL;
        CREATE UNIQUE INDEX gl_accounts_one_retained_idx ON app.gl_accounts(property_id)
            WHERE is_retained_earnings;
        CREATE UNIQUE INDEX gl_accounts_one_control_idx ON app.gl_accounts(property_id,
            control_source)
            WHERE control_source IS NOT NULL;

        CREATE TABLE app.gl_suppliers (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200 AND name = btrim(name)),
            phone text CHECK (phone IS NULL OR length(btrim(phone)) BETWEEN 1 AND 50),
            note text CHECK (note IS NULL OR length(btrim(note)) BETWEEN 1 AND 1000),
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT
        );
        CREATE INDEX gl_suppliers_property_idx ON app.gl_suppliers(property_id, name);

        CREATE TABLE app.gl_method_accounts (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            payment_method_id uuid REFERENCES app.payment_methods(id) ON DELETE RESTRICT,
            refund_method_id uuid REFERENCES app.refund_methods(id) ON DELETE RESTRICT,
            account_id uuid NOT NULL,
            effective_from date NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT gl_method_accounts_account_fkey FOREIGN KEY (account_id, property_id)
                REFERENCES app.gl_accounts(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_method_accounts_one_method CHECK
                (num_nonnulls(payment_method_id, refund_method_id) = 1),
            CONSTRAINT gl_method_accounts_payment_key UNIQUE (payment_method_id, effective_from),
            CONSTRAINT gl_method_accounts_refund_key UNIQUE (refund_method_id, effective_from)
        );
        CREATE INDEX gl_method_accounts_account_idx ON app.gl_method_accounts(account_id);

        CREATE TABLE app.gl_fiscal_years (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            fiscal_year smallint NOT NULL CHECK (fiscal_year BETWEEN 2000 AND 2099),
            starts_on date NOT NULL,
            ends_on date NOT NULL,
            status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
            closed_at timestamptz,
            closed_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            closing_entry_id uuid,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT gl_fiscal_years_key UNIQUE (property_id, fiscal_year),
            CONSTRAINT gl_fiscal_years_id_property_key UNIQUE (id, property_id),
            CONSTRAINT gl_fiscal_years_calendar CHECK (starts_on = make_date(fiscal_year, 1, 1)
                AND ends_on = make_date(fiscal_year, 12, 31)),
            CONSTRAINT gl_fiscal_years_closed CHECK
                ((status = 'CLOSED') = (closed_at IS NOT NULL AND closed_by IS NOT NULL)),
            CONSTRAINT gl_fiscal_years_closing_entry CHECK
                (closing_entry_id IS NULL OR status = 'CLOSED')
        );

        CREATE TABLE app.gl_periods (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            fiscal_year_id uuid NOT NULL,
            property_id uuid NOT NULL,
            period_no smallint NOT NULL CHECK (period_no BETWEEN 1 AND 13),
            starts_on date NOT NULL,
            ends_on date NOT NULL,
            status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
            closed_at timestamptz,
            closed_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            close_checks jsonb,
            CONSTRAINT gl_periods_fiscal_year_fkey FOREIGN KEY (fiscal_year_id, property_id)
                REFERENCES app.gl_fiscal_years(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_periods_key UNIQUE (fiscal_year_id, period_no),
            CONSTRAINT gl_periods_id_property_key UNIQUE (id, property_id),
            CONSTRAINT gl_periods_dates CHECK (ends_on >= starts_on),
            CONSTRAINT gl_periods_closed CHECK ((status = 'CLOSED') =
                (closed_at IS NOT NULL AND closed_by IS NOT NULL AND close_checks IS NOT NULL)),
            CONSTRAINT gl_periods_checks_object CHECK
                (close_checks IS NULL OR jsonb_typeof(close_checks) = 'object')
        );
        CREATE INDEX gl_periods_dates_idx ON app.gl_periods(property_id, starts_on, period_no);

        CREATE TABLE app.gl_journal_entries (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            entry_number text NOT NULL UNIQUE CHECK (entry_number ~ '^JE[0-9]{6,}$'),
            entry_date date NOT NULL,
            period_id uuid NOT NULL,
            entry_kind text NOT NULL CHECK (entry_kind IN ('AUTO','RENT_TO_INCOME',
                'DEPRECIATION','FX_REVALUATION','OPENING','ADJUSTING','REVERSAL',
                'YEAR_END_CLOSE')),
            description text NOT NULL CHECK (length(btrim(description)) BETWEEN 1 AND 500),
            source_type text NOT NULL CHECK (source_type ~ '^[A-Z][A-Z_]{1,62}$'),
            source_id uuid,
            posting_key text NOT NULL UNIQUE CHECK (length(posting_key) BETWEEN 3 AND 300
                AND posting_key = btrim(posting_key)),
            reverses_entry_id uuid UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT,
            reason text CHECK (reason IS NULL OR length(btrim(reason)) BETWEEN 1 AND 1000),
            posted_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            posted_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            approved_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            correlation_id uuid NOT NULL,
            created_txid bigint NOT NULL DEFAULT txid_current(),
            CONSTRAINT gl_je_period_fkey FOREIGN KEY (period_id, property_id)
                REFERENCES app.gl_periods(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_je_id_property_key UNIQUE (id, property_id),
            CONSTRAINT gl_je_reversal CHECK
                ((entry_kind = 'REVERSAL') = (reverses_entry_id IS NOT NULL)),
            CONSTRAINT gl_je_not_self CHECK (reverses_entry_id IS DISTINCT FROM id),
            CONSTRAINT gl_je_reason CHECK
                (entry_kind NOT IN ('ADJUSTING','REVERSAL','OPENING') OR reason IS NOT NULL),
            CONSTRAINT gl_je_approved CHECK (entry_kind <> 'ADJUSTING' OR approved_by IS NOT NULL)
        );
        CREATE INDEX gl_je_date_idx ON app.gl_journal_entries(property_id, entry_date,
            entry_number);
        CREATE INDEX gl_je_period_idx ON app.gl_journal_entries(period_id);
        CREATE INDEX gl_je_source_idx ON app.gl_journal_entries(source_type, source_id)
            WHERE source_id IS NOT NULL;

        ALTER TABLE app.gl_fiscal_years ADD CONSTRAINT gl_fiscal_years_closing_entry_fkey
            FOREIGN KEY (closing_entry_id) REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT;

        CREATE TABLE app.gl_journal_lines (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            entry_id uuid NOT NULL,
            property_id uuid NOT NULL,
            line_no smallint NOT NULL CHECK (line_no BETWEEN 1 AND 500),
            account_id uuid NOT NULL,
            debit_cents bigint NOT NULL DEFAULT 0
                CHECK (debit_cents BETWEEN 0 AND 9000000000000000),
            credit_cents bigint NOT NULL DEFAULT 0
                CHECK (credit_cents BETWEEN 0 AND 9000000000000000),
            memo text CHECK (memo IS NULL OR length(btrim(memo)) BETWEEN 1 AND 500),
            customer_id uuid REFERENCES app.customers(id) ON DELETE RESTRICT,
            lease_id uuid REFERENCES app.leases(id) ON DELETE RESTRICT,
            unit_id uuid REFERENCES app.units(id) ON DELETE RESTRICT,
            supplier_id uuid REFERENCES app.gl_suppliers(id) ON DELETE RESTRICT,
            expense_request_id uuid,
            fixed_asset_id uuid,
            employee_id uuid,
            maintenance_request_id uuid,
            original_currency text NOT NULL DEFAULT 'USD' CHECK (original_currency IN
                ('USD','KHR')),
            original_amount_minor bigint CHECK (original_amount_minor BETWEEN 1 AND
                9000000000000000),
            exchange_rate_record_id uuid REFERENCES app.exchange_rate_records(id) ON DELETE
                RESTRICT,
            CONSTRAINT gl_jl_entry_fkey FOREIGN KEY (entry_id, property_id)
                REFERENCES app.gl_journal_entries(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_jl_account_fkey FOREIGN KEY (account_id, property_id)
                REFERENCES app.gl_accounts(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_jl_line_key UNIQUE (entry_id, line_no),
            CONSTRAINT gl_jl_one_side CHECK ((debit_cents > 0 AND credit_cents = 0)
                OR (credit_cents > 0 AND debit_cents = 0)),
            CONSTRAINT gl_jl_riel CHECK (
                (original_currency = 'USD' AND original_amount_minor IS NULL
                    AND exchange_rate_record_id IS NULL)
                OR (original_currency = 'KHR' AND original_amount_minor IS NOT NULL))
        );
        CREATE INDEX gl_jl_account_idx ON app.gl_journal_lines(account_id, entry_id);
        CREATE INDEX gl_jl_customer_idx ON app.gl_journal_lines(customer_id)
            WHERE customer_id IS NOT NULL;
        CREATE INDEX gl_jl_lease_idx ON app.gl_journal_lines(lease_id) WHERE lease_id IS NOT NULL;
        CREATE INDEX gl_jl_unit_idx ON app.gl_journal_lines(unit_id) WHERE unit_id IS NOT NULL;
        CREATE INDEX gl_jl_supplier_idx ON app.gl_journal_lines(supplier_id)
            WHERE supplier_id IS NOT NULL;
        CREATE INDEX gl_jl_expense_request_idx ON app.gl_journal_lines(expense_request_id)
            WHERE expense_request_id IS NOT NULL;
        CREATE INDEX gl_jl_fixed_asset_idx ON app.gl_journal_lines(fixed_asset_id)
            WHERE fixed_asset_id IS NOT NULL;
        CREATE INDEX gl_jl_employee_idx ON app.gl_journal_lines(employee_id)
            WHERE employee_id IS NOT NULL;
        CREATE INDEX gl_jl_maintenance_idx ON app.gl_journal_lines(maintenance_request_id)
            WHERE maintenance_request_id IS NOT NULL;
        CREATE INDEX gl_jl_rate_idx ON app.gl_journal_lines(exchange_rate_record_id)
            WHERE exchange_rate_record_id IS NOT NULL;
        """
    )
    op.execute(
        r"""
        -- Accounts: code and type are fixed once a line uses the account; never deleted.
        CREATE FUNCTION app.gl_guard_account() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_parent record;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'A ledger account is never deleted; turn it off instead'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
                    OR NEW.created_at <> OLD.created_at OR NEW.created_by <> OLD.created_by
                    OR NEW.control_source IS DISTINCT FROM OLD.control_source
                    OR NEW.is_retained_earnings <> OLD.is_retained_earnings THEN
                    RAISE EXCEPTION 'This account field cannot change' USING ERRCODE = '55000';
                END IF;
                IF (NEW.code <> OLD.code OR NEW.account_type <> OLD.account_type
                        OR NEW.is_postable <> OLD.is_postable
                        OR NEW.cash_kind IS DISTINCT FROM OLD.cash_kind)
                    AND EXISTS (SELECT 1 FROM app.gl_journal_lines AS line
                                WHERE line.account_id = OLD.id) THEN
                    RAISE EXCEPTION 'Account % has entries: its code, type and kind are fixed',
                        OLD.code USING ERRCODE = '55000';
                END IF;
            END IF;
            IF NEW.parent_account_id IS NOT NULL THEN
                SELECT parent.property_id, parent.account_type INTO v_parent
                FROM app.gl_accounts AS parent WHERE parent.id = NEW.parent_account_id;
                IF NOT FOUND OR v_parent.property_id <> NEW.property_id
                    OR v_parent.account_type <> NEW.account_type THEN
                    RAISE EXCEPTION 'A parent account must be of the same Property and type'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_guard_account() FROM PUBLIC;
        CREATE TRIGGER gl_accounts_guard BEFORE INSERT OR UPDATE OR DELETE ON app.gl_accounts
            FOR EACH ROW EXECUTE FUNCTION app.gl_guard_account();
        CREATE TRIGGER gl_accounts_reject_truncate BEFORE TRUNCATE ON app.gl_accounts
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();

        CREATE FUNCTION app.gl_guard_supplier() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'A supplier is never deleted; turn it off instead'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
                OR NEW.created_at <> OLD.created_at OR NEW.created_by <> OLD.created_by THEN
                RAISE EXCEPTION 'This supplier field cannot change' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_guard_supplier() FROM PUBLIC;
        CREATE TRIGGER gl_suppliers_guard BEFORE UPDATE OR DELETE ON app.gl_suppliers
            FOR EACH ROW EXECUTE FUNCTION app.gl_guard_supplier();
        CREATE TRIGGER gl_suppliers_reject_truncate BEFORE TRUNCATE ON app.gl_suppliers
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();

        -- Method accounts point only at cash or bank accounts.
        CREATE FUNCTION app.gl_check_method_account() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM app.gl_accounts AS account
                           WHERE account.id = NEW.account_id AND account.cash_kind IS NOT NULL) THEN
                RAISE EXCEPTION 'A Payment Method or Refund method uses a cash or bank account'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_check_method_account() FROM PUBLIC;
        CREATE TRIGGER gl_method_accounts_check BEFORE INSERT ON app.gl_method_accounts
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_method_account();

        -- Fiscal years: fixed dates; only OPEN to CLOSED; never deleted.
        CREATE FUNCTION app.gl_guard_fiscal_year() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'A fiscal year is never deleted' USING ERRCODE = '55000';
            END IF;
            IF NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
                OR NEW.fiscal_year <> OLD.fiscal_year OR NEW.starts_on <> OLD.starts_on
                OR NEW.ends_on <> OLD.ends_on OR NEW.created_at <> OLD.created_at
                OR NEW.created_by <> OLD.created_by
                OR NOT (OLD.status = 'OPEN' AND NEW.status = 'CLOSED') THEN
                RAISE EXCEPTION 'A fiscal year only closes, once, and never reopens'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_guard_fiscal_year() FROM PUBLIC;
        CREATE TRIGGER gl_fiscal_years_guard BEFORE UPDATE OR DELETE ON app.gl_fiscal_years
            FOR EACH ROW EXECUTE FUNCTION app.gl_guard_fiscal_year();
        CREATE TRIGGER gl_fiscal_years_reject_truncate BEFORE TRUNCATE ON app.gl_fiscal_years
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();

        -- Periods: dates follow the month (13 = 31 December); close in order; never reopen.
        CREATE FUNCTION app.gl_guard_period() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_year smallint;
            v_before record;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'A period is never deleted' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'INSERT' THEN
                SELECT year.fiscal_year INTO STRICT v_year FROM app.gl_fiscal_years AS year
                WHERE year.id = NEW.fiscal_year_id;
                IF NEW.status <> 'OPEN' OR NEW.closed_at IS NOT NULL OR (
                    NEW.period_no <= 12 AND (
                        NEW.starts_on <> make_date(v_year, NEW.period_no, 1)
                        OR NEW.ends_on <> (make_date(v_year, NEW.period_no, 1)
                            + interval '1 month' - interval '1 day')::date))
                    OR (NEW.period_no = 13 AND (NEW.starts_on <> make_date(v_year, 12, 31)
                        OR NEW.ends_on <> make_date(v_year, 12, 31))) THEN
                    RAISE EXCEPTION 'A period starts OPEN and covers its whole month'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.id <> OLD.id OR NEW.property_id <> OLD.property_id
                OR NEW.fiscal_year_id <> OLD.fiscal_year_id OR NEW.period_no <> OLD.period_no
                OR NEW.starts_on <> OLD.starts_on OR NEW.ends_on <> OLD.ends_on
                OR NOT (OLD.status = 'OPEN' AND NEW.status = 'CLOSED') THEN
                RAISE EXCEPTION 'A period only closes, once, and never reopens'
                    USING ERRCODE = '55000';
            END IF;
            -- The month before must already be closed (period 13 follows period 12).
            SELECT period.status INTO v_before FROM app.gl_periods AS period
            WHERE period.property_id = NEW.property_id
              AND period.period_no <> 13
              AND period.ends_on < NEW.starts_on
              AND (NEW.period_no <> 13 OR period.ends_on < NEW.starts_on)
            ORDER BY period.ends_on DESC LIMIT 1;
            IF NEW.period_no = 13 THEN
                SELECT period.status INTO v_before FROM app.gl_periods AS period
                WHERE period.fiscal_year_id = NEW.fiscal_year_id AND period.period_no = 12;
            END IF;
            IF FOUND AND v_before.status <> 'CLOSED' THEN
                RAISE EXCEPTION 'Close the month before first' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_guard_period() FROM PUBLIC;
        CREATE TRIGGER gl_periods_guard BEFORE INSERT OR UPDATE OR DELETE ON app.gl_periods
            FOR EACH ROW EXECUTE FUNCTION app.gl_guard_period();
        CREATE TRIGGER gl_periods_reject_truncate BEFORE TRUNCATE ON app.gl_periods
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_update_or_delete
            BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.gl_reject_mutation();
            CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
            """
        )
    op.execute(
        r"""
        -- Entries: an OPEN period that holds the date; period 13 only for the year-end close.
        CREATE FUNCTION app.gl_check_entry() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_period record;
            v_year_status text;
            v_reversed record;
        BEGIN
            IF NEW.created_txid <> txid_current() THEN
                RAISE EXCEPTION 'created_txid is set by the database' USING ERRCODE = '23514';
            END IF;
            SELECT period.* INTO v_period FROM app.gl_periods AS period
            WHERE period.id = NEW.period_id FOR SHARE;
            SELECT year.status INTO STRICT v_year_status FROM app.gl_fiscal_years AS year
            WHERE year.id = v_period.fiscal_year_id;
            IF v_period.status <> 'OPEN' OR v_year_status <> 'OPEN' THEN
                RAISE EXCEPTION 'Period % is closed: nothing can be dated in it',
                    pg_catalog.to_char(v_period.starts_on, 'MM/YYYY') USING ERRCODE = '55000';
            END IF;
            IF NEW.entry_date NOT BETWEEN v_period.starts_on AND v_period.ends_on THEN
                RAISE EXCEPTION 'The entry date is outside its period' USING ERRCODE = '23514';
            END IF;
            IF (NEW.entry_kind = 'YEAR_END_CLOSE') <> (v_period.period_no = 13) THEN
                RAISE EXCEPTION 'Only the year-end closing entry uses the year-end period'
                    USING ERRCODE = '23514';
            END IF;
            -- The closing entry belongs to its year, once, after every month is closed.
            IF NEW.entry_kind = 'YEAR_END_CLOSE' AND (NEW.source_type <> 'FISCAL_YEAR'
                    OR NEW.source_id IS DISTINCT FROM v_period.fiscal_year_id) THEN
                RAISE EXCEPTION 'The year-end closing entry names its fiscal year'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.entry_kind = 'YEAR_END_CLOSE' AND EXISTS (
                SELECT 1 FROM app.gl_periods AS month
                WHERE month.fiscal_year_id = v_period.fiscal_year_id AND month.period_no <= 12
                  AND month.status <> 'CLOSED') THEN
                RAISE EXCEPTION 'Close every month of the year before the year-end close'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.reverses_entry_id IS NOT NULL THEN
                SELECT entry.property_id, entry.entry_kind INTO v_reversed
                FROM app.gl_journal_entries AS entry WHERE entry.id = NEW.reverses_entry_id;
                IF NOT FOUND OR v_reversed.property_id <> NEW.property_id
                    OR v_reversed.entry_kind IN ('REVERSAL','YEAR_END_CLOSE') THEN
                    RAISE EXCEPTION 'This entry cannot be reversed' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_check_entry() FROM PUBLIC;
        CREATE TRIGGER gl_journal_entries_check BEFORE INSERT ON app.gl_journal_entries
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_entry();

        -- Lines: same transaction as the entry; a usable account; control and tax rules.
        CREATE FUNCTION app.gl_check_line() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_entry record;
            v_account record;
            v_reversed_kind text;
        BEGIN
            SELECT entry.created_txid, entry.entry_kind, entry.reverses_entry_id INTO v_entry
            FROM app.gl_journal_entries AS entry WHERE entry.id = NEW.entry_id;
            IF NOT FOUND OR v_entry.created_txid <> txid_current() THEN
                RAISE EXCEPTION 'Lines are written only with their entry, in one step'
                    USING ERRCODE = '55000';
            END IF;
            SELECT account.code, account.is_active, account.is_postable, account.is_tax_locked,
                account.control_source INTO STRICT v_account
            FROM app.gl_accounts AS account WHERE account.id = NEW.account_id;
            IF NOT v_account.is_active OR NOT v_account.is_postable THEN
                RAISE EXCEPTION 'Account % is turned off or a heading', v_account.code
                    USING ERRCODE = '23514';
            END IF;
            IF v_account.is_tax_locked THEN
                RAISE EXCEPTION 'Account % takes no entries until a tax agent confirms the rules',
                    v_account.code USING ERRCODE = '23514';
            END IF;
            IF v_account.control_source IS NOT NULL THEN
                IF v_entry.entry_kind = 'REVERSAL' THEN
                    SELECT entry.entry_kind INTO v_reversed_kind FROM app.gl_journal_entries AS
                        entry
                    WHERE entry.id = v_entry.reverses_entry_id;
                ELSE
                    v_reversed_kind := v_entry.entry_kind;
                END IF;
                IF v_reversed_kind NOT IN ('AUTO','RENT_TO_INCOME') THEN
                    RAISE EXCEPTION 'Account % changes only through app records', v_account.code
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_check_line() FROM PUBLIC;
        CREATE TRIGGER gl_journal_lines_check BEFORE INSERT ON app.gl_journal_lines
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_line();

        -- At commit: 2+ lines, debits = credits > 0, and a reversal mirrors what it reverses.
        CREATE FUNCTION app.gl_check_entry_balanced() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_lines integer;
            v_debit numeric;
            v_credit numeric;
        BEGIN
            SELECT count(*), coalesce(sum(line.debit_cents), 0), coalesce(sum(line.credit_cents), 0)
            INTO v_lines, v_debit, v_credit
            FROM app.gl_journal_lines AS line WHERE line.entry_id = NEW.id;
            IF v_lines < 2 OR v_debit <> v_credit OR v_debit = 0 THEN
                RAISE EXCEPTION 'Entry % does not balance: debits %, credits %, lines %',
                    NEW.entry_number, v_debit, v_credit, v_lines USING ERRCODE = '23514';
            END IF;
            IF NEW.reverses_entry_id IS NOT NULL AND EXISTS (
                (SELECT line.account_id, line.credit_cents, line.debit_cents
                 FROM app.gl_journal_lines AS line WHERE line.entry_id = NEW.reverses_entry_id
                 EXCEPT ALL
                 SELECT line.account_id, line.debit_cents, line.credit_cents
                 FROM app.gl_journal_lines AS line WHERE line.entry_id = NEW.id)
                UNION ALL
                (SELECT line.account_id, line.debit_cents, line.credit_cents
                 FROM app.gl_journal_lines AS line WHERE line.entry_id = NEW.id
                 EXCEPT ALL
                 SELECT line.account_id, line.credit_cents, line.debit_cents
                 FROM app.gl_journal_lines AS line WHERE line.entry_id = NEW.reverses_entry_id)
            ) THEN
                RAISE EXCEPTION 'Reversal % must mirror the entry it reverses', NEW.entry_number
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_check_entry_balanced() FROM PUBLIC;
        CREATE CONSTRAINT TRIGGER gl_journal_entries_balanced
            AFTER INSERT ON app.gl_journal_entries DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_entry_balanced();
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION app.gl_open_fiscal_year(p_property uuid, p_year smallint, p_actor uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_year uuid;
        BEGIN
            SELECT year.id INTO v_year FROM app.gl_fiscal_years AS year
            WHERE year.property_id = p_property AND year.fiscal_year = p_year;
            IF FOUND THEN
                RETURN v_year;
            END IF;
            v_year := gen_random_uuid();
            INSERT INTO app.gl_fiscal_years (id, property_id, fiscal_year, starts_on, ends_on,
                created_by)
            VALUES (v_year, p_property, p_year, make_date(p_year, 1, 1), make_date(p_year, 12, 31),
                p_actor);
            INSERT INTO app.gl_periods (id, fiscal_year_id, property_id, period_no, starts_on,
                ends_on)
            SELECT gen_random_uuid(), v_year, p_property, month_no::smallint,
                make_date(p_year, month_no, 1),
                (make_date(p_year, month_no, 1) + interval '1 month' - interval '1 day')::date
            FROM generate_series(1, 12) AS month_no;
            INSERT INTO app.gl_periods (id, fiscal_year_id, property_id, period_no, starts_on,
                ends_on)
            VALUES (gen_random_uuid(), v_year, p_property, 13, make_date(p_year, 12, 31),
                make_date(p_year, 12, 31));
            RETURN v_year;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_open_fiscal_year(uuid, smallint, uuid) FROM PUBLIC;

        -- One way in: header and lines in one step. A known posting key returns the first entry.
        -- p_lines: [{"account": "1010", "debit_cents": 100} | {"account": "4010",
        --   "credit_cents": 100, "memo": ..., "customer_id": ..., "lease_id": ..., "unit_id": ...,
        --   "supplier_id": ..., "expense_request_id": ..., "fixed_asset_id": ..., "employee_id":
            -- ...,
        --   "maintenance_request_id": ..., "original_currency": "KHR",
        --   "original_amount_minor": ..., "exchange_rate_record_id": ...}, ...]
        CREATE FUNCTION app.gl_post_entry(
            p_property uuid, p_entry_date date, p_kind text, p_description text,
            p_source_type text, p_source_id uuid, p_posting_key text, p_reason text,
            p_actor uuid, p_approved_by uuid, p_correlation uuid, p_lines jsonb,
            p_reverses uuid DEFAULT NULL)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_existing record;
            v_period uuid;
            v_entry uuid;
            v_line jsonb;
            v_no integer := 0;
            v_debit numeric := 0;
            v_credit numeric := 0;
            v_account uuid;
        BEGIN
            SELECT entry.id, entry.property_id INTO v_existing FROM app.gl_journal_entries AS entry
            WHERE entry.posting_key = p_posting_key;
            IF FOUND THEN
                IF v_existing.property_id <> p_property THEN
                    RAISE EXCEPTION 'Posting key belongs to another Property' USING ERRCODE =
                        '23505';
                END IF;
                RETURN v_existing.id;
            END IF;
            IF jsonb_typeof(p_lines) <> 'array' OR jsonb_array_length(p_lines) < 2 THEN
                RAISE EXCEPTION 'An entry needs two or more lines' USING ERRCODE = '22023';
            END IF;
            FOR v_line IN SELECT value FROM jsonb_array_elements(p_lines) LOOP
                v_debit := v_debit + coalesce((v_line ->> 'debit_cents')::bigint, 0);
                v_credit := v_credit + coalesce((v_line ->> 'credit_cents')::bigint, 0);
            END LOOP;
            IF v_debit <> v_credit OR v_debit = 0 THEN
                RAISE EXCEPTION 'Debits (% cents) must equal credits (% cents)', v_debit, v_credit
                    USING ERRCODE = '22023';
            END IF;
            SELECT period.id INTO v_period FROM app.gl_periods AS period
            WHERE period.property_id = p_property
              AND p_entry_date BETWEEN period.starts_on AND period.ends_on
              AND (period.period_no = 13) = (p_kind = 'YEAR_END_CLOSE');
            IF NOT FOUND THEN
                RAISE EXCEPTION 'No ledger period holds %', p_entry_date USING ERRCODE = '22023';
            END IF;
            v_entry := gen_random_uuid();
            INSERT INTO app.gl_journal_entries (id, property_id, entry_number, entry_date,
                period_id,
                entry_kind, description, source_type, source_id, posting_key, reverses_entry_id,
                reason, posted_by, approved_by, correlation_id)
            VALUES (v_entry, p_property, app.gl_next_number(p_property, 'JE', p_entry_date),
                p_entry_date, v_period, p_kind, p_description, p_source_type, p_source_id,
                p_posting_key, p_reverses, p_reason, p_actor, p_approved_by, p_correlation);
            FOR v_line IN SELECT value FROM jsonb_array_elements(p_lines) LOOP
                v_no := v_no + 1;
                SELECT account.id INTO v_account FROM app.gl_accounts AS account
                WHERE account.property_id = p_property AND account.code = v_line ->> 'account';
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'No account %', v_line ->> 'account' USING ERRCODE = '22023';
                END IF;
                INSERT INTO app.gl_journal_lines (id, entry_id, property_id, line_no, account_id,
                    debit_cents, credit_cents, memo, customer_id, lease_id, unit_id, supplier_id,
                    expense_request_id, fixed_asset_id, employee_id, maintenance_request_id,
                    original_currency, original_amount_minor, exchange_rate_record_id)
                VALUES (gen_random_uuid(), v_entry, p_property, v_no, v_account,
                    coalesce((v_line ->> 'debit_cents')::bigint, 0),
                    coalesce((v_line ->> 'credit_cents')::bigint, 0),
                    v_line ->> 'memo', (v_line ->> 'customer_id')::uuid,
                    (v_line ->> 'lease_id')::uuid, (v_line ->> 'unit_id')::uuid,
                    (v_line ->> 'supplier_id')::uuid, (v_line ->> 'expense_request_id')::uuid,
                    (v_line ->> 'fixed_asset_id')::uuid, (v_line ->> 'employee_id')::uuid,
                    (v_line ->> 'maintenance_request_id')::uuid,
                    coalesce(v_line ->> 'original_currency', 'USD'),
                    (v_line ->> 'original_amount_minor')::bigint,
                    (v_line ->> 'exchange_rate_record_id')::uuid);
            END LOOP;
            IF p_kind IN ('ADJUSTING','OPENING','REVERSAL','YEAR_END_CLOSE') THEN
                PERFORM app.gl_audit(p_property, p_actor, 'ledger.entry.' || lower(p_kind),
                    'gl_journal_entry', v_entry, coalesce(p_reason, p_description), p_correlation,
                    jsonb_build_object('posting_key', p_posting_key, 'entry_date', p_entry_date,
                        'total_cents', v_debit, 'reverses_entry_id', p_reverses));
            END IF;
            RETURN v_entry;
        END
        $$;

        CREATE FUNCTION app.gl_audit(p_property uuid, p_actor uuid, p_action text,
            p_entity_type text, p_entity uuid, p_reason text, p_correlation uuid, p_state jsonb)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_timezone text;
            v_at timestamptz := statement_timestamp();
        BEGIN
            SELECT property.timezone_name INTO STRICT v_timezone FROM app.properties AS property
            WHERE property.id = p_property;
            INSERT INTO app.audit_events (id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                resulting_state, correlation_id, source, outcome)
            VALUES (gen_random_uuid(), v_at, timezone(v_timezone, v_at)::date, p_actor, p_action,
                p_entity_type, p_entity, p_reason, NULL, p_property, p_state, p_correlation,
                'API', 'SUCCEEDED');
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_audit(uuid, uuid, text, text, uuid, text, uuid, jsonb)
            FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.gl_post_entry(uuid, date, text, text, text, uuid, text, text,
            uuid, uuid, uuid, jsonb, uuid) FROM PUBLIC;

        -- A correction: every line on the other side, linked to the first entry.
        CREATE FUNCTION app.gl_reverse_entry(p_entry uuid, p_date date, p_reason text,
            p_actor uuid, p_posting_key text, p_correlation uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_first record;
            v_lines jsonb;
        BEGIN
            SELECT entry.* INTO v_first FROM app.gl_journal_entries AS entry WHERE entry.id =
                p_entry;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'No entry to reverse' USING ERRCODE = '22023';
            END IF;
            SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                    'account', account.code,
                    'debit_cents', nullif(line.credit_cents, 0),
                    'credit_cents', nullif(line.debit_cents, 0),
                    'memo', line.memo, 'customer_id', line.customer_id, 'lease_id', line.lease_id,
                    'unit_id', line.unit_id, 'supplier_id', line.supplier_id,
                    'expense_request_id', line.expense_request_id,
                    'fixed_asset_id', line.fixed_asset_id, 'employee_id', line.employee_id,
                    'maintenance_request_id', line.maintenance_request_id,
                    'original_currency', line.original_currency,
                    'original_amount_minor', line.original_amount_minor,
                    'exchange_rate_record_id', line.exchange_rate_record_id))
                    ORDER BY line.line_no)
            INTO v_lines
            FROM app.gl_journal_lines AS line JOIN app.gl_accounts AS account
              ON account.id = line.account_id
            WHERE line.entry_id = p_entry;
            RETURN app.gl_post_entry(v_first.property_id, p_date, 'REVERSAL',
                'Reversal of ' || v_first.entry_number, v_first.source_type, v_first.source_id,
                p_posting_key, p_reason, p_actor, NULL, p_correlation, v_lines, p_entry);
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_reverse_entry(uuid, date, text, uuid, text, uuid) FROM PUBLIC;

        -- Month-end close: every check must be true; the lock stops a post crossing the close.
        CREATE FUNCTION app.gl_close_period(p_period uuid, p_actor uuid, p_checks jsonb)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_period record;
        BEGIN
            SELECT period.* INTO v_period FROM app.gl_periods AS period
            WHERE period.id = p_period FOR UPDATE;
            IF NOT FOUND OR v_period.period_no = 13 THEN
                RAISE EXCEPTION 'No month to close' USING ERRCODE = '22023';
            END IF;
            IF jsonb_typeof(p_checks) <> 'object' OR p_checks = '{}'::jsonb OR EXISTS (
                SELECT 1 FROM jsonb_each(p_checks) AS item WHERE item.value <> 'true'::jsonb) THEN
                RAISE EXCEPTION 'A month closes only when every check is green'
                    USING ERRCODE = '55000';
            END IF;
            UPDATE app.gl_periods SET status = 'CLOSED', closed_at = statement_timestamp(),
                closed_by = p_actor, close_checks = p_checks
            WHERE id = p_period;
            PERFORM app.gl_audit(v_period.property_id, p_actor, 'ledger.period.closed',
                'gl_period', p_period, 'Month-end close', gen_random_uuid(),
                jsonb_build_object('starts_on', v_period.starts_on, 'checks', p_checks));
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_close_period(uuid, uuid, jsonb) FROM PUBLIC;

        -- Year-end close (PR-GL-051): income, cost and expense balances move into 3900 on
        -- 31 December in period 13; then period 13 and the year close.
        CREATE FUNCTION app.gl_close_year(p_year uuid, p_actor uuid, p_reason text)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_year record;
            v_lines jsonb;
            v_profit numeric;
            v_retained text;
            v_entry uuid;
            v_last uuid;
        BEGIN
            SELECT year.* INTO v_year FROM app.gl_fiscal_years AS year WHERE year.id = p_year
            FOR UPDATE;
            IF NOT FOUND OR v_year.status <> 'OPEN' THEN
                RAISE EXCEPTION 'No open year to close' USING ERRCODE = '22023';
            END IF;
            IF EXISTS (SELECT 1 FROM app.gl_periods AS period WHERE period.fiscal_year_id = p_year
                       AND period.period_no <= 12 AND period.status <> 'CLOSED') THEN
                RAISE EXCEPTION 'Close every month of % first', v_year.fiscal_year
                    USING ERRCODE = '55000';
            END IF;
            SELECT account.code INTO v_retained FROM app.gl_accounts AS account
            WHERE account.property_id = v_year.property_id AND account.is_retained_earnings;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'No account for profit kept from past years'
                    USING ERRCODE = '22023';
            END IF;
            WITH balances AS (
                SELECT account.code, sum(line.debit_cents - line.credit_cents) AS net
                FROM app.gl_journal_lines AS line
                JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                JOIN app.gl_accounts AS account ON account.id = line.account_id
                WHERE entry.property_id = v_year.property_id
                  AND entry.entry_date BETWEEN v_year.starts_on AND v_year.ends_on
                  AND account.account_type IN ('INCOME','COST_OF_SALES','EXPENSE')
                GROUP BY account.code HAVING sum(line.debit_cents - line.credit_cents) <> 0
            )
            SELECT jsonb_agg(CASE WHEN net > 0
                    THEN jsonb_build_object('account', code, 'credit_cents', net)
                    ELSE jsonb_build_object('account', code, 'debit_cents', -net) END
                    ORDER BY code),
                coalesce(sum(-net), 0)
            INTO v_lines, v_profit FROM balances;
            IF v_lines IS NOT NULL THEN
                v_lines := v_lines || CASE WHEN v_profit > 0
                    THEN jsonb_build_object('account', v_retained, 'credit_cents', v_profit)
                    WHEN v_profit < 0
                    THEN jsonb_build_object('account', v_retained, 'debit_cents', -v_profit)
                    ELSE '[]'::jsonb END;
                v_entry := app.gl_post_entry(v_year.property_id, v_year.ends_on, 'YEAR_END_CLOSE',
                    'Year-end close ' || v_year.fiscal_year, 'FISCAL_YEAR', p_year,
                    'fiscal_year:' || p_year || ':' || 'close', coalesce(p_reason,
                        'Year-end close'),
                    p_actor, NULL, gen_random_uuid(), v_lines);
            END IF;
            SELECT period.id INTO STRICT v_last FROM app.gl_periods AS period
            WHERE period.fiscal_year_id = p_year AND period.period_no = 13;
            UPDATE app.gl_periods SET status = 'CLOSED', closed_at = statement_timestamp(),
                closed_by = p_actor, close_checks = jsonb_build_object('year_end_close', true)
            WHERE id = v_last;
            UPDATE app.gl_fiscal_years SET status = 'CLOSED', closed_at = statement_timestamp(),
                closed_by = p_actor, closing_entry_id = v_entry
            WHERE id = p_year;
            PERFORM app.gl_audit(v_year.property_id, p_actor, 'ledger.year.closed',
                'gl_fiscal_year', p_year, coalesce(p_reason, 'Year-end close'), gen_random_uuid(),
                jsonb_build_object('fiscal_year', v_year.fiscal_year, 'profit_cents', v_profit,
                    'closing_entry_id', v_entry));
            RETURN v_entry;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_close_year(uuid, uuid, text) FROM PUBLIC;
        """
    )
    for table in READ_TABLES:
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime, prm_financial")


def downgrade() -> None:
    """Remove only the ledger core, and only while no entry has ever been posted (owner Q2)."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.gl_journal_entries) THEN
                RAISE EXCEPTION 'The ledger has posted entries: it cannot be rolled back'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$;
        DROP FUNCTION app.gl_close_year(uuid, uuid, text);
        DROP FUNCTION app.gl_close_period(uuid, uuid, jsonb);
        DROP FUNCTION app.gl_reverse_entry(uuid, date, text, uuid, text, uuid);
        DROP FUNCTION app.gl_post_entry(uuid, date, text, text, text, uuid, text, text, uuid, uuid,
            uuid, jsonb, uuid);
        DROP FUNCTION app.gl_audit(uuid, uuid, text, text, uuid, text, uuid, jsonb);
        DROP FUNCTION app.gl_open_fiscal_year(uuid, smallint, uuid);
        ALTER TABLE app.gl_fiscal_years DROP CONSTRAINT gl_fiscal_years_closing_entry_fkey;
        DROP TABLE app.gl_journal_lines;
        DROP TABLE app.gl_journal_entries;
        DROP TABLE app.gl_periods;
        DROP TABLE app.gl_fiscal_years;
        DROP TABLE app.gl_method_accounts;
        DROP TABLE app.gl_suppliers;
        DROP TABLE app.gl_accounts;
        DROP TABLE app.gl_number_counters;
        DROP FUNCTION app.gl_check_entry_balanced();
        DROP FUNCTION app.gl_check_line();
        DROP FUNCTION app.gl_check_entry();
        DROP FUNCTION app.gl_guard_period();
        DROP FUNCTION app.gl_guard_fiscal_year();
        DROP FUNCTION app.gl_check_method_account();
        DROP FUNCTION app.gl_guard_supplier();
        DROP FUNCTION app.gl_guard_account();
        DROP FUNCTION app.gl_next_number(uuid, text, date);
        DROP FUNCTION app.gl_reject_mutation();
        """
    )
