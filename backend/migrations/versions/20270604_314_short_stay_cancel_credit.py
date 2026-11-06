# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 4b: cancel, no-show and late-cancel credit.

The owner's rules (PRD 03/11/2026, Business rules > Short stays):

1. A booking that is not checked in yet is cancelled with a reason. It is free until 23:59
   SS_FREE_CANCEL_DAYS (2) days before the check-in day: the money paid comes back. The app makes
   it Customer Credit of the guest (a credit adjustment of each Invoice line), and the desk pays
   it back on the usual Refund of Credit, which keeps the approvals and the Receipt trail.
2. Later (or a guest who never came, a no-show, from the check-in day): no refund. The money paid
   is kept as income; what was not paid yet is no longer owed (an unpaid Invoice is voided, the
   unpaid rest of a partly paid one is credited off).
3. After a late cancel, the Owner, the Manager or the credit right may turn some or all of the kept
   money into Customer Credit, once, for SS_CREDIT_MONTHS (12; owner 05/11/2026) months: for a stay or the first
   month of a Lease, only when a Unit is free (the credit holds no room). The use-by day is kept.
4. A booking-site booking paid on the site follows the site's rules: the app moves no money.
5. The deposit always comes back.

Change to a Lease is step 4c. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270604_314"
down_revision: str | None = "20270603_313"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USED = ("SS_FREE_CANCEL_DAYS", "SS_CREDIT_MONTHS")

SCHEMA = r"""
CREATE TABLE app.short_stay_cancellations (
    booking_id uuid PRIMARY KEY REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('CANCELLED', 'NO_SHOW')),
    free boolean NOT NULL,
    paid_usd_cents bigint NOT NULL CHECK (paid_usd_cents >= 0),
    back_usd_cents bigint NOT NULL CHECK (back_usd_cents >= 0),
    kept_usd_cents bigint NOT NULL CHECK (kept_usd_cents >= 0),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT short_stay_cancellations_money CHECK (
        back_usd_cents + kept_usd_cents = paid_usd_cents
        AND (free OR back_usd_cents = 0) AND (NOT free OR kept_usd_cents = 0)
        AND (kind = 'CANCELLED' OR NOT free))
);

CREATE TABLE app.short_stay_credits (
    booking_id uuid PRIMARY KEY REFERENCES app.short_stay_cancellations (booking_id)
        ON DELETE RESTRICT,
    amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
    use_by date NOT NULL,
    note text NOT NULL CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
);

CREATE TRIGGER short_stay_cancellations_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_cancellations FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_cancellations_truncate BEFORE TRUNCATE ON app.short_stay_cancellations
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate();
CREATE TRIGGER short_stay_credits_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_credits FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_credits_truncate BEFORE TRUNCATE ON app.short_stay_credits
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate();

ALTER FUNCTION app.short_stay_booking_json(uuid) RENAME TO short_stay_booking_stay_json;
"""

