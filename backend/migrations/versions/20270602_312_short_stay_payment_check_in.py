# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 3: payment, deposit, check-in, check-out, damage.

The owner's rules (PRD 03/11/2026, decisions after mock-up v70):

1. Full payment before check-in. "Bill" makes the booking's Invoice from its price lines (one
   Invoice item per line) and issues it; the guest pays it on the usual Receive payment screen,
   which makes the Receipt. A booking-site guest who paid the site is marked "paid on the site"
   instead (card question 04/11, recommended answer; no Invoice to the guest, so nothing is
   paid twice).
2. Every guest leaves a deposit: SS_CASH_DEPOSIT ($50) in cash, or a card hold of SS_CARD_HOLD
   ($50). A card number is never saved, only the hold reference and, if wanted, the last 4 digits.
3. Check-in from the check-in day, before the check-out day: the stay is paid, the deposit is
   taken, the guest's ID or passport number is on the Customer, the desk made a copy and the
   guest signed the house rules. The room must be ready (the Unit is Vacant, so the room check
   of the guest before is done). The Unit becomes "Short stay".
4. Check-out: the Unit becomes Cleaning and a room check is due today.
5. The room check (housekeeping right) is done once; it can report damage with a cost. The Unit
   becomes Vacant again.
6. Damage waits for the Manager (approve right), who approves or refuses it with a reason.
   Approved damage is taken from the deposit first; the rest is an Invoice for the guest (card
   question 04/11, recommended answer).
7. The deposit ends after the room check, once no damage waits: Returned, or Kept with what the
   approved damage took from it.

Early check-in and late check-out fees, cancel, credit and extend are step 4. Technical choices by
Claude under the owner's 2026-10-23 22:30 rule. Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270602_312"
down_revision: str | None = "20270601_311"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USED = ("SS_CASH_DEPOSIT", "SS_CARD_HOLD")

SCHEMA = r"""
ALTER TABLE app.short_stay_bookings
    ADD COLUMN invoice_id uuid UNIQUE REFERENCES app.invoices (id) ON DELETE RESTRICT,
    ADD COLUMN paid_on_site boolean NOT NULL DEFAULT false,
    ADD COLUMN id_copy_made boolean NOT NULL DEFAULT false,
    ADD COLUMN house_rules_signed boolean NOT NULL DEFAULT false,
    ADD CONSTRAINT short_stay_bookings_paid_on_site_shape
        CHECK (NOT paid_on_site OR (source = 'BOOKING_SITE' AND invoice_id IS NULL)),
    ADD CONSTRAINT short_stay_bookings_check_in_needs
        CHECK (status NOT IN ('CHECKED_IN', 'CHECKED_OUT')
            OR (id_copy_made AND house_rules_signed AND (paid_on_site OR invoice_id IS NOT NULL)));

ALTER TABLE app.short_stay_damages
    ADD COLUMN from_deposit_usd_cents bigint NOT NULL DEFAULT 0
        CHECK (from_deposit_usd_cents >= 0),
    ADD COLUMN invoice_id uuid UNIQUE REFERENCES app.invoices (id) ON DELETE RESTRICT,
    ADD CONSTRAINT short_stay_damages_charge_shape CHECK (
        from_deposit_usd_cents <= amount_usd_cents
        AND (status = 'APPROVED' OR (from_deposit_usd_cents = 0 AND invoice_id IS NULL))
        AND (status <> 'APPROVED'
            OR (invoice_id IS NOT NULL) = (from_deposit_usd_cents < amount_usd_cents)));

-- The payment and check-in columns only move forward. A voided Invoice may be billed again.
CREATE FUNCTION app.protect_short_stay_payment() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF (NEW.invoice_id IS DISTINCT FROM OLD.invoice_id AND OLD.invoice_id IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM app.invoices AS invoice
                            WHERE invoice.id = OLD.invoice_id AND invoice.status = 'VOID'))
        OR (OLD.paid_on_site AND NOT NEW.paid_on_site)
        OR (OLD.id_copy_made AND NOT NEW.id_copy_made)
        OR (OLD.house_rules_signed AND NOT NEW.house_rules_signed)
        OR ((NEW.id_copy_made, NEW.house_rules_signed)
                IS DISTINCT FROM (OLD.id_copy_made, OLD.house_rules_signed)
            AND NOT (OLD.status = 'BOOKED' AND NEW.status = 'CHECKED_IN'))
    THEN
        RAISE EXCEPTION 'A short-stay payment or check-in only moves forward'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.protect_short_stay_payment() FROM PUBLIC;
CREATE TRIGGER short_stay_bookings_payment BEFORE UPDATE ON app.short_stay_bookings
    FOR EACH ROW EXECUTE FUNCTION app.protect_short_stay_payment();

-- Damage keeps what it took from the deposit and its Invoice when it is approved.
CREATE OR REPLACE FUNCTION app.protect_short_stay_step() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_old jsonb := to_jsonb(OLD);
    v_new jsonb := to_jsonb(NEW);
    v_open text := CASE TG_TABLE_NAME
        WHEN 'short_stay_deposits' THEN 'HELD'
        WHEN 'housekeeping_tasks' THEN 'TO_DO'
        ELSE 'WAITING' END;
    v_free text[] := CASE TG_TABLE_NAME
        WHEN 'short_stay_deposits' THEN ARRAY['status', 'kept_usd_cents', 'ended_at', 'ended_by',
            'end_note', 'version']
        WHEN 'housekeeping_tasks' THEN ARRAY['status', 'note', 'done_at', 'done_by', 'version']
        ELSE ARRAY['status', 'decided_at', 'decided_by', 'decision_note', 'version',
            'from_deposit_usd_cents', 'invoice_id'] END;
BEGIN
    IF TG_OP <> 'UPDATE' OR OLD.status <> v_open OR NEW.status = v_open
        OR (v_new ->> 'version')::integer <> (v_old ->> 'version')::integer + 1
        OR (v_old - v_free) <> (v_new - v_free)
    THEN
        RAISE EXCEPTION '% rows move forward once and are never removed', TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
"""

