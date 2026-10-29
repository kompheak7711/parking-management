// V1-060 B6: what the Reports screen tests read: report pages shaped as the V1-057 server sends
// them, the Units of a small building, a helper that opens the Reports page on one address,
// and small readers for the tables, headline numbers and bar lists on screen.

import { render } from "@testing-library/react";
import { vi } from "vitest";

import type {
  CreditLedgerRow,
  DepositRow,
  ExportAnswer,
  FinalSettlementRow,
  InvoiceRegisterRow,
  LeaseDatesRow,
  PaymentRegisterRow,
  RegisterFilter,
  RegisterName,
  RegisterPage,
  TotalsPage,
  TotalsReport,
  UnitOccupancyRow,
  UtilityConsumptionRow,
} from "../reportsClient";
import type { Language } from "../signInText";
import {
  type ReportApi,
  ReportsPage,
  type ReportsPageProps,
} from "./ReportsPage";

export const PROPERTY = "property-1";
export const TODAY = "2026-10-28";
/** 10:30 on 28/10/2026 in Phnom Penh. */
export const NOW = Date.parse("2026-10-28T03:30:00Z");

/** The Staff bundle: the operational reads, no money, audit or export rights. */
export const STAFF: ReadonlySet<string> = new Set([
  "payments.read",
  "invoices.read",
  "units.read",
  "leases.read",
  "reservations.read",
  "utility.read",
]);

/** A Manager: Staff plus the money reports, History and exports. */
export const MANAGER: ReadonlySet<string> = new Set([
  ...STAFF,
  "reports.read",
  "audit.view",
  "data.export",
]);

// ---------- the Totals tables ----------

function months(entries: Record<number, number>): (number | null)[] {
  return Array.from({ length: 12 }, (_, index) => entries[index] ?? null);
}

function quantities(entries: Record<number, string>): (string | null)[] {
  return Array.from({ length: 12 }, (_, index) => entries[index] ?? null);
}

const ALL_UNITS = {
  unit_id: null,
  unit_number: null,
  floor: null,
  from: null,
  to: null,
};

export const INCOME: TotalsPage = {
  report: "total_income",
  currency: "USD",
  filter: ALL_UNITS,
  // Oldest first, as a check that the screen puts the newest year on top.
  years: [
    { year: 2025, months: months({ 10: 90000, 11: 95000 }), total: 185000 },
    {
      year: 2026,
      months: months({ 0: 100000, 1: 100000, 9: 98000 }),
      total: 298000,
    },
  ],
  summary: {
    total: 483000,
    highest_month: { month: "2026-01", amount: 100000 },
    highest_unit: { unit_id: "unit-203", unit_number: "U203", amount: 250000 },
    no_unit_amount: 5000,
  },
  chart: {
    months: [
      { month: "2025-11", parts: { rent: 80000, utilities: 10000 } },
      { month: "2025-12", parts: { rent: 80000, utilities: 15000 } },
      {
        month: "2026-01",
        parts: { rent: 80000, utilities: 15000, move_out_and_damage: 5000 },
      },
      { month: "2026-02", parts: { rent: 80000, utilities: 20000 } },
      // "kept_deposit" is a part the screen does not know: it is added to the last part.
      {
        month: "2026-10",
        parts: {
          rent: 80000,
          utilities: 12000,
          other: 4000,
          kept_deposit: 2000,
        },
      },
    ],
    top_units: [
      { unit_id: "unit-203", unit_number: "U203", amount: 250000 },
      { unit_id: "unit-101", unit_number: "U101", amount: 180000 },
      { unit_id: "unit-204", unit_number: "U204", amount: 48000 },
    ],
  },
};

export const INCOME_U203: TotalsPage = {
  ...INCOME,
  filter: { ...ALL_UNITS, unit_id: "unit-203", unit_number: "U203" },
  years: [
    { year: 2025, months: months({ 10: 50000, 11: 52000 }), total: 102000 },
    {
      year: 2026,
      months: months({ 0: 50000, 1: 50000, 9: 48000 }),
      total: 148000,
    },
  ],
  summary: {
    total: 250000,
    highest_month: { month: "2025-12", amount: 52000 },
    highest_unit: { unit_id: "unit-203", unit_number: "U203", amount: 250000 },
    no_unit_amount: 0,
  },
  chart: {
    months: [
      { month: "2025-11", parts: { rent: 45000, utilities: 5000 } },
      { month: "2025-12", parts: { rent: 45000, utilities: 7000 } },
      { month: "2026-01", parts: { rent: 45000, utilities: 5000 } },
      { month: "2026-02", parts: { rent: 45000, utilities: 5000 } },
      { month: "2026-10", parts: { rent: 45000, utilities: 3000 } },
    ],
    top_units: [{ unit_id: "unit-203", unit_number: "U203", amount: 250000 }],
  },
};

