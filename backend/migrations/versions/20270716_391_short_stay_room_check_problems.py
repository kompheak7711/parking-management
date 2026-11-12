# ruff: noqa: E501
"""Short stays: the room check reports problems; damage is charged without an approval (DL-222).

The owner's answer "All recommended" of 12 Nov 2026 04:56 (UTC+7), thread "Rethink short-stay
damage approval": a short-stay check-out works like a long-stay move-out.

1. The room check reports problems, not money. Each problem the housekeeper finds is a Unit
   Problem report (UP...) of the stay's Unit, with its type, what is wrong and Urgent, made by
   the usual ``app.add_problem_report`` with the new source ``ROOM_CHECK``; the repair is then
   planned, fixed and closed on the Problem reports page. ``app.short_stay_problem_reports``
   keeps each report's booking (append-only). The room check refuses a cost. Reporting a problem
   also needs ``problem_reports.add`` (Staff hold it).
2. The charge is decided on the booking by the person who bills damage (``damage_charges.bill``,
   the right of a long-stay Damage Invoice), with no approval: ``app.decide_short_stay_charge``
   records "Charge the guest" (what for and how much) or "No charge" in
   ``app.short_stay_damage_decisions`` (one per booking, append-only). A charge is a
   ``short_stay_damages`` row decided at once: it comes from the deposit first and the rest is a
   Damage Invoice for the guest, as before (4070 Damage recovered).
3. The deposit waits while the room check's problems have no decision.
4. A damage charge still waiting from before this change is decided on the booking by the same
   right: ``app.decide_short_stay_damage`` checks ``damage_charges.bill`` instead of
   ``short_stays.approve``.
5. The booking read adds ``problems``, ``damage_decision`` and ``damage_due``; a Problem report
   read adds ``stay`` (the booking it came from). ``app.short_stay_damage_due`` lists the stays
   whose damage is not decided yet, for the person who bills damage.

This replaces rule 6 of migration 20270602_312 ("Damage waits for the Manager"). Technical
choices by Claude under the owner's 2026-10-23 22:30 rule. Forward-only and additive: no row
changes; two new tables; the source check of ``problem_reports`` takes one more value.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270716_391"
down_revision: str | None = "20270716_390"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("short_stay_problem_reports", "short_stay_damage_decisions")

SCHEMA = r"""
ALTER TABLE app.problem_reports DROP CONSTRAINT problem_reports_source_check;
ALTER TABLE app.problem_reports ADD CONSTRAINT problem_reports_source_check
    CHECK (source IN ('PHONE', 'WALKIN', 'SEEN', 'INSPECTION', 'TENANT_BOT', 'STAFF_BOT',
        'ROOM_CHECK'));

-- One Problem report from a short-stay room check, with its booking.
CREATE TABLE app.short_stay_problem_reports (
    report_id uuid PRIMARY KEY REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
    booking_id uuid NOT NULL REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp() CHECK (isfinite(created_at)),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
);
CREATE INDEX short_stay_problem_reports_booking_idx
    ON app.short_stay_problem_reports (booking_id);

-- The one decision on the damage of a stay: Charge the guest (its damage row) or No charge.
CREATE TABLE app.short_stay_damage_decisions (
    booking_id uuid PRIMARY KEY REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    outcome text NOT NULL CHECK (outcome IN ('CHARGE', 'NO_CHARGE')),
    damage_id uuid UNIQUE REFERENCES app.short_stay_damages (id) ON DELETE RESTRICT,
    note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
    decided_at timestamptz NOT NULL DEFAULT statement_timestamp() CHECK (isfinite(decided_at)),
    decided_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
    CONSTRAINT short_stay_damage_decisions_shape
        CHECK ((outcome = 'CHARGE') = (damage_id IS NOT NULL))
);
"""

FUNCTIONS = r"""
-- The booking a room-check report comes from: in this Property and Unit, checked out, and its
-- room check still to do (the report is made while the room check is saved).
CREATE FUNCTION app.problem_report_booking_for(p_property uuid, p_report jsonb, p_kind text,
    p_unit uuid, p_source text) RETURNS uuid
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
DECLARE
    v_booking uuid;
    v_unit uuid;
    v_status text;
