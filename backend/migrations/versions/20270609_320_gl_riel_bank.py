# ruff: noqa: E501
"""General Ledger: a riel bank account, and a riel account for each Payment Method.

Owner 04/11/2026: NBC requires a riel account in every bank; one ABA QR code takes both riel and
dollars, and bank transfers come in both. Card 12:05 "Riel bank account per method"; card 17:52
"Same as riel cash": at each month end the riel in the bank is valued at the app's system rate
and the difference goes to 4100, like Cash on hand (KHR).

- ``app.gl_accounts.cash_kind`` takes ``BANK_KHR`` (a riel bank account). The starter chart gets
  1021 "ABA Bank · KHR account"; every Property that already has a chart gets it too.
- ``app.gl_method_accounts.riel_account_id``: a Payment Method's riel account (riel cash or riel
  bank). A riel payment goes there; with none, it goes where it went before (1011 for a dollar
  cash method, else the method's account). Refunds are always in dollars, so a Refund method has
  no riel account. ``app.gl_set_method_account`` takes it as a last, optional argument and
  ``app.gl_method_list`` shows it.
- A riel bank account keeps riel on every line (``app.gl_check_line``): money in or out of it is
  recorded in riel with the rate, and only the month-end valuation is in dollars alone. So
  ``app.gl_value_riel`` values the sum of its riel at the month-end system rate (riel cash still
  starts from its count), and bank matching compares the statement in riel.
- Money moves and Expenses take riel on a riel bank account, as on riel cash. Typed lines
  (adjusting entries, opening balances) cannot use it, since they carry no riel.
- Month-end close: a riel bank account must be matched and valued.

Forward-only: once a riel account is used, its rows cannot be read back by the old functions.
"""

import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270609_320"
down_revision: str | None = "20270512_292"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RIEL_KINDS = "('CASH_KHR', 'BANK_KHR')"
BANKS = "('BANK', 'BANK_KHR')"

