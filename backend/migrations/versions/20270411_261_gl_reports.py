"""General Ledger report functions: ledger detail, trial balance, statements (PR-GL).

Revision ID: 20270411_261
Revises: 20270410_260
Create Date: 2026-11-02

Owner approved the ledger database plan on 2026-11-02 21:08
(https://claude.ai/artifact/5nttjeU5y5SaNSHU1etyuK, section 6). Reads only; nothing here
writes. Amounts are whole cents.

- ``app.gl_entry_lines_v``: each line with its entry, account and tags, and whether the entry
  was reversed (the general ledger detail).
- ``app.gl_account_balances(property, as_of)``: debit and credit totals and the balance on
  the account's normal side.
- ``app.gl_trial_balance(property, as_of)``: a debit or a credit balance for each account.
- ``app.gl_ledger_detail(account, from, to)``: opening balance, each line, running balance.
- ``app.gl_profit_and_loss(property, from, to)``: income, cost of products sold and expenses,
  without the year-end closing entry, so a closed year still shows its profit.
- ``app.gl_balance_sheet(property, as_of)``: assets, liabilities and equity, with
  "Profit this year not closed yet", so assets = liabilities + equity on every date.
- ``app.gl_cash_flow(property, from, to)``: direct method; cash and bank lines grouped by
  the other side's cash-flow group; a move between two cash accounts is not a flow.

The checked wrappers with the ``ledger.read`` right come in the coding phase; until then
only the application roles may call these.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270411_261"
down_revision: str | None = "20270410_260"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = (
    "app.gl_account_balances(uuid, date)",
    "app.gl_trial_balance(uuid, date)",
    "app.gl_ledger_detail(uuid, date, date)",
    "app.gl_profit_and_loss(uuid, date, date)",
    "app.gl_balance_sheet(uuid, date)",
    "app.gl_cash_flow(uuid, date, date)",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE VIEW app.gl_entry_lines_v AS
        SELECT line.id AS line_id, entry.id AS entry_id, entry.property_id, entry.entry_number,
            entry.entry_date, entry.period_id, entry.entry_kind, entry.description,
            entry.source_type, entry.source_id, entry.posting_key, entry.reverses_entry_id,
            EXISTS (SELECT 1 FROM app.gl_journal_entries AS reversal
                    WHERE reversal.reverses_entry_id = entry.id) AS is_reversed,
            entry.posted_at, entry.posted_by, entry.approved_by,
            line.line_no, account.id AS account_id, account.code AS account_code,
            account.name_en AS account_name_en, account.name_km AS account_name_km,
            account.account_type, line.debit_cents, line.credit_cents, line.memo,
            line.customer_id, line.lease_id, line.unit_id, line.supplier_id,
            line.expense_request_id, line.fixed_asset_id, line.employee_id,
            line.maintenance_request_id, line.original_currency, line.original_amount_minor,
            line.exchange_rate_record_id
        FROM app.gl_journal_lines AS line
        JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
        JOIN app.gl_accounts AS account ON account.id = line.account_id;

        CREATE FUNCTION app.gl_account_balances(p_property uuid, p_as_of date)
        RETURNS TABLE (account_id uuid, code text, name_en text, name_km text,
            account_type text, normal_side text, debit_cents bigint, credit_cents bigint,
            balance_cents bigint)
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT account.id, account.code, account.name_en, account.name_km,
                account.account_type, account.normal_side,
                coalesce(sum(line.debit_cents), 0)::bigint,
                coalesce(sum(line.credit_cents), 0)::bigint,
                (CASE WHEN account.normal_side = 'DEBIT'
                    THEN coalesce(sum(line.debit_cents), 0) - coalesce(sum(line.credit_cents), 0)
                    ELSE coalesce(sum(line.credit_cents), 0) - coalesce(sum(line.debit_cents), 0)
                    END)::bigint
            FROM app.gl_accounts AS account
            LEFT JOIN (app.gl_journal_lines AS line
                JOIN app.gl_journal_entries AS entry
                  ON entry.id = line.entry_id AND entry.entry_date <= p_as_of)
              ON line.account_id = account.id
            WHERE account.property_id = p_property
            GROUP BY account.id
            ORDER BY account.code
        $$;

        CREATE FUNCTION app.gl_trial_balance(p_property uuid, p_as_of date)
        RETURNS TABLE (account_id uuid, code text, name_en text, name_km text,
            account_type text, debit_balance_cents bigint, credit_balance_cents bigint)
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT balance.account_id, balance.code, balance.name_en, balance.name_km,
                balance.account_type,
                greatest(balance.debit_cents - balance.credit_cents, 0),
                greatest(balance.credit_cents - balance.debit_cents, 0)
            FROM app.gl_account_balances(p_property, p_as_of) AS balance
            WHERE balance.debit_cents <> 0 OR balance.credit_cents <> 0
            ORDER BY balance.code
        $$;

        -- Line 0 is the opening balance; the running balance is on the normal side.
        CREATE FUNCTION app.gl_ledger_detail(p_account uuid, p_from date, p_to date)
        RETURNS TABLE (entry_id uuid, entry_number text, entry_date date, line_no smallint,
            description text, memo text, debit_cents bigint, credit_cents bigint,
            running_balance_cents bigint)
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            WITH account AS (
                SELECT CASE WHEN normal_side = 'DEBIT' THEN 1 ELSE -1 END AS sign
                FROM app.gl_accounts WHERE id = p_account
            ), opening AS (
                SELECT coalesce(sum(line.debit_cents - line.credit_cents), 0) AS net
                FROM app.gl_journal_lines AS line
                JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                WHERE line.account_id = p_account AND entry.entry_date < p_from
            ), lines AS (
                SELECT entry.id AS entry_id, entry.entry_number, entry.entry_date, line.line_no,
                    entry.description, line.memo, line.debit_cents, line.credit_cents
                FROM app.gl_journal_lines AS line
                JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                WHERE line.account_id = p_account
                  AND entry.entry_date BETWEEN p_from AND p_to
            )
            SELECT NULL::uuid, NULL::text, p_from, 0::smallint, 'Opening balance', NULL::text,
                0::bigint, 0::bigint, (opening.net * account.sign)::bigint
            FROM opening, account
            UNION ALL
            SELECT lines.entry_id, lines.entry_number, lines.entry_date, lines.line_no,
                lines.description, lines.memo, lines.debit_cents, lines.credit_cents,
                ((opening.net + sum(lines.debit_cents - lines.credit_cents) OVER (
                    ORDER BY lines.entry_date, lines.entry_number, lines.line_no))
                    * account.sign)::bigint
            FROM lines, opening, account
            ORDER BY 3, 2 NULLS FIRST, 4
        $$;

        CREATE FUNCTION app.gl_profit_and_loss(p_property uuid, p_from date, p_to date)
        RETURNS TABLE (section text, account_id uuid, code text, name_en text, name_km text,
            amount_cents bigint)
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT account.account_type, account.id, account.code, account.name_en,
                account.name_km,
                (CASE WHEN account.account_type = 'INCOME'
                    THEN sum(line.credit_cents - line.debit_cents)
                    ELSE sum(line.debit_cents - line.credit_cents) END)::bigint
            FROM app.gl_journal_lines AS line
            JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
            JOIN app.gl_accounts AS account ON account.id = line.account_id
            WHERE entry.property_id = p_property
              AND entry.entry_date BETWEEN p_from AND p_to
              AND entry.entry_kind <> 'YEAR_END_CLOSE'
              AND account.account_type IN ('INCOME','COST_OF_SALES','EXPENSE')
            GROUP BY account.id
            HAVING sum(line.debit_cents - line.credit_cents) <> 0
            ORDER BY account.code
        $$;

        -- Assets on the debit side, liabilities and equity on the credit side (a contra
        -- account shows as a minus in its group). The last row is the profit since the last
        -- year-end close, so assets = liabilities + equity.
        CREATE FUNCTION app.gl_balance_sheet(p_property uuid, p_as_of date)
        RETURNS TABLE (section text, bs_section text, account_id uuid, code text, name_en text,
            name_km text, amount_cents bigint)
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT balance.account_type, account.bs_section, balance.account_id, balance.code,
                balance.name_en, balance.name_km, balance.balance_cents
            FROM app.gl_account_balances(p_property, p_as_of) AS balance
            JOIN app.gl_accounts AS account ON account.id = balance.account_id
            WHERE balance.account_type IN ('ASSET','LIABILITY','EQUITY')
              AND balance.balance_cents <> 0
            UNION ALL
            SELECT 'EQUITY', NULL, NULL, NULL, 'Profit this year not closed yet',
                'ចំណេញឆ្នាំនេះមិនទាន់បិទ',
                coalesce(sum(CASE WHEN balance.account_type = 'INCOME' THEN balance.balance_cents
                    ELSE -balance.balance_cents END), 0)::bigint
            FROM app.gl_account_balances(p_property, p_as_of) AS balance
            WHERE balance.account_type IN ('INCOME','COST_OF_SALES','EXPENSE')
            ORDER BY 1, 4 NULLS LAST
        $$;

        -- Direct method: for each entry that touches a cash account, its other lines (money
        -- in = credit) grouped by their cash-flow group (Operating when not set).
        CREATE FUNCTION app.gl_cash_flow(p_property uuid, p_from date, p_to date)
        RETURNS TABLE (cash_flow_group text, account_id uuid, code text, name_en text,
            name_km text, amount_cents bigint)
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT coalesce(account.cash_flow_group, 'OPERATING'), account.id, account.code,
                account.name_en, account.name_km,
                sum(line.credit_cents - line.debit_cents)::bigint
            FROM app.gl_journal_lines AS line
            JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
            JOIN app.gl_accounts AS account ON account.id = line.account_id
            WHERE entry.property_id = p_property
              AND entry.entry_date BETWEEN p_from AND p_to
              AND account.cash_kind IS NULL
              AND EXISTS (SELECT 1 FROM app.gl_journal_lines AS cash_line
                          JOIN app.gl_accounts AS cash ON cash.id = cash_line.account_id
                          WHERE cash_line.entry_id = entry.id AND cash.cash_kind IS NOT NULL)
            GROUP BY account.id
            HAVING sum(line.credit_cents - line.debit_cents) <> 0
            ORDER BY 1, account.code
        $$;
        """
    )
    op.execute("GRANT SELECT ON app.gl_entry_lines_v TO prm_runtime, prm_financial")
    for function in FUNCTIONS:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC; "
            f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime, prm_financial"
        )


def downgrade() -> None:
    """Reads only, so removing them loses nothing; the ledger data stays."""
    for function in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {function}")
    op.execute("DROP VIEW app.gl_entry_lines_v")