BEGIN
    IF p_source <> 'ROOM_CHECK' THEN
        RAISE EXCEPTION 'Only a report from a room check has a booking' USING ERRCODE = '22023';
    END IF;
    IF p_kind <> 'UNIT' THEN
        RAISE EXCEPTION 'A report from a room check is a Unit Problem' USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_booking := (p_report ->> 'booking_id')::uuid;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'the booking does not exist' USING ERRCODE = '22023';
    END;
    SELECT booking.unit_id, booking.status INTO v_unit, v_status
    FROM app.short_stay_bookings AS booking
    WHERE booking.id = v_booking AND booking.property_id = p_property;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the booking does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_unit IS DISTINCT FROM p_unit THEN
        RAISE EXCEPTION 'The report must be in the Unit of the stay' USING ERRCODE = '22023';
    END IF;
    IF v_status <> 'CHECKED_OUT' OR NOT EXISTS (
        SELECT 1 FROM app.housekeeping_tasks AS task
        WHERE task.booking_id = v_booking AND task.kind = 'ROOM_CHECK' AND task.status = 'TO_DO') THEN
        RAISE EXCEPTION 'Problems of a stay are reported at its room check' USING ERRCODE = '55000';
    END IF;
    RETURN v_booking;
END $$;
REVOKE ALL ON FUNCTION app.problem_report_booking_for(uuid, jsonb, text, uuid, text) FROM PUBLIC;

