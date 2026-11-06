# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 5c: the weekly report and tenant complaints.

The PRD "How we judge the test" (owner 03/11/2026): occupancy (the share of unit-nights that are
paid), income per unit each week after cleaning, laundry and booking-site costs, the guests who
signed a monthly Lease, and damage and complaints from monthly tenants, compared with the 40%
occupancy before the test. The booking-site fees and the cleaning costs are used only by this
report. Site fees start at 0% (owner 05/11: no site is connected yet); the owner sets them in Settings.

Readings by Claude (owner rule 2026-10-23 22:30, non-money): a week is 7 days from the day asked
for (the screen asks for Mondays); the Units in the report are the Units for rent that are empty,
in a short stay or being cleaned now, plus any Unit with a short-stay night that week; a night is
counted when the stay is paid, paid on the site, checked in or checked out; a stay's money is
shared evenly by its nights; money kept after a late cancel counts in the week of the cancel.
Cleaning is the change-over cost plus linen for each check-out (its room check, not skipped), and
linen for each daily clean done. Also: a quote shows the 1-month-only price and the monthly rent next to
the stay (PRD "night, week and month prices side by side").

Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270608_318"
down_revision: str | None = "20270607_317"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RANGE = "app.business_rules_program_range()"
RANGE_BEFORE = "OR (v_code = 'TR_AUTO_CLOSE_DAYS' AND NEW.value NOT BETWEEN 1 AND 30)"
SEED_REASON = "Starts at 0%: the owner sets each site share when the site is connected"

# code, unit, value, lowest, highest, English, Khmer
RULES = (
    (
        "SS_SITE_FEE_BOOKING_COM",
        "PERCENT",
        0,
        0,
        5000,
        "Report only: Booking.com share of each booking",
        "សម្រាប់របាយការណ៍៖ ចំណែករបស់ Booking.com លើការកក់នីមួយៗ",
    ),
    (
        "SS_SITE_FEE_AGODA",
        "PERCENT",
        0,
        0,
        5000,
        "Report only: Agoda share of each booking",
        "សម្រាប់របាយការណ៍៖ ចំណែករបស់ Agoda លើការកក់នីមួយៗ",
    ),
    (
        "SS_SITE_FEE_AIRBNB",
        "PERCENT",
        0,
        0,
        5000,
        "Report only: Airbnb share of each booking",
        "សម្រាប់របាយការណ៍៖ ចំណែករបស់ Airbnb លើការកក់នីមួយៗ",
    ),
    (
        "SS_BASE_OCCUPANCY",
        "PERCENT",
        4000,
        0,
        10000,
        "Report only: occupancy before the short-stay test",
        "សម្រាប់របាយការណ៍៖ អត្រាមានអ្នកស្នាក់មុនការសាកល្បងស្នាក់នៅខ្លី",
    ),
)
USED = ("SS_CHANGE_OVER_COST", "SS_LINEN_COST")

SCHEMA = r"""
-- Complaints from monthly tenants about short-stay guests (noise, visitors): the test's last measure.
CREATE TABLE app.short_stay_complaints (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
    unit_id uuid REFERENCES app.units (id) ON DELETE RESTRICT,
    noted_on date NOT NULL,
    what text NOT NULL CHECK (what = btrim(what) AND length(what) BETWEEN 1 AND 500),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
);
CREATE INDEX short_stay_complaints_property_idx ON app.short_stay_complaints (property_id, noted_on);
CREATE TRIGGER short_stay_complaints_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_complaints FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_complaints_truncate BEFORE TRUNCATE ON app.short_stay_complaints
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate();
REVOKE ALL ON TABLE app.short_stay_complaints FROM PUBLIC, prm_runtime, prm_bootstrap;
GRANT SELECT ON TABLE app.short_stay_complaints TO prm_runtime;

ALTER FUNCTION app.short_stay_quote_json(uuid) RENAME TO short_stay_quote_main_json;
"""

