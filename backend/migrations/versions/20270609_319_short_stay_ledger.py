# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 5d: short-stay money in the ledger, and credit that ends.

The tech plan (03/11/2026): "Each booking gets an Invoice and a Receipt, so money reports and the
General Ledger see it". The ledger job already posts every Invoice, Payment, Customer Credit and
Refund. This step makes the short-stay records post to the right accounts and adds the money the
ledger did not see yet:

1. A short-stay Invoice (the stay, an extension, an early check-in or late check-out fee) is rent:
   its lines go to 4010 Rent instead of 4080 Other income, and each line carries the booking's
   Unit. A damage Invoice goes to 4070 Damage recovered. A discount or a cancel credit (credit
   adjustments of those lines) takes off the same account.
2. A cash deposit: taken, DR the USD cash account, CR 2100 Security Deposits held; at the end,
   DR 2100, CR cash for what goes back and CR 4070 Damage recovered for what approved damage kept.
   2100's list in the books check counts the cash deposits held, so the check stays green.
3. A card hold moves no money. When approved damage keeps it, the card is charged: DR the bank
   account, CR 4070 Damage recovered.
4. A booking paid on the booking site has no Invoice: the site pays the hotel later, net of its
   share. Nothing posts until the site payouts are set up (the owner has not connected the sites;
   their fees start at 0%, owner 05/11/2026).

5. A late-cancel credit the guest did not use by its use-by day ends (owner 05/11/2026 08:07,
   with the credit lasting SS_CREDIT_MONTHS = 12 months): once the day has passed, the Owner, the
   Manager or the credit right presses "End credit". What is left of the guest's credit pays a
   "Credit ended" Invoice, so the app's credit balance goes down with the usual trail and the
   ledger counts the money as 4010 Rent on the booking's Unit (DR 2200 through the Invoice). The
   Short stays list shows the credits waiting to end. A person does it, because an Invoice needs
   an active human user (the scheduled worker runs as a service identity).

A record the job cannot post (no USD cash account or no bank account in the ledger) waits in
"Needs check" like other records and posts by itself once the account exists. Account choices by
Claude under the owner's 2026-10-23 22:30 rule (non-money: which existing account a record uses).
Forward-only and additive.
"""

import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270609_319"
down_revision: str | None = "20270608_318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
-- A late-cancel credit that ended after its use-by day: what was left, and the Invoice it paid.
CREATE TABLE app.short_stay_credit_ends (
    booking_id uuid PRIMARY KEY REFERENCES app.short_stay_credits (booking_id) ON DELETE RESTRICT,
    left_usd_cents bigint NOT NULL CHECK (left_usd_cents >= 0),
    invoice_id uuid UNIQUE REFERENCES app.invoices (id) ON DELETE RESTRICT,
    ended_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    ended_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT short_stay_credit_ends_invoice CHECK ((left_usd_cents > 0) = (invoice_id IS NOT NULL))
);
CREATE TRIGGER short_stay_credit_ends_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_credit_ends FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_credit_ends_truncate BEFORE TRUNCATE ON app.short_stay_credit_ends
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate();
REVOKE ALL ON TABLE app.short_stay_credit_ends FROM PUBLIC;

ALTER FUNCTION app.short_stay_booking_json(uuid) RENAME TO short_stay_booking_guest_json;
"""

