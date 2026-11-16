"""Who holds a Unit is worked out from the dates of its records (C2, DL-241).

Owner (12 Nov 2026, DL-226, C2). Before, one stored status word said both who holds the Unit
(Vacant, Reserved, Occupied, Short stay) and its condition (Cleaning, Under maintenance, Out of
service), and each Reservation, signing, move-in and check-in changed the word. A Lease signed
today that starts next month showed the Unit as Occupied for that month, and a Lease ended before
any move-in left the word at Occupied. Now who holds the Unit is worked out from the records on
the day asked, and only the condition is stored, set by staff (and by a move-out, a guest's
check-out and the room check, as before).

What changes:

- ``app.units.status`` keeps only the condition: ``VACANT`` (ready), ``CLEANING``,
  ``UNDER_MAINTENANCE`` or ``OUT_OF_SERVICE``. A Unit stored as ``RESERVED``, ``OCCUPIED`` or
  ``SHORT_STAY`` becomes ``VACANT`` (all data is test data; owner 12 Nov 2026 08:28Z); its
  Reservation, Lease or guest still holds it, now from the records.
- New ``app.unit_held_by(unit, day)``: ``OCCUPIED`` while someone lives there (an open
  Occupancy) or from the start date of a Signed Lease; ``SHORT_STAY`` while a guest is checked
  in or on a booked night; ``RESERVED`` while an Active Reservation holds it; else NULL.
  ``app.unit_status_on(unit, day)`` is that word, or the condition when nobody holds the Unit.
  ``app.unit_lease_from(unit, day)`` is the start date of a Signed Lease that starts later.
  ``app.unit_lease_held(unit, except_lease)`` is true while another Signed Lease or an open
  Occupancy holds the Unit. ``app.unit_today(unit)`` is the Property's date.
- The steps that wrote a holder word no longer do; they still raise the Unit version, so every
  version kept in the history stays as it was. The checks that read the word read the records
  instead, and refuse the same things as before: a Reservation needs a ready Unit that nobody
  holds and no Signed Lease or open Occupancy; a signing without a Reservation is refused while
  another Reservation is Active, the Unit is Out of service, or (not a renewal) another Signed
  Lease or an open Occupancy holds it; a check-in needs a ready Unit with no other guest in.
- The three triggers that kept the word in step with the Reservation and the guest are dropped
  (``units_validate_reservation_summary``, ``reservations_validate_unit_summary``,
  ``units_short_stay_status``); the checks of a complete Reservation, move-in and move-out no
  longer ask for a holder word.
- The readers (Home, the Unit occupancy report, the short-stay calendar, booking and week
  report) show the worked-out word, so they say the same as before for today.

Recorded history (signing outcomes, move-out events) keeps its words. This migration is
forward-only.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the rule is the owner's.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270803_421"
down_revision: str | None = "20270802_399"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = r"""
CREATE FUNCTION app.unit_today(p_unit uuid) RETURNS date
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'pg_catalog' AS $$
    SELECT timezone(property.timezone_name, statement_timestamp())::date
    FROM app.units AS unit JOIN app.properties AS property ON property.id = unit.property_id
    WHERE unit.id = p_unit
$$;

