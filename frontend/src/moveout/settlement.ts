// V1-058 R3 Move-out M5: the Final Settlement as the Move-out page reads it. The server keeps
// every money rule (DL-032 order, kept Deposits, who may pay what); the page only reads the
// Settlement's state and its preview and shows them in the design's fixed order (DESIGN.md
// "Move-out (round 3)", Statement). Answers are read field by field: a shape the page does not
// know makes the read fail, never a wrong amount.

import type { SettlementRecord } from "../settlementClient";

/** One Lease's Final Settlement: open, waiting for a Manager, or closed. */
export interface SettlementState {
  id: string;
  lease_id: string;
  started_at: string;
  closed: boolean;
  closed_at: string | null;
  /** What the Customers still owed when it closed (stays open; no write-off in V1). */
  closing_balance_due_usd_cents: number | null;
  /** A draft of it waits for a Manager (Waiting for approval). */
  pending_draft: boolean;
}

export interface OwedLine {
  invoice_id: string;
  invoice_line_id: string;
  customer_id: string;
  category: string;
  description: string;
  due_date: string;
  outstanding_usd_cents: number;
  pet_damage: boolean;
}

export interface OwedLateCharge {
  late_payment_charge_id: string;
  source_invoice_id: string;
  customer_id: string;
  remaining_usd_cents: number;
}

export interface SettlementCustomer {
  customer_id: string;
  primary_tenant: boolean;
  invoice_lines: OwedLine[];
  late_payment_charges: OwedLateCharge[];
  open_total_usd_cents: number;
  /** The Customer's Credits with value left, oldest first. */
  credits: { customer_credit_id: string; available_usd_cents: number }[];
  credit_available_usd_cents: number;
  /** The Customer's own Credit pays the Customer's own debt first, up to this. */
  credit_may_use_usd_cents: number;
}

/**
 * DL_032: used in the DL-032 order. KEPT: kept for a forfeiture ground (never a payment).
 * FORFEITURE_REQUIRED: a ground keeps it, but the kept record is not confirmed yet.
 * NOTHING_HELD: a ground keeps it and it holds nothing.
 */
export type DepositPath =
  | "DL_032"
  | "KEPT"
  | "FORFEITURE_REQUIRED"
  | "NOTHING_HELD";

export interface SettlementDeposit {
  deposit_id: string;
  deposit_type: "SECURITY" | "PET";
  customer_id: string | null;
  held_usd_cents: number;
  path: DepositPath;
}

export interface SettlementIssue {
  code: string;
  reason: string | null;
  invoice_id: string | null;
}

export interface SettlementPreview {
  settlement: SettlementState;
  customers: SettlementCustomer[];
  deposits: SettlementDeposit[];
  open_total_usd_cents: number;
  pet_damage_open_usd_cents: number;
  /** Who may let the rest of the Pet Deposit pay other debt (DL-032 step 5). */
  pet_remainder_chosen_by: "CUSTOMER_ONLY" | "CUSTOMER_OR_STAFF_WITH_REASON";
  blocking_issues: SettlementIssue[];
  /** One-time charges whose Invoice was voided and that are not billed again. */
  voided_not_billed_usd_cents: number[];
  ready: boolean;
}

