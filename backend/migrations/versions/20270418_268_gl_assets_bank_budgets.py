# ruff: noqa: E501
"""General Ledger fixed assets, depreciation, riel at month end, bank matching, budgets (phase 6 step 4, part 2).

Owner decisions: PRD v2 PR-GL-036 (items from the Asset limit are assets; monthly straight-line
depreciation by itself from the month after purchase), PR-GL-048 and PR-GL-054 (budget by month,
prepared and approved), PR-GL-055 (bank matched line by line before close), gap G7 (riel cash
valued at month end, difference to 4100), DESIGN.md round 22 (Fixed assets, Bank and cash,
Budget pages; nobody approves their own), and the owner's answers of 03/11/2026 10:26: a Building
lasts 20 years, Furniture and appliances in Units 5 years, Office equipment 3 years (Business
rules); Land is never depreciated; value ends at $0 and the last month takes the leftover cents;
riel cash is valued at the app's system rate; the Owner or an allowed user may change one item's
years, and the value left is spread over the months left.

- An expense or Expense request on an equipment account (1500 to 1530) is at least the Asset
  limit; below it, it is an expense. Only those and 1200 (paid in advance) take spending among the
  asset accounts. A posted equipment expense adds its item to the register by itself; voiding the
  expense removes the item while no depreciation is posted for it.
- Depreciation: one entry per month (DR 6140, CR 1590 for each item), made by the posting job once
  the month has ended, or by the Owner from Month-end close. Each item takes the same amount each
  month (its value over its months); the last month takes what is left. A late item catches up
  in the next entry.
- Riel cash: valued once a month from the month's riel count and the riel moved after it, at the
  system rate in force at the month's end.
- Bank matching: the statement balance must equal every bank line marked as on the statement, up
  to the month; earlier months first.
- Budgets: one waiting and one approved version per year; the Owner's own budget is approved at
  once with a note (owner's card of 03/11/2026 12:08).
"""

import importlib.util
import re
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "20270418_268"
down_revision: str | None = "20270417_267"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_FUNCTIONS = (
    "app.gl_run_month_end(uuid, uuid, uuid)",
    "app.gl_change_asset_life(uuid, uuid, smallint, text, uuid)",
    "app.gl_asset_values(uuid)",
    "app.gl_prepare_budget(uuid, uuid, smallint, jsonb, text, uuid)",
    "app.gl_decide_budget(uuid, uuid, boolean, text, uuid)",
    "app.gl_match_bank(uuid, uuid, text, uuid, bigint, jsonb, uuid)",
    "app.gl_bank_lines(uuid, text, uuid)",
)
FINANCIAL_FUNCTIONS = ("app.gl_month_end_work(uuid, uuid)",)
INTERNAL_FUNCTIONS = (
    "app.gl_months_between(date, date)",
    "app.gl_rule_on(text, date)",
    "app.gl_asset_schedule(uuid)",
    "app.gl_asset_accumulated(uuid, date)",
    "app.gl_depreciation_due(uuid, date)",
    "app.gl_post_depreciation(uuid, uuid)",
    "app.gl_value_riel(uuid, uuid, boolean)",
)
TRIGGER_FUNCTIONS = (
    "app.gl_check_asset_spending()",
    "app.gl_expense_asset()",
)
# Functions of earlier steps this step replaces (restored on downgrade).
REPLACED = (
    ("20270416_266_gl_money_records.py", "gl_spend_account"),
    ("20270417_267_gl_close_and_adjust.py", "gl_month_close_checks"),
)

SCHEMA = r"""
-- Land has no years; an item removed by voiding its expense is VOID.
ALTER TABLE app.gl_fixed_assets ALTER COLUMN useful_life_years DROP NOT NULL,
    ADD COLUMN expense_id uuid UNIQUE REFERENCES app.gl_expenses(id) ON DELETE RESTRICT,
    DROP CONSTRAINT gl_fixed_assets_status_check,
    ADD CONSTRAINT gl_fixed_assets_status_check CHECK (status IN ('IN_USE','DISPOSED','VOID'));
DROP TRIGGER gl_fixed_assets_guard ON app.gl_fixed_assets;
CREATE TRIGGER gl_fixed_assets_guard BEFORE INSERT OR UPDATE OR DELETE ON app.gl_fixed_assets
    FOR EACH ROW EXECUTE FUNCTION app.gl_guard_record('status disposed_on disposal_entry_id',
        'IN_USE', 'IN_USE>DISPOSED', 'IN_USE>VOID');

-- A change of one item's years (owner 03/11/2026 10:26): the value left over the months left.
CREATE TABLE app.gl_fixed_asset_life_changes (
    id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'),
    fixed_asset_id uuid NOT NULL REFERENCES app.gl_fixed_assets(id) ON DELETE RESTRICT,
    useful_life_years smallint NOT NULL CHECK (useful_life_years BETWEEN 1 AND 100),
    starts_on date NOT NULL CHECK (starts_on = date_trunc('month', starts_on)::date),
    value_cents bigint NOT NULL CHECK (value_cents BETWEEN 0 AND 9000000000000000),
    months_left integer NOT NULL CHECK (months_left BETWEEN 1 AND 1200),
    reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT
);
CREATE INDEX gl_falc_asset_idx ON app.gl_fixed_asset_life_changes(fixed_asset_id, created_at);
CREATE TRIGGER gl_fixed_asset_life_changes_reject_update_or_delete BEFORE UPDATE OR DELETE
    ON app.gl_fixed_asset_life_changes FOR EACH ROW EXECUTE FUNCTION app.gl_reject_mutation();
CREATE TRIGGER gl_fixed_asset_life_changes_reject_truncate BEFORE TRUNCATE
    ON app.gl_fixed_asset_life_changes FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
GRANT SELECT ON TABLE app.gl_fixed_asset_life_changes TO prm_runtime, prm_financial;

-- Budgets: a sent-back version keeps its reason; one waiting and one approved version a year.
ALTER TABLE app.gl_budgets ADD COLUMN decision_note text CHECK (decision_note IS NULL
        OR length(btrim(decision_note)) BETWEEN 1 AND 1000),
    ADD COLUMN own_budget_note text CHECK (own_budget_note IS NULL
        OR length(btrim(own_budget_note)) BETWEEN 1 AND 1000);
COMMENT ON COLUMN app.gl_budgets.approved_by IS
    'Who decided: approved it, or sent it back (REPLACED from DRAFT, with decision_note).';
DROP TRIGGER gl_budgets_guard ON app.gl_budgets;
CREATE TRIGGER gl_budgets_guard BEFORE INSERT OR UPDATE OR DELETE ON app.gl_budgets
    FOR EACH ROW EXECUTE FUNCTION app.gl_guard_record('status approved_by approved_at decision_note',
        'DRAFT', 'DRAFT>APPROVED', 'DRAFT>REPLACED', 'APPROVED>REPLACED');
CREATE UNIQUE INDEX gl_budgets_one_waiting ON app.gl_budgets(fiscal_year_id) WHERE status = 'DRAFT';
CREATE UNIQUE INDEX gl_budgets_one_approved ON app.gl_budgets(fiscal_year_id)
    WHERE status = 'APPROVED';
"""

