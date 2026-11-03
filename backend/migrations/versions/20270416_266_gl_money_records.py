# ruff: noqa: E501
"""General Ledger money records: expenses, supplier bills, petty cash, moves (phase 6 step 3).

Owner decisions: the expense flow of 02/11/2026 (design page "Expense requests and Expense
reports"), D4 (nobody approves their own; the Owner's own spending goes in at once with a note),
the round 21 and 22 screens (DESIGN.md: Give advance, Record bill returns the change or owes the
staff the extra, Pay back staff; Supplier bills pay part or full; petty cash top-up up to the Petty
cash amount; a cash count difference needs a reason and goes to 6180, riel cash is counted in riel
and turned into dollars at the rate), and the rights table of 03/11/2026 06:56 and 07:03.

Every writer is a checked function for the runtime login. It checks the actor's right for the
Property (``app.actor_capability_grants``), writes the record and its journal entry in one step,
and writes one audit event. Records are never edited: a mistake is voided with a reason, which
posts the mirrored entry.

What each step writes:

- Expense request or report sent, approved or refused: no entry. An urgent report, when approved,
  records the expense at once: DR the expense or asset account, CR 1030 Petty cash or 2310 Money
  owed to staff.
- Give advance: DR 1400 Staff advances, CR the cash or bank account.
- Record bill: DR the account; CR the account it was paid from, 2010 Supplier bills to pay (a
  supplier bill due 30 days after the bill date unless it shows its own), or 1400 for an advance,
  with the change back to cash or the extra to 2310.
- Pay back staff: DR 2310, CR cash or bank. Pay a supplier bill: DR 2010, CR cash or bank.
- Money move: DR the account it goes to, CR the account it leaves; a riel exchange difference goes
  to 4100 Exchange gain or loss. Owner money: DR cash CR 3000, or DR 3100 CR cash. Petty cash top-up:
  DR 1030, CR cash or bank. Cash count difference: 6180 Cash short or over.
"""

import re
from collections.abc import Sequence

from alembic import op

revision: str = "20270416_266"
down_revision: str | None = "20270415_265"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_FUNCTIONS = (
    "app.gl_add_supplier(uuid, uuid, text, text, text, uuid)",
    "app.gl_submit_expense_request(uuid, uuid, text, text, text, text, bigint, text, bigint, uuid, uuid, uuid, date, text, text, uuid)",
    "app.gl_decide_expense_request(uuid, uuid, boolean, text, uuid)",
    "app.gl_give_advance(uuid, uuid, text, date, uuid)",
    "app.gl_record_request_bill(uuid, uuid, bigint, date, text, uuid, date, uuid)",
    "app.gl_pay_back_staff(uuid, uuid, text, date, uuid)",
    "app.gl_void_expense_request(uuid, uuid, text, uuid)",
    "app.gl_record_expense(uuid, uuid, date, text, text, bigint, text, bigint, uuid, text, uuid, text, date, uuid, uuid)",
    "app.gl_void_expense(uuid, uuid, text, uuid)",
    "app.gl_pay_supplier_bill(uuid, uuid, text, date, bigint, uuid)",
    "app.gl_reverse_bill_payment(uuid, uuid, text, uuid)",
    "app.gl_move_money(uuid, uuid, date, text, text, bigint, bigint, bigint, uuid, text, uuid)",
    "app.gl_record_owner_money(uuid, uuid, text, date, text, bigint, text, uuid)",
    "app.gl_top_up_petty_cash(uuid, uuid, date, text, bigint, uuid)",
    "app.gl_count_cash(uuid, uuid, text, date, bigint, bigint, uuid, text, uuid)",
)
INTERNAL_FUNCTIONS = (
    "app.gl_can(uuid, uuid, text)",
    "app.gl_require(uuid, uuid, text)",
    "app.gl_today(uuid)",
    "app.gl_money_account(uuid, text)",
    "app.gl_spend_account(uuid, text)",
    "app.gl_account_balance(uuid, date)",
    "app.gl_check_record_day(uuid, date)",
    "app.gl_post_request_expense(uuid, uuid, bigint, date, text, uuid, date, uuid)",
)

HELPERS = r"""
-- The actor holds the right for the Property (V1 bundles and the Owner class).
CREATE FUNCTION app.gl_can(p_actor uuid, p_property uuid, p_capability text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT EXISTS (SELECT 1 FROM app.actor_capability_grants(p_actor) AS grant_row
                   WHERE grant_row.capability_id = p_capability
                     AND grant_row.property_id = p_property)
$$;

CREATE FUNCTION app.gl_require(p_actor uuid, p_property uuid, p_capability text)
RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF p_actor IS NULL OR NOT app.gl_can(p_actor, p_property, p_capability) THEN
        RAISE EXCEPTION 'This needs the right %', p_capability USING ERRCODE = '42501';
    END IF;
END $$;

CREATE FUNCTION app.gl_today(p_property uuid)
RETURNS date LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_day date;
BEGIN
    SELECT timezone(property.timezone_name, statement_timestamp())::date INTO v_day
    FROM app.properties AS property WHERE property.id = p_property;
    IF v_day IS NULL THEN
        RAISE EXCEPTION 'The Property was not found' USING ERRCODE = '22023';
    END IF;
    RETURN v_day;
END $$;

-- A cash, bank or petty cash account of the Property that is turned on.
CREATE FUNCTION app.gl_money_account(p_property uuid, p_code text)
RETURNS app.gl_accounts LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
BEGIN
    SELECT account.* INTO v_account FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.code = p_code;
    IF NOT FOUND OR v_account.cash_kind IS NULL OR NOT v_account.is_active THEN
        RAISE EXCEPTION 'Account % is not a cash or bank account that is turned on',
            coalesce(p_code, '(none)') USING ERRCODE = '22023';
    END IF;
    RETURN v_account;
END $$;

-- What an expense may go to: an expense, cost or asset account that takes typed lines.
CREATE FUNCTION app.gl_spend_account(p_property uuid, p_code text)
RETURNS app.gl_accounts LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
BEGIN
    SELECT account.* INTO v_account FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.code = p_code;
    IF NOT FOUND OR NOT v_account.is_active OR NOT v_account.is_postable
        OR v_account.control_source IS NOT NULL OR v_account.is_tax_locked
        OR v_account.cash_kind IS NOT NULL OR v_account.is_contra
        OR v_account.account_type NOT IN ('EXPENSE', 'COST_OF_SALES', 'ASSET') THEN
        RAISE EXCEPTION 'Account % cannot take an expense', coalesce(p_code, '(none)')
            USING ERRCODE = '22023';
    END IF;
    RETURN v_account;
END $$;

-- The USD balance of an account (debits less credits) at the end of a day.
CREATE FUNCTION app.gl_account_balance(p_account uuid, p_through date)
RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT coalesce(sum(line.debit_cents - line.credit_cents), 0)::bigint
    FROM app.gl_journal_lines AS line
    JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
    WHERE line.account_id = p_account AND entry.entry_date <= p_through
$$;

-- A record is dated today or earlier, in an open ledger month.
CREATE FUNCTION app.gl_check_record_day(p_property uuid, p_day date)
RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_status text;
BEGIN
    IF p_day IS NULL OR p_day > app.gl_today(p_property) THEN
        RAISE EXCEPTION 'A money record is dated today or earlier' USING ERRCODE = '22023';
    END IF;
    SELECT period.status INTO v_status FROM app.gl_periods AS period
    WHERE period.property_id = p_property AND period.period_no <= 12
      AND p_day BETWEEN period.starts_on AND period.ends_on;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'The ledger has no month for %', to_char(p_day, 'DD/MM/YYYY')
            USING ERRCODE = '22023';
    END IF;
    IF v_status <> 'OPEN' THEN
        RAISE EXCEPTION 'The month of % is closed: date it in an open month',
            to_char(p_day, 'DD/MM/YYYY') USING ERRCODE = '55000';
    END IF;
END $$;
"""