class Unreadable extends Error {
  constructor() {
    super("The Final Settlement answer is not readable.");
    this.name = "SettlementUnreadable";
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function text(value: unknown): string {
  if (typeof value !== "string") throw new Unreadable();
  return value;
}

function textOrNull(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function cents(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw new Unreadable();
  return value;
}

function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw new Unreadable();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Unreadable();
  return value;
}

function object(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Unreadable();
  return value;
}

/**
 * listed: read from the Settlement list, which always says whether a draft waits; the preview
 * and the start answer do not, and the page takes that from the list.
 */
export function readSettlement(
  value: SettlementRecord,
  listed = true,
): SettlementState {
  return {
    id: text(value.id),
    lease_id: text(value.lease_id),
    started_at: text(value.started_at),
    closed: flag(value.closed),
    closed_at: textOrNull(value.closed_at),
    closing_balance_due_usd_cents:
      value.closing_balance_due_usd_cents === null ||
      value.closing_balance_due_usd_cents === undefined
        ? null
        : cents(value.closing_balance_due_usd_cents),
    pending_draft: listed ? flag(value.pending_draft) : false,
  };
}

/** The Lease's Settlement, if one was started: the newest when the read gives more. */
export function settlementOf(
  items: SettlementRecord[],
  leaseId: string,
): SettlementState | null {
  return (
    items
      .map((item) => readSettlement(item))
      .filter((item) => item.lease_id === leaseId)
      .sort((left, right) => right.started_at.localeCompare(left.started_at))
      .at(0) ?? null
  );
}

function readLine(value: unknown): OwedLine {
  const line = object(value);
  return {
    invoice_id: text(line.invoice_id),
    invoice_line_id: text(line.invoice_line_id),
    customer_id: text(line.customer_id),
    category: text(line.category),
    description: text(line.description),
    due_date: text(line.due_date),
    outstanding_usd_cents: cents(line.outstanding_usd_cents),
    pet_damage: flag(line.pet_damage),
  };
}

function readCharge(value: unknown): OwedLateCharge {
  const charge = object(value);
  return {
    late_payment_charge_id: text(charge.late_payment_charge_id),
    source_invoice_id: text(charge.source_invoice_id),
    customer_id: text(charge.customer_id),
    remaining_usd_cents: cents(charge.remaining_usd_cents),
  };
}

function readCustomer(value: unknown): SettlementCustomer {
  const customer = object(value);
  return {
    customer_id: text(customer.customer_id),
    primary_tenant: flag(customer.primary_tenant),
    invoice_lines: list(customer.invoice_lines).map(readLine),
    late_payment_charges: list(customer.late_payment_charges).map(readCharge),
    open_total_usd_cents: cents(customer.open_total_usd_cents),
    credits: list(customer.credits).map((value) => {
      const credit = object(value);
      return {
        customer_credit_id: text(credit.customer_credit_id),
        available_usd_cents: cents(credit.available_usd_cents),
      };
    }),
    credit_available_usd_cents: cents(customer.credit_available_usd_cents),
    credit_may_use_usd_cents: cents(customer.credit_may_use_usd_cents),
  };
}

const PATHS: readonly DepositPath[] = [
  "DL_032",
  "KEPT",
  "FORFEITURE_REQUIRED",
  "NOTHING_HELD",
];

function readDeposit(value: unknown): SettlementDeposit {
  const deposit = object(value);
  const type = deposit.deposit_type;
  const path = deposit.path;
  if (type !== "SECURITY" && type !== "PET") throw new Unreadable();
  if (!PATHS.includes(path as DepositPath)) throw new Unreadable();
  return {
    deposit_id: text(deposit.deposit_id),
    deposit_type: type,
    customer_id: textOrNull(deposit.customer_id),
    held_usd_cents: cents(deposit.held_usd_cents),
    path: path as DepositPath,
  };
}

function readIssue(value: unknown): SettlementIssue {
  const issue = object(value);
  return {
    code: text(issue.code),
    reason: typeof issue.reason === "string" ? issue.reason : null,
    invoice_id: typeof issue.invoice_id === "string" ? issue.invoice_id : null,
  };
}

export function readPreview(value: SettlementRecord): SettlementPreview {
  const steps = list(value.steps).map(object);
  const step = (kind: string) => steps.find((item) => item.kind === kind);
  const chosen = step("PET_DEPOSIT_REMAINDER")?.chosen_by;
  if (chosen !== "CUSTOMER_ONLY" && chosen !== "CUSTOMER_OR_STAFF_WITH_REASON")
    throw new Unreadable();
  return {
    settlement: readSettlement(object(value.settlement), false),
    customers: list(value.customers).map(readCustomer),
    deposits: list(value.deposits).map(readDeposit),
    open_total_usd_cents: cents(value.open_total_usd_cents),
    pet_damage_open_usd_cents: cents(
      step("PET_DEPOSIT_PET_DAMAGE")?.pet_damage_open_usd_cents,
    ),
    pet_remainder_chosen_by: chosen,
    blocking_issues: list(value.blocking_issues).map(readIssue),
    voided_not_billed_usd_cents: list(value.information ?? [])
      .map(object)
      .filter((item) => item.code === "VOIDED_CHARGE_NOT_BILLED_AGAIN")
      .map((item) => cents(item.amount_usd_cents)),
    ready: flag(value.ready),
  };
}

/** Blocking issues of one kind are said once. */
export function issueCodes(issues: SettlementIssue[]): string[] {
  return [...new Set(issues.map((issue) => issue.code))];
}
