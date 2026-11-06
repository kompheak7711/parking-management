# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 5a: booking-site calendars (free iCal links, owner D1).

1. Booking.com, Agoda and Airbnb each give a calendar link per room. The Owner or the Manager
   (short_stays.approve) saves it for a Unit; the billing worker reads it every 15 minutes and
   keeps each booked range as a site hold. A hold blocks the nights for every other booking,
   except a booking from the same site (that is the same guest, typed in by the desk). The
   calendar shows the holds, and a hold that clashes with a booking is shown as a clash.
2. Our own calendar for each link is offered by a long private token (64 hex): only busy dates,
   never a guest's name. Whether the sites can reach it is the owner's hosting choice.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule. Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270606_316"
down_revision: str | None = "20270605_315"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICE = "app.short_stay_price_read(uuid,uuid,date,date,uuid)"
PRICE_REPLACEMENTS = (
    (
        "        'blockers', app.short_stay_blockers(p_unit, p_check_in, p_check_out, v_today));",
        "        'blockers', app.short_stay_blockers(p_unit, p_check_in, p_check_out, v_today),\n"
        "        'site_holds', app.short_stay_site_holds(p_unit, p_check_in, p_check_out, NULL));",
    ),
)

SCHEMA = r"""
-- What a booking site's calendar says is booked. Sync state, not money: a hold that leaves the
-- site's calendar is marked gone, never removed.
CREATE TABLE app.booking_site_holds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    calendar_id uuid NOT NULL REFERENCES app.booking_site_calendars (id) ON DELETE RESTRICT,
    unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
    event_uid text NOT NULL CHECK (length(event_uid) BETWEEN 1 AND 300),
    start_on date NOT NULL,
    end_on date NOT NULL,
    summary text CHECK (length(summary) BETWEEN 1 AND 200),
    first_seen_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    last_seen_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    gone_at timestamptz,
    CONSTRAINT booking_site_holds_nights CHECK (end_on > start_on AND end_on - start_on <= 400),
    CONSTRAINT booking_site_holds_once UNIQUE (calendar_id, event_uid, start_on, end_on)
);
CREATE INDEX booking_site_holds_unit_idx ON app.booking_site_holds (unit_id, start_on)
    WHERE gone_at IS NULL;

CREATE FUNCTION app.protect_booking_site_hold() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP <> 'UPDATE' OR NEW.id <> OLD.id OR NEW.calendar_id <> OLD.calendar_id
        OR NEW.unit_id <> OLD.unit_id OR NEW.event_uid <> OLD.event_uid
        OR NEW.start_on <> OLD.start_on OR NEW.end_on <> OLD.end_on
        OR NEW.first_seen_at <> OLD.first_seen_at
    THEN
        RAISE EXCEPTION 'A booking-site hold is never removed; it is marked gone'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.protect_booking_site_hold() FROM PUBLIC;
CREATE TRIGGER booking_site_holds_protect BEFORE UPDATE OR DELETE ON app.booking_site_holds
    FOR EACH ROW EXECUTE FUNCTION app.protect_booking_site_hold();
CREATE TRIGGER booking_site_holds_truncate BEFORE TRUNCATE ON app.booking_site_holds
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate();

ALTER FUNCTION app.short_stay_calendar(uuid, date, integer, uuid) RENAME TO short_stay_calendar_main;
"""

