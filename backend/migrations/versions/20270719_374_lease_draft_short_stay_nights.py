# ruff: noqa: E501
"""Owner report of 12 Nov 2026, DL-223: a Lease draft is not saved over a short-stay booking.

The owner made a paid short-stay booking on U301 for 13 to 15 Nov 2026, then a Lease draft for
the same Unit from 11 Nov 2026. The draft was saved, because migration 20270531_310 checked the
booked nights only for a signed or terminated Lease. "Receive and sign" then stopped, as the
owner's rule C of 3 Nov 2026 says (the booking wins: offer another Unit or a later Start Date),
but only after the Customer was at the desk with the money.

The trigger function of ``app.leases`` is replaced with one change: a DRAFTED Lease is checked
too. So a new draft (walk-in, from a Reservation or a renewal) and Edit draft stop at once when a
booked or checked-in guest has one of the Lease's days. A draft with no Start Date holds no day
and is not checked; a draft with no End Date is checked from its Start Date on.

What stays as it was:
- A booking still holds the nights from the check-in day up to, not including, the check-out day,
  so a Lease may start on the check-out day.
- A draft holds no day. A guest may still book a Unit that has a draft, and the booking wins: the
  draft then cannot be signed (same refusal) until its dates are changed, and it can always be
  cancelled (a cancelled Lease is not checked).
- A draft saved before this migration is not touched. It is checked the next time it is edited
  or signed.

No table, column, grant or data change. Forward-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270719_374"
down_revision: str | None = "20270716_391"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = r"""
-- One Unit never has a booking and a Lease on the same night; a draft is stopped as early as a
-- signed Lease (DL-223). The Unit row is locked so two people cannot each pass the check.
CREATE OR REPLACE FUNCTION app.guard_lease_short_stay_nights() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v_to date;
BEGIN
    IF NEW.status NOT IN ('DRAFTED', 'SIGNED', 'TERMINATED') OR NEW.start_date IS NULL THEN
        RETURN NEW;
    END IF;
    v_to := CASE WHEN NEW.status = 'TERMINATED' THEN NEW.actual_termination_date ELSE NEW.end_date END;
    PERFORM 1 FROM app.units AS unit WHERE unit.id = NEW.unit_id FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM app.short_stay_bookings AS booking
        WHERE booking.unit_id = NEW.unit_id AND booking.status IN ('BOOKED', 'CHECKED_IN')
          AND app.short_stay_lease_night_taken(NEW.unit_id, booking.check_in_on,
              booking.check_out_on, NEW.start_date, v_to)
    ) THEN
        RAISE EXCEPTION 'A daily or weekly guest has booked this Unit on one of these days; offer another Unit or a later Start Date'
            USING ERRCODE = '23P01';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.guard_lease_short_stay_nights() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(FUNCTION)


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