FUNCTIONS = r"""
-- Every Invoice of the stay that is not voided: the main one, then fees and extensions.
CREATE FUNCTION app.short_stay_invoices(p_booking uuid) RETURNS SETOF uuid
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT invoice.id FROM (
        SELECT booking.invoice_id AS id, 0 AS position FROM app.short_stay_bookings AS booking
        WHERE booking.id = p_booking AND booking.invoice_id IS NOT NULL
        UNION ALL
        SELECT extra.invoice_id, extra.price_version FROM app.short_stay_extra_invoices AS extra
        WHERE extra.booking_id = p_booking
    ) AS found
    JOIN app.invoices AS invoice ON invoice.id = found.id
    WHERE invoice.status <> 'VOID'
    ORDER BY found.position
$$;
REVOKE ALL ON FUNCTION app.short_stay_invoices(uuid) FROM PUBLIC;

-- What the guest has paid on the stay's Invoices (payments, credit and deposits applied).
CREATE FUNCTION app.short_stay_paid(p_booking uuid) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT COALESCE(sum(app.invoice_line_application_value_at(line.id, 'infinity')), 0)::bigint
    FROM app.short_stay_invoices(p_booking) AS invoice(id)
    JOIN app.invoice_lines AS line ON line.invoice_id = invoice.id
$$;
REVOKE ALL ON FUNCTION app.short_stay_paid(uuid) FROM PUBLIC;

-- Credit adjustments on one Invoice. 'ALL' credits each line in full (what was paid becomes
-- Customer Credit), 'UNPAID' credits what is not paid yet, 'BUDGET' credits up to p_budget of
-- what was paid. Returns what was paid that became Customer Credit.
CREATE FUNCTION app.short_stay_credit_invoice(p_property uuid, p_invoice uuid, p_actor uuid,
    p_mode text, p_budget bigint, p_reference text, p_reason text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_line record;
    v_owed bigint;
    v_paid bigint;
    v_amount bigint;
    v_left bigint := COALESCE(p_budget, 0);
    v_credit bigint := 0;
    v_key uuid;
BEGIN
    FOR v_line IN SELECT line.id FROM app.invoice_lines AS line
                  WHERE line.invoice_id = p_invoice ORDER BY line.id LOOP
        v_owed := app.invoice_adjusted_line_obligation(v_line.id);
        v_paid := app.invoice_line_application_value_at(v_line.id, 'infinity');
        v_amount := CASE p_mode
            WHEN 'ALL' THEN v_owed
            WHEN 'UNPAID' THEN v_owed - v_paid
            ELSE least(v_owed, v_paid, v_left) END;
        IF v_amount > 0 THEN
            v_key := gen_random_uuid();
            PERFORM app.adjust_invoice(p_property, p_invoice, v_line.id, p_actor, v_key,
                encode(sha256(convert_to('short-stay-credit:' || v_key::text, 'UTF8')), 'hex'),
                (SELECT invoice.version FROM app.invoices AS invoice WHERE invoice.id = p_invoice),
                'CREDIT', v_amount, p_reference, p_reason, gen_random_uuid(), gen_random_uuid());
            v_credit := v_credit + greatest(v_paid - (v_owed - v_amount), 0);
            IF p_mode = 'BUDGET' THEN
                v_left := v_left - v_amount;
            END IF;
        END IF;
    END LOOP;
    RETURN v_credit;
END $$;
REVOKE ALL ON FUNCTION app.short_stay_credit_invoice(uuid, uuid, uuid, text, bigint, text, text) FROM PUBLIC;

-- The last day of free cancel (until 23:59).
CREATE FUNCTION app.short_stay_free_cancel_until(p_booking app.short_stay_bookings) RETURNS date
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT p_booking.check_in_on
        - app.short_stay_rule('SS_FREE_CANCEL_DAYS', p_booking.check_in_on)::integer
$$;
REVOKE ALL ON FUNCTION app.short_stay_free_cancel_until(app.short_stay_bookings) FROM PUBLIC;

CREATE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT app.short_stay_booking_stay_json(booking.id) || jsonb_build_object(
        'free_cancel_until', app.short_stay_free_cancel_until(booking),
        'cancel_reason', booking.cancel_reason, 'cancelled_at', booking.cancelled_at,
        'paid_usd_cents', app.short_stay_paid(booking.id),
        'cancellation', (SELECT jsonb_build_object('kind', cancel.kind, 'free', cancel.free,
                'paid_usd_cents', cancel.paid_usd_cents, 'back_usd_cents', cancel.back_usd_cents,
                'kept_usd_cents', cancel.kept_usd_cents, 'at', cancel.created_at)
            FROM app.short_stay_cancellations AS cancel WHERE cancel.booking_id = booking.id),
        'credit', (SELECT jsonb_build_object('amount_usd_cents', credit.amount_usd_cents,
                'use_by', credit.use_by, 'note', credit.note, 'at', credit.created_at)
            FROM app.short_stay_credits AS credit WHERE credit.booking_id = booking.id))
    FROM app.short_stay_bookings AS booking WHERE booking.id = p_booking
$$;
REVOKE ALL ON FUNCTION app.short_stay_booking_json(uuid) FROM PUBLIC;

-- 1. Cancel, or a no-show from the check-in day.
CREATE FUNCTION app.cancel_short_stay(p_property uuid, p_booking uuid, p_cancel jsonb,
    p_version integer, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
    v_reason text := NULLIF(btrim(p_cancel ->> 'reason'), '');
    v_no_show boolean;
    v_kind text;
    v_free boolean;
    v_paid bigint;
    v_back bigint := 0;
    v_invoice uuid;
    v_reference text := 'Short stay ' || v_row.booking_number;
BEGIN
    BEGIN
        v_no_show := COALESCE((p_cancel ->> 'no_show')::boolean, false);
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The cancel is invalid' USING ERRCODE = '22023';
    END;
    IF v_reason IS NULL OR length(v_reason) > 500 THEN
        RAISE EXCEPTION 'A cancel says why' USING ERRCODE = '22023';
    END IF;
    IF v_row.status <> 'BOOKED' THEN
        RAISE EXCEPTION 'Only a booking that is not checked in yet is cancelled' USING ERRCODE = '55000';
    END IF;
    IF v_no_show AND v_today < v_row.check_in_on THEN
        RAISE EXCEPTION 'A guest is a no-show only from the check-in day' USING ERRCODE = '55000';
    END IF;
    v_kind := CASE WHEN v_no_show THEN 'NO_SHOW' ELSE 'CANCELLED' END;
    v_free := NOT v_no_show AND v_today <= app.short_stay_free_cancel_until(v_row);
    v_paid := app.short_stay_paid(p_booking);
    FOR v_invoice IN SELECT stay_invoice.id FROM app.short_stay_invoices(p_booking) AS stay_invoice(id) LOOP
        IF NOT EXISTS (SELECT 1 FROM app.invoice_lines AS line
                       WHERE line.invoice_id = v_invoice
                         AND app.invoice_line_application_value_at(line.id, 'infinity') > 0) THEN
            PERFORM app.void_invoice(p_property, v_invoice, p_actor, gen_random_uuid(),
                encode(sha256(convert_to('short-stay-void:' || v_invoice::text, 'UTF8')), 'hex'),
                (SELECT invoice.version FROM app.invoices AS invoice WHERE invoice.id = v_invoice),
                v_reference || ' cancelled: ' || v_reason, gen_random_uuid(), gen_random_uuid());
        ELSE
            v_back := v_back + app.short_stay_credit_invoice(p_property, v_invoice, p_actor,
                CASE WHEN v_free THEN 'ALL' ELSE 'UNPAID' END, NULL, v_reference,
                CASE WHEN v_free THEN 'Free cancel: the money paid comes back'
                     ELSE 'Late cancel: what was not paid is no longer owed' END);
        END IF;
    END LOOP;
    UPDATE app.short_stay_deposits AS deposit
    SET status = 'RETURNED', ended_at = statement_timestamp(), ended_by = p_actor,
        end_note = 'The booking was cancelled', version = deposit.version + 1
    WHERE deposit.booking_id = p_booking AND deposit.status = 'HELD';
    UPDATE app.short_stay_bookings AS booking
    SET status = v_kind, cancelled_at = statement_timestamp(), cancelled_by = p_actor,
        cancel_reason = v_reason, version = booking.version + 1
    WHERE booking.id = p_booking;
    INSERT INTO app.short_stay_cancellations (booking_id, kind, free, paid_usd_cents,
        back_usd_cents, kept_usd_cents, created_by)
    VALUES (p_booking, v_kind, v_free, v_paid, v_back, v_paid - v_back, p_actor);
    PERFORM app.short_stay_event(p_booking, v_kind, p_actor, v_reason,
        jsonb_build_object('free', v_free, 'paid_usd_cents', v_paid, 'back_usd_cents', v_back));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.cancelled',
        'short_stay_booking', p_booking, v_reason, 'short_stays.desk',
        jsonb_build_object('status', 'BOOKED'),
        jsonb_build_object('status', v_kind, 'free', v_free, 'paid_usd_cents', v_paid,
            'back_usd_cents', v_back), COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 2. After a late cancel: some or all of the kept money as Customer Credit, once.
CREATE FUNCTION app.give_short_stay_credit(p_property uuid, p_booking uuid, p_credit jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.credit', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
    v_cancel app.short_stay_cancellations%ROWTYPE;
    v_amount bigint;
    v_note text := NULLIF(btrim(p_credit ->> 'note'), '');
    v_left bigint;
    v_given bigint := 0;
    v_invoice uuid;
    v_use_by date;
BEGIN
    BEGIN
        v_amount := (p_credit ->> 'amount_usd_cents')::bigint;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The credit amount is invalid' USING ERRCODE = '22023';
    END;
    SELECT cancel.* INTO v_cancel FROM app.short_stay_cancellations AS cancel
    WHERE cancel.booking_id = p_booking;
    IF NOT FOUND OR v_cancel.free OR v_cancel.kept_usd_cents = 0 THEN
        RAISE EXCEPTION 'Credit is given only for money kept after a late cancel'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_credits AS credit WHERE credit.booking_id = p_booking) THEN
        RAISE EXCEPTION 'This booking already has its credit' USING ERRCODE = '55000';
    END IF;
    IF v_amount IS NULL OR v_amount < 1 OR v_amount > v_cancel.kept_usd_cents THEN
        RAISE EXCEPTION 'The credit is at most the money kept' USING ERRCODE = '22023';
    END IF;
    IF v_note IS NULL OR length(v_note) > 500 THEN
        RAISE EXCEPTION 'A credit says why' USING ERRCODE = '22023';
    END IF;
    v_left := v_amount;
    FOR v_invoice IN SELECT stay_invoice.id FROM app.short_stay_invoices(p_booking) AS stay_invoice(id) LOOP
        EXIT WHEN v_left <= 0;
        v_given := v_given + app.short_stay_credit_invoice(p_property, v_invoice, p_actor,
            'BUDGET', v_left, 'Short stay ' || v_row.booking_number,
            'Late cancel credit: ' || v_note);
        v_left := v_amount - v_given;
    END LOOP;
    IF v_given <> v_amount THEN
        RAISE EXCEPTION 'The paid money could not be turned into credit' USING ERRCODE = '55000';
    END IF;
    v_use_by := (v_today + make_interval(months =>
        app.short_stay_rule('SS_CREDIT_MONTHS', v_today)::integer))::date;
    INSERT INTO app.short_stay_credits (booking_id, amount_usd_cents, use_by, note, created_by)
    VALUES (p_booking, v_amount, v_use_by, v_note, p_actor);
    -- A cancelled booking never changes; the credit row and the history keep the credit.
    PERFORM app.short_stay_event(p_booking, 'CREDIT_GIVEN', p_actor, v_note,
        jsonb_build_object('amount_usd_cents', v_amount, 'use_by', v_use_by));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.credit',
        'short_stay_booking', p_booking, v_note, 'short_stays.credit', NULL,
        jsonb_build_object('amount_usd_cents', v_amount, 'use_by', v_use_by),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_booking_json(p_booking);
END $$;
"""

ACTIONS = (
    "app.cancel_short_stay(uuid, uuid, jsonb, integer, uuid, uuid)",
    "app.give_short_stay_credit(uuid, uuid, jsonb, uuid, uuid)",
)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(FUNCTIONS)
    for signature in ACTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    codes = ", ".join(_text(code) for code in USED)
    op.execute(f"UPDATE app.business_rule_names SET used_by_app = true WHERE code IN ({codes})")


def downgrade() -> None:
    raise RuntimeError("Short stays step 4b migration is forward-only")
