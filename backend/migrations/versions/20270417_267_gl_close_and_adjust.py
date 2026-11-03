# ruff: noqa: E501
"""General Ledger close: adjusting entries, opening balances, Books check, month and year close (phase 6 step 4, part 1).

Owner decisions: the round 22 screens of DESIGN.md (Month-end close checks itself, no tick
boxes; months close in order and only the Owner closes; the Owner closes the year after
December; opening balances are read-only once the first month is closed; an adjusting entry is
prepared with a reason and balanced lines, never on a control account, and the Owner's own entry
goes in at once with a note), the PRD v2 rules PR-GL-037, PR-GL-043, PR-GL-050 and PR-GL-051, the
Books check of gap G2 (eight lines), the Month-end close lines of rounds 22, 23 and gap G7, and the
phase 6 plan L3 (posting starts on the ledger's first day; the opening balances hold what came
before it).

- Opening balances: the Owner types the accounts that are not control accounts (cash, bank,
  equipment, supplier bills, owner money). The app works out each control account (Customer
  debt, Deposits, Customer Credit, money not used yet, Rent billed in advance) from the app's own
  lists, so the ledger and the lists agree from the first day. The entry must balance; the
  difference is shown so the Owner can put it on an equity account.
- Books check: each control account against its app list as at today, every record posted, every
  entry balanced.
- Month-end close: the checks run inside the database; Close works only when all are green.
"""

import re
from collections.abc import Sequence

from alembic import op

revision: str = "20270417_267"
down_revision: str | None = "20270416_266"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_FUNCTIONS = (
    "app.gl_prepare_adjusting_entry(uuid, uuid, date, text, jsonb, text, uuid)",
    "app.gl_decide_adjusting_entry(uuid, uuid, boolean, text, uuid)",
    "app.gl_void_adjusting_entry(uuid, uuid, text, uuid)",
    "app.gl_begin_ledger(uuid, uuid, smallint, uuid)",
    "app.gl_set_opening_lines(uuid, uuid, jsonb, uuid)",
    "app.gl_opening_preview(uuid)",
    "app.gl_post_opening_balances(uuid, uuid, uuid)",
    "app.gl_books_check(uuid)",
    "app.gl_month_close_checks(uuid)",
    "app.gl_close_month(uuid, uuid, uuid)",
    "app.gl_close_fiscal_year(uuid, uuid, uuid)",
)
FINANCIAL_FUNCTIONS = ("app.gl_keep_years_open(uuid, uuid)",)
INTERNAL_FUNCTIONS = (
    "app.gl_natural(text, bigint, bigint)",
    "app.gl_control_lists(uuid)",
    "app.gl_control_movements(uuid, date, date)",
    "app.gl_post_adjusting(uuid, uuid, uuid)",
)

