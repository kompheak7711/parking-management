# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 5b: quotes, guest history, thank-you and extra discounts.

The owner's rules (PRD 03/11/2026):
1. A returning direct guest (walk-in, phone, Telegram, website) gets SS_RETURNING_GUEST_OFF ($3)
   off as a thank-you, when the guest has stayed and checked out before. Booking-site guests pay
   the site's price.
2. An extra discount needs the approve right (Owner or Manager) and a reason, before billing.
3. The Invoice shows the stay's lines; a thank-you or a discount is a credit adjustment of the
   Invoice (an Invoice line is never below zero), so the Invoice total is the booking total.
4. A quote (SQ) gives today's price for a Unit and nights, to send by Telegram. It is the price
   of today, not a promise: the booking is priced again when it is made.
5. Guest history: every stay of a guest, nights, money, notes and the problem-guest mark.
6. After the check-out the desk asks for a review once; the history keeps it.
7. The calendars are read every SS_CALENDAR_SYNC_MINUTES (the rule step 5a left fixed at 15).

Technical choices by Claude under the owner's 2026-10-23 22:30 rule. Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270607_317"
down_revision: str | None = "20270606_316"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USED = ("SS_RETURNING_GUEST_OFF", "SS_CALENDAR_SYNC_MINUTES")

BOOK = "app.make_short_stay_booking(uuid,jsonb,uuid,uuid)"
BOOK_REPLACEMENTS = (
    (
        "    v_price := app.short_stay_price(v_unit.default_monthly_rent_usd_cents,\n"
        "        v_check_out - v_check_in, v_check_in);\n",
        "    v_price := app.short_stay_price(v_unit.default_monthly_rent_usd_cents,\n"
        "        v_check_out - v_check_in, v_check_in);\n"
        "    -- Step 5b: a returning direct guest's thank-you.\n"
        "    v_price := app.short_stay_with_thank_you(v_price, v_customer, v_source, v_check_in);\n",
    ),
)

BILL = "app.bill_short_stay(uuid,uuid,integer,uuid,uuid)"
BILL_REPLACEMENTS = (
    (
        "                 AND line.amount_usd_cents < 1) THEN",
        "                 AND line.amount_usd_cents < 1\n"
        "                 AND line.kind NOT IN ('RETURNING_GUEST', 'EXTRA_DISCOUNT')) THEN",
    ),
    (
        "    WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version;\n"
        "    v_issued := app.short_stay_invoice(",
        "    WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version\n"
        "      AND line.amount_usd_cents > 0;\n"
        "    v_issued := app.short_stay_invoice(",
    ),
    (
        "    UPDATE app.short_stay_bookings AS booking\n"
        "    SET invoice_id = (v_issued ->> 'invoice_id')::uuid, version = booking.version + 1",
        "    -- Step 5b: the thank-you and the discount come off as a credit adjustment.\n"
        "    PERFORM app.short_stay_discount_invoice(p_property, (v_issued ->> 'invoice_id')::uuid,\n"
        "        v_row, p_actor);\n"
        "    UPDATE app.short_stay_bookings AS booking\n"
        "    SET invoice_id = (v_issued ->> 'invoice_id')::uuid, version = booking.version + 1",
    ),
)

SCHEMA = r"""
ALTER FUNCTION app.short_stay_booking_json(uuid) RENAME TO short_stay_booking_lease_json;
"""