HELPERS = r"""
-- Months from one month to another (same month = 0).
CREATE FUNCTION app.gl_months_between(p_from date, p_to date)
RETURNS integer LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT ((date_part('year', p_to) - date_part('year', p_from)) * 12
        + date_part('month', p_to) - date_part('month', p_from))::integer
$$;

-- A Business rule on a day; a day before the rule was first set uses its first value.
CREATE FUNCTION app.gl_rule_on(p_code text, p_day date)
RETURNS bigint LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT coalesce(app.business_rule_value(p_code, p_day), (
        SELECT rule.value FROM app.business_rules AS rule
        JOIN app.business_rule_names AS name ON name.id = rule.rule_name_id
        WHERE name.code = p_code ORDER BY rule.effective_from LIMIT 1))
$$;

-- Which accounts take spending (step 3), now: expense and cost accounts, 1200 paid in advance
-- and the equipment accounts (non-current, not the depreciation account).
CREATE OR REPLACE FUNCTION app.gl_spend_account(p_property uuid, p_code text)
RETURNS app.gl_accounts LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
BEGIN
    SELECT account.* INTO v_account FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.code = p_code;
    IF NOT FOUND OR NOT v_account.is_active OR NOT v_account.is_postable
        OR v_account.control_source IS NOT NULL OR v_account.is_tax_locked
        OR v_account.cash_kind IS NOT NULL OR v_account.is_contra
        OR v_account.account_type NOT IN ('EXPENSE', 'COST_OF_SALES', 'ASSET')
        OR (v_account.account_type = 'ASSET' AND v_account.code <> '1200'
            AND v_account.bs_section IS DISTINCT FROM 'NON_CURRENT') THEN
        RAISE EXCEPTION 'Account % cannot take an expense', coalesce(p_code, '(none)')
            USING ERRCODE = '22023';
    END IF;
    RETURN v_account;
END $$;

-- An equipment purchase is at least the Asset limit (PR-GL-036); below it, it is an expense.
CREATE FUNCTION app.gl_check_asset_spending() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
    v_limit bigint;
    v_day date;
BEGIN
    SELECT account.* INTO STRICT v_account FROM app.gl_accounts AS account
    WHERE account.id = NEW.account_id;
    IF v_account.account_type <> 'ASSET' OR v_account.bs_section IS DISTINCT FROM 'NON_CURRENT' THEN
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME = 'gl_expenses' THEN
        v_day := NEW.expense_date;
    ELSE
        v_day := coalesce(NEW.spent_on, app.gl_today(NEW.property_id));
    END IF;
    v_limit := app.gl_rule_on('ASSET_LIMIT', v_day);
    IF v_limit IS NULL THEN
        RAISE EXCEPTION 'Set the Asset limit in Business rules first' USING ERRCODE = '55000';
    END IF;
    IF NEW.amount_cents < v_limit THEN
        RAISE EXCEPTION 'A purchase under the Asset limit ($%) is an expense: choose an expense account',
            to_char(v_limit / 100.0, 'FM999999999990.00') USING ERRCODE = '22023';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER gl_expense_requests_asset_limit BEFORE INSERT ON app.gl_expense_requests
    FOR EACH ROW EXECUTE FUNCTION app.gl_check_asset_spending();
CREATE TRIGGER gl_expenses_asset_limit BEFORE INSERT ON app.gl_expenses
    FOR EACH ROW EXECUTE FUNCTION app.gl_check_asset_spending();

-- A posted equipment expense adds its item; voiding it removes the item while no depreciation
-- is posted for it.
CREATE FUNCTION app.gl_expense_asset() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
    v_asset app.gl_fixed_assets%ROWTYPE;
    v_years smallint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT account.* INTO STRICT v_account FROM app.gl_accounts AS account
        WHERE account.id = NEW.account_id;
        IF v_account.account_type <> 'ASSET'
            OR v_account.bs_section IS DISTINCT FROM 'NON_CURRENT' THEN
            RETURN NEW;
        END IF;
        -- Land is never depreciated (owner 03/11/2026 10:26).
        IF v_account.code <> '1500' THEN
            v_years := app.gl_rule_on('ASSET_LIFE_' || v_account.code, NEW.expense_date)::smallint;
            IF v_years IS NULL THEN
                RAISE EXCEPTION 'Set how many years % lasts in Business rules first',
                    v_account.name_en USING ERRCODE = '55000';
            END IF;
        END IF;
        INSERT INTO app.gl_fixed_assets (id, property_id, asset_number, item, account_id, unit_id,
            cost_cents, bought_on, useful_life_years, depreciation_starts_on, purchase_entry_id,
            status, expense_id, created_by)
        VALUES (gen_random_uuid(), NEW.property_id,
            app.gl_next_number(NEW.property_id, 'FA', NEW.expense_date), left(NEW.description, 200),
            NEW.account_id, NEW.unit_id, NEW.amount_cents, NEW.expense_date,
            v_years,
            (date_trunc('month', NEW.expense_date) + interval '1 month')::date, NEW.entry_id,
            'IN_USE', NEW.id, NEW.created_by);
        RETURN NEW;
    END IF;
    IF NEW.status = 'VOID' AND OLD.status <> 'VOID' THEN
        SELECT asset.* INTO v_asset FROM app.gl_fixed_assets AS asset
        WHERE asset.expense_id = NEW.id FOR UPDATE;
        IF FOUND THEN
            IF app.gl_asset_accumulated(v_asset.id, 'infinity'::date) <> 0 THEN
                RAISE EXCEPTION 'Depreciation is posted for % %: it stays in the register',
                    v_asset.asset_number, v_asset.item USING ERRCODE = '55000';
            END IF;
            UPDATE app.gl_fixed_assets SET status = 'VOID' WHERE id = v_asset.id;
        END IF;
    END IF;
    RETURN NEW;
END $$;
"""