# Suppliers and the Expense request flow.
REQUESTS = r"""
CREATE FUNCTION app.gl_add_supplier(p_property uuid, p_actor uuid, p_name text, p_phone text,
    p_note text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_id uuid := gen_random_uuid();
BEGIN
    -- Staff may add a supplier on an Expense request ("From the supplier list, or add a new one").
    PERFORM app.gl_require(p_actor, p_property, 'expenses.request');
    INSERT INTO app.gl_suppliers (id, property_id, name, phone, note, created_by)
    VALUES (v_id, p_property, btrim(p_name), nullif(btrim(p_phone), ''), nullif(btrim(p_note), ''),
        p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.supplier.added', 'gl_supplier', v_id,
        'Supplier added', p_correlation, jsonb_build_object('name', btrim(p_name)));
    RETURN v_id;
END $$;

-- An urgent report or a request paid with no advance: the expense and its entry.
CREATE FUNCTION app.gl_post_request_expense(p_request uuid, p_actor uuid, p_spent_cents bigint,
    p_spent_on date, p_bill_number text, p_supplier uuid, p_due_date date, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_request app.gl_expense_requests%ROWTYPE;
    v_account app.gl_accounts%ROWTYPE;
    v_from app.gl_accounts%ROWTYPE;
    v_expense uuid := gen_random_uuid();
    v_number text;
    v_entry uuid;
    v_lines jsonb;
    v_base jsonb;
    v_advance bigint;
    v_supplier uuid;
    v_from_id uuid;
BEGIN
    SELECT request.* INTO STRICT v_request FROM app.gl_expense_requests AS request
    WHERE request.id = p_request;
    SELECT account.* INTO STRICT v_account FROM app.gl_accounts AS account
    WHERE account.id = v_request.account_id;
    PERFORM app.gl_check_record_day(v_request.property_id, p_spent_on);
    IF p_spent_cents IS NULL OR p_spent_cents < 1 THEN
        RAISE EXCEPTION 'The bill amount is more than zero' USING ERRCODE = '22023';
    END IF;
    v_supplier := coalesce(p_supplier, v_request.supplier_id);
    v_number := app.gl_next_number(v_request.property_id, 'EX', p_spent_on);
    v_base := jsonb_build_object('memo', v_request.request_number, 'unit_id', v_request.unit_id,
        'supplier_id', v_supplier, 'expense_request_id', v_request.id);
    v_lines := jsonb_build_array(v_base || jsonb_build_object('account', v_account.code,
        'debit_cents', p_spent_cents));
    IF v_request.paid_how = 'ADVANCE' THEN
        -- The advance clears; the change goes back to cash, or the extra is owed to the staff.
        SELECT coalesce(sum(line.debit_cents - line.credit_cents), 0) INTO v_advance
        FROM app.gl_journal_lines AS line
        JOIN app.gl_accounts AS account ON account.id = line.account_id
        WHERE line.expense_request_id = v_request.id AND account.code = '1400';
        SELECT account.* INTO STRICT v_from FROM app.gl_accounts AS account
        WHERE account.id = v_request.paid_from_account_id;
        v_lines := v_lines || jsonb_build_array(v_base || jsonb_build_object('account', '1400',
            'credit_cents', v_advance));
        IF p_spent_cents < v_advance THEN
            v_lines := v_lines || jsonb_build_array(v_base || jsonb_build_object(
                'account', v_from.code, 'debit_cents', v_advance - p_spent_cents));
        ELSIF p_spent_cents > v_advance THEN
            v_lines := v_lines || jsonb_build_array(v_base || jsonb_build_object(
                'account', '2310', 'credit_cents', p_spent_cents - v_advance));
        END IF;
        v_from_id := v_request.paid_from_account_id;
    ELSIF v_request.paid_how = 'OWN_MONEY' THEN
        v_lines := v_lines || jsonb_build_array(v_base || jsonb_build_object('account', '2310',
            'credit_cents', p_spent_cents));
    ELSIF v_request.paid_how = 'PAY_LATER' THEN
        IF v_supplier IS NULL THEN
            RAISE EXCEPTION 'A bill to pay later names its supplier' USING ERRCODE = '22023';
        END IF;
        v_lines := v_lines || jsonb_build_array(v_base || jsonb_build_object('account', '2010',
            'credit_cents', p_spent_cents));
    ELSE
        SELECT account.* INTO STRICT v_from FROM app.gl_accounts AS account
        WHERE account.id = v_request.paid_from_account_id;
        v_lines := v_lines || jsonb_build_array(v_base || jsonb_build_object(
            'account', v_from.code, 'credit_cents', p_spent_cents)
            || CASE WHEN v_from.cash_kind = 'CASH_KHR' AND v_request.original_currency = 'KHR'
                    AND p_spent_cents = v_request.amount_cents
                THEN jsonb_build_object('original_currency', 'KHR',
                    'original_amount_minor', v_request.original_amount_minor,
                    'exchange_rate_record_id', v_request.exchange_rate_record_id)
                ELSE '{}'::jsonb END);
        v_from_id := v_request.paid_from_account_id;
    END IF;
    v_entry := app.gl_post_entry(v_request.property_id, p_spent_on, 'AUTO',
        left('Expense ' || v_number || ' for ' || v_request.request_number || ': '
            || v_request.description, 500),
        'EXPENSE', v_expense, 'expense:' || v_expense, NULL, p_actor, v_request.decided_by,
        p_correlation, v_lines);
    INSERT INTO app.gl_expenses (id, property_id, expense_number, expense_date, supplier_id,
        account_id, description, amount_cents, paid_from_account_id, bill_number,
        expense_request_id, unit_id, entry_id, status, created_by)
    VALUES (v_expense, v_request.property_id, v_number, p_spent_on, v_supplier,
        v_request.account_id, v_request.description, p_spent_cents, v_from_id,
        nullif(btrim(p_bill_number), ''), v_request.id, v_request.unit_id, v_entry, 'POSTED',
        p_actor);
    IF v_request.paid_how = 'PAY_LATER' THEN
        INSERT INTO app.gl_supplier_bills (id, property_id, bill_number, supplier_id,
            supplier_reference, bill_date, due_date, amount_cents, expense_id, status, created_by)
        VALUES (gen_random_uuid(), v_request.property_id,
            app.gl_next_number(v_request.property_id, 'SB', p_spent_on), v_supplier,
            nullif(btrim(p_bill_number), ''), p_spent_on,
            coalesce(p_due_date, p_spent_on + app.business_rule_value('SUPPLIER_BILL_DAYS',
                p_spent_on)::integer),
            p_spent_cents, v_expense, 'OPEN', p_actor);
    END IF;
    RETURN v_expense;
END $$;

CREATE FUNCTION app.gl_submit_expense_request(p_property uuid, p_actor uuid, p_kind text,
    p_account_code text, p_description text, p_reason text, p_amount_cents bigint,
    p_currency text, p_original_minor bigint, p_rate_record uuid, p_supplier uuid, p_unit uuid,
    p_spent_on date, p_paid_how text, p_paid_from_code text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_id uuid := gen_random_uuid();
    v_today date;
    v_account app.gl_accounts%ROWTYPE;
    v_from app.gl_accounts%ROWTYPE;
    v_from_id uuid;
    v_own boolean;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'expenses.request');
    v_today := app.gl_today(p_property);
    v_account := app.gl_spend_account(p_property, p_account_code);
    IF p_kind = 'URGENT_REPORT' THEN
        IF p_spent_on IS NULL OR p_spent_on > v_today THEN
            RAISE EXCEPTION 'An Expense report names the day the money was spent, today or earlier'
                USING ERRCODE = '22023';
        END IF;
        IF p_paid_how NOT IN ('OWN_MONEY', 'CASH') THEN
            RAISE EXCEPTION 'An Expense report is paid with the staff''s own money or petty cash'
                USING ERRCODE = '22023';
        END IF;
    ELSIF p_kind = 'REQUEST' THEN
        IF p_spent_on IS NOT NULL OR p_paid_how NOT IN ('ADVANCE', 'CASH', 'PAY_LATER') THEN
            RAISE EXCEPTION 'An Expense request is paid by advance, from cash or bank, or later'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        RAISE EXCEPTION 'An Expense request is a REQUEST or an URGENT_REPORT' USING ERRCODE = '22023';
    END IF;
    IF p_paid_how = 'CASH' THEN
        v_from := app.gl_money_account(p_property, p_paid_from_code);
        IF p_kind = 'URGENT_REPORT' AND v_from.cash_kind <> 'PETTY' THEN
            RAISE EXCEPTION 'An Expense report is paid with the staff''s own money or petty cash'
                USING ERRCODE = '22023';
        END IF;
        v_from_id := v_from.id;
    ELSIF p_paid_from_code IS NOT NULL THEN
        RAISE EXCEPTION 'Only a cash or bank payment names the account it is paid from'
            USING ERRCODE = '22023';
    END IF;
    IF p_unit IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.units AS unit
            WHERE unit.id = p_unit AND unit.property_id = p_property) THEN
        RAISE EXCEPTION 'The Unit is not in this Property' USING ERRCODE = '22023';
    END IF;
    IF p_supplier IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.gl_suppliers AS supplier
            WHERE supplier.id = p_supplier AND supplier.property_id = p_property
              AND supplier.is_active) THEN
        RAISE EXCEPTION 'The supplier is not on this Property''s list' USING ERRCODE = '22023';
    END IF;
    INSERT INTO app.gl_expense_requests (id, property_id, request_number, request_kind,
        requested_by, account_id, description, reason, amount_cents, original_currency,
        original_amount_minor, exchange_rate_record_id, supplier_id, unit_id, spent_on, status,
        paid_how, paid_from_account_id, created_by)
    VALUES (v_id, p_property, app.gl_next_number(p_property, 'ER', v_today), p_kind, p_actor,
        v_account.id, btrim(p_description), btrim(p_reason), p_amount_cents,
        coalesce(p_currency, 'USD'), p_original_minor, p_rate_record, p_supplier, p_unit,
        p_spent_on, 'WAITING', p_paid_how, v_from_id, p_actor);
    INSERT INTO app.gl_expense_request_events (id, expense_request_id, step, actor_id)
    VALUES (gen_random_uuid(), v_id, 'SUBMITTED', p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.expense_request.submitted',
        'gl_expense_request', v_id, btrim(p_reason), p_correlation,
        jsonb_build_object('kind', p_kind, 'account', p_account_code, 'amount_cents',
            p_amount_cents, 'paid_how', p_paid_how));
    -- D4: the Owner's own spending is approved at once and kept with a note.
    v_own := app.gl_can(p_actor, p_property, 'expenses.approve_over_limit');
    IF v_own THEN
        UPDATE app.gl_expense_requests SET status = 'APPROVED', decided_by = p_actor,
            decided_at = statement_timestamp(), own_spending_note = 'Owner''s own spending'
        WHERE id = v_id;
        INSERT INTO app.gl_expense_request_events (id, expense_request_id, step, note, actor_id)
        VALUES (gen_random_uuid(), v_id, 'APPROVED', 'Owner''s own spending', p_actor);
        IF p_kind = 'URGENT_REPORT' THEN
            PERFORM app.gl_post_request_expense(v_id, p_actor, p_amount_cents, p_spent_on, NULL,
                NULL, NULL, p_correlation);
            UPDATE app.gl_expense_requests SET status = 'DONE' WHERE id = v_id;
            INSERT INTO app.gl_expense_request_events (id, expense_request_id, step, actor_id)
            VALUES (gen_random_uuid(), v_id, 'DONE', p_actor);
        END IF;
    END IF;
    RETURN v_id;
END $$;

CREATE FUNCTION app.gl_decide_expense_request(p_request uuid, p_actor uuid, p_approve boolean,
    p_note text, p_correlation uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_request app.gl_expense_requests%ROWTYPE;
    v_limit bigint;
BEGIN
    SELECT request.* INTO v_request FROM app.gl_expense_requests AS request
    WHERE request.id = p_request FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No Expense request' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_request.property_id, 'expenses.approve');
    IF v_request.status <> 'WAITING' THEN
        RAISE EXCEPTION 'This Expense request is not waiting for approval' USING ERRCODE = '55000';
    END IF;
    IF p_actor = v_request.requested_by THEN
        RAISE EXCEPTION 'Nobody approves their own Expense request' USING ERRCODE = '42501';
    END IF;
    v_limit := app.business_rule_value('EXPENSE_LIMIT', app.gl_today(v_request.property_id));
    IF p_approve AND (v_limit IS NULL OR v_request.amount_cents > v_limit) THEN
        PERFORM app.gl_require(p_actor, v_request.property_id, 'expenses.approve_over_limit');
    END IF;
    IF NOT p_approve AND (p_note IS NULL OR btrim(p_note) = '') THEN
        RAISE EXCEPTION 'Say why the Expense request is not approved' USING ERRCODE = '22023';
    END IF;
    UPDATE app.gl_expense_requests SET status = CASE WHEN p_approve THEN 'APPROVED'
            ELSE 'REFUSED' END,
        decided_by = p_actor, decided_at = statement_timestamp(),
        decision_note = nullif(btrim(p_note), '')
    WHERE id = p_request;
    INSERT INTO app.gl_expense_request_events (id, expense_request_id, step, note, actor_id)
    VALUES (gen_random_uuid(), p_request, CASE WHEN p_approve THEN 'APPROVED' ELSE 'REFUSED' END,
        nullif(btrim(p_note), ''), p_actor);
    PERFORM app.gl_audit(v_request.property_id, p_actor,
        CASE WHEN p_approve THEN 'ledger.expense_request.approved'
            ELSE 'ledger.expense_request.refused' END,
        'gl_expense_request', p_request, coalesce(nullif(btrim(p_note), ''), 'Approved'),
        p_correlation, jsonb_build_object('amount_cents', v_request.amount_cents,
            'expense_limit_cents', v_limit));
    -- An approved Expense report records the expense at once.
    IF p_approve AND v_request.request_kind = 'URGENT_REPORT' THEN
        PERFORM app.gl_post_request_expense(p_request, p_actor, v_request.amount_cents,
            v_request.spent_on, NULL, NULL, NULL, p_correlation);
        UPDATE app.gl_expense_requests SET status = 'DONE' WHERE id = p_request;
        INSERT INTO app.gl_expense_request_events (id, expense_request_id, step, actor_id)
        VALUES (gen_random_uuid(), p_request, 'DONE', p_actor);
    END IF;
END $$;

CREATE FUNCTION app.gl_give_advance(p_request uuid, p_actor uuid, p_from_code text,
    p_paid_on date, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_request app.gl_expense_requests%ROWTYPE;
    v_from app.gl_accounts%ROWTYPE;
    v_entry uuid;
BEGIN
    SELECT request.* INTO v_request FROM app.gl_expense_requests AS request
    WHERE request.id = p_request FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No Expense request' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_request.property_id, 'expenses.record');
    IF v_request.status <> 'APPROVED' OR v_request.paid_how <> 'ADVANCE' THEN
        RAISE EXCEPTION 'An advance is given for an approved request paid by advance'
            USING ERRCODE = '55000';
    END IF;
    v_from := app.gl_money_account(v_request.property_id, p_from_code);
    PERFORM app.gl_check_record_day(v_request.property_id, p_paid_on);
    v_entry := app.gl_post_entry(v_request.property_id, p_paid_on, 'AUTO',
        left('Advance for ' || v_request.request_number || ': ' || v_request.description, 500),
        'EXPENSE_REQUEST', p_request, 'expense_request:' || p_request || ':advance', NULL,
        p_actor, v_request.decided_by, p_correlation, jsonb_build_array(
            jsonb_build_object('account', '1400', 'debit_cents', v_request.amount_cents,
                'memo', v_request.request_number, 'expense_request_id', p_request),
            jsonb_build_object('account', v_from.code, 'credit_cents', v_request.amount_cents,
                'memo', v_request.request_number, 'expense_request_id', p_request)));
    UPDATE app.gl_expense_requests SET status = 'PAID_OUT', paid_out_entry_id = v_entry,
        paid_from_account_id = v_from.id
    WHERE id = p_request;
    INSERT INTO app.gl_expense_request_events (id, expense_request_id, step, actor_id)
    VALUES (gen_random_uuid(), p_request, 'PAID_OUT', p_actor);
    PERFORM app.gl_audit(v_request.property_id, p_actor, 'ledger.expense_request.advance_given',
        'gl_expense_request', p_request, 'Advance given', p_correlation,
        jsonb_build_object('amount_cents', v_request.amount_cents, 'from', p_from_code));
    RETURN v_entry;
END $$;

CREATE FUNCTION app.gl_record_request_bill(p_request uuid, p_actor uuid, p_spent_cents bigint,
    p_spent_on date, p_bill_number text, p_supplier uuid, p_due_date date, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_request app.gl_expense_requests%ROWTYPE;
    v_expense uuid;
BEGIN
    SELECT request.* INTO v_request FROM app.gl_expense_requests AS request
    WHERE request.id = p_request FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No Expense request' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_request.property_id, 'expenses.record');
    IF v_request.request_kind <> 'REQUEST' OR NOT (
        (v_request.status = 'PAID_OUT' AND v_request.paid_how = 'ADVANCE')
        OR (v_request.status = 'APPROVED' AND v_request.paid_how IN ('CASH', 'PAY_LATER'))) THEN
        RAISE EXCEPTION 'The bill is recorded for an approved request, after its advance if it has one'
            USING ERRCODE = '55000';
    END IF;
    -- Only an advance can come back with more spent: the extra is owed to the staff.
    IF v_request.paid_how <> 'ADVANCE' AND p_spent_cents > v_request.amount_cents THEN
        RAISE EXCEPTION 'The bill is more than the approved amount; send a new request for the rest'
            USING ERRCODE = '22023';
    END IF;
    IF p_supplier IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.gl_suppliers AS supplier
            WHERE supplier.id = p_supplier AND supplier.property_id = v_request.property_id) THEN
        RAISE EXCEPTION 'The supplier is not on this Property''s list' USING ERRCODE = '22023';
    END IF;
    v_expense := app.gl_post_request_expense(p_request, p_actor, p_spent_cents, p_spent_on,
        p_bill_number, p_supplier, p_due_date, p_correlation);
    UPDATE app.gl_expense_requests SET status = 'DONE' WHERE id = p_request;
    INSERT INTO app.gl_expense_request_events (id, expense_request_id, step, actor_id)
    VALUES (gen_random_uuid(), p_request, CASE WHEN v_request.paid_how = 'ADVANCE'
        THEN 'BILL_BACK' ELSE 'DONE' END, p_actor);
    PERFORM app.gl_audit(v_request.property_id, p_actor, 'ledger.expense_request.bill_recorded',
        'gl_expense_request', p_request, 'Bill recorded', p_correlation,
        jsonb_build_object('expense_id', v_expense, 'spent_cents', p_spent_cents));
    RETURN v_expense;
END $$;

CREATE FUNCTION app.gl_pay_back_staff(p_request uuid, p_actor uuid, p_from_code text,
    p_paid_on date, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_request app.gl_expense_requests%ROWTYPE;
    v_from app.gl_accounts%ROWTYPE;
    v_owed bigint;
    v_id uuid := gen_random_uuid();
    v_entry uuid;
BEGIN
    SELECT request.* INTO v_request FROM app.gl_expense_requests AS request
    WHERE request.id = p_request FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No Expense request' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_request.property_id, 'expenses.record');
    SELECT coalesce(sum(line.credit_cents - line.debit_cents), 0) INTO v_owed
    FROM app.gl_journal_lines AS line
    JOIN app.gl_accounts AS account ON account.id = line.account_id
    WHERE line.expense_request_id = p_request AND account.code = '2310';
    IF v_owed <= 0 THEN
        RAISE EXCEPTION 'Nothing is owed to the staff for this request' USING ERRCODE = '55000';
    END IF;
    v_from := app.gl_money_account(v_request.property_id, p_from_code);
    PERFORM app.gl_check_record_day(v_request.property_id, p_paid_on);
    v_entry := app.gl_post_entry(v_request.property_id, p_paid_on, 'AUTO',
        left('Staff paid back for ' || v_request.request_number, 500), 'STAFF_PAYBACK', v_id,
        'staff_payback:' || v_id, NULL, p_actor, NULL, p_correlation, jsonb_build_array(
            jsonb_build_object('account', '2310', 'debit_cents', v_owed,
                'memo', v_request.request_number, 'expense_request_id', p_request),
            jsonb_build_object('account', v_from.code, 'credit_cents', v_owed,
                'memo', v_request.request_number, 'expense_request_id', p_request)));
    INSERT INTO app.gl_staff_paybacks (id, property_id, expense_request_id, paid_on,
        from_account_id, amount_cents, entry_id, created_by)
    VALUES (v_id, v_request.property_id, p_request, p_paid_on, v_from.id, v_owed, v_entry, p_actor);
    PERFORM app.gl_audit(v_request.property_id, p_actor, 'ledger.expense_request.paid_back',
        'gl_expense_request', p_request, 'Staff paid back', p_correlation,
        jsonb_build_object('amount_cents', v_owed, 'from', p_from_code));
    RETURN v_id;
END $$;

CREATE FUNCTION app.gl_void_expense_request(p_request uuid, p_actor uuid, p_reason text,
    p_correlation uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_request app.gl_expense_requests%ROWTYPE;
BEGIN
    SELECT request.* INTO v_request FROM app.gl_expense_requests AS request
    WHERE request.id = p_request FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No Expense request' USING ERRCODE = '22023';
    END IF;
    -- The person who sent it may take back a waiting request; otherwise an approver voids it.
    IF NOT (p_actor = v_request.requested_by AND v_request.status = 'WAITING') THEN
        PERFORM app.gl_require(p_actor, v_request.property_id, 'expenses.approve');
    END IF;
    IF v_request.status NOT IN ('WAITING', 'APPROVED') THEN
        RAISE EXCEPTION 'Money has moved for this request: void its expense instead'
            USING ERRCODE = '55000';
    END IF;
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'A void needs a reason' USING ERRCODE = '22023';
    END IF;
    UPDATE app.gl_expense_requests SET status = 'VOID', void_reason = btrim(p_reason),
        voided_at = statement_timestamp(), voided_by = p_actor
    WHERE id = p_request;
    INSERT INTO app.gl_expense_request_events (id, expense_request_id, step, note, actor_id)
    VALUES (gen_random_uuid(), p_request, 'VOID', btrim(p_reason), p_actor);
    PERFORM app.gl_audit(v_request.property_id, p_actor, 'ledger.expense_request.voided',
        'gl_expense_request', p_request, btrim(p_reason), p_correlation, '{}'::jsonb);
END $$;
"""