CREATE FUNCTION app.unit_lease_held(p_unit uuid, p_except_lease uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'pg_catalog' AS $$
    SELECT EXISTS (
            SELECT 1 FROM app.leases AS lease
            WHERE lease.unit_id = p_unit AND lease.status = 'SIGNED'
              AND lease.id IS DISTINCT FROM p_except_lease)
        OR EXISTS (
            SELECT 1 FROM app.occupancies AS occupancy
            JOIN app.leases AS lease ON lease.id = occupancy.lease_id
            WHERE lease.unit_id = p_unit AND occupancy.move_out_date IS NULL
              AND lease.id IS DISTINCT FROM p_except_lease)
$$;

CREATE FUNCTION app.unit_held_by(p_unit uuid, p_day date) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'pg_catalog' AS $$
    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM app.occupancies AS occupancy
            JOIN app.leases AS lease ON lease.id = occupancy.lease_id
            WHERE lease.unit_id = p_unit AND occupancy.move_out_date IS NULL
              AND occupancy.move_in_date <= p_day) THEN 'OCCUPIED'
        WHEN EXISTS (
            SELECT 1 FROM app.short_stay_bookings AS booking
            WHERE booking.unit_id = p_unit
              AND (booking.status = 'CHECKED_IN'
                   OR (booking.status = 'BOOKED' AND booking.check_in_on <= p_day
                       AND p_day < booking.check_out_on))) THEN 'SHORT_STAY'
        WHEN EXISTS (
            SELECT 1 FROM app.leases AS lease
            WHERE lease.unit_id = p_unit AND lease.status = 'SIGNED'
              AND lease.start_date <= p_day) THEN 'OCCUPIED'
        WHEN EXISTS (
            SELECT 1 FROM app.reservations AS reservation
            WHERE reservation.unit_id = p_unit AND reservation.status = 'ACTIVE') THEN 'RESERVED'
    END
$$;

CREATE FUNCTION app.unit_status_on(p_unit uuid, p_day date) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'pg_catalog' AS $$
    SELECT COALESCE(app.unit_held_by(unit.id, p_day), unit.status)
    FROM app.units AS unit WHERE unit.id = p_unit
$$;

CREATE FUNCTION app.unit_lease_from(p_unit uuid, p_day date) RETURNS date
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'pg_catalog' AS $$
    SELECT min(lease.start_date) FROM app.leases AS lease
    WHERE lease.unit_id = p_unit AND lease.status = 'SIGNED' AND lease.start_date > p_day
$$;
"""

NEW_FUNCTIONS = (
    "app.unit_today(uuid)",
    "app.unit_lease_held(uuid,uuid)",
    "app.unit_held_by(uuid,date)",
    "app.unit_status_on(uuid,date)",
    "app.unit_lease_from(uuid,date)",
)

HOLDER_GONE = r"""
DROP TRIGGER units_validate_reservation_summary ON app.units;
DROP TRIGGER reservations_validate_unit_summary ON app.reservations;
DROP TRIGGER units_short_stay_status ON app.units;
DROP FUNCTION app.validate_unit_reservation_summary();
DROP FUNCTION app.assert_reservation_unit_summary();
DROP FUNCTION app.guard_short_stay_unit_status();
UPDATE app.units SET status = 'VACANT', version = version + 1,
    updated_at = GREATEST(updated_at, statement_timestamp())
WHERE status IN ('RESERVED', 'OCCUPIED', 'SHORT_STAY');
ALTER TABLE app.units DROP CONSTRAINT units_status_supported;
ALTER TABLE app.units ADD CONSTRAINT units_status_supported
    CHECK (status IN ('VACANT', 'CLEANING', 'UNDER_MAINTENANCE', 'OUT_OF_SERVICE'));
COMMENT ON COLUMN app.units.status IS
    'The condition set by staff: VACANT (ready), CLEANING, UNDER_MAINTENANCE or OUT_OF_SERVICE. '
    'Who holds the Unit is worked out by app.unit_held_by (C2, DL-241).';
