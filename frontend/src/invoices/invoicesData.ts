// V1-058 R5: what the Invoices screens read and how they count an Invoice. Invoices name only
// the Customer id and the Lease id, so the Customer names and the Units come from the Customer
// and Lease lists; a person who may not read those still sees the Invoices, without names.

import type { CustomerApi } from "../customerClient";
import type {
  InvoiceApi,
  InvoiceCategory,
  InvoiceResource,
  Money,
} from "../invoiceClient";
import type { LeaseApi, LeaseResource } from "../leaseClient";

export interface InvoicesData {
  invoices: InvoiceResource[];
  /** Customer id → name. */
  names: ReadonlyMap<string, string>;
  /** Customer id → phone, for the printed Invoice. */
  phones: ReadonlyMap<string, string>;
  /** Lease id → Unit number. */
  leaseUnits: ReadonlyMap<string, string>;
  /** Customer id → the Unit of their newest signed Lease, for an Invoice with no Lease. */
  customerUnits: ReadonlyMap<string, string>;
  /** Customer id → their newest signed Lease, which a one-time charge is billed under. */
  customerLeases: ReadonlyMap<string, string>;
  /** What the person may do with Invoices, from the server. */
  capabilities: readonly string[];
}

// More pages than this means something is wrong; V1 has one building of a few dozen Units.
const MAX_PAGES = 100;

async function allPages<T>(
  load: (cursor?: string) => Promise<{ items: T[]; next: string | null }>,
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await load(cursor);
    items.push(...result.items);
    if (result.next === null) return items;
    cursor = result.next;
  }
  // Totals from a cut-off list would be wrong, so the page says it could not read them.
  throw new Error("Too many pages");
}

export async function loadInvoicesData(
  apis: {
    invoiceApi: Pick<InvoiceApi, "list">;
    leaseApi: Pick<LeaseApi, "list">;
    customerApi: Pick<CustomerApi, "list">;
  },
  propertyId: string,
): Promise<InvoicesData> {
  let capabilities: string[] = [];
  const [invoices, leases, customers] = await Promise.all([
    allPages(async (cursor) => {
      const page = await apis.invoiceApi.list(
        propertyId,
        cursor === undefined ? {} : { cursor },
      );
      capabilities = page.capabilities;
      return { items: page.items, next: page.next_cursor };
    }),
    // Names are a help, not the record: a refused or failed list leaves them out.
    allPages(async (cursor) => {
      const page = await apis.leaseApi.list(
        propertyId,
        cursor === undefined ? {} : { cursor },
      );
      return { items: page.items, next: page.next_cursor };
    }).catch((): LeaseResource[] => []),
    allPages(async (cursor) => {
      const page = await apis.customerApi.list(
        propertyId,
        cursor === undefined ? {} : { cursor },
      );
      return { items: page.items, next: page.next_cursor };
    }).catch(() => []),
  ]);
  const names = new Map<string, string>();
  const phones = new Map<string, string>();
  for (const customer of customers) {
    names.set(customer.customer_id, customer.legal_name);
    if (customer.phone_number)
      phones.set(customer.customer_id, customer.phone_number);
  }
  const leaseUnits = new Map<string, string>();
  const customerUnits = new Map<string, string>();
  const customerLeases = new Map<string, string>();
  // Oldest first, so the newest signed Lease of a Customer is the one kept.
  const byStart = [...leases].sort((left, right) =>
    (left.start_date ?? "").localeCompare(right.start_date ?? ""),
  );
  for (const lease of byStart) {
    leaseUnits.set(lease.lease_id, lease.unit_number);
    if (!names.has(lease.primary_tenant_id))
      names.set(lease.primary_tenant_id, lease.primary_tenant_name);
    if (lease.status !== "DRAFTED" && lease.status !== "CANCELLED") {
      customerUnits.set(lease.primary_tenant_id, lease.unit_number);
      customerLeases.set(lease.primary_tenant_id, lease.lease_id);
    }
  }
  return {
    invoices,
    names,
    phones,
    leaseUnits,
    customerUnits,
    customerLeases,
    capabilities,
  };
}

/** "500.00" or "500" as cents; null when it is not a whole-cent amount above zero. */
export function centsOf(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  const [dollars = "0", part = ""] = value.split(".");
  const amount = Number(dollars) * 100 + Number(part.padEnd(2, "0"));
  return amount > 0 ? amount : null;
}