HELPERS = r"""
-- A balance on the account's normal side (debit for assets and expenses, credit otherwise).
CREATE FUNCTION app.gl_natural(p_normal_side text, p_debit bigint, p_credit bigint)
RETURNS bigint LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN p_normal_side = 'DEBIT' THEN p_debit - p_credit ELSE p_credit - p_debit END
$$;

-- What the app's own lists hold today for each control account (Books check "In the list").
CREATE FUNCTION app.gl_control_lists(p_property uuid)
RETURNS TABLE (code text, cents bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    WITH zone AS (
        SELECT property.timezone_name AS tz,
            timezone(property.timezone_name, statement_timestamp())::date AS today
        FROM app.properties AS property WHERE property.id = p_property
    ),
    sources AS (
        SELECT source.balance_kind, source.balance_usd_cents
        FROM app.customer_ledger_balance_sources AS source WHERE source.property_id = p_property
    ),
    -- Rent Invoices for a later month: what each such Rent line still holds.
    advance_rent AS (
        SELECT coalesce(sum(line.amount_usd_cents + coalesce((
            SELECT sum(CASE adjustment.adjustment_type WHEN 'DEBIT' THEN adjustment.amount_usd_cents
                    ELSE -adjustment.amount_usd_cents END)
            FROM app.invoice_adjustments AS adjustment
            WHERE adjustment.invoice_line_id = line.id
              AND NOT EXISTS (SELECT 1 FROM app.invoice_adjustment_reversals AS reversal
                              WHERE reversal.invoice_adjustment_id = adjustment.id)), 0)), 0)
            AS cents
        FROM app.invoice_lines AS line
        JOIN app.invoices AS invoice ON invoice.id = line.invoice_id
        JOIN app.leases AS lease ON lease.id = invoice.lease_id
        JOIN app.units AS unit ON unit.id = lease.unit_id
        CROSS JOIN zone
        WHERE unit.property_id = p_property AND line.category = 'RENT'
          AND invoice.issued_at IS NOT NULL
          AND date_trunc('month', line.period_start) > date_trunc('month', zone.today)
          AND app.gl_rent_account(date_trunc('month', line.period_start)::date,
              timezone(zone.tz, invoice.issued_at)::date) = '2050'
          AND NOT EXISTS (SELECT 1 FROM app.invoice_void_events AS void
                          WHERE void.invoice_id = invoice.id)
    )
    SELECT '1100', coalesce(sum(greatest(balance_usd_cents, 0)) FILTER (WHERE balance_kind = 'INVOICE'), 0)::bigint FROM sources
    UNION ALL SELECT '1110', coalesce(sum(greatest(balance_usd_cents, 0)) FILTER (WHERE balance_kind = 'LATE_PAYMENT_CHARGE'), 0)::bigint FROM sources
    UNION ALL SELECT '2050', cents::bigint FROM advance_rent
    UNION ALL SELECT '2100', coalesce(sum(balance_usd_cents) FILTER (WHERE balance_kind = 'SECURITY_DEPOSIT'), 0)::bigint FROM sources
    UNION ALL SELECT '2110', coalesce(sum(balance_usd_cents) FILTER (WHERE balance_kind = 'PET_DEPOSIT'), 0)::bigint FROM sources
    UNION ALL SELECT '2200', coalesce(sum(balance_usd_cents) FILTER (WHERE balance_kind = 'CREDIT'), 0)::bigint FROM sources
    UNION ALL SELECT '2210', coalesce(sum(balance_usd_cents) FILTER (WHERE balance_kind = 'UNALLOCATED_PAYMENT'), 0)::bigint FROM sources
$$;

-- The app records' lines on each control account from one day to another, posted or not.
CREATE FUNCTION app.gl_control_movements(p_property uuid, p_from date, p_until date)
RETURNS TABLE (code text, cents bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT account.code,
        coalesce(sum(app.gl_natural(account.normal_side,
            coalesce((line ->> 'debit_cents')::bigint, 0),
            coalesce((line ->> 'credit_cents')::bigint, 0))), 0)::bigint
    FROM app.gl_accounts AS account
    LEFT JOIN (
        SELECT item AS line FROM app.gl_app_record_events(p_property, p_from, p_until) AS event
        CROSS JOIN LATERAL jsonb_array_elements(event.lines) AS item
    ) AS moved ON moved.line ->> 'account' = account.code
    WHERE account.property_id = p_property AND account.control_source IS NOT NULL
    GROUP BY account.code
$$;

-- The year that holds today stays open, so the app's records always have a month to go to.
CREATE FUNCTION app.gl_keep_years_open(p_property uuid, p_actor uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_year smallint;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app.gl_fiscal_years AS year WHERE year.property_id = p_property) THEN
        RETURN;
    END IF;
    v_year := date_part('year', app.gl_today(p_property))::smallint;
    IF NOT EXISTS (SELECT 1 FROM app.gl_fiscal_years AS year
                   WHERE year.property_id = p_property AND year.fiscal_year = v_year) THEN
        PERFORM app.gl_open_fiscal_year(p_property, v_year, p_actor);
        PERFORM app.gl_audit(p_property, p_actor, 'ledger.year.opened', 'gl_fiscal_year',
            (SELECT year.id FROM app.gl_fiscal_years AS year
             WHERE year.property_id = p_property AND year.fiscal_year = v_year),
            'A new year starts', gen_random_uuid(), jsonb_build_object('fiscal_year', v_year));
    END IF;
END $$;

-- Opening balance entries carry the control accounts the app works out (L3).
CREATE OR REPLACE FUNCTION app.gl_check_line()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
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
            SELECT entry.entry_kind INTO v_reversed_kind FROM app.gl_journal_entries AS entry
            WHERE entry.id = v_entry.reverses_entry_id;
        ELSE
            v_reversed_kind := v_entry.entry_kind;
        END IF;
        IF v_reversed_kind NOT IN ('AUTO', 'RENT_TO_INCOME', 'OPENING') THEN
            RAISE EXCEPTION 'Account % changes only through app records', v_account.code
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;
"""

