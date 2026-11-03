// V1-058 R3: what the Reservations screens read and how they group a Reservation.

import {
  EARLIER_RESERVATION_RULES,
  type ReservationApi,
  type ReservationResource,
  type ReservationRules,
} from "../reservationClient";

export type ReservationCard = "active" | "ending" | "completed" | "cancelled";

export interface ReservationsData {
  reservations: ReservationResource[];
  canCreate: boolean;
  /** V1.1 step 2b (DL-119): today's Reservation rules. */
  rules: ReservationRules;
}

// More pages than this means something is wrong; V1 has one building of a few dozen Units.
const MAX_PAGES = 50;

export async function loadReservationsData(
  api: ReservationApi,
  propertyId: string,
): Promise<ReservationsData> {
  const reservations: ReservationResource[] = [];
  let canCreate = false;
  let rules = EARLIER_RESERVATION_RULES;
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await api.list(propertyId, undefined, cursor);
    reservations.push(...result.items);
    canCreate = result.can_create;
    rules = result.rules ?? rules;
    if (result.next_cursor === null) break;
    cursor = result.next_cursor;
  }
  // Active first, then the newest.
  const order = { ACTIVE: 0, COMPLETED: 1, CANCELLED: 2 } as const;
  reservations.sort(
    (left, right) =>
      order[left.status] - order[right.status] ||
      right.reservation_date.localeCompare(left.reservation_date),
  );
  return { reservations, canCreate, rules };
}

/** Whole days from `from` to `to`, both "yyyy-mm-dd". */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

export function addDays(day: string, days: number): string {
  return new Date(Date.parse(day) + days * 86_400_000)
    .toISOString()
    .slice(0, 10);
}

export function daysLeft(reservation: ReservationResource, today: string) {
  return daysBetween(today, reservation.effective_expiration_date);
}

/** "Ending within 7 days" counts Active ones too; the card filter uses this test. */
export function isEnding(
  reservation: ReservationResource,
  today: string,
): boolean {
  return reservation.status === "ACTIVE" && daysLeft(reservation, today) <= 7;
}

export function cardOf(reservation: ReservationResource): ReservationCard {
  if (reservation.status === "ACTIVE") return "active";
  if (reservation.status === "COMPLETED") return "completed";
  return "cancelled";
}

export type ResultKind = "lease" | "expired" | "customer" | "property" | null;

export function resultOf(reservation: ReservationResource): ResultKind {
  if (reservation.status === "COMPLETED") return "lease";
  if (reservation.status !== "CANCELLED") return null;
  if (reservation.cancellation_reason_code === "RESERVATION_EXPIRED")
    return "expired";
  return reservation.cancellation_responsibility === "PROPERTY"
    ? "property"
    : "customer";
}

/** The suggested Security Deposit: the rule's share of the agreed Rent (20% before V1.1),
 * rounded half up to the cent, as the server works it out. */
export function suggestedDeposit(
  rentCents: number,
  rateBasisPoints: number = EARLIER_RESERVATION_RULES.deposit_rate_basis_points,
): number {
  return Math.floor((rentCents * rateBasisPoints + 5000) / 10000);
}

/** A rate in hundredths of a percent as the screen shows it: 2000 is "20%". */
export function percentText(rateBasisPoints: number): string {
  return `${String(rateBasisPoints / 100)}%`;
}
