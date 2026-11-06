// What one night of one Unit holds on the calendar, read the same way as the database's blockers
// (migration 20270601_311 app.short_stay_blockers): a booking covers [check-in, check-out), a
// Lease covers [start, end]. Display only: the server checks every night again.

import type {
  CalendarBooking,
  CalendarUnit,
  SiteHold,
} from "./shortStaysClient";

export type Night =
  | { kind: "FREE" }
  | {
      kind: "BOOKING";
      booking: CalendarBooking;
      first: boolean;
      /** A booking site holds the same night for someone else (step 5a). */
      clash: SiteHold | null;
    }
  | { kind: "HOLD"; hold: SiteHold }
  | { kind: "LEASE" }
  | { kind: "RESERVED" }
  | { kind: "NOT_FOR_RENT" }
  | { kind: "CLOSED" };

const CLOSED_STATUSES = ["UNDER_MAINTENANCE", "OUT_OF_SERVICE"];

/** A booking that still holds its nights (a guest who left keeps the square, shown done). */
function holds(booking: CalendarBooking, day: string): boolean {
  return booking.check_in_on <= day && day < booking.check_out_on;
}

function siteHolds(hold: SiteHold, day: string): boolean {
  return hold.start_on <= day && day < hold.end_on;
}

export function nightOf(unit: CalendarUnit, day: string): Night {
  const booking = unit.bookings.find((entry) => holds(entry, day));
  const hold = unit.site_holds.find((entry) => siteHolds(entry, day));
  if (booking !== undefined)
    return {
      kind: "BOOKING",
      booking,
      first: booking.check_in_on === day,
      clash: hold?.clash ? hold : null,
    };
  if (hold !== undefined) return { kind: "HOLD", hold };
  if (
    unit.leases.some(
      (lease) => lease.start_date <= day && day <= lease.end_date,
    )
  )
    return { kind: "LEASE" };
  if (!unit.for_rent) return { kind: "NOT_FOR_RENT" };
  if (CLOSED_STATUSES.includes(unit.status)) return { kind: "CLOSED" };
  if (unit.reserved) return { kind: "RESERVED" };
  return { kind: "FREE" };
}

/** May this Unit be booked for every night from check-in to check-out? A booking from a booking
 * site may take the nights that same site holds (it is that guest). */
export function freeForStay(
  unit: CalendarUnit,
  checkIn: string,
  checkOut: string,
  site: string | null = null,
): boolean {
  if (!unit.for_rent || unit.reserved || CLOSED_STATUSES.includes(unit.status))
    return false;
  const taken = unit.bookings.some(
    (booking) =>
      (booking.status === "BOOKED" || booking.status === "CHECKED_IN") &&
      booking.check_in_on < checkOut &&
      checkIn < booking.check_out_on,
  );
  const leased = unit.leases.some(
    (lease) => lease.start_date < checkOut && checkIn <= lease.end_date,
  );
  const held = unit.site_holds.some(
    (hold) =>
      hold.start_on < checkOut &&
      checkIn < hold.end_on &&
      hold.site_name.toLowerCase() !== (site ?? "").toLowerCase(),
  );
  return !taken && !leased && !held;
}
