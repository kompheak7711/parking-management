// V1-058 R3: what the Letters screen reads and how it counts the days of a Rent letter.

import type { LeaseResource } from "../leaseClient";
import { addDays, daysBetween } from "../reservations/reservationsData";
import type {
  LeaseWarning,
  LetterKind,
  LettersApi,
  RentAlert,
  RentAssessment,
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

// DL-237 (owner 13 Nov 2026): notices on day 10, 20 and 25 of the Rent month, then the
// termination letter on day 30.
export const NOTICE_STEPS = [10, 20, 25] as const;
export const STEPS = [...NOTICE_STEPS, 30] as const;
export type Step = (typeof STEPS)[number];
export type NoticeStep = (typeof NOTICE_STEPS)[number];

export const STEP_KIND: Record<Step, LetterKind> = {
  10: "TEN_DAY_NOTICE",
  20: "TWENTY_DAY_WARNING",
  25: "TWENTY_FIVE_DAY_NOTICE",
  30: "THIRTY_DAY_SERIOUS_DEFAULT",
};

/** The step is on the case. */
export function stepGiven(a: RentAssessment, step: Step): boolean {
  if (step === 10) return a.ten_day_notice_recorded;
  if (step === 20) return a.warning_recorded;
  if (step === 25) return a.twenty_five_day_notice_recorded;
  return a.serious_default_recorded;
}

/** The server says the step may be recorded now (its day has come and the Rent is unpaid). */
export function stepDue(a: RentAssessment, step: Step): boolean {
  if (step === 10) return a.ten_day_notice_eligible;
  if (step === 20) return a.twenty_day_warning_eligible;
  if (step === 25) return a.twenty_five_day_notice_eligible;
  return a.thirty_day_default_eligible;
}

export function noticesGiven(a: RentAssessment): boolean {
  return NOTICE_STEPS.every((step) => stepGiven(a, step));
}

export function dayNumber(monthStart: string, businessDate: string): number {
  return daysBetween(monthStart, businessDate) + 1;
}

// What is stored with a termination notice for unpaid Rent, in English like every stored
// record. The Lease page's Terminate reuses the notice's own provision and grounds.
export const NOTICE_PROVISION =
  "Signed Lease: Rent not paid after the notices of day 10, day 20 and day 25 (BR-LEASE-026)";
export const NOTICE_GROUNDS =
  "Rent unpaid on day 30 after the three notices (DL-237)";
export const NOTICE_TERMS = "The Lease ends on the date written in the notice";
export const NOTICE_REASON = "Termination notice given";
export const NOTICE_AUTHORITY =
  "Approved in the app by the signed-in Owner or Manager (leases.terminate)";

export interface RentRow {
  alert: RentAlert;
  lease: LeaseResource | undefined;
  monthStart: string;
  /** The letters already given, or null when they could not be read. */
  letters: Record<Step, RentLetterEvent | null> | null;
}

const NO_LETTERS: Record<Step, RentLetterEvent | null> = {
  10: null,
  20: null,
  25: null,
  30: null,
};

/**
 * The first day of a step. The server counts it: day N is N - 1 days after the 1st of the Rent
 * month (day 30 of February is 1 or 2 March), and no step comes before the Due Date has passed.
 */
export function stepDay(row: RentRow, step: Step): string {
  const counted = row.alert.assessment.step_days?.[STEP_KIND[step]];
  if (counted !== undefined) return counted;
  const byMonth = addDays(row.monthStart, step - 1);
  const afterDue = addDays(row.alert.due_date, 1);
  return byMonth > afterDue ? byMonth : afterDue;
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
        return { alert, lease, monthStart, letters: NO_LETTERS };
      try {
        const events = await api.events(alert.case_id);
        const find = (kind: RentLetterEvent["event_kind"]) =>
          events.find((event) => event.event_kind === kind) ?? null;
        return {
          alert,
          lease,
          monthStart,
          letters: {
            10: find(STEP_KIND[10]),
            20: find(STEP_KIND[20]),
            25: find(STEP_KIND[25]),
            30: find(STEP_KIND[30]),
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

function dueNotice(a: RentAssessment): NoticeStep | null {
  return (
    NOTICE_STEPS.find((step) => stepDue(a, step) && !stepGiven(a, step)) ?? null
  );
}

/**
 * The step a person does now. The termination letter always waits for a person. The notices
 * of a tenant with a Tenant-bot link go by themselves, so only a tenant without one is listed.
 */
export function nextLetter(row: RentRow): Step | null {
  const a = row.alert.assessment;
  if (a.thirty_day_default_eligible && !a.serious_default_recorded) return 30;
  return a.telegram_linked ? null : dueNotice(a);
}

/** The notice the Tenant bot sends by itself at 09:00 (a linked tenant only). */
export function botNotice(row: RentRow): NoticeStep | null {
  const a = row.alert.assessment;
  return a.telegram_linked ? dueNotice(a) : null;
}

/** The first step not given yet: the one to wait for when nothing is due today. */
export function waitingStep(row: RentRow): Step | null {
  const a = row.alert.assessment;
  return STEPS.find((step) => !stepGiven(a, step)) ?? null;
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
