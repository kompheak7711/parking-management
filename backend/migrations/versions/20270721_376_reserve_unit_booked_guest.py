# ruff: noqa: E501
"""DL-225 (12 Nov 2026): Reserve Unit stops on a Unit a short-stay guest has booked.

A Reservation holds its Unit from the Reservation Date (today) for the Lease that follows.
``app.create_reservation`` checked only that the Unit was VACANT, and a Unit with a booked guest
who has not checked in yet is still VACANT. So the Reservation was saved and its deposit taken.
The guest could then not check in (a RESERVED Unit stops the check-in), and the Lease draft that
followed stopped only later (DL-223). The gap was found while fixing DL-223 and told to the
owner on 12 Nov 2026. It applies the owner's rule for a Lease (rule C of 3 Nov 2026): the booking
wins, and staff reserve another Unit or move the guest first with Change Unit (DL-224). No new
business or money rule.

One new trigger on ``app.reservations``: a Reservation that becomes ACTIVE on a Unit is refused
when a booked or checked-in guest still has a night there from the Reservation Date on. A booking
holds the nights from the check-in day up to, not including, the check-out day (as for a Lease),
so a stay whose check-out day is the Reservation Date or earlier does not stop it. The refusal
is raised inside ``app.create_reservation``; the one-step command
(``app.create_reservation_with_payment``) runs in one transaction, so the Payment confirmed in
the same step is gone with it.

What stays as it was:
- The other direction: a short-stay booking is already refused on a RESERVED Unit.
- A Reservation saved before this migration is not touched.
- A booking-site hold with no booking typed in here is not checked (as for a Lease).

No table, column, grant or data change. Forward-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270721_376"
down_revision: str | None = "20270720_375"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUARD = r"""
-- One Unit is never held for a Lease while a short-stay guest still has a night there (DL-225).
-- The Unit row is locked, as the booking and Lease checks lock it, so two people cannot each
-- pass the check.
CREATE FUNCTION app.guard_reservation_short_stay_guest() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.status <> 'ACTIVE' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'ACTIVE' AND OLD.unit_id = NEW.unit_id THEN
        RETURN NEW;
    END IF;
    PERFORM 1 FROM app.units AS unit WHERE unit.id = NEW.unit_id FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM app.short_stay_bookings AS booking
        WHERE booking.unit_id = NEW.unit_id AND booking.status IN ('BOOKED', 'CHECKED_IN')
          AND booking.check_out_on > NEW.reservation_date
    ) THEN
        RAISE EXCEPTION 'A daily or weekly guest has booked this Unit; reserve another Unit or move the guest to another Unit first'
            USING ERRCODE = '23P01';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.guard_reservation_short_stay_guest() FROM PUBLIC;

CREATE TRIGGER reservations_short_stay_guest
BEFORE INSERT OR UPDATE OF unit_id, status ON app.reservations
FOR EACH ROW EXECUTE FUNCTION app.guard_reservation_short_stay_guest();
"""


def upgrade() -> None:
    op.execute(GUARD)


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
