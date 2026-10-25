// V1-058 R3: what the Letters screen reads and how it counts the days of a Rent letter.

import type { LeaseResource } from "../leaseClient";
import { addDays, daysBetween } from "../reservations/reservationsData";
import type {
  LeaseWarning,
  LettersApi,
  RentAlert,
  RentLetterEvent,
} from "./lettersClient";
import { storedText } from "./text";

// Owner 2026-10-25: a letter may be given on paper, or sent by email, Telegram or WhatsApp.
export const HOWS = ["HAND", "DOOR", "EMAIL", "TG", "WA", "OTHER"] as const;
export type How = (typeof HOWS)[number];

/** How a letter or warning was given, kept with the record as "Handed to the tenant: …". */
export function howRecord(how: How, details: string): string {
  const label = storedText(`h_${how}`);
  return details === "" ? label : `${label}: ${details}`;
}

/** Reads back how a letter or warning was given; null when it was written another way. */
export function howOf(record: string | null): {
  how: How | null;
  details: string;
} {
  if (record === null) return { how: null, details: "" };
  for (const how of HOWS) {
    const label = storedText(`h_${how}`);
    if (record === label) return { how, details: "" };
    if (record.startsWith(`${label}: `))
      return { how, details: record.slice(label.length + 2) };
  }
  return { how: null, details: record };
}

/**
 * The 1st of the Rent month. Rent is billed for the month its Due Date falls in (issued on
 * the 25th, due on the 5th), and day 1 is the 1st of that month (BR-LEASE-026).
 */
export function rentMonthStart(dueDate: string): string {
  return `${dueDate.slice(0, 8)}01`;
}

/** The day of a letter: day N is N - 1 days after the 1st of the Rent month (day 30 of
 * February is 1 or 2 March). */
export function letterDay(monthStart: string, day: 20 | 30): string {
  return addDays(monthStart, day - 1);
}

export function dayNumber(monthStart: string, businessDate: string): number {
  return daysBetween(monthStart, businessDate) + 1;
}

export interface RentRow {
  alert: RentAlert;
  lease: LeaseResource | undefined;
  monthStart: string;
  /** The letters already given, or null when they could not be read. */
  letters: { d20: RentLetterEvent | null; d30: RentLetterEvent | null } | null;
}

export interface RentLetters {
  rows: RentRow[];
  businessDate: string;
}

export async function loadRentLetters(
  api: Pick<LettersApi, "alerts" | "events">,
  propertyId: string,
  leases: LeaseResource[],
): Promise<RentLetters> {
  const alerts = await api.alerts(propertyId);
  const byId = new Map(leases.map((lease) => [lease.lease_id, lease]));
  const rows = await Promise.all(
    alerts.items.map(async (alert): Promise<RentRow> => {
      const monthStart = rentMonthStart(alert.due_date);
      const lease = byId.get(alert.lease_id);
      if (alert.case_id === null)
        return { alert, lease, monthStart, letters: { d20: null, d30: null } };
      try {
        const events = await api.events(alert.case_id);
        const find = (kind: RentLetterEvent["event_kind"]) =>
          events.find((event) => event.event_kind === kind) ?? null;
        return {
          alert,
          lease,
          monthStart,
          letters: {
            d20: find("TWENTY_DAY_WARNING"),
            d30: find("THIRTY_DAY_SERIOUS_DEFAULT"),
          },
        };
      } catch {
        return { alert, lease, monthStart, letters: null };
      }
    }),
  );
  rows.sort(
    (a, b) =>
      a.monthStart.localeCompare(b.monthStart) ||
      (a.lease?.unit_number ?? "").localeCompare(b.lease?.unit_number ?? ""),
  );
  return { rows, businessDate: alerts.business_date };
}

/** The letter to record next, if one is due and not given. */
export function nextLetter(row: RentRow): 20 | 30 | null {
  const a = row.alert.assessment;
  if (a.twenty_day_warning_eligible && !a.warning_recorded) return 20;
  if (a.thirty_day_default_eligible && !a.serious_default_recorded) return 30;
  return null;
}

/** A Lease that may be warned: signed, moved in, and not ended. */
export function warnable(lease: LeaseResource, today: string): boolean {
  return (
    lease.status === "SIGNED" &&
    lease.actual_termination_date === null &&
    lease.occupancies.length > 0 &&
    (lease.end_date === null || lease.end_date >= today)
  );
}

export interface WarningRow {
  lease: LeaseResource;
  warnings: LeaseWarning[];
}

export interface LeaseWarnings {
  rows: WarningRow[];
  /** Leases whose warnings could not be read. */
  failed: LeaseResource[];
}

/** The warnings of every signed Lease, oldest first; Leases without any are left out. */
export async function loadWarnings(
  api: Pick<LettersApi, "warnings">,
  leases: LeaseResource[],
): Promise<LeaseWarnings> {
  const signed = leases.filter(
    (lease) => lease.status === "SIGNED" || lease.status === "TERMINATED",
  );
  const results = await Promise.allSettled(
    signed.map((lease) => api.warnings(lease.lease_id)),
  );
  const rows: WarningRow[] = [];
  const failed: LeaseResource[] = [];
  results.forEach((result, index) => {
    const lease = signed[index];
    if (lease === undefined) return;
    if (result.status === "rejected") {
      failed.push(lease);
      return;
    }
    if (result.value.length === 0) return;
    rows.push({
      lease,
      warnings: [...result.value].sort(
        (a, b) => a.warning_sequence - b.warning_sequence,
      ),
    });
  });
  rows.sort((a, b) => a.lease.unit_number.localeCompare(b.lease.unit_number));
  return { rows, failed };
}
