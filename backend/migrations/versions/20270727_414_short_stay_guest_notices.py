# ruff: noqa: E501
"""Short stays: notices for guests by the Tenant bot (DL-238).

Owner (14 Nov 2026): "Let's start building notice for short stay", with the four notices Claude
proposed on the same day:

1. Check-out reminder: by itself at 18:00 the evening before check-out. It names the check-out
   time and the late check-out of the Business rules (until 18:00, $5, free for a stay of 7 nights
   or more), or the later time when late check-out is already added to the stay.
2. Late check-out notice: by itself 30 minutes after the check-out time (or after the late
   check-out time when it is added) while the guest is still checked in. No money is added; the
   front desk decides.
3. House-rule warning: staff (``short_stays.desk``) write it with the reason. Warning 1, then the
   final warning 2. After the final warning a Manager may end the stay early, with the rule for
   early check-out (unused nights stay paid). Nothing here ends a stay or adds a charge.
4. Unpaid charge notice: by itself from 09:00 the day after staff add a charge to the stay (a fee,
   an extension or a damage charge) that is still not fully paid.

Each notice is sent to the Telegram links of the booking (the check-in QR, DL-214), in the language
each guest chose. A guest with no link gets no message: the Notices page lists the notice under
"Tell the guest in person" until staff mark it told. Paper is not used for short stays.

What changes:

- ``app.short_stay_guest_notices``: each notice once (one reminder and one late notice per
  check-out day, two warnings per stay, one notice per charge), with the message fields as they
  were that day. ``app.short_stay_guest_notice_deliveries`` keeps the Telegram messages, and
  ``app.short_stay_guest_notice_told`` the notices staff gave in person. Never changed.
- ``app.short_stay_notices_run`` (``telegram.operate``, run by the Telegram pull job) records the
  automatic notices that are due and sends what was not sent yet.
- ``app.give_short_stay_warning`` and ``app.short_stay_notice_told`` (``short_stays.desk``), and
  ``app.short_stay_notices_page`` (``short_stays.read``) for the Notices page.

Times are Asia/Phnom_Penh (the Property's time zone). Technical choices by Claude under the
owner's 2026-10-23 22:30 rule; the four notices and their times are the owner's.

Forward-only.

Revision ID: 20270727_414
Revises: 20270728_405
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270727_414"
down_revision: str | None = "20270728_405"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Minutes after midnight. A notice is never sent at night: a run after the window waits for the
# next day (the reminder and the late notice of that day are then not sent).
REMINDER_FROM, REMINDER_UNTIL = 18 * 60, 22 * 60
LATE_AFTER_MINUTES, LATE_UNTIL = 30, 22 * 60
UNPAID_FROM, UNPAID_UNTIL = 9 * 60, 21 * 60
# A notice is sent to links made up to a day after it, and the page shows 90 days.
SEND_DAYS, PAGE_DAYS = 1, 90
AUTOMATIC = "'CHECK_OUT_REMINDER','LATE_CHECK_OUT','UNPAID_CHARGE'"

TABLES = r"""
CREATE TABLE app.short_stay_guest_notices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
    booking_id uuid NOT NULL REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('CHECK_OUT_REMINDER', 'LATE_CHECK_OUT',
        'HOUSE_RULE_WARNING', 'UNPAID_CHARGE')),
    notice_on date NOT NULL,
    warning_number smallint CHECK (warning_number IN (1, 2)),
    reason text CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
    invoice_id uuid REFERENCES app.invoices (id) ON DELETE RESTRICT,
    -- The Tenant bot text and its fields, as they were when the notice was made.
    text_code text NOT NULL CHECK (text_code ~ '^tenant\.ss_[a-z0-9_]{1,40}$'),
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT short_stay_guest_notices_shape CHECK (
        (kind = 'HOUSE_RULE_WARNING') = (warning_number IS NOT NULL AND reason IS NOT NULL)
        AND (kind = 'UNPAID_CHARGE') = (invoice_id IS NOT NULL))
);
CREATE UNIQUE INDEX short_stay_guest_notices_day_once
    ON app.short_stay_guest_notices (booking_id, kind, notice_on)
    WHERE kind IN ('CHECK_OUT_REMINDER', 'LATE_CHECK_OUT');
CREATE UNIQUE INDEX short_stay_guest_notices_warning_once
    ON app.short_stay_guest_notices (booking_id, warning_number) WHERE kind = 'HOUSE_RULE_WARNING';