ASSETS = r"""
-- The plan an item follows: its value over its months from a start month (the latest change).
CREATE FUNCTION app.gl_asset_schedule(p_asset uuid)
RETURNS TABLE (starts_on date, value_cents bigint, months integer, useful_life_years smallint)
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT * FROM (
        SELECT change.starts_on, change.value_cents, change.months_left, change.useful_life_years
        FROM app.gl_fixed_asset_life_changes AS change
        WHERE change.fixed_asset_id = p_asset
        ORDER BY change.created_at DESC, change.id DESC LIMIT 1) AS latest
    UNION ALL
    SELECT asset.depreciation_starts_on, asset.cost_cents, asset.useful_life_years * 12,
        asset.useful_life_years
    FROM app.gl_fixed_assets AS asset
    WHERE asset.id = p_asset AND asset.useful_life_years IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM app.gl_fixed_asset_life_changes AS change
                      WHERE change.fixed_asset_id = p_asset)
$$;

-- Depreciation posted for an item up to a day.
CREATE FUNCTION app.gl_asset_accumulated(p_asset uuid, p_through date)
RETURNS bigint LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT coalesce(sum(line.credit_cents - line.debit_cents), 0)::bigint
    FROM app.gl_journal_lines AS line
    JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
    JOIN app.gl_accounts AS account ON account.id = line.account_id
    WHERE line.fixed_asset_id = p_asset AND account.code = '1590' AND entry.entry_date <= p_through
$$;

-- What an item should have lost by the end of a month, less what is posted: the same amount
-- each month, the last month taking what is left (owner 03/11/2026 10:26).
CREATE FUNCTION app.gl_depreciation_due(p_asset uuid, p_month_end date)
RETURNS bigint LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
DECLARE
    v_asset app.gl_fixed_assets%ROWTYPE;
    v_plan record;
    v_months integer;
    v_target bigint;
BEGIN
    SELECT asset.* INTO v_asset FROM app.gl_fixed_assets AS asset WHERE asset.id = p_asset;
    IF NOT FOUND OR v_asset.status <> 'IN_USE' OR v_asset.useful_life_years IS NULL THEN
        RETURN 0;
    END IF;
    SELECT * INTO v_plan FROM app.gl_asset_schedule(p_asset);
    v_months := app.gl_months_between(v_plan.starts_on, p_month_end) + 1;
    IF v_months <= 0 THEN
        RETURN 0;
    END IF;
    v_target := (v_asset.cost_cents - v_plan.value_cents) + CASE
        WHEN v_months >= v_plan.months THEN v_plan.value_cents
        ELSE v_months * (v_plan.value_cents / v_plan.months) END;
    RETURN greatest(v_target - app.gl_asset_accumulated(p_asset, p_month_end), 0);
END $$;

-- The month's depreciation entry (one per month); a late item catches up in the next one.
CREATE FUNCTION app.gl_post_depreciation(p_period uuid, p_actor uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_period app.gl_periods%ROWTYPE;
    v_key text := 'depreciation:' || p_period;
    v_entry uuid;
    v_lines jsonb;
BEGIN
    SELECT entry.id INTO v_entry FROM app.gl_journal_entries AS entry
    WHERE entry.posting_key = v_key;
    IF FOUND THEN
        RETURN v_entry;
    END IF;
    SELECT period.* INTO STRICT v_period FROM app.gl_periods AS period WHERE period.id = p_period;
    WITH due AS (
        SELECT asset.id, asset.asset_number, asset.item,
            app.gl_depreciation_due(asset.id, v_period.ends_on) AS cents
        FROM app.gl_fixed_assets AS asset
        WHERE asset.property_id = v_period.property_id AND asset.status = 'IN_USE'
          AND asset.useful_life_years IS NOT NULL
          AND asset.depreciation_starts_on <= v_period.ends_on
    )
    SELECT jsonb_agg(line ORDER BY due.asset_number, side) INTO v_lines
    FROM due
    CROSS JOIN LATERAL (VALUES
        (1, jsonb_build_object('account', '6140', 'debit_cents', due.cents,
            'fixed_asset_id', due.id, 'memo', left(due.asset_number || ' ' || due.item, 500))),
        (2, jsonb_build_object('account', '1590', 'credit_cents', due.cents,
            'fixed_asset_id', due.id, 'memo', left(due.asset_number || ' ' || due.item, 500))))
        AS item(side, line)
    WHERE due.cents > 0;
    IF v_lines IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN app.gl_post_entry(v_period.property_id, v_period.ends_on, 'DEPRECIATION',
        'Depreciation for ' || to_char(v_period.ends_on, 'MM/YYYY'), 'GL_PERIOD', p_period, v_key,
        NULL, p_actor, NULL, gen_random_uuid(), v_lines);
END $$;

-- Each item with cost, years, monthly amount, depreciation so far and value now (Fixed assets).
CREATE FUNCTION app.gl_asset_values(p_property uuid)
RETURNS TABLE (id uuid, asset_number text, item text, account_code text, unit_id uuid,
    cost_cents bigint, bought_on date, useful_life_years smallint, status text,
    monthly_cents bigint, depreciation_cents bigint, value_cents bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT asset.id, asset.asset_number, asset.item, account.code, asset.unit_id, asset.cost_cents,
        asset.bought_on, plan.useful_life_years, asset.status,
        CASE WHEN plan.months IS NULL THEN 0 ELSE plan.value_cents / plan.months END,
        app.gl_asset_accumulated(asset.id, 'infinity'::date),
        asset.cost_cents - app.gl_asset_accumulated(asset.id, 'infinity'::date)
    FROM app.gl_fixed_assets AS asset
    JOIN app.gl_accounts AS account ON account.id = asset.account_id
    LEFT JOIN LATERAL app.gl_asset_schedule(asset.id) AS plan ON true
    WHERE asset.property_id = p_property
    ORDER BY asset.asset_number
$$;

-- One item's years change (owner 03/11/2026 10:26): from the month after the last depreciated
-- month, the value left is spread over the months left of the new life.
CREATE FUNCTION app.gl_change_asset_life(p_asset uuid, p_actor uuid, p_years smallint,
    p_reason text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_asset app.gl_fixed_assets%ROWTYPE;
    v_last date;
    v_starts date;
    v_value bigint;
    v_months integer;
    v_id uuid := gen_random_uuid();
BEGIN
    SELECT asset.* INTO v_asset FROM app.gl_fixed_assets AS asset WHERE asset.id = p_asset
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No fixed asset' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_asset.property_id, 'ledger.fixed_assets');
    IF v_asset.status <> 'IN_USE' OR v_asset.useful_life_years IS NULL THEN
        RAISE EXCEPTION 'Only equipment in use has years to change' USING ERRCODE = '55000';
    END IF;
    IF p_years IS NULL OR p_years NOT BETWEEN 1 AND 100 THEN
        RAISE EXCEPTION 'Years are 1 to 100' USING ERRCODE = '22023';
    END IF;
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'A change of years needs a reason' USING ERRCODE = '22023';
    END IF;
    SELECT max(entry.entry_date) INTO v_last
    FROM app.gl_journal_lines AS line JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
    WHERE line.fixed_asset_id = p_asset AND entry.entry_kind = 'DEPRECIATION';
    v_starts := CASE WHEN v_last IS NULL THEN v_asset.depreciation_starts_on
        ELSE greatest((date_trunc('month', v_last) + interval '1 month')::date,
            v_asset.depreciation_starts_on) END;
    v_value := v_asset.cost_cents - app.gl_asset_accumulated(p_asset, 'infinity'::date);
    v_months := p_years * 12 - app.gl_months_between(v_asset.depreciation_starts_on, v_starts);
    IF v_months < 1 THEN
        RAISE EXCEPTION 'The item has already been used for % months: choose more years',
            app.gl_months_between(v_asset.depreciation_starts_on, v_starts) USING ERRCODE = '22023';
    END IF;
    INSERT INTO app.gl_fixed_asset_life_changes (id, fixed_asset_id, useful_life_years, starts_on,
        value_cents, months_left, reason, created_by)
    VALUES (v_id, p_asset, p_years, v_starts, v_value, v_months, btrim(p_reason), p_actor);
    PERFORM app.gl_audit(v_asset.property_id, p_actor, 'ledger.fixed_asset.life_changed',
        'gl_fixed_asset', p_asset, btrim(p_reason), p_correlation,
        jsonb_build_object('years', p_years, 'from', v_starts, 'value_cents', v_value,
            'months_left', v_months));
    RETURN v_id;
END $$;
"""

