// V1-057 client: the Home page, the reports and their files (API-076 to API-078, DL-072, DL-079).
// Amounts are integer USD cents. A section the person may not read is missing from the answer
// (never zero), so a screen shows a card only when its data is present.

export type HomeSection =
  | "units"
  | "invoices"
  | "payments"
  | "leases"
  | "reservations"
  | "approvals"
  | "deposit_decisions"
  | "readings"
  | "letters"
  | "settlements";

export type TodoGroup = "overdue" | "today" | "this_week" | "later";

export type TodoKind =
  | "overdue_initial_rent"
  | "lease_ending"
  | "reservation_expiring"
  | "draft_waiting"
  | "deposit_decision"
  | "readings_missing"
  | "letter_day_20"
  | "letter_day_30"
  | "settlement_open"
  | "refund_due";

export interface HomeCards {
  units_occupied?: { occupied: number; total: number };
  pending_payment?: { amount_usd_cents: number; invoice_count: number };
  overdue?: { amount_usd_cents: number; invoice_count: number };
  // "Paid for this month": the billed fields come with Invoices, the received fields with
  // Payments; a person may have one part only.
  paid_this_month?: {
    billed_usd_cents?: number;
    billed_paid_usd_cents?: number;
    invoice_count?: number;
    received_usd_cents?: number;
    payment_count?: number;
  };
  lease_renewal?: { count: number; end_on_or_before: string };
  waiting_for_approval?: { count: number };
  meter_readings_missing?: { count: number; reading_date: string };
  letters_due?: { count: number; day_20: number; day_30: number };
}

export interface TodoItem {
  kind: TodoKind;
  date: string;
  group: TodoGroup;
  unit_id?: string;
  unit_number?: string;
  customer_id?: string;
  customer_name?: string;
  lease_id?: string;
  invoice_id?: string;
  invoice_number?: string;
  reservation_id?: string;
  deposit_id?: string;
  draft_id?: string;
  draft_kind?: string;
  final_settlement_id?: string;
  balance_usd_cents?: number;
  held_usd_cents?: number;
  count?: number;
}

export interface HomePage {
  as_of: string;
  business_date: string;
  timezone: string;
  sections: HomeSection[];
  cards: HomeCards;
  todo: TodoItem[];
  todo_counts: Record<TodoGroup, number>;
}

export class ReportsUnavailableError extends Error {
  constructor() {
    super("This information is not available right now.");
    this.name = "ReportsUnavailableError";
  }
}

export class ReportsNotAllowedError extends Error {
  constructor() {
    super("Your account cannot see this.");
    this.name = "ReportsNotAllowedError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function read(path: string): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new ReportsUnavailableError();
  }
  if (response.status === 401 || response.status === 403) {
    throw new ReportsNotAllowedError();
  }
  if (!response.ok) throw new ReportsUnavailableError();
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ReportsUnavailableError();
  }
  if (!isObject(payload) || !isObject(payload.data)) {
    throw new ReportsUnavailableError();
  }
  return payload.data;
}

function homePage(data: Record<string, unknown>): HomePage {
  if (
    typeof data.as_of !== "string" ||
    typeof data.business_date !== "string" ||
    !Array.isArray(data.sections) ||
    !isObject(data.cards) ||
    !Array.isArray(data.todo) ||
    !isObject(data.todo_counts) ||
    !data.todo.every(
      (item) =>
        isObject(item) &&
        typeof item.kind === "string" &&
        typeof item.date === "string" &&
        typeof item.group === "string",
    )
  ) {
    throw new ReportsUnavailableError();
  }
  return data as unknown as HomePage;
}

export const reportsApi = {
  home: async (propertyId: string): Promise<HomePage> =>
    homePage(
      await read(`/api/v1/properties/${encodeURIComponent(propertyId)}/home`),
    ),
};
