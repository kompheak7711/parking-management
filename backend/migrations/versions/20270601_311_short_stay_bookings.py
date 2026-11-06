# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 2: the price, the calendar and a new booking.

The owner's price rules (03/11 and 04/11/2026; card answer 04/11 16:21 "Weeks + cheaper of two
prices"), all read from Settings on the check-in day:

1. Night price = monthly rent x SS_NIGHT_PERCENT (300%) / SS_NIGHT_DAYS (30), and week price =
   monthly rent x SS_WEEK_PERCENT (200%) / SS_WEEKS_IN_MONTH_TENTHS (4.3), each rounded down to
   a whole dollar. The monthly rent is the Unit's default monthly Rent.
2. 1 night: the night price. 2 nights: SS_TWO_NIGHTS_OFF (20%) off each night. 3 to 6 nights:
   SS_THREE_NIGHTS_OFF (30%) off each night (rounded down to the cent).
3. 7 nights or more: whole weeks, then the extra nights at the 3-to-6-night price. 2 weeks get
   SS_TWO_WEEKS_OFF (10%) and 3 weeks or more SS_THREE_WEEKS_OFF (15%), rounded down to a whole
   dollar. A stay never costs more than the next whole week: when it would, the guest pays the
   whole-week price (13 nights in a one bedroom $225, 27 nights $425).
4. At most SS_MAX_NIGHTS (29) nights; longer is a Lease.
5. The monthly hint: when the stay costs more than the 1-month-only rent of the Unit type
   (SS_MONTH_ONLY_STUDIO, _ONE_BEDROOM, _TWO_BEDROOM), staff offer the month.

A booking (``app.make_short_stay_booking``) is for a guest who is a Customer, in a Unit that is
for rent, not under maintenance or out of service, without an active Reservation, from today
on. Its price lines are saved as price version 1 and the history starts with Booked.
Technical choices by Claude under the owner's 2026-10-23 22:30 rule. Forward-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270601_311"
down_revision: str | None = "20270531_310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USED = (
    "SS_NIGHT_PERCENT",
    "SS_NIGHT_DAYS",
    "SS_WEEK_PERCENT",
    "SS_WEEKS_IN_MONTH_TENTHS",
    "SS_TWO_NIGHTS_OFF",
    "SS_THREE_NIGHTS_OFF",
    "SS_TWO_WEEKS_OFF",
    "SS_THREE_WEEKS_OFF",
    "SS_MAX_NIGHTS",
    "SS_MONTH_ONLY_STUDIO",
    "SS_MONTH_ONLY_ONE_BEDROOM",
    "SS_MONTH_ONLY_TWO_BEDROOM",
)