ADJUSTING = r"""
CREATE FUNCTION app.gl_post_adjusting(p_adjustment uuid, p_actor uuid, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_adjustment app.gl_adjusting_entries%ROWTYPE;
    v_lines jsonb;
    v_entry uuid;
BEGIN
    SELECT adjustment.* INTO STRICT v_adjustment FROM app.gl_adjusting_entries AS adjustment
    WHERE adjustment.id = p_adjustment;
    PERFORM app.gl_check_record_day(v_adjustment.property_id, v_adjustment.entry_date);
    SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object('account', account.code,
            'debit_cents', nullif(line.debit_cents, 0), 'credit_cents', nullif(line.credit_cents, 0),
            'memo', coalesce(line.memo, v_adjustment.adjustment_number), 'unit_id', line.unit_id,
            'customer_id', line.customer_id, 'supplier_id', line.supplier_id))
            ORDER BY line.line_no)
    INTO v_lines
    FROM app.gl_adjusting_entry_lines AS line
    JOIN app.gl_accounts AS account ON account.id = line.account_id
    WHERE line.adjusting_entry_id = p_adjustment;
    v_entry := app.gl_post_entry(v_adjustment.property_id, v_adjustment.entry_date, 'ADJUSTING',
        left('Adjusting entry ' || v_adjustment.adjustment_number || ': ' || v_adjustment.reason, 500),
        'ADJUSTING_ENTRY', p_adjustment, 'adjusting_entry:' || p_adjustment, v_adjustment.reason,
        v_adjustment.prepared_by, p_actor, p_correlation, v_lines);
    UPDATE app.gl_adjusting_entries SET status = 'POSTED', decided_by = p_actor,
        decided_at = statement_timestamp(), entry_id = v_entry
    WHERE id = p_adjustment;
    RETURN v_entry;
END $$;

CREATE FUNCTION app.gl_prepare_adjusting_entry(p_property uuid, p_actor uuid, p_entry_date date,
    p_reason text, p_lines jsonb, p_own_note text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_id uuid := gen_random_uuid();
    v_line jsonb;
    v_no integer := 0;
    v_debit bigint := 0;
    v_credit bigint := 0;
    v_account uuid;
    v_own boolean;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.adjustments.prepare');
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'An adjusting entry needs a reason' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_check_record_day(p_property, p_entry_date);
    IF jsonb_typeof(p_lines) IS DISTINCT FROM 'array' OR jsonb_array_length(p_lines) < 2
        OR jsonb_array_length(p_lines) > 500 THEN
        RAISE EXCEPTION 'An adjusting entry has 2 to 500 lines' USING ERRCODE = '22023';
    END IF;
    v_own := app.gl_can(p_actor, p_property, 'ledger.adjustments.approve');
    IF v_own AND (p_own_note IS NULL OR btrim(p_own_note) = '') THEN
        RAISE EXCEPTION 'Your own adjusting entry goes in at once: add a note'
            USING ERRCODE = '22023';
    END IF;
    INSERT INTO app.gl_adjusting_entries (id, property_id, adjustment_number, entry_date, reason,
        prepared_by, status, own_entry_note, created_by)
    VALUES (v_id, p_property, app.gl_next_number(p_property, 'AJ', p_entry_date), p_entry_date,
        btrim(p_reason), p_actor, 'WAITING',
        CASE WHEN v_own THEN btrim(p_own_note) END, p_actor);
    FOR v_line IN SELECT value FROM jsonb_array_elements(p_lines) LOOP
        v_no := v_no + 1;
        SELECT account.id INTO v_account FROM app.gl_accounts AS account
        WHERE account.property_id = p_property AND account.code = v_line ->> 'account';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'No account %', coalesce(v_line ->> 'account', '(none)')
                USING ERRCODE = '22023';
        END IF;
        v_debit := v_debit + coalesce((v_line ->> 'debit_cents')::bigint, 0);
        v_credit := v_credit + coalesce((v_line ->> 'credit_cents')::bigint, 0);
        INSERT INTO app.gl_adjusting_entry_lines (id, adjusting_entry_id, property_id, line_no,
            account_id, debit_cents, credit_cents, memo, unit_id, customer_id, supplier_id)
        VALUES (gen_random_uuid(), v_id, p_property, v_no, v_account,
            coalesce((v_line ->> 'debit_cents')::bigint, 0),
            coalesce((v_line ->> 'credit_cents')::bigint, 0),
            nullif(btrim(v_line ->> 'memo'), ''), (v_line ->> 'unit_id')::uuid,
            (v_line ->> 'customer_id')::uuid, (v_line ->> 'supplier_id')::uuid);
    END LOOP;
    IF v_debit <> v_credit THEN
        RAISE EXCEPTION 'Debits (% cents) must equal credits (% cents)', v_debit, v_credit
            USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.adjusting_entry.prepared',
        'gl_adjusting_entry', v_id, btrim(p_reason), p_correlation,
        jsonb_build_object('entry_date', p_entry_date, 'total_cents', v_debit, 'own', v_own));
    -- The Owner's own entry goes in at once with a note (DESIGN.md round 22).
    IF v_own THEN
        PERFORM app.gl_post_adjusting(v_id, p_actor, p_correlation);
    END IF;
    RETURN v_id;
END $$;

CREATE FUNCTION app.gl_decide_adjusting_entry(p_adjustment uuid, p_actor uuid, p_approve boolean,
    p_note text, p_correlation uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_adjustment app.gl_adjusting_entries%ROWTYPE;
BEGIN
    SELECT adjustment.* INTO v_adjustment FROM app.gl_adjusting_entries AS adjustment
    WHERE adjustment.id = p_adjustment FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No adjusting entry' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_adjustment.property_id, 'ledger.adjustments.approve');
    IF v_adjustment.status <> 'WAITING' THEN
        RAISE EXCEPTION 'This adjusting entry is not waiting for approval' USING ERRCODE = '55000';
    END IF;
    IF p_actor = v_adjustment.prepared_by THEN
        RAISE EXCEPTION 'Nobody approves their own adjusting entry' USING ERRCODE = '42501';
    END IF;
    IF NOT p_approve AND (p_note IS NULL OR btrim(p_note) = '') THEN
        RAISE EXCEPTION 'Say why the adjusting entry is not approved' USING ERRCODE = '22023';
    END IF;
    IF p_approve THEN
        PERFORM app.gl_post_adjusting(p_adjustment, p_actor, p_correlation);
        UPDATE app.gl_adjusting_entries SET decision_note = nullif(btrim(p_note), '')
        WHERE id = p_adjustment;
    ELSE
        UPDATE app.gl_adjusting_entries SET status = 'REFUSED', decided_by = p_actor,
            decided_at = statement_timestamp(), decision_note = btrim(p_note)
        WHERE id = p_adjustment;
    END IF;
    PERFORM app.gl_audit(v_adjustment.property_id, p_actor,
        CASE WHEN p_approve THEN 'ledger.adjusting_entry.approved'
            ELSE 'ledger.adjusting_entry.refused' END,
        'gl_adjusting_entry', p_adjustment, coalesce(nullif(btrim(p_note), ''), 'Approved'),
        p_correlation, '{}'::jsonb);
END $$;

CREATE FUNCTION app.gl_void_adjusting_entry(p_adjustment uuid, p_actor uuid, p_reason text,
    p_correlation uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_adjustment app.gl_adjusting_entries%ROWTYPE;
BEGIN
    SELECT adjustment.* INTO v_adjustment FROM app.gl_adjusting_entries AS adjustment
    WHERE adjustment.id = p_adjustment FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No adjusting entry' USING ERRCODE = '22023';
    END IF;
    IF p_actor IS DISTINCT FROM v_adjustment.prepared_by THEN
        PERFORM app.gl_require(p_actor, v_adjustment.property_id, 'ledger.adjustments.approve');
    ELSE
        PERFORM app.gl_require(p_actor, v_adjustment.property_id, 'ledger.adjustments.prepare');
    END IF;
    IF v_adjustment.status <> 'WAITING' THEN
        RAISE EXCEPTION 'Only a waiting adjusting entry is voided; a posted one is reversed by a new one'
            USING ERRCODE = '55000';
    END IF;
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'A void needs a reason' USING ERRCODE = '22023';
    END IF;
    UPDATE app.gl_adjusting_entries SET status = 'VOID', decided_by = p_actor,
        decided_at = statement_timestamp(), decision_note = btrim(p_reason)
    WHERE id = p_adjustment;
    PERFORM app.gl_audit(v_adjustment.property_id, p_actor, 'ledger.adjusting_entry.voided',
        'gl_adjusting_entry', p_adjustment, btrim(p_reason), p_correlation, '{}'::jsonb);
END $$;
"""

