// V1-058 R3: what the Leases screens read and how they group a Lease.

import type { DepositApi, DepositResource } from "../depositClient";
import type { LeaseApi, LeaseResource } from "../leaseClient";
import { addDays, daysBetween } from "../reservations/reservationsData";

export type LeaseKind =
  | "current"
  | "ending"
  | "draft"
  | "ended"
  | "terminated"
  | "cancelled";
export type LeaseCard = "current" | "ending" | "draft" | "ended";

/** The Security Deposit amounts of one Lease, or why they are not shown. */
export type DepositCell =
  | { state: "shown"; required: number; received: number }
  | { state: "none" | "hidden" | "failed" };

export interface LeasesData {
  leases: LeaseResource[];
  canCreate: boolean;
}

// More pages than this means something is wrong; V1 has one building of a few dozen Units.
const MAX_PAGES = 50;

export async function loadLeasesData(
  api: LeaseApi,
  propertyId: string,
): Promise<LeasesData> {
  const leases: LeaseResource[] = [];
  let canCreate = false;
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await api.list(
      propertyId,
      cursor === undefined ? undefined : { cursor },
    );
    leases.push(...result.items);
    canCreate = result.can_create;
    if (result.next_cursor === null) break;
    cursor = result.next_cursor;
  }
  return { leases, canCreate };
}

/** "Ending soon" looks two months ahead, as Home does. */
export function endingLimit(today: string): string {
  const [year, month, day] = today.split("-").map(Number) as [
    number,
    number,
    number,
  ];
  const target = new Date(Date.UTC(year, month + 1, 1));
  const last = new Date(
    Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0),
  ).getUTCDate();
  target.setUTCDate(Math.min(day, last));
  return target.toISOString().slice(0, 10);
}

/** A Lease that a later Lease renews (not counting a cancelled draft). */
export function renewedIds(leases: LeaseResource[]): Set<string> {
  return new Set(
    leases.flatMap((lease) =>
      lease.status === "CANCELLED" || lease.predecessor_lease_id === null
        ? []
        : [lease.predecessor_lease_id],
    ),
  );
}

export function kindOf(
  lease: LeaseResource,
  today: string,
  renewed: boolean,
): LeaseKind {
  if (lease.status === "DRAFTED") return "draft";
  if (lease.status === "CANCELLED") return "cancelled";
  if (lease.status === "TERMINATED") return "terminated";
  if (lease.end_date !== null && lease.end_date < today) return "ended";
  if (
    !renewed &&
    lease.end_date !== null &&
    lease.end_date < endingLimit(today)
  )
    return "ending";
  return "current";
}

export function cardsOf(kind: LeaseKind): LeaseCard[] {
  if (kind === "ending") return ["current", "ending"];
  if (kind === "current" || kind === "draft") return [kind];
  return ["ended"];
}

/** Current Leases first (soonest End Date first), then drafts, then the newest ended. */
export function sortLeases(
  leases: LeaseResource[],
  today: string,
): LeaseResource[] {
  const renewed = renewedIds(leases);
  const rank = (lease: LeaseResource) =>
    ({
      ending: 0,
      current: 0,
      draft: 1,
      ended: 2,
      terminated: 2,
      cancelled: 2,
    })[kindOf(lease, today, renewed.has(lease.lease_id))];
  return [...leases].sort((left, right) => {
    const order = rank(left) - rank(right);
    if (order !== 0) return order;
    const leftEnd = left.actual_termination_date ?? left.end_date ?? "";
    const rightEnd = right.actual_termination_date ?? right.end_date ?? "";
    return rank(left) === 0
      ? leftEnd.localeCompare(rightEnd) ||
          left.unit_number.localeCompare(right.unit_number)
      : rightEnd.localeCompare(leftEnd) ||
          right.created_at.localeCompare(left.created_at);
  });
}

export function securityOf(
  deposits: DepositResource[],
): DepositResource | null {
  return (
    deposits.find((deposit) => deposit.deposit_type === "SECURITY") ?? null
  );
}

/**
 * The Security Deposit of each draft or running Lease, read a few at a time. An ended Lease
 * shows a dash: its deposits belong to the Move-out page.
 */
export async function loadDepositCells(
  api: DepositApi,
  leases: LeaseResource[],
  canRead: boolean,
): Promise<Map<string, DepositCell>> {
  const cells = new Map<string, DepositCell>();
  const wanted = leases.filter(
    (lease) => lease.status === "DRAFTED" || lease.status === "SIGNED",
  );
  if (!canRead) {
    for (const lease of wanted) cells.set(lease.lease_id, { state: "hidden" });
    return cells;
  }
  let next = 0;
  async function worker() {
    for (;;) {
      const lease = wanted.at(next);
      next += 1;
      if (lease === undefined) return;
      try {
        const security = securityOf(
          (await api.leaseDeposits(lease.lease_id)).items,
        );
        cells.set(
          lease.lease_id,
          security === null
            ? { state: "none" }
            : {
                state: "shown",
                required: security.required_usd_cents,
                received: security.received_usd_cents,
              },
        );
      } catch {
        cells.set(lease.lease_id, { state: "failed" });
      }
    }
  }
  await Promise.all(Array.from({ length: 6 }, worker));
  return cells;
}

export interface InitialRent {
  /** Days billed in the first month (from the Start Date to the month end). */
  days: number;
  daysInMonth: number;
  firstPart: number;
  /** The whole next month when the Lease starts on day 21 or later. */
  nextMonth: number;
  total: number;
  due: string;
}

/**
 * The Initial Rent by the rules: the first month is prorated by inclusive days, rounded half
 * up to the cent; a Start Date on day 21 or later adds the whole next month; due 5 days after
 * the Start Date (BR-RENT-005 to BR-RENT-009, BR-MONEY-012).
 */
export function initialRent(start: string, rent: number): InitialRent {
  const [year, month, day] = start.split("-").map(Number) as [
    number,
    number,
    number,
  ];
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const days = daysInMonth - day + 1;
  const firstPart =
    days === daysInMonth
      ? rent
      : Math.floor((2 * rent * days + daysInMonth) / (2 * daysInMonth));
  const nextMonth = day >= 21 ? rent : 0;
  return {
    days,
    daysInMonth,
    firstPart,
    nextMonth,
    total: firstPart + nextMonth,
    due: addDays(start, 5),
  };
}

export { addDays, daysBetween };