FUNCTIONS = r"""
-- Each short-stay Invoice with its booking's Unit and the income account of its lines.
CREATE VIEW app.short_stay_invoice_accounts AS
    SELECT booking.invoice_id, booking.id AS booking_id, booking.unit_id, '4010'::text AS code
    FROM app.short_stay_bookings AS booking WHERE booking.invoice_id IS NOT NULL
    UNION ALL
    SELECT extra.invoice_id, booking.id, booking.unit_id, '4010'
    FROM app.short_stay_extra_invoices AS extra
    JOIN app.short_stay_bookings AS booking ON booking.id = extra.booking_id
    UNION ALL
    SELECT damage.invoice_id, booking.id, booking.unit_id, '4070'
    FROM app.short_stay_damages AS damage
    JOIN app.short_stay_bookings AS booking ON booking.id = damage.booking_id
    WHERE damage.invoice_id IS NOT NULL
    UNION ALL
    SELECT ended.invoice_id, booking.id, booking.unit_id, '4010'
    FROM app.short_stay_credit_ends AS ended
    JOIN app.short_stay_bookings AS booking ON booking.id = ended.booking_id
    WHERE ended.invoice_id IS NOT NULL;
REVOKE ALL ON app.short_stay_invoice_accounts FROM PUBLIC;

-- The guest's Customer Credit rows that a late-cancel credit made (credit adjustments of the
-- stay's Invoices whose paid part became credit).
CREATE FUNCTION app.short_stay_credit_sources(p_booking uuid) RETURNS SETOF uuid
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT DISTINCT coalesce(released.customer_credit_id, application.customer_credit_id)
    FROM app.invoice_credit_excess_releases AS released
    JOIN app.invoice_adjustments AS adjustment ON adjustment.id = released.invoice_adjustment_id
    LEFT JOIN app.customer_credit_applications AS application
        ON application.id = released.reversed_credit_application_id
    WHERE adjustment.reason LIKE 'Late cancel credit: %'
      AND adjustment.invoice_id IN (SELECT app.short_stay_invoices(p_booking))
$$;
REVOKE ALL ON FUNCTION app.short_stay_credit_sources(uuid) FROM PUBLIC;

-- What is left of a late-cancel credit: never more than the credit given, 0 once ended.
CREATE FUNCTION app.short_stay_credit_left(p_booking uuid) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN EXISTS (SELECT 1 FROM app.short_stay_credit_ends AS ended
                             WHERE ended.booking_id = p_booking) THEN 0
        ELSE least(credit.amount_usd_cents, coalesce((
            SELECT sum(app.credit_available_value(source.id))
            FROM app.short_stay_credit_sources(p_booking) AS source(id)), 0))::bigint END
    FROM app.short_stay_credits AS credit WHERE credit.booking_id = p_booking
$$;
REVOKE ALL ON FUNCTION app.short_stay_credit_left(uuid) FROM PUBLIC;

CREATE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT found.booking || CASE WHEN jsonb_typeof(found.booking -> 'credit') = 'object'
        THEN jsonb_build_object('credit', (found.booking -> 'credit') || jsonb_build_object(
            'left_usd_cents', app.short_stay_credit_left(p_booking),
            'ended', (SELECT jsonb_build_object('left_usd_cents', ended.left_usd_cents,
                    'invoice_id', ended.invoice_id, 'invoice_number', invoice.invoice_number,
                    'at', ended.ended_at)
                FROM app.short_stay_credit_ends AS ended
                LEFT JOIN app.invoices AS invoice ON invoice.id = ended.invoice_id
                WHERE ended.booking_id = p_booking)))
        ELSE '{}'::jsonb END
    FROM (SELECT app.short_stay_booking_guest_json(p_booking) AS booking) AS found
$$;
REVOKE ALL ON FUNCTION app.short_stay_booking_json(uuid) FROM PUBLIC;

-- The late-cancel credits past their use-by day with money left (the credit right).
CREATE FUNCTION app.short_stay_credits_due(p_property uuid, p_actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.credit', p_property);
BEGIN
    RETURN coalesce((
        SELECT jsonb_agg(jsonb_build_object('booking_id', due.booking_id,
                'booking_number', due.booking_number, 'guest_name', due.legal_name,
                'use_by', due.use_by, 'left_usd_cents', due.left_cents) ORDER BY due.use_by,
                due.booking_number)
        FROM (
            SELECT booking.id AS booking_id, booking.booking_number, customer.legal_name,
                credit.use_by, app.short_stay_credit_left(booking.id) AS left_cents
            FROM app.short_stay_credits AS credit
            JOIN app.short_stay_bookings AS booking ON booking.id = credit.booking_id
            JOIN app.customers AS customer ON customer.id = booking.customer_id
            WHERE booking.property_id = p_property AND credit.use_by < v_today
              AND NOT EXISTS (SELECT 1 FROM app.short_stay_credit_ends AS ended
                              WHERE ended.booking_id = booking.id)
        ) AS due WHERE due.left_cents > 0), '[]'::jsonb);
END $$;

-- End a late-cancel credit after its use-by day: what is left pays a "Credit ended" Invoice.
CREATE FUNCTION app.end_short_stay_credit(p_property uuid, p_booking uuid, p_actor uuid,
    p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.credit', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
    v_credit app.short_stay_credits%ROWTYPE;
    v_left bigint;
    v_rest bigint;
    v_take bigint;
    v_source uuid;
    v_issued jsonb;
    v_invoice uuid;
    v_line uuid;
    v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
BEGIN
    SELECT credit.* INTO v_credit FROM app.short_stay_credits AS credit
    WHERE credit.booking_id = p_booking;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This booking has no credit' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_credit_ends AS ended WHERE ended.booking_id = p_booking) THEN
        RAISE EXCEPTION 'This credit has already ended' USING ERRCODE = '55000';
    END IF;
    IF v_credit.use_by >= v_today THEN
        RAISE EXCEPTION 'The guest can use this credit until %', to_char(v_credit.use_by, 'DD/MM/YYYY')
            USING ERRCODE = '55000';
    END IF;
    PERFORM 1 FROM app.customer_credits AS credit
    WHERE credit.id IN (SELECT app.short_stay_credit_sources(p_booking))
    ORDER BY credit.id FOR UPDATE;
    v_left := app.short_stay_credit_left(p_booking);
    IF v_left > 0 THEN
        v_issued := app.short_stay_invoice(p_property, p_actor, v_row.customer_id,
            'Late-cancel credit ended for short stay ' || v_row.booking_number,
            'Short stay ' || v_row.booking_number,
            jsonb_build_array(jsonb_build_object('charge_id', gen_random_uuid(),
                'description', 'Credit ended · ' || v_row.booking_number || ' · not used by '
                    || to_char(v_credit.use_by, 'DD/MM/YYYY'),
                'quantity', 1, 'unit_price_usd_cents', v_left)),
            v_correlation);
        v_invoice := (v_issued ->> 'invoice_id')::uuid;
        SELECT line.id INTO STRICT v_line FROM app.invoice_lines AS line
        WHERE line.invoice_id = v_invoice;
        v_rest := v_left;
        FOR v_source IN SELECT source.id FROM app.short_stay_credit_sources(p_booking) AS source(id)
                        ORDER BY source.id LOOP
            EXIT WHEN v_rest <= 0;
            v_take := least(app.credit_available_value(v_source), v_rest);
            IF v_take > 0 THEN
                PERFORM app.post_credit_application(p_property, v_source, p_actor,
                    gen_random_uuid(), jsonb_build_object('mode', 'DESIGNATED',
                        'invoice_id', v_invoice, 'amount_usd_cents', v_take,
                        'details', jsonb_build_array(jsonb_build_object(
                            'invoice_line_id', v_line, 'amount_usd_cents', v_take)),
                        'designation_reference',
                            'Short stay ' || v_row.booking_number || ': credit ended'));
                v_rest := v_rest - v_take;
            END IF;
        END LOOP;
        IF v_rest <> 0 THEN
            RAISE EXCEPTION 'The credit could not pay the Credit ended Invoice' USING ERRCODE = '55000';
        END IF;
    END IF;
    INSERT INTO app.short_stay_credit_ends (booking_id, left_usd_cents, invoice_id, ended_by)
    VALUES (p_booking, v_left, v_invoice, p_actor);
    PERFORM app.short_stay_event(p_booking, 'CREDIT_ENDED', p_actor, NULL,
        jsonb_build_object('left_usd_cents', v_left, 'use_by', v_credit.use_by,
            'invoice_number', v_issued ->> 'invoice_number'));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.credit_ended',
        'short_stay_booking', p_booking, 'Late-cancel credit ended after its use-by day',
        'short_stays.credit', jsonb_build_object('left_usd_cents', v_left),
        jsonb_build_object('left_usd_cents', 0, 'invoice_id', v_invoice), v_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- The cash deposits the front desk holds now (2100's list in the books check).
CREATE FUNCTION app.short_stay_cash_deposits_held(p_property uuid) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT coalesce(sum(deposit.amount_usd_cents), 0)::bigint
    FROM app.short_stay_deposits AS deposit
    JOIN app.short_stay_bookings AS booking ON booking.id = deposit.booking_id
    WHERE booking.property_id = p_property AND deposit.kind = 'CASH' AND deposit.status = 'HELD'
$$;
REVOKE ALL ON FUNCTION app.short_stay_cash_deposits_held(uuid) FROM PUBLIC;

-- The ledger entries of the short-stay deposits, in the shape of app.gl_app_record_events.
CREATE FUNCTION app.gl_short_stay_deposit_events(p_property uuid)
RETURNS TABLE (source_type text, source_id uuid, posting_key text, event_date date,
    event_at timestamptz, entry_kind text, description text, problem text, lines jsonb)
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
WITH zone AS (
    SELECT property.timezone_name AS tz FROM app.properties AS property WHERE property.id = p_property
),
cash AS (
    SELECT (SELECT account.code FROM app.gl_accounts AS account
            WHERE account.property_id = p_property AND account.cash_kind = 'CASH_USD'
              AND account.is_active AND account.is_postable
            ORDER BY account.code LIMIT 1) AS code,
        (SELECT account.code FROM app.gl_accounts AS account
            WHERE account.property_id = p_property AND account.cash_kind = 'BANK'
              AND account.is_active AND account.is_postable
            ORDER BY account.code LIMIT 1) AS bank
),
deposit AS (
    SELECT d.id, d.kind, d.amount_usd_cents AS amount, d.kept_usd_cents AS kept, d.status,
        d.taken_at, d.ended_at, booking.booking_number, booking.customer_id, booking.unit_id
    FROM app.short_stay_deposits AS d
    JOIN app.short_stay_bookings AS booking ON booking.id = d.booking_id
    WHERE booking.property_id = p_property
)
-- A cash deposit taken.
SELECT 'SHORT_STAY_DEPOSIT', d.id, 'short_stay_deposit:' || d.id || ':taken',
    timezone(zone.tz, d.taken_at)::date, d.taken_at, 'AUTO',
    'Short-stay deposit taken for ' || d.booking_number,
    CASE WHEN cash.code IS NULL THEN 'No USD cash account is in the ledger' END,
    jsonb_build_array(
        jsonb_build_object('account', cash.code, 'debit_cents', d.amount, 'memo', d.booking_number,
            'customer_id', d.customer_id, 'lease_id', NULL, 'unit_id', d.unit_id),
        jsonb_build_object('account', '2100', 'credit_cents', d.amount, 'memo', d.booking_number,
            'customer_id', d.customer_id, 'lease_id', NULL, 'unit_id', d.unit_id))
FROM deposit AS d CROSS JOIN zone CROSS JOIN cash
WHERE d.kind = 'CASH'
UNION ALL
-- A cash deposit ended: what goes back to the guest and what approved damage kept.
SELECT 'SHORT_STAY_DEPOSIT', d.id, 'short_stay_deposit:' || d.id || ':ended',
    timezone(zone.tz, d.ended_at)::date, d.ended_at, 'AUTO',
    'Short-stay deposit ' || CASE WHEN d.kept > 0 THEN 'kept for damage' ELSE 'returned' END
        || ' for ' || d.booking_number,
    CASE WHEN cash.code IS NULL AND d.kept < d.amount THEN 'No USD cash account is in the ledger' END,
    jsonb_build_array(
        jsonb_build_object('account', '2100', 'debit_cents', d.amount, 'memo', d.booking_number,
            'customer_id', d.customer_id, 'lease_id', NULL, 'unit_id', d.unit_id),
        jsonb_build_object('account', cash.code, 'credit_cents', d.amount - d.kept,
            'memo', d.booking_number, 'customer_id', d.customer_id, 'lease_id', NULL,
            'unit_id', d.unit_id),
        jsonb_build_object('account', '4070', 'credit_cents', d.kept, 'memo', d.booking_number,
            'customer_id', d.customer_id, 'lease_id', NULL, 'unit_id', d.unit_id))
FROM deposit AS d CROSS JOIN zone CROSS JOIN cash
WHERE d.kind = 'CASH' AND d.status <> 'HELD'
UNION ALL
-- A card hold kept for approved damage: the card is charged and the money comes to the bank.
SELECT 'SHORT_STAY_DEPOSIT', d.id, 'short_stay_deposit:' || d.id || ':card_kept',
    timezone(zone.tz, d.ended_at)::date, d.ended_at, 'AUTO',
    'Short-stay card hold kept for damage for ' || d.booking_number,
    CASE WHEN cash.bank IS NULL THEN 'No bank account is in the ledger' END,
    jsonb_build_array(
        jsonb_build_object('account', cash.bank, 'debit_cents', d.kept, 'memo', d.booking_number,
            'customer_id', d.customer_id, 'lease_id', NULL, 'unit_id', d.unit_id),
        jsonb_build_object('account', '4070', 'credit_cents', d.kept, 'memo', d.booking_number,
            'customer_id', d.customer_id, 'lease_id', NULL, 'unit_id', d.unit_id))
FROM deposit AS d CROSS JOIN zone CROSS JOIN cash
WHERE d.kind = 'CARD_HOLD' AND d.status = 'KEPT'
$$;
REVOKE ALL ON FUNCTION app.gl_short_stay_deposit_events(uuid) FROM PUBLIC;
"""

