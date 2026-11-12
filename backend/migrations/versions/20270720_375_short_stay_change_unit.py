# ruff: noqa: E501
"""Owner's rules of 12 Nov 2026, DL-224: Change Unit for a short-stay booking before check-in.

The owner's words: staff may move a booked guest to another Unit while the guest has not checked
in yet; a Unit of the same type first; when none is free, another type "with special discount" or
an upgrade to a bigger Unit. The owner's two answers of 12 Nov 2026:

- "Guest keeps the agreed price": the price lines, the bill and the money paid stay as they are,
  even if the new Unit has another Rent. A bigger Unit is a free upgrade.
- "Owner or Manager types the amount": the move changes no money by itself. An Owner or Manager
  may then give a special discount with a reason. When the stay is already paid, the amount
  becomes the guest's Credit.

What this migration adds (functions and one trigger; no table, column or data change):

- ``app.short_stay_move_units``: the Units a booked stay can move to (free on every night of the
  stay, the same type first), for the Change Unit dialog.
- ``app.change_short_stay_unit``: the move, with a reason, by the front desk
  (``short_stays.desk``), only while the booking is Booked. The price lines are copied to a new
  price version unchanged; the booking's History keeps the old and the new Unit.
- ``app.give_short_stay_move_discount``: the special discount after a move
  (``short_stays.approve``), once for each move. Before the Invoice it is a price line; after it
  the Invoice is credited too, and what was paid above the new total becomes Customer Credit.
- ``app.short_stay_refund_sources`` also finds that Credit, so the booking shows it with the
  Refund button a free cancel already has.
- A moved stay is not extended: Extend prices every night again from the Rent of the Unit the
  guest is in, which would change the agreed price. The extra nights are a new booking.

An Invoice keeps the Unit number it was issued with; the History shows the move.

Forward-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270720_375"
down_revision: str | None = "20270719_374"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = r"""
-- Why a Unit cannot take a booked stay that moves to it (empty when it can). The same checks as
-- a new booking, but a stay whose check-in day has come may still move, and a booking site's
-- hold counts as the booking trigger counts it.
CREATE FUNCTION app.short_stay_move_blockers(p_unit uuid, p_row app.short_stay_bookings,
    p_today date)
RETURNS jsonb LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT COALESCE(jsonb_agg(found.blocker ORDER BY found.blocker), '[]'::jsonb) FROM (
        SELECT blocker FROM jsonb_array_elements_text(app.short_stay_blockers(p_unit,
            p_row.check_in_on, p_row.check_out_on, p_today)) AS blocker
        WHERE blocker <> 'PAST'
        UNION ALL
        SELECT 'SITE_HOLD' WHERE app.short_stay_site_holds(p_unit, p_row.check_in_on,
            p_row.check_out_on,
            CASE WHEN p_row.source = 'BOOKING_SITE' THEN p_row.site_name END) <> '[]'::jsonb
    ) AS found
$$;
REVOKE ALL ON FUNCTION app.short_stay_move_blockers(uuid, app.short_stay_bookings, date) FROM PUBLIC;

