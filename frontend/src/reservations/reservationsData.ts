// V1-058 R3: what the Reservations screens read and how they group a Reservation.

import type { ReservationApi, ReservationResource } from "../reservationClient";

export type ReservationCard = "active" | "ending" | "completed" | "cancelled";

export interface ReservationsData {
  reservations: ReservationResource[];
  canCreate: boolean;
}

// More pages than this means something is wrong; V1 has one building of a few dozen Units.
const MAX_PAGES = 50;

export async function loadReservationsData(
  api: ReservationApi,
  propertyId: string,
): Promise<ReservationsData> {
  const reservations: ReservationResource[] = [];
  let canCreate = false;
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await api.list(propertyId, undefined, cursor);
    reservations.push(...result.items);
    canCreate = result.can_create;
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
  return { reservations, canCreate };
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

/** The suggested Security Deposit: 20% of the agreed Rent, rounded half up to the cent. */
export function suggestedDeposit(rentCents: number): number {
  return Math.floor((rentCents + 2) / 5);
}
