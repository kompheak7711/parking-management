# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 4a: daily cleaning, early and late fees, extend a stay.

The owner's rules (PRD 03/11/2026 and 04/11/2026):

1. Daily and weekly guests get a daily clean (owner 04/11). At check-in a Daily clean task is made
   for every morning the guest stays (from the day after check-in to the day before check-out);
   the check-out makes the room check (step 3). A housekeeper marks a task done, or skipped with a
   reason ("do not disturb"). A guest who checks out early leaves the later cleans skipped.
2. Early check-in or late check-out (until SS_LATE_CHECK_OUT_UNTIL, 18:00) costs SS_EARLY_LATE_FEE
   ($5), free for a stay of SS_EARLY_LATE_FREE_NIGHTS (7) nights or more. Each is added once. A fee
   is a new price line (a new price version); once the stay is billed or paid on the booking site,
   the fee is its own Invoice.
3. A stay is extended to a later check-out day while it is Booked or Checked in, if the Unit is
   free on the added nights. The whole stay is priced again with the rules of its check-in day
   (so 6 nights extended to 7 become one week), fees are kept, and once billed the difference is
   its own Invoice. A guest who is in gets daily cleans for the added days.
4. Full payment before check-in now counts every Invoice of the stay: the payment state is not
   Paid while a fee or extension Invoice is unpaid.

Cancel, credit and change to a Lease are step 4b. Technical choices by Claude under the owner's
2026-10-23 22:30 rule. Forward-only and additive: the old read functions are renamed and wrapped.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270603_313"
down_revision: str | None = "20270602_312"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USED = (
    "SS_EARLY_LATE_FEE",
    "SS_EARLY_LATE_FREE_NIGHTS",
    "SS_LATE_CHECK_OUT_UNTIL",
    "SS_CHECK_IN_TIME",
    "SS_CHECK_OUT_TIME",
)

SCHEMA = r"""
-- An Invoice for a fee or an extension, made after the stay was billed. Never changed.
CREATE TABLE app.short_stay_extra_invoices (
    invoice_id uuid PRIMARY KEY REFERENCES app.invoices (id) ON DELETE RESTRICT,
    booking_id uuid NOT NULL REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('EXTEND', 'EARLY_CHECK_IN', 'LATE_CHECK_OUT')),
    price_version integer NOT NULL CHECK (price_version > 1),
    amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT short_stay_extra_invoices_once UNIQUE (booking_id, price_version)
);
CREATE INDEX short_stay_extra_invoices_booking_idx ON app.short_stay_extra_invoices (booking_id);
CREATE TRIGGER short_stay_extra_invoices_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_extra_invoices FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_extra_invoices_truncate BEFORE TRUNCATE ON app.short_stay_extra_invoices
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate();

-- Daily cleans at check-in; an early check-out leaves the later ones skipped.
CREATE FUNCTION app.short_stay_daily_cleaning() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v_out date;
BEGIN
    IF OLD.status = 'BOOKED' AND NEW.status = 'CHECKED_IN' THEN
        INSERT INTO app.housekeeping_tasks (property_id, unit_id, booking_id, task_on, kind,
            created_by)
        SELECT NEW.property_id, NEW.unit_id, NEW.id, day::date, 'DAILY_CLEAN', NEW.checked_in_by
        FROM generate_series(NEW.check_in_on + 1, NEW.check_out_on - 1, interval '1 day') AS day
        ON CONFLICT (booking_id, task_on, kind) DO NOTHING;
    ELSIF OLD.status = 'CHECKED_IN' AND NEW.status = 'CHECKED_OUT' THEN
        SELECT timezone(property.timezone_name, NEW.checked_out_at)::date INTO v_out
        FROM app.properties AS property WHERE property.id = NEW.property_id;
        UPDATE app.housekeeping_tasks AS task
        SET status = 'SKIPPED', note = 'The guest checked out', done_at = NEW.checked_out_at,
            done_by = NEW.checked_out_by, version = task.version + 1
        WHERE task.booking_id = NEW.id AND task.kind = 'DAILY_CLEAN' AND task.status = 'TO_DO'
          AND task.task_on >= v_out;
    END IF;
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION app.short_stay_daily_cleaning() FROM PUBLIC;
CREATE TRIGGER short_stay_bookings_daily_cleaning AFTER UPDATE OF status
    ON app.short_stay_bookings FOR EACH ROW EXECUTE FUNCTION app.short_stay_daily_cleaning();

-- The step 3 reads are kept under new names and wrapped.
ALTER FUNCTION app.short_stay_payment_state(uuid) RENAME TO short_stay_main_payment_state;
ALTER FUNCTION app.short_stay_booking_json(uuid) RENAME TO short_stay_booking_main_json;
"""