# Expenses recorded straight, supplier bills and their payments.
EXPENSES = r"""
CREATE FUNCTION app.gl_record_expense(p_property uuid, p_actor uuid, p_expense_date date,
    p_account_code text, p_description text, p_amount_cents bigint, p_currency text,
    p_original_minor bigint, p_rate_record uuid, p_paid_from_code text, p_supplier uuid,
    p_bill_number text, p_due_date date, p_unit uuid, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
    v_from app.gl_accounts%ROWTYPE;
    v_id uuid := gen_random_uuid();
    v_number text;
    v_entry uuid;
    v_base jsonb;
    v_credit jsonb;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'expenses.record');
    v_account := app.gl_spend_account(p_property, p_account_code);
    PERFORM app.gl_check_record_day(p_property, p_expense_date);
    IF p_paid_from_code IS NULL THEN
        -- Pay later: the expense becomes a supplier bill.
        PERFORM app.gl_require(p_actor, p_property, 'supplier_bills.manage');
        IF p_supplier IS NULL THEN
            RAISE EXCEPTION 'A bill to pay later names its supplier' USING ERRCODE = '22023';
        END IF;
    ELSE
        v_from := app.gl_money_account(p_property, p_paid_from_code);
    END IF;
    IF p_supplier IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.gl_suppliers AS supplier
            WHERE supplier.id = p_supplier AND supplier.property_id = p_property) THEN
        RAISE EXCEPTION 'The supplier is not on this Property''s list' USING ERRCODE = '22023';
    END IF;
    IF p_unit IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.units AS unit
            WHERE unit.id = p_unit AND unit.property_id = p_property) THEN
        RAISE EXCEPTION 'The Unit is not in this Property' USING ERRCODE = '22023';
    END IF;
    v_number := app.gl_next_number(p_property, 'EX', p_expense_date);
    v_base := jsonb_build_object('memo', v_number, 'unit_id', p_unit, 'supplier_id', p_supplier);
    IF p_paid_from_code IS NULL THEN
        v_credit := v_base || jsonb_build_object('account', '2010', 'credit_cents', p_amount_cents);
    ELSE
        v_credit := v_base || jsonb_build_object('account', v_from.code,
            'credit_cents', p_amount_cents)
            || CASE WHEN v_from.cash_kind = 'CASH_KHR' AND coalesce(p_currency, 'USD') = 'KHR'
                THEN jsonb_build_object('original_currency', 'KHR',
                    'original_amount_minor', p_original_minor,
                    'exchange_rate_record_id', p_rate_record)
                ELSE '{}'::jsonb END;
    END IF;
    v_entry := app.gl_post_entry(p_property, p_expense_date, 'AUTO',
        left('Expense ' || v_number || ': ' || btrim(p_description), 500), 'EXPENSE', v_id,
        'expense:' || v_id, NULL, p_actor, NULL, p_correlation, jsonb_build_array(
            v_base || jsonb_build_object('account', v_account.code, 'debit_cents', p_amount_cents),
            v_credit));
    INSERT INTO app.gl_expenses (id, property_id, expense_number, expense_date, supplier_id,
        account_id, description, amount_cents, original_currency, original_amount_minor,
        exchange_rate_record_id, paid_from_account_id, bill_number, unit_id, entry_id, status,
        created_by)
    VALUES (v_id, p_property, v_number, p_expense_date, p_supplier, v_account.id,
        btrim(p_description), p_amount_cents, coalesce(p_currency, 'USD'), p_original_minor,
        p_rate_record, v_from.id, nullif(btrim(p_bill_number), ''), p_unit, v_entry, 'POSTED',
        p_actor);
    IF p_paid_from_code IS NULL THEN
        INSERT INTO app.gl_supplier_bills (id, property_id, bill_number, supplier_id,
            supplier_reference, bill_date, due_date, amount_cents, expense_id, status, created_by)
        VALUES (gen_random_uuid(), p_property,
            app.gl_next_number(p_property, 'SB', p_expense_date), p_supplier,
            nullif(btrim(p_bill_number), ''), p_expense_date,
            coalesce(p_due_date, p_expense_date + app.business_rule_value('SUPPLIER_BILL_DAYS',
                p_expense_date)::integer),
            p_amount_cents, v_id, 'OPEN', p_actor);
    END IF;
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.expense.recorded', 'gl_expense', v_id,
        left(btrim(p_description), 500), p_correlation, jsonb_build_object('account',
            p_account_code, 'amount_cents', p_amount_cents, 'paid_from', p_paid_from_code));
    RETURN v_id;
END $$;

CREATE FUNCTION app.gl_void_expense(p_expense uuid, p_actor uuid, p_reason text,
    p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_expense app.gl_expenses%ROWTYPE;
    v_bill app.gl_supplier_bills%ROWTYPE;
    v_entry uuid;
    v_today date;
BEGIN
    SELECT expense.* INTO v_expense FROM app.gl_expenses AS expense
    WHERE expense.id = p_expense FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No expense' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_expense.property_id, 'expenses.record');
    IF v_expense.status <> 'POSTED' THEN
        RAISE EXCEPTION 'This expense is already void' USING ERRCODE = '55000';
    END IF;
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'A void needs a reason' USING ERRCODE = '22023';
    END IF;
    SELECT bill.* INTO v_bill FROM app.gl_supplier_bills AS bill
    WHERE bill.expense_id = p_expense FOR UPDATE;
    IF FOUND THEN
        IF EXISTS (SELECT 1 FROM app.gl_bill_payments AS payment
                   WHERE payment.supplier_bill_id = v_bill.id
                     AND NOT EXISTS (SELECT 1 FROM app.gl_bill_payment_reversals AS reversal
                                     WHERE reversal.bill_payment_id = payment.id)) THEN
            RAISE EXCEPTION 'Reverse the payments of supplier bill % first', v_bill.bill_number
                USING ERRCODE = '55000';
        END IF;
        IF v_bill.status = 'OPEN' THEN
            UPDATE app.gl_supplier_bills SET status = 'VOID', void_reason = btrim(p_reason),
                voided_at = statement_timestamp(), voided_by = p_actor
            WHERE id = v_bill.id;
        END IF;
    END IF;
    v_today := app.gl_today(v_expense.property_id);
    PERFORM app.gl_check_record_day(v_expense.property_id, v_today);
    v_entry := app.gl_reverse_entry(v_expense.entry_id, v_today, btrim(p_reason), p_actor,
        'expense:' || p_expense || ':void', p_correlation);
    UPDATE app.gl_expenses SET status = 'VOID', void_entry_id = v_entry,
        void_reason = btrim(p_reason), voided_at = statement_timestamp(), voided_by = p_actor
    WHERE id = p_expense;
    PERFORM app.gl_audit(v_expense.property_id, p_actor, 'ledger.expense.voided', 'gl_expense',
        p_expense, btrim(p_reason), p_correlation,
        jsonb_build_object('amount_cents', v_expense.amount_cents));
    RETURN v_entry;
END $$;

CREATE FUNCTION app.gl_pay_supplier_bill(p_bill uuid, p_actor uuid, p_from_code text,
    p_paid_on date, p_amount_cents bigint, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_bill app.gl_supplier_bills%ROWTYPE;
    v_from app.gl_accounts%ROWTYPE;
    v_open bigint;
    v_id uuid := gen_random_uuid();
    v_entry uuid;
BEGIN
    SELECT bill.* INTO v_bill FROM app.gl_supplier_bills AS bill WHERE bill.id = p_bill FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No supplier bill' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_bill.property_id, 'supplier_bills.pay');
    IF v_bill.status <> 'OPEN' THEN
        RAISE EXCEPTION 'This supplier bill is not open' USING ERRCODE = '55000';
    END IF;
    SELECT v_bill.amount_cents - coalesce(sum(payment.amount_cents), 0) INTO v_open
    FROM app.gl_bill_payments AS payment
    WHERE payment.supplier_bill_id = p_bill
      AND NOT EXISTS (SELECT 1 FROM app.gl_bill_payment_reversals AS reversal
                      WHERE reversal.bill_payment_id = payment.id);
    IF p_amount_cents IS NULL OR p_amount_cents < 1 OR p_amount_cents > v_open THEN
        RAISE EXCEPTION 'Pay from 0.01 up to the % cents still to pay', v_open
            USING ERRCODE = '22023';
    END IF;
    v_from := app.gl_money_account(v_bill.property_id, p_from_code);
    PERFORM app.gl_check_record_day(v_bill.property_id, p_paid_on);
    v_entry := app.gl_post_entry(v_bill.property_id, p_paid_on, 'AUTO',
        'Supplier bill ' || v_bill.bill_number || ' paid', 'BILL_PAYMENT', v_id,
        'bill_payment:' || v_id, NULL, p_actor, NULL, p_correlation, jsonb_build_array(
            jsonb_build_object('account', '2010', 'debit_cents', p_amount_cents,
                'memo', v_bill.bill_number, 'supplier_id', v_bill.supplier_id),
            jsonb_build_object('account', v_from.code, 'credit_cents', p_amount_cents,
                'memo', v_bill.bill_number, 'supplier_id', v_bill.supplier_id)));
    INSERT INTO app.gl_bill_payments (id, property_id, supplier_bill_id, paid_on, amount_cents,
        paid_from_account_id, entry_id, created_by)
    VALUES (v_id, v_bill.property_id, p_bill, p_paid_on, p_amount_cents, v_from.id, v_entry,
        p_actor);
    IF p_amount_cents = v_open THEN
        UPDATE app.gl_supplier_bills SET status = 'PAID' WHERE id = p_bill;
    END IF;
    PERFORM app.gl_audit(v_bill.property_id, p_actor, 'ledger.supplier_bill.paid',
        'gl_supplier_bill', p_bill, 'Supplier bill paid', p_correlation,
        jsonb_build_object('amount_cents', p_amount_cents, 'from', p_from_code,
            'still_to_pay_cents', v_open - p_amount_cents));
    RETURN v_id;
END $$;

CREATE FUNCTION app.gl_reverse_bill_payment(p_payment uuid, p_actor uuid, p_reason text,
    p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_payment app.gl_bill_payments%ROWTYPE;
    v_entry uuid;
    v_today date;
BEGIN
    SELECT payment.* INTO v_payment FROM app.gl_bill_payments AS payment
    WHERE payment.id = p_payment;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No supplier bill payment' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_payment.property_id, 'supplier_bills.pay');
    PERFORM 1 FROM app.gl_supplier_bills AS bill WHERE bill.id = v_payment.supplier_bill_id
    FOR UPDATE;
    IF EXISTS (SELECT 1 FROM app.gl_bill_payment_reversals AS reversal
               WHERE reversal.bill_payment_id = p_payment) THEN
        RAISE EXCEPTION 'This payment is already reversed' USING ERRCODE = '55000';
    END IF;
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'A reversal needs a reason' USING ERRCODE = '22023';
    END IF;
    v_today := app.gl_today(v_payment.property_id);
    PERFORM app.gl_check_record_day(v_payment.property_id, v_today);
    v_entry := app.gl_reverse_entry(v_payment.entry_id, v_today, btrim(p_reason), p_actor,
        'bill_payment:' || p_payment || ':reversal', p_correlation);
    INSERT INTO app.gl_bill_payment_reversals (id, bill_payment_id, entry_id, reason, created_by)
    VALUES (gen_random_uuid(), p_payment, v_entry, btrim(p_reason), p_actor);
    UPDATE app.gl_supplier_bills SET status = 'OPEN'
    WHERE id = v_payment.supplier_bill_id AND status = 'PAID';
    PERFORM app.gl_audit(v_payment.property_id, p_actor, 'ledger.supplier_bill.payment_reversed',
        'gl_supplier_bill', v_payment.supplier_bill_id, btrim(p_reason), p_correlation,
        jsonb_build_object('amount_cents', v_payment.amount_cents));
    RETURN v_entry;
END $$;
"""