FUNCTIONS = r"""
-- A short-stay rule on a day; every one has a first value, so a missing one is an error.
CREATE FUNCTION app.short_stay_rule(p_code text, p_on date) RETURNS bigint
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
DECLARE v_value bigint := app.business_rule_value(p_code, p_on);
BEGIN
    IF v_value IS NULL THEN
        RAISE EXCEPTION 'The rule % has no value on %', p_code, p_on USING ERRCODE = '22023';
    END IF;
    RETURN v_value;
END $$;
REVOKE ALL ON FUNCTION app.short_stay_rule(text, date) FROM PUBLIC;

-- Whole weeks at their discount, rounded down to a whole dollar.
CREATE FUNCTION app.short_stay_weeks_amount(p_week bigint, p_weeks integer, p_on date)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
DECLARE v_off bigint := CASE
    WHEN p_weeks >= 3 THEN app.short_stay_rule('SS_THREE_WEEKS_OFF', p_on)
    WHEN p_weeks = 2 THEN app.short_stay_rule('SS_TWO_WEEKS_OFF', p_on)
    ELSE 0 END;
BEGIN
    RETURN jsonb_build_object('kind', 'WEEKS', 'quantity', p_weeks,
        'unit_price_usd_cents', p_week, 'discount_basis_points', v_off,
        'amount_usd_cents', (p_weeks * p_week * (10000 - v_off) / 10000) / 100 * 100);
END $$;
REVOKE ALL ON FUNCTION app.short_stay_weeks_amount(bigint, integer, date) FROM PUBLIC;

-- The price of a stay of p_nights for a monthly rent, with the rules of the day p_on.
CREATE FUNCTION app.short_stay_price(p_rent bigint, p_nights integer, p_on date)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
DECLARE
    v_night bigint;
    v_week bigint;
    v_lines jsonb := '[]'::jsonb;
    v_weeks integer := p_nights / 7;
    v_extra integer := p_nights % 7;
    v_off bigint;
    v_total bigint;
    v_whole jsonb;
    v_capped boolean := false;
BEGIN
    IF p_rent IS NULL OR p_rent <= 0 THEN
        RAISE EXCEPTION 'The Unit has no monthly Rent to price a short stay from'
            USING ERRCODE = '55000';
    END IF;
    IF p_nights IS NULL OR p_nights < 1
        OR p_nights > app.short_stay_rule('SS_MAX_NIGHTS', p_on) THEN
        RAISE EXCEPTION 'A short stay is 1 to % nights; a longer stay is a Lease',
            app.short_stay_rule('SS_MAX_NIGHTS', p_on) USING ERRCODE = '22023';
    END IF;
    v_night := p_rent * app.short_stay_rule('SS_NIGHT_PERCENT', p_on)
        / (10000 * app.short_stay_rule('SS_NIGHT_DAYS', p_on)) / 100 * 100;
    v_week := p_rent * app.short_stay_rule('SS_WEEK_PERCENT', p_on) * 10
        / (10000 * app.short_stay_rule('SS_WEEKS_IN_MONTH_TENTHS', p_on)) / 100 * 100;
    IF v_weeks > 0 THEN
        v_lines := jsonb_build_array(app.short_stay_weeks_amount(v_week, v_weeks, p_on));
    END IF;
    IF v_extra > 0 THEN
        v_off := CASE
            WHEN v_weeks > 0 OR v_extra >= 3 THEN app.short_stay_rule('SS_THREE_NIGHTS_OFF', p_on)
            WHEN v_extra = 2 THEN app.short_stay_rule('SS_TWO_NIGHTS_OFF', p_on)
            ELSE 0 END;
        v_lines := v_lines || jsonb_build_array(jsonb_build_object('kind', 'NIGHTS',
            'quantity', v_extra, 'unit_price_usd_cents', v_night,
            'discount_basis_points', v_off,
            'amount_usd_cents', v_extra * (v_night * (10000 - v_off) / 10000)));
    END IF;
    SELECT sum((line ->> 'amount_usd_cents')::bigint) INTO v_total
    FROM jsonb_array_elements(v_lines) AS line;
    -- Never more than the next whole week (owner 04/11/2026 16:21).
    IF v_extra > 0 AND p_nights >= 3 THEN
        v_whole := app.short_stay_weeks_amount(v_week, v_weeks + 1, p_on);
        IF (v_whole ->> 'amount_usd_cents')::bigint < v_total THEN
            v_lines := jsonb_build_array(v_whole);
            v_total := (v_whole ->> 'amount_usd_cents')::bigint;
            v_capped := true;
        END IF;
    END IF;
    RETURN jsonb_build_object(
        'nights', p_nights, 'night_usd_cents', v_night, 'week_usd_cents', v_week,
        'total_usd_cents', v_total, 'charged_as_whole_weeks', v_capped,
        'lines', (SELECT jsonb_agg(line || jsonb_build_object('position', position)
                                   ORDER BY position)
                  FROM jsonb_array_elements(v_lines) WITH ORDINALITY AS listed(line, position)));
END $$;
REVOKE ALL ON FUNCTION app.short_stay_price(bigint, integer, date) FROM PUBLIC;

-- The 1-month-only rent of a Unit type (NULL when the owner has not set one).
CREATE FUNCTION app.short_stay_month_only(p_unit_type text, p_on date) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT app.business_rule_value('SS_MONTH_ONLY_' || p_unit_type, p_on)
$$;
REVOKE ALL ON FUNCTION app.short_stay_month_only(text, date) FROM PUBLIC;

-- Why a Unit cannot be booked for these nights (empty when it can).
CREATE FUNCTION app.short_stay_blockers(p_unit uuid, p_check_in date, p_check_out date,
    p_today date)
RETURNS jsonb LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT COALESCE(jsonb_agg(blocker ORDER BY blocker), '[]'::jsonb) FROM (
        SELECT 'PAST' AS blocker WHERE p_check_in < p_today
        UNION ALL SELECT 'NOT_FOR_RENT' FROM app.units AS unit
            WHERE unit.id = p_unit AND unit.for_rent = false
        UNION ALL SELECT 'UNIT_' || unit.status FROM app.units AS unit
            WHERE unit.id = p_unit AND unit.status IN ('UNDER_MAINTENANCE', 'OUT_OF_SERVICE')
        UNION ALL SELECT 'RESERVED' WHERE EXISTS (
            SELECT 1 FROM app.reservations AS reservation
            WHERE reservation.unit_id = p_unit AND reservation.status = 'ACTIVE')
        UNION ALL SELECT 'LEASE' WHERE EXISTS (
            SELECT 1 FROM app.leases AS lease
            WHERE lease.unit_id = p_unit AND lease.status IN ('SIGNED', 'TERMINATED')
              AND app.short_stay_lease_night_taken(p_unit, p_check_in, p_check_out,
                  lease.start_date, CASE WHEN lease.status = 'TERMINATED'
                      THEN lease.actual_termination_date ELSE lease.end_date END))
        UNION ALL SELECT 'BOOKED' WHERE EXISTS (
            SELECT 1 FROM app.short_stay_bookings AS booking
            WHERE booking.unit_id = p_unit AND booking.status IN ('BOOKED', 'CHECKED_IN')
              AND daterange(booking.check_in_on, booking.check_out_on, '[)')
                  && daterange(p_check_in, p_check_out, '[)'))
    ) AS found
$$;
REVOKE ALL ON FUNCTION app.short_stay_blockers(uuid, date, date, date) FROM PUBLIC;

-- What a stay in a Unit costs (the price box and the quote).
CREATE FUNCTION app.short_stay_price_read(p_property uuid, p_unit uuid, p_check_in date,
    p_check_out date, p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.read', p_property);
    v_unit app.units%ROWTYPE;
    v_price jsonb;
    v_month bigint;
BEGIN
    SELECT unit.* INTO v_unit FROM app.units AS unit
    WHERE unit.id = p_unit AND unit.property_id = p_property;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the Unit does not exist' USING ERRCODE = '22023';
    END IF;
    IF p_check_in IS NULL OR p_check_out IS NULL OR p_check_out <= p_check_in THEN
        RAISE EXCEPTION 'The check-out day is after the check-in day' USING ERRCODE = '22023';
    END IF;
    v_price := app.short_stay_price(v_unit.default_monthly_rent_usd_cents,
        p_check_out - p_check_in, p_check_in);
    v_month := app.short_stay_month_only(v_unit.unit_type, p_check_in);
    RETURN v_price || jsonb_build_object(
        'unit_id', v_unit.id, 'unit_number', v_unit.unit_number, 'unit_type', v_unit.unit_type,
        'check_in_on', p_check_in, 'check_out_on', p_check_out,
        'monthly_rent_usd_cents', v_unit.default_monthly_rent_usd_cents,
        'month_only_usd_cents', v_month,
        'suggest_month', v_month IS NOT NULL AND (v_price ->> 'total_usd_cents')::bigint > v_month,
        'blockers', app.short_stay_blockers(p_unit, p_check_in, p_check_out, v_today));
END $$;

-- The calendar: every Unit with its bookings, Leases and Reservation in the days shown.
CREATE FUNCTION app.short_stay_calendar(p_property uuid, p_from date, p_days integer,
    p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.read', p_property);
    v_to date;
BEGIN
    IF p_from IS NULL OR p_days IS NULL OR p_days NOT BETWEEN 1 AND 62 THEN
        RAISE EXCEPTION 'The calendar shows 1 to 62 days' USING ERRCODE = '22023';
    END IF;
    v_to := p_from + p_days;
    RETURN jsonb_build_object('from', p_from, 'days', p_days, 'today', v_today,
        'units', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'unit_id', unit.id, 'unit_number', unit.unit_number, 'floor', unit.floor,
                'unit_type', unit.unit_type, 'status', unit.status, 'for_rent', unit.for_rent,
                'monthly_rent_usd_cents', unit.default_monthly_rent_usd_cents,
                'bookings', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                        'booking_id', booking.id, 'booking_number', booking.booking_number,
                        'guest_name', customer.legal_name, 'status', booking.status,
                        'source', booking.source, 'check_in_on', booking.check_in_on,
                        'check_out_on', booking.check_out_on) ORDER BY booking.check_in_on)
                    FROM app.short_stay_bookings AS booking
                    JOIN app.customers AS customer ON customer.id = booking.customer_id
                    WHERE booking.unit_id = unit.id
                      AND booking.status IN ('BOOKED', 'CHECKED_IN', 'CHECKED_OUT')
                      AND booking.check_in_on < v_to AND booking.check_out_on > p_from),
                    '[]'::jsonb),
                'leases', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('lease_id', lease.id,
                        'start_date', lease.start_date,
                        'end_date', CASE WHEN lease.status = 'TERMINATED'
                            THEN lease.actual_termination_date ELSE lease.end_date END)
                        ORDER BY lease.start_date)
                    FROM app.leases AS lease
                    WHERE lease.unit_id = unit.id AND lease.status IN ('SIGNED', 'TERMINATED')
                      AND lease.start_date < v_to
                      AND CASE WHEN lease.status = 'TERMINATED'
                          THEN lease.actual_termination_date ELSE lease.end_date END >= p_from),
                    '[]'::jsonb),
                'reserved', EXISTS (SELECT 1 FROM app.reservations AS reservation
                    WHERE reservation.unit_id = unit.id AND reservation.status = 'ACTIVE'))
                ORDER BY unit.unit_number)
            FROM app.units AS unit WHERE unit.property_id = p_property), '[]'::jsonb));
END $$;

-- One booking as the screens read it.
CREATE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT jsonb_build_object(
        'booking_id', booking.id, 'booking_number', booking.booking_number,
        'unit_id', booking.unit_id, 'unit_number', unit.unit_number, 'unit_type', unit.unit_type,
        'customer_id', booking.customer_id, 'guest_name', customer.legal_name,
        'guest_phone', customer.phone_number, 'guest_count', booking.guest_count,
        'check_in_on', booking.check_in_on, 'check_out_on', booking.check_out_on,
        'nights', booking.nights, 'source', booking.source, 'site_name', booking.site_name,
        'site_reference', booking.site_reference, 'note', booking.note,
        'status', booking.status, 'total_usd_cents', booking.total_usd_cents,
        'price_version', booking.price_version, 'version', booking.version,
        'created_at', booking.created_at,
        'lines', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('position', line.line_position,
                'kind', line.kind, 'quantity', line.quantity,
                'unit_price_usd_cents', line.unit_price_usd_cents,
                'discount_basis_points', line.discount_basis_points,
                'amount_usd_cents', line.amount_usd_cents, 'reason', line.reason)
                ORDER BY line.line_position)
            FROM app.short_stay_price_lines AS line
            WHERE line.booking_id = booking.id AND line.price_version = booking.price_version),
            '[]'::jsonb),
        'history', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('kind', event.kind,
                'occurred_at', event.occurred_at, 'actor_id', event.actor_id,
                'note', event.note, 'details', event.details) ORDER BY event.event_number)
            FROM app.short_stay_booking_events AS event WHERE event.booking_id = booking.id),
            '[]'::jsonb))
    FROM app.short_stay_bookings AS booking
    JOIN app.units AS unit ON unit.id = booking.unit_id
    JOIN app.customers AS customer ON customer.id = booking.customer_id
    WHERE booking.id = p_booking
$$;
REVOKE ALL ON FUNCTION app.short_stay_booking_json(uuid) FROM PUBLIC;

CREATE FUNCTION app.short_stay_bookings_read(p_property uuid, p_actor uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    PERFORM app.require_product_right(p_actor, 'short_stays.read', p_property);
    RETURN COALESCE((
        SELECT jsonb_agg(app.short_stay_booking_json(recent.id)
            ORDER BY recent.check_in_on DESC, recent.booking_number DESC)
        FROM (SELECT booking.id, booking.check_in_on, booking.booking_number
              FROM app.short_stay_bookings AS booking
              WHERE booking.property_id = p_property
              ORDER BY booking.check_in_on DESC, booking.booking_number DESC
              LIMIT 300) AS recent), '[]'::jsonb);
END $$;

CREATE FUNCTION app.short_stay_booking_read(p_property uuid, p_booking uuid, p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    PERFORM app.require_product_right(p_actor, 'short_stays.read', p_property);
    IF NOT EXISTS (SELECT 1 FROM app.short_stay_bookings AS booking
                   WHERE booking.id = p_booking AND booking.property_id = p_property) THEN
        RAISE EXCEPTION 'the booking does not exist' USING ERRCODE = '22023';
    END IF;
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- A history row for a booking, numbered in order.
CREATE FUNCTION app.short_stay_event(p_booking uuid, p_kind text, p_actor uuid, p_note text,
    p_details jsonb)
RETURNS void LANGUAGE sql SET search_path = pg_catalog AS $$
    INSERT INTO app.short_stay_booking_events (booking_id, event_number, kind, actor_id, note,
        details)
    SELECT p_booking, COALESCE(max(event.event_number), 0) + 1, p_kind, p_actor, p_note,
        COALESCE(p_details, '{}'::jsonb)
    FROM app.short_stay_booking_events AS event WHERE event.booking_id = p_booking
$$;
REVOKE ALL ON FUNCTION app.short_stay_event(uuid, text, uuid, text, jsonb) FROM PUBLIC;

-- A new booking for a guest who is a Customer.
CREATE FUNCTION app.make_short_stay_booking(p_property uuid, p_booking jsonb, p_actor uuid,
    p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_id uuid := gen_random_uuid();
    v_unit app.units%ROWTYPE;
    v_customer uuid;
    v_check_in date;
    v_check_out date;
    v_guests integer;
    v_source text := p_booking ->> 'source';
    v_site text := NULLIF(btrim(p_booking ->> 'site_name'), '');
    v_reference text := NULLIF(btrim(p_booking ->> 'site_reference'), '');
    v_note text := NULLIF(btrim(p_booking ->> 'note'), '');
    v_blockers jsonb;
    v_price jsonb;
    v_number text;
BEGIN
    IF p_booking IS NULL OR jsonb_typeof(p_booking) <> 'object' THEN
        RAISE EXCEPTION 'The booking is invalid' USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_customer := (p_booking ->> 'customer_id')::uuid;
        v_check_in := (p_booking ->> 'check_in_on')::date;
        v_check_out := (p_booking ->> 'check_out_on')::date;
        v_guests := (p_booking ->> 'guest_count')::integer;
        SELECT unit.* INTO v_unit FROM app.units AS unit
        WHERE unit.id = (p_booking ->> 'unit_id')::uuid AND unit.property_id = p_property
        FOR UPDATE;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The booking is invalid' USING ERRCODE = '22023';
    END;
    IF v_unit.id IS NULL THEN
        RAISE EXCEPTION 'the Unit does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_customer IS NULL OR NOT EXISTS (
        SELECT 1 FROM app.customers AS customer
        WHERE customer.id = v_customer AND customer.deactivated_at IS NULL) THEN
        RAISE EXCEPTION 'the Customer does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_check_in IS NULL OR v_check_out IS NULL OR v_check_out <= v_check_in THEN
        RAISE EXCEPTION 'The check-out day is after the check-in day' USING ERRCODE = '22023';
    END IF;
    IF v_guests IS NULL OR v_guests NOT BETWEEN 1 AND 10 THEN
        RAISE EXCEPTION 'A booking is for 1 to 10 guests' USING ERRCODE = '22023';
    END IF;
    IF v_source IS NULL
        OR v_source NOT IN ('WALK_IN', 'PHONE', 'TELEGRAM', 'WEBSITE', 'BOOKING_SITE') THEN
        RAISE EXCEPTION 'The booking source is invalid' USING ERRCODE = '22023';
    END IF;
    IF (v_source = 'BOOKING_SITE') <> (v_site IS NOT NULL)
        OR (v_reference IS NOT NULL AND v_source <> 'BOOKING_SITE') THEN
        RAISE EXCEPTION 'A booking-site booking names its site; other bookings do not'
            USING ERRCODE = '22023';
    END IF;
    IF length(v_site) > 80 OR length(v_reference) > 80 OR length(v_note) > 500 THEN
        RAISE EXCEPTION 'A text is too long' USING ERRCODE = '22023';
    END IF;
    v_blockers := app.short_stay_blockers(v_unit.id, v_check_in, v_check_out, v_today);
    IF v_blockers <> '[]'::jsonb THEN
        RAISE EXCEPTION 'The Unit cannot be booked for these nights: %',
            (SELECT string_agg(value, ', ') FROM jsonb_array_elements_text(v_blockers))
            USING ERRCODE = '55000';
    END IF;
    v_price := app.short_stay_price(v_unit.default_monthly_rent_usd_cents,
        v_check_out - v_check_in, v_check_in);
    v_number := app.take_document_number('SHORT_STAY', date_part('year', v_today)::integer);
    INSERT INTO app.short_stay_bookings (id, property_id, unit_id, booking_number, customer_id,
        guest_count, check_in_on, check_out_on, source, site_name, site_reference, note,
        total_usd_cents, created_by)
    VALUES (v_id, p_property, v_unit.id, v_number, v_customer, v_guests, v_check_in,
        v_check_out, v_source, v_site, v_reference, v_note,
        (v_price ->> 'total_usd_cents')::bigint, p_actor);
    INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind,
        quantity, unit_price_usd_cents, discount_basis_points, amount_usd_cents)
    SELECT v_id, 1, (line ->> 'position')::smallint, line ->> 'kind',
        (line ->> 'quantity')::integer, (line ->> 'unit_price_usd_cents')::bigint,
        (line ->> 'discount_basis_points')::integer, (line ->> 'amount_usd_cents')::bigint
    FROM jsonb_array_elements(v_price -> 'lines') AS line;
    PERFORM app.short_stay_event(v_id, 'BOOKED', p_actor, v_note,
        jsonb_build_object('total_usd_cents', v_price -> 'total_usd_cents',
            'check_in_on', v_check_in, 'check_out_on', v_check_out));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.booked',
        'short_stay_booking', v_id, 'Short-stay booking made', 'short_stays.desk', NULL,
        jsonb_build_object('booking_number', v_number, 'unit_id', v_unit.id,
            'total_usd_cents', v_price -> 'total_usd_cents'), p_correlation);
    RETURN v_id;
END $$;
"""

READS = (
    "app.short_stay_price_read(uuid, uuid, date, date, uuid)",
    "app.short_stay_calendar(uuid, date, integer, uuid)",
    "app.short_stay_bookings_read(uuid, uuid)",
    "app.short_stay_booking_read(uuid, uuid, uuid)",
    "app.make_short_stay_booking(uuid, jsonb, uuid, uuid)",
)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature in READS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    codes = ", ".join(_text(code) for code in USED)
    op.execute(f"UPDATE app.business_rule_names SET used_by_app = true WHERE code IN ({codes})")


def downgrade() -> None:
    raise RuntimeError("Short stays step 2 migration is forward-only")