FUNCTIONS = r"""
-- The stay is paid only when its main Invoice (or the booking site) and every fee or extension
-- Invoice are paid.
CREATE FUNCTION app.short_stay_payment_state(p_booking uuid) RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT CASE
        WHEN main.state NOT IN ('PAID', 'PAID_ON_SITE') THEN main.state
        ELSE COALESCE((
            SELECT CASE WHEN bool_or(invoice.status = 'PARTIALLY_PAID') THEN 'PARTIALLY_PAID'
                        ELSE 'UNPAID' END
            FROM app.short_stay_extra_invoices AS extra
            JOIN app.invoices AS invoice ON invoice.id = extra.invoice_id
            WHERE extra.booking_id = p_booking AND invoice.status NOT IN ('PAID', 'VOID')
            HAVING count(*) > 0), main.state) END
    FROM (SELECT app.short_stay_main_payment_state(p_booking) AS state) AS main
$$;
REVOKE ALL ON FUNCTION app.short_stay_payment_state(uuid) FROM PUBLIC;

-- What an early check-in or a late check-out costs this stay (0 from 7 nights).
CREATE FUNCTION app.short_stay_fee(p_booking app.short_stay_bookings) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN p_booking.nights >= app.short_stay_rule('SS_EARLY_LATE_FREE_NIGHTS',
                    p_booking.check_in_on) THEN 0
                ELSE app.short_stay_rule('SS_EARLY_LATE_FEE', p_booking.check_in_on) END
$$;
REVOKE ALL ON FUNCTION app.short_stay_fee(app.short_stay_bookings) FROM PUBLIC;

-- One booking as the screens read it, now with its fee and extension Invoices and the times.
CREATE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT app.short_stay_booking_main_json(booking.id) || jsonb_build_object(
        'extra_invoices', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('invoice_id', invoice.id,
                'invoice_number', invoice.invoice_number, 'status', invoice.status,
                'kind', extra.kind, 'total_usd_cents', extra.amount_usd_cents)
                ORDER BY extra.price_version)
            FROM app.short_stay_extra_invoices AS extra
            JOIN app.invoices AS invoice ON invoice.id = extra.invoice_id
            WHERE extra.booking_id = booking.id), '[]'::jsonb),
        'early_check_in', EXISTS (SELECT 1 FROM app.short_stay_booking_events AS event
            WHERE event.booking_id = booking.id AND event.kind = 'EARLY_CHECK_IN'),
        'late_check_out', EXISTS (SELECT 1 FROM app.short_stay_booking_events AS event
            WHERE event.booking_id = booking.id AND event.kind = 'LATE_CHECK_OUT'),
        'fee_usd_cents', app.short_stay_fee(booking),
        'check_in_time', app.short_stay_rule('SS_CHECK_IN_TIME', booking.check_in_on),
        'check_out_time', app.short_stay_rule('SS_CHECK_OUT_TIME', booking.check_in_on),
        'late_check_out_until', app.short_stay_rule('SS_LATE_CHECK_OUT_UNTIL', booking.check_in_on),
        'cleans', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('task_id', task.id, 'task_on', task.task_on,
                'status', task.status, 'note', task.note) ORDER BY task.task_on)
            FROM app.housekeeping_tasks AS task
            WHERE task.booking_id = booking.id AND task.kind = 'DAILY_CLEAN'), '[]'::jsonb))
    FROM app.short_stay_bookings AS booking WHERE booking.id = p_booking
$$;
REVOKE ALL ON FUNCTION app.short_stay_booking_json(uuid) FROM PUBLIC;

-- The stay has its main Invoice or was paid on the booking site: a later fee or extension is then
-- its own Invoice.
CREATE FUNCTION app.short_stay_billed(p_booking uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT app.short_stay_main_payment_state(p_booking) <> 'NOT_BILLED'
$$;
REVOKE ALL ON FUNCTION app.short_stay_billed(uuid) FROM PUBLIC;

-- A fee or extension Invoice of one item, kept with the booking.
CREATE FUNCTION app.short_stay_extra_invoice(p_property uuid, p_actor uuid,
    p_row app.short_stay_bookings, p_kind text, p_version integer, p_cents bigint,
    p_description text, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v_issued jsonb;
BEGIN
    v_issued := app.short_stay_invoice(p_property, p_actor, p_row.customer_id,
        'Short stay ' || p_row.booking_number || ': ' || lower(replace(p_kind, '_', ' ')),
        'Short stay ' || p_row.booking_number,
        jsonb_build_array(jsonb_build_object('charge_id', gen_random_uuid(),
            'description', p_description, 'quantity', 1, 'unit_price_usd_cents', p_cents)),
        p_correlation);
    INSERT INTO app.short_stay_extra_invoices (invoice_id, booking_id, kind, price_version,
        amount_usd_cents, created_by)
    VALUES ((v_issued ->> 'invoice_id')::uuid, p_row.id, p_kind, p_version, p_cents, p_actor);
    RETURN v_issued;
END $$;
REVOKE ALL ON FUNCTION app.short_stay_extra_invoice(uuid, uuid, app.short_stay_bookings, text,
    integer, bigint, text, uuid) FROM PUBLIC;

-- 1. Early check-in or late check-out, once each.
CREATE FUNCTION app.add_short_stay_fee(p_property uuid, p_booking uuid, p_kind text,
    p_version integer, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
    v_fee bigint;
    v_next integer := v_row.price_version + 1;
    v_unit text;
    v_issued jsonb;
    v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
BEGIN
    IF p_kind IS NULL OR p_kind NOT IN ('EARLY_CHECK_IN', 'LATE_CHECK_OUT') THEN
        RAISE EXCEPTION 'The fee is an early check-in or a late check-out' USING ERRCODE = '22023';
    END IF;
    IF NOT (v_row.status = 'BOOKED'
            OR (v_row.status = 'CHECKED_IN' AND p_kind = 'LATE_CHECK_OUT')) THEN
        RAISE EXCEPTION 'An early check-in is before the guest is in; a late check-out before the guest leaves'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_booking_events AS event
               WHERE event.booking_id = p_booking AND event.kind = p_kind) THEN
        RAISE EXCEPTION 'This stay already has it' USING ERRCODE = '55000';
    END IF;
    v_fee := app.short_stay_fee(v_row);
    IF v_fee > 0 THEN
        INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind,
            quantity, unit_price_usd_cents, discount_basis_points, amount_usd_cents, reason,
            approved_by)
        SELECT p_booking, v_next, line.line_position, line.kind, line.quantity,
            line.unit_price_usd_cents, line.discount_basis_points, line.amount_usd_cents,
            line.reason, line.approved_by
        FROM app.short_stay_price_lines AS line
        WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version;
        INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind,
            quantity, unit_price_usd_cents, amount_usd_cents)
        SELECT p_booking, v_next, COALESCE(max(line.line_position), 0) + 1, p_kind, 1, v_fee, v_fee
        FROM app.short_stay_price_lines AS line
        WHERE line.booking_id = p_booking AND line.price_version = v_next;
        UPDATE app.short_stay_bookings AS booking
        SET price_version = v_next, total_usd_cents = booking.total_usd_cents + v_fee,
            version = booking.version + 1
        WHERE booking.id = p_booking;
        IF app.short_stay_billed(p_booking) THEN
            SELECT unit.unit_number INTO v_unit FROM app.units AS unit WHERE unit.id = v_row.unit_id;
            v_issued := app.short_stay_extra_invoice(p_property, p_actor, v_row, p_kind, v_next,
                v_fee, v_row.booking_number || ' · ' || v_unit || ' · '
                    || CASE p_kind WHEN 'EARLY_CHECK_IN' THEN 'Early check-in '
                        || to_char(v_row.check_in_on, 'DD/MM/YYYY')
                        ELSE 'Late check-out ' || to_char(v_row.check_out_on, 'DD/MM/YYYY') END,
                v_correlation);
        END IF;
    ELSE
        UPDATE app.short_stay_bookings AS booking SET version = booking.version + 1
        WHERE booking.id = p_booking;
    END IF;
    PERFORM app.short_stay_event(p_booking, p_kind, p_actor, NULL,
        jsonb_build_object('fee_usd_cents', v_fee, 'invoice_id', v_issued ->> 'invoice_id',
            'invoice_number', v_issued ->> 'invoice_number'));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.fee',
        'short_stay_booking', p_booking, 'Short-stay early check-in or late check-out',
        'short_stays.desk', NULL,
        jsonb_build_object('kind', p_kind, 'fee_usd_cents', v_fee), v_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 2. Extend the stay to a later check-out day.
CREATE FUNCTION app.extend_short_stay(p_property uuid, p_booking uuid, p_change jsonb,
    p_version integer, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
    v_out date;
    v_rent bigint;
    v_unit text;
    v_blockers jsonb;
    v_price jsonb;
    v_next integer := v_row.price_version + 1;
    v_total bigint;
    v_more bigint;
    v_issued jsonb;
    v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
BEGIN
    IF v_row.status NOT IN ('BOOKED', 'CHECKED_IN') THEN
        RAISE EXCEPTION 'Only a stay that is booked or in is extended' USING ERRCODE = '55000';
    END IF;
    BEGIN
        v_out := (p_change ->> 'check_out_on')::date;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The new check-out day is invalid' USING ERRCODE = '22023';
    END;
    IF v_out IS NULL OR v_out <= v_row.check_out_on THEN
        RAISE EXCEPTION 'The new check-out day is after the old one' USING ERRCODE = '22023';
    END IF;
    SELECT unit.default_monthly_rent_usd_cents, unit.unit_number INTO v_rent, v_unit
    FROM app.units AS unit WHERE unit.id = v_row.unit_id FOR UPDATE;
    -- The nights added; a guest who is in may stay on past nights already started.
    SELECT COALESCE(jsonb_agg(blocker), '[]'::jsonb) INTO v_blockers
    FROM jsonb_array_elements_text(app.short_stay_blockers(v_row.unit_id, v_row.check_out_on,
        v_out, v_today)) AS blocker
    WHERE NOT (blocker = 'PAST' AND v_row.status = 'CHECKED_IN');
    IF v_blockers <> '[]'::jsonb THEN
        RAISE EXCEPTION 'The Unit cannot be booked for the added nights: %',
            (SELECT string_agg(value, ', ') FROM jsonb_array_elements_text(v_blockers))
            USING ERRCODE = '55000';
    END IF;
    v_price := app.short_stay_price(v_rent, v_out - v_row.check_in_on, v_row.check_in_on);
    INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind,
        quantity, unit_price_usd_cents, discount_basis_points, amount_usd_cents)
    SELECT p_booking, v_next, (line ->> 'position')::smallint, line ->> 'kind',
        (line ->> 'quantity')::integer, (line ->> 'unit_price_usd_cents')::bigint,
        (line ->> 'discount_basis_points')::integer, (line ->> 'amount_usd_cents')::bigint
    FROM jsonb_array_elements(v_price -> 'lines') AS line;
    -- Fees and discounts stay with the stay.
    INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind,
        quantity, unit_price_usd_cents, discount_basis_points, amount_usd_cents, reason,
        approved_by)
    SELECT p_booking, v_next, jsonb_array_length(v_price -> 'lines')
            + row_number() OVER (ORDER BY line.line_position),
        line.kind, line.quantity, line.unit_price_usd_cents, line.discount_basis_points,
        line.amount_usd_cents, line.reason, line.approved_by
    FROM app.short_stay_price_lines AS line
    WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version
      AND line.kind NOT IN ('NIGHTS', 'WEEKS');
    SELECT sum(line.amount_usd_cents) INTO v_total FROM app.short_stay_price_lines AS line
    WHERE line.booking_id = p_booking AND line.price_version = v_next;
    v_more := v_total - v_row.total_usd_cents;
    IF v_more < 0 THEN
        RAISE EXCEPTION 'The longer stay would cost less than now; ask the Manager'
            USING ERRCODE = '55000';
    END IF;
    UPDATE app.short_stay_bookings AS booking
    SET check_out_on = v_out, price_version = v_next, total_usd_cents = v_total,
        version = booking.version + 1
    WHERE booking.id = p_booking;
    IF v_more > 0 AND app.short_stay_billed(p_booking) THEN
        v_issued := app.short_stay_extra_invoice(p_property, p_actor, v_row, 'EXTEND', v_next,
            v_more, v_row.booking_number || ' · ' || v_unit || ' · Stay extended '
                || to_char(v_row.check_out_on, 'DD/MM/YYYY') || ' to '
                || to_char(v_out, 'DD/MM/YYYY') || ' (' || (v_out - v_row.check_in_on)
                || ' nights in all)', v_correlation);
    END IF;
    IF v_row.status = 'CHECKED_IN' THEN
        INSERT INTO app.housekeeping_tasks (property_id, unit_id, booking_id, task_on, kind,
            created_by)
        SELECT p_property, v_row.unit_id, p_booking, day::date, 'DAILY_CLEAN', p_actor
        FROM generate_series(v_row.check_out_on, v_out - 1, interval '1 day') AS day
        ON CONFLICT (booking_id, task_on, kind) DO NOTHING;
    END IF;
    PERFORM app.short_stay_event(p_booking, 'EXTENDED', p_actor, NULL,
        jsonb_build_object('check_out_on', v_row.check_out_on, 'new_check_out_on', v_out,
            'more_usd_cents', v_more, 'invoice_id', v_issued ->> 'invoice_id',
            'invoice_number', v_issued ->> 'invoice_number'));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.extended',
        'short_stay_booking', p_booking, 'Short stay extended', 'short_stays.desk',
        jsonb_build_object('check_out_on', v_row.check_out_on,
            'total_usd_cents', v_row.total_usd_cents),
        jsonb_build_object('check_out_on', v_out, 'total_usd_cents', v_total), v_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 3. The cleaning list of one day: that day's tasks, and today also the ones not done before.
CREATE FUNCTION app.short_stay_housekeeping(p_property uuid, p_day date, p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v_today date := app.require_product_right(p_actor, 'short_stays.read', p_property);
BEGIN
    IF p_day IS NULL THEN
        RAISE EXCEPTION 'The day is invalid' USING ERRCODE = '22023';
    END IF;
    RETURN jsonb_build_object('day', p_day, 'today', v_today, 'tasks', COALESCE((
        SELECT jsonb_agg(jsonb_build_object('task_id', task.id, 'kind', task.kind,
            'task_on', task.task_on, 'status', task.status, 'note', task.note,
            'done_at', task.done_at, 'unit_id', task.unit_id, 'unit_number', unit.unit_number,
            'booking_id', booking.id, 'booking_number', booking.booking_number,
            'guest_name', customer.legal_name, 'late', task.task_on < p_day,
            'version', task.version)
            ORDER BY task.status <> 'TO_DO', unit.unit_number, task.kind, task.task_on)
        FROM app.housekeeping_tasks AS task
        JOIN app.units AS unit ON unit.id = task.unit_id
        LEFT JOIN app.short_stay_bookings AS booking ON booking.id = task.booking_id
        LEFT JOIN app.customers AS customer ON customer.id = booking.customer_id
        WHERE task.property_id = p_property
          AND (task.task_on = p_day
               OR (p_day = v_today AND task.task_on < p_day AND task.status = 'TO_DO'))),
        '[]'::jsonb));
END $$;

-- 4. A clean done, or skipped with a reason. The room check is done on the booking page.
CREATE FUNCTION app.finish_housekeeping_task(p_property uuid, p_task uuid, p_finish jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.housekeeping', p_property);
    v_task app.housekeeping_tasks%ROWTYPE;
    v_skip boolean;
    v_note text := NULLIF(btrim(p_finish ->> 'note'), '');
BEGIN
    SELECT task.* INTO v_task FROM app.housekeeping_tasks AS task
    WHERE task.id = p_task AND task.property_id = p_property FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the task does not exist' USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_skip := COALESCE((p_finish ->> 'skip')::boolean, false);
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The task answer is invalid' USING ERRCODE = '22023';
    END;
    IF v_task.kind = 'ROOM_CHECK' THEN
        RAISE EXCEPTION 'The room check is done on the booking page' USING ERRCODE = '55000';
    END IF;
    IF v_task.status <> 'TO_DO' THEN
        RAISE EXCEPTION 'This task is already done' USING ERRCODE = '55000';
    END IF;
    IF v_task.task_on > v_today THEN
        RAISE EXCEPTION 'This task is not due yet' USING ERRCODE = '55000';
    END IF;
    IF v_skip AND v_note IS NULL THEN
        RAISE EXCEPTION 'A skipped clean says why' USING ERRCODE = '22023';
    END IF;
    IF length(v_note) > 500 THEN
        RAISE EXCEPTION 'The note is too long' USING ERRCODE = '22023';
    END IF;
    UPDATE app.housekeeping_tasks AS task
    SET status = CASE WHEN v_skip THEN 'SKIPPED' ELSE 'DONE' END, note = v_note,
        done_at = statement_timestamp(), done_by = p_actor, version = task.version + 1
    WHERE task.id = p_task;
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.cleaned',
        'housekeeping_task', p_task, 'Housekeeping task finished', 'short_stays.housekeeping',
        jsonb_build_object('status', 'TO_DO'),
        jsonb_build_object('status', CASE WHEN v_skip THEN 'SKIPPED' ELSE 'DONE' END),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_housekeeping(p_property, v_task.task_on, p_actor);
END $$;
"""

ACTIONS = (
    "app.add_short_stay_fee(uuid, uuid, text, integer, uuid, uuid)",
    "app.extend_short_stay(uuid, uuid, jsonb, integer, uuid, uuid)",
    "app.short_stay_housekeeping(uuid, date, uuid)",
    "app.finish_housekeeping_task(uuid, uuid, jsonb, uuid, uuid)",
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
    raise RuntimeError("Short stays step 4a migration is forward-only")
