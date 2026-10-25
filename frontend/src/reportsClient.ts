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

export type RegisterName =
  | "invoice_register"
  | "payments"
  | "utility_consumption"
  | "credit_ledger"
  | "deposits"
  | "final_settlements"
  | "unit_occupancy"
  | "lease_dates"
  | "audit_activity";

export interface RegisterFilter {
  floor?: string;
  from?: string;
  to?: string;
  offset?: number;
  limit?: number;
}

// Every row with a Unit carries unit_id, unit_number and floor.
interface UnitPart {
  unit_id: string | null;
  unit_number: string | null;
  floor: string | null;
}

export type OverdueGroup = "days_1_19" | "days_20_29" | "days_30_plus";

export interface InvoiceRegisterRow extends UnitPart {
  invoice_id: string;
  invoice_number: string;
  status: string;
  customer_id: string;
  customer_name: string;
  lease_id: string | null;
  primary_category: string;
  rent_billing_kind: string | null;
  invoice_date: string;
  due_date: string;
  total_usd_cents: number;
  paid_usd_cents: number;
  other_settled_usd_cents: number;
  owed_usd_cents: number;
  overdue_days: number | null;
  overdue_group?: OverdueGroup;
}

export type PaymentLine =
  | "INVOICES"
  | "LATE_PAYMENT_CHARGES"
  | "DEPOSITS"
  | "CREDIT"
  | "REFUNDED"
  | "NOT_ALLOCATED"
  | "REVERSED_LATER";

export interface PaymentRegisterRow extends UnitPart {
  payment_id: string;
  receipt_number: string;
  payment_date: string;
  status: string;
  customer_id: string;
  customer_name: string;
  method_name: string;
  // Information only; never added to USD.
  received_currency: string;
  received_amount_minor: number;
  rate_khr_per_usd: number | null;
  amount_usd_cents: number;
  reversed_on: string | null;
  parts: {
    kind: PaymentLine;
    category: string | null;
    unit_id: string | null;
    amount_usd_cents: number;
  }[];
  not_allocated_usd_cents: number;
}

export interface UtilityConsumptionRow extends UnitPart {
  period_id: string;
  utility_type: "ELECTRICITY" | "WATER";
  period_start: string;
  period_end: string;
  quantity: string;
  is_estimate: boolean;
  billed: boolean;
  // Only for people who may read the money reports.
  amount_usd_cents?: number;
}

export interface CreditLedgerRow extends UnitPart {
  credit_id: string;
  customer_id: string;
  customer_name: string;
  source_payment_id: string;
  receipt_number: string;
  recognized_on: string;
  recognized_usd_cents: number;
  applied_usd_cents: number;
  refunded_usd_cents: number;
  reversed_usd_cents: number;
  available_usd_cents: number;
}

export interface DepositRow extends UnitPart {
  deposit_id: string;
  deposit_type: "SECURITY" | "PET";
  lease_id: string | null;
  reservation_id: string | null;
  customer_id: string;
  customer_name: string;
  required_usd_cents: number;
  received_usd_cents: number;
  applied_usd_cents: number;
  kept_usd_cents: number;
  refunded_usd_cents: number;
  held_usd_cents: number;
  record_status: string;
  settlement_closed: boolean;
}

export interface FinalSettlementRow extends UnitPart {
  final_settlement_id: string;
  lease_id: string;
  customer_id: string;
  customer_name: string;
  started_on: string;
  move_out_date: string | null;
  closed_on: string | null;
  status: "OPEN" | "CLOSED";
  deposits_applied_usd_cents: number;
  credit_applied_usd_cents: number;
  deposits_kept_usd_cents: number;
  refunded_usd_cents: number;
  balance_due_usd_cents: number | null;
}

export interface UnitOccupancyRow extends UnitPart {
  unit_status: string;
  unit_type: string;
  lease_id: string | null;
  reservation_id: string | null;
  customer_id: string | null;
  customer_name: string | null;
  monthly_rent_usd_cents: number | null;
  until_date: string | null;
}

export interface LeaseDatesRow extends UnitPart {
  lease_id: string;
  customer_id: string;
  customer_name: string;
  status: "SIGNED" | "TERMINATED";
  start_date: string;
  // The actual termination date when the Lease was ended early.
  end_date: string;
  actual_termination_date: string | null;
  monthly_rent_usd_cents: number;
  days_to_end: number | null;
  renewal_drafted: boolean;
}

export interface AuditActivityRow {
  day: string;
  count: number;
}

export interface RegisterRows {
  invoice_register: InvoiceRegisterRow;
  payments: PaymentRegisterRow;
  utility_consumption: UtilityConsumptionRow;
  credit_ledger: CreditLedgerRow;
  deposits: DepositRow;
  final_settlements: FinalSettlementRow;
  unit_occupancy: UnitOccupancyRow;
  lease_dates: LeaseDatesRow;
  audit_activity: AuditActivityRow;
}

// The summary, chart and totals are worked out over every row of the filter, not only this
// page. Their fields differ by register; see ops/V1_057_PLAN.md.
export interface RegisterPage<N extends RegisterName> {
  report: N;
  currency: "USD";
  filter: {
    floor: string | null;
    from: string | null;
    to: string | null;
    // Unit occupancy and Deposit liability show today; the period does not apply to them.
    period_applies: boolean;
  };
  summary: Record<string, unknown>;
  chart: Record<string, unknown>;
  totals: Record<string, unknown> | null;
  rows: RegisterRows[N][];
  row_count: number;
  offset: number;
  limit: number;
  // Utility consumption only, for people who may read the money reports.
  rates?: {
    utility_type: string;
    measurement_unit_code: string;
    rate_usd: string;
    effective_date: string;
  }[];
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

function registerPage<N extends RegisterName>(
  data: Record<string, unknown>,
): RegisterPage<N> {
  if (
    typeof data.report !== "string" ||
    !Array.isArray(data.rows) ||
    typeof data.row_count !== "number" ||
    !isObject(data.summary) ||
    !isObject(data.chart) ||
    !isObject(data.filter)
  ) {
    throw new ReportsUnavailableError();
  }
  return data as unknown as RegisterPage<N>;
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
  register: async <N extends RegisterName>(
    propertyId: string,
    name: N,
    filter: RegisterFilter = {},
  ): Promise<RegisterPage<N>> =>
    registerPage<N>(
      await read(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/reports/${name}` +
          query({
            floor: filter.floor,
            from: filter.from,
            to: filter.to,
            offset: filter.offset?.toString(),
            limit: filter.limit?.toString(),
          }),
      ),
    ),
};