-- The stay of one report, on every read of it.
CREATE FUNCTION app.problem_report_stay_json(p_report uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT jsonb_build_object('booking_id', booking.id, 'booking_number', booking.booking_number,
        'guest_name', customer.legal_name, 'check_in_on', booking.check_in_on,
        'check_out_on', booking.check_out_on)
    FROM app.short_stay_problem_reports AS link
    JOIN app.short_stay_bookings AS booking ON booking.id = link.booking_id
    JOIN app.customers AS customer ON customer.id = booking.customer_id
    WHERE link.report_id = p_report
$$;
REVOKE ALL ON FUNCTION app.problem_report_stay_json(uuid) FROM PUBLIC;

-- 1. The room check after check-out reports problems, not money; the Unit is Vacant again.
CREATE OR REPLACE FUNCTION app.check_short_stay_room(p_property uuid, p_booking uuid, p_check jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.housekeeping', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
    v_task app.housekeeping_tasks%ROWTYPE;
    v_note text;
    v_problems jsonb;
    v_problem jsonb;
    v_report uuid;
    v_found jsonb := '[]'::jsonb;
    v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
BEGIN
    IF p_check IS NULL OR jsonb_typeof(p_check) <> 'object' THEN
        RAISE EXCEPTION 'The room check is invalid' USING ERRCODE = '22023';
    END IF;
    IF p_check ? 'damage' OR p_check ? 'damage_usd_cents' THEN
        RAISE EXCEPTION 'The room check reports problems; the damage charge is set on the booking'
            USING ERRCODE = '22023';
    END IF;
    v_note := NULLIF(btrim(p_check ->> 'note'), '');
    v_problems := COALESCE(p_check -> 'problems', '[]'::jsonb);
    IF jsonb_typeof(v_problems) <> 'array' OR jsonb_array_length(v_problems) > 20
        OR length(v_note) > 500 THEN
        RAISE EXCEPTION 'The room check is invalid' USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(v_problems) > 0 AND NOT EXISTS (
        SELECT 1 FROM app.actor_capability_grants(p_actor) AS held
        WHERE held.capability_id = 'problem_reports.add' AND held.property_id = p_property) THEN
        RAISE EXCEPTION 'Reporting a problem needs the right to add a Problem report'
            USING ERRCODE = '42501';
    END IF;
    SELECT task.* INTO v_task FROM app.housekeeping_tasks AS task
    WHERE task.booking_id = p_booking AND task.kind = 'ROOM_CHECK' AND task.status = 'TO_DO'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No room check is due for this booking' USING ERRCODE = '55000';
    END IF;
    -- DL-222 (A): each problem is a Unit Problem report of the stay's Unit, kept with the booking.
    FOR v_problem IN SELECT problem.value FROM jsonb_array_elements(v_problems) AS problem LOOP
        IF jsonb_typeof(v_problem) <> 'object' OR EXISTS (
            SELECT 1 FROM jsonb_object_keys(v_problem) AS field
            WHERE field NOT IN ('problem_type_id', 'description', 'urgent')) THEN
            RAISE EXCEPTION 'A problem has its type, what is wrong and Urgent'
                USING ERRCODE = '22023';
        END IF;
        v_report := app.add_problem_report(p_property, jsonb_build_object('kind', 'UNIT',
                'unit_id', v_row.unit_id, 'source', 'ROOM_CHECK', 'booking_id', p_booking,
                'problem_type_id', v_problem -> 'problem_type_id',
                'description', v_problem -> 'description',
                'urgent', COALESCE(v_problem -> 'urgent', 'false'::jsonb),
                'may_enter', true, 'best_time', 'ANY'),
            p_actor, v_correlation);
        SELECT v_found || jsonb_build_array(jsonb_build_object('report_id', report.id,
                'report_number', report.report_number, 'description', report.description))
        INTO v_found
        FROM app.problem_reports AS report WHERE report.id = v_report;
    END LOOP;
    UPDATE app.housekeeping_tasks AS task
    SET status = 'DONE', note = v_note, done_at = statement_timestamp(), done_by = p_actor,
        version = task.version + 1
    WHERE task.id = v_task.id;
    UPDATE app.units AS unit
    SET status = 'VACANT', version = unit.version + 1, updated_at = statement_timestamp(),
        updated_by = p_actor
    WHERE unit.id = v_row.unit_id AND unit.status = 'CLEANING';
    PERFORM app.short_stay_event(p_booking, 'ROOM_CHECKED', p_actor, v_note,
        CASE WHEN jsonb_array_length(v_found) = 0 THEN '{}'::jsonb
            ELSE jsonb_build_object('problems', v_found) END);
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.room_checked',
        'short_stay_booking', p_booking, 'Room checked after check-out', 'short_stays.housekeeping',
        NULL, jsonb_build_object('problems', jsonb_array_length(v_found)), v_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 2. The person who bills damage decides on the stay's damage, with no approval: Charge the
-- guest (from the deposit first, the rest an Invoice for the guest) or No charge.
CREATE FUNCTION app.decide_short_stay_charge(p_property uuid, p_booking uuid, p_decision jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'damage_charges.bill', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
    v_charge boolean;
    v_text text := NULLIF(btrim(p_decision ->> 'description'), '');
    v_note text := NULLIF(btrim(p_decision ->> 'note'), '');
    v_cost bigint;
    v_left bigint := 0;
    v_from bigint := 0;
    v_issued jsonb;
    v_damage uuid;
    v_correlation uuid := COALESCE(p_correlation, gen_random_uuid());
BEGIN
    IF p_decision IS NULL OR jsonb_typeof(p_decision) <> 'object'
        OR jsonb_typeof(p_decision -> 'charge') IS DISTINCT FROM 'boolean'
        OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_decision) AS field
                   WHERE field NOT IN ('charge', 'description', 'amount_usd_cents', 'note')) THEN
        RAISE EXCEPTION 'The decision is invalid' USING ERRCODE = '22023';
    END IF;
    v_charge := (p_decision ->> 'charge')::boolean;
    BEGIN
        v_cost := (p_decision ->> 'amount_usd_cents')::bigint;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'The amount is invalid' USING ERRCODE = '22023';
    END;
    IF length(v_note) > 500 THEN
        RAISE EXCEPTION 'The note is at most 500 letters' USING ERRCODE = '22023';
    END IF;
    IF v_charge THEN
        IF v_text IS NULL OR length(v_text) > 500 THEN
            RAISE EXCEPTION 'Say what the guest pays for, at most 500 letters'
                USING ERRCODE = '22023';
        END IF;
        IF v_cost IS NULL OR v_cost <= 0 OR v_cost > 100000000 THEN
            RAISE EXCEPTION 'The amount is invalid' USING ERRCODE = '22023';
        END IF;
    ELSIF v_text IS NOT NULL OR v_cost IS NOT NULL THEN
        RAISE EXCEPTION 'No charge has no amount' USING ERRCODE = '22023';
    END IF;
    IF v_row.status <> 'CHECKED_OUT' OR NOT EXISTS (
        SELECT 1 FROM app.short_stay_problem_reports AS link WHERE link.booking_id = p_booking) THEN
        RAISE EXCEPTION 'Damage is decided after the room check reports a problem'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_damage_decisions AS decided
               WHERE decided.booking_id = p_booking) THEN
        RAISE EXCEPTION 'The damage of this stay is already decided' USING ERRCODE = '55000';
    END IF;
    IF v_charge THEN
        SELECT deposit.amount_usd_cents - COALESCE((
                SELECT sum(other.from_deposit_usd_cents) FROM app.short_stay_damages AS other
                WHERE other.booking_id = v_row.id AND other.status = 'APPROVED'), 0)
            INTO v_left
        FROM app.short_stay_deposits AS deposit
        WHERE deposit.booking_id = v_row.id AND deposit.status = 'HELD';
        v_from := GREATEST(LEAST(COALESCE(v_left, 0), v_cost), 0);
        IF v_from < v_cost THEN
            v_issued := app.short_stay_invoice(p_property, p_actor, v_row.customer_id,
                'Damage charged for short stay ' || v_row.booking_number,
                'Short stay ' || v_row.booking_number,
                jsonb_build_array(jsonb_build_object('charge_id', gen_random_uuid(),
                    'description', 'Damage · ' || v_row.booking_number || ' · ' || v_text
                        || CASE WHEN v_from > 0 THEN ' (after '
                            || app.short_stay_dollars(v_from) || ' from the deposit)' ELSE '' END,
                    'quantity', 1,
                    'unit_price_usd_cents', v_cost - v_from)),
                v_correlation);
        END IF;
        INSERT INTO app.short_stay_damages (booking_id, description, amount_usd_cents, status,
            asked_by, decided_at, decided_by, decision_note, from_deposit_usd_cents, invoice_id)
        VALUES (p_booking, v_text, v_cost, 'APPROVED', p_actor, statement_timestamp(), p_actor,
            v_note, v_from, (v_issued ->> 'invoice_id')::uuid)
        RETURNING id INTO v_damage;
    END IF;
    INSERT INTO app.short_stay_damage_decisions (booking_id, outcome, damage_id, note, decided_by)
    VALUES (p_booking, CASE WHEN v_charge THEN 'CHARGE' ELSE 'NO_CHARGE' END, v_damage, v_note,
        p_actor);
    PERFORM app.short_stay_event(p_booking,
        CASE WHEN v_charge THEN 'DAMAGE_CHARGED' ELSE 'NO_DAMAGE_CHARGE' END, p_actor, v_note,
        CASE WHEN v_charge THEN jsonb_strip_nulls(jsonb_build_object('description', v_text,
                'amount_usd_cents', v_cost, 'from_deposit_usd_cents', v_from,
                'invoice_number', v_issued ->> 'invoice_number'))
            ELSE '{}'::jsonb END);
    PERFORM app.product_audit(p_property, p_actor, v_today,
        CASE WHEN v_charge THEN 'short_stay.damage_charged' ELSE 'short_stay.no_damage_charge' END,
        'short_stay_booking', p_booking,
        COALESCE(v_note, CASE WHEN v_charge THEN 'Damage charged' ELSE 'No damage charge' END),
        'damage_charges.bill', NULL,
        jsonb_build_object('amount_usd_cents', v_cost, 'from_deposit_usd_cents', v_from,
            'invoice_id', v_issued ->> 'invoice_id'), v_correlation);
    RETURN app.short_stay_booking_json(p_booking);