# Money moves, owner money, petty cash and cash counts.
MONEY = r"""
CREATE FUNCTION app.gl_move_money(p_property uuid, p_actor uuid, p_moved_on date,
    p_from_code text, p_to_code text, p_amount_cents bigint, p_received_cents bigint,
    p_riel_minor bigint, p_rate_record uuid, p_note text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_from app.gl_accounts%ROWTYPE;
    v_to app.gl_accounts%ROWTYPE;
    v_id uuid := gen_random_uuid();
    v_number text;
    v_received bigint := coalesce(p_received_cents, p_amount_cents);
    v_difference bigint;
    v_riel jsonb := '{}'::jsonb;
    v_lines jsonb;
    v_entry uuid;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.money_move');
    v_from := app.gl_money_account(p_property, p_from_code);
    v_to := app.gl_money_account(p_property, p_to_code);
    IF v_from.id = v_to.id THEN
        RAISE EXCEPTION 'Money moves between two different accounts' USING ERRCODE = '22023';
    END IF;
    IF v_to.cash_kind = 'PETTY' OR v_from.cash_kind = 'PETTY' THEN
        RAISE EXCEPTION 'Petty cash is topped up with its own step' USING ERRCODE = '22023';
    END IF;
    IF p_amount_cents IS NULL OR p_amount_cents < 1 OR v_received < 1 THEN
        RAISE EXCEPTION 'The amount is more than zero' USING ERRCODE = '22023';
    END IF;
    -- An exchange difference only comes from changing riel.
    IF v_received <> p_amount_cents AND 'CASH_KHR' NOT IN (v_from.cash_kind, v_to.cash_kind) THEN
        RAISE EXCEPTION 'Only a riel change can have an exchange difference'
            USING ERRCODE = '22023';
    END IF;
    IF (p_riel_minor IS NULL) <> (p_rate_record IS NULL)
        OR (p_riel_minor IS NOT NULL AND 'CASH_KHR' NOT IN (v_from.cash_kind, v_to.cash_kind)) THEN
        RAISE EXCEPTION 'Riel amounts come with their rate, on a riel cash account'
            USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_check_record_day(p_property, p_moved_on);
    IF p_riel_minor IS NOT NULL THEN
        v_riel := jsonb_build_object('original_currency', 'KHR',
            'original_amount_minor', p_riel_minor, 'exchange_rate_record_id', p_rate_record);
    END IF;
    v_number := app.gl_next_number(p_property, 'MV', p_moved_on);
    v_difference := v_received - p_amount_cents;
    v_lines := jsonb_build_array(
        jsonb_build_object('account', v_to.code, 'debit_cents', v_received, 'memo', v_number)
            || CASE WHEN v_to.cash_kind = 'CASH_KHR' THEN v_riel ELSE '{}'::jsonb END,
        jsonb_build_object('account', v_from.code, 'credit_cents', p_amount_cents,
            'memo', v_number)
            || CASE WHEN v_from.cash_kind = 'CASH_KHR' THEN v_riel ELSE '{}'::jsonb END);
    IF v_difference > 0 THEN
        v_lines := v_lines || jsonb_build_array(jsonb_build_object('account', '4100',
            'credit_cents', v_difference, 'memo', v_number));
    ELSIF v_difference < 0 THEN
        v_lines := v_lines || jsonb_build_array(jsonb_build_object('account', '4100',
            'debit_cents', -v_difference, 'memo', v_number));
    END IF;
    v_entry := app.gl_post_entry(p_property, p_moved_on, 'AUTO',
        left('Money move ' || v_number || ' from ' || v_from.code || ' to ' || v_to.code
            || coalesce(': ' || nullif(btrim(p_note), ''), ''), 500),
        'MONEY_MOVE', v_id, 'money_move:' || v_id, NULL, p_actor, NULL, p_correlation, v_lines);
    INSERT INTO app.gl_money_moves (id, property_id, move_number, moved_on, from_account_id,
        to_account_id, amount_cents, original_currency, original_amount_minor,
        exchange_rate_record_id, exchange_difference_cents, note, entry_id, created_by)
    VALUES (v_id, p_property, v_number, p_moved_on, v_from.id, v_to.id, p_amount_cents,
        CASE WHEN p_riel_minor IS NULL THEN 'USD' ELSE 'KHR' END, p_riel_minor, p_rate_record,
        v_difference, nullif(btrim(p_note), ''), v_entry, p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.money_move.recorded', 'gl_money_move',
        v_id, coalesce(nullif(btrim(p_note), ''), 'Money moved'), p_correlation,
        jsonb_build_object('from', p_from_code, 'to', p_to_code, 'amount_cents', p_amount_cents,
            'received_cents', v_received));
    RETURN v_id;
END $$;

CREATE FUNCTION app.gl_record_owner_money(p_property uuid, p_actor uuid, p_direction text,
    p_moved_on date, p_account_code text, p_amount_cents bigint, p_note text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_cash app.gl_accounts%ROWTYPE;
    v_id uuid := gen_random_uuid();
    v_entry uuid;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.owner_money');
    IF p_direction NOT IN ('IN', 'OUT') THEN
        RAISE EXCEPTION 'Owner money goes IN or OUT' USING ERRCODE = '22023';
    END IF;
    v_cash := app.gl_money_account(p_property, p_account_code);
    PERFORM app.gl_check_record_day(p_property, p_moved_on);
    v_entry := app.gl_post_entry(p_property, p_moved_on, 'AUTO',
        left(CASE p_direction WHEN 'IN' THEN 'Owner money in' ELSE 'Owner money out' END
            || coalesce(': ' || nullif(btrim(p_note), ''), ''), 500),
        'OWNER_MONEY', v_id, 'owner_money:' || v_id, NULL, p_actor, NULL, p_correlation,
        CASE p_direction WHEN 'IN' THEN jsonb_build_array(
                jsonb_build_object('account', v_cash.code, 'debit_cents', p_amount_cents),
                jsonb_build_object('account', '3000', 'credit_cents', p_amount_cents))
            ELSE jsonb_build_array(
                jsonb_build_object('account', '3100', 'debit_cents', p_amount_cents),
                jsonb_build_object('account', v_cash.code, 'credit_cents', p_amount_cents)) END);
    INSERT INTO app.gl_owner_money (id, property_id, direction, moved_on, account_id,
        amount_cents, note, entry_id, created_by)
    VALUES (v_id, p_property, p_direction, p_moved_on, v_cash.id, p_amount_cents,
        nullif(btrim(p_note), ''), v_entry, p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.owner_money.recorded', 'gl_owner_money',
        v_id, coalesce(nullif(btrim(p_note), ''), 'Owner money'), p_correlation,
        jsonb_build_object('direction', p_direction, 'account', p_account_code,
            'amount_cents', p_amount_cents));
    RETURN v_id;
END $$;

CREATE FUNCTION app.gl_top_up_petty_cash(p_property uuid, p_actor uuid, p_topped_up_on date,
    p_from_code text, p_amount_cents bigint, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_from app.gl_accounts%ROWTYPE;
    v_petty app.gl_accounts%ROWTYPE;
    v_float bigint;
    v_balance bigint;
    v_id uuid := gen_random_uuid();
    v_entry uuid;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.petty_cash');
    v_from := app.gl_money_account(p_property, p_from_code);
    IF v_from.cash_kind NOT IN ('CASH_USD', 'BANK') THEN
        RAISE EXCEPTION 'Petty cash is topped up from Cash on hand (USD) or the bank'
            USING ERRCODE = '22023';
    END IF;
    SELECT account.* INTO v_petty FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.cash_kind = 'PETTY' AND account.is_active
    ORDER BY account.code LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No Petty cash account is turned on' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_check_record_day(p_property, p_topped_up_on);
    -- Up to the Petty cash amount (business rule), counting what petty cash holds now.
    v_float := app.business_rule_value('PETTY_CASH', p_topped_up_on);
    v_balance := app.gl_account_balance(v_petty.id, app.gl_today(p_property));
    IF p_amount_cents IS NULL OR p_amount_cents < 1
        OR v_float IS NULL OR v_balance + p_amount_cents > v_float THEN
        RAISE EXCEPTION 'Petty cash holds % cents; a top-up brings it up to % cents at most',
            v_balance, coalesce(v_float, 0) USING ERRCODE = '22023';
    END IF;
    v_entry := app.gl_post_entry(p_property, p_topped_up_on, 'AUTO', 'Petty cash topped up',
        'PETTY_CASH_TOPUP', v_id, 'petty_cash_topup:' || v_id, NULL, p_actor, NULL,
        p_correlation, jsonb_build_array(
            jsonb_build_object('account', v_petty.code, 'debit_cents', p_amount_cents),
            jsonb_build_object('account', v_from.code, 'credit_cents', p_amount_cents)));
    INSERT INTO app.gl_petty_cash_topups (id, property_id, topped_up_on, from_account_id,
        amount_cents, entry_id, created_by)
    VALUES (v_id, p_property, p_topped_up_on, v_from.id, p_amount_cents, v_entry, p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.petty_cash.topped_up',
        'gl_petty_cash_topup', v_id, 'Petty cash topped up', p_correlation,
        jsonb_build_object('amount_cents', p_amount_cents, 'from', p_from_code,
            'float_cents', v_float, 'balance_before_cents', v_balance));
    RETURN v_id;
END $$;

-- A cash count compares in USD cents. Riel cash is counted in riel and turned into dollars at
-- the rate of the given exchange rate record.
CREATE FUNCTION app.gl_count_cash(p_property uuid, p_actor uuid, p_account_code text,
    p_counted_on date, p_counted_cents bigint, p_counted_riel bigint, p_rate_record uuid,
    p_reason text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_cash app.gl_accounts%ROWTYPE;
    v_period uuid;
    v_rate bigint;
    v_counted bigint;
    v_book bigint;
    v_difference bigint;
    v_id uuid := gen_random_uuid();
    v_entry uuid;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.cash_count');
    v_cash := app.gl_money_account(p_property, p_account_code);
    IF v_cash.cash_kind = 'BANK' THEN
        RAISE EXCEPTION 'A bank account is matched, not counted' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_check_record_day(p_property, p_counted_on);
    IF v_cash.cash_kind = 'CASH_KHR' THEN
        IF p_counted_riel IS NULL OR p_counted_riel < 0 OR p_rate_record IS NULL
            OR p_counted_cents IS NOT NULL THEN
            RAISE EXCEPTION 'Riel cash is counted in riel, with the rate' USING ERRCODE = '22023';
        END IF;
        SELECT rate.system_rate_khr_per_usd INTO v_rate FROM app.exchange_rate_records AS rate
        WHERE rate.id = p_rate_record;
        IF v_rate IS NULL OR v_rate <= 0 THEN
            RAISE EXCEPTION 'No riel rate in that exchange rate record' USING ERRCODE = '22023';
        END IF;
        v_counted := round(p_counted_riel * 100.0 / v_rate)::bigint;
    ELSE
        IF p_counted_cents IS NULL OR p_counted_cents < 0 OR p_counted_riel IS NOT NULL
            OR p_rate_record IS NOT NULL THEN
            RAISE EXCEPTION 'Dollar cash is counted in dollars' USING ERRCODE = '22023';
        END IF;
        v_counted := p_counted_cents;
    END IF;
    SELECT period.id INTO STRICT v_period FROM app.gl_periods AS period
    WHERE period.property_id = p_property AND period.period_no <= 12
      AND p_counted_on BETWEEN period.starts_on AND period.ends_on;
    -- One count per cash account each month (the month-end count of the close checks).
    IF EXISTS (SELECT 1 FROM app.gl_cash_counts AS count_row
               WHERE count_row.account_id = v_cash.id AND count_row.period_id = v_period) THEN
        RAISE EXCEPTION 'Account % is already counted for this month', v_cash.code
            USING ERRCODE = '55000';
    END IF;
    v_book :=app.gl_account_balance(v_cash.id, p_counted_on);
    v_difference := v_counted - v_book;
    IF v_difference <> 0 THEN
        IF p_reason IS NULL OR btrim(p_reason) = '' THEN
            RAISE EXCEPTION 'A cash count difference needs a reason' USING ERRCODE = '22023';
        END IF;
        v_entry := app.gl_post_entry(p_property, p_counted_on, 'AUTO',
            left('Cash count difference on ' || v_cash.code || ': ' || btrim(p_reason), 500),
            'CASH_COUNT', v_id, 'cash_count:' || v_id, NULL, p_actor, NULL, p_correlation,
            CASE WHEN v_difference > 0 THEN jsonb_build_array(
                    jsonb_build_object('account', v_cash.code, 'debit_cents', v_difference),
                    jsonb_build_object('account', '6180', 'credit_cents', v_difference))
                ELSE jsonb_build_array(
                    jsonb_build_object('account', '6180', 'debit_cents', -v_difference),
                    jsonb_build_object('account', v_cash.code, 'credit_cents', -v_difference)) END);
    END IF;
    INSERT INTO app.gl_cash_counts (id, property_id, account_id, period_id, counted_on,
        counted_minor, book_minor, difference_entry_id, note, counted_riel,
        exchange_rate_record_id, created_by)
    VALUES (v_id, p_property, v_cash.id, v_period, p_counted_on, v_counted, v_book, v_entry,
        nullif(btrim(p_reason), ''), p_counted_riel, p_rate_record, p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.cash.counted', 'gl_cash_count', v_id,
        coalesce(nullif(btrim(p_reason), ''), 'Cash counted'), p_correlation,
        jsonb_build_object('account', p_account_code, 'counted_cents', v_counted,
            'book_cents', v_book, 'difference_cents', v_difference));
    RETURN v_id;
END $$;
"""