/** Whole cents of an amount; the server sends at most a few thousand dollars per Invoice. */
export function cents(money: Money): number {
  return Number(money.minor_units);
}

export type InvoiceState =
  | "draft"
  | "void"
  | "paid"
  | "overdue"
  | "part"
  | "unpaid";

/**
 * An Invoice is overdue on the day after its Due Date while anything is owed; there is no grace
 * period (BR-INV-051).
 */
export function stateOf(invoice: InvoiceResource, today: string): InvoiceState {
  if (invoice.status === "DRAFT") return "draft";
  if (invoice.status === "VOID") return "void";
  if (invoice.status === "PAID" || cents(invoice.outstanding_balance) <= 0)
    return "paid";
  if (invoice.due_date !== null && invoice.due_date < today) return "overdue";
  return cents(invoice.active_application_total) > 0 ? "part" : "unpaid";
}

/** The four summary cards: every issued Invoice, still owed, overdue, and any amount paid. */
export type InvoiceCard = "all" | "open" | "overdue" | "paid";

export function inCard(
  invoice: InvoiceResource,
  card: InvoiceCard,
  today: string,
): boolean {
  const state = stateOf(invoice, today);
  if (state === "draft" || state === "void") return false;
  if (card === "all") return true;
  if (card === "open") return cents(invoice.outstanding_balance) > 0;
  if (card === "overdue") return state === "overdue";
  return paidOf(invoice) > 0;
}

/** What was paid toward the Invoice, never more than it bills. */
export function paidOf(invoice: InvoiceResource): number {
  return Math.min(
    cents(invoice.adjusted_total),
    cents(invoice.active_application_total),
  );
}

/** The amount on each card for these Invoices. */
export function cardAmount(
  invoices: readonly InvoiceResource[],
  card: InvoiceCard,
  today: string,
): number {
  return invoices
    .filter((invoice) => inCard(invoice, card, today))
    .reduce(
      (sum, invoice) =>
        sum +
        (card === "all"
          ? cents(invoice.adjusted_total)
          : card === "paid"
            ? paidOf(invoice)
            : Math.max(0, cents(invoice.outstanding_balance))),
      0,
    );
}

export type InvoicePeriod = "all" | "month" | "last" | "pick";

/** "2026-10-25" → "2026-09". */
export function monthBefore(month: string): string {
  const year = Number(month.slice(0, 4));
  const number = Number(month.slice(5, 7));
  return number === 1
    ? `${String(year - 1)}-12`
    : `${String(year)}-${String(number - 1).padStart(2, "0")}`;
}

/** The month the period shows, or null for All. A month means the Due Date is in it. */
export function periodMonth(
  period: InvoicePeriod,
  today: string,
  picked: string,
): string | null {
  if (period === "all") return null;
  if (period === "month") return today.slice(0, 7);
  if (period === "last") return monthBefore(today.slice(0, 7));
  return picked;
}

/** The Invoices of the chosen month, type and Customer; Drafts have no Due Date yet. */
export function filtered(
  invoices: readonly InvoiceResource[],
  month: string | null,
  type: InvoiceCategory | "all",
  customerId: string | null,
): InvoiceResource[] {
  return invoices.filter(
    (invoice) =>
      (type === "all" || invoice.category === type) &&
      (customerId === null || invoice.customer_id === customerId) &&
      (month === null || invoice.due_date?.startsWith(month) === true),
  );
}

/** The Unit of an Invoice: its Lease's Unit, else the Customer's Unit. */
export function unitOf(data: InvoicesData, invoice: InvoiceResource): string {
  return (
    (invoice.lease_id !== null
      ? data.leaseUnits.get(invoice.lease_id)
      : undefined) ??
    data.customerUnits.get(invoice.customer_id) ??
    ""
  );
}

/** Newest first by number; the numbers count up, so this is also the order they were made. */
export function sortInvoices(
  invoices: readonly InvoiceResource[],
): InvoiceResource[] {
  return [...invoices].sort(
    (left, right) =>
      right.invoice_date.localeCompare(left.invoice_date) ||
      right.invoice_number.localeCompare(left.invoice_number, undefined, {
        numeric: true,
      }),
  );
}

/** Days from one "yyyy-mm-dd" to another. */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

/** The day after a "yyyy-mm-dd". */
export function dayAfter(day: string): string {
  return new Date(Date.parse(day) + 86_400_000).toISOString().slice(0, 10);
}