END $$;

-- 3. The booking as the screens read it, with the room check's problems and the decision.
ALTER FUNCTION app.short_stay_booking_json(uuid) RENAME TO short_stay_booking_refund_json;
CREATE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT app.short_stay_booking_refund_json(p_booking) || jsonb_build_object(
        'problems', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('report_id', report.id,
                'report_number', report.report_number, 'description', report.description,
                'type_name_en', kind.name_en, 'type_name_kh', kind.name_kh,
                'urgent', report.urgent, 'status', report.status)
                ORDER BY report.created_at, report.report_number)
            FROM app.short_stay_problem_reports AS link
            JOIN app.problem_reports AS report ON report.id = link.report_id
            JOIN app.problem_types AS kind ON kind.id = report.problem_type_id
            WHERE link.booking_id = p_booking), '[]'::jsonb),
        'damage_decision', (
            SELECT jsonb_build_object('outcome', decided.outcome, 'damage_id', decided.damage_id,
                'note', decided.note, 'decided_at', decided.decided_at)
            FROM app.short_stay_damage_decisions AS decided
            WHERE decided.booking_id = p_booking),
        'damage_due', EXISTS (
                SELECT 1 FROM app.short_stay_problem_reports AS link
                WHERE link.booking_id = p_booking)
            AND NOT EXISTS (
                SELECT 1 FROM app.short_stay_damage_decisions AS decided
                WHERE decided.booking_id = p_booking))
$$;
REVOKE ALL ON FUNCTION app.short_stay_booking_json(uuid) FROM PUBLIC;

