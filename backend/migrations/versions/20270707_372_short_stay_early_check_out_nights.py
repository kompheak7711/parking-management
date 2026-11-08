# ruff: noqa: E501
"""Database review fixes of 7 Nov 2026, DL-202 (D): after an early check-out the week report counts the Unit's nights only up to the day the guest left.

Owner rule of 7 Nov 2026 13:58 (answer 1): "count unused nights as empty from the day the guest
left. Money stays as DL-200." The review found that ``short_stay_week_report`` counted a stay's
nights to the booked check-out day, so a night sold again after an early check-out counted twice
and the occupancy was too high.

The function is replaced with one change: a stay that is CHECKED_OUT stops counting nights on the
Property's day of ``checked_out_at`` (never after the booked check-out day, never below 0). The
money of the stay is still shared over its booked nights, so the week that holds those nights
keeps the whole amount (DL-200: the unused nights stay paid). Nothing else in the report changes;
the calendar still shows the booking to its booked check-out day.

Forward-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270707_372"
down_revision: str | None = "20270706_371"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = r"""
-- The weekly report: 7 days from p_from (Owner and Manager).
CREATE OR REPLACE FUNCTION app.short_stay_week_report(p_property uuid, p_from date, p_actor uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.approve', p_property);
    v_to date := p_from + 7;
    v_change bigint;
    v_linen bigint;
    v_units jsonb;
    v_totals jsonb;
BEGIN
    IF p_from IS NULL OR p_from > v_today THEN
        RAISE EXCEPTION 'A report is for a week that has started' USING ERRCODE = '22023';
    END IF;
    v_change := COALESCE(app.short_stay_rule('SS_CHANGE_OVER_COST', p_from), 0);
    v_linen := COALESCE(app.short_stay_rule('SS_LINEN_COST', p_from), 0);
    WITH stays AS (
        -- Each counted stay with its nights in the week and its money shared by night. After an
        -- early check-out the nights stop on the day the guest left (DL-202 (D)); the money is
        -- still shared by the booked nights, because the unused nights stay paid (DL-200).
        SELECT booking.unit_id, booking.id,
            GREATEST(0, LEAST(booking.check_out_on, v_to,
                    CASE WHEN booking.status = 'CHECKED_OUT'
                        THEN app.short_stay_local_day(p_property, booking.checked_out_at) END)
                - GREATEST(booking.check_in_on, p_from)) AS nights,
            booking.total_usd_cents * (LEAST(booking.check_out_on, v_to)
                - GREATEST(booking.check_in_on, p_from)) / booking.nights AS income,
            app.short_stay_site_fee(booking.source, booking.site_name, booking.check_in_on)
                AS fee_points
        FROM app.short_stay_bookings AS booking
        WHERE booking.property_id = p_property
          AND booking.check_in_on < v_to AND booking.check_out_on > p_from
          AND (booking.status IN ('CHECKED_IN', 'CHECKED_OUT')
               OR (booking.status = 'BOOKED'
                   AND app.short_stay_payment_state(booking.id) IN ('PAID', 'PAID_ON_SITE')))
    ), kept AS (
        SELECT booking.unit_id, cancel.kept_usd_cents AS income,
            app.short_stay_site_fee(booking.source, booking.site_name, booking.check_in_on)
                AS fee_points
        FROM app.short_stay_cancellations AS cancel
        JOIN app.short_stay_bookings AS booking ON booking.id = cancel.booking_id
        WHERE booking.property_id = p_property AND cancel.kept_usd_cents > 0
          AND app.short_stay_local_day(p_property, cancel.created_at) >= p_from
          AND app.short_stay_local_day(p_property, cancel.created_at) < v_to
    ), money AS (
        SELECT unit_id, sum(nights)::bigint AS nights, sum(income)::bigint AS income,
            sum(income * fee_points / 10000)::bigint AS site_fees
        FROM (SELECT unit_id, nights, income, fee_points FROM stays
              UNION ALL SELECT unit_id, 0, income, fee_points FROM kept) AS counted
        GROUP BY unit_id
    ), cleaning AS (
        SELECT task.unit_id, sum(CASE
                -- A check-out makes the room check; the change-over clean goes with it.
                WHEN task.kind IN ('ROOM_CHECK', 'CHANGE_OVER') AND task.status <> 'SKIPPED'
                    THEN v_change + v_linen
                WHEN task.kind = 'DAILY_CLEAN' AND task.status = 'DONE' THEN v_linen
                ELSE 0 END)::bigint AS cost
        FROM app.housekeeping_tasks AS task
        WHERE task.property_id = p_property AND task.task_on >= p_from AND task.task_on < v_to
        GROUP BY task.unit_id
    ), rows AS (
        SELECT unit.id, unit.unit_number, COALESCE(money.nights, 0) AS nights,
            COALESCE(money.income, 0) AS income, COALESCE(money.site_fees, 0) AS site_fees,
            COALESCE(cleaning.cost, 0) AS cleaning
        FROM app.units AS unit
        LEFT JOIN money ON money.unit_id = unit.id
        LEFT JOIN cleaning ON cleaning.unit_id = unit.id
        WHERE unit.property_id = p_property
          AND ((unit.for_rent AND unit.status IN ('VACANT', 'SHORT_STAY', 'CLEANING'))
               OR money.unit_id IS NOT NULL OR cleaning.unit_id IS NOT NULL)
    )
    SELECT COALESCE(jsonb_agg(jsonb_build_object('unit_id', rows.id,
                'unit_number', rows.unit_number, 'nights', rows.nights,
                'income_usd_cents', rows.income, 'site_fees_usd_cents', rows.site_fees,
                'cleaning_usd_cents', rows.cleaning,
                'net_usd_cents', rows.income - rows.site_fees - rows.cleaning)
            ORDER BY rows.unit_number), '[]'::jsonb),
        jsonb_build_object('units', count(*), 'unit_nights', count(*) * 7,
            'nights', COALESCE(sum(rows.nights), 0)::bigint,
            'income_usd_cents', COALESCE(sum(rows.income), 0),
            'site_fees_usd_cents', COALESCE(sum(rows.site_fees), 0),
            'cleaning_usd_cents', COALESCE(sum(rows.cleaning), 0),
            'net_usd_cents', COALESCE(sum(rows.income - rows.site_fees - rows.cleaning), 0),
            -- Basis points: 4250 = 42.50%.
            'occupancy_points', CASE WHEN count(*) = 0 THEN 0
                ELSE COALESCE(sum(rows.nights), 0)::bigint * 10000 / (count(*) * 7) END)
        INTO v_units, v_totals
    FROM rows;
    RETURN jsonb_build_object('from', p_from, 'to', v_to - 1, 'today', v_today,
        'so_far', v_today < v_to - 1,
        'base_occupancy_points', COALESCE(app.short_stay_rule('SS_BASE_OCCUPANCY', p_from), 0),
        'change_over_usd_cents', v_change, 'linen_usd_cents', v_linen,
        'units', v_units, 'totals', v_totals,
        'leases', COALESCE((SELECT jsonb_agg(jsonb_build_object('booking_id', booking.id,
                'booking_number', booking.booking_number, 'guest_name', customer.legal_name,
                'lease_id', offer.lease_id, 'lease_unit_number', unit.unit_number,
                'off_usd_cents', offer.off_usd_cents, 'linked_at', offer.created_at)
                ORDER BY offer.created_at)
            FROM app.short_stay_lease_offers AS offer
            JOIN app.short_stay_bookings AS booking ON booking.id = offer.booking_id
            JOIN app.customers AS customer ON customer.id = booking.customer_id
            JOIN app.leases AS lease ON lease.id = offer.lease_id
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE booking.property_id = p_property
              AND app.short_stay_local_day(p_property, offer.created_at) >= p_from
              AND app.short_stay_local_day(p_property, offer.created_at) < v_to), '[]'::jsonb),
        'damages', COALESCE((SELECT jsonb_agg(jsonb_build_object('damage_id', damage.id,
                'booking_id', booking.id, 'booking_number', booking.booking_number,
                'unit_number', unit.unit_number, 'description', damage.description,
                'amount_usd_cents', damage.amount_usd_cents, 'status', damage.status)
                ORDER BY damage.asked_at)
            FROM app.short_stay_damages AS damage
            JOIN app.short_stay_bookings AS booking ON booking.id = damage.booking_id
            JOIN app.units AS unit ON unit.id = booking.unit_id
            WHERE booking.property_id = p_property
              AND app.short_stay_local_day(p_property, damage.asked_at) >= p_from
              AND app.short_stay_local_day(p_property, damage.asked_at) < v_to), '[]'::jsonb),
        'complaints', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                'complaint_id', complaint.id, 'noted_on', complaint.noted_on,
                'unit_number', unit.unit_number, 'what', complaint.what)
                ORDER BY complaint.noted_on, complaint.created_at)
            FROM app.short_stay_complaints AS complaint
            LEFT JOIN app.units AS unit ON unit.id = complaint.unit_id
            WHERE complaint.property_id = p_property
              AND complaint.noted_on >= p_from AND complaint.noted_on < v_to), '[]'::jsonb),
        'sources', COALESCE((SELECT jsonb_agg(jsonb_build_object('source', counted.source,
                'site_name', counted.site_name, 'stays', counted.stays)
                ORDER BY counted.stays DESC, counted.source, counted.site_name)
            FROM (SELECT booking.source, booking.site_name, count(*) AS stays
                  FROM app.short_stay_bookings AS booking
                  WHERE booking.property_id = p_property
                    AND booking.check_in_on < v_to AND booking.check_out_on > p_from
                    AND (booking.status IN ('CHECKED_IN', 'CHECKED_OUT')
                         OR (booking.status = 'BOOKED' AND app.short_stay_payment_state(booking.id)
                             IN ('PAID', 'PAID_ON_SITE')))
                  GROUP BY booking.source, booking.site_name) AS counted), '[]'::jsonb),
        'cancellations', (SELECT jsonb_build_object('count', count(*),
                'kept_usd_cents', COALESCE(sum(cancel.kept_usd_cents), 0))
            FROM app.short_stay_cancellations AS cancel
            JOIN app.short_stay_bookings AS booking ON booking.id = cancel.booking_id
            WHERE booking.property_id = p_property
              AND app.short_stay_local_day(p_property, cancel.created_at) >= p_from
              AND app.short_stay_local_day(p_property, cancel.created_at) < v_to));
END $$;
"""


def upgrade() -> None:
    op.execute(FUNCTION)


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