OPENING = r"""
CREATE FUNCTION app.gl_begin_ledger(p_property uuid, p_actor uuid, p_first_year smallint,
    p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_id uuid := gen_random_uuid();
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.opening_balances');
    IF EXISTS (SELECT 1 FROM app.gl_opening_balances AS opening
               WHERE opening.property_id = p_property) THEN
        RAISE EXCEPTION 'The ledger has already started' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.gl_fiscal_years AS year WHERE year.property_id = p_property
               AND year.fiscal_year < p_first_year) THEN
        RAISE EXCEPTION 'The ledger already has an earlier year' USING ERRCODE = '55000';
    END IF;
    PERFORM app.gl_start_ledger(p_property, p_first_year, p_actor);
    INSERT INTO app.gl_opening_balances (id, property_id, start_date, status, created_by)
    VALUES (v_id, p_property, make_date(p_first_year, 1, 1), 'DRAFT', p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.opening_balances.started',
        'gl_opening_balance', v_id, 'The ledger starts on ' || to_char(make_date(p_first_year, 1, 1), 'DD/MM/YYYY'),
        p_correlation, jsonb_build_object('first_year', p_first_year));
    RETURN v_id;
END $$;

-- The Owner types every account that is not a control account; the lines are replaced whole.
CREATE FUNCTION app.gl_set_opening_lines(p_property uuid, p_actor uuid, p_lines jsonb,
    p_correlation uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_opening app.gl_opening_balances%ROWTYPE;
    v_line jsonb;
    v_account uuid;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.opening_balances');
    SELECT opening.* INTO v_opening FROM app.gl_opening_balances AS opening
    WHERE opening.property_id = p_property FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Start the ledger first' USING ERRCODE = '55000';
    END IF;
    IF v_opening.status <> 'DRAFT' THEN
        RAISE EXCEPTION 'Opening balances are fixed once posted; later fixes are adjusting entries'
            USING ERRCODE = '55000';
    END IF;
    IF jsonb_typeof(p_lines) IS DISTINCT FROM 'array' OR jsonb_array_length(p_lines) > 500 THEN
        RAISE EXCEPTION 'Opening balances are a list of up to 500 accounts' USING ERRCODE = '22023';
    END IF;
    DELETE FROM app.gl_opening_balance_lines WHERE opening_balance_id = v_opening.id;
    FOR v_line IN SELECT value FROM jsonb_array_elements(p_lines) LOOP
        SELECT account.id INTO v_account FROM app.gl_accounts AS account
        WHERE account.property_id = p_property AND account.code = v_line ->> 'account';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'No account %', coalesce(v_line ->> 'account', '(none)')
                USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.gl_opening_balance_lines (id, opening_balance_id, property_id, account_id,
            debit_cents, credit_cents, memo)
        VALUES (gen_random_uuid(), v_opening.id, p_property, v_account,
            coalesce((v_line ->> 'debit_cents')::bigint, 0),
            coalesce((v_line ->> 'credit_cents')::bigint, 0), nullif(btrim(v_line ->> 'memo'), ''));
    END LOOP;
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.opening_balances.changed',
        'gl_opening_balance', v_opening.id, 'Opening balances typed', p_correlation,
        jsonb_build_object('lines', jsonb_array_length(p_lines)));
END $$;

-- The opening entry as it would post now: typed lines and the control accounts the app works
-- out (what each app list holds today less what the app's records moved since the start).
CREATE FUNCTION app.gl_opening_preview(p_property uuid)
RETURNS TABLE (code text, debit_cents bigint, credit_cents bigint, worked_out boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    WITH opening AS (
        SELECT opening.* FROM app.gl_opening_balances AS opening
        WHERE opening.property_id = p_property
    ),
    controls AS (
        SELECT account.code, account.normal_side, list.cents - coalesce(moved.cents, 0) AS natural
        FROM opening
        CROSS JOIN app.gl_control_lists(p_property) AS list
        JOIN app.gl_accounts AS account ON account.property_id = p_property
            AND account.code = list.code
        LEFT JOIN app.gl_control_movements(p_property, (SELECT start_date FROM opening),
            app.gl_today(p_property)) AS moved ON moved.code = list.code
    )
    SELECT account.code, line.debit_cents, line.credit_cents, false
    FROM opening
    JOIN app.gl_opening_balance_lines AS line ON line.opening_balance_id = opening.id
    JOIN app.gl_accounts AS account ON account.id = line.account_id
    UNION ALL
    SELECT controls.code,
        CASE WHEN (controls.normal_side = 'DEBIT') = (controls.natural > 0) THEN abs(controls.natural) ELSE 0 END,
        CASE WHEN (controls.normal_side = 'DEBIT') = (controls.natural > 0) THEN 0 ELSE abs(controls.natural) END,
        true
    FROM controls WHERE controls.natural <> 0
    ORDER BY 1
$$;

CREATE FUNCTION app.gl_post_opening_balances(p_property uuid, p_actor uuid, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_opening app.gl_opening_balances%ROWTYPE;
    v_lines jsonb;
    v_debit bigint;
    v_credit bigint;
    v_entry uuid;
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.opening_balances');
    SELECT opening.* INTO v_opening FROM app.gl_opening_balances AS opening
    WHERE opening.property_id = p_property FOR UPDATE;
    IF NOT FOUND OR v_opening.status <> 'DRAFT' THEN
        RAISE EXCEPTION 'There are no opening balances waiting to post' USING ERRCODE = '55000';
    END IF;
    -- A record that cannot post would make the worked-out control accounts wrong.
    IF EXISTS (SELECT 1 FROM app.gl_app_record_events(p_property, v_opening.start_date,
                   app.gl_today(p_property)) AS event WHERE event.problem IS NOT NULL)
        OR EXISTS (SELECT 1 FROM app.gl_posting_problems AS problem
                   WHERE problem.property_id = p_property) THEN
        RAISE EXCEPTION 'Clear the Needs check list first' USING ERRCODE = '55000';
    END IF;
    SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object('account', preview.code,
            'debit_cents', nullif(preview.debit_cents, 0),
            'credit_cents', nullif(preview.credit_cents, 0),
            'memo', CASE WHEN preview.worked_out THEN 'From the app''s lists'
                ELSE 'Opening balance' END)) ORDER BY preview.code),
        coalesce(sum(preview.debit_cents), 0), coalesce(sum(preview.credit_cents), 0)
    INTO v_lines, v_debit, v_credit
    FROM app.gl_opening_preview(p_property) AS preview;
    IF v_debit <> v_credit OR v_debit = 0 THEN
        RAISE EXCEPTION 'Opening balances are off by % cents (debits % , credits %): put the difference on an equity account such as 3000',
            v_debit - v_credit, v_debit, v_credit USING ERRCODE = '22023';
    END IF;
    v_entry := app.gl_post_entry(p_property, v_opening.start_date, 'OPENING',
        'Opening balances at ' || to_char(v_opening.start_date - 1, 'DD/MM/YYYY'),
        'OPENING_BALANCE', v_opening.id, 'opening_balance:' || v_opening.id,
        'Opening balances at ' || to_char(v_opening.start_date - 1, 'DD/MM/YYYY'), p_actor, p_actor,
        p_correlation, v_lines);
    UPDATE app.gl_opening_balances SET status = 'POSTED', entry_id = v_entry, posted_by = p_actor,
        posted_at = statement_timestamp()
    WHERE id = v_opening.id;
    RETURN v_entry;
END $$;
"""