export const PAYMENT: TotalsPage = {
  report: "total_payment",
  currency: "USD",
  filter: ALL_UNITS,
  years: [
    { year: 2026, months: months({ 8: 120000, 9: 124483 }), total: 244483 },
  ],
  summary: {
    total: 244483,
    highest_month: { month: "2026-10", amount: 124483 },
    highest_unit: { unit_id: "unit-203", unit_number: "U203", amount: 100000 },
    no_unit_amount: 0,
  },
  chart: {
    months: [
      { month: "2026-09", parts: { paid_to_invoices: 90000, deposits: 30000 } },
      {
        month: "2026-10",
        parts: { paid_to_invoices: 74483, deposits: 30000, other: 20000 },
      },
    ],
    top_units: [{ unit_id: "unit-203", unit_number: "U203", amount: 100000 }],
  },
};

export const ELECTRICITY: TotalsPage = {
  report: "total_electricity",
  currency: "USD",
  filter: ALL_UNITS,
  years: [
    {
      year: 2026,
      months: months({ 8: 29500, 9: 5263 }),
      total: 34763,
      quantities: quantities({ 8: "1180", 9: "210.5" }),
      total_quantity: "1390.5",
      estimate_months: Array.from({ length: 12 }, (_, index) => index === 9),
    },
  ],
  summary: {
    total: 34763,
    highest_month: { month: "2026-09", amount: 29500 },
    highest_unit: { unit_id: "unit-101", unit_number: "U101", amount: 20000 },
    no_unit_amount: 0,
    total_quantity: "1390.5",
    measurement_unit: "KWH",
  },
  chart: {
    months: [
      { month: "2026-09", parts: { reading: 29500 } },
      { month: "2026-10", parts: { reading: 0, estimate: 5263 } },
    ],
    top_units: [
      { unit_id: "unit-101", unit_number: "U101", amount: 20000 },
      { unit_id: "unit-203", unit_number: "U203", amount: 14763 },
    ],
  },
};

export const WATER: TotalsPage = {
  report: "total_water",
  currency: "USD",
  filter: ALL_UNITS,
  years: [
    {
      year: 2026,
      months: months({ 9: 450 }),
      total: 450,
      quantities: quantities({ 9: "4.5" }),
      total_quantity: "4.5",
      estimate_months: Array.from({ length: 12 }, () => false),
    },
  ],
  summary: {
    total: 450,
    highest_month: { month: "2026-10", amount: 450 },
    highest_unit: { unit_id: "unit-101", unit_number: "U101", amount: 450 },
    no_unit_amount: 0,
    total_quantity: "4.5",
    measurement_unit: "M3",
  },
  chart: {
    months: [{ month: "2026-10", parts: { reading: 450 } }],
    top_units: [{ unit_id: "unit-101", unit_number: "U101", amount: 450 }],
  },
};

export const TOTALS: Record<TotalsReport, TotalsPage> = {
  total_income: INCOME,
  total_payment: PAYMENT,
  total_electricity: ELECTRICITY,
  total_water: WATER,
};

// ---------- the registers ----------

const BASE = {
  currency: "USD" as const,
  filter: { floor: null, from: null, to: null, period_applies: true },
  offset: 0,
  limit: 200,
};

const TODAY_ONLY = {
  ...BASE,
  filter: { ...BASE.filter, period_applies: false },
};

export function invoiceRow(
  row: Partial<InvoiceRegisterRow> &
    Pick<InvoiceRegisterRow, "invoice_id" | "invoice_number">,
): InvoiceRegisterRow {
  return {
    status: "UNPAID",
    customer_id: "cust-1",
    customer_name: "Sok Dara",
    lease_id: "lease-1",
    primary_category: "RENT",
    rent_billing_kind: null,
    invoice_date: "2026-10-01",
    due_date: "2026-10-05",
    total_usd_cents: 0,
    paid_usd_cents: 0,
    other_settled_usd_cents: 0,
    owed_usd_cents: 0,
    overdue_days: null,
    unit_id: "unit-203",
    unit_number: "U203",
    floor: "2",
    ...row,
  };
}