CREATE UNIQUE INDEX short_stay_guest_notices_charge_once
    ON app.short_stay_guest_notices (invoice_id) WHERE kind = 'UNPAID_CHARGE';
CREATE INDEX short_stay_guest_notices_property_idx
    ON app.short_stay_guest_notices (property_id, created_at DESC);

CREATE TABLE app.short_stay_guest_notice_deliveries (
    notice_id uuid NOT NULL REFERENCES app.short_stay_guest_notices (id) ON DELETE RESTRICT,
    telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
    outbox_id uuid NOT NULL UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (notice_id, telegram_user_id)
);

CREATE TABLE app.short_stay_guest_notice_told (
    notice_id uuid PRIMARY KEY REFERENCES app.short_stay_guest_notices (id) ON DELETE RESTRICT,
    told_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    told_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
);

CREATE TRIGGER short_stay_guest_notices_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_guest_notices FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_guest_notices_truncate BEFORE TRUNCATE ON app.short_stay_guest_notices
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate();
CREATE TRIGGER short_stay_guest_notice_deliveries_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_guest_notice_deliveries FOR EACH ROW
    EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_guest_notice_deliveries_truncate BEFORE TRUNCATE
    ON app.short_stay_guest_notice_deliveries FOR EACH STATEMENT
    EXECUTE FUNCTION app.reject_short_stay_truncate();
CREATE TRIGGER short_stay_guest_notice_told_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_guest_notice_told FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_guest_notice_told_truncate BEFORE TRUNCATE
    ON app.short_stay_guest_notice_told FOR EACH STATEMENT
    EXECUTE FUNCTION app.reject_short_stay_truncate();
REVOKE ALL ON app.short_stay_guest_notices, app.short_stay_guest_notice_deliveries,
    app.short_stay_guest_notice_told FROM PUBLIC;
"""

FUNCTIONS = rf"""
-- A time of day of the Business rules (minutes after midnight) as the guest reads it.
CREATE FUNCTION app.short_stay_notice_time(p_minutes bigint) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT to_char(time '00:00' + make_interval(mins => p_minutes::integer), 'HH24:MI')
$$;

-- The time a guest must leave: the check-out time, or the late check-out time when late
-- check-out is part of the stay's price now.
CREATE FUNCTION app.short_stay_notice_leave_minutes(p_booking uuid) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN EXISTS (
            SELECT 1 FROM app.short_stay_price_lines AS line
            WHERE line.booking_id = booking.id AND line.price_version = booking.price_version
              AND line.kind = 'LATE_CHECK_OUT')
        THEN app.short_stay_rule('SS_LATE_CHECK_OUT_UNTIL', booking.check_in_on)
        ELSE app.short_stay_rule('SS_CHECK_OUT_TIME', booking.check_in_on) END
    FROM app.short_stay_bookings AS booking WHERE booking.id = p_booking
$$;

-- The check-out reminder's text and fields.
CREATE FUNCTION app.short_stay_reminder(p_booking uuid, OUT o_text text, OUT o_details jsonb)
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
DECLARE
    v_booking app.short_stay_bookings;
    v_unit text;
    v_late boolean;
BEGIN
    SELECT booking.* INTO v_booking FROM app.short_stay_bookings AS booking
    WHERE booking.id = p_booking;
    SELECT unit.unit_number INTO v_unit FROM app.units AS unit WHERE unit.id = v_booking.unit_id;
    v_late := app.short_stay_notice_leave_minutes(p_booking)
        <> app.short_stay_rule('SS_CHECK_OUT_TIME', v_booking.check_in_on);
    o_text := CASE
        WHEN v_late THEN 'tenant.ss_check_out_late'
        WHEN v_booking.nights >= app.short_stay_rule('SS_EARLY_LATE_FREE_NIGHTS',
            v_booking.check_in_on) THEN 'tenant.ss_check_out_free'
        ELSE 'tenant.ss_check_out' END;
    o_details := jsonb_build_object(
        'unit', v_unit,
        'date', to_char(v_booking.check_out_on, 'DD/MM/YYYY'),
        'time', app.short_stay_notice_time(app.short_stay_rule('SS_CHECK_OUT_TIME',
            v_booking.check_in_on)),
        'until', app.short_stay_notice_time(app.short_stay_rule('SS_LATE_CHECK_OUT_UNTIL',
            v_booking.check_in_on)),
        'fee', app.telegram_usd(app.short_stay_rule('SS_EARLY_LATE_FEE', v_booking.check_in_on)));