CLOSE = r"""
-- Gap G2: each control account against its app list as at today, then the two book checks.
CREATE FUNCTION app.gl_books_check(p_property uuid)
RETURNS TABLE (check_code text, accounts text, in_books bigint, in_list bigint, ok boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    WITH books AS (
        SELECT account.code, coalesce(sum(app.gl_natural(account.normal_side, line.debit_cents,
            line.credit_cents)), 0)::bigint AS cents
        FROM app.gl_accounts AS account
        LEFT JOIN app.gl_journal_lines AS line ON line.account_id = account.id
        WHERE account.property_id = p_property AND account.control_source IS NOT NULL
        GROUP BY account.code
    ),
    lists AS (SELECT * FROM app.gl_control_lists(p_property)),
    pairs (check_code, accounts, codes, position) AS (VALUES
        ('CUSTOMER_DEBT', '1100 + 1110', ARRAY['1100', '1110'], 1),
        ('RENT_IN_ADVANCE', '2050', ARRAY['2050'], 2),
        ('SECURITY_DEPOSITS', '2100', ARRAY['2100'], 3),
        ('PET_DEPOSITS', '2110', ARRAY['2110'], 4),
        ('CUSTOMER_CREDIT', '2200', ARRAY['2200'], 5),
        ('MONEY_NOT_USED', '2210', ARRAY['2210'], 6)),
    start AS (
        SELECT min(period.starts_on) AS day FROM app.gl_periods AS period
        WHERE period.property_id = p_property
    ),
    unposted AS (
        SELECT count(*)::bigint AS records
        FROM start CROSS JOIN LATERAL app.gl_app_record_events(p_property, start.day,
            app.gl_today(p_property)) AS event
        WHERE start.day IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
            WHERE entry.posting_key = event.posting_key)
    ),
    unbalanced AS (
        SELECT count(*)::bigint AS entries FROM (
            SELECT entry.id FROM app.gl_journal_entries AS entry
            JOIN app.gl_journal_lines AS line ON line.entry_id = entry.id
            WHERE entry.property_id = p_property
            GROUP BY entry.id HAVING sum(line.debit_cents) <> sum(line.credit_cents)) AS bad
    )
    SELECT pairs.check_code, pairs.accounts,
        (SELECT coalesce(sum(books.cents), 0)::bigint FROM books WHERE books.code = ANY (pairs.codes)),
        (SELECT coalesce(sum(lists.cents), 0)::bigint FROM lists WHERE lists.code = ANY (pairs.codes)),
        (SELECT coalesce(sum(books.cents), 0) FROM books WHERE books.code = ANY (pairs.codes))
            = (SELECT coalesce(sum(lists.cents), 0) FROM lists WHERE lists.code = ANY (pairs.codes))
    FROM pairs
    UNION ALL
    SELECT 'EVERY_RECORD_POSTED', NULL, 0::bigint, unposted.records, unposted.records = 0
    FROM unposted
    UNION ALL
    SELECT 'EVERY_ENTRY_BALANCED', NULL, 0::bigint, unbalanced.entries, unbalanced.entries = 0
    FROM unbalanced
$$;

-- The Month-end close lines (rounds 22, 23 and gap G7); each is green or not, with a count.
CREATE FUNCTION app.gl_month_close_checks(p_period uuid)
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
    JOIN app.gl_accounts AS account ON account.id = asset.account_id
    WHERE asset.property_id = v_period.property_id AND asset.status = 'IN_USE'
      AND account.code <> '1500'
      AND asset.depreciation_starts_on <= v_period.ends_on
      AND NOT EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
                      WHERE entry.posting_key = 'depreciation:' || p_period);
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

CREATE FUNCTION app.gl_close_month(p_period uuid, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_period app.gl_periods%ROWTYPE;
    v_checks jsonb;
BEGIN
    SELECT period.* INTO v_period FROM app.gl_periods AS period
    WHERE period.id = p_period AND period.period_no <= 12 FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No month' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_period.property_id, 'ledger.close');
    IF v_period.status <> 'OPEN' THEN
        RAISE EXCEPTION 'This month is already closed' USING ERRCODE = '55000';
    END IF;
    IF v_period.ends_on >= app.gl_today(v_period.property_id) THEN
        RAISE EXCEPTION 'A month closes after its last day' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.gl_periods AS before WHERE before.property_id = v_period.property_id
               AND before.period_no <= 12 AND before.ends_on < v_period.starts_on
               AND before.status = 'OPEN') THEN
        RAISE EXCEPTION 'Months close in order: close the oldest open month first'
            USING ERRCODE = '55000';
    END IF;
    SELECT jsonb_object_agg(lower(item.check_code), item.ok) INTO v_checks
    FROM app.gl_month_close_checks(p_period) AS item;
    INSERT INTO app.gl_close_runs (id, period_id, ran_by, checks, all_green)
    VALUES (gen_random_uuid(), p_period, p_actor, v_checks,
        NOT EXISTS (SELECT 1 FROM jsonb_each(v_checks) AS item WHERE item.value <> 'true'::jsonb));
    -- A close with a red check is kept as a run (so the screen shows what was tried) and
    -- answers closed = false; nothing is raised, so the run row is not rolled back.
    IF EXISTS (SELECT 1 FROM jsonb_each(v_checks) AS item WHERE item.value <> 'true'::jsonb) THEN
        RETURN jsonb_build_object('closed', false, 'checks', v_checks);
    END IF;
    PERFORM app.gl_close_period(p_period, p_actor, v_checks);
    RETURN jsonb_build_object('closed', true, 'checks', v_checks);
END $$;

CREATE FUNCTION app.gl_close_fiscal_year(p_year uuid, p_actor uuid, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_year app.gl_fiscal_years%ROWTYPE;
    v_entry uuid;
BEGIN
    SELECT year.* INTO v_year FROM app.gl_fiscal_years AS year WHERE year.id = p_year;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No year' USING ERRCODE = '22023';
    END IF;
    PERFORM app.gl_require(p_actor, v_year.property_id, 'ledger.close');
    PERFORM app.gl_open_fiscal_year(v_year.property_id, (v_year.fiscal_year + 1)::smallint, p_actor);
    v_entry := app.gl_close_year(p_year, p_actor, 'Year-end close ' || v_year.fiscal_year);
    RETURN v_entry;
END $$;
"""


