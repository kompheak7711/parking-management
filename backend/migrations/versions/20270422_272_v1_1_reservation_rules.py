# ruff: noqa: E501
"""V1.1 step 2b (owner 2026-11-03 "Continue your task"): Reservations read their business rules.

The plan of 01/11/2026 says the business rules are read by the app. Migration 271 seeded the
Reservation rules with the values the app used before (21 days, one extension of at most 14
days, a suggested deposit of 20% of the monthly Rent). This migration makes the app read them.
Technical choices by Claude under the owner's 2026-10-23 22:30 rule.

1. ``app.reservation_rule(code, on)`` gives the rule in force on a day, else the earlier value.
   ``app.reservation_deposit_suggestion(rent, on)`` gives the suggested deposit, rounded half up
   to the cent (20% gives exactly the earlier ``(rent + 2) / 5``).
2. A Reservation may last at most RESERVATION_DAYS from its Reservation Date (the rule on the
   Reservation Date). The fixed 21-day check becomes a trigger that reads the rule; a Reservation
   still never ends before it starts.
3. One extension adds at most RESERVATION_EXTENSION_DAYS (the rule on the day it is approved).
   When an extension may be asked (the last 14 days) is not a business rule and stays.
4. The deposit suggestion and its recorded rate follow RESERVATION_DEPOSIT_PERCENT on the
   Reservation Date. It stays a suggestion: an amount below it still needs the override.
5. The three rules are marked as used by the app and keep a safe range (1 to 90 days; 0.01% to
   100%). Rows already saved are unchanged.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270422_272"
down_revision: str | None = "20270421_271"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_RESERVATION = (
    "app.create_reservation(uuid,uuid,text,uuid,uuid,uuid,date,bigint,date,uuid,bigint,text,"
    "timestamp with time zone,text,text,jsonb,uuid,bigint,uuid,uuid,timestamp with time zone,uuid)"
)
SUGGESTION_BEFORE = "v_suggestion := (p_agreed_monthly_rent_usd_cents + 2) / 5;"
SUGGESTION_AFTER = (
    "v_suggestion := app.reservation_deposit_suggestion(p_agreed_monthly_rent_usd_cents,\n"
    "                p_reservation_date);"
)
RATE_BEFORE = "p_acceptance_id, p_reservation_id, 2000, v_suggestion,"
RATE_AFTER = (
    "p_acceptance_id, p_reservation_id,\n"
    "                app.reservation_rule('RESERVATION_DEPOSIT_PERCENT', p_reservation_date),\n"
    "                v_suggestion,"
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"{signature} does not have the expected text")
        definition = definition.replace(before, after)
    op.execute(text(definition))


def upgrade() -> None:
    op.execute(
        """
        -- 1. The rules, with the earlier values when no rule is in force.
        CREATE FUNCTION app.reservation_rule(p_code text, p_on date)
        RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT coalesce(app.business_rule_value(p_code, p_on),
                CASE p_code
                    WHEN 'RESERVATION_DAYS' THEN 21
                    WHEN 'RESERVATION_EXTENSION_DAYS' THEN 14
                    WHEN 'RESERVATION_DEPOSIT_PERCENT' THEN 2000
                END)::integer
            WHERE p_code IN ('RESERVATION_DAYS', 'RESERVATION_EXTENSION_DAYS',
                'RESERVATION_DEPOSIT_PERCENT')
        $$;
        REVOKE ALL ON FUNCTION app.reservation_rule(text, date) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.reservation_rule(text, date) TO prm_runtime;

        CREATE FUNCTION app.reservation_deposit_suggestion(p_rent bigint, p_on date)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT floor((p_rent::numeric
                * app.reservation_rule('RESERVATION_DEPOSIT_PERCENT', p_on) + 5000) / 10000)::bigint
        $$;
        REVOKE ALL ON FUNCTION app.reservation_deposit_suggestion(bigint, date) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.reservation_deposit_suggestion(bigint, date) TO prm_runtime;

        -- 2. How long a Reservation may last.
        ALTER TABLE app.reservations DROP CONSTRAINT reservations_initial_period_valid;
        ALTER TABLE app.reservations ADD CONSTRAINT reservations_initial_period_forward
            CHECK (original_expiration_date >= reservation_date);
        CREATE FUNCTION app.reservation_period_within_rule() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NEW.original_expiration_date > NEW.reservation_date
                + app.reservation_rule('RESERVATION_DAYS', NEW.reservation_date) THEN
                RAISE EXCEPTION 'The Reservation lasts longer than the business rule allows'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.reservation_period_within_rule() FROM PUBLIC;
        CREATE TRIGGER reservations_period_within_rule
            BEFORE INSERT OR UPDATE OF reservation_date, original_expiration_date
            ON app.reservations
            FOR EACH ROW EXECUTE FUNCTION app.reservation_period_within_rule();

        -- 3. How far one extension may go.
        ALTER TABLE app.reservation_extension_notices
            DROP CONSTRAINT reservation_extension_forward_and_bounded;
        ALTER TABLE app.reservation_extension_notices ADD CONSTRAINT reservation_extension_forward
            CHECK (new_expiration_date > previous_expiration_date);
        CREATE FUNCTION app.reservation_extension_within_rule() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.reservations AS reservation
            JOIN app.units AS unit ON unit.id = reservation.unit_id
            JOIN app.properties AS property ON property.id = unit.property_id
            WHERE reservation.id = NEW.reservation_id;
            IF NEW.new_expiration_date > NEW.previous_expiration_date
                + app.reservation_rule('RESERVATION_EXTENSION_DAYS',
                    timezone(v_timezone, NEW.approved_at)::date) THEN
                RAISE EXCEPTION 'The extension is longer than the business rule allows'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION app.reservation_extension_within_rule() FROM PUBLIC;
        CREATE TRIGGER reservation_extension_notices_within_rule
            BEFORE INSERT ON app.reservation_extension_notices
            FOR EACH ROW EXECUTE FUNCTION app.reservation_extension_within_rule();

        -- 4. The suggested deposit and its recorded rate.
        ALTER TABLE app.reservation_deposit_acceptances
            DROP CONSTRAINT reservation_deposit_acceptanc_suggested_rate_basis_points_check;
        ALTER TABLE app.reservation_deposit_acceptances
            ADD CONSTRAINT reservation_deposit_acceptance_rate_range
            CHECK (suggested_rate_basis_points BETWEEN 1 AND 10000);
        CREATE OR REPLACE FUNCTION app.validate_reservation_deposit_acceptance()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_rent bigint;
            v_on date;
            v_rate integer;
            v_suggestion bigint;
        BEGIN
            SELECT reservation.agreed_monthly_rent_usd_cents, reservation.reservation_date
            INTO v_rent, v_on
            FROM app.reservations AS reservation
            WHERE reservation.id = NEW.reservation_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation was not found' USING ERRCODE = '23503';
            END IF;
            v_rate := app.reservation_rule('RESERVATION_DEPOSIT_PERCENT', v_on);
            v_suggestion := app.reservation_deposit_suggestion(v_rent, v_on);
            IF NEW.accepted_at > clock_timestamp() + interval '5 seconds'
                OR NEW.suggested_rate_basis_points <> v_rate
                OR NEW.suggested_amount_usd_cents <> v_suggestion
                OR NOT (NEW.calculation_trace @> jsonb_build_object(
                    'agreed_monthly_rent_usd_cents', v_rent,
                    'suggested_rate_basis_points', v_rate,
                    'suggested_amount_usd_cents', v_suggestion
                ))
                OR (
                    NEW.accepted_required_amount_usd_cents = v_suggestion
                    AND NEW.acceptance_kind <> 'NORMAL_SUGGESTION'
                )
                OR (
                    NEW.accepted_required_amount_usd_cents <> v_suggestion
                    AND NEW.acceptance_kind <> 'AUTHORIZED_VARIANCE'
                )
            THEN
                RAISE EXCEPTION 'Reservation Deposit acceptance calculation is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;

        -- 5. A safe range for every rule the app reads.
        CREATE OR REPLACE FUNCTION app.business_rules_program_range() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_code text;
        BEGIN
            SELECT name.code INTO STRICT v_code FROM app.business_rule_names AS name
            WHERE name.id = NEW.rule_name_id;
            IF (v_code = 'LATE_PAYMENT_PERCENT' AND NEW.value > 10000)
                OR (v_code IN ('METER_READING_DAY', 'INVOICE_ISSUE_DAY', 'RENT_DUE_DAY')
                    AND NEW.value NOT BETWEEN 1 AND 28)
                OR (v_code IN ('RESERVATION_DAYS', 'RESERVATION_EXTENSION_DAYS')
                    AND NEW.value NOT BETWEEN 1 AND 90)
                OR (v_code = 'RESERVATION_DEPOSIT_PERCENT' AND NEW.value NOT BETWEEN 1 AND 10000)
            THEN
                RAISE EXCEPTION 'The business rule value is outside what the app allows'
                    USING ERRCODE = '22023';
            END IF;
            RETURN NEW;
        END $$;

        UPDATE app.business_rule_names SET used_by_app = true
        WHERE code IN ('RESERVATION_DAYS', 'RESERVATION_EXTENSION_DAYS',
            'RESERVATION_DEPOSIT_PERCENT');
        """
    )
    _patch(CREATE_RESERVATION, ((SUGGESTION_BEFORE, SUGGESTION_AFTER), (RATE_BEFORE, RATE_AFTER)))


def downgrade() -> None:
    raise RuntimeError("V1.1 step 2b migration is forward-only")