export const INVOICES: RegisterPage<"invoice_register"> = {
  ...BASE,
  report: "invoice_register",
  summary: {
    issued_usd_cents: 130000,
    paid_to_invoices_usd_cents: 50000,
    other_settled_usd_cents: 10000,
    owed_usd_cents: 70000,
    invoice_count: 4,
    void_count: 1,
    overdue_groups: {
      days_1_19: { count: 1, owed_usd_cents: 10000 },
      days_20_29: { count: 0, owed_usd_cents: 0 },
      days_30_plus: { count: 1, owed_usd_cents: 50000 },
    },
  },
  chart: {
    months: [
      { month: "2026-09", parts: { owed: 50000, other_settled: 0, paid: 0 } },
      {
        month: "2026-10",
        parts: { owed: 20000, other_settled: 10000, paid: 50000 },
      },
    ],
  },
  totals: {
    total_usd_cents: 130000,
    paid_usd_cents: 50000,
    other_settled_usd_cents: 10000,
    owed_usd_cents: 70000,
  },
  rows: [
    invoiceRow({
      invoice_id: "inv-1",
      invoice_number: "INV-0001",
      invoice_date: "2026-09-01",
      due_date: "2026-09-05",
      total_usd_cents: 50000,
      owed_usd_cents: 50000,
      overdue_days: 53,
      overdue_group: "days_30_plus",
    }),
    invoiceRow({
      invoice_id: "inv-2",
      invoice_number: "INV-0002",
      status: "PARTIALLY_PAID",
      customer_id: "cust-2",
      customer_name: "Chan Sophea",
      lease_id: "lease-3",
      primary_category: "UTILITIES",
      invoice_date: "2026-10-25",
      due_date: "2026-11-01",
      total_usd_cents: 40000,
      paid_usd_cents: 20000,
      other_settled_usd_cents: 10000,
      owed_usd_cents: 10000,
      unit_id: "unit-101",
      unit_number: "U101",
      floor: "1",
    }),
    invoiceRow({
      invoice_id: "inv-3",
      invoice_number: "INV-0003",
      status: "PAID",
      primary_category: "SERVICE_CHARGES",
      total_usd_cents: 30000,
      paid_usd_cents: 30000,
      unit_id: "unit-204",
      unit_number: "U204",
    }),
    invoiceRow({
      invoice_id: "inv-4",
      invoice_number: "INV-0004",
      status: "VOID",
      customer_id: "cust-3",
      customer_name: "Keo Mony",
      lease_id: null,
      primary_category: "DAMAGE_CHARGES",
      invoice_date: "2026-10-02",
      due_date: "2026-10-09",
      total_usd_cents: 20000,
      unit_id: null,
      unit_number: null,
      floor: null,
    }),
    invoiceRow({
      invoice_id: "inv-5",
      invoice_number: "INV-0005",
      primary_category: "MISCELLANEOUS_CHARGES",
      invoice_date: "2026-10-20",
      due_date: "2026-10-27",
      total_usd_cents: 10000,
      owed_usd_cents: 10000,
      overdue_days: 1,
      overdue_group: "days_1_19",
    }),
  ],
  row_count: 5,
};

function paymentRow(
  row: Partial<PaymentRegisterRow> &
    Pick<PaymentRegisterRow, "payment_id" | "receipt_number">,
): PaymentRegisterRow {
  return {
    payment_date: "2026-10-03",
    status: "RECEIVED",
    customer_id: "cust-1",
    customer_name: "Sok Dara",
    method_name: "Cash",
    received_currency: "USD",
    received_amount_minor: 0,
    rate_khr_per_usd: null,
    amount_usd_cents: 0,
    reversed_on: null,
    parts: [],
    not_allocated_usd_cents: 0,
    unit_id: "unit-203",
    unit_number: "U203",
    floor: "2",
    ...row,
  };
}