"""

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.create_reservation(uuid,uuid,text,uuid,uuid,uuid,date,bigint,date,uuid,bigint,text,"
        "timestamp with time zone,text,text,jsonb,uuid,bigint,uuid,uuid,timestamp with time zone,"
        "uuid)",
        (
            (
                "            IF v_unit.status <> 'VACANT' THEN\n",
                "            -- C2 (DL-241): a ready Unit that nobody holds, by its records. A\n"
                "            -- short-stay guest is refused by the "
                "Reservation trigger, with its text.\n"
                "            IF v_unit.status <> 'VACANT'\n"
                "                OR app.unit_held_by(v_unit.id, p_reservation_date)\n"
                "                    IN ('OCCUPIED', 'RESERVED')\n"
                "                OR EXISTS (SELECT 1 FROM app.short_stay_bookings AS late\n"
                "                    WHERE late.unit_id = v_unit.id AND "
                "late.status = 'CHECKED_IN'\n"
                "                      AND late.check_out_on <= p_reservation_date)\n"
                "                OR app.unit_lease_held(v_unit.id, NULL) THEN\n",
            ),
            ("            SET status = 'RESERVED', version", "            SET version"),
        ),
    ),
    (
        "app.cancel_reservation(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,"
        "uuid)",
        (("            SET status = 'VACANT', version", "            SET version"),),
    ),
    (
        "app.expire_reservation(uuid,uuid,text,uuid,uuid,integer,boolean,text,uuid)",
        (("            SET status = 'VACANT', version", "            SET version"),),
    ),
    (
        "app.complete_reservation_move_in(uuid,uuid,text,uuid,uuid,uuid,integer,integer,integer,"
        "date,jsonb,text,text,uuid)",
        (
            (
                "IF v_reservation.status <> 'ACTIVE' OR v_unit.status <> 'RESERVED'\n",
                "IF v_reservation.status <> 'ACTIVE'\n",
            ),
            (
                "            UPDATE app.units SET status = 'OCCUPIED', version",
                "            UPDATE app.units SET version",
            ),
        ),
    ),
    (
        "app.record_signed_lease_move_in(uuid,uuid,text,uuid,uuid,integer,date,jsonb,text,text,"
        "uuid)",
        (
            (
                "OR v_lease.status <> 'SIGNED' OR v_unit.status <> 'OCCUPIED'\n",
                "OR v_lease.status <> 'SIGNED'\n",
            ),
        ),
    ),
    (
        "app.sign_lease_with_reservation(uuid,uuid,text,uuid,uuid,integer,"
        "timestamp with time zone,text,uuid,uuid)",
        (
            ("                    OR v_unit.status <> 'RESERVED'\n", ""),
            (
                "            ELSIF v_unit.status = 'RESERVED' OR v_unit.status = 'OUT_OF_SERVICE'\n"
                "                OR (v_unit.status = 'OCCUPIED' AND "
                "v_lease.predecessor_lease_id IS NULL)\n",
                "            -- C2 (DL-241): the same refusals, read from the records.\n"
                "            ELSIF v_unit.status = 'OUT_OF_SERVICE'\n"
                "                OR EXISTS (SELECT 1 FROM app.reservations AS other\n"
                "                    WHERE other.unit_id = v_unit.id AND other.status = 'ACTIVE')\n"
                "                OR (v_lease.predecessor_lease_id IS NULL\n"
                "                    AND app.unit_lease_held(v_unit.id, v_lease.id))\n",
            ),
            (
                "            IF v_unit.status <> 'OCCUPIED' THEN\n"
                "                UPDATE app.units SET status = 'OCCUPIED', version",
                "            IF v_lease.predecessor_lease_id IS NULL THEN\n"
                "                UPDATE app.units SET version",
            ),
        ),
    ),
    (
        "app.check_in_short_stay(uuid,uuid,jsonb,integer,uuid,uuid)",
        (
            (
                "    IF v_unit.status <> 'VACANT' THEN\n",
                "    IF v_unit.status <> 'VACANT' OR EXISTS (\n"
                "        SELECT 1 FROM app.short_stay_bookings AS other\n"
                "        WHERE other.unit_id = v_unit.id AND other.status = 'CHECKED_IN'\n"
                "          AND other.id <> p_booking) THEN\n",
            ),
            ("    SET status = 'SHORT_STAY', version", "    SET version"),
        ),
    ),
    (
        "app.check_out_short_stay(uuid,uuid,integer,uuid,uuid)",
        (
            (
                "    WHERE unit.id = v_row.unit_id AND unit.status = 'SHORT_STAY';",
                "    WHERE unit.id = v_row.unit_id AND unit.status = 'VACANT';",
            ),
        ),
    ),
    (
        "app.set_unit_for_rent(uuid,integer,boolean,uuid)",
        (
            (
                "                v_unit.status IN ('RESERVED', 'OCCUPIED')\n",
                "                app.unit_lease_held(p_unit_id, NULL)\n",
            ),
        ),
    ),
    (
        "app.resolve_unpaid_initial_never_moved_in(uuid,uuid,uuid,text,uuid,uuid,text,text,text)",
        (
            (
                "            IF v_unit.status<>'OCCUPIED' THEN\n"
                "                RAISE EXCEPTION 'Unit is not held by this "
                "Lease' USING ERRCODE='22023'; END IF;",
                "            IF v_unit.status IN ('UNDER_MAINTENANCE','OUT_OF_SERVICE') THEN\n"
                "                RAISE EXCEPTION 'Unit is not held by this "
                "Lease' USING ERRCODE='22023'; END IF;",
            ),
        ),
    ),
    (
        "app.physical_move_out_record(uuid,uuid,uuid,uuid,text,jsonb,text)",
        (
            (
                "THEN 'OCCUPIED' ELSE p_intent->>'unit_condition' END;",
                "THEN v_u.status ELSE p_intent->>'unit_condition' END;",
            ),
        ),
    ),
    (
        "app.validate_physical_move_out_complete()",
        (
            (
                "                OR (v_e.resulting_unit_status IN ('VACANT','RESERVED')\n",
                "                OR (v_e.resulting_unit_status IN ('VACANT','RESERVED')\n"
                "                    AND v_e.previous_unit_status IS "
                "DISTINCT FROM v_e.resulting_unit_status\n",
            ),
        ),
    ),
    (
        "app.assert_reservation_activation_bundle()",
        (("                OR v_unit_status <> 'RESERVED'\n", ""),),
    ),
    (
        "app.assert_move_in_event_applied()",
        (("                  AND unit.status = 'OCCUPIED'\n", ""),),
    ),
    (
        "app.home_page(uuid,uuid,uuid[],text[])",
        (
            (
                "            FROM app.units unit WHERE unit.property_id=p_property\n",
                "            FROM (SELECT u.id, u.property_id, u.for_rent,\n"
                "                    app.unit_status_on(u.id, v_today) AS status\n"
                "                FROM app.units u) unit WHERE unit.property_id=p_property\n",
            ),
        ),
    ),
    (
        "app.report_unit_occupancy(uuid,uuid,uuid[])",
        (
            (
                "        SELECT unit.id, unit.status, lease.id, reservation.id,",
                "        SELECT unit.id, app.unit_status_on(unit.id, "
                "v_today), lease.id, reservation.id,",
            ),
        ),
    ),
    (
        "app.short_stay_calendar_main(uuid,date,integer,uuid)",
        (
            (
                "'status', unit.status, 'for_rent', unit.for_rent,",
                "'status', app.unit_status_on(unit.id, v_today), 'for_rent', unit.for_rent,",
            ),
        ),
    ),
    (
        "app.short_stay_booking_main_json(uuid)",
        (
            (
                "        'unit_status', unit.status,",
                "        'unit_status', app.unit_status_on(unit.id, app.unit_today(unit.id)),",
            ),
        ),
    ),
    (
        "app.short_stay_week_report(uuid,date,uuid)",
        (
            (
                "unit.status IN ('VACANT', 'SHORT_STAY', 'CLEANING')",
                "app.unit_status_on(unit.id, v_today) IN ('VACANT', 'SHORT_STAY', 'CLEANING')",
            ),
        ),
    ),
)


def _definition(signature: str) -> str:
    found = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    return str(found)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Unit holder source contract changed: {signature}: {before!r}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(text(definition.replace(":", "\\:")))


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature in NEW_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime, prm_financial")
    op.execute(HOLDER_GONE)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("the Unit holder migration is forward-only")