RIEL = r"""
-- Riel cash at month end (gap G7, owner 03/11/2026 10:26): the month's riel count plus the riel
-- moved after it, at the system rate in force at the month's end; the difference goes to 4100.
-- p_strict raises what is missing; the posting job skips it and tries again on the next pass.
CREATE FUNCTION app.gl_value_riel(p_period uuid, p_actor uuid, p_strict boolean)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_period app.gl_periods%ROWTYPE;
    v_zone text;
    v_cash record;
    v_count app.gl_cash_counts%ROWTYPE;
    v_rate record;
    v_riel bigint;
    v_book bigint;
    v_new bigint;
    v_entry uuid;
    v_id uuid;
    v_done integer := 0;
BEGIN
    SELECT period.* INTO STRICT v_period FROM app.gl_periods AS period WHERE period.id = p_period;
    SELECT property.timezone_name INTO STRICT v_zone FROM app.properties AS property
    WHERE property.id = v_period.property_id;
    FOR v_cash IN
        SELECT account.id, account.code FROM app.gl_accounts AS account
        WHERE account.property_id = v_period.property_id AND account.cash_kind = 'CASH_KHR'
          AND EXISTS (SELECT 1 FROM app.gl_journal_lines AS line
                      JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                      WHERE line.account_id = account.id AND entry.entry_date <= v_period.ends_on)
          AND NOT EXISTS (SELECT 1 FROM app.gl_fx_revaluations AS valued
                          WHERE valued.account_id = account.id AND valued.period_id = p_period)
        ORDER BY account.code
    LOOP
        SELECT counted.* INTO v_count FROM app.gl_cash_counts AS counted
        WHERE counted.account_id = v_cash.id AND counted.period_id = p_period;
        IF NOT FOUND THEN
            IF p_strict THEN
                RAISE EXCEPTION 'Count the riel cash (%) for this month first', v_cash.code
                    USING ERRCODE = '55000';
            END IF;
            CONTINUE;
        END IF;
        IF EXISTS (SELECT 1 FROM app.gl_journal_lines AS line
                   JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                   WHERE line.account_id = v_cash.id AND entry.entry_date > v_count.counted_on
                     AND entry.entry_date <= v_period.ends_on
                     AND (line.original_currency IS DISTINCT FROM 'KHR'
                          OR line.original_amount_minor IS NULL)) THEN
            IF p_strict THEN
                RAISE EXCEPTION 'A riel cash record after the count has no riel amount; fix it with an adjusting entry'
                    USING ERRCODE = '55000';
            END IF;
            CONTINUE;
        END IF;
        SELECT rate.id, rate.system_rate_khr_per_usd AS khr INTO v_rate
        FROM app.exchange_rate_records AS rate
        WHERE rate.applicable_at < ((v_period.ends_on + 1)::timestamp AT TIME ZONE v_zone)
          AND rate.system_rate_khr_per_usd > 0
        ORDER BY rate.applicable_at DESC, rate.id DESC LIMIT 1;
        IF NOT FOUND THEN
            IF p_strict THEN
                RAISE EXCEPTION 'No riel rate on or before %', to_char(v_period.ends_on, 'DD/MM/YYYY')
                    USING ERRCODE = '55000';
            END IF;
            CONTINUE;
        END IF;
        v_riel := v_count.counted_riel + coalesce((
            SELECT sum(CASE WHEN line.debit_cents > 0 THEN line.original_amount_minor
                ELSE -line.original_amount_minor END)
            FROM app.gl_journal_lines AS line
            JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
            WHERE line.account_id = v_cash.id AND entry.entry_date > v_count.counted_on
              AND entry.entry_date <= v_period.ends_on), 0);
        IF v_riel < 0 THEN
            IF p_strict THEN
                RAISE EXCEPTION 'The riel cash would be below zero' USING ERRCODE = '55000';
            END IF;
            CONTINUE;
        END IF;
        v_book := app.gl_account_balance(v_cash.id, v_period.ends_on);
        v_new := round(v_riel * 100.0 / v_rate.khr)::bigint;
        v_id := gen_random_uuid();
        v_entry := NULL;
        IF v_new <> v_book THEN
            v_entry := app.gl_post_entry(v_period.property_id, v_period.ends_on, 'FX_REVALUATION',
                'Riel cash valued at the month-end rate ' || to_char(v_period.ends_on, 'MM/YYYY'),
                'GL_FX_REVALUATION', v_id, 'fx_revaluation:' || v_cash.id || ':' || p_period, NULL,
                p_actor, NULL, gen_random_uuid(),
                CASE WHEN v_new > v_book THEN jsonb_build_array(
                        jsonb_build_object('account', v_cash.code, 'debit_cents', v_new - v_book),
                        jsonb_build_object('account', '4100', 'credit_cents', v_new - v_book))
                    ELSE jsonb_build_array(
                        jsonb_build_object('account', '4100', 'debit_cents', v_book - v_new),
                        jsonb_build_object('account', v_cash.code, 'credit_cents', v_book - v_new))
                END);
        END IF;
        INSERT INTO app.gl_fx_revaluations (id, property_id, account_id, period_id, riel_held_minor,
            exchange_rate_record_id, book_usd_cents, new_usd_cents, entry_id, created_by)
        VALUES (v_id, v_period.property_id, v_cash.id, p_period, v_riel, v_rate.id, v_book, v_new,
            v_entry, p_actor);
        v_done := v_done + 1;
    END LOOP;
    RETURN v_done;
END $$;

-- The posting job's month-end work: each open month that has ended, oldest first.
CREATE FUNCTION app.gl_month_end_work(p_property uuid, p_actor uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_period record;
    v_done integer := 0;
    v_today date;
BEGIN
    -- A Property whose ledger has not started has no month-end work.
    IF NOT EXISTS (SELECT 1 FROM app.gl_periods AS period WHERE period.property_id = p_property) THEN
        RETURN 0;
    END IF;
    v_today := app.gl_today(p_property);
    FOR v_period IN
        SELECT period.id FROM app.gl_periods AS period
        WHERE period.property_id = p_property AND period.period_no <= 12
          AND period.status = 'OPEN' AND period.ends_on < v_today
        ORDER BY period.starts_on
    LOOP
        IF NOT EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
                       WHERE entry.posting_key = 'depreciation:' || v_period.id) THEN
            IF app.gl_post_depreciation(v_period.id, p_actor) IS NOT NULL THEN
                v_done := v_done + 1;
            END IF;
        END IF;
        v_done := v_done + app.gl_value_riel(v_period.id, p_actor, false);
    END LOOP;
    RETURN v_done;
END $$;

-- The same from Month-end close, for one month, saying what is missing.
CREATE FUNCTION app.gl_run_month_end(p_period uuid, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_period app.gl_periods%ROWTYPE;
    v_entry uuid;
    v_valued integer;
BEGIN
    SELECT period.* INTO v_period FROM app.gl_periods AS period
    WHERE period.id = p_period AND period.period_no <= 12;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No month' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_period.property_id, 'ledger.close');
    IF v_period.status <> 'OPEN' THEN
        RAISE EXCEPTION 'This month is already closed' USING ERRCODE = '55000';
    END IF;
    IF v_period.ends_on >= app.gl_today(v_period.property_id) THEN
        RAISE EXCEPTION 'Month-end work runs after the month''s last day' USING ERRCODE = '55000';
    END IF;
    v_entry := app.gl_post_depreciation(p_period, p_actor);
    v_valued := app.gl_value_riel(p_period, p_actor, true);
    PERFORM app.gl_audit(v_period.property_id, p_actor, 'ledger.month_end.run', 'gl_period',
        p_period, 'Month-end work', p_correlation,
        jsonb_build_object('depreciation_entry_id', v_entry, 'riel_valued', v_valued));
    RETURN jsonb_build_object('depreciation_entry_id', v_entry, 'riel_valued', v_valued);
END $$;
"""