-- The Units a booked stay can move to: the same type first, then the other types.
CREATE FUNCTION app.short_stay_move_units(p_property uuid, p_booking uuid, p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.read', p_property);
    v_row app.short_stay_bookings%ROWTYPE;
    v_type text;
BEGIN
    SELECT booking.* INTO v_row FROM app.short_stay_bookings AS booking
    WHERE booking.id = p_booking AND booking.property_id = p_property;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the booking does not exist' USING ERRCODE = '22023';
    END IF;
    SELECT unit.unit_type INTO v_type FROM app.units AS unit WHERE unit.id = v_row.unit_id;
    RETURN jsonb_build_object('booking_id', v_row.id, 'unit_id', v_row.unit_id,
        'unit_type', v_type,
        'units', CASE WHEN v_row.status <> 'BOOKED' THEN '[]'::jsonb ELSE COALESCE((
            SELECT jsonb_agg(jsonb_build_object('unit_id', unit.id,
                    'unit_number', unit.unit_number, 'floor', unit.floor,
                    'unit_type', unit.unit_type, 'same_type', unit.unit_type = v_type,
                    'monthly_rent_usd_cents', unit.default_monthly_rent_usd_cents)
                ORDER BY (unit.unit_type = v_type) DESC, unit.unit_number)
            FROM app.units AS unit
            WHERE unit.property_id = p_property AND unit.id <> v_row.unit_id
              AND app.short_stay_move_blockers(unit.id, v_row, v_today) = '[]'::jsonb),
            '[]'::jsonb) END);
END $$;

-- Change Unit: a booked guest moves to another Unit before check-in and keeps the agreed price.
CREATE FUNCTION app.change_short_stay_unit(p_property uuid, p_booking uuid, p_change jsonb,
    p_version integer, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
    v_reason text := NULLIF(btrim(p_change ->> 'reason'), '');
    v_from app.units%ROWTYPE;
    v_to app.units%ROWTYPE;
    v_blockers jsonb;
    v_next integer := v_row.price_version + 1;
BEGIN
    IF p_change IS NULL OR jsonb_typeof(p_change) <> 'object' THEN
        RAISE EXCEPTION 'The move is invalid' USING ERRCODE = '22023';
    END IF;
    BEGIN
        SELECT unit.* INTO v_to FROM app.units AS unit
        WHERE unit.id = (p_change ->> 'unit_id')::uuid AND unit.property_id = p_property
        FOR UPDATE;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The move is invalid' USING ERRCODE = '22023';
    END;
    IF v_to.id IS NULL THEN
        RAISE EXCEPTION 'the Unit does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_to.id = v_row.unit_id THEN
        RAISE EXCEPTION 'The guest is already booked in this Unit' USING ERRCODE = '22023';
    END IF;
    IF v_reason IS NULL OR length(v_reason) > 500 THEN
        RAISE EXCEPTION 'A move to another Unit says why' USING ERRCODE = '22023';
    END IF;
    IF v_row.status <> 'BOOKED' THEN
        RAISE EXCEPTION 'Only a booking that is not checked in yet moves to another Unit'
            USING ERRCODE = '55000';
    END IF;
    v_blockers := app.short_stay_move_blockers(v_to.id, v_row, v_today);
    IF v_blockers <> '[]'::jsonb THEN
        RAISE EXCEPTION 'The Unit cannot take this stay: %',
            (SELECT string_agg(value, ', ') FROM jsonb_array_elements_text(v_blockers))
            USING ERRCODE = '55000';
    END IF;
    SELECT unit.* INTO v_from FROM app.units AS unit WHERE unit.id = v_row.unit_id;
    -- The guest keeps the agreed price: the same lines under the next price version.
    INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind,
        quantity, unit_price_usd_cents, discount_basis_points, amount_usd_cents, reason,
        approved_by)
    SELECT p_booking, v_next, line.line_position, line.kind, line.quantity,
        line.unit_price_usd_cents, line.discount_basis_points, line.amount_usd_cents,
        line.reason, line.approved_by
    FROM app.short_stay_price_lines AS line
    WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version;
    UPDATE app.short_stay_bookings AS booking
    SET unit_id = v_to.id, price_version = v_next, version = booking.version + 1
    WHERE booking.id = p_booking;
    PERFORM app.short_stay_event(p_booking, 'UNIT_CHANGED', p_actor, v_reason,
        jsonb_build_object('from_unit_id', v_from.id, 'from_unit_number', v_from.unit_number,
            'from_unit_type', v_from.unit_type, 'to_unit_id', v_to.id,
            'to_unit_number', v_to.unit_number, 'to_unit_type', v_to.unit_type));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.unit_changed',
        'short_stay_booking', p_booking, v_reason, 'short_stays.desk',
        jsonb_build_object('unit_id', v_from.id, 'unit_number', v_from.unit_number,
            'unit_type', v_from.unit_type),
        jsonb_build_object('unit_id', v_to.id, 'unit_number', v_to.unit_number,
            'unit_type', v_to.unit_type, 'total_usd_cents', v_row.total_usd_cents),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- The special discount after a move: Owner or Manager, with a reason, once for each move.
CREATE FUNCTION app.give_short_stay_move_discount(p_property uuid, p_booking uuid,
    p_discount jsonb, p_version integer, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.approve', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
    v_amount bigint;
    v_reason text := NULLIF(btrim(p_discount ->> 'reason'), '');
    v_next integer := v_row.price_version + 1;
    v_moves integer;
    v_given integer;
    v_left bigint;
    v_credit bigint := 0;
    v_invoice uuid;
    v_line record;
    v_owed bigint;
    v_paid bigint;
    v_part bigint;
    v_key uuid;
BEGIN
    BEGIN
        v_amount := (p_discount ->> 'amount_usd_cents')::bigint;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The discount is a whole number of cents' USING ERRCODE = '22023';
    END;
    IF v_amount IS NULL OR v_amount < 1 THEN
        RAISE EXCEPTION 'The discount is a whole number of cents' USING ERRCODE = '22023';
    END IF;
    IF v_reason IS NULL OR length(v_reason) > 460 THEN
        RAISE EXCEPTION 'A discount needs a reason' USING ERRCODE = '22023';
    END IF;
    IF v_row.status <> 'BOOKED' THEN
        RAISE EXCEPTION 'The special discount is given before the guest checks in'
            USING ERRCODE = '55000';
    END IF;
    SELECT count(*) FILTER (WHERE event.kind = 'UNIT_CHANGED'),
        count(*) FILTER (WHERE event.kind = 'MOVE_DISCOUNT')
    INTO v_moves, v_given
    FROM app.short_stay_booking_events AS event WHERE event.booking_id = p_booking;
    IF v_moves = 0 THEN
        RAISE EXCEPTION 'The special discount is for a stay that was moved to another Unit'
            USING ERRCODE = '55000';
    END IF;
    IF v_given >= v_moves THEN
        RAISE EXCEPTION 'This move already has its special discount' USING ERRCODE = '55000';
    END IF;
    IF v_row.paid_on_site THEN
        RAISE EXCEPTION 'This stay was paid on the booking site; there is no Invoice here to take a discount off'
            USING ERRCODE = '55000';
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
    -- After the Invoice: the Invoices of the stay are credited, the main one first. What the
    -- guest paid above the new amount becomes Customer Credit.
    IF app.short_stay_billed(p_booking) THEN
        v_left := v_amount;
        FOR v_invoice IN SELECT stay_invoice.id
                         FROM app.short_stay_invoices(p_booking) AS stay_invoice(id) LOOP
            FOR v_line IN SELECT line.id FROM app.invoice_lines AS line
                          WHERE line.invoice_id = v_invoice ORDER BY line.id LOOP
                EXIT WHEN v_left <= 0;
                v_owed := app.invoice_adjusted_line_obligation(v_line.id);
                v_paid := app.invoice_line_application_value_at(v_line.id, 'infinity');
                v_part := least(v_owed, v_left);
                IF v_part > 0 THEN
                    v_key := gen_random_uuid();
                    PERFORM app.adjust_invoice(p_property, v_invoice, v_line.id, p_actor, v_key,
                        encode(sha256(convert_to('short-stay-move-discount:' || v_key::text,
                            'UTF8')), 'hex'),
                        (SELECT invoice.version FROM app.invoices AS invoice
                         WHERE invoice.id = v_invoice),
                        'CREDIT', v_part, 'Short stay ' || v_row.booking_number,
                        'Special discount after a move: ' || v_reason,
                        gen_random_uuid(), gen_random_uuid());
                    v_credit := v_credit + greatest(v_paid - (v_owed - v_part), 0);
                    v_left := v_left - v_part;
                END IF;
            END LOOP;
            EXIT WHEN v_left <= 0;
        END LOOP;
        IF v_left > 0 THEN
            RAISE EXCEPTION 'The discount is more than the Invoices of the stay'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    PERFORM app.short_stay_event(p_booking, 'MOVE_DISCOUNT', p_actor, v_reason,
        jsonb_build_object('amount_usd_cents', v_amount, 'credit_usd_cents', v_credit));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.move_discount',
        'short_stay_booking', p_booking, v_reason, 'short_stays.approve', NULL,
        jsonb_build_object('amount_usd_cents', v_amount, 'credit_usd_cents', v_credit),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- The Customer Credits of a stay that the Refund button gives back: from a free cancel, and
-- now also from a special discount on a paid stay.
CREATE OR REPLACE FUNCTION app.short_stay_refund_sources(p_booking uuid) RETURNS SETOF uuid
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT DISTINCT coalesce(released.customer_credit_id, application.customer_credit_id)
    FROM app.invoice_credit_excess_releases AS released
    JOIN app.invoice_adjustments AS adjustment ON adjustment.id = released.invoice_adjustment_id
    LEFT JOIN app.customer_credit_applications AS application
        ON application.id = released.reversed_credit_application_id
    WHERE (adjustment.reason = 'Free cancel: the money paid comes back'
           OR adjustment.reason LIKE 'Special discount after a move: %')
      AND adjustment.invoice_id IN (SELECT app.short_stay_invoices(p_booking))
$$;
REVOKE ALL ON FUNCTION app.short_stay_refund_sources(uuid) FROM PUBLIC;

-- A moved stay keeps its agreed price, so it is not extended: Extend prices every night again
-- from the Rent of the Unit the guest is in. The extra nights are a new booking.
CREATE FUNCTION app.guard_short_stay_moved_extend() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.check_out_on > OLD.check_out_on AND EXISTS (
        SELECT 1 FROM app.short_stay_booking_events AS event
        WHERE event.booking_id = NEW.id AND event.kind = 'UNIT_CHANGED') THEN
        RAISE EXCEPTION 'This stay was moved to another Unit and keeps its agreed price; make a new booking for the extra nights'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.guard_short_stay_moved_extend() FROM PUBLIC;
CREATE TRIGGER short_stay_bookings_moved_extend BEFORE UPDATE OF check_out_on
    ON app.short_stay_bookings FOR EACH ROW EXECUTE FUNCTION app.guard_short_stay_moved_extend();
"""

ACTIONS = (
    "app.short_stay_move_units(uuid, uuid, uuid)",
    "app.change_short_stay_unit(uuid, uuid, jsonb, integer, uuid, uuid)",
    "app.give_short_stay_move_discount(uuid, uuid, jsonb, integer, uuid, uuid)",
)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature in ACTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
