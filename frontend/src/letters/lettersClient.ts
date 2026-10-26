// V1-058 R3: what the Letters screen reads and records (the lease enforcement routes): unpaid
// Rent after day 20, the letters on each case, and the Lease rule warnings of each Lease.

export interface RentAssessment {
  business_date: string;
  remaining_rent: { currency: "USD"; minor_units: number };
  twenty_day_warning_eligible: boolean;
  thirty_day_default_eligible: boolean;
  warning_recorded: boolean;
  serious_default_recorded: boolean;
}

/** One unpaid Rent line from day 20 of its month on. */
export interface RentAlert {
  rent_invoice_line_id: string;
  invoice_id: string;
  invoice_number: string;
  lease_id: string;
  customer_id: string;
  due_date: string;
  case_id: string | null;
  assessment: RentAssessment;
}

export interface RentAlerts {
  items: RentAlert[];
  business_date: string;
}

export type LetterKind = "TWENTY_DAY_WARNING" | "THIRTY_DAY_SERIOUS_DEFAULT";

export interface RentLetterEvent {
  id: string;
  event_kind: LetterKind | "CURE" | "AUTHORIZED_FOLLOW_UP";
  event_date: string;
  notice_document_reference: string | null;
  communication_record: string | null;
}

export interface RentCase {
  id: string;
}

export interface LeaseWarning {
  id: string;
  lease_id: string;
  warning_sequence: number;
  violation_date: string;
  warning_date: string;
  violation_description: string;
  lease_provision: string;
  communication_record: string;
}

export interface WarningContext {
  suggested_sequence: number | null;
  business_date: string;
}

/** A recorded termination notice (DL-073: the third letter). It never ends a Lease by itself. */
export interface TerminationNotice {
  id: string;
  lease_id: string;
  notice_date: string;
  intended_termination_date: string | null;
  notice_text: string;
  governing_lease_provision: string;
  occurred_at: string;
  context: {
    approved_grounds: string;
    notice_period_terms: string;
    evidence_reference: string;
    communication_record: string;
  } | null;
  current_effect: "NOTICE_ONLY" | "SUPERSEDED" | "HISTORICAL_NOTICE_ONLY";
}

export interface TerminationNoticeSource {
  notice_id: string;
  expected_lease_version: number;
  notice_date: string;
  intended_termination_date: string;
  notice_text: string;
  governing_lease_provision: string;
  approved_grounds: string;
  notice_period_terms: string;
  evidence_reference: string;
  communication_record: string;
  authorization_reference: string;
  reason: string;
}

export interface LettersApi {
  alerts: (propertyId: string) => Promise<RentAlerts>;
  events: (caseId: string) => Promise<RentLetterEvent[]>;
  openCase: (
    leaseId: string,
    source: { rent_invoice_line_id: string; reason: string },
    key: string,
  ) => Promise<RentCase>;
  recordLetter: (
    caseId: string,
    source: {
      event_kind: LetterKind;
      reason: string;
      communication_record: string;
      notice_document_reference?: string;
    },
    key: string,
  ) => Promise<RentLetterEvent>;
  warnings: (leaseId: string) => Promise<LeaseWarning[]>;
  warningContext: (leaseId: string) => Promise<WarningContext>;
  recordWarning: (
    leaseId: string,
    source: {
      warning_sequence: number;
      violation_date: string;
      warning_date: string;
      violation_description: string;
      lease_provision: string;
      communication_record: string;
      reason: string;
    },
    key: string,
  ) => Promise<LeaseWarning>;
  notices: (
    propertyId: string,
    leaseId: string,
  ) => Promise<TerminationNotice[]>;
  recordNotice: (
    propertyId: string,
    leaseId: string,
    source: TerminationNoticeSource,
    key: string,
  ) => Promise<TerminationNotice>;
}

/** The record changed meanwhile (or the same key was used for other values): read again. */
export class LettersConflictError extends Error {
  constructor() {
    super("The record changed meanwhile.");
    this.name = "LettersConflictError";
  }
}