# function signature -> ((old text, new text), ...); each old text must appear exactly once.
PATCHES: dict[str, tuple[tuple[str, str], ...]] = {
    "app.gl_app_record_events(uuid, date, date)": (
        # 1. Short-stay Invoice lines: their Unit and their income account.
        (
            "        i.invoice_number, i.customer_id, i.lease_id, lease.unit_id, i.issued_at,\n",
            "        i.invoice_number, i.customer_id, i.lease_id,\n"
            "        coalesce(lease.unit_id, stay.unit_id) AS unit_id, i.issued_at,\n",
        ),
        ("        CASE l.category\n", "        coalesce(stay.code, CASE l.category\n"),
        ("        END AS other_code\n", "        END) AS other_code\n"),
        (
            "    LEFT JOIN app.unit_cleaning_charges AS cleaning ON cleaning.obligation_id = l.authorized_obligation_id\n",
            "    LEFT JOIN app.unit_cleaning_charges AS cleaning ON cleaning.obligation_id = l.authorized_obligation_id\n"
            "    LEFT JOIN app.short_stay_invoice_accounts AS stay ON stay.invoice_id = i.id\n",
        ),
        (
            "        i.invoice_number, i.customer_id, i.lease_id, lease.unit_id,\n"
            "        coalesce(l.category, i.primary_category) AS category,\n",
            "        i.invoice_number, i.customer_id, i.lease_id,\n"
            "        coalesce(lease.unit_id, lc.unit_id) AS unit_id,\n"
            "        coalesce(l.category, i.primary_category) AS category,\n",
        ),
        # 2 and 3. The short-stay deposits.
        (
            "\n)\nSELECT raw.source_type, raw.source_id,",
            "\n    UNION ALL\n"
            "    -- Daily and weekly rent: cash deposits and card holds kept for damage.\n"
            "    SELECT * FROM app.gl_short_stay_deposit_events(p_property)\n"
            ")\nSELECT raw.source_type, raw.source_id,",
        ),
    ),
    "app.gl_control_lists(uuid)": (
        (
            "UNION ALL SELECT '2100', coalesce(sum(balance_usd_cents) FILTER (WHERE balance_kind = 'SECURITY_DEPOSIT'), 0)::bigint FROM sources\n",
            "UNION ALL SELECT '2100', coalesce(sum(balance_usd_cents) FILTER (WHERE balance_kind = 'SECURITY_DEPOSIT'), 0)::bigint\n"
            "        + app.short_stay_cash_deposits_held(p_property) FROM sources\n",
        ),
    ),
}


def _literal_colons(sql: str) -> str:
    """Keep ``'invoice:...:issue'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def _patch(signature: str, changes: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for old, new in changes:
        if definition.count(old) != 1:
            raise RuntimeError(f"{signature} changed: expected one {old!r}")
        definition = definition.replace(old, new)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(_literal_colons(definition))


GRANTS = (
    "app.short_stay_credits_due(uuid, uuid)",
    "app.end_short_stay_credit(uuid, uuid, uuid, uuid)",
)


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(_literal_colons(FUNCTIONS))
    for signature in GRANTS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    for signature, changes in PATCHES.items():
        _patch(signature, changes)


def downgrade() -> None:
    raise RuntimeError("The short-stay ledger migration is forward-only")