export const PAYMENTS: RegisterPage<"payments"> = {
  ...BASE,
  report: "payments",
  summary: {
    received_usd_cents: 124483,
    lines: {
      INVOICES: 74483,
      LATE_PAYMENT_CHARGES: 2000,
      DEPOSITS: 30000,
      CREDIT: 8000,
      REFUNDED: 0,
      NOT_ALLOCATED: 10000,
      REVERSED_LATER: 0,
    },
    paid_to_invoices_by_category: {
      DAMAGE_CHARGES: 3000,
      MISCELLANEOUS_CHARGES: 2000,
      RENT: 60000,
      SERVICE_CHARGES: 5000,
      UTILITIES: 4483,
    },
    reversals_usd_cents: -40000,
    net_usd_cents: 84483,
    payment_count: 3,
    received_other_currency_minor: { KHR: 184263 },
  },
  chart: {
    months: [
      {
        month: "2026-10",
        parts: { paid_to_invoices: 74483, deposits: 30000, other: 20000 },
      },
    ],
  },
  totals: { amount_usd_cents: 124483, not_allocated_usd_cents: 10000 },
  rows: [
    paymentRow({
      payment_id: "pay-1",
      receipt_number: "RCPT-0001",
      received_amount_minor: 80000,
      amount_usd_cents: 80000,
      parts: [
        {
          kind: "INVOICES",
          category: "RENT",
          unit_id: "unit-203",
          amount_usd_cents: 60000,
        },
        {
          kind: "INVOICES",
          category: "SERVICE_CHARGES",
          unit_id: "unit-203",
          amount_usd_cents: 5000,
        },
        {
          kind: "DEPOSITS",
          category: null,
          unit_id: "unit-203",
          amount_usd_cents: 15000,
        },
      ],
    }),
    paymentRow({
      payment_id: "pay-2",
      receipt_number: "RCPT-0002",
      payment_date: "2026-10-10",
      customer_id: "cust-2",
      customer_name: "Chan Sophea",
      method_name: "ABA",
      received_currency: "KHR",
      received_amount_minor: 184263,
      rate_khr_per_usd: 4110,
      amount_usd_cents: 4483,
      parts: [
        {
          kind: "INVOICES",
          category: "UTILITIES",
          unit_id: "unit-101",
          amount_usd_cents: 4483,
        },
      ],
      unit_id: "unit-101",
      unit_number: "U101",
      floor: "1",
    }),
    paymentRow({
      payment_id: "pay-3",
      receipt_number: "RCPT-0003",
      payment_date: "2026-10-20",
      status: "REVERSED",
      customer_id: "cust-3",
      customer_name: "Keo Mony",
      method_name: "Bank transfer",
      received_amount_minor: 40000,
      amount_usd_cents: 40000,
      reversed_on: "2026-10-22",
      parts: [
        {
          kind: "INVOICES",
          category: "DAMAGE_CHARGES",
          unit_id: "unit-204",
          amount_usd_cents: 3000,
        },
        {
          kind: "INVOICES",
          category: "MISCELLANEOUS_CHARGES",
          unit_id: "unit-204",
          amount_usd_cents: 2000,
        },
        {
          kind: "LATE_PAYMENT_CHARGES",
          category: null,
          unit_id: "unit-204",
          amount_usd_cents: 2000,
        },
        {
          kind: "DEPOSITS",
          category: null,
          unit_id: "unit-204",
          amount_usd_cents: 15000,
        },
        {
          kind: "CREDIT",
          category: null,
          unit_id: null,
          amount_usd_cents: 8000,
        },
        {
          kind: "NOT_ALLOCATED",
          category: null,
          unit_id: null,
          amount_usd_cents: 10000,
        },
      ],
      not_allocated_usd_cents: 10000,
      unit_id: "unit-204",
      unit_number: "U204",
    }),
  ],
  row_count: 3,
};

function utilityRow(
  row: Partial<UtilityConsumptionRow> &
    Pick<UtilityConsumptionRow, "period_id" | "utility_type" | "quantity">,
): UtilityConsumptionRow {
  return {
    period_start: "2026-08-25",
    period_end: "2026-09-24",
    is_estimate: false,
    billed: true,
    unit_id: "unit-101",
    unit_number: "U101",
    floor: "1",
    ...row,
  };
}

export const UTILITY: RegisterPage<"utility_consumption"> = {
  ...BASE,
  report: "utility_consumption",
  summary: {
    electricity_kwh: "1390.5",
    water_m3: "4.5",
    estimate_count: 1,
    period_count: 3,
    electricity_usd_cents: 34763,
    water_usd_cents: 450,
  },
  chart: {
    months: [
      { month: "2026-09", electricity_kwh: "180", water_m3: "4.5" },
      { month: "2026-10", electricity_kwh: "1210.5", water_m3: "0" },
    ],
  },
  totals: {
    electricity_kwh: "1390.5",
    water_m3: "4.5",
    electricity_usd_cents: 34763,
    water_usd_cents: 450,
  },
  rows: [
    utilityRow({
      period_id: "per-1",
      utility_type: "ELECTRICITY",
      quantity: "180",
      amount_usd_cents: 4500,
    }),
    utilityRow({
      period_id: "per-2",
      utility_type: "WATER",
      quantity: "4.5",
      amount_usd_cents: 450,
    }),
    utilityRow({
      period_id: "per-3",
      utility_type: "ELECTRICITY",
      quantity: "1210.5",
      period_start: "2026-09-25",
      period_end: "2026-10-24",
      is_estimate: true,
      billed: false,
      amount_usd_cents: 30263,
      unit_id: "unit-203",
      unit_number: "U203",
      floor: "2",
    }),
  ],
  row_count: 3,
  rates: [
    {
      utility_type: "ELECTRICITY",
      measurement_unit_code: "KWH",
      rate_usd: "0.25",
      effective_date: "2026-01-01",
    },
    {
      utility_type: "WATER",
      measurement_unit_code: "M3",
      rate_usd: "1.00",
      effective_date: "2026-06-01",
    },
  ],
};