END $$;

-- The money still to pay on an Invoice.
CREATE FUNCTION app.short_stay_notice_outstanding(p_invoice uuid) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)), 0)::bigint
    FROM app.invoice_lines AS line WHERE line.invoice_id = p_invoice
$$;

-- Record the automatic notices that are due at p_now. Answers how many were recorded.
CREATE FUNCTION app.short_stay_notices_record(p_property uuid, p_now timestamptz, p_actor uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_local timestamp;
    v_today date;
    v_minutes integer;
    v_row record;
    v_text text;
    v_details jsonb;
    v_count integer := 0;
    v_added integer;
BEGIN
    SELECT timezone(property.timezone_name, p_now) INTO v_local
    FROM app.properties AS property WHERE property.id = p_property;
    IF v_local IS NULL THEN
        RAISE EXCEPTION 'the property does not exist' USING ERRCODE = '22023';
    END IF;
    v_today := v_local::date;
    v_minutes := extract(hour FROM v_local)::integer * 60 + extract(minute FROM v_local)::integer;

    -- 1. The check-out reminder, the evening before check-out.
    IF v_minutes >= {REMINDER_FROM} AND v_minutes < {REMINDER_UNTIL} THEN
        FOR v_row IN
            SELECT booking.id FROM app.short_stay_bookings AS booking
            WHERE booking.property_id = p_property AND booking.status = 'CHECKED_IN'
              AND booking.check_out_on = v_today + 1
              AND NOT EXISTS (SELECT 1 FROM app.short_stay_guest_notices AS notice
                  WHERE notice.booking_id = booking.id AND notice.kind = 'CHECK_OUT_REMINDER'
                    AND notice.notice_on = v_today)
            ORDER BY booking.id
        LOOP
            SELECT made.o_text, made.o_details INTO v_text, v_details
            FROM app.short_stay_reminder(v_row.id) AS made;
            INSERT INTO app.short_stay_guest_notices (property_id, booking_id, kind, notice_on,
                text_code, details, created_at, created_by)
            VALUES (p_property, v_row.id, 'CHECK_OUT_REMINDER', v_today, v_text, v_details,
                p_now, p_actor)
            ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS v_added = ROW_COUNT;
            v_count := v_count + v_added;
        END LOOP;
    END IF;

    -- 2. The late check-out notice: still checked in {LATE_AFTER_MINUTES} minutes after the time
    -- to leave on the check-out day.
    IF v_minutes < {LATE_UNTIL} THEN
        FOR v_row IN
            SELECT booking.id, unit.unit_number,
                app.short_stay_notice_leave_minutes(booking.id) AS leave_at
            FROM app.short_stay_bookings AS booking
            JOIN app.units AS unit ON unit.id = booking.unit_id
            WHERE booking.property_id = p_property AND booking.status = 'CHECKED_IN'
              AND booking.check_out_on = v_today
              AND NOT EXISTS (SELECT 1 FROM app.short_stay_guest_notices AS notice
                  WHERE notice.booking_id = booking.id AND notice.kind = 'LATE_CHECK_OUT'
                    AND notice.notice_on = v_today)
            ORDER BY booking.id
        LOOP
            CONTINUE WHEN v_minutes < v_row.leave_at + {LATE_AFTER_MINUTES};
            INSERT INTO app.short_stay_guest_notices (property_id, booking_id, kind, notice_on,
                text_code, details, created_at, created_by)
            VALUES (p_property, v_row.id, 'LATE_CHECK_OUT', v_today, 'tenant.ss_late',
                jsonb_build_object('unit', v_row.unit_number,
                    'time', app.short_stay_notice_time(v_row.leave_at)),
                p_now, p_actor)
            ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS v_added = ROW_COUNT;
            v_count := v_count + v_added;
        END LOOP;
    END IF;

    -- 3. A charge added to the stay (a fee, an extension or a damage charge) and still not fully
    -- paid on a later day.
    IF v_minutes >= {UNPAID_FROM} AND v_minutes < {UNPAID_UNTIL} THEN
        FOR v_row IN
            SELECT booking.id, unit.unit_number, invoice.id AS invoice_id, invoice.invoice_number
            FROM (SELECT extra.invoice_id, extra.booking_id FROM app.short_stay_extra_invoices AS extra
                  UNION
                  SELECT damage.invoice_id, damage.booking_id FROM app.short_stay_damages AS damage
                  WHERE damage.invoice_id IS NOT NULL) AS charge
            JOIN app.short_stay_bookings AS booking ON booking.id = charge.booking_id
            JOIN app.units AS unit ON unit.id = booking.unit_id
            JOIN app.invoices AS invoice ON invoice.id = charge.invoice_id
            JOIN app.properties AS property ON property.id = booking.property_id
            WHERE booking.property_id = p_property AND booking.status = 'CHECKED_IN'
              AND invoice.status IN ('UNPAID', 'PARTIALLY_PAID') AND invoice.issued_at IS NOT NULL
              AND timezone(property.timezone_name, invoice.issued_at)::date < v_today
              AND NOT EXISTS (SELECT 1 FROM app.short_stay_guest_notices AS notice
                  WHERE notice.kind = 'UNPAID_CHARGE' AND notice.invoice_id = invoice.id)
            ORDER BY invoice.issued_at, invoice.id
        LOOP
            INSERT INTO app.short_stay_guest_notices (property_id, booking_id, kind, notice_on,
                invoice_id, text_code, details, created_at, created_by)
            VALUES (p_property, v_row.id, 'UNPAID_CHARGE', v_today, v_row.invoice_id,
                'tenant.ss_unpaid',
                jsonb_build_object('unit', v_row.unit_number, 'invoice', v_row.invoice_number,
                    'amount', app.telegram_usd(app.short_stay_notice_outstanding(v_row.invoice_id))),
                p_now, p_actor)
            ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS v_added = ROW_COUNT;
            v_count := v_count + v_added;
        END LOOP;
    END IF;
    RETURN v_count;
END $$;

-- Send one notice to each live Telegram link of its booking that has not had it, in the language
-- the guest chose. A link made more than {SEND_DAYS} day after the notice does not get it.
CREATE FUNCTION app.short_stay_notice_send(p_notice uuid, p_actor uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_notice app.short_stay_guest_notices;
    v_person record;
    v_outbox uuid;
    v_count integer := 0;
BEGIN
    SELECT notice.* INTO v_notice FROM app.short_stay_guest_notices AS notice
    WHERE notice.id = p_notice;
    FOR v_person IN
        SELECT DISTINCT ON (link.telegram_user_id) link.telegram_user_id,
            COALESCE((SELECT choice.language FROM app.telegram_language_choices AS choice
                      WHERE choice.bot_code = 'TENANT'
                        AND choice.telegram_user_id = link.telegram_user_id
                      ORDER BY choice.chosen_at DESC LIMIT 1), 'km') AS language
        FROM app.tenant_telegram_links AS link
        WHERE link.property_id = v_notice.property_id AND link.booking_id = v_notice.booking_id
          AND link.linked_at - interval '{SEND_DAYS} day' <= v_notice.created_at
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND app.tenant_link_stay_live(NULL, link.booking_id, app.gl_today(link.property_id))
          AND NOT EXISTS (SELECT 1 FROM app.short_stay_guest_notice_deliveries AS sent
                          WHERE sent.notice_id = p_notice
                            AND sent.telegram_user_id = link.telegram_user_id)
        ORDER BY link.telegram_user_id, link.linked_at DESC
    LOOP
        INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
            details, keyboard, created_by)
        VALUES (v_notice.property_id, 'TENANT', v_person.telegram_user_id, v_notice.text_code,
            v_person.language, v_notice.details, NULL, p_actor)
        RETURNING id INTO v_outbox;
        INSERT INTO app.short_stay_guest_notice_deliveries (notice_id, telegram_user_id, outbox_id)
        VALUES (p_notice, v_person.telegram_user_id, v_outbox);
        v_count := v_count + 1;
    END LOOP;
    RETURN v_count;
END $$;

-- Run by the Telegram pull job, about once a minute: record what is due, then send what was
-- recorded in the last {SEND_DAYS} day and not sent yet. Answers how many messages were queued.
CREATE FUNCTION app.short_stay_notices_run(p_property uuid, p_actor uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_notice uuid;
    v_count integer := 0;
BEGIN
    PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
    PERFORM app.short_stay_notices_record(p_property, statement_timestamp(), p_actor);
    FOR v_notice IN
        SELECT notice.id FROM app.short_stay_guest_notices AS notice
        WHERE notice.property_id = p_property
          AND notice.created_at >= statement_timestamp() - interval '{SEND_DAYS} day'
        ORDER BY notice.created_at, notice.id
    LOOP
        v_count := v_count + app.short_stay_notice_send(v_notice, p_actor);
    END LOOP;
    RETURN v_count;
END $$;

-- Staff give a guest a house-rule warning with the reason: warning 1, then the final warning 2.
-- It goes to the guest's Telegram at once.
CREATE FUNCTION app.give_short_stay_warning(p_property uuid, p_booking uuid, p_warning jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_booking app.short_stay_bookings;
    v_reason text;
    v_number smallint;
    v_id uuid;
    v_sent integer;
BEGIN
    IF p_warning IS NULL OR jsonb_typeof(p_warning) <> 'object'
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_warning) AS key WHERE key <> 'reason')
       OR jsonb_typeof(p_warning -> 'reason') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'The warning is invalid' USING ERRCODE = '22023';
    END IF;
    v_reason := btrim(p_warning ->> 'reason');
    IF length(v_reason) NOT BETWEEN 1 AND 500 THEN
        RAISE EXCEPTION 'Write why, in 1 to 500 characters' USING ERRCODE = '22023';
    END IF;
    SELECT booking.* INTO v_booking FROM app.short_stay_bookings AS booking
    WHERE booking.id = p_booking AND booking.property_id = p_property FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the booking does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_booking.status <> 'CHECKED_IN' THEN
        RAISE EXCEPTION 'Only a guest who is checked in gets a warning' USING ERRCODE = '55000';
    END IF;
    SELECT count(*) + 1 INTO v_number FROM app.short_stay_guest_notices AS notice
    WHERE notice.booking_id = p_booking AND notice.kind = 'HOUSE_RULE_WARNING';
    IF v_number > 2 THEN
        RAISE EXCEPTION 'This guest already has the final warning' USING ERRCODE = '55000';
    END IF;
    INSERT INTO app.short_stay_guest_notices (property_id, booking_id, kind, notice_on,
        warning_number, reason, text_code, details, created_by)
    VALUES (p_property, p_booking, 'HOUSE_RULE_WARNING', v_today, v_number, v_reason,
        'tenant.ss_warning_' || v_number,
        jsonb_build_object('unit', (SELECT unit.unit_number FROM app.units AS unit
                WHERE unit.id = v_booking.unit_id),
            'date', to_char(v_today, 'DD/MM/YYYY'), 'text', v_reason),
        p_actor)
    RETURNING id INTO v_id;
    PERFORM app.short_stay_event(p_booking, 'HOUSE_RULE_WARNING', p_actor, v_reason,
        jsonb_build_object('warning_number', v_number));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.guest_warned',
        'short_stay_booking', p_booking,
        CASE WHEN v_number = 1 THEN 'House-rule warning 1' ELSE 'Final house-rule warning' END,
        'short_stays.desk', NULL,
        jsonb_build_object('notice_id', v_id, 'warning_number', v_number, 'reason', v_reason),
        p_correlation);
    v_sent := app.short_stay_notice_send(v_id, p_actor);
    RETURN jsonb_build_object('notice_id', v_id, 'warning_number', v_number,
        'telegram_messages', v_sent);