# function signature -> ((old text, new text, times it must appear), ...)
PATCHES: dict[str, tuple[tuple[str, str, int], ...]] = {
    "app.gl_app_record_events(uuid, date, date)": (
        (
            "SELECT p.*, method_account.code AS method_code, method_account.cash_kind\n",
            "SELECT p.*, method_account.code AS method_code, method_account.cash_kind,\n"
            "        method_account.riel_code\n",
            1,
        ),
        (
            "        SELECT account.code, account.cash_kind FROM app.gl_method_accounts AS map\n"
            "        JOIN app.gl_accounts AS account ON account.id = map.account_id\n",
            "        SELECT account.code, account.cash_kind, riel.code AS riel_code\n"
            "        FROM app.gl_method_accounts AS map\n"
            "        JOIN app.gl_accounts AS account ON account.id = map.account_id\n"
            "        LEFT JOIN app.gl_accounts AS riel ON riel.id = map.riel_account_id\n",
            1,
        ),
        (
            "    SELECT pay.*, CASE WHEN pay.received_currency = 'KHR' AND pay.cash_kind = 'CASH_USD'\n",
            "    SELECT pay.*, CASE WHEN pay.received_currency = 'KHR' AND pay.riel_code IS NOT NULL\n"
            "            THEN pay.riel_code\n"
            "            WHEN pay.received_currency = 'KHR' AND pay.cash_kind = 'CASH_USD'\n",
            1,
        ),
    ),
    "app.gl_move_money(uuid, uuid, date, text, text, bigint, bigint, bigint, uuid, text, uuid)": (
        (
            "'CASH_KHR' NOT IN (v_from.cash_kind, v_to.cash_kind)",
            f"NOT (v_from.cash_kind IN {RIEL_KINDS} OR v_to.cash_kind IN {RIEL_KINDS})",
            2,
        ),
        (
            "Riel amounts come with their rate, on a riel cash account",
            "Riel amounts come with their rate, on a riel cash or riel bank account",
            1,
        ),
        (
            "    PERFORM app.gl_check_record_day(p_property, p_moved_on);\n",
            "    IF p_riel_minor IS NULL AND 'BANK_KHR' IN (v_from.cash_kind, v_to.cash_kind) THEN\n"
            "        RAISE EXCEPTION 'Money in or out of a riel bank account is typed in riel, with the rate'\n"
            "            USING ERRCODE = '22023';\n"
            "    END IF;\n"
            "    PERFORM app.gl_check_record_day(p_property, p_moved_on);\n",
            1,
        ),
        ("v_to.cash_kind = 'CASH_KHR'", f"v_to.cash_kind IN {RIEL_KINDS}", 1),
        ("v_from.cash_kind = 'CASH_KHR'", f"v_from.cash_kind IN {RIEL_KINDS}", 1),
    ),
    "app.gl_record_expense(uuid, uuid, date, text, text, bigint, text, bigint, uuid, text, uuid, text, date, uuid, uuid)": (
        ("v_from.cash_kind = 'CASH_KHR' AND", f"v_from.cash_kind IN {RIEL_KINDS} AND", 1),
    ),
    "app.gl_post_request_expense(uuid, uuid, bigint, date, text, uuid, date, uuid)": (
        ("v_from.cash_kind = 'CASH_KHR' AND", f"v_from.cash_kind IN {RIEL_KINDS} AND", 1),
    ),
    "app.gl_count_cash(uuid, uuid, text, date, bigint, bigint, uuid, text, uuid)": (
        ("IF v_cash.cash_kind = 'BANK' THEN", f"IF v_cash.cash_kind IN {BANKS} THEN", 1),
    ),
    "app.gl_month_close_checks(uuid)": (
        ("account.cash_kind = 'BANK'\n", f"account.cash_kind IN {BANKS}\n", 1),
        ("account.cash_kind = 'CASH_KHR'\n", f"account.cash_kind IN {RIEL_KINDS}\n", 1),
    ),
    "app.gl_check_record_accounts()": (
        (
            "(TG_ARGV[1] <> '' AND v_kind <> TG_ARGV[1])",
            "(TG_ARGV[1] <> '' AND NOT v_kind = ANY (string_to_array(TG_ARGV[1], ' ')))",
            1,
        ),
        ("ELSE TG_ARGV[1] END", "ELSE replace(TG_ARGV[1], ' ', ' or ') END", 1),
    ),
    "app.gl_check_manual_line()": (
        (
            "account.is_active, account.is_postable INTO STRICT v_account",
            "account.is_active, account.is_postable, account.cash_kind INTO STRICT v_account",
            1,
        ),
        (
            "OR NOT v_account.is_active OR NOT v_account.is_postable THEN",
            "OR NOT v_account.is_active OR NOT v_account.is_postable\n"
            "                    OR v_account.cash_kind IS NOT DISTINCT FROM 'BANK_KHR' THEN",
            1,
        ),
    ),
    "app.gl_check_reconciliation_item()": (
        (
            "AND entry.entry_date <= v_reconciliation.ends_on) THEN",
            "AND entry.entry_date <= v_reconciliation.ends_on\n"
            "                  AND entry.entry_kind <> 'FX_REVALUATION') THEN",
            1,
        ),
    ),
}

STRUCTURE = r"""
ALTER TABLE app.gl_accounts DROP CONSTRAINT gl_accounts_cash_kind_check,
    ADD CONSTRAINT gl_accounts_cash_kind_check
        CHECK (cash_kind IN ('CASH_USD', 'CASH_KHR', 'BANK', 'BANK_KHR', 'PETTY'));

INSERT INTO app.gl_chart_template (code, name_en, name_km, account_type, is_contra,
    control_source, is_tax_locked, is_retained_earnings, allows_unit, bs_section, cash_kind,
    cash_flow_group)
VALUES ('1021', 'ABA Bank · KHR account', 'ធនាគារ ABA · រៀល', 'ASSET', false, NULL, false, false,
    false, 'CURRENT', 'BANK_KHR', NULL);

-- Every Property that already has a chart gets 1021, written by whoever started its chart.
INSERT INTO app.gl_accounts (id, property_id, code, name_en, name_km, account_type, is_contra,
    control_source, is_tax_locked, is_retained_earnings, allows_unit, bs_section, cash_kind,
    cash_flow_group, created_by)
SELECT gen_random_uuid(), bank.property_id, template.code, template.name_en, template.name_km,
    template.account_type, template.is_contra, template.control_source, template.is_tax_locked,
    template.is_retained_earnings, template.allows_unit, template.bs_section, template.cash_kind,
    template.cash_flow_group, bank.created_by
FROM app.gl_accounts AS bank
JOIN app.gl_chart_template AS template ON template.code = '1021'
WHERE bank.code = '1020'
  AND NOT EXISTS (SELECT 1 FROM app.gl_accounts AS taken
                  WHERE taken.property_id = bank.property_id AND taken.code = '1021');

ALTER TABLE app.gl_method_accounts ADD COLUMN riel_account_id uuid,
    ADD CONSTRAINT gl_method_accounts_riel_fkey FOREIGN KEY (riel_account_id, property_id)
        REFERENCES app.gl_accounts(id, property_id) ON DELETE RESTRICT,
    ADD CONSTRAINT gl_method_accounts_riel_payment_only
        CHECK (riel_account_id IS NULL OR payment_method_id IS NOT NULL);
CREATE INDEX gl_method_accounts_riel_idx ON app.gl_method_accounts (riel_account_id)
    WHERE riel_account_id IS NOT NULL;

ALTER TABLE app.gl_bank_reconciliations ADD COLUMN statement_riel bigint
    CHECK (statement_riel BETWEEN -9000000000000000 AND 9000000000000000);

DROP TRIGGER gl_bank_reconciliations_accounts ON app.gl_bank_reconciliations;
CREATE TRIGGER gl_bank_reconciliations_accounts BEFORE INSERT OR UPDATE
    ON app.gl_bank_reconciliations
    FOR EACH ROW EXECUTE FUNCTION app.gl_check_record_accounts('account_id', 'BANK BANK_KHR');
DROP TRIGGER gl_fx_revaluations_accounts ON app.gl_fx_revaluations;
CREATE TRIGGER gl_fx_revaluations_accounts BEFORE INSERT OR UPDATE ON app.gl_fx_revaluations
    FOR EACH ROW EXECUTE FUNCTION app.gl_check_record_accounts('account_id', 'CASH_KHR BANK_KHR');
"""