/** The same readings for a person without the money right: no amounts and no Rates. */
export const UTILITY_NO_MONEY: RegisterPage<"utility_consumption"> = {
  ...BASE,
  report: "utility_consumption",
  summary: {
    electricity_kwh: "1390.5",
    water_m3: "4.5",
    estimate_count: 1,
    period_count: 3,
  },
  chart: UTILITY.chart,
  totals: { electricity_kwh: "1390.5", water_m3: "4.5" },
  rows: UTILITY.rows.map((row) => {
    const copy = { ...row };
    delete copy.amount_usd_cents;
    return copy;
  }),
  row_count: 3,
};

function creditRow(
  row: Partial<CreditLedgerRow> & Pick<CreditLedgerRow, "credit_id">,
): CreditLedgerRow {
  return {
    customer_id: "cust-1",
    customer_name: "Sok Dara",
    source_payment_id: "pay-3",
    receipt_number: "RCPT-0003",
    recognized_on: "2026-10-20",
    recognized_usd_cents: 0,
    applied_usd_cents: 0,
    refunded_usd_cents: 0,
    reversed_usd_cents: 0,
    available_usd_cents: 0,
    unit_id: "unit-203",
    unit_number: "U203",
    floor: "2",
    ...row,
  };
}

const CREDIT_SUMS = {
  recognized_usd_cents: 10000,
  applied_usd_cents: 3000,
  refunded_usd_cents: 1000,
  reversed_usd_cents: 1000,
  available_usd_cents: 5000,
};

export const CREDITS: RegisterPage<"credit_ledger"> = {
  ...BASE,
  report: "credit_ledger",
  summary: { ...CREDIT_SUMS, credit_count: 2 },
  chart: {
    bars: [
      { key: "recognized", amount: 10000 },
      { key: "applied", amount: 3000 },
      { key: "refunded", amount: 1000 },
      { key: "reversed", amount: 1000 },
      { key: "available", amount: 5000 },
    ],
  },
  totals: CREDIT_SUMS,
  rows: [
    creditRow({
      credit_id: "credit-1",
      recognized_usd_cents: 8000,
      applied_usd_cents: 3000,
      available_usd_cents: 5000,
    }),
    creditRow({
      credit_id: "credit-2",
      customer_id: "cust-2",
      customer_name: "Chan Sophea",
      source_payment_id: "pay-2",
      receipt_number: "RCPT-0002",
      recognized_on: "2026-10-10",
      recognized_usd_cents: 2000,
      refunded_usd_cents: 1000,
      reversed_usd_cents: 1000,
      unit_id: "unit-101",
      unit_number: "U101",
      floor: "1",
    }),
  ],
  row_count: 2,
};

function depositRow(
  row: Partial<DepositRow> & Pick<DepositRow, "deposit_id">,
): DepositRow {
  return {
    deposit_type: "SECURITY",
    lease_id: null,
    reservation_id: null,
    customer_id: "cust-1",
    customer_name: "Sok Dara",
    required_usd_cents: 0,
    received_usd_cents: 0,
    applied_usd_cents: 0,
    kept_usd_cents: 0,
    refunded_usd_cents: 0,
    held_usd_cents: 0,
    record_status: "SIGNED",
    settlement_closed: false,
    unit_id: "unit-203",
    unit_number: "U203",
    floor: "2",
    ...row,
  };
}

const DEPOSIT_SUMS = {
  received_usd_cents: 100000,
  applied_usd_cents: 20000,
  kept_usd_cents: 5000,
  refunded_usd_cents: 15000,
  held_usd_cents: 60000,
};

export const DEPOSITS: RegisterPage<"deposits"> = {
  ...TODAY_ONLY,
  report: "deposits",
  summary: {
    ...DEPOSIT_SUMS,
    held_by_type: { PET: 10000, SECURITY: 50000 },
    deposit_count: 3,
  },
  chart: {
    bars: [
      { key: "received", amount: 100000 },
      { key: "applied", amount: 20000 },
      { key: "kept", amount: 5000 },
      { key: "refunded", amount: 15000 },
      { key: "held", amount: 60000 },
    ],
  },
  totals: DEPOSIT_SUMS,
  rows: [
    depositRow({
      deposit_id: "dep-1",
      lease_id: "lease-1",
      required_usd_cents: 50000,
      received_usd_cents: 50000,
      held_usd_cents: 50000,
    }),
    depositRow({
      deposit_id: "dep-2",
      deposit_type: "PET",
      reservation_id: "res-1",
      customer_id: "cust-2",
      customer_name: "Chan Sophea",
      required_usd_cents: 10000,
      received_usd_cents: 10000,
      held_usd_cents: 10000,
      record_status: "ACTIVE",
      unit_id: "unit-101",
      unit_number: "U101",
      floor: "1",
    }),
    depositRow({
      deposit_id: "dep-3",
      lease_id: "lease-2",
      customer_id: "cust-3",
      customer_name: "Keo Mony",
      required_usd_cents: 40000,
      received_usd_cents: 40000,
      applied_usd_cents: 20000,
      kept_usd_cents: 5000,
      refunded_usd_cents: 15000,
      record_status: "ENDED",
      settlement_closed: true,
      unit_id: "unit-204",
      unit_number: "U204",
    }),
  ],
  row_count: 3,
};