END $$;

-- Staff told a guest with no Telegram in person.
CREATE FUNCTION app.short_stay_notice_told(p_property uuid, p_notice uuid, p_actor uuid,
    p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_notice app.short_stay_guest_notices;
BEGIN
    SELECT notice.* INTO v_notice FROM app.short_stay_guest_notices AS notice
    WHERE notice.id = p_notice AND notice.property_id = p_property;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the notice does not exist' USING ERRCODE = '22023';
    END IF;
    INSERT INTO app.short_stay_guest_notice_told (notice_id, told_by) VALUES (p_notice, p_actor)
    ON CONFLICT (notice_id) DO NOTHING;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This notice is already marked as told' USING ERRCODE = '55000';
    END IF;
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.notice_told',
        'short_stay_guest_notice', p_notice, 'Guest told in person', 'short_stays.desk', NULL,
        jsonb_build_object('kind', v_notice.kind, 'booking_id', v_notice.booking_id),
        p_correlation);
    RETURN app.short_stay_notices_page(p_property, p_actor);
END $$;

-- The Notices page for short stays: the notices of the last {PAGE_DAYS} days, newest first, with
-- how each reached the guest, and the checked-in guests who may get a warning.
CREATE FUNCTION app.short_stay_notices_page(p_property uuid, p_actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.read', p_property);
    v_notices jsonb;
    v_stays jsonb;
BEGIN
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
            'notice_id', notice.id, 'kind', notice.kind, 'notice_on', notice.notice_on,
            'created_at', notice.created_at, 'warning_number', notice.warning_number,
            'reason', notice.reason, 'invoice_number', invoice.invoice_number,
            'amount', notice.details ->> 'amount', 'time', notice.details ->> 'time',
            'booking_id', booking.id, 'booking_number', booking.booking_number,
            'booking_status', booking.status, 'check_out_on', booking.check_out_on,
            'unit_number', unit.unit_number, 'guest_name', customer.legal_name,
            'automatic', notice.kind IN ({AUTOMATIC}),
            'given_by_name', CASE WHEN notice.kind = 'HOUSE_RULE_WARNING'
                THEN given.display_name END,
            'telegram', COALESCE((
                SELECT CASE WHEN bool_or(final.outcome = 'SENT') THEN 'SENT'
                            WHEN bool_and(final.outcome = 'GAVE_UP') THEN 'NOT_DELIVERED'
                            ELSE 'WAITING' END
                FROM app.short_stay_guest_notice_deliveries AS sent
                LEFT JOIN app.telegram_outbox_attempts AS final
                  ON final.outbox_id = sent.outbox_id AND final.outcome IN ('SENT', 'GAVE_UP')
                WHERE sent.notice_id = notice.id HAVING count(*) > 0), 'NO_TELEGRAM'),
            'told_at', told.told_at, 'told_by_name', teller.display_name)
            ORDER BY notice.created_at DESC, notice.id), '[]'::jsonb)
    INTO v_notices
    FROM app.short_stay_guest_notices AS notice
    JOIN app.short_stay_bookings AS booking ON booking.id = notice.booking_id
    JOIN app.units AS unit ON unit.id = booking.unit_id
    JOIN app.customers AS customer ON customer.id = booking.customer_id
    LEFT JOIN app.invoices AS invoice ON invoice.id = notice.invoice_id
    LEFT JOIN app.user_accounts AS given ON given.actor_id = notice.created_by
    LEFT JOIN app.short_stay_guest_notice_told AS told ON told.notice_id = notice.id
    LEFT JOIN app.user_accounts AS teller ON teller.actor_id = told.told_by
    WHERE notice.property_id = p_property AND notice.notice_on > v_today - {PAGE_DAYS};

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
            'booking_id', booking.id, 'booking_number', booking.booking_number,
            'unit_number', unit.unit_number, 'guest_name', customer.legal_name,
            'check_out_on', booking.check_out_on,
            'warnings', (SELECT count(*) FROM app.short_stay_guest_notices AS notice
                WHERE notice.booking_id = booking.id AND notice.kind = 'HOUSE_RULE_WARNING'),
            'telegram', EXISTS (SELECT 1 FROM app.tenant_telegram_links AS link
                WHERE link.booking_id = booking.id
                  AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                                  WHERE ending.link_id = link.id)))
            ORDER BY unit.unit_number, booking.id), '[]'::jsonb)
    INTO v_stays
    FROM app.short_stay_bookings AS booking
    JOIN app.units AS unit ON unit.id = booking.unit_id
    JOIN app.customers AS customer ON customer.id = booking.customer_id
    WHERE booking.property_id = p_property AND booking.status = 'CHECKED_IN';

    RETURN jsonb_build_object('notices', v_notices, 'stays', v_stays,
        'rules', jsonb_build_object('days', {PAGE_DAYS},
            'reminder_at', app.short_stay_notice_time({REMINDER_FROM}),
            'late_after_minutes', {LATE_AFTER_MINUTES},
            'unpaid_at', app.short_stay_notice_time({UNPAID_FROM})));
END $$;
"""

INTERNAL = (
    "app.short_stay_notice_time(bigint)",
    "app.short_stay_notice_leave_minutes(uuid)",
    "app.short_stay_reminder(uuid)",
    "app.short_stay_notice_outstanding(uuid)",
    "app.short_stay_notices_record(uuid,timestamptz,uuid)",
    "app.short_stay_notice_send(uuid,uuid)",
)
RUNTIME = (
    "app.short_stay_notices_run(uuid,uuid)",
    "app.give_short_stay_warning(uuid,uuid,jsonb,uuid,uuid)",
    "app.short_stay_notice_told(uuid,uuid,uuid,uuid)",
    "app.short_stay_notices_page(uuid,uuid)",
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in INTERNAL + RUNTIME:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