FUNCTIONS = r"""
-- Method accounts: the main account is cash or a dollar bank; the riel account is riel cash or
-- a riel bank account.
CREATE OR REPLACE FUNCTION app.gl_check_method_account() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app.gl_accounts AS account
                   WHERE account.id = NEW.account_id AND account.cash_kind IS NOT NULL
                     AND account.cash_kind <> 'BANK_KHR') THEN
        RAISE EXCEPTION 'A Payment Method or Refund method uses a cash or bank account'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.riel_account_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM app.gl_accounts AS account
        WHERE account.id = NEW.riel_account_id AND account.cash_kind IN ('CASH_KHR', 'BANK_KHR')) THEN
        RAISE EXCEPTION 'A method''s riel account is riel cash or a riel bank account'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

DROP FUNCTION app.gl_set_method_account(uuid, uuid, uuid, text, date, uuid, uuid);
CREATE FUNCTION app.gl_set_method_account(p_property uuid, p_payment_method uuid,
    p_refund_method uuid, p_account_code text, p_effective_from date, p_actor uuid,
    p_correlation uuid, p_riel_account_code text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
    v_riel app.gl_accounts%ROWTYPE;
    v_id uuid := gen_random_uuid();
BEGIN
    IF (p_payment_method IS NULL) = (p_refund_method IS NULL) THEN
        RAISE EXCEPTION 'Name one Payment Method or one Refund method' USING ERRCODE = '22023';
    END IF;
    SELECT account.* INTO v_account FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.code = p_account_code;
    IF NOT FOUND OR v_account.cash_kind IS NULL OR NOT v_account.is_active THEN
        RAISE EXCEPTION 'A method goes to an active cash or bank account' USING ERRCODE = '22023';
    END IF;
    IF v_account.cash_kind = 'BANK_KHR' THEN
        RAISE EXCEPTION 'Account % keeps riel: choose it as the riel account', v_account.code
            USING ERRCODE = '22023';
    END IF;
    IF p_riel_account_code IS NOT NULL THEN
        IF p_refund_method IS NOT NULL THEN
            RAISE EXCEPTION 'Refunds are paid in dollars, so a Refund method has no riel account'
                USING ERRCODE = '22023';
        END IF;
        SELECT account.* INTO v_riel FROM app.gl_accounts AS account
        WHERE account.property_id = p_property AND account.code = p_riel_account_code;
        IF NOT FOUND OR coalesce(v_riel.cash_kind, '') NOT IN ('CASH_KHR', 'BANK_KHR')
            OR NOT v_riel.is_active THEN
            RAISE EXCEPTION 'The riel account is an active riel cash or riel bank account'
                USING ERRCODE = '22023';
        END IF;
    END IF;
    INSERT INTO app.gl_method_accounts (id, property_id, payment_method_id, refund_method_id,
        account_id, riel_account_id, effective_from, created_by)
    VALUES (v_id, p_property, p_payment_method, p_refund_method, v_account.id, v_riel.id,
        p_effective_from, p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.method_account.set', 'gl_method_account',
        v_id, 'Ledger account of a payment or refund method', p_correlation,
        jsonb_build_object('payment_method_id', p_payment_method,
            'refund_method_id', p_refund_method, 'account', p_account_code,
            'riel_account', p_riel_account_code, 'effective_from', p_effective_from));
    RETURN v_id;
END $$;

DROP FUNCTION app.gl_method_list(uuid, date);
CREATE FUNCTION app.gl_method_list(p_property uuid, p_day date)
RETURNS TABLE (kind text, method_id uuid, code text, name text, account_code text,
    account_name text, effective_from date, riel_account_code text, riel_account_name text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT method.kind, method.id, method.code, method.name, account.code, account.name_en,
        mapped.effective_from, riel.code, riel.name_en
    FROM (
        SELECT 'PAYMENT' AS kind, payment.id, payment.code, payment.display_name AS name
        FROM app.payment_methods AS payment
        UNION ALL
        SELECT 'REFUND', refund.id, refund.code, refund.display_name
        FROM app.refund_methods AS refund
    ) AS method
    LEFT JOIN LATERAL (
        SELECT map.account_id, map.riel_account_id, map.effective_from
        FROM app.gl_method_accounts AS map
        WHERE map.property_id = p_property AND map.effective_from <= p_day
          AND CASE method.kind WHEN 'PAYMENT' THEN map.payment_method_id
              ELSE map.refund_method_id END = method.id
        ORDER BY map.effective_from DESC, map.created_at DESC LIMIT 1
    ) AS mapped ON true
    LEFT JOIN app.gl_accounts AS account ON account.id = mapped.account_id
    LEFT JOIN app.gl_accounts AS riel ON riel.id = mapped.riel_account_id
    ORDER BY method.kind, method.code
$$;

-- Lines: as before, and a riel bank account keeps riel on every line. Only the month-end
-- valuation (and its reversal) is in dollars alone.
CREATE OR REPLACE FUNCTION app.gl_check_line() RETURNS trigger
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
        account.control_source, account.cash_kind INTO STRICT v_account
    FROM app.gl_accounts AS account WHERE account.id = NEW.account_id;
    IF NOT v_account.is_active OR NOT v_account.is_postable THEN
        RAISE EXCEPTION 'Account % is turned off or a heading', v_account.code
            USING ERRCODE = '23514';
    END IF;
    IF v_account.is_tax_locked THEN
        RAISE EXCEPTION 'Account % takes no entries until a tax agent confirms the rules',
            v_account.code USING ERRCODE = '23514';
    END IF;
    IF v_entry.entry_kind = 'REVERSAL' THEN
        SELECT entry.entry_kind INTO v_reversed_kind FROM app.gl_journal_entries AS entry
        WHERE entry.id = v_entry.reverses_entry_id;
    ELSE
        v_reversed_kind := v_entry.entry_kind;
    END IF;
    IF v_account.control_source IS NOT NULL
        AND v_reversed_kind NOT IN ('AUTO', 'RENT_TO_INCOME', 'OPENING') THEN
        RAISE EXCEPTION 'Account % changes only through app records', v_account.code
            USING ERRCODE = '23514';
    END IF;
    IF v_account.cash_kind = 'BANK_KHR' AND v_reversed_kind <> 'FX_REVALUATION'
        AND (NEW.original_currency IS DISTINCT FROM 'KHR' OR NEW.original_amount_minor IS NULL) THEN
        RAISE EXCEPTION 'Account % keeps riel: record money in or out of it in riel, with the rate',
            v_account.code USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

-- Riel at month end (gap G7, owner 03/11/2026 10:26; riel bank owner 04/11/2026 17:52): riel
-- cash is the month's count plus the riel moved after it; a riel bank account is the riel on
-- its lines. Both are valued at the system rate in force at the month's end, and the difference
-- goes to 4100. p_strict raises what is missing; the posting job skips it and tries again later.
CREATE OR REPLACE FUNCTION app.gl_value_riel(p_period uuid, p_actor uuid, p_strict boolean)
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
        SELECT account.id, account.code, account.cash_kind FROM app.gl_accounts AS account
        WHERE account.property_id = v_period.property_id
          AND account.cash_kind IN ('CASH_KHR', 'BANK_KHR')
          AND EXISTS (SELECT 1 FROM app.gl_journal_lines AS line
                      JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                      WHERE line.account_id = account.id AND entry.entry_date <= v_period.ends_on)
          AND NOT EXISTS (SELECT 1 FROM app.gl_fx_revaluations AS valued
                          WHERE valued.account_id = account.id AND valued.period_id = p_period)
        ORDER BY account.code
    LOOP
        IF v_cash.cash_kind = 'CASH_KHR' THEN
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
        IF v_cash.cash_kind = 'CASH_KHR' THEN
            v_riel := v_count.counted_riel + coalesce((
                SELECT sum(CASE WHEN line.debit_cents > 0 THEN line.original_amount_minor
                    ELSE -line.original_amount_minor END)
                FROM app.gl_journal_lines AS line
                JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                WHERE line.account_id = v_cash.id AND entry.entry_date > v_count.counted_on
                  AND entry.entry_date <= v_period.ends_on), 0);
        ELSE
            -- Every line but the month-end valuation carries its riel (app.gl_check_line).
            v_riel := coalesce((
                SELECT sum(CASE WHEN line.debit_cents > 0 THEN line.original_amount_minor
                    ELSE -line.original_amount_minor END)
                FROM app.gl_journal_lines AS line
                JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
                WHERE line.account_id = v_cash.id AND line.original_currency = 'KHR'
                  AND entry.entry_date <= v_period.ends_on), 0);
        END IF;
        IF v_riel < 0 THEN
            IF p_strict THEN
                IF v_cash.cash_kind = 'CASH_KHR' THEN
                    RAISE EXCEPTION 'The riel cash would be below zero' USING ERRCODE = '55000';
                END IF;
                RAISE EXCEPTION 'The riel in account % would be below zero', v_cash.code
                    USING ERRCODE = '55000';
            END IF;
            CONTINUE;
        END IF;
        v_book := app.gl_account_balance(v_cash.id, v_period.ends_on);
        v_new := round(v_riel * 100.0 / v_rate.khr)::bigint;
        v_id := gen_random_uuid();
        v_entry := NULL;
        IF v_new <> v_book THEN
            v_entry := app.gl_post_entry(v_period.property_id, v_period.ends_on, 'FX_REVALUATION',
                CASE WHEN v_cash.cash_kind = 'CASH_KHR' THEN 'Riel cash' ELSE 'Riel bank' END
                    || ' valued at the month-end rate ' || to_char(v_period.ends_on, 'MM/YYYY'),
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

-- Bank lines up to a month's end not yet on a statement, with their riel. The month-end
-- valuation of a riel bank account is not on any statement.
DROP FUNCTION app.gl_bank_lines(uuid, text, uuid);
CREATE FUNCTION app.gl_bank_lines(p_property uuid, p_account_code text, p_period uuid)
RETURNS TABLE (line_id uuid, entry_number text, entry_date date, description text, memo text,
    debit_cents bigint, credit_cents bigint, riel_minor bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT line.id, entry.entry_number, entry.entry_date, entry.description, line.memo,
        line.debit_cents, line.credit_cents,
        CASE WHEN line.original_currency = 'KHR' THEN line.original_amount_minor END
    FROM app.gl_accounts AS account
    JOIN app.gl_periods AS period ON period.id = p_period AND period.property_id = p_property
    JOIN app.gl_journal_lines AS line ON line.account_id = account.id
    JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
    WHERE account.property_id = p_property AND account.code = p_account_code
      AND account.cash_kind IN ('BANK', 'BANK_KHR') AND entry.entry_date <= period.ends_on
      AND entry.entry_kind <> 'FX_REVALUATION'
      AND NOT EXISTS (SELECT 1 FROM app.gl_bank_reconciliation_items AS item
                      WHERE item.journal_line_id = line.id)
    ORDER BY entry.entry_date, entry.entry_number, line.line_no
$$;

-- Mark as matched (PR-GL-055): the lines on this month's statement are marked, and the statement
-- balance equals every marked line up to this month. Earlier months first. A riel bank account
-- is matched in riel (p_statement_riel); its dollar balance is then the marked lines' dollars.
DROP FUNCTION app.gl_match_bank(uuid, uuid, text, uuid, bigint, jsonb, uuid);
CREATE FUNCTION app.gl_match_bank(p_property uuid, p_actor uuid, p_account_code text,
    p_period uuid, p_statement_cents bigint, p_statement_riel bigint, p_items jsonb,
    p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
    v_period app.gl_periods%ROWTYPE;
    v_id uuid := gen_random_uuid();
    v_item jsonb;
    v_cleared bigint;
    v_cleared_riel bigint;
    v_riel boolean;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.reconcile');
    SELECT account.* INTO v_account FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.code = p_account_code
      AND account.cash_kind IN ('BANK', 'BANK_KHR');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Account % is not a bank account', coalesce(p_account_code, '(none)')
            USING ERRCODE = '22023';
    END IF;
    v_riel := v_account.cash_kind = 'BANK_KHR';
    SELECT period.* INTO v_period FROM app.gl_periods AS period
    WHERE period.id = p_period AND period.property_id = p_property AND period.period_no <= 12;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No month' USING ERRCODE = '22023';
    END IF;
    IF v_period.status <> 'OPEN' THEN
        RAISE EXCEPTION 'This month is already closed' USING ERRCODE = '55000';
    END IF;
    IF v_riel AND (p_statement_riel IS NULL OR p_statement_cents IS NOT NULL) THEN
        RAISE EXCEPTION 'Type the statement balance in riel' USING ERRCODE = '22023';
    END IF;
    IF NOT v_riel AND (p_statement_cents IS NULL OR p_statement_riel IS NOT NULL) THEN
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
    -- What the marked lines clear: the lines of earlier statements and the lines marked now.
    SELECT coalesce(sum(line.debit_cents - line.credit_cents), 0),
        coalesce(sum(CASE WHEN line.debit_cents > 0 THEN line.original_amount_minor
            ELSE -line.original_amount_minor END), 0)
    INTO v_cleared, v_cleared_riel
    FROM app.gl_journal_lines AS line
    WHERE line.account_id = v_account.id
      AND (line.id IN (SELECT item.journal_line_id
                       FROM app.gl_bank_reconciliation_items AS item
                       JOIN app.gl_bank_reconciliations AS match
                         ON match.id = item.reconciliation_id
                       JOIN app.gl_periods AS period ON period.id = match.period_id
                       WHERE match.account_id = v_account.id
                         AND period.ends_on <= v_period.ends_on)
           OR line.id IN (SELECT (marked.value ->> 'line_id')::uuid
                          FROM jsonb_array_elements(p_items) AS marked));
    INSERT INTO app.gl_bank_reconciliations (id, property_id, account_id, period_id,
        statement_balance_cents, statement_riel, status, created_by)
    VALUES (v_id, p_property, v_account.id, p_period,
        CASE WHEN v_riel THEN v_cleared ELSE p_statement_cents END, p_statement_riel, 'OPEN',
        p_actor);
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
    IF v_riel THEN
        IF v_cleared_riel <> p_statement_riel THEN
            RAISE EXCEPTION 'The statement is off by % riel: record bank fees, or mark the lines on the statement',
                p_statement_riel - v_cleared_riel USING ERRCODE = '22023';
        END IF;
    ELSIF v_cleared <> p_statement_cents THEN
        RAISE EXCEPTION 'The statement is off by % cents: record bank fees, or mark the lines on the statement',
            p_statement_cents - v_cleared USING ERRCODE = '22023';
    END IF;
    UPDATE app.gl_bank_reconciliations SET status = 'MATCHED', matched_by = p_actor,
        matched_at = statement_timestamp()
    WHERE id = v_id;
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.bank.matched', 'gl_bank_reconciliation',
        v_id, 'Bank matched for ' || to_char(v_period.ends_on, 'MM/YYYY'), p_correlation,
        jsonb_build_object('account', p_account_code, 'statement_balance_cents',
            coalesce(p_statement_cents, v_cleared), 'statement_riel', p_statement_riel,
            'lines', jsonb_array_length(p_items)));
    RETURN v_id;
END $$;
"""

RUNTIME = (
    "app.gl_set_method_account(uuid, uuid, uuid, text, date, uuid, uuid, text)",
    "app.gl_method_list(uuid, date)",
    "app.gl_bank_lines(uuid, text, uuid)",
    "app.gl_match_bank(uuid, uuid, text, uuid, bigint, bigint, jsonb, uuid)",
)


def _literal_colons(sql: str) -> str:
    """Keep ``'invoice:...:issue'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def _patch(signature: str, changes: tuple[tuple[str, str, int], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for old, new, times in changes:
        if definition.count(old) != times:
            raise RuntimeError(f"{signature} changed: expected {times} of {old!r}")
        definition = definition.replace(old, new)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(_literal_colons(definition))


def upgrade() -> None:
    op.execute(STRUCTURE)
    op.execute(FUNCTIONS)
    for function in RUNTIME:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC; "
            f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime"
        )
    for signature, changes in PATCHES.items():
        _patch(signature, changes)


def downgrade() -> None:
    raise RuntimeError("The riel bank account migration is forward-only")
