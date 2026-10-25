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
  units_occupied?: {
    occupied: number;
    reserved: number;
    vacant: number;
    total: number;
  };
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
  // Money out: Refund and Payment return drafts, which pay money when confirmed.
  waiting_for_approval?: {
    count: number;
    money_out_usd_cents: number;
    money_out_count: number;
  };
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

// The line under the to-do list. The billing fields come with Invoices, the rate with Payments.
export interface HomeJobs {
  last_billing_at?: string | null;
  next_billing_date?: string;
  rate_updated_at?: string | null;
}

export interface HomePage {
  as_of: string;
  business_date: string;
  timezone: string;
  sections: HomeSection[];
  cards: HomeCards;
  jobs: HomeJobs;
  todo: TodoItem[];
  todo_counts: Record<TodoGroup, number>;
}

export type TotalsReport =
  | "total_income"
  | "total_payment"
  | "total_electricity"
  | "total_water";

export interface TotalsFilter {
  unitId?: string;
  floor?: string;
  // dd/mm/yyyy on screen; ISO yyyy-mm-dd here. Only the month of each date counts.
  from?: string;
  to?: string;
}

// One year of a Totals table: twelve months, January first; null is a month with no record
// (shown blank, never zero). Utility tables add the quantity as exact decimal text.
export interface TotalsYear {
  year: number;
  months: (number | null)[];
  total: number;
  quantities?: (string | null)[];
  total_quantity?: string;
  estimate_months?: boolean[];
}

export interface TotalsPage {
  report: TotalsReport;
  currency: "USD";
  filter: {
    unit_id: string | null;
    unit_number: string | null;
    floor: string | null;
    from: string | null;
    to: string | null;
  };
  years: TotalsYear[];
  summary: {
    total: number;
    highest_month: { month: string; amount: number } | null;
    highest_unit: {
      unit_id: string;
      unit_number: string | null;
      amount: number;
    } | null;
    // Money that belongs to no Unit; it counts only in the whole-Property table.
    no_unit_amount: number;
    total_quantity?: string;
    measurement_unit?: "KWH" | "M3";
  };
  chart: {
    // parts: Income rent, utilities, move_out_and_damage, other; Payments paid_to_invoices,
    // deposits, other; Utilities reading, estimate.
    months: { month: string; parts: Record<string, number> }[];
    top_units: {
      unit_id: string;
      unit_number: string | null;
      amount: number;
    }[];
  };
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
    !isObject(data.jobs) ||
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

function totalsPage(data: Record<string, unknown>): TotalsPage {
  if (
    typeof data.report !== "string" ||
    !Array.isArray(data.years) ||
    !isObject(data.summary) ||
    !isObject(data.chart) ||
    !isObject(data.filter) ||
    !data.years.every(
      (year) =>
        isObject(year) &&
        typeof year.year === "number" &&
        Array.isArray(year.months) &&
        year.months.length === 12,
    )
  ) {
    throw new ReportsUnavailableError();
  }
  return data as unknown as TotalsPage;
}

function query(values: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const reportsApi = {
  home: async (propertyId: string): Promise<HomePage> =>
    homePage(
      await read(`/api/v1/properties/${encodeURIComponent(propertyId)}/home`),
    ),
  totals: async (
    propertyId: string,
    report: TotalsReport,
    filter: TotalsFilter = {},
  ): Promise<TotalsPage> =>
    totalsPage(
      await read(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/reports/totals/${report}` +
          query({
            unit_id: filter.unitId,
            floor: filter.floor,
            from: filter.from,
            to: filter.to,
          }),
      ),
    ),
};