def _literal_colons(sql: str) -> str:
    """Keep ``'adjusting_entry:...'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def upgrade() -> None:
    op.execute(
        """
        -- The Owner's own adjusting entry goes in at once, kept with a note (DESIGN.md round 22);
        -- the one who prepared an entry may void it while it waits.
        ALTER TABLE app.gl_adjusting_entries
            ADD COLUMN own_entry_note text CHECK (own_entry_note IS NULL
                OR length(btrim(own_entry_note)) BETWEEN 1 AND 500),
            DROP CONSTRAINT gl_aj_not_own,
            ADD CONSTRAINT gl_aj_not_own CHECK (decided_by IS DISTINCT FROM prepared_by
                OR status = 'VOID' OR (own_entry_note IS NOT NULL AND status = 'POSTED'));
        COMMENT ON COLUMN app.gl_adjusting_entries.own_entry_note IS
            'Set when the Owner (who approves adjusting entries) prepares one: it posts at once.';
        """
    )
    for block in (HELPERS, ADJUSTING, OPENING, CLOSE):
        op.execute(_literal_colons(block))
    for function in (*RUNTIME_FUNCTIONS, *FINANCIAL_FUNCTIONS, *INTERNAL_FUNCTIONS):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in RUNTIME_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")
    for function in FINANCIAL_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")
    op.execute(
        """
        -- Business rules: how many years equipment lasts (owner yes 03/11/2026 10:26).
        INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area, used_by_app)
        VALUES
            ('ASSET_LIFE_1510', 'Building lasts (years)', 'អាយុកាលអគារ (ឆ្នាំ)', 'COUNT', 'LEDGER', true),
            ('ASSET_LIFE_1520', 'Furniture and appliances in Units last (years)',
                'អាយុកាលគ្រឿងសង្ហារិម និងឧបករណ៍ក្នុងបន្ទប់ (ឆ្នាំ)', 'COUNT', 'LEDGER', true),
            ('ASSET_LIFE_1530', 'Office equipment lasts (years)', 'អាយុកាលឧបករណ៍ការិយាល័យ (ឆ្នាំ)',
                'COUNT', 'LEDGER', true);
        INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
        SELECT name.id, seed.value, DATE '2026-01-01',
            'First value: owner decision 03/11/2026 10:26 (General Ledger phase 6 step 4)',
            (SELECT classification.actor_id FROM app.user_account_classes AS classification
             WHERE classification.account_class = 'owner')
        FROM (VALUES ('ASSET_LIFE_1510', 20), ('ASSET_LIFE_1520', 5), ('ASSET_LIFE_1530', 3))
            AS seed(code, value)
        JOIN app.business_rule_names AS name ON name.code = seed.code;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.gl_adjusting_entries)
                OR EXISTS (SELECT 1 FROM app.gl_opening_balances)
                OR EXISTS (SELECT 1 FROM app.gl_close_runs) THEN
                RAISE EXCEPTION 'Ledger close records exist; it cannot be rolled back'
                    USING ERRCODE = '55000';
            END IF;
        END $$;
        """
    )
    for function in (*RUNTIME_FUNCTIONS, *FINANCIAL_FUNCTIONS, *INTERNAL_FUNCTIONS[::-1]):
        op.execute(f"DROP FUNCTION {function}")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.gl_check_line()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $fn$
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
                    SELECT entry.entry_kind INTO v_reversed_kind FROM app.gl_journal_entries AS entry
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
        $fn$;
        DO $$
        BEGIN
            IF (SELECT count(*) FROM app.business_rules AS rule
                JOIN app.business_rule_names AS name ON name.id = rule.rule_name_id
                WHERE name.code IN ('ASSET_LIFE_1510', 'ASSET_LIFE_1520', 'ASSET_LIFE_1530')) > 3
            THEN
                RAISE EXCEPTION 'The asset life rules were changed; they are kept'
                    USING ERRCODE = '55000';
            END IF;
        END $$;
        ALTER TABLE app.business_rules DISABLE TRIGGER business_rules_append_only_row;
        DELETE FROM app.business_rules WHERE rule_name_id IN (SELECT id FROM app.business_rule_names
            WHERE code IN ('ASSET_LIFE_1510', 'ASSET_LIFE_1520', 'ASSET_LIFE_1530'));
        ALTER TABLE app.business_rules ENABLE TRIGGER business_rules_append_only_row;
        ALTER TABLE app.business_rule_names DISABLE TRIGGER business_rule_names_guard_row;
        DELETE FROM app.business_rule_names
            WHERE code IN ('ASSET_LIFE_1510', 'ASSET_LIFE_1520', 'ASSET_LIFE_1530');
        ALTER TABLE app.business_rule_names ENABLE TRIGGER business_rule_names_guard_row;
        ALTER TABLE app.gl_adjusting_entries DROP CONSTRAINT gl_aj_not_own,
            DROP COLUMN own_entry_note,
            ADD CONSTRAINT gl_aj_not_own CHECK (decided_by IS DISTINCT FROM prepared_by);
        """
    )