/** No answer: the request may or may not have been saved. */
export class LettersUnavailableError extends Error {
  constructor() {
    super("The letters service did not answer.");
    this.name = "LettersUnavailableError";
  }
}

export class LettersRequestError extends Error {
  constructor() {
    super("The letters request was not completed.");
    this.name = "LettersRequestError";
  }
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const value = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (value === undefined) throw new LettersRequestError();
  return decodeURIComponent(value.slice(prefix.length));
}

async function request(path: string, init: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new LettersUnavailableError();
  }
  if (response.status === 409) throw new LettersConflictError();
  if (response.status === 503) throw new LettersUnavailableError();
  if (!response.ok) throw new LettersRequestError();
  const value: unknown = await response.json();
  if (typeof value !== "object" || value === null || !("data" in value))
    throw new LettersRequestError();
  const found = (value as { data: unknown }).data;
  if (typeof found !== "object" || found === null)
    throw new LettersRequestError();
  return found;
}

function itemsOf(value: unknown): unknown[] {
  const items = (value as { items?: unknown }).items;
  if (!Array.isArray(items)) throw new LettersRequestError();
  return items;
}

function command(path: string, source: object, key: string) {
  return request(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": key,
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify(source),
  });
}

const leasePath = (id: string) => `/api/v1/leases/${encodeURIComponent(id)}`;
const noticePath = (propertyId: string, leaseId: string) =>
  `/api/v1/properties/${encodeURIComponent(propertyId)}/leases/${encodeURIComponent(leaseId)}/termination-notices`;
const casePath = (id: string) =>
  `/api/v1/rent-nonpayment-cases/${encodeURIComponent(id)}`;

// More pages than this means something is wrong; V1 has one building of a few dozen Units.
const MAX_PAGES = 50;

export const lettersApi: LettersApi = {
  alerts: async (propertyId) => {
    const items: RentAlert[] = [];
    let businessDate = "";
    let cursor: string | null = null;
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const parameters = new URLSearchParams({ limit: "100" });
      if (cursor !== null) parameters.set("cursor", cursor);
      const found = (await request(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/rent-nonpayment-alerts?${parameters.toString()}`,
        { method: "GET" },
      )) as { next_cursor?: unknown; business_date?: unknown };
      items.push(...(itemsOf(found) as RentAlert[]));
      if (typeof found.business_date !== "string")
        throw new LettersRequestError();
      businessDate = found.business_date;
      cursor = typeof found.next_cursor === "string" ? found.next_cursor : null;
      if (cursor === null) break;
    }
    return { items, business_date: businessDate };
  },
  events: async (caseId) =>
    itemsOf(
      await request(`${casePath(caseId)}/events?limit=100`, { method: "GET" }),
    ) as RentLetterEvent[],
  openCase: async (leaseId, source, key) =>
    (await command(
      `${leasePath(leaseId)}/rent-nonpayment-cases`,
      source,
      key,
    )) as RentCase,
  recordLetter: async (caseId, source, key) =>
    (await command(
      `${casePath(caseId)}/events`,
      source,
      key,
    )) as RentLetterEvent,
  warnings: async (leaseId) =>
    itemsOf(
      await request(`${leasePath(leaseId)}/violation-warnings?limit=100`, {
        method: "GET",
      }),
    ) as LeaseWarning[],
  warningContext: async (leaseId) =>
    (await request(`${leasePath(leaseId)}/violation-warning-context`, {
      method: "GET",
    })) as WarningContext,
  recordWarning: async (leaseId, source, key) =>
    (await command(
      `${leasePath(leaseId)}/violation-warnings`,
      source,
      key,
    )) as LeaseWarning,
  notices: async (propertyId, leaseId) =>
    itemsOf(
      await request(`${noticePath(propertyId, leaseId)}?limit=100`, {
        method: "GET",
      }),
    ) as TerminationNotice[],
  recordNotice: async (propertyId, leaseId, source, key) =>
    (await command(
      noticePath(propertyId, leaseId),
      source,
      key,
    )) as TerminationNotice,
};