BANK = r"""
-- Bank lines up to a month's end that are not yet marked as on a statement.
CREATE FUNCTION app.gl_bank_lines(p_property uuid, p_account_code text, p_period uuid)
RETURNS TABLE (line_id uuid, entry_number text, entry_date date, description text, memo text,
    debit_cents bigint, credit_cents bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT line.id, entry.entry_number, entry.entry_date, entry.description, line.memo,
        line.debit_cents, line.credit_cents
    FROM app.gl_accounts AS account
    JOIN app.gl_periods AS period ON period.id = p_period AND period.property_id = p_property
    JOIN app.gl_journal_lines AS line ON line.account_id = account.id
    JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
    WHERE account.property_id = p_property AND account.code = p_account_code
      AND account.cash_kind = 'BANK' AND entry.entry_date <= period.ends_on
      AND NOT EXISTS (SELECT 1 FROM app.gl_bank_reconciliation_items AS item
                      WHERE item.journal_line_id = line.id)
    ORDER BY entry.entry_date, entry.entry_number, line.line_no
$$;

-- Mark as matched (PR-GL-055): the lines on this month's statement are marked, and the statement
-- balance equals every marked line up to this month. Earlier months first.
CREATE FUNCTION app.gl_match_bank(p_property uuid, p_actor uuid, p_account_code text,
    p_period uuid, p_statement_cents bigint, p_items jsonb, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
    v_period app.gl_periods%ROWTYPE;
    v_id uuid := gen_random_uuid();
    v_item jsonb;
    v_cleared bigint;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.reconcile');
    SELECT account.* INTO v_account FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.code = p_account_code
      AND account.cash_kind = 'BANK';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Account % is not a bank account', coalesce(p_account_code, '(none)')
            USING ERRCODE = '22023';
    END IF;
    SELECT period.* INTO v_period FROM app.gl_periods AS period
    WHERE period.id = p_period AND period.property_id = p_property AND period.period_no <= 12;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No month' USING ERRCODE = '22023';
    END IF;
    IF v_period.status <> 'OPEN' THEN
        RAISE EXCEPTION 'This month is already closed' USING ERRCODE = '55000';
    END IF;
    IF p_statement_cents IS NULL THEN
        RAISE EXCEPTION 'Type the statement balance' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (SELECT 1 FROM app.gl_bank_reconciliations AS match
               WHERE match.account_id = v_account.id AND match.period_id = p_period) THEN
        RAISE EXCEPTION 'This month is already matched' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.gl_periods AS before
               WHERE before.property_id = p_property AND before.period_no <= 12
                 AND before.ends_on < v_period.starts_on
                 AND EXISTS (SELECT 1 FROM app.gl_journal_lines AS line
                             JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                             WHERE line.account_id = v_account.id
                               AND entry.entry_date <= before.ends_on)
                 AND NOT EXISTS (SELECT 1 FROM app.gl_bank_reconciliations AS match
                                 WHERE match.account_id = v_account.id
                                   AND match.period_id = before.id
                                   AND match.status = 'MATCHED')) THEN
        RAISE EXCEPTION 'Match the earlier month first' USING ERRCODE = '55000';
    END IF;
    IF jsonb_typeof(p_items) IS DISTINCT FROM 'array' OR jsonb_array_length(p_items) > 5000 THEN
        RAISE EXCEPTION 'The marked lines are a list of up to 5000' USING ERRCODE = '22023';
    END IF;
    INSERT INTO app.gl_bank_reconciliations (id, property_id, account_id, period_id,
        statement_balance_cents, status, created_by)
    VALUES (v_id, p_property, v_account.id, p_period, p_statement_cents, 'OPEN', p_actor);
    FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
        IF EXISTS (SELECT 1 FROM app.gl_bank_reconciliation_items AS item
                   WHERE item.journal_line_id = (v_item ->> 'line_id')::uuid) THEN
            RAISE EXCEPTION 'A line is already on an earlier statement' USING ERRCODE = '55000';
        END IF;
        INSERT INTO app.gl_bank_reconciliation_items (id, reconciliation_id, journal_line_id,
            statement_date, statement_reference, created_by)
        VALUES (gen_random_uuid(), v_id, (v_item ->> 'line_id')::uuid,
            coalesce((v_item ->> 'statement_date')::date, v_period.ends_on),
            nullif(btrim(v_item ->> 'reference'), ''), p_actor);
    END LOOP;
    SELECT coalesce(sum(line.debit_cents - line.credit_cents), 0) INTO v_cleared
    FROM app.gl_bank_reconciliation_items AS item
    JOIN app.gl_bank_reconciliations AS match ON match.id = item.reconciliation_id
    JOIN app.gl_periods AS period ON period.id = match.period_id
    JOIN app.gl_journal_lines AS line ON line.id = item.journal_line_id
    WHERE match.account_id = v_account.id AND period.ends_on <= v_period.ends_on;
    IF v_cleared <> p_statement_cents THEN
        RAISE EXCEPTION 'The statement is off by % cents: record bank fees, or mark the lines on the statement',
            p_statement_cents - v_cleared USING ERRCODE = '22023';
    END IF;
    UPDATE app.gl_bank_reconciliations SET status = 'MATCHED', matched_by = p_actor,
        matched_at = statement_timestamp()
    WHERE id = v_id;
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.bank.matched', 'gl_bank_reconciliation',
        v_id, 'Bank matched for ' || to_char(v_period.ends_on, 'MM/YYYY'), p_correlation,
        jsonb_build_object('account', p_account_code, 'statement_balance_cents', p_statement_cents,
            'lines', jsonb_array_length(p_items)));
    RETURN v_id;
END $$;
"""