FUNCTIONS = r"""
-- A quote with the month prices next to the stay.
CREATE FUNCTION app.short_stay_quote_json(p_quote uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT app.short_stay_quote_main_json(quote.id) || jsonb_build_object(
        'month_only_usd_cents', app.short_stay_month_only(quote.unit_type, quote.check_in_on),
        'monthly_rent_usd_cents', unit.default_monthly_rent_usd_cents)
    FROM app.short_stay_quotes AS quote
    LEFT JOIN app.units AS unit ON unit.id = quote.unit_id
    WHERE quote.id = p_quote
$$;
REVOKE ALL ON FUNCTION app.short_stay_quote_json(uuid) FROM PUBLIC;

-- A booking site's share of a booking (report only); 0 for a direct booking.
CREATE FUNCTION app.short_stay_site_fee(p_source text, p_site text, p_on date) RETURNS bigint
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN p_source <> 'BOOKING_SITE' THEN 0
        ELSE COALESCE(app.business_rule_value(CASE lower(p_site)
            WHEN 'booking.com' THEN 'SS_SITE_FEE_BOOKING_COM'
            WHEN 'agoda' THEN 'SS_SITE_FEE_AGODA'
            WHEN 'airbnb' THEN 'SS_SITE_FEE_AIRBNB' END, p_on), 0) END
$$;
REVOKE ALL ON FUNCTION app.short_stay_site_fee(text, text, date) FROM PUBLIC;

-- A tenant's complaint about short-stay guests (the front desk, the Owner or the Manager).
CREATE FUNCTION app.record_short_stay_complaint(p_property uuid, p_complaint jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_unit uuid;
    v_on date;
    v_what text := NULLIF(btrim(p_complaint ->> 'what'), '');
    v_id uuid;
BEGIN
    BEGIN
        v_unit := (p_complaint ->> 'unit_id')::uuid;
        v_on := COALESCE((p_complaint ->> 'noted_on')::date, v_today);
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The complaint is invalid' USING ERRCODE = '22023';
    END;
    IF v_what IS NULL OR length(v_what) > 500 THEN
        RAISE EXCEPTION 'Write what happened (up to 500 letters)' USING ERRCODE = '22023';
    END IF;
    IF v_on > v_today THEN
        RAISE EXCEPTION 'A complaint is about a day that has come' USING ERRCODE = '22023';
    END IF;
    IF v_unit IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.units AS unit
            WHERE unit.id = v_unit AND unit.property_id = p_property) THEN
        RAISE EXCEPTION 'the Unit does not exist' USING ERRCODE = '22023';
    END IF;
    INSERT INTO app.short_stay_complaints (property_id, unit_id, noted_on, what, created_by)
    VALUES (p_property, v_unit, v_on, v_what, p_actor)
    RETURNING id INTO v_id;
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.complaint',
        'short_stay_complaint', v_id, 'Tenant complaint about short stays', 'short_stays.desk',
        NULL, jsonb_build_object('unit_id', v_unit, 'noted_on', v_on),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN jsonb_build_object('complaint_id', v_id, 'unit_id', v_unit, 'noted_on', v_on,
        'what', v_what);
END $$;

-- The weekly report: 7 days from p_from (Owner and Manager).
CREATE FUNCTION app.short_stay_week_report(p_property uuid, p_from date, p_actor uuid)
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
        -- Each counted stay with its nights in the week and its money shared by night.
        SELECT booking.unit_id, booking.id,
            (LEAST(booking.check_out_on, v_to) - GREATEST(booking.check_in_on, p_from)) AS nights,
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

HELPER = r"""
-- The Property's day of a moment (Phnom Penh).
CREATE FUNCTION app.short_stay_local_day(p_property uuid, p_at timestamptz) RETURNS date
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT timezone(property.timezone_name, p_at)::date FROM app.properties AS property
    WHERE property.id = p_property
$$;
REVOKE ALL ON FUNCTION app.short_stay_local_day(uuid, timestamptz) FROM PUBLIC;
"""

GRANTS = (
    "app.record_short_stay_complaint(uuid, jsonb, uuid, uuid)",
    "app.short_stay_week_report(uuid, date, uuid)",
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
    op.execute(HELPER)
    op.execute(FUNCTIONS)
    for signature in GRANTS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    ranges = "".join(
        f"\n                OR (v_code = {_text(code)} AND NEW.value NOT BETWEEN {low} AND {high})"
        for code, _unit, _value, low, high, _en, _kh in RULES
    )
    _patch(RANGE, ((RANGE_BEFORE, RANGE_BEFORE + ranges),))
    for code, unit, value, _low, _high, en, kh in RULES:
        op.execute(
            f"""
            WITH named AS (
                INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area,
                    used_by_app)
                VALUES ({_text(code)}, {_text(en)}, {_text(kh)}, {_text(unit)}, 'SHORT_STAYS', true)
                RETURNING id
            )
            INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by)
            SELECT named.id, {value}, DATE '2026-01-01', {_text(SEED_REASON)},
                (SELECT classification.actor_id FROM app.user_account_classes AS classification
                 WHERE classification.account_class = 'owner')
            FROM named
            """
        )
    codes = ", ".join(_text(code) for code in USED)
    op.execute(f"UPDATE app.business_rule_names SET used_by_app = true WHERE code IN ({codes})")


def downgrade() -> None:
    raise RuntimeError("Short stays step 5c migration is forward-only")