function settlementRow(
  row: Partial<FinalSettlementRow> &
    Pick<FinalSettlementRow, "final_settlement_id" | "lease_id">,
): FinalSettlementRow {
  return {
    customer_id: "cust-3",
    customer_name: "Keo Mony",
    started_on: "2026-08-15",
    move_out_date: null,
    closed_on: null,
    status: "OPEN",
    deposits_applied_usd_cents: 0,
    credit_applied_usd_cents: 0,
    deposits_kept_usd_cents: 0,
    refunded_usd_cents: 0,
    balance_due_usd_cents: null,
    unit_id: "unit-204",
    unit_number: "U204",
    floor: "2",
    ...row,
  };
}

const SETTLEMENT_SUMS = {
  deposits_applied_usd_cents: 20000,
  credit_applied_usd_cents: 0,
  deposits_kept_usd_cents: 5000,
  refunded_usd_cents: 15000,
  balance_due_usd_cents: 0,
};

export const SETTLEMENTS: RegisterPage<"final_settlements"> = {
  ...BASE,
  report: "final_settlements",
  summary: { ...SETTLEMENT_SUMS, open_count: 1, closed_count: 1 },
  chart: {
    bars: [
      { key: "deposits_applied", amount: 20000 },
      { key: "credit_applied", amount: 0 },
      { key: "deposits_kept", amount: 5000 },
      { key: "refunded", amount: 15000 },
      { key: "balance_due", amount: 0 },
    ],
  },
  totals: SETTLEMENT_SUMS,
  rows: [
    settlementRow({
      final_settlement_id: "fs-1",
      lease_id: "lease-2",
      move_out_date: "2026-08-15",
      closed_on: "2026-08-30",
      status: "CLOSED",
      deposits_applied_usd_cents: 20000,
      deposits_kept_usd_cents: 5000,
      refunded_usd_cents: 15000,
      balance_due_usd_cents: 0,
    }),
    settlementRow({
      final_settlement_id: "fs-2",
      lease_id: "lease-5",
      customer_id: "cust-4",
      customer_name: "Mao Vanna",
      started_on: "2026-10-25",
      unit_id: "unit-302",
      unit_number: "U302",
      floor: "3",
    }),
  ],
  row_count: 2,
};

function occupancyRow(
  row: Partial<UnitOccupancyRow> &
    Pick<UnitOccupancyRow, "unit_id" | "unit_number" | "unit_status">,
): UnitOccupancyRow {
  return {
    unit_type: "STUDIO",
    lease_id: null,
    reservation_id: null,
    customer_id: null,
    customer_name: null,
    until_date: null,
    floor: "1",
    ...row,
  };
}

export const OCCUPANCY: RegisterPage<"unit_occupancy"> = {
  ...TODAY_ONLY,
  report: "unit_occupancy",
  summary: {
    occupied: 1,
    reserved: 1,
    vacant: 1,
    not_available: 1,
    unit_count: 4,
  },
  chart: {
    bars: [
      { key: "occupied", count: 1 },
      { key: "reserved", count: 1 },
      { key: "vacant", count: 1 },
      { key: "not_available", count: 1 },
    ],
  },
  totals: null,
  rows: [
    occupancyRow({
      unit_id: "unit-101",
      unit_number: "U101",
      unit_status: "OCCUPIED",
      lease_id: "lease-1",
      customer_id: "cust-1",
      customer_name: "Sok Dara",
      monthly_rent_usd_cents: 45000,
      until_date: "2027-03-31",
    }),
    occupancyRow({
      unit_id: "unit-203",
      unit_number: "U203",
      unit_status: "RESERVED",
      reservation_id: "res-1",
      customer_id: "cust-2",
      customer_name: "Chan Sophea",
      monthly_rent_usd_cents: 50000,
      until_date: "2026-11-15",
      floor: "2",
    }),
    occupancyRow({
      unit_id: "unit-204",
      unit_number: "U204",
      unit_status: "VACANT",
      unit_type: "ONE_BED",
      monthly_rent_usd_cents: 40000,
      floor: "2",
    }),
    occupancyRow({
      unit_id: "unit-302",
      unit_number: "U302",
      unit_status: "UNDER_MAINTENANCE",
      monthly_rent_usd_cents: null,
      floor: "3",
    }),
  ],
  row_count: 4,
};