-- 4. The stays whose room check reported problems and whose damage is not decided yet, for the
-- Short stays page of the person who bills damage.
CREATE FUNCTION app.short_stay_damage_due(p_property uuid, p_actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    PERFORM app.require_product_right(p_actor, 'damage_charges.bill', p_property);
    RETURN COALESCE((
        SELECT jsonb_agg(jsonb_build_object('booking_id', due.booking_id,
                'booking_number', due.booking_number, 'guest_name', due.legal_name,
                'unit_number', due.unit_number, 'problem_count', due.problem_count)
                ORDER BY due.first_at, due.booking_number)
        FROM (
            SELECT booking.id AS booking_id, booking.booking_number, customer.legal_name,
                unit.unit_number, count(*) AS problem_count, min(link.created_at) AS first_at
            FROM app.short_stay_problem_reports AS link
            JOIN app.short_stay_bookings AS booking ON booking.id = link.booking_id
            JOIN app.customers AS customer ON customer.id = booking.customer_id
            JOIN app.units AS unit ON unit.id = booking.unit_id
            WHERE booking.property_id = p_property
              AND NOT EXISTS (SELECT 1 FROM app.short_stay_damage_decisions AS decided
                              WHERE decided.booking_id = booking.id)
            GROUP BY booking.id, booking.booking_number, customer.legal_name, unit.unit_number
        ) AS due), '[]'::jsonb);
END $$;
"""

ADD = "app.add_problem_report(uuid, jsonb, uuid, uuid)"
ADD_PATCHES = (
    (
        "IF v_source IS NULL OR v_source NOT IN ('PHONE', 'WALKIN', 'SEEN', 'INSPECTION') THEN",
        "IF v_source IS NULL OR v_source NOT IN ('PHONE', 'WALKIN', 'SEEN', 'INSPECTION',\n"
        "            'ROOM_CHECK') THEN",
    ),
    (
        "-- DL-132: a report made from a move-out inspection finding keeps the link.",
        "-- DL-222: a report made at a short-stay room check keeps its booking.\n"
        "        IF v_source = 'ROOM_CHECK' OR p_report ? 'booking_id' THEN\n"
        "            INSERT INTO app.short_stay_problem_reports (report_id, booking_id, created_by)\n"
        "            VALUES (v_id, app.problem_report_booking_for(p_property, p_report, v_kind,\n"
        "                v_unit, v_source), p_actor);\n"
        "        END IF;\n"
        "        -- DL-132: a report made from a move-out inspection finding keeps the link.",
    ),
)

READ_JSON = "app.problem_report_json(uuid, boolean)"
READ_PATCHES = (
    (
        "'finding', app.problem_report_finding_json(base.id),",
        "'finding', app.problem_report_finding_json(base.id),\n"
        "            'stay', app.problem_report_stay_json(base.id),",
    ),
)

DECIDE = "app.decide_short_stay_damage(uuid, uuid, jsonb, uuid, uuid)"
DECIDE_PATCHES = (
    (
        "app.require_product_right(p_actor, 'short_stays.approve', p_property)",
        "app.require_product_right(p_actor, 'damage_charges.bill', p_property)",
    ),
    (
        "'short_stays.approve', jsonb_build_object('status', 'WAITING'),",
        "'damage_charges.bill', jsonb_build_object('status', 'WAITING'),",
    ),
)

END_DEPOSIT = "app.end_short_stay_deposit(uuid, uuid, uuid, uuid)"
END_PATCHES = (
    (
        """    IF EXISTS (SELECT 1 FROM app.short_stay_damages AS damage
               WHERE damage.booking_id = p_booking AND damage.status = 'WAITING') THEN
        RAISE EXCEPTION 'Damage waits for the Manager; the deposit waits too' USING ERRCODE = '55000';
    END IF;""",
        """    IF EXISTS (SELECT 1 FROM app.short_stay_damages AS damage
               WHERE damage.booking_id = p_booking AND damage.status = 'WAITING')
        OR (EXISTS (SELECT 1 FROM app.short_stay_problem_reports AS link
                    WHERE link.booking_id = p_booking)
            AND NOT EXISTS (SELECT 1 FROM app.short_stay_damage_decisions AS decided
                            WHERE decided.booking_id = p_booking)) THEN
        RAISE EXCEPTION 'The damage charge is not decided yet; the deposit waits too'
            USING ERRCODE = '55000';
    END IF;""",
    ),
    ("'Kept for approved damage'", "'Kept for the damage charge'"),
)

ACTIONS = (
    "app.decide_short_stay_charge(uuid, uuid, jsonb, uuid, uuid)",
    "app.short_stay_damage_due(uuid, uuid)",
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
    op.execute(SCHEMA)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_protect BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate()"
        )
    tables = ", ".join(f"app.{table}" for table in TABLES)
    op.execute(f"REVOKE ALL ON TABLE {tables} FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute(f"GRANT SELECT ON TABLE {tables} TO prm_runtime")
    op.execute(FUNCTIONS)
    _patch(ADD, ADD_PATCHES)
    _patch(READ_JSON, READ_PATCHES)
    _patch(DECIDE, DECIDE_PATCHES)
    _patch(END_DEPOSIT, END_PATCHES)
    for signature in ACTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("The short-stay room check problems migration is forward-only")