BUDGETS = r"""
-- A budget by month (PR-GL-054): sent whole; the Owner's own is approved at once with a note.
CREATE FUNCTION app.gl_prepare_budget(p_property uuid, p_actor uuid, p_year smallint,
    p_lines jsonb, p_own_note text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_year app.gl_fiscal_years%ROWTYPE;
    v_id uuid := gen_random_uuid();
    v_line jsonb;
    v_account app.gl_accounts%ROWTYPE;
    v_own boolean;
    v_total bigint := 0;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.budgets.prepare');
    SELECT year.* INTO v_year FROM app.gl_fiscal_years AS year
    WHERE year.property_id = p_property AND year.fiscal_year = p_year;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'The ledger has no year %', p_year USING ERRCODE = '22023';
    END IF;
    IF v_year.status <> 'OPEN' THEN
        RAISE EXCEPTION 'The year % is closed', p_year USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.gl_budgets AS budget
               WHERE budget.fiscal_year_id = v_year.id AND budget.status = 'DRAFT') THEN
        RAISE EXCEPTION 'A budget for % is already waiting for approval', p_year
            USING ERRCODE = '55000';
    END IF;
    IF jsonb_typeof(p_lines) IS DISTINCT FROM 'array' OR jsonb_array_length(p_lines) = 0
        OR jsonb_array_length(p_lines) > 5000 THEN
        RAISE EXCEPTION 'A budget has 1 to 5000 lines' USING ERRCODE = '22023';
    END IF;
    v_own := app.gl_can(p_actor, p_property, 'ledger.budgets.approve');
    IF v_own AND (p_own_note IS NULL OR btrim(p_own_note) = '') THEN
        RAISE EXCEPTION 'Your own budget is approved at once: add a note' USING ERRCODE = '22023';
    END IF;
    INSERT INTO app.gl_budgets (id, fiscal_year_id, property_id, version, status, created_by,
        own_budget_note)
    VALUES (v_id, v_year.id, p_property,
        coalesce((SELECT max(budget.version) FROM app.gl_budgets AS budget
                  WHERE budget.fiscal_year_id = v_year.id), 0) + 1,
        'DRAFT', p_actor, CASE WHEN v_own THEN btrim(p_own_note) END);
    FOR v_line IN SELECT value FROM jsonb_array_elements(p_lines) LOOP
        SELECT account.* INTO v_account FROM app.gl_accounts AS account
        WHERE account.property_id = p_property AND account.code = v_line ->> 'account';
        IF NOT FOUND OR NOT v_account.is_postable
            OR v_account.account_type NOT IN ('INCOME', 'COST_OF_SALES', 'EXPENSE') THEN
            RAISE EXCEPTION 'A budget line is an income, cost or expense account, not %',
                coalesce(v_line ->> 'account', '(none)') USING ERRCODE = '22023';
        END IF;
        IF (v_line ->> 'month_no')::integer NOT BETWEEN 1 AND 12
            OR coalesce((v_line ->> 'amount_cents')::bigint, -1) < 0 THEN
            RAISE EXCEPTION 'A budget line has a month 1 to 12 and an amount of 0 or more'
                USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.gl_budget_lines (id, budget_id, property_id, account_id, month_no,
            amount_cents)
        VALUES (gen_random_uuid(), v_id, p_property, v_account.id,
            (v_line ->> 'month_no')::smallint, (v_line ->> 'amount_cents')::bigint);
        v_total := v_total + (v_line ->> 'amount_cents')::bigint;
    END LOOP;
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.budget.sent', 'gl_budget', v_id,
        coalesce(nullif(btrim(p_own_note), ''), 'Budget sent'), p_correlation,
        jsonb_build_object('fiscal_year', p_year, 'lines', jsonb_array_length(p_lines),
            'total_cents', v_total, 'own', v_own));
    IF v_own THEN
        UPDATE app.gl_budgets SET status = 'REPLACED'
        WHERE fiscal_year_id = v_year.id AND status = 'APPROVED';
        UPDATE app.gl_budgets SET status = 'APPROVED', approved_by = p_actor,
            approved_at = statement_timestamp()
        WHERE id = v_id;
    END IF;
    RETURN v_id;
END $$;

CREATE FUNCTION app.gl_decide_budget(p_budget uuid, p_actor uuid, p_approve boolean,
    p_note text, p_correlation uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_budget app.gl_budgets%ROWTYPE;
BEGIN
    SELECT budget.* INTO v_budget FROM app.gl_budgets AS budget WHERE budget.id = p_budget
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No budget' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_budget.property_id, 'ledger.budgets.approve');
    IF v_budget.status <> 'DRAFT' THEN
        RAISE EXCEPTION 'This budget is not waiting for approval' USING ERRCODE = '55000';
    END IF;
    IF p_actor = v_budget.created_by THEN
        RAISE EXCEPTION 'Nobody approves their own budget' USING ERRCODE = '42501';
    END IF;
    IF NOT p_approve AND (p_note IS NULL OR btrim(p_note) = '') THEN
        RAISE EXCEPTION 'Say why the budget is sent back' USING ERRCODE = '22023';
    END IF;
    IF p_approve THEN
        UPDATE app.gl_budgets SET status = 'REPLACED'
        WHERE fiscal_year_id = v_budget.fiscal_year_id AND status = 'APPROVED';
    END IF;
    UPDATE app.gl_budgets SET status = CASE WHEN p_approve THEN 'APPROVED' ELSE 'REPLACED' END,
        approved_by = p_actor, approved_at = statement_timestamp(),
        decision_note = nullif(btrim(p_note), '')
    WHERE id = p_budget;
    PERFORM app.gl_audit(v_budget.property_id, p_actor,
        CASE WHEN p_approve THEN 'ledger.budget.approved' ELSE 'ledger.budget.sent_back' END,
        'gl_budget', p_budget, coalesce(nullif(btrim(p_note), ''), 'Approved'), p_correlation,
        '{}'::jsonb);
END $$;
"""