function leaseRow(
  row: Partial<LeaseDatesRow> &
    Pick<LeaseDatesRow, "lease_id" | "end_date" | "days_to_end">,
): LeaseDatesRow {
  return {
    customer_id: "cust-1",
    customer_name: "Sok Dara",
    status: "SIGNED",
    start_date: "2025-12-01",
    actual_termination_date: null,
    monthly_rent_usd_cents: 45000,
    renewal_drafted: false,
    unit_id: "unit-101",
    unit_number: "U101",
    floor: "1",
    ...row,
  };
}

export const LEASES: RegisterPage<"lease_dates"> = {
  ...BASE,
  report: "lease_dates",
  summary: {
    current_count: 3,
    ending_60_days_count: 2,
    ending_without_renewal_count: 1,
    terminated_count: 1,
  },
  chart: {
    months: [
      { month: "2026-11", count: 1 },
      { month: "2026-12", count: 1 },
      { month: "2027-06", count: 1 },
    ],
  },
  totals: null,
  rows: [
    leaseRow({
      lease_id: "lease-2",
      customer_id: "cust-3",
      customer_name: "Keo Mony",
      status: "TERMINATED",
      start_date: "2025-11-01",
      end_date: "2026-08-15",
      actual_termination_date: "2026-08-15",
      monthly_rent_usd_cents: 40000,
      days_to_end: -74,
      unit_id: "unit-204",
      unit_number: "U204",
      floor: "2",
    }),
    leaseRow({ lease_id: "lease-1", end_date: "2026-11-30", days_to_end: 33 }),
    leaseRow({
      lease_id: "lease-3",
      customer_id: "cust-2",
      customer_name: "Chan Sophea",
      start_date: "2026-01-01",
      end_date: "2026-12-20",
      monthly_rent_usd_cents: 50000,
      days_to_end: 53,
      renewal_drafted: true,
      unit_id: "unit-203",
      unit_number: "U203",
      floor: "2",
    }),
    leaseRow({
      lease_id: "lease-4",
      customer_id: "cust-4",
      customer_name: "Mao Vanna",
      start_date: "2026-07-01",
      end_date: "2027-06-30",
      days_to_end: 245,
      unit_id: "unit-302",
      unit_number: "U302",
      floor: "3",
    }),
  ],
  row_count: 4,
};

export const AUDIT: RegisterPage<"audit_activity"> = {
  ...BASE,
  report: "audit_activity",
  summary: {
    event_count: 42,
    by_actor: [
      { actor_id: "user-1", name: "Kompheak", count: 30 },
      { actor_id: "system", name: "System", count: 12 },
    ],
    // "invoice" and "invoice_line" are both Invoice in History, so they are added together.
    by_kind: [
      { kind: "invoice", count: 20 },
      { kind: "payment", count: 10 },
      { kind: "unit", count: 7 },
      { kind: "invoice_line", count: 5 },
    ],
  },
  chart: {
    days: [
      { day: "2026-10-26", count: 12 },
      { day: "2026-10-27", count: 30 },
    ],
  },
  totals: { count: 42 },
  rows: [
    { day: "2026-10-27", count: 30 },
    { day: "2026-10-26", count: 12 },
  ],
  row_count: 2,
};

export const REGISTERS: Record<RegisterName, RegisterPage<RegisterName>> = {
  invoice_register: INVOICES,
  payments: PAYMENTS,
  utility_consumption: UTILITY,
  credit_ledger: CREDITS,
  deposits: DEPOSITS,
  final_settlements: SETTLEMENTS,
  unit_occupancy: OCCUPANCY,
  lease_dates: LEASES,
  audit_activity: AUDIT,
};

/** A register with no rows, as the server sends it for an empty period. */
export function emptyPage(name: RegisterName): RegisterPage<RegisterName> {
  return { ...REGISTERS[name], rows: [], row_count: 0 };
}

// ---------- the Units and the page ----------

const UNITS = [
  { unit_id: "unit-203", unit_number: "U203", floor: "2" },
  { unit_id: "unit-101", unit_number: "U101", floor: "1" },
  { unit_id: "unit-204", unit_number: "U204", floor: "2" },
];