def _literal_colons(sql: str) -> str:
    """Keep ``'expense:...:void'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def upgrade() -> None:
    op.execute(
        """
        -- How a request is paid, chosen when it is sent (DESIGN.md round 21 "Paid from").
        ALTER TABLE app.gl_expense_requests
            ADD COLUMN paid_how text NOT NULL CHECK (paid_how IN
                ('ADVANCE', 'CASH', 'PAY_LATER', 'OWN_MONEY')),
            ADD CONSTRAINT gl_er_paid_how CHECK (
                (request_kind = 'URGENT_REPORT' AND paid_how IN ('OWN_MONEY', 'CASH'))
                OR (request_kind = 'REQUEST' AND paid_how IN ('ADVANCE', 'CASH', 'PAY_LATER')));
        COMMENT ON COLUMN app.gl_expense_requests.paid_how IS
            'ADVANCE to staff, CASH from paid_from_account_id (petty cash for a report), PAY_LATER '
            '(a supplier bill), or OWN_MONEY (an urgent report paid by the staff).';

        -- Riel cash is counted in riel, turned into dollars at the rate.
        ALTER TABLE app.gl_cash_counts
            ADD COLUMN counted_riel bigint CHECK (counted_riel BETWEEN 0 AND 9000000000000000),
            ADD COLUMN exchange_rate_record_id uuid REFERENCES app.exchange_rate_records(id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT gl_cc_riel CHECK ((counted_riel IS NULL) = (exchange_rate_record_id IS NULL));
        COMMENT ON COLUMN app.gl_cash_counts.counted_minor IS
            'What was counted, in USD cents (riel cash: counted_riel at the rate).';

        -- Money paid back to staff for an Expense report or an advance that cost more.
        CREATE TABLE app.gl_staff_paybacks (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            expense_request_id uuid NOT NULL REFERENCES app.gl_expense_requests(id)
                ON DELETE RESTRICT,
            paid_on date NOT NULL,
            from_account_id uuid NOT NULL,
            amount_cents bigint NOT NULL CHECK (amount_cents BETWEEN 1 AND 9000000000000000),
            entry_id uuid NOT NULL UNIQUE REFERENCES app.gl_journal_entries(id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT gl_sp_from_account_id_fkey FOREIGN KEY (from_account_id, property_id)
                REFERENCES app.gl_accounts(id, property_id) ON DELETE RESTRICT
        );
        CREATE INDEX gl_sp_request_idx ON app.gl_staff_paybacks(expense_request_id);
        CREATE TRIGGER gl_staff_paybacks_reject_update_or_delete
            BEFORE UPDATE OR DELETE ON app.gl_staff_paybacks
            FOR EACH ROW EXECUTE FUNCTION app.gl_reject_mutation();
        CREATE TRIGGER gl_staff_paybacks_reject_truncate BEFORE TRUNCATE ON app.gl_staff_paybacks
            FOR EACH STATEMENT EXECUTE FUNCTION app.gl_reject_mutation();
        CREATE TRIGGER gl_staff_paybacks_accounts BEFORE INSERT OR UPDATE ON app.gl_staff_paybacks
            FOR EACH ROW EXECUTE FUNCTION app.gl_check_record_accounts('from_account_id', '');
        REVOKE ALL ON TABLE app.gl_staff_paybacks FROM PUBLIC;
        GRANT SELECT ON TABLE app.gl_staff_paybacks TO prm_runtime, prm_financial;
        """
    )
    op.execute(HELPERS)
    op.execute(_literal_colons(REQUESTS))
    op.execute(_literal_colons(EXPENSES))
    op.execute(_literal_colons(MONEY))
    for function in (*INTERNAL_FUNCTIONS, *RUNTIME_FUNCTIONS):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in RUNTIME_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.gl_expense_requests)
                OR EXISTS (SELECT 1 FROM app.gl_expenses)
                OR EXISTS (SELECT 1 FROM app.gl_money_moves)
                OR EXISTS (SELECT 1 FROM app.gl_owner_money)
                OR EXISTS (SELECT 1 FROM app.gl_petty_cash_topups)
                OR EXISTS (SELECT 1 FROM app.gl_cash_counts)
                OR EXISTS (SELECT 1 FROM app.gl_suppliers) THEN
                RAISE EXCEPTION 'Ledger money records exist; it cannot be rolled back'
                    USING ERRCODE = '55000';
            END IF;
        END $$;
        """
    )
    for function in (*RUNTIME_FUNCTIONS, *INTERNAL_FUNCTIONS[::-1]):
        op.execute(f"DROP FUNCTION {function}")
    op.execute(
        """
        DROP TABLE app.gl_staff_paybacks;
        ALTER TABLE app.gl_cash_counts DROP CONSTRAINT gl_cc_riel,
            DROP COLUMN exchange_rate_record_id, DROP COLUMN counted_riel;
        ALTER TABLE app.gl_expense_requests DROP CONSTRAINT gl_er_paid_how,
            DROP COLUMN paid_how;
        """
    )