CHECKS = r"""
-- Month-end close lines (step 4 part 1), with "Depreciation done" green when the month's entry is
-- posted or no item has depreciation due for it (a fully depreciated item needs none).
CREATE OR REPLACE FUNCTION app.gl_month_close_checks(p_period uuid)
RETURNS TABLE (check_code text, ok boolean, open_items bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_period app.gl_periods%ROWTYPE;
    v_zone text;
    v_days integer;
BEGIN
    SELECT period.* INTO v_period FROM app.gl_periods AS period
    WHERE period.id = p_period AND period.period_no <= 12;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No month' USING ERRCODE = '22023';
    END IF;
    SELECT property.timezone_name INTO STRICT v_zone FROM app.properties AS property
    WHERE property.id = v_period.property_id;
    v_days := coalesce(app.business_rule_value('EXP_REPORT_DAYS', v_period.ends_on), 3)::integer;
    RETURN QUERY
    SELECT 'BOOKS_CHECK', bool_and(books.ok)
            AND NOT EXISTS (SELECT 1 FROM app.gl_opening_balances AS opening
                            WHERE opening.property_id = v_period.property_id
                              AND opening.status <> 'POSTED'),
        count(*) FILTER (WHERE NOT books.ok)
    FROM app.gl_books_check(v_period.property_id) AS books;
    RETURN QUERY
    SELECT 'NOTHING_WAITING', count(*) = 0, count(*) FROM (
        SELECT request.id FROM app.gl_expense_requests AS request
        WHERE request.property_id = v_period.property_id AND request.status = 'WAITING'
          AND coalesce(request.spent_on, timezone(v_zone, request.created_at)::date)
              <= v_period.ends_on
        UNION ALL
        SELECT adjustment.id FROM app.gl_adjusting_entries AS adjustment
        WHERE adjustment.property_id = v_period.property_id AND adjustment.status = 'WAITING'
          AND adjustment.entry_date <= v_period.ends_on) AS waiting;
    RETURN QUERY
    SELECT 'NO_LATE_ADVANCE', count(*) = 0, count(*)
    FROM app.gl_expense_requests AS request
    JOIN app.gl_journal_entries AS advance ON advance.id = request.paid_out_entry_id
    WHERE request.property_id = v_period.property_id AND request.status = 'PAID_OUT'
      AND advance.entry_date + v_days < v_period.ends_on;
    RETURN QUERY
    SELECT 'BANK_MATCHED', count(*) = 0, count(*)
    FROM app.gl_accounts AS account
    WHERE account.property_id = v_period.property_id AND account.cash_kind = 'BANK'
      AND EXISTS (SELECT 1 FROM app.gl_journal_lines AS line
                  JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                  WHERE line.account_id = account.id AND entry.entry_date <= v_period.ends_on)
      AND NOT EXISTS (SELECT 1 FROM app.gl_bank_reconciliations AS match
                      WHERE match.account_id = account.id AND match.period_id = p_period
                        AND match.status = 'MATCHED');
    RETURN QUERY
    SELECT 'CASH_COUNTED', count(*) = 0, count(*)
    FROM app.gl_accounts AS account
    WHERE account.property_id = v_period.property_id
      AND account.cash_kind IN ('CASH_USD', 'CASH_KHR', 'PETTY')
      AND EXISTS (SELECT 1 FROM app.gl_journal_lines AS line
                  JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                  WHERE line.account_id = account.id AND entry.entry_date <= v_period.ends_on)
      AND NOT EXISTS (SELECT 1 FROM app.gl_cash_counts AS counted
                      WHERE counted.account_id = account.id AND counted.period_id = p_period);
    RETURN QUERY
    SELECT 'DEPRECIATION_DONE', count(*) = 0, count(*)
    FROM app.gl_fixed_assets AS asset
    WHERE asset.property_id = v_period.property_id AND asset.status = 'IN_USE'
      AND asset.depreciation_starts_on <= v_period.ends_on
      AND NOT EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
                      WHERE entry.posting_key = 'depreciation:' || p_period)
      AND app.gl_depreciation_due(asset.id, v_period.ends_on) > 0;
    RETURN QUERY
    SELECT 'RIEL_VALUED', count(*) = 0, count(*)
    FROM app.gl_accounts AS account
    WHERE account.property_id = v_period.property_id AND account.cash_kind = 'CASH_KHR'
      AND EXISTS (SELECT 1 FROM app.gl_journal_lines AS line
                  JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                  WHERE line.account_id = account.id AND entry.entry_date <= v_period.ends_on)
      AND NOT EXISTS (SELECT 1 FROM app.gl_fx_revaluations AS valued
                      WHERE valued.account_id = account.id AND valued.period_id = p_period);
    -- Round 23: payroll comes from the HRIS; until it is built there is no payroll to approve.
    RETURN QUERY SELECT 'PAYROLL_APPROVED', true, 0::bigint;
END $$;
"""