const LISTS = {
  lists: {
    FLOOR: [
      { code: "F1", name_en: "1", name_km: null },
      { code: "F2", name_en: "2", name_km: null },
    ],
    UNIT_TYPE: [{ code: "STUDIO", name_en: "Studio", name_km: "ស្ទូឌីយោ" }],
    VIEW: [],
    KITCHEN: [],
    ROOM_FEATURE: [],
    FEATURE_TYPE: [],
    UNIT_FEATURE: [],
    ITEM_TYPE: [],
  },
  can_manage: false,
};

export function unitsApi() {
  return {
    list: vi.fn(() =>
      Promise.resolve({
        items: UNITS,
        next_cursor: null,
        can_manage: false,
      } as never),
    ),
    setupLists: vi.fn(() => Promise.resolve(LISTS as never)),
  };
}

export type RegisterCall = (
  propertyId: string,
  name: RegisterName,
  filter?: RegisterFilter,
) => Promise<RegisterPage<RegisterName>>;

export const SAVED: ExportAnswer = {
  kind: "file",
  exportId: "export-1",
  fileName: "report.xlsx",
  sha256: "abc",
  rowCount: 5,
  file: new Blob(["file"]),
};

export interface OpenOptions {
  /** The address to open, such as "#/reports/total_income". */
  hash?: string;
  language?: Language;
  capabilities?: ReadonlySet<string> | null;
  totals?: ReportApi["totals"];
  register?: RegisterCall;
  exportFile?: ReportApi["exportFile"];
  download?: ReportApi["download"];
}

/** Opens the Reports page on an address, with the fixture pages unless a test gives others. */
export function openReports(options: OpenOptions = {}) {
  window.history.replaceState(null, "", options.hash ?? "#/reports");
  const totals = vi.fn<ReportApi["totals"]>(
    options.totals ?? ((_property, report) => Promise.resolve(TOTALS[report])),
  );
  const register = vi.fn<RegisterCall>(
    options.register ?? ((_property, name) => Promise.resolve(REGISTERS[name])),
  );
  const exportFile = vi.fn<ReportApi["exportFile"]>(
    options.exportFile ?? (() => Promise.resolve(SAVED)),
  );
  const download = vi.fn<ReportApi["download"]>(
    options.download ??
      (() =>
        Promise.resolve({
          fileName: "report.xlsx",
          sha256: "abc",
          file: new Blob(["file"]),
        })),
  );
  const api: ReportApi = {
    totals,
    register: register as unknown as ReportApi["register"],
    exportFile,
    download,
  };
  const units = unitsApi();
  let props: ReportsPageProps = {
    active: true,
    api,
    capabilities:
      options.capabilities === undefined ? null : options.capabilities,
    language: options.language ?? "en",
    now: () => NOW,
    propertyId: PROPERTY,
    today: TODAY,
    units,
  };
  const view = render(<ReportsPage {...props} />);
  return {
    totals,
    register,
    exportFile,
    download,
    units,
    /** Draws the page again with some props changed; the API and clock stay the same. */
    rerender(changes: Partial<ReportsPageProps>) {
      props = { ...props, ...changes };
      view.rerender(<ReportsPage {...props} />);
    },
  };
}

// ---------- reading the screen ----------

function cells(row: Element): string[] {
  return [...row.querySelectorAll("th, td")].map((cell) => cell.textContent);
}

/** The text of each cell of each body row. */
export function bodyRows(table: HTMLElement): string[][] {
  return [...table.querySelectorAll("tbody tr")].map(cells);
}

/** The text of the head row. */
export function headRow(table: HTMLElement): string[] {
  const row = table.querySelector("thead tr");
  return row === null ? [] : cells(row);
}

/** The text of the footer total. */
export function footRow(table: HTMLElement): string[] {
  const row = table.querySelector("tfoot tr");
  return row === null ? [] : cells(row);
}

/** The headline numbers of a Summary card: each label with its value and any note. */
export function facts(summary: HTMLElement): string[][] {
  const list = summary.querySelector("dl");
  const out: string[][] = [];
  for (const item of list === null ? [] : [...list.children]) {
    if (item.tagName === "DT") out.push([item.textContent]);
    else out[out.length - 1]?.push(item.textContent);
  }
  return out;
}

/** The label and value of each bar of the bar list with this title. */
export function barRows(container: HTMLElement, title: string): string[][] {
  const caption = [...container.querySelectorAll("figcaption")].find(
    (element) => element.textContent === title,
  );
  const figure = caption?.closest("figure");
  if (figure === null || figure === undefined) return [];
  return [...figure.querySelectorAll("li")].map((item) => [
    item.querySelector(".rp-hc-l")?.textContent ?? "",
    item.querySelector(".rp-hc-v")?.textContent ?? "",
  ]);
}