FUNCTIONS = r"""
-- "$26.00", as the Invoice text shows money.
CREATE FUNCTION app.short_stay_dollars(p_cents bigint) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT '$' || to_char(p_cents / 100.0, 'FM999,999,990.00')
$$;
REVOKE ALL ON FUNCTION app.short_stay_dollars(bigint) FROM PUBLIC;

-- An issued one-time Invoice for the guest, made the way a signed Quotation makes one.
CREATE FUNCTION app.short_stay_invoice(p_property uuid, p_actor uuid, p_customer uuid,
    p_reason text, p_reference text, p_items jsonb, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_invoice uuid := gen_random_uuid();
    v_digest text := encode(sha256(convert_to('short-stay:' || v_invoice::text, 'UTF8')), 'hex');
    v_version integer;
BEGIN
    PERFORM app.create_items_invoice_draft(p_property, p_actor, gen_random_uuid(), v_digest,
        v_invoice, gen_random_uuid(), p_correlation, p_customer, NULL, p_reason, p_reference,
        p_items);
    SELECT invoice.version INTO v_version FROM app.invoices AS invoice WHERE invoice.id = v_invoice;
    RETURN app.issue_invoice(p_property, v_invoice, p_actor, gen_random_uuid(), v_digest,
        v_version, gen_random_uuid(), p_correlation, NULL, NULL)
        || jsonb_build_object('invoice_id', v_invoice);
END $$;
REVOKE ALL ON FUNCTION app.short_stay_invoice(uuid, uuid, uuid, text, text, jsonb, uuid) FROM PUBLIC;

-- The booking, locked, in this Property, at the version the screen read.
CREATE FUNCTION app.short_stay_locked(p_property uuid, p_booking uuid, p_version integer)
RETURNS app.short_stay_bookings LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE v_row app.short_stay_bookings%ROWTYPE;
BEGIN
    SELECT booking.* INTO v_row FROM app.short_stay_bookings AS booking
    WHERE booking.id = p_booking AND booking.property_id = p_property FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the booking does not exist' USING ERRCODE = '22023';
    END IF;
    IF p_version IS NOT NULL AND p_version <> v_row.version THEN
        RAISE EXCEPTION 'The booking changed since it was read' USING ERRCODE = '40001';
    END IF;
    RETURN v_row;
END $$;
REVOKE ALL ON FUNCTION app.short_stay_locked(uuid, uuid, integer) FROM PUBLIC;

-- How the stay is paid: not billed, the Invoice's status, or paid on the booking site.
CREATE FUNCTION app.short_stay_payment_state(p_booking uuid) RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT CASE
        WHEN booking.paid_on_site THEN 'PAID_ON_SITE'
        WHEN invoice.id IS NULL OR invoice.status = 'VOID' THEN 'NOT_BILLED'
        ELSE invoice.status END
    FROM app.short_stay_bookings AS booking
    LEFT JOIN app.invoices AS invoice ON invoice.id = booking.invoice_id
    WHERE booking.id = p_booking
$$;
REVOKE ALL ON FUNCTION app.short_stay_payment_state(uuid) FROM PUBLIC;

-- One booking as the screens read it, now with payment, deposit, room check and damage.
CREATE OR REPLACE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT jsonb_build_object(
        'booking_id', booking.id, 'booking_number', booking.booking_number,
        'unit_id', booking.unit_id, 'unit_number', unit.unit_number, 'unit_type', unit.unit_type,
        'unit_status', unit.status,
        'customer_id', booking.customer_id, 'guest_name', customer.legal_name,
        'guest_phone', customer.phone_number, 'guest_count', booking.guest_count,
        'guest_has_id', customer.id_document_number IS NOT NULL,
        'check_in_on', booking.check_in_on, 'check_out_on', booking.check_out_on,
        'nights', booking.nights, 'source', booking.source, 'site_name', booking.site_name,
        'site_reference', booking.site_reference, 'note', booking.note,
        'status', booking.status, 'total_usd_cents', booking.total_usd_cents,
        'price_version', booking.price_version, 'version', booking.version,
        'created_at', booking.created_at,
        'payment', app.short_stay_payment_state(booking.id),
        'invoice', CASE WHEN invoice.id IS NULL THEN NULL ELSE jsonb_build_object(
            'invoice_id', invoice.id, 'invoice_number', invoice.invoice_number,
            'status', invoice.status, 'total_usd_cents', invoice.original_total_usd_cents) END,
        'id_copy_made', booking.id_copy_made, 'house_rules_signed', booking.house_rules_signed,
        'checked_in_at', booking.checked_in_at, 'checked_out_at', booking.checked_out_at,
        'deposit', (SELECT jsonb_build_object('deposit_id', deposit.id, 'kind', deposit.kind,
                'amount_usd_cents', deposit.amount_usd_cents,
                'hold_reference', deposit.hold_reference, 'card_last4', deposit.card_last4,
                'status', deposit.status, 'kept_usd_cents', deposit.kept_usd_cents,
                'taken_at', deposit.taken_at, 'ended_at', deposit.ended_at,
                'end_note', deposit.end_note)
            FROM app.short_stay_deposits AS deposit WHERE deposit.booking_id = booking.id),
        'room_check', (SELECT jsonb_build_object('task_id', task.id, 'task_on', task.task_on,
                'status', task.status, 'note', task.note, 'done_at', task.done_at)
            FROM app.housekeeping_tasks AS task
            WHERE task.booking_id = booking.id AND task.kind = 'ROOM_CHECK'
            ORDER BY task.task_on DESC LIMIT 1),
        'damages', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('damage_id', damage.id,
                'description', damage.description, 'amount_usd_cents', damage.amount_usd_cents,
                'status', damage.status, 'asked_at', damage.asked_at,
                'decided_at', damage.decided_at, 'decision_note', damage.decision_note,
                'from_deposit_usd_cents', damage.from_deposit_usd_cents,
                'invoice_id', damage.invoice_id, 'invoice_number', damage_invoice.invoice_number)
                ORDER BY damage.asked_at, damage.id)
            FROM app.short_stay_damages AS damage
            LEFT JOIN app.invoices AS damage_invoice ON damage_invoice.id = damage.invoice_id
            WHERE damage.booking_id = booking.id), '[]'::jsonb),
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
    LEFT JOIN app.invoices AS invoice ON invoice.id = booking.invoice_id
    WHERE booking.id = p_booking
$$;

-- The calendar now says whether each booking is paid (a dashed square when it is not).
CREATE OR REPLACE FUNCTION app.short_stay_calendar(p_property uuid, p_from date, p_days integer,
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
                        'check_out_on', booking.check_out_on,
                        'paid', app.short_stay_payment_state(booking.id)
                            IN ('PAID', 'PAID_ON_SITE')) ORDER BY booking.check_in_on)
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

-- 1. Bill: the booking's Invoice, one item per price line, issued at once.
CREATE FUNCTION app.bill_short_stay(p_property uuid, p_booking uuid, p_version integer,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
    v_unit text;
    v_items jsonb;
    v_issued jsonb;
    v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
BEGIN
    IF v_row.status <> 'BOOKED' THEN
        RAISE EXCEPTION 'Only a booking that is not checked in yet is billed' USING ERRCODE = '55000';
    END IF;
    IF app.short_stay_payment_state(p_booking) <> 'NOT_BILLED' THEN
        RAISE EXCEPTION 'This booking is already billed or paid' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_price_lines AS line
               WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version
                 AND line.amount_usd_cents < 1) THEN
        RAISE EXCEPTION 'A price line without an amount cannot be billed' USING ERRCODE = '55000';
    END IF;
    SELECT unit.unit_number INTO v_unit FROM app.units AS unit WHERE unit.id = v_row.unit_id;
    SELECT jsonb_agg(jsonb_build_object('charge_id', gen_random_uuid(),
            'description', v_row.booking_number || ' · ' || v_unit || ' · '
                || line.quantity || CASE line.kind
                    WHEN 'WEEKS' THEN CASE WHEN line.quantity = 1 THEN ' week' ELSE ' weeks' END
                    WHEN 'NIGHTS' THEN CASE WHEN line.quantity = 1 THEN ' night' ELSE ' nights' END
                    ELSE (' ' || chr(215) || ' ') || lower(replace(line.kind, '_', ' ')) END
                || (' ' || chr(215) || ' ') || app.short_stay_dollars(line.unit_price_usd_cents)
                || CASE WHEN line.discount_basis_points > 0
                    THEN ' (' || (line.discount_basis_points / 100) || '% off)' ELSE '' END
                || ' · ' || to_char(v_row.check_in_on, 'DD/MM/YYYY') || ' to '
                || to_char(v_row.check_out_on, 'DD/MM/YYYY'),
            'quantity', 1, 'unit_price_usd_cents', line.amount_usd_cents)
            ORDER BY line.line_position)
        INTO v_items
    FROM app.short_stay_price_lines AS line
    WHERE line.booking_id = p_booking AND line.price_version = v_row.price_version;
    v_issued := app.short_stay_invoice(p_property, p_actor, v_row.customer_id,
        'Short stay ' || v_row.booking_number || ': full payment before check-in',
        'Short stay ' || v_row.booking_number, v_items, v_correlation);
    UPDATE app.short_stay_bookings AS booking
    SET invoice_id = (v_issued ->> 'invoice_id')::uuid, version = booking.version + 1
    WHERE booking.id = p_booking;
    PERFORM app.short_stay_event(p_booking, 'BILLED', p_actor, NULL,
        jsonb_build_object('invoice_id', v_issued ->> 'invoice_id',
            'invoice_number', v_issued ->> 'invoice_number',
            'total_usd_cents', v_row.total_usd_cents));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.billed',
        'short_stay_booking', p_booking, 'Short-stay Invoice issued', 'short_stays.desk', NULL,
        jsonb_build_object('invoice_id', v_issued ->> 'invoice_id'), v_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 1b. Paid on the booking site: no Invoice to the guest.
CREATE FUNCTION app.mark_short_stay_paid_on_site(p_property uuid, p_booking uuid,
    p_version integer, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
BEGIN
    IF v_row.source <> 'BOOKING_SITE' THEN
        RAISE EXCEPTION 'Only a booking-site booking is paid on the site' USING ERRCODE = '55000';
    END IF;
    IF v_row.status <> 'BOOKED' OR app.short_stay_payment_state(p_booking) <> 'NOT_BILLED' THEN
        RAISE EXCEPTION 'This booking is already billed or paid' USING ERRCODE = '55000';
    END IF;
    UPDATE app.short_stay_bookings AS booking
    SET paid_on_site = true, invoice_id = NULL, version = booking.version + 1
    WHERE booking.id = p_booking;
    PERFORM app.short_stay_event(p_booking, 'PAID_ON_SITE', p_actor, NULL,
        jsonb_build_object('site_name', v_row.site_name, 'site_reference', v_row.site_reference));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.paid_on_site',
        'short_stay_booking', p_booking, 'Paid on the booking site', 'short_stays.desk', NULL,
        jsonb_build_object('site_name', v_row.site_name), p_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 2. The deposit: cash, or a card hold with its reference (never the card number).
CREATE FUNCTION app.take_short_stay_deposit(p_property uuid, p_booking uuid, p_deposit jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
    v_kind text := p_deposit ->> 'kind';
    v_reference text := NULLIF(btrim(p_deposit ->> 'hold_reference'), '');
    v_last4 text := NULLIF(btrim(p_deposit ->> 'card_last4'), '');
    v_amount bigint;
BEGIN
    IF v_row.status NOT IN ('BOOKED', 'CHECKED_IN') THEN
        RAISE EXCEPTION 'The deposit is taken before or during the stay' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_deposits AS deposit WHERE deposit.booking_id = p_booking) THEN
        RAISE EXCEPTION 'This booking already has its deposit' USING ERRCODE = '55000';
    END IF;
    IF p_deposit IS NULL OR jsonb_typeof(p_deposit) <> 'object' OR v_kind IS NULL
        OR v_kind NOT IN ('CASH', 'CARD_HOLD')
        OR (v_kind = 'CARD_HOLD') <> (v_reference IS NOT NULL)
        OR (v_last4 IS NOT NULL AND (v_kind <> 'CARD_HOLD' OR v_last4 !~ '^[0-9]{4}$'))
        OR length(v_reference) > 60
        OR regexp_replace(COALESCE(v_reference, ''), '[^0-9]', '', 'g') ~ '[0-9]{12,}' THEN
        RAISE EXCEPTION 'The deposit is invalid: a card hold has its reference, never a card number'
            USING ERRCODE = '22023';
    END IF;
    v_amount := app.short_stay_rule(CASE v_kind WHEN 'CASH' THEN 'SS_CASH_DEPOSIT'
        ELSE 'SS_CARD_HOLD' END, v_today);
    INSERT INTO app.short_stay_deposits (booking_id, kind, amount_usd_cents, hold_reference,
        card_last4, taken_by)
    VALUES (p_booking, v_kind, v_amount, v_reference, v_last4, p_actor);
    PERFORM app.short_stay_event(p_booking, 'DEPOSIT_TAKEN', p_actor, NULL,
        jsonb_build_object('kind', v_kind, 'amount_usd_cents', v_amount));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.deposit_taken',
        'short_stay_booking', p_booking, 'Short-stay deposit taken', 'short_stays.desk', NULL,
        jsonb_build_object('kind', v_kind, 'amount_usd_cents', v_amount), p_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 3. Check-in: paid, deposit, ID, copy made, house rules signed, room ready.
CREATE FUNCTION app.check_in_short_stay(p_property uuid, p_booking uuid, p_check_in jsonb,
    p_version integer, p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
    v_unit app.units%ROWTYPE;
    v_missing text[] := '{}';
BEGIN
    IF v_row.status <> 'BOOKED' THEN
        RAISE EXCEPTION 'Only a booked guest checks in' USING ERRCODE = '55000';
    END IF;
    IF v_today < v_row.check_in_on OR v_today >= v_row.check_out_on THEN
        RAISE EXCEPTION 'A guest checks in from the check-in day, before the check-out day'
            USING ERRCODE = '55000';
    END IF;
    SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = v_row.unit_id FOR UPDATE;
    IF app.short_stay_payment_state(p_booking) NOT IN ('PAID', 'PAID_ON_SITE') THEN
        v_missing := array_append(v_missing, 'PAYMENT');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.short_stay_deposits AS deposit
                   WHERE deposit.booking_id = p_booking AND deposit.status = 'HELD') THEN
        v_missing := array_append(v_missing, 'DEPOSIT');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.customers AS customer
                   WHERE customer.id = v_row.customer_id
                     AND customer.id_document_number IS NOT NULL) THEN
        v_missing := array_append(v_missing, 'ID_NUMBER');
    END IF;
    IF p_check_in IS NULL OR jsonb_typeof(p_check_in) <> 'object'
        OR (p_check_in -> 'id_copy_made') IS DISTINCT FROM 'true'::jsonb THEN
        v_missing := array_append(v_missing, 'ID_COPY');
    END IF;
    IF p_check_in IS NULL OR jsonb_typeof(p_check_in) <> 'object'
        OR (p_check_in -> 'house_rules_signed') IS DISTINCT FROM 'true'::jsonb THEN
        v_missing := array_append(v_missing, 'HOUSE_RULES');
    END IF;
    IF v_unit.status <> 'VACANT' THEN
        v_missing := array_append(v_missing, 'ROOM_NOT_READY');
    END IF;
    IF cardinality(v_missing) > 0 THEN
        RAISE EXCEPTION 'The guest cannot check in yet: %', array_to_string(v_missing, ', ')
            USING ERRCODE = '55000';
    END IF;
    UPDATE app.short_stay_bookings AS booking
    SET status = 'CHECKED_IN', checked_in_at = statement_timestamp(), checked_in_by = p_actor,
        id_copy_made = true, house_rules_signed = true, version = booking.version + 1
    WHERE booking.id = p_booking;
    UPDATE app.units AS unit
    SET status = 'SHORT_STAY', version = unit.version + 1, updated_at = statement_timestamp(),
        updated_by = p_actor
    WHERE unit.id = v_row.unit_id;
    PERFORM app.short_stay_event(p_booking, 'CHECKED_IN', p_actor, NULL, '{}'::jsonb);
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.checked_in',
        'short_stay_booking', p_booking, 'Short-stay guest checked in', 'short_stays.desk',
        jsonb_build_object('unit_status', v_unit.status),
        jsonb_build_object('unit_status', 'SHORT_STAY'), p_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 4. Check-out: the Unit is Cleaning and the room check is due today.
CREATE FUNCTION app.check_out_short_stay(p_property uuid, p_booking uuid, p_version integer,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, p_version);
BEGIN
    IF v_row.status <> 'CHECKED_IN' THEN
        RAISE EXCEPTION 'Only a guest who is in checks out' USING ERRCODE = '55000';
    END IF;
    UPDATE app.short_stay_bookings AS booking
    SET status = 'CHECKED_OUT', checked_out_at = statement_timestamp(), checked_out_by = p_actor,
        version = booking.version + 1
    WHERE booking.id = p_booking;
    UPDATE app.units AS unit
    SET status = 'CLEANING', version = unit.version + 1, updated_at = statement_timestamp(),
        updated_by = p_actor
    WHERE unit.id = v_row.unit_id AND unit.status = 'SHORT_STAY';
    INSERT INTO app.housekeeping_tasks (property_id, unit_id, booking_id, task_on, kind, created_by)
    VALUES (p_property, v_row.unit_id, p_booking, v_today, 'ROOM_CHECK', p_actor);
    PERFORM app.short_stay_event(p_booking, 'CHECKED_OUT', p_actor, NULL,
        jsonb_build_object('early', v_today < v_row.check_out_on));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.checked_out',
        'short_stay_booking', p_booking, 'Short-stay guest checked out', 'short_stays.desk',
        jsonb_build_object('unit_status', 'SHORT_STAY'),
        jsonb_build_object('unit_status', 'CLEANING'), p_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 5. The room check after check-out, with any damage found; the Unit is Vacant again.
CREATE FUNCTION app.check_short_stay_room(p_property uuid, p_booking uuid, p_check jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.housekeeping', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
    v_task app.housekeeping_tasks%ROWTYPE;
    v_note text := NULLIF(btrim(p_check ->> 'note'), '');
    v_damage text := NULLIF(btrim(p_check ->> 'damage'), '');
    v_cost bigint;
BEGIN
    IF p_check IS NULL OR jsonb_typeof(p_check) <> 'object' THEN
        RAISE EXCEPTION 'The room check is invalid' USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_cost := (p_check ->> 'damage_usd_cents')::bigint;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The damage cost is invalid' USING ERRCODE = '22023';
    END;
    IF (v_damage IS NULL) <> (v_cost IS NULL) OR v_cost <= 0 OR v_cost > 100000000
        OR length(v_damage) > 500 OR length(v_note) > 500 THEN
        RAISE EXCEPTION 'Damage has what was damaged and its cost' USING ERRCODE = '22023';
    END IF;
    SELECT task.* INTO v_task FROM app.housekeeping_tasks AS task
    WHERE task.booking_id = p_booking AND task.kind = 'ROOM_CHECK' AND task.status = 'TO_DO'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No room check is due for this booking' USING ERRCODE = '55000';
    END IF;
    UPDATE app.housekeeping_tasks AS task
    SET status = 'DONE', note = v_note, done_at = statement_timestamp(), done_by = p_actor,
        version = task.version + 1
    WHERE task.id = v_task.id;
    IF v_damage IS NOT NULL THEN
        INSERT INTO app.short_stay_damages (booking_id, description, amount_usd_cents, asked_by)
        VALUES (p_booking, v_damage, v_cost, p_actor);
    END IF;
    UPDATE app.units AS unit
    SET status = 'VACANT', version = unit.version + 1, updated_at = statement_timestamp(),
        updated_by = p_actor
    WHERE unit.id = v_row.unit_id AND unit.status = 'CLEANING';
    PERFORM app.short_stay_event(p_booking, 'ROOM_CHECKED', p_actor, v_note,
        CASE WHEN v_damage IS NULL THEN '{}'::jsonb
            ELSE jsonb_build_object('damage', v_damage, 'damage_usd_cents', v_cost) END);
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.room_checked',
        'short_stay_booking', p_booking, 'Room checked after check-out', 'short_stays.housekeeping',
        NULL, jsonb_build_object('damage_usd_cents', v_cost), p_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 6. The Manager decides on damage: approved damage is taken from the deposit first and the
-- rest is an Invoice for the guest.
CREATE FUNCTION app.decide_short_stay_damage(p_property uuid, p_damage uuid, p_decision jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.approve', p_property);
    v_damage app.short_stay_damages%ROWTYPE;
    v_row app.short_stay_bookings%ROWTYPE;
    v_approve boolean;
    v_note text := NULLIF(btrim(p_decision ->> 'note'), '');
    v_left bigint := 0;
    v_from bigint := 0;
    v_issued jsonb;
    v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
BEGIN
    IF p_decision IS NULL OR jsonb_typeof(p_decision) <> 'object'
        OR jsonb_typeof(p_decision -> 'approve') IS DISTINCT FROM 'boolean'
        OR length(v_note) > 500 THEN
        RAISE EXCEPTION 'The decision is invalid' USING ERRCODE = '22023';
    END IF;
    v_approve := (p_decision ->> 'approve')::boolean;
    IF NOT v_approve AND v_note IS NULL THEN
        RAISE EXCEPTION 'A refused damage charge says why' USING ERRCODE = '22023';
    END IF;
    SELECT damage.* INTO v_damage FROM app.short_stay_damages AS damage
    JOIN app.short_stay_bookings AS booking ON booking.id = damage.booking_id
    WHERE damage.id = p_damage AND booking.property_id = p_property;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the damage does not exist' USING ERRCODE = '22023';
    END IF;
    v_row := app.short_stay_locked(p_property, v_damage.booking_id, NULL);
    SELECT damage.* INTO v_damage FROM app.short_stay_damages AS damage
    WHERE damage.id = p_damage FOR UPDATE;
    IF v_damage.status <> 'WAITING' THEN
        RAISE EXCEPTION 'This damage is already decided' USING ERRCODE = '55000';
    END IF;
    IF v_approve THEN
        SELECT deposit.amount_usd_cents - COALESCE((
                SELECT sum(other.from_deposit_usd_cents) FROM app.short_stay_damages AS other
                WHERE other.booking_id = v_row.id AND other.status = 'APPROVED'), 0)
            INTO v_left
        FROM app.short_stay_deposits AS deposit
        WHERE deposit.booking_id = v_row.id AND deposit.status = 'HELD';
        v_from := LEAST(COALESCE(v_left, 0), v_damage.amount_usd_cents);
        IF v_from < v_damage.amount_usd_cents THEN
            v_issued := app.short_stay_invoice(p_property, p_actor, v_row.customer_id,
                'Damage approved for short stay ' || v_row.booking_number,
                'Short stay ' || v_row.booking_number,
                jsonb_build_array(jsonb_build_object('charge_id', gen_random_uuid(),
                    'description', 'Damage · ' || v_row.booking_number || ' · '
                        || v_damage.description
                        || CASE WHEN v_from > 0 THEN ' (after '
                            || app.short_stay_dollars(v_from) || ' from the deposit)' ELSE '' END,
                    'quantity', 1,
                    'unit_price_usd_cents', v_damage.amount_usd_cents - v_from)),
                v_correlation);
        END IF;
    END IF;
    UPDATE app.short_stay_damages AS damage
    SET status = CASE WHEN v_approve THEN 'APPROVED' ELSE 'REFUSED' END,
        decided_at = statement_timestamp(), decided_by = p_actor, decision_note = v_note,
        from_deposit_usd_cents = v_from, invoice_id = (v_issued ->> 'invoice_id')::uuid,
        version = damage.version + 1
    WHERE damage.id = p_damage;
    PERFORM app.short_stay_event(v_row.id,
        CASE WHEN v_approve THEN 'DAMAGE_APPROVED' ELSE 'DAMAGE_REFUSED' END, p_actor, v_note,
        jsonb_build_object('amount_usd_cents', v_damage.amount_usd_cents,
            'from_deposit_usd_cents', v_from, 'invoice_number', v_issued ->> 'invoice_number'));
    PERFORM app.product_audit(p_property, p_actor, v_today,
        CASE WHEN v_approve THEN 'short_stay.damage_approved' ELSE 'short_stay.damage_refused' END,
        'short_stay_damage', p_damage, COALESCE(v_note, 'Damage charge approved'),
        'short_stays.approve', jsonb_build_object('status', 'WAITING'),
        jsonb_build_object('from_deposit_usd_cents', v_from,
            'invoice_id', v_issued ->> 'invoice_id'), v_correlation);
    RETURN app.short_stay_booking_json(v_row.id);
END $$;

-- 7. The deposit ends after the room check, once no damage waits: Returned, or Kept with what
-- the approved damage took from it.
CREATE FUNCTION app.end_short_stay_deposit(p_property uuid, p_booking uuid, p_actor uuid,
    p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
    v_deposit app.short_stay_deposits%ROWTYPE;
    v_kept bigint;
BEGIN
    SELECT deposit.* INTO v_deposit FROM app.short_stay_deposits AS deposit
    WHERE deposit.booking_id = p_booking FOR UPDATE;
    IF NOT FOUND OR v_deposit.status <> 'HELD' THEN
        RAISE EXCEPTION 'This booking holds no deposit' USING ERRCODE = '55000';
    END IF;
    IF v_row.status <> 'CHECKED_OUT' OR EXISTS (
        SELECT 1 FROM app.housekeeping_tasks AS task
        WHERE task.booking_id = p_booking AND task.kind = 'ROOM_CHECK' AND task.status = 'TO_DO') THEN
        RAISE EXCEPTION 'The deposit ends after check-out and the room check' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_damages AS damage
               WHERE damage.booking_id = p_booking AND damage.status = 'WAITING') THEN
        RAISE EXCEPTION 'Damage waits for the Manager; the deposit waits too' USING ERRCODE = '55000';
    END IF;
    SELECT COALESCE(sum(damage.from_deposit_usd_cents), 0) INTO v_kept
    FROM app.short_stay_damages AS damage
    WHERE damage.booking_id = p_booking AND damage.status = 'APPROVED';
    UPDATE app.short_stay_deposits AS deposit
    SET status = CASE WHEN v_kept > 0 THEN 'KEPT' ELSE 'RETURNED' END, kept_usd_cents = v_kept,
        ended_at = statement_timestamp(), ended_by = p_actor,
        end_note = CASE WHEN v_kept > 0 THEN 'Kept for approved damage' ELSE NULL END,
        version = deposit.version + 1
    WHERE deposit.id = v_deposit.id;
    PERFORM app.short_stay_event(p_booking,
        CASE WHEN v_kept > 0 THEN 'DEPOSIT_KEPT' ELSE 'DEPOSIT_RETURNED' END, p_actor, NULL,
        jsonb_build_object('kept_usd_cents', v_kept,
            'returned_usd_cents', v_deposit.amount_usd_cents - v_kept));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.deposit_ended',
        'short_stay_booking', p_booking, 'Short-stay deposit ended', 'short_stays.desk',
        jsonb_build_object('status', 'HELD'),
        jsonb_build_object('kept_usd_cents', v_kept), p_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;
"""

ACTIONS = (
    "app.bill_short_stay(uuid, uuid, integer, uuid, uuid)",
    "app.mark_short_stay_paid_on_site(uuid, uuid, integer, uuid, uuid)",
    "app.take_short_stay_deposit(uuid, uuid, jsonb, uuid, uuid)",
    "app.check_in_short_stay(uuid, uuid, jsonb, integer, uuid, uuid)",
    "app.check_out_short_stay(uuid, uuid, integer, uuid, uuid)",
    "app.check_short_stay_room(uuid, uuid, jsonb, uuid, uuid)",
    "app.decide_short_stay_damage(uuid, uuid, jsonb, uuid, uuid)",
    "app.end_short_stay_deposit(uuid, uuid, uuid, uuid)",
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
    raise RuntimeError("Short stays step 3 migration is forward-only")