def _literal_colons(sql: str) -> str:
    """Keep ``'depreciation:...'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def _module(file_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        file_name.removesuffix(".py"), Path(__file__).with_name(file_name)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _earlier_body(file_name: str, function: str) -> str:
    """The function as the earlier step created it, as CREATE OR REPLACE."""
    module = _module(file_name)
    for value in vars(module).values():
        if isinstance(value, str) and f"CREATE FUNCTION app.{function}(" in value:
            start = value.index(f"CREATE FUNCTION app.{function}(")
            end = value.index("END $$;", start) + len("END $$;")
            return value[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    raise LookupError(function)


def upgrade() -> None:
    op.execute(SCHEMA)
    for block in (ASSETS, HELPERS, RIEL, BANK, BUDGETS, CHECKS):
        op.execute(_literal_colons(block))
    op.execute(
        """
        CREATE TRIGGER gl_expenses_fixed_asset AFTER INSERT OR UPDATE OF status
            ON app.gl_expenses FOR EACH ROW EXECUTE FUNCTION app.gl_expense_asset();
        """
    )
    for function in (
        *RUNTIME_FUNCTIONS,
        *FINANCIAL_FUNCTIONS,
        *INTERNAL_FUNCTIONS,
        *TRIGGER_FUNCTIONS,
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in RUNTIME_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")
    for function in FINANCIAL_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.gl_fixed_assets)
                OR EXISTS (SELECT 1 FROM app.gl_budgets)
                OR EXISTS (SELECT 1 FROM app.gl_bank_reconciliations)
                OR EXISTS (SELECT 1 FROM app.gl_fx_revaluations) THEN
                RAISE EXCEPTION 'Ledger assets, budgets or matches exist; they cannot be rolled back'
                    USING ERRCODE = '55000';
            END IF;
        END $$;
        DROP TRIGGER gl_expenses_fixed_asset ON app.gl_expenses;
        DROP TRIGGER gl_expense_requests_asset_limit ON app.gl_expense_requests;
        DROP TRIGGER gl_expenses_asset_limit ON app.gl_expenses;
        """
    )
    for file_name, function in REPLACED:
        op.execute(_literal_colons(_earlier_body(file_name, function)))
    for function in (
        *RUNTIME_FUNCTIONS,
        *FINANCIAL_FUNCTIONS,
        *INTERNAL_FUNCTIONS[::-1],
        *TRIGGER_FUNCTIONS,
    ):
        op.execute(f"DROP FUNCTION {function}")
    op.execute(
        """
        DROP INDEX app.gl_budgets_one_waiting;
        DROP INDEX app.gl_budgets_one_approved;
        DROP TRIGGER gl_budgets_guard ON app.gl_budgets;
        CREATE TRIGGER gl_budgets_guard BEFORE INSERT OR UPDATE OR DELETE ON app.gl_budgets
            FOR EACH ROW EXECUTE FUNCTION app.gl_guard_record('status approved_by approved_at',
                'DRAFT', 'DRAFT>APPROVED', 'DRAFT>REPLACED', 'APPROVED>REPLACED');
        ALTER TABLE app.gl_budgets DROP COLUMN decision_note, DROP COLUMN own_budget_note;
        COMMENT ON COLUMN app.gl_budgets.approved_by IS NULL;
        DROP TABLE app.gl_fixed_asset_life_changes;
        DROP TRIGGER gl_fixed_assets_guard ON app.gl_fixed_assets;
        CREATE TRIGGER gl_fixed_assets_guard BEFORE INSERT OR UPDATE OR DELETE
            ON app.gl_fixed_assets FOR EACH ROW EXECUTE FUNCTION
            app.gl_guard_record('status disposed_on disposal_entry_id', 'IN_USE', 'IN_USE>DISPOSED');
        ALTER TABLE app.gl_fixed_assets DROP COLUMN expense_id,
            DROP CONSTRAINT gl_fixed_assets_status_check,
            ADD CONSTRAINT gl_fixed_assets_status_check CHECK (status IN ('IN_USE','DISPOSED')),
            ALTER COLUMN useful_life_years SET NOT NULL;
        """
    )
