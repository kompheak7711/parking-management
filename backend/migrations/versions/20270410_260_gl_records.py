"""General Ledger records: expenses, bills, money moves, assets, adjustments, close (PR-GL).

Revision ID: 20270410_260
Revises: 20270409_259
Create Date: 2026-11-02

Owner approved the ledger database plan on 2026-11-02 21:08
(https://claude.ai/artifact/5nttjeU5y5SaNSHU1etyuK, section 3.4). Every table is new; no
existing table changes. Each record keeps who and when; money is whole cents in ``bigint``.

- ``gl_expense_requests`` + ``gl_expense_request_events`` (ER): a request before spending,
  or an urgent report after it. Nobody decides their own request, except the Owner's own
  spending kept with a note (D4). A Unit only on an account that allows one. Never edited;
  each step is an event; void with a reason.
- ``gl_expenses`` (EX): posted with its entry; void = a reversal entry.
- ``gl_supplier_bills`` + ``gl_bill_payments`` + ``gl_bill_payment_reversals`` (SB): payments
  never more than the bill.
- ``gl_money_moves`` (MV): between two different cash or bank accounts.
- ``gl_owner_money``, ``gl_petty_cash_topups``.
- ``gl_write_offs``: marks a confirmed V1 CHARGE_REDUCTION correction as a write-off (Q5);
  the posting job posts it to 6160.
- ``gl_fixed_assets`` (FA): depreciation starts the month after purchase (decision 25).
- ``gl_adjusting_entries`` + lines (AJ): no control or tax account; the approver is never the
  preparer (D5).
- ``gl_opening_balances`` + lines: one batch per Property; no control account.
- ``gl_budgets`` + lines: an approved budget is locked; a change is a new version (D3).
- ``gl_bank_reconciliations`` + items, ``gl_cash_counts``, ``gl_fx_revaluations``,
  ``gl_close_runs`` (append-only, every close try with each check result).

Status changes follow fixed steps (``app.gl_guard_record``); other fields change only with
a step. Limits (Expense limit, petty cash amount, asset limit, budget warning) stay in the
business rules and are checked by the coding phase, never here.

Downgrade removes only these objects and refuses once any ledger record or entry exists.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270410_260"
down_revision: str | None = "20270409_259"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = "id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid)"
PROPERTY = "property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT"
CREATED = (
    "created_at timestamptz NOT NULL DEFAULT statement_timestamp(),\n"
    "            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id)"
    " ON DELETE RESTRICT"
)
CENTS = "bigint NOT NULL CHECK ({0} BETWEEN 1 AND 9000000000000000)"
ENTRY = "uuid UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT"
ACTOR = "uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT"
RIEL = (
    "original_currency text NOT NULL DEFAULT 'USD' CHECK (original_currency IN ('USD','KHR')),\n"
    "            original_amount_minor bigint CHECK (original_amount_minor BETWEEN 1 AND "
    "9000000000000000),\n"
    "            exchange_rate_record_id uuid REFERENCES app.exchange_rate_records(id)"
    " ON DELETE RESTRICT"
)


def riel_check(table: str) -> str:
    return (
        f"CONSTRAINT {table}_riel CHECK ((original_currency = 'USD' AND original_amount_minor "
        "IS NULL AND exchange_rate_record_id IS NULL) OR (original_currency = 'KHR' AND "
        "original_amount_minor IS NOT NULL AND exchange_rate_record_id IS NOT NULL))"
    )


def account_fk(table: str, column: str) -> str:
    return (
        f"CONSTRAINT {table}_{column}_fkey FOREIGN KEY ({column}, property_id)\n"
        "                REFERENCES app.gl_accounts(id, property_id) ON DELETE RESTRICT"
    )


def number(column: str, series: str) -> str:
    return f"{column} text NOT NULL UNIQUE CHECK ({column} ~ '^{series}[0-9]{{6,}}$')"


# (table, free columns, first statuses, allowed steps)
STATUS_TABLES = (
    (
        "gl_expense_requests",
        "status decided_by decided_at decision_note own_spending_note paid_from_account_id "
        "paid_out_entry_id void_reason voided_at voided_by",
        "WAITING",
        (
            "WAITING>APPROVED",
            "WAITING>REFUSED",
            "WAITING>VOID",
            "APPROVED>PAID_OUT",
            "APPROVED>DONE",
            "APPROVED>VOID",
            "PAID_OUT>DONE",
        ),
    ),
    (
        "gl_expenses",
        "status void_entry_id void_reason voided_at voided_by",
        "POSTED",
        ("POSTED>VOID",),
    ),
    (
        "gl_supplier_bills",
        "status void_reason voided_at voided_by",
        "OPEN",
        ("OPEN>PAID", "OPEN>VOID", "PAID>OPEN"),
    ),
    (
        "gl_fixed_assets",
        "status disposed_on disposal_entry_id",
        "IN_USE",
        ("IN_USE>DISPOSED",),
    ),
    (
        "gl_adjusting_entries",
        "status decided_by decided_at decision_note entry_id",
        "WAITING",
        ("WAITING>POSTED", "WAITING>REFUSED", "WAITING>VOID"),
    ),
    (
        "gl_opening_balances",
        "status entry_id posted_by posted_at",
        "DRAFT",
        ("DRAFT>POSTED",),
    ),
    (
        "gl_budgets",
        "status approved_by approved_at",
        "DRAFT",
        ("DRAFT>APPROVED", "DRAFT>REPLACED", "APPROVED>REPLACED"),
    ),
    (
        "gl_bank_reconciliations",
        "status matched_by matched_at",
        "OPEN",
        ("OPEN>MATCHED",),
    ),
)
APPEND_ONLY_TABLES = (
    "gl_expense_request_events",
    "gl_bill_payments",
    "gl_bill_payment_reversals",
    "gl_money_moves",
    "gl_owner_money",
    "gl_petty_cash_topups",
    "gl_write_offs",
    "gl_adjusting_entry_lines",
    "gl_bank_reconciliation_items",
    "gl_cash_counts",
    "gl_fx_revaluations",
    "gl_close_runs",
)
# Lines of a draft change only while their batch is still a draft.
DRAFT_LINE_TABLES = ("gl_opening_balance_lines", "gl_budget_lines")
TABLES = (
    "gl_expense_requests",
    "gl_expense_request_events",
    "gl_expenses",
    "gl_supplier_bills",
    "gl_bill_payments",
    "gl_bill_payment_reversals",
    "gl_money_moves",
    "gl_owner_money",
    "gl_petty_cash_topups",
    "gl_write_offs",
    "gl_fixed_assets",
    "gl_adjusting_entries",
    "gl_adjusting_entry_lines",
    "gl_opening_balances",
    "gl_opening_balance_lines",
    "gl_budgets",
    "gl_budget_lines",
    "gl_bank_reconciliations",
    "gl_bank_reconciliation_items",
    "gl_cash_counts",
    "gl_fx_revaluations",
    "gl_close_runs",
)
# (table, columns that must name a cash or bank account, kind it must be or NULL)
CASH_COLUMNS = (
    ("gl_expense_requests", "paid_from_account_id", None),
    ("gl_expenses", "paid_from_account_id", None),
    ("gl_bill_payments", "paid_from_account_id", None),
    ("gl_money_moves", "from_account_id to_account_id", None),
    ("gl_owner_money", "account_id", None),
    ("gl_petty_cash_topups", "from_account_id", None),
    ("gl_bank_reconciliations", "account_id", "BANK"),
    ("gl_cash_counts", "account_id", None),
    ("gl_fx_revaluations", "account_id", "CASH_KHR"),
)


def upgrade() -> None:
    op.execute(
        r"""
        -- Status steps: TG_ARGV[0] = the columns that may change (with a step), [1] = the
        -- first statuses, [2..] = the allowed steps 'FROM>TO'. Never deleted.
        CREATE FUNCTION app.gl_guard_record() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_free text[] := string_to_array(TG_ARGV[0], ' ');
            v_new jsonb := to_jsonb(NEW);
            v_old jsonb;
            v_step text;
            i integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'A ledger record is never deleted; void it instead'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NOT (v_new ->> 'status') = ANY (string_to_array(TG_ARGV[1], ' ')) THEN
                    RAISE EXCEPTION 'A new % starts as %', TG_TABLE_NAME, TG_ARGV[1]
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            v_old := to_jsonb(OLD);
            IF (v_new - v_free) <> (v_old - v_free) THEN
                RAISE EXCEPTION 'This % field cannot change', TG_TABLE_NAME USING ERRCODE = '55000';
            END IF;
            IF v_new = v_old THEN
                RETURN NEW;
            END IF;
            v_step := (v_old ->> 'status') || '>' || (v_new ->> 'status');
            FOR i IN 2 .. TG_NARGS - 1 LOOP
                IF TG_ARGV[i] = v_step THEN
                    RETURN NEW;
                END IF;
            END LOOP;
            RAISE EXCEPTION 'A % cannot go from % to %', TG_TABLE_NAME, v_old ->> 'status',
                v_new ->> 'status' USING ERRCODE = '55000';
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_guard_record() FROM PUBLIC;

        -- Cash columns: TG_ARGV[0] = column names, TG_ARGV[1] = the cash kind or ''.
        -- A Unit only on an account that allows one (column account_id + unit_id).
        CREATE FUNCTION app.gl_check_record_accounts() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_new jsonb := to_jsonb(NEW);
            v_column text;
            v_kind text;
        BEGIN
            FOREACH v_column IN ARRAY string_to_array(TG_ARGV[0], ' ') LOOP
                CONTINUE WHEN v_new ->> v_column IS NULL;
                SELECT account.cash_kind INTO v_kind FROM app.gl_accounts AS account
                WHERE account.id = (v_new ->> v_column)::uuid;
                IF v_kind IS NULL OR (TG_ARGV[1] <> '' AND v_kind <> TG_ARGV[1]) THEN
                    RAISE EXCEPTION 'The % must be a % account', v_column,
                        CASE WHEN TG_ARGV[1] = '' THEN 'cash or bank' ELSE TG_ARGV[1] END
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;
            IF v_new ? 'unit_id' AND v_new ->> 'unit_id' IS NOT NULL AND v_new ? 'account_id'
                AND NOT EXISTS (SELECT 1 FROM app.gl_accounts AS account
                                WHERE account.id = (v_new ->> 'account_id')::uuid
                                  AND (account.allows_unit OR account.account_type = 'ASSET')) THEN
                RAISE EXCEPTION 'This account does not take a Unit' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_check_record_accounts() FROM PUBLIC;
        """
    )
    op.execute(
        f"""
        CREATE TABLE app.gl_expense_requests (
            {ID},
            {PROPERTY},
            {number("request_number", "ER")},
            request_kind text NOT NULL CHECK (request_kind IN ('REQUEST','URGENT_REPORT')),
            requested_by uuid NOT NULL REFERENCES app.actor_identities(actor_id)
                ON DELETE RESTRICT,
            account_id uuid NOT NULL,
            description text NOT NULL CHECK (length(btrim(description)) BETWEEN 1 AND 500),
            reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
            amount_cents {CENTS.format("amount_cents")},
            {RIEL},
            supplier_id uuid REFERENCES app.gl_suppliers(id) ON DELETE RESTRICT,
            unit_id uuid REFERENCES app.units(id) ON DELETE RESTRICT,
            spent_on date,
            status text NOT NULL CHECK (status IN
                ('WAITING','APPROVED','REFUSED','PAID_OUT','DONE','VOID')),
            decided_by {ACTOR},
            decided_at timestamptz,
            decision_note text CHECK (decision_note IS NULL
                OR length(btrim(decision_note)) BETWEEN 1 AND 1000),
            own_spending_note text CHECK (own_spending_note IS NULL
                OR length(btrim(own_spending_note)) BETWEEN 1 AND 1000),
            paid_from_account_id uuid,
            paid_out_entry_id {ENTRY},
            void_reason text CHECK (void_reason IS NULL
                OR length(btrim(void_reason)) BETWEEN 1 AND 1000),
            voided_at timestamptz,
            voided_by {ACTOR},
            {CREATED},
            {account_fk("gl_er", "account_id")},
            {account_fk("gl_er", "paid_from_account_id")},
            {riel_check("gl_er")},
            CONSTRAINT gl_er_urgent_spent CHECK ((request_kind = 'URGENT_REPORT') = (spent_on IS
                NOT NULL)),
            CONSTRAINT gl_er_decided CHECK ((status IN ('WAITING','VOID'))
                OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)),
            CONSTRAINT gl_er_refused_note CHECK (status <> 'REFUSED' OR decision_note IS NOT NULL),
            CONSTRAINT gl_er_not_own CHECK (decided_by IS DISTINCT FROM requested_by
                OR own_spending_note IS NOT NULL),
            CONSTRAINT gl_er_paid_out CHECK ((status = 'PAID_OUT' OR paid_out_entry_id IS NULL)
                OR status = 'DONE'),
            CONSTRAINT gl_er_void CHECK ((status = 'VOID') =
                (void_reason IS NOT NULL AND voided_at IS NOT NULL AND voided_by IS NOT NULL))
        );
        CREATE INDEX gl_er_status_idx ON app.gl_expense_requests(property_id, status, created_at);
        CREATE INDEX gl_er_requested_by_idx ON app.gl_expense_requests(requested_by);
        CREATE INDEX gl_er_account_idx ON app.gl_expense_requests(account_id);

        CREATE TABLE app.gl_expense_request_events (
            {ID},
            expense_request_id uuid NOT NULL REFERENCES app.gl_expense_requests(id)
                ON DELETE RESTRICT,
            step text NOT NULL CHECK (step IN
                ('SUBMITTED','APPROVED','REFUSED','PAID_OUT','BILL_BACK','DONE','VOID')),
            note text CHECK (note IS NULL OR length(btrim(note)) BETWEEN 1 AND 1000),
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT
        );
        CREATE INDEX gl_er_events_request_idx
            ON app.gl_expense_request_events(expense_request_id, occurred_at);

        CREATE TABLE app.gl_expenses (
            {ID},
            {PROPERTY},
            {number("expense_number", "EX")},
            expense_date date NOT NULL,
            supplier_id uuid REFERENCES app.gl_suppliers(id) ON DELETE RESTRICT,
            account_id uuid NOT NULL,
            description text NOT NULL CHECK (length(btrim(description)) BETWEEN 1 AND 500),
            amount_cents {CENTS.format("amount_cents")},
            {RIEL},
            paid_from_account_id uuid,
            bill_number text CHECK (bill_number IS NULL OR length(btrim(bill_number)) BETWEEN 1 AND
                100),
            expense_request_id uuid REFERENCES app.gl_expense_requests(id) ON DELETE RESTRICT,
            unit_id uuid REFERENCES app.units(id) ON DELETE RESTRICT,
            entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT,
            status text NOT NULL CHECK (status IN ('POSTED','VOID')),
            void_entry_id {ENTRY},
            void_reason text CHECK (void_reason IS NULL OR length(btrim(void_reason)) BETWEEN 1 AND
                1000),
            voided_at timestamptz,
            voided_by {ACTOR},
            {CREATED},
            {account_fk("gl_ex", "account_id")},
            {account_fk("gl_ex", "paid_from_account_id")},
            {riel_check("gl_ex")},
            CONSTRAINT gl_ex_void CHECK ((status = 'VOID') = (void_entry_id IS NOT NULL
                AND void_reason IS NOT NULL AND voided_at IS NOT NULL AND voided_by IS NOT NULL))
        );
        CREATE INDEX gl_ex_date_idx ON app.gl_expenses(property_id, expense_date);
        CREATE INDEX gl_ex_request_idx ON app.gl_expenses(expense_request_id)
            WHERE expense_request_id IS NOT NULL;
        CREATE INDEX gl_ex_supplier_idx ON app.gl_expenses(supplier_id) WHERE supplier_id IS NOT
            NULL;

        CREATE TABLE app.gl_supplier_bills (
            {ID},
            {PROPERTY},
            {number("bill_number", "SB")},
            supplier_id uuid NOT NULL REFERENCES app.gl_suppliers(id) ON DELETE RESTRICT,
            supplier_reference text CHECK (supplier_reference IS NULL
                OR length(btrim(supplier_reference)) BETWEEN 1 AND 100),
            bill_date date NOT NULL,
            due_date date NOT NULL,
            amount_cents {CENTS.format("amount_cents")},
            expense_id uuid UNIQUE REFERENCES app.gl_expenses(id) ON DELETE RESTRICT,
            status text NOT NULL CHECK (status IN ('OPEN','PAID','VOID')),
            void_reason text CHECK (void_reason IS NULL OR length(btrim(void_reason)) BETWEEN 1 AND
                1000),
            voided_at timestamptz,
            voided_by {ACTOR},
            {CREATED},
            CONSTRAINT gl_sb_due CHECK (due_date >= bill_date),
            CONSTRAINT gl_sb_void CHECK ((status = 'VOID') =
                (void_reason IS NOT NULL AND voided_at IS NOT NULL AND voided_by IS NOT NULL))
        );
        CREATE INDEX gl_sb_due_idx ON app.gl_supplier_bills(property_id, status, due_date);
        CREATE INDEX gl_sb_supplier_idx ON app.gl_supplier_bills(supplier_id);

        CREATE TABLE app.gl_bill_payments (
            {ID},
            {PROPERTY},
            supplier_bill_id uuid NOT NULL REFERENCES app.gl_supplier_bills(id) ON DELETE RESTRICT,
            paid_on date NOT NULL,
            amount_cents {CENTS.format("amount_cents")},
            paid_from_account_id uuid NOT NULL,
            entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT,
            {CREATED},
            {account_fk("gl_bp", "paid_from_account_id")}
        );
        CREATE INDEX gl_bp_bill_idx ON app.gl_bill_payments(supplier_bill_id);

        CREATE TABLE app.gl_bill_payment_reversals (
            {ID},
            bill_payment_id uuid NOT NULL UNIQUE REFERENCES app.gl_bill_payments(id)
                ON DELETE RESTRICT,
            entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
            {CREATED}
        );

        CREATE TABLE app.gl_money_moves (
            {ID},
            {PROPERTY},
            {number("move_number", "MV")},
            moved_on date NOT NULL,
            from_account_id uuid NOT NULL,
            to_account_id uuid NOT NULL,
            amount_cents {CENTS.format("amount_cents")},
            {RIEL},
            exchange_difference_cents bigint NOT NULL DEFAULT 0
                CHECK (exchange_difference_cents BETWEEN -9000000000000000 AND 9000000000000000),
            note text CHECK (note IS NULL OR length(btrim(note)) BETWEEN 1 AND 500),
            entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT,
            {CREATED},
            {account_fk("gl_mv", "from_account_id")},
            {account_fk("gl_mv", "to_account_id")},
            {riel_check("gl_mv")},
            CONSTRAINT gl_mv_two_accounts CHECK (from_account_id <> to_account_id)
        );
        CREATE INDEX gl_mv_date_idx ON app.gl_money_moves(property_id, moved_on);

        CREATE TABLE app.gl_owner_money (
            {ID},
            {PROPERTY},
            direction text NOT NULL CHECK (direction IN ('IN','OUT')),
            moved_on date NOT NULL,
            account_id uuid NOT NULL,
            amount_cents {CENTS.format("amount_cents")},
            note text CHECK (note IS NULL OR length(btrim(note)) BETWEEN 1 AND 500),
            entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT,
            {CREATED},
            {account_fk("gl_om", "account_id")}
        );
        CREATE INDEX gl_om_date_idx ON app.gl_owner_money(property_id, moved_on);

        CREATE TABLE app.gl_petty_cash_topups (
            {ID},
            {PROPERTY},
            topped_up_on date NOT NULL,
            from_account_id uuid NOT NULL,
            amount_cents {CENTS.format("amount_cents")},
            entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT,
            {CREATED},
            {account_fk("gl_pc", "from_account_id")}
        );
        CREATE INDEX gl_pc_date_idx ON app.gl_petty_cash_topups(property_id, topped_up_on);

        CREATE TABLE app.gl_write_offs (
            {ID},
            {PROPERTY},
            settlement_correction_id uuid NOT NULL UNIQUE REFERENCES app.settlement_corrections(id)
                ON DELETE RESTRICT,
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            amount_cents {CENTS.format("amount_cents")},
            reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
            approved_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            {CREATED}
        );
        CREATE INDEX gl_wo_invoice_idx ON app.gl_write_offs(invoice_id);

        CREATE TABLE app.gl_fixed_assets (
            {ID},
            {PROPERTY},
            {number("asset_number", "FA")},
            item text NOT NULL CHECK (length(btrim(item)) BETWEEN 1 AND 200),
            account_id uuid NOT NULL,
            unit_id uuid REFERENCES app.units(id) ON DELETE RESTRICT,
            cost_cents {CENTS.format("cost_cents")},
            bought_on date NOT NULL,
            useful_life_years smallint NOT NULL CHECK (useful_life_years BETWEEN 1 AND 100),
            depreciation_starts_on date NOT NULL,
            purchase_entry_id {ENTRY},
            status text NOT NULL CHECK (status IN ('IN_USE','DISPOSED')),
            disposed_on date,
            disposal_entry_id {ENTRY},
            {CREATED},
            {account_fk("gl_fa", "account_id")},
            CONSTRAINT gl_fa_month_after CHECK (depreciation_starts_on =
                (date_trunc('month', bought_on) + interval '1 month')::date),
            CONSTRAINT gl_fa_disposed CHECK ((status = 'DISPOSED') = (disposed_on IS NOT NULL)),
            CONSTRAINT gl_fa_disposed_after CHECK (disposed_on IS NULL OR disposed_on >= bought_on)
        );
        CREATE INDEX gl_fa_account_idx ON app.gl_fixed_assets(account_id);

        CREATE TABLE app.gl_adjusting_entries (
            {ID},
            {PROPERTY},
            {number("adjustment_number", "AJ")},
            entry_date date NOT NULL,
            reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
            prepared_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            status text NOT NULL CHECK (status IN ('WAITING','POSTED','REFUSED','VOID')),
            decided_by {ACTOR},
            decided_at timestamptz,
            decision_note text CHECK (decision_note IS NULL
                OR length(btrim(decision_note)) BETWEEN 1 AND 1000),
            entry_id {ENTRY},
            {CREATED},
            CONSTRAINT gl_aj_posted CHECK ((status = 'POSTED') = (entry_id IS NOT NULL)),
            CONSTRAINT gl_aj_decided CHECK ((status = 'WAITING')
                = (decided_by IS NULL AND decided_at IS NULL)),
            CONSTRAINT gl_aj_not_own CHECK (decided_by IS DISTINCT FROM prepared_by)
        );
        CREATE INDEX gl_aj_status_idx ON app.gl_adjusting_entries(property_id, status);

        CREATE TABLE app.gl_adjusting_entry_lines (
            {ID},
            adjusting_entry_id uuid NOT NULL REFERENCES app.gl_adjusting_entries(id)
                ON DELETE RESTRICT,
            property_id uuid NOT NULL,
            line_no smallint NOT NULL CHECK (line_no BETWEEN 1 AND 500),
            account_id uuid NOT NULL,
            debit_cents bigint NOT NULL DEFAULT 0 CHECK (debit_cents BETWEEN 0 AND
                9000000000000000),
            credit_cents bigint NOT NULL DEFAULT 0
                CHECK (credit_cents BETWEEN 0 AND 9000000000000000),
            memo text CHECK (memo IS NULL OR length(btrim(memo)) BETWEEN 1 AND 500),
            unit_id uuid REFERENCES app.units(id) ON DELETE RESTRICT,
            customer_id uuid REFERENCES app.customers(id) ON DELETE RESTRICT,
            supplier_id uuid REFERENCES app.gl_suppliers(id) ON DELETE RESTRICT,
            {account_fk("gl_ajl", "account_id")},
            CONSTRAINT gl_ajl_line_key UNIQUE (adjusting_entry_id, line_no),
            CONSTRAINT gl_ajl_one_side CHECK ((debit_cents > 0 AND credit_cents = 0)
                OR (credit_cents > 0 AND debit_cents = 0))
        );
        CREATE INDEX gl_ajl_account_idx ON app.gl_adjusting_entry_lines(account_id);

        CREATE TABLE app.gl_opening_balances (
            {ID},
            property_id uuid NOT NULL UNIQUE REFERENCES app.properties(id) ON DELETE RESTRICT,
            start_date date NOT NULL,
            status text NOT NULL CHECK (status IN ('DRAFT','POSTED')),
            entry_id {ENTRY},
            posted_by {ACTOR},
            posted_at timestamptz,
            {CREATED},
            CONSTRAINT gl_ob_posted CHECK ((status = 'POSTED') =
                (entry_id IS NOT NULL AND posted_by IS NOT NULL AND posted_at IS NOT NULL))
        );

        CREATE TABLE app.gl_opening_balance_lines (
            {ID},
            opening_balance_id uuid NOT NULL REFERENCES app.gl_opening_balances(id)
                ON DELETE RESTRICT,
            property_id uuid NOT NULL,
            account_id uuid NOT NULL,
            debit_cents bigint NOT NULL DEFAULT 0 CHECK (debit_cents BETWEEN 0 AND
                9000000000000000),
            credit_cents bigint NOT NULL DEFAULT 0
                CHECK (credit_cents BETWEEN 0 AND 9000000000000000),
            memo text CHECK (memo IS NULL OR length(btrim(memo)) BETWEEN 1 AND 500),
            {account_fk("gl_obl", "account_id")},
            CONSTRAINT gl_obl_account_key UNIQUE (opening_balance_id, account_id),
            CONSTRAINT gl_obl_one_side CHECK ((debit_cents > 0 AND credit_cents = 0)
                OR (credit_cents > 0 AND debit_cents = 0))
        );
        CREATE INDEX gl_obl_account_idx ON app.gl_opening_balance_lines(account_id);

        CREATE TABLE app.gl_budgets (
            {ID},
            fiscal_year_id uuid NOT NULL,
            property_id uuid NOT NULL,
            version smallint NOT NULL CHECK (version BETWEEN 1 AND 999),
            status text NOT NULL CHECK (status IN ('DRAFT','APPROVED','REPLACED')),
            approved_by {ACTOR},
            approved_at timestamptz,
            {CREATED},
            CONSTRAINT gl_budgets_year_fkey FOREIGN KEY (fiscal_year_id, property_id)
                REFERENCES app.gl_fiscal_years(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_budgets_version_key UNIQUE (fiscal_year_id, version),
            CONSTRAINT gl_budgets_approved CHECK ((status = 'DRAFT')
                = (approved_by IS NULL AND approved_at IS NULL))
        );
        CREATE UNIQUE INDEX gl_budgets_one_approved_idx ON app.gl_budgets(fiscal_year_id)
            WHERE status = 'APPROVED';

        CREATE TABLE app.gl_budget_lines (
            {ID},
            budget_id uuid NOT NULL REFERENCES app.gl_budgets(id) ON DELETE RESTRICT,
            property_id uuid NOT NULL,
            account_id uuid NOT NULL,
            month_no smallint NOT NULL CHECK (month_no BETWEEN 1 AND 12),
            amount_cents bigint NOT NULL CHECK (amount_cents BETWEEN 0 AND 9000000000000000),
            {account_fk("gl_bl", "account_id")},
            CONSTRAINT gl_bl_key UNIQUE (budget_id, account_id, month_no)
        );
        CREATE INDEX gl_bl_account_idx ON app.gl_budget_lines(account_id);

        CREATE TABLE app.gl_bank_reconciliations (
            {ID},
            {PROPERTY},
            account_id uuid NOT NULL,
            period_id uuid NOT NULL,
            statement_balance_cents bigint NOT NULL
                CHECK (statement_balance_cents BETWEEN -9000000000000000 AND 9000000000000000),
            status text NOT NULL CHECK (status IN ('OPEN','MATCHED')),
            matched_by {ACTOR},
            matched_at timestamptz,
            {CREATED},
            {account_fk("gl_br", "account_id")},
            CONSTRAINT gl_br_period_fkey FOREIGN KEY (period_id, property_id)
                REFERENCES app.gl_periods(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_br_key UNIQUE (account_id, period_id),
            CONSTRAINT gl_br_matched CHECK ((status = 'MATCHED')
                = (matched_by IS NOT NULL AND matched_at IS NOT NULL))
        );
        CREATE INDEX gl_br_period_idx ON app.gl_bank_reconciliations(period_id);

        CREATE TABLE app.gl_bank_reconciliation_items (
            {ID},
            reconciliation_id uuid NOT NULL REFERENCES app.gl_bank_reconciliations(id)
                ON DELETE RESTRICT,
            journal_line_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_lines(id)
                ON DELETE RESTRICT,
            statement_date date NOT NULL,
            statement_reference text CHECK (statement_reference IS NULL
                OR length(btrim(statement_reference)) BETWEEN 1 AND 200),
            {CREATED}
        );
        CREATE INDEX gl_bri_reconciliation_idx
            ON app.gl_bank_reconciliation_items(reconciliation_id);

        CREATE TABLE app.gl_cash_counts (
            {ID},
            {PROPERTY},
            account_id uuid NOT NULL,
            period_id uuid NOT NULL,
            counted_on date NOT NULL,
            counted_minor bigint NOT NULL CHECK (counted_minor BETWEEN 0 AND 9000000000000000),
            book_minor bigint NOT NULL
                CHECK (book_minor BETWEEN -9000000000000000 AND 9000000000000000),
            difference_entry_id {ENTRY},
            note text CHECK (note IS NULL OR length(btrim(note)) BETWEEN 1 AND 500),
            {CREATED},
            {account_fk("gl_cc", "account_id")},
            CONSTRAINT gl_cc_period_fkey FOREIGN KEY (period_id, property_id)
                REFERENCES app.gl_periods(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_cc_key UNIQUE (account_id, period_id),
            CONSTRAINT gl_cc_difference CHECK ((counted_minor = book_minor)
                = (difference_entry_id IS NULL))
        );
        CREATE INDEX gl_cc_period_idx ON app.gl_cash_counts(period_id);

        CREATE TABLE app.gl_fx_revaluations (
            {ID},
            {PROPERTY},
            account_id uuid NOT NULL,
            period_id uuid NOT NULL,
            riel_held_minor bigint NOT NULL CHECK (riel_held_minor BETWEEN 0 AND 9000000000000000),
            exchange_rate_record_id uuid NOT NULL REFERENCES app.exchange_rate_records(id)
                ON DELETE RESTRICT,
            book_usd_cents bigint NOT NULL
                CHECK (book_usd_cents BETWEEN -9000000000000000 AND 9000000000000000),
            new_usd_cents bigint NOT NULL CHECK (new_usd_cents BETWEEN 0 AND 9000000000000000),
            entry_id {ENTRY},
            {CREATED},
            {account_fk("gl_fx", "account_id")},
            CONSTRAINT gl_fx_period_fkey FOREIGN KEY (period_id, property_id)
                REFERENCES app.gl_periods(id, property_id) ON DELETE RESTRICT,
            CONSTRAINT gl_fx_key UNIQUE (account_id, period_id),
            CONSTRAINT gl_fx_entry CHECK ((book_usd_cents = new_usd_cents) = (entry_id IS NULL))
        );
        CREATE INDEX gl_fx_period_idx ON app.gl_fx_revaluations(period_id);

        CREATE TABLE app.gl_close_runs (
            {ID},
            period_id uuid NOT NULL REFERENCES app.gl_periods(id) ON DELETE RESTRICT,
            ran_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            ran_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            checks jsonb NOT NULL CHECK (jsonb_typeof(checks) = 'object' AND checks <>
                '{{}}'::jsonb),
            all_green boolean NOT NULL
        );
        CREATE INDEX gl_close_runs_period_idx ON app.gl_close_runs(period_id, ran_at);

        ALTER TABLE app.gl_journal_lines ADD CONSTRAINT gl_jl_expense_request_fkey
            FOREIGN KEY (expense_request_id) REFERENCES app.gl_expense_requests(id)
            ON DELETE RESTRICT;
        ALTER TABLE app.gl_journal_lines ADD CONSTRAINT gl_jl_fixed_asset_fkey
            FOREIGN KEY (fixed_asset_id) REFERENCES app.gl_fixed_assets(id) ON DELETE RESTRICT;
        """
    )
    for table, free, first, steps in STATUS_TABLES:
        arguments = ", ".join(f"'{item}'" for item in (free, first, *steps))
        op.execute(
            f"""
            CREATE TRIGGER {table}_guard BEFORE INSERT OR UPDATE OR DELETE ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.gl_guard_record({arguments});
            CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
            """
        )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_update_or_delete BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.gl_reject_mutation();
            CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
            """
        )
    for table, columns, kind in CASH_COLUMNS:
        op.execute(
            f"""
            CREATE TRIGGER {table}_accounts BEFORE INSERT OR UPDATE ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_record_accounts('{columns}', '{kind or ""}');
            """
        )
    op.execute(
        """
        CREATE TRIGGER gl_fixed_assets_accounts BEFORE INSERT ON app.gl_fixed_assets
        FOR EACH ROW EXECUTE FUNCTION app.gl_check_record_accounts('', '');
        """
    )
    op.execute(
        r"""
        -- Manual lines (adjusting, opening): no control or tax-locked account, batch still open,
        -- and the line's Property is its batch's Property.
        CREATE FUNCTION app.gl_check_manual_line() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_account record;
            v_status text;
            v_property uuid;
            v_line record;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                v_line := OLD;
            ELSE
                v_line := NEW;
            END IF;
            IF TG_TABLE_NAME = 'gl_adjusting_entry_lines' THEN
                SELECT batch.status, batch.property_id INTO v_status, v_property
                FROM app.gl_adjusting_entries AS batch WHERE batch.id = v_line.adjusting_entry_id
                FOR SHARE;
                IF v_status <> 'WAITING' THEN
                    RAISE EXCEPTION 'Lines are added only while the adjusting entry waits'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF TG_TABLE_NAME = 'gl_opening_balance_lines' THEN
                SELECT batch.status, batch.property_id INTO v_status, v_property
                FROM app.gl_opening_balances AS batch WHERE batch.id = v_line.opening_balance_id
                FOR SHARE;
                IF v_status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'Opening balances are fixed once posted' USING ERRCODE =
                        '55000';
                END IF;
            ELSE
                SELECT batch.status, batch.property_id INTO v_status, v_property
                FROM app.gl_budgets AS batch WHERE batch.id = v_line.budget_id FOR SHARE;
                IF v_status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'An approved budget is locked; make a new version'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            IF v_property <> NEW.property_id THEN
                RAISE EXCEPTION 'A line belongs to the Property of its batch' USING ERRCODE =
                    '23514';
            END IF;
            IF TG_TABLE_NAME <> 'gl_budget_lines' THEN
                SELECT account.code, account.control_source, account.is_tax_locked,
                    account.is_active, account.is_postable INTO STRICT v_account
                FROM app.gl_accounts AS account WHERE account.id = NEW.account_id;
                IF v_account.control_source IS NOT NULL OR v_account.is_tax_locked
                    OR NOT v_account.is_active OR NOT v_account.is_postable THEN
                    RAISE EXCEPTION 'Account % cannot take a typed line', v_account.code
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_check_manual_line() FROM PUBLIC;
        CREATE TRIGGER gl_adjusting_entry_lines_check BEFORE INSERT
            ON app.gl_adjusting_entry_lines
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_manual_line();
        CREATE TRIGGER gl_opening_balance_lines_check BEFORE INSERT OR UPDATE OR DELETE
            ON app.gl_opening_balance_lines
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_manual_line();
        CREATE TRIGGER gl_budget_lines_check BEFORE INSERT OR UPDATE OR DELETE
            ON app.gl_budget_lines
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_manual_line();
        CREATE TRIGGER gl_opening_balance_lines_reject_truncate BEFORE TRUNCATE
            ON app.gl_opening_balance_lines
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
        CREATE TRIGGER gl_budget_lines_reject_truncate BEFORE TRUNCATE ON app.gl_budget_lines
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();

        -- A bill is never paid more than its amount, and a void bill takes no payment.
        CREATE FUNCTION app.gl_check_bill_payment() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_bill record;
            v_paid numeric;
        BEGIN
            SELECT bill.* INTO STRICT v_bill FROM app.gl_supplier_bills AS bill
            WHERE bill.id = NEW.supplier_bill_id FOR UPDATE;
            IF v_bill.status = 'VOID' OR v_bill.property_id <> NEW.property_id THEN
                RAISE EXCEPTION 'This bill takes no payment' USING ERRCODE = '23514';
            END IF;
            SELECT coalesce(sum(payment.amount_cents), 0) INTO v_paid
            FROM app.gl_bill_payments AS payment
            WHERE payment.supplier_bill_id = NEW.supplier_bill_id
              AND NOT EXISTS (SELECT 1 FROM app.gl_bill_payment_reversals AS reversal
                              WHERE reversal.bill_payment_id = payment.id);
            IF v_paid + NEW.amount_cents > v_bill.amount_cents THEN
                RAISE EXCEPTION 'Payments (% cents) would be more than the bill (% cents)',
                    v_paid + NEW.amount_cents, v_bill.amount_cents USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_check_bill_payment() FROM PUBLIC;
        CREATE TRIGGER gl_bill_payments_check BEFORE INSERT ON app.gl_bill_payments
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_bill_payment();

        -- Each reconciliation item is a line on that bank account, inside its month or before.
        CREATE FUNCTION app.gl_check_reconciliation_item() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_reconciliation record;
        BEGIN
            SELECT reconciliation.status, reconciliation.account_id, period.ends_on
            INTO STRICT v_reconciliation
            FROM app.gl_bank_reconciliations AS reconciliation
            JOIN app.gl_periods AS period ON period.id = reconciliation.period_id
            WHERE reconciliation.id = NEW.reconciliation_id FOR SHARE OF reconciliation;
            IF v_reconciliation.status <> 'OPEN' OR NOT EXISTS (
                SELECT 1 FROM app.gl_journal_lines AS line
                JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                WHERE line.id = NEW.journal_line_id
                  AND line.account_id = v_reconciliation.account_id
                  AND entry.entry_date <= v_reconciliation.ends_on) THEN
                RAISE EXCEPTION 'This line cannot be matched here' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        REVOKE ALL ON FUNCTION app.gl_check_reconciliation_item() FROM PUBLIC;
        CREATE TRIGGER gl_bank_reconciliation_items_check BEFORE INSERT
            ON app.gl_bank_reconciliation_items
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_reconciliation_item();
        """
    )
    for table in TABLES:
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime, prm_financial")


def downgrade() -> None:
    """Remove only these records tables, and only while the ledger is empty (owner Q2)."""
    checks = " OR ".join(f"EXISTS (SELECT 1 FROM app.{table})" for table in TABLES)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.gl_journal_entries) OR {checks} THEN
                RAISE EXCEPTION 'The ledger has records: it cannot be rolled back'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$;
        ALTER TABLE app.gl_journal_lines DROP CONSTRAINT gl_jl_fixed_asset_fkey;
        ALTER TABLE app.gl_journal_lines DROP CONSTRAINT gl_jl_expense_request_fkey;
        """
    )
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    op.execute(
        """
        DROP FUNCTION app.gl_check_reconciliation_item();
        DROP FUNCTION app.gl_check_bill_payment();
        DROP FUNCTION app.gl_check_manual_line();
        DROP FUNCTION app.gl_check_record_accounts();
        DROP FUNCTION app.gl_guard_record();
        """
    )