FUNCTIONS = r"""
-- The site holds over these nights; a booking from the same site is the same guest.
CREATE FUNCTION app.short_stay_site_holds(p_unit uuid, p_check_in date, p_check_out date,
    p_site text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT COALESCE(jsonb_agg(jsonb_build_object('hold_id', hold.id,
            'site_name', calendar.site_name, 'start_on', hold.start_on, 'end_on', hold.end_on,
            'summary', hold.summary) ORDER BY hold.start_on, calendar.site_name), '[]'::jsonb)
    FROM app.booking_site_holds AS hold
    JOIN app.booking_site_calendars AS calendar ON calendar.id = hold.calendar_id
    WHERE hold.unit_id = p_unit AND hold.gone_at IS NULL AND calendar.active
      AND daterange(hold.start_on, hold.end_on, '[)') && daterange(p_check_in, p_check_out, '[)')
      AND lower(calendar.site_name) IS DISTINCT FROM lower(btrim(p_site))
$$;
REVOKE ALL ON FUNCTION app.short_stay_site_holds(uuid, date, date, text) FROM PUBLIC;

-- No booking takes nights a booking site holds (a booking from that site may: same guest).
-- On a change only the added nights are checked.
CREATE FUNCTION app.guard_short_stay_site_holds() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_from date := NEW.check_in_on;
    v_site text;
BEGIN
    IF NEW.status NOT IN ('BOOKED', 'CHECKED_IN') THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.unit_id = OLD.unit_id AND NEW.check_in_on >= OLD.check_in_on
            AND NEW.check_out_on <= OLD.check_out_on THEN
            RETURN NEW;
        END IF;
        IF NEW.unit_id = OLD.unit_id AND NEW.check_in_on >= OLD.check_in_on THEN
            v_from := OLD.check_out_on;
        END IF;
    END IF;
    SELECT calendar.site_name INTO v_site
    FROM app.booking_site_holds AS hold
    JOIN app.booking_site_calendars AS calendar ON calendar.id = hold.calendar_id
    WHERE hold.unit_id = NEW.unit_id AND hold.gone_at IS NULL AND calendar.active
      AND daterange(hold.start_on, hold.end_on, '[)')
          && daterange(v_from, NEW.check_out_on, '[)')
      AND (NEW.source <> 'BOOKING_SITE'
           OR lower(calendar.site_name) IS DISTINCT FROM lower(NEW.site_name))
    ORDER BY hold.start_on LIMIT 1;
    IF v_site IS NOT NULL THEN
        RAISE EXCEPTION 'The nights are booked on %', v_site USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.guard_short_stay_site_holds() FROM PUBLIC;
CREATE TRIGGER short_stay_bookings_site_holds
    BEFORE INSERT OR UPDATE OF unit_id, check_in_on, check_out_on, status
    ON app.short_stay_bookings FOR EACH ROW EXECUTE FUNCTION app.guard_short_stay_site_holds();

-- The calendar with each Unit's site holds; a hold over a booking from another source clashes.
CREATE FUNCTION app.short_stay_calendar(p_property uuid, p_from date, p_days integer,
    p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_main jsonb := app.short_stay_calendar_main(p_property, p_from, p_days, p_actor);
BEGIN
    RETURN v_main || jsonb_build_object('units', COALESCE((
        SELECT jsonb_agg(unit_row || jsonb_build_object('site_holds', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('hold_id', hold.id,
                    'site_name', calendar.site_name, 'start_on', hold.start_on,
                    'end_on', hold.end_on,
                    'clash', EXISTS (SELECT 1 FROM app.short_stay_bookings AS booking
                        WHERE booking.unit_id = hold.unit_id
                          AND booking.status IN ('BOOKED', 'CHECKED_IN')
                          AND daterange(booking.check_in_on, booking.check_out_on, '[)')
                              && daterange(hold.start_on, hold.end_on, '[)')
                          AND (booking.source <> 'BOOKING_SITE' OR lower(booking.site_name)
                               IS DISTINCT FROM lower(calendar.site_name))))
                ORDER BY hold.start_on)
            FROM app.booking_site_holds AS hold
            JOIN app.booking_site_calendars AS calendar ON calendar.id = hold.calendar_id
            WHERE hold.unit_id = (unit_row ->> 'unit_id')::uuid AND hold.gone_at IS NULL
              AND calendar.active
              AND hold.start_on < p_from + p_days AND hold.end_on > p_from
              -- A hold the desk has already typed in as a booking from that site is that booking.
              AND NOT EXISTS (SELECT 1 FROM app.short_stay_bookings AS same
                  WHERE same.unit_id = hold.unit_id AND same.source = 'BOOKING_SITE'
                    AND lower(same.site_name) = lower(calendar.site_name)
                    AND same.status IN ('BOOKED', 'CHECKED_IN', 'CHECKED_OUT')
                    AND daterange(same.check_in_on, same.check_out_on, '[)')
                        && daterange(hold.start_on, hold.end_on, '[)'))), '[]'::jsonb))
            ORDER BY position)
        FROM jsonb_array_elements(v_main -> 'units') WITH ORDINALITY AS unit_list(unit_row, position)),
        '[]'::jsonb));
END $$;

CREATE FUNCTION app.booking_site_calendar_json(p_calendar uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT jsonb_build_object('calendar_id', calendar.id, 'unit_id', calendar.unit_id,
        'unit_number', unit.unit_number, 'site_name', calendar.site_name,
        'import_url', calendar.import_url, 'export_token', calendar.export_token,
        'active', calendar.active, 'last_read_at', calendar.last_read_at,
        'last_read_ok', calendar.last_read_ok, 'last_error', calendar.last_error,
        'version', calendar.version,
        'holds', (SELECT count(*) FROM app.booking_site_holds AS hold
                  WHERE hold.calendar_id = calendar.id AND hold.gone_at IS NULL
                    AND hold.end_on >= CURRENT_DATE))
    FROM app.booking_site_calendars AS calendar
    JOIN app.units AS unit ON unit.id = calendar.unit_id
    WHERE calendar.id = p_calendar
$$;
REVOKE ALL ON FUNCTION app.booking_site_calendar_json(uuid) FROM PUBLIC;

-- The booking-site calendar links of the building (the Owner and the Manager).
CREATE FUNCTION app.booking_site_calendars_read(p_property uuid, p_actor uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    PERFORM app.require_product_right(p_actor, 'short_stays.approve', p_property);
    RETURN COALESCE((
        SELECT jsonb_agg(app.booking_site_calendar_json(calendar.id)
            ORDER BY unit.unit_number, calendar.site_name)
        FROM app.booking_site_calendars AS calendar
        JOIN app.units AS unit ON unit.id = calendar.unit_id
        WHERE calendar.property_id = p_property), '[]'::jsonb);
END $$;

-- Save a calendar link: new (no calendar_id) or changed (calendar_id and version).
CREATE FUNCTION app.save_booking_site_calendar(p_property uuid, p_link jsonb, p_actor uuid,
    p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.approve', p_property);
    v_site text := btrim(p_link ->> 'site_name');
    v_url text := NULLIF(btrim(p_link ->> 'import_url'), '');
    v_active boolean := COALESCE((p_link ->> 'active')::boolean, true);
    v_unit uuid;
    v_old app.booking_site_calendars%ROWTYPE;
    v_id uuid;
BEGIN
    IF v_site IS NULL OR length(v_site) NOT BETWEEN 1 AND 80 THEN
        RAISE EXCEPTION 'Name the booking site' USING ERRCODE = '22023';
    END IF;
    IF v_url IS NOT NULL AND (v_url !~ '^https://[^[:space:]]+$' OR length(v_url) > 2000) THEN
        RAISE EXCEPTION 'The calendar link starts with https://' USING ERRCODE = '22023';
    END IF;
    IF p_link ? 'calendar_id' THEN
        SELECT calendar.* INTO v_old FROM app.booking_site_calendars AS calendar
        WHERE calendar.id = (p_link ->> 'calendar_id')::uuid AND calendar.property_id = p_property
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the calendar link does not exist' USING ERRCODE = '22023';
        END IF;
        IF v_old.version IS DISTINCT FROM (p_link ->> 'version')::integer THEN
            RAISE EXCEPTION 'The calendar link was changed by someone else' USING ERRCODE = '40001';
        END IF;
        UPDATE app.booking_site_calendars SET site_name = v_site, import_url = v_url,
            active = v_active, version = version + 1, updated_at = statement_timestamp(),
            updated_by = p_actor,
            -- A new link is read again from the start.
            last_read_at = CASE WHEN v_url IS DISTINCT FROM v_old.import_url THEN NULL ELSE last_read_at END,
            last_read_ok = CASE WHEN v_url IS DISTINCT FROM v_old.import_url THEN NULL ELSE last_read_ok END,
            last_error = CASE WHEN v_url IS DISTINCT FROM v_old.import_url THEN NULL ELSE last_error END
        WHERE id = v_old.id;
        IF v_url IS DISTINCT FROM v_old.import_url OR NOT v_active THEN
            UPDATE app.booking_site_holds SET gone_at = statement_timestamp()
            WHERE calendar_id = v_old.id AND gone_at IS NULL;
        END IF;
        v_id := v_old.id;
    ELSE
        SELECT unit.id INTO v_unit FROM app.units AS unit
        WHERE unit.id = (p_link ->> 'unit_id')::uuid AND unit.property_id = p_property;
        IF v_unit IS NULL THEN
            RAISE EXCEPTION 'the Unit does not exist' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.booking_site_calendars AS calendar
                   WHERE calendar.unit_id = v_unit AND lower(calendar.site_name) = lower(v_site)) THEN
            RAISE EXCEPTION 'This Unit already has a link for %', v_site USING ERRCODE = '55000';
        END IF;
        INSERT INTO app.booking_site_calendars (property_id, unit_id, site_name, import_url,
            active, created_by, updated_by)
        VALUES (p_property, v_unit, v_site, v_url, v_active, p_actor, p_actor)
        RETURNING id INTO v_id;
    END IF;
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.site_calendar_saved',
        'booking_site_calendar', v_id, 'Booking-site calendar link', 'short_stays.approve',
        CASE WHEN v_old.id IS NULL THEN NULL ELSE jsonb_build_object('site_name', v_old.site_name,
            'import_url', v_old.import_url, 'active', v_old.active) END,
        jsonb_build_object('site_name', v_site, 'import_url', v_url, 'active', v_active),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.booking_site_calendar_json(v_id);
EXCEPTION WHEN invalid_text_representation THEN
    RAISE EXCEPTION 'the calendar link is not readable' USING ERRCODE = '22023';
END $$;

-- The billing worker: the links to read now (not read in the last 15 minutes).
CREATE FUNCTION app.booking_site_calendars_due(p_property uuid, p_actor uuid, p_limit integer)
RETURNS TABLE (calendar_id uuid, import_url text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    PERFORM app.assert_active_financial_actor(p_actor, p_property);
    RETURN QUERY
    SELECT calendar.id, calendar.import_url FROM app.booking_site_calendars AS calendar
    WHERE calendar.property_id = p_property AND calendar.active AND calendar.import_url IS NOT NULL
      AND (calendar.last_read_at IS NULL
           OR calendar.last_read_at < statement_timestamp() - interval '15 minutes')
    ORDER BY calendar.last_read_at NULLS FIRST, calendar.id
    LIMIT LEAST(GREATEST(p_limit, 1), 100);
END $$;

-- The events of a read that matter: from yesterday to two years ahead, at most 400 nights each.
CREATE FUNCTION app.booking_site_events(p_events jsonb, p_today date)
RETURNS TABLE (event_uid text, start_on date, end_on date, summary text)
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT DISTINCT ON (uid, first_day, last_day) uid, first_day, last_day, label
    FROM (SELECT left(event ->> 'uid', 300) AS uid, (event ->> 'start_on')::date AS first_day,
                 (event ->> 'end_on')::date AS last_day,
                 NULLIF(left(btrim(event ->> 'summary'), 200), '') AS label
          FROM jsonb_array_elements(p_events) AS event) AS parsed
    WHERE length(uid) > 0 AND last_day > first_day AND last_day - first_day <= 400
      AND last_day > p_today - 1 AND first_day < p_today + 730
    ORDER BY uid, first_day, last_day, label
$$;
REVOKE ALL ON FUNCTION app.booking_site_events(jsonb, date) FROM PUBLIC;

-- The billing worker: what one read found. The events are [{uid, start_on, end_on, summary}];
-- a failed read keeps the holds as they were.
CREATE FUNCTION app.record_booking_site_calendar_read(p_property uuid, p_calendar uuid,
    p_actor uuid, p_ok boolean, p_error text, p_events jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_calendar app.booking_site_calendars%ROWTYPE;
    v_today date;
    v_now timestamptz := statement_timestamp();
    v_seen integer := 0;
BEGIN
    PERFORM app.assert_active_financial_actor(p_actor, p_property);
    SELECT calendar.* INTO v_calendar FROM app.booking_site_calendars AS calendar
    WHERE calendar.id = p_calendar AND calendar.property_id = p_property FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the calendar link does not exist' USING ERRCODE = '22023';
    END IF;
    SELECT timezone(property.timezone_name, v_now)::date INTO v_today
    FROM app.properties AS property WHERE property.id = p_property;
    IF p_ok THEN
        IF jsonb_typeof(p_events) <> 'array' OR jsonb_array_length(p_events) > 5000 THEN
            RAISE EXCEPTION 'The calendar events are a list of up to 5000' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.booking_site_holds (calendar_id, unit_id, event_uid, start_on, end_on,
            summary, first_seen_at, last_seen_at)
        SELECT p_calendar, v_calendar.unit_id, site_event.event_uid, site_event.start_on, site_event.end_on,
            site_event.summary, v_now, v_now
        FROM app.booking_site_events(p_events, v_today) AS site_event
        ON CONFLICT (calendar_id, event_uid, start_on, end_on)
        DO UPDATE SET last_seen_at = v_now, gone_at = NULL, summary = EXCLUDED.summary;
        GET DIAGNOSTICS v_seen = ROW_COUNT;
        UPDATE app.booking_site_holds AS hold SET gone_at = v_now
        WHERE hold.calendar_id = p_calendar AND hold.gone_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM app.booking_site_events(p_events, v_today) AS site_event
              WHERE site_event.event_uid = hold.event_uid AND site_event.start_on = hold.start_on
                AND site_event.end_on = hold.end_on);
    END IF;
    UPDATE app.booking_site_calendars SET last_read_at = v_now, last_read_ok = p_ok,
        last_error = CASE WHEN p_ok THEN NULL
            ELSE COALESCE(NULLIF(left(btrim(p_error), 500), ''), 'The calendar could not be read') END,
        version = version + 1, updated_at = v_now, updated_by = p_actor
    WHERE id = p_calendar;
    RETURN v_seen;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN
    RAISE EXCEPTION 'A calendar event has an unreadable date' USING ERRCODE = '22023';
END $$;

-- Our calendar for a booking site, by its private token: busy nights only, never a name.
CREATE FUNCTION app.booking_site_calendar_feed(p_token text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_calendar app.booking_site_calendars%ROWTYPE;
    v_unit app.units%ROWTYPE;
    v_today date;
BEGIN
    IF p_token IS NULL OR p_token !~ '^[0-9a-f]{64}$' THEN
        RETURN NULL;
    END IF;
    SELECT calendar.* INTO v_calendar FROM app.booking_site_calendars AS calendar
    WHERE calendar.export_token = p_token AND calendar.active;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = v_calendar.unit_id;
    SELECT timezone(property.timezone_name, statement_timestamp())::date INTO v_today
    FROM app.properties AS property WHERE property.id = v_calendar.property_id;
    RETURN jsonb_build_object('unit_number', v_unit.unit_number, 'site_name', v_calendar.site_name,
        'busy', COALESCE((SELECT jsonb_agg(busy ORDER BY busy ->> 'start_on', busy ->> 'uid') FROM (
            -- Our bookings (a booking from this same site is already on its calendar).
            SELECT jsonb_build_object('uid', 'st-' || booking.id::text,
                'start_on', booking.check_in_on, 'end_on', booking.check_out_on) AS busy
            FROM app.short_stay_bookings AS booking
            WHERE booking.unit_id = v_unit.id AND booking.status IN ('BOOKED', 'CHECKED_IN')
              AND booking.check_out_on > v_today
              AND (booking.source <> 'BOOKING_SITE'
                   OR lower(booking.site_name) IS DISTINCT FROM lower(v_calendar.site_name))
            UNION ALL
            -- Monthly Leases: the nights from the start to the last day.
            SELECT jsonb_build_object('uid', 'lease-' || lease.id::text,
                'start_on', GREATEST(lease.start_date, v_today),
                'end_on', (CASE WHEN lease.status = 'TERMINATED'
                    THEN lease.actual_termination_date ELSE lease.end_date END) + 1)
            FROM app.leases AS lease
            WHERE lease.unit_id = v_unit.id AND lease.status IN ('SIGNED', 'TERMINATED')
              AND (CASE WHEN lease.status = 'TERMINATED'
                  THEN lease.actual_termination_date ELSE lease.end_date END) >= v_today
            UNION ALL
            -- The other booking sites' holds.
            SELECT jsonb_build_object('uid', 'hold-' || hold.id::text,
                'start_on', hold.start_on, 'end_on', hold.end_on)
            FROM app.booking_site_holds AS hold
            JOIN app.booking_site_calendars AS other ON other.id = hold.calendar_id
            WHERE hold.unit_id = v_unit.id AND hold.gone_at IS NULL AND other.active
              AND other.id <> v_calendar.id AND hold.end_on > v_today
            UNION ALL
            -- A Reservation, or a Unit not open for rent: closed for the next year.
            SELECT jsonb_build_object('uid', 'closed-' || v_unit.id::text,
                'start_on', v_today, 'end_on', v_today + 365)
            WHERE NOT v_unit.for_rent
               OR v_unit.status IN ('UNDER_MAINTENANCE', 'OUT_OF_SERVICE')
               OR EXISTS (SELECT 1 FROM app.reservations AS reservation
                          WHERE reservation.unit_id = v_unit.id AND reservation.status = 'ACTIVE')
        ) AS site_event), '[]'::jsonb));
END $$;
"""

READS = (
    "app.booking_site_calendars_read(uuid, uuid)",
    "app.save_booking_site_calendar(uuid, jsonb, uuid, uuid)",
    "app.booking_site_calendar_feed(text)",
    "app.short_stay_calendar(uuid, date, integer, uuid)",
)
WORKER = (
    "app.booking_site_calendars_due(uuid, uuid, integer)",
    "app.record_booking_site_calendar_read(uuid, uuid, uuid, boolean, text, jsonb)",
)


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
    _patch(PRICE, PRICE_REPLACEMENTS)
    for signature in READS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    for signature in WORKER:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Short stays step 5a migration is forward-only")