FUNCTIONS = r"""
-- A returning direct guest's thank-you: one line off the price (rule of the check-in day).
CREATE FUNCTION app.short_stay_with_thank_you(p_price jsonb, p_customer uuid, p_source text,
    p_check_in date)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT CASE
        WHEN p_source = 'BOOKING_SITE' OR thank.off < 1
            OR (p_price ->> 'total_usd_cents')::bigint <= thank.off
            OR NOT EXISTS (SELECT 1 FROM app.short_stay_bookings AS before
                           WHERE before.customer_id = p_customer AND before.status = 'CHECKED_OUT')
        THEN p_price
        ELSE p_price || jsonb_build_object(
            'total_usd_cents', (p_price ->> 'total_usd_cents')::bigint - thank.off,
            'lines', (p_price -> 'lines') || jsonb_build_array(jsonb_build_object(
                'position', jsonb_array_length(p_price -> 'lines') + 1,
                'kind', 'RETURNING_GUEST', 'quantity', 1, 'unit_price_usd_cents', thank.off,
                'discount_basis_points', 0, 'amount_usd_cents', -thank.off)))
        END
    FROM (SELECT COALESCE(app.short_stay_rule('SS_RETURNING_GUEST_OFF', p_check_in), 0) AS off)
        AS thank
$$;
REVOKE ALL ON FUNCTION app.short_stay_with_thank_you(jsonb, uuid, text, date) FROM PUBLIC;

-- At billing: the thank-you and the discount lines as one credit adjustment on the largest line.
CREATE FUNCTION app.short_stay_discount_invoice(p_property uuid, p_invoice uuid,
    p_row app.short_stay_bookings, p_actor uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_off bigint;
    v_line uuid;
    v_key uuid := gen_random_uuid();
BEGIN
    SELECT COALESCE(-sum(line.amount_usd_cents), 0) INTO v_off
    FROM app.short_stay_price_lines AS line
    WHERE line.booking_id = p_row.id AND line.price_version = p_row.price_version
      AND line.amount_usd_cents < 0;
    IF v_off = 0 THEN
        RETURN;
    END IF;
    SELECT line.id INTO v_line FROM app.invoice_lines AS line
    WHERE line.invoice_id = p_invoice
      AND app.invoice_adjusted_line_obligation(line.id) >= v_off
    ORDER BY app.invoice_adjusted_line_obligation(line.id) DESC, line.line_sequence LIMIT 1;
    IF v_line IS NULL THEN
        RAISE EXCEPTION 'The discount is more than one line of the stay' USING ERRCODE = '55000';
    END IF;
    PERFORM app.adjust_invoice(p_property, p_invoice, v_line, p_actor, v_key,
        encode(sha256(convert_to('short-stay-discount:' || v_key::text, 'UTF8')), 'hex'),
        (SELECT invoice.version FROM app.invoices AS invoice WHERE invoice.id = p_invoice),
        'CREDIT', v_off, 'Short stay ' || p_row.booking_number || ': thank-you and discount',
        'Short-stay thank-you or discount', gen_random_uuid(), gen_random_uuid());
END $$;
REVOKE ALL ON FUNCTION app.short_stay_discount_invoice(uuid, uuid, app.short_stay_bookings, uuid)
    FROM PUBLIC;

-- An extra discount: Owner or Manager, with a reason, before the Invoice.
CREATE FUNCTION app.give_short_stay_discount(p_property uuid, p_booking uuid, p_discount jsonb,
    p_version integer, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.approve', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
    v_amount bigint;
    v_reason text := NULLIF(btrim(p_discount ->> 'reason'), '');
    v_next integer := v_row.price_version + 1;
BEGIN
    BEGIN
        v_amount := (p_discount ->> 'amount_usd_cents')::bigint;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The discount is a whole number of cents' USING ERRCODE = '22023';
    END;
    IF v_amount IS NULL OR v_amount < 1 THEN
        RAISE EXCEPTION 'The discount is a whole number of cents' USING ERRCODE = '22023';
    END IF;
    IF v_reason IS NULL OR length(v_reason) > 500 THEN
        RAISE EXCEPTION 'A discount needs a reason' USING ERRCODE = '22023';
    END IF;
    IF v_row.status <> 'BOOKED' OR app.short_stay_payment_state(p_booking) <> 'NOT_BILLED' THEN
        RAISE EXCEPTION 'A discount is given before the Invoice' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_price_lines AS line
               WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version
                 AND line.kind = 'EXTRA_DISCOUNT') THEN
        RAISE EXCEPTION 'This stay already has a discount' USING ERRCODE = '55000';
    END IF;
    IF v_amount >= v_row.total_usd_cents THEN
        RAISE EXCEPTION 'The discount is less than the stay' USING ERRCODE = '55000';
    END IF;
    INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind,
        quantity, unit_price_usd_cents, discount_basis_points, amount_usd_cents, reason,
        approved_by)
    SELECT p_booking, v_next, line.line_position, line.kind, line.quantity,
        line.unit_price_usd_cents, line.discount_basis_points, line.amount_usd_cents,
        line.reason, line.approved_by
    FROM app.short_stay_price_lines AS line
    WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version;
    INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind,
        quantity, unit_price_usd_cents, amount_usd_cents, reason, approved_by)
    SELECT p_booking, v_next, COALESCE(max(line.line_position), 0) + 1, 'EXTRA_DISCOUNT', 1,
        v_amount, -v_amount, v_reason, p_actor
    FROM app.short_stay_price_lines AS line
    WHERE line.booking_id = p_booking AND line.price_version = v_next;
    UPDATE app.short_stay_bookings AS booking
    SET price_version = v_next, total_usd_cents = booking.total_usd_cents - v_amount,
        version = booking.version + 1
    WHERE booking.id = p_booking;
    PERFORM app.short_stay_event(p_booking, 'DISCOUNT', p_actor, v_reason,
        jsonb_build_object('amount_usd_cents', v_amount));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.discount',
        'short_stay_booking', p_booking, v_reason, 'short_stays.approve', NULL,
        jsonb_build_object('amount_usd_cents', v_amount), COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- A guest's stays in this building, their notes and the problem-guest mark.
CREATE FUNCTION app.short_stay_guest_json(p_property uuid, p_customer uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT jsonb_build_object('customer_id', customer.id, 'legal_name', customer.legal_name,
        'phone_number', customer.phone_number,
        'stays', COALESCE((SELECT jsonb_agg(jsonb_build_object('booking_id', booking.id,
                'booking_number', booking.booking_number, 'unit_number', unit.unit_number,
                'check_in_on', booking.check_in_on, 'check_out_on', booking.check_out_on,
                'status', booking.status, 'source', booking.source,
                'site_name', booking.site_name, 'total_usd_cents', booking.total_usd_cents)
                ORDER BY booking.check_in_on DESC, booking.booking_number DESC)
            FROM app.short_stay_bookings AS booking
            JOIN app.units AS unit ON unit.id = booking.unit_id
            WHERE booking.customer_id = customer.id AND booking.property_id = p_property),
            '[]'::jsonb),
        'stays_done', (SELECT count(*) FROM app.short_stay_bookings AS booking
            WHERE booking.customer_id = customer.id AND booking.status = 'CHECKED_OUT'),
        'nights_done', (SELECT COALESCE(sum(booking.check_out_on - booking.check_in_on), 0)
            FROM app.short_stay_bookings AS booking
            WHERE booking.customer_id = customer.id AND booking.property_id = p_property
              AND booking.status = 'CHECKED_OUT'),
        'spent_usd_cents', (SELECT COALESCE(sum(booking.total_usd_cents), 0)
            FROM app.short_stay_bookings AS booking
            WHERE booking.customer_id = customer.id AND booking.property_id = p_property
              AND booking.status = 'CHECKED_OUT'),
        'returning', EXISTS (SELECT 1 FROM app.short_stay_bookings AS booking
            WHERE booking.customer_id = customer.id AND booking.status = 'CHECKED_OUT'),
        'problem_guest', EXISTS (SELECT 1 FROM app.guest_notes AS note
            WHERE note.customer_id = customer.id AND note.problem_guest),
        'notes', COALESCE((SELECT jsonb_agg(jsonb_build_object('note', note.note,
                'problem_guest', note.problem_guest, 'created_at', note.created_at,
                'booking_number', booking.booking_number)
                ORDER BY note.created_at DESC)
            FROM app.guest_notes AS note
            LEFT JOIN app.short_stay_bookings AS booking ON booking.id = note.booking_id
            WHERE note.customer_id = customer.id AND note.property_id = p_property), '[]'::jsonb))
    FROM app.customers AS customer WHERE customer.id = p_customer
$$;
REVOKE ALL ON FUNCTION app.short_stay_guest_json(uuid, uuid) FROM PUBLIC;

CREATE FUNCTION app.short_stay_guest(p_property uuid, p_customer uuid, p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.read', p_property);
    v_found jsonb := app.short_stay_guest_json(p_property, p_customer);
BEGIN
    IF v_found IS NULL THEN
        RAISE EXCEPTION 'the guest does not exist' USING ERRCODE = '22023';
    END IF;
    -- Today's thank-you, so New booking can say what comes off a direct booking.
    RETURN v_found || jsonb_build_object('thank_you_usd_cents',
        COALESCE(app.short_stay_rule('SS_RETURNING_GUEST_OFF', v_today), 0));
END $$;

-- A note about a guest (the front desk); a problem guest is flagged for every later booking.
CREATE FUNCTION app.add_guest_note(p_property uuid, p_customer uuid, p_note jsonb, p_actor uuid,
    p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_note text := NULLIF(btrim(p_note ->> 'note'), '');
    v_problem boolean;
    v_booking uuid;
    v_id uuid;
BEGIN
    BEGIN
        v_problem := COALESCE((p_note ->> 'problem_guest')::boolean, false);
        v_booking := (p_note ->> 'booking_id')::uuid;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The note is invalid' USING ERRCODE = '22023';
    END;
    IF NOT EXISTS (SELECT 1 FROM app.customers AS customer WHERE customer.id = p_customer) THEN
        RAISE EXCEPTION 'the guest does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_note IS NULL OR length(v_note) > 500 THEN
        RAISE EXCEPTION 'Write the note (up to 500 letters)' USING ERRCODE = '22023';
    END IF;
    IF v_booking IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.short_stay_bookings AS booking
            WHERE booking.id = v_booking AND booking.property_id = p_property
              AND booking.customer_id = p_customer) THEN
        RAISE EXCEPTION 'the booking does not exist' USING ERRCODE = '22023';
    END IF;
    INSERT INTO app.guest_notes (property_id, customer_id, booking_id, note, problem_guest,
        created_by)
    VALUES (p_property, p_customer, v_booking, v_note, v_problem, p_actor)
    RETURNING id INTO v_id;
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.guest_note',
        'customer', p_customer, 'Guest note', 'short_stays.desk', NULL,
        jsonb_build_object('note_id', v_id, 'problem_guest', v_problem),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_guest_json(p_property, p_customer);
END $$;

-- After the check-out the desk asks for a review, once.
CREATE FUNCTION app.ask_short_stay_review(p_property uuid, p_booking uuid, p_actor uuid,
    p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
BEGIN
    IF v_row.status <> 'CHECKED_OUT' THEN
        RAISE EXCEPTION 'A review is asked for after the check-out' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_booking_events AS event
               WHERE event.booking_id = p_booking AND event.kind = 'REVIEW_ASKED') THEN
        RAISE EXCEPTION 'A review was already asked for' USING ERRCODE = '55000';
    END IF;
    PERFORM app.short_stay_event(p_booking, 'REVIEW_ASKED', p_actor, NULL,
        jsonb_build_object('site_name', v_row.site_name));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.review_asked',
        'short_stay_booking', p_booking, 'Review asked for', 'short_stays.desk', NULL,
        jsonb_build_object('review_asked', true), COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- The booking with its guest's marks and the review.
CREATE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT stay.found || jsonb_build_object(
        -- The Invoice's amount after the thank-you or discount credit.
        'invoice', CASE WHEN jsonb_typeof(stay.found -> 'invoice') = 'object'
            THEN (stay.found -> 'invoice') || jsonb_build_object('due_usd_cents',
                (SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(line.id)), 0)
                 FROM app.invoice_lines AS line WHERE line.invoice_id = booking.invoice_id))
            ELSE 'null'::jsonb END,
        'returning_guest', EXISTS (SELECT 1 FROM app.short_stay_bookings AS before
            WHERE before.customer_id = booking.customer_id AND before.status = 'CHECKED_OUT'
              AND before.id <> booking.id AND before.check_out_on <= booking.check_in_on),
        'problem_guest', EXISTS (SELECT 1 FROM app.guest_notes AS note
            WHERE note.customer_id = booking.customer_id AND note.problem_guest),
        'review_asked_at', (SELECT min(event.occurred_at)
            FROM app.short_stay_booking_events AS event
            WHERE event.booking_id = booking.id AND event.kind = 'REVIEW_ASKED'))
    FROM app.short_stay_bookings AS booking
    CROSS JOIN LATERAL (SELECT app.short_stay_booking_lease_json(booking.id) AS found) AS stay
    WHERE booking.id = p_booking
$$;
REVOKE ALL ON FUNCTION app.short_stay_booking_json(uuid) FROM PUBLIC;

CREATE FUNCTION app.short_stay_quote_json(p_quote uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT jsonb_build_object('quote_id', quote.id, 'quote_number', quote.quote_number,
        'unit_id', quote.unit_id, 'unit_number', unit.unit_number, 'unit_type', quote.unit_type,
        'customer_id', quote.customer_id,
        'guest_name', COALESCE(customer.legal_name, quote.guest_name),
        'guest_contact', COALESCE(quote.guest_contact, customer.phone_number),
        'guest_count', quote.guest_count, 'check_in_on', quote.check_in_on,
        'check_out_on', quote.check_out_on, 'nights', quote.check_out_on - quote.check_in_on,
        'total_usd_cents', quote.total_usd_cents, 'lines', quote.price_lines,
        'made_on', quote.made_on, 'valid_until', quote.valid_until,
        'check_in_time', app.short_stay_rule('SS_CHECK_IN_TIME', quote.check_in_on),
        'check_out_time', app.short_stay_rule('SS_CHECK_OUT_TIME', quote.check_in_on),
        'deposit_usd_cents', app.short_stay_rule('SS_CASH_DEPOSIT', quote.check_in_on))
    FROM app.short_stay_quotes AS quote
    LEFT JOIN app.units AS unit ON unit.id = quote.unit_id
    LEFT JOIN app.customers AS customer ON customer.id = quote.customer_id
    WHERE quote.id = p_quote
$$;
REVOKE ALL ON FUNCTION app.short_stay_quote_json(uuid) FROM PUBLIC;

-- A quote: today's price for a Unit and nights, to send to the guest. Not a promise.
CREATE FUNCTION app.make_short_stay_quote(p_property uuid, p_quote jsonb, p_actor uuid,
    p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_unit app.units%ROWTYPE;
    v_customer uuid;
    v_name text := NULLIF(btrim(p_quote ->> 'guest_name'), '');
    v_contact text := NULLIF(btrim(p_quote ->> 'guest_contact'), '');
    v_check_in date;
    v_check_out date;
    v_guests integer;
    v_blockers jsonb;
    v_price jsonb;
    v_id uuid;
BEGIN
    BEGIN
        v_customer := (p_quote ->> 'customer_id')::uuid;
        v_check_in := (p_quote ->> 'check_in_on')::date;
        v_check_out := (p_quote ->> 'check_out_on')::date;
        v_guests := (p_quote ->> 'guest_count')::integer;
        SELECT unit.* INTO v_unit FROM app.units AS unit
        WHERE unit.id = (p_quote ->> 'unit_id')::uuid AND unit.property_id = p_property;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The quote is invalid' USING ERRCODE = '22023';
    END;
    IF v_unit.id IS NULL THEN
        RAISE EXCEPTION 'the Unit does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_customer IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.customers AS customer
                                              WHERE customer.id = v_customer) THEN
        RAISE EXCEPTION 'the Customer does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_customer IS NULL AND v_name IS NULL THEN
        RAISE EXCEPTION 'A quote names its guest' USING ERRCODE = '22023';
    END IF;
    IF length(v_name) > 120 OR length(v_contact) > 120 THEN
        RAISE EXCEPTION 'A text is too long' USING ERRCODE = '22023';
    END IF;
    IF v_check_in IS NULL OR v_check_out IS NULL OR v_check_out <= v_check_in THEN
        RAISE EXCEPTION 'The check-out day is after the check-in day' USING ERRCODE = '22023';
    END IF;
    IF v_guests IS NULL OR v_guests NOT BETWEEN 1 AND 10 THEN
        RAISE EXCEPTION 'A booking is for 1 to 10 guests' USING ERRCODE = '22023';
    END IF;
    v_blockers := app.short_stay_blockers(v_unit.id, v_check_in, v_check_out, v_today);
    IF v_blockers <> '[]'::jsonb
        OR app.short_stay_site_holds(v_unit.id, v_check_in, v_check_out, NULL) <> '[]'::jsonb THEN
        RAISE EXCEPTION 'The Unit cannot be booked for these nights' USING ERRCODE = '55000';
    END IF;
    v_price := app.short_stay_price(v_unit.default_monthly_rent_usd_cents,
        v_check_out - v_check_in, v_check_in);
    IF v_customer IS NOT NULL THEN
        v_price := app.short_stay_with_thank_you(v_price, v_customer, 'TELEGRAM', v_check_in);
    END IF;
    INSERT INTO app.short_stay_quotes (property_id, quote_number, unit_id, unit_type,
        customer_id, guest_name, guest_contact, guest_count, check_in_on, check_out_on,
        total_usd_cents, price_lines, made_on, valid_until, created_by)
    VALUES (p_property,
        app.take_document_number('SHORT_STAY_QUOTE', date_part('year', v_today)::integer),
        v_unit.id, v_unit.unit_type, v_customer, CASE WHEN v_customer IS NULL THEN v_name END,
        v_contact, v_guests, v_check_in, v_check_out, (v_price ->> 'total_usd_cents')::bigint,
        v_price -> 'lines', v_today, v_today, p_actor)
    RETURNING id INTO v_id;
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.quoted',
        'short_stay_quote', v_id, 'Short-stay quote', 'short_stays.desk', NULL,
        jsonb_build_object('total_usd_cents', v_price -> 'total_usd_cents'),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_quote_json(v_id);
END $$;

CREATE FUNCTION app.short_stay_quotes_read(p_property uuid, p_actor uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    PERFORM app.require_product_right(p_actor, 'short_stays.read', p_property);
    RETURN COALESCE((SELECT jsonb_agg(app.short_stay_quote_json(recent.id)
            ORDER BY recent.created_at DESC, recent.quote_number DESC)
        FROM (SELECT quote.id, quote.created_at, quote.quote_number
              FROM app.short_stay_quotes AS quote WHERE quote.property_id = p_property
              ORDER BY quote.created_at DESC, quote.quote_number DESC LIMIT 100) AS recent),
        '[]'::jsonb);
END $$;

-- Step 5a read the calendars every 15 minutes; the owner's rule decides.
CREATE OR REPLACE FUNCTION app.booking_site_calendars_due(p_property uuid, p_actor uuid,
    p_limit integer)
RETURNS TABLE (calendar_id uuid, import_url text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_minutes bigint;
BEGIN
    PERFORM app.assert_active_financial_actor(p_actor, p_property);
    SELECT COALESCE(app.short_stay_rule('SS_CALENDAR_SYNC_MINUTES',
            timezone(property.timezone_name, statement_timestamp())::date), 15)
        INTO v_minutes
    FROM app.properties AS property WHERE property.id = p_property;
    RETURN QUERY
    SELECT calendar.id, calendar.import_url FROM app.booking_site_calendars AS calendar
    WHERE calendar.property_id = p_property AND calendar.active AND calendar.import_url IS NOT NULL
      AND (calendar.last_read_at IS NULL
           OR calendar.last_read_at < statement_timestamp() - make_interval(mins => v_minutes::integer))
    ORDER BY calendar.last_read_at NULLS FIRST, calendar.id
    LIMIT LEAST(GREATEST(p_limit, 1), 100);
END $$;
"""

READS = (
    "app.give_short_stay_discount(uuid, uuid, jsonb, integer, uuid, uuid)",
    "app.short_stay_guest(uuid, uuid, uuid)",
    "app.add_guest_note(uuid, uuid, jsonb, uuid, uuid)",
    "app.ask_short_stay_review(uuid, uuid, uuid, uuid)",
    "app.make_short_stay_quote(uuid, jsonb, uuid, uuid)",
    "app.short_stay_quotes_read(uuid, uuid)",
)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Short-stay source contract changed: {signature}")
        definition = definition.replace(before, after)
    op.execute(definition)


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(FUNCTIONS)
    _patch(BOOK, BOOK_REPLACEMENTS)
    _patch(BILL, BILL_REPLACEMENTS)
    for signature in READS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    codes = ", ".join(_text(code) for code in USED)
    op.execute(f"UPDATE app.business_rule_names SET used_by_app = true WHERE code IN ({codes})")


def downgrade() -> None:
    raise RuntimeError("Short stays step 5b migration is forward-only")
