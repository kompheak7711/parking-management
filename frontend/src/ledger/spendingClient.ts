// General Ledger phase 6 step 6 part 2: Expense requests and reports, Expenses and Supplier
// bills. Every role sends requests; the server checks each right, the Expense limit and every
// number, and makes each journal entry. This client only reads and sends.

import {
  LedgerError,
  csrfToken,
  list,
  maybeText,
  record,
  request,
  text,
  whole,
} from "./ledgerClient";

export interface SpendAccount {
  code: string;
  name_en: string;
  name_km: string | null;
  account_type: string;
}

export interface SpendingForm {
  today: string;
  expense_limit_cents: number | null;
  asset_limit_cents: number | null;
  report_days: number;
  bill_days: number;
  rate: { id: string; khr_per_usd: number } | null;
  accounts: SpendAccount[];
  money_accounts: SpendAccount[];
  suppliers: { id: string; name: string }[];
  units: { id: string; unit_number: string }[];
}

export type RequestStatus =
  | "WAITING"
  | "APPROVED"
  | "REFUSED"
  | "PAID_OUT"
  | "DONE"
  | "VOID";
export type PaidHow = "ADVANCE" | "CASH" | "PAY_LATER" | "OWN_MONEY";

export interface ExpenseRequest {
  id: string;
  request_number: string;
  kind: "REQUEST" | "URGENT_REPORT";
  status: RequestStatus;
  requested_by: string;
  requested_by_name: string | null;
  account_code: string;
  account_name: string;
  account_name_km: string | null;
  description: string;
  reason: string;
  amount_cents: number;
  original_currency: "USD" | "KHR";
  original_amount_minor: number | null;
  paid_how: PaidHow;
  paid_from_code: string | null;
  paid_from_name: string | null;
  paid_from_name_km: string | null;
  supplier_name: string | null;
  unit_number: string | null;
  spent_on: string | null;
  decided_at: string | null;
  decision_note: string | null;
  own_spending_note: string | null;
  void_reason: string | null;
  created_at: string;
  is_late: boolean;
  advance_late: boolean;
  owed_to_staff_cents: number;
}

export interface RequestStep {
  step: string;
  note: string | null;
  at: string;
  by_name: string | null;
}

export interface RequestDetail extends ExpenseRequest {
  steps: RequestStep[];
  advance: {
    amount_cents: number;
    paid_on: string;
    entry_number: string | null;
    by_name: string | null;
    from_code: string | null;
  } | null;
  expenses: {
    expense_number: string;
    expense_date: string;
    amount_cents: number;
    bill_number: string | null;
    status: string;
    entry_number: string | null;
    by_name: string | null;
  }[];
  paybacks: {
    paid_on: string;
    amount_cents: number;
    from_code: string;
    entry_number: string | null;
    by_name: string | null;
  }[];
}

export interface ExpenseRow {
  id: string;
  expense_number: string;
  expense_date: string;
  status: string;
  account_code: string;
  account_name: string;
  account_name_km: string | null;
  description: string;
  amount_cents: number;
  paid_from_code: string | null;
  paid_from_name: string | null;
  paid_from_name_km: string | null;
  bill_number: string | null;
  supplier_name: string | null;
  unit_number: string | null;
  request_number: string | null;
  void_reason: string | null;
  entry_number: string | null;
  supplier_bill_number: string | null;
  voided_by_name: string | null;
  voided_at: string | null;
  void_entry_number: string | null;
  /** A "pay later" expense whose supplier bill has a payment not reversed. */
  bill_has_payments: boolean;
}

export interface BillPayment {
  id: string;
  paid_on: string;
  amount_cents: number;
  paid_from_code: string;
  paid_from_name: string | null;
  paid_from_name_km: string | null;
  entry_number: string | null;
  reversed: boolean;
  reversal_reason: string | null;
  reversed_at: string | null;
  reversed_by_name: string | null;
  reversal_entry_number: string | null;
}

export interface SupplierBill {
  id: string;
  bill_number: string;
  status: string;
  supplier_name: string;
  supplier_reference: string | null;
  bill_date: string;
  due_date: string;
  amount_cents: number;
  still_to_pay_cents: number;
  account_code: string | null;
  account_name: string | null;
  account_name_km: string | null;
  entry_number: string | null;
  payments: BillPayment[];
}

export interface NewRequest {
  kind: "REQUEST" | "URGENT_REPORT";
  account_code: string;
  description: string;
  reason: string;
  amount_cents: number;
  currency: "USD" | "KHR";
  original_amount_minor: number | null;
  exchange_rate_record_id: string | null;
  supplier_id: string | null;
  unit_id: string | null;
  spent_on: string | null;
  paid_how: PaidHow;
  paid_from_code: string | null;
}

export interface NewExpense {
  expense_date: string;
  account_code: string;
  description: string;
  amount_cents: number;
  paid_from_code: string | null;
  supplier_id: string | null;
  bill_number: string | null;
  due_date: string | null;
  unit_id: string | null;
}

export interface SpendingApi {
  form: (propertyId: string) => Promise<SpendingForm>;
  requests: (propertyId: string) => Promise<ExpenseRequest[]>;
  request: (
    propertyId: string,
    requestNumber: string,
  ) => Promise<RequestDetail>;
  expenses: (propertyId: string) => Promise<ExpenseRow[]>;
  bills: (propertyId: string) => Promise<SupplierBill[]>;
  addSupplier: (propertyId: string, name: string) => Promise<string>;
  submitRequest: (propertyId: string, body: NewRequest) => Promise<string>;
  decide: (
    propertyId: string,
    requestId: string,
    approve: boolean,
    note: string | null,
  ) => Promise<string>;
  giveAdvance: (
    propertyId: string,
    requestId: string,
    fromCode: string,
    paidOn: string,
  ) => Promise<string>;
  recordBill: (
    propertyId: string,
    requestId: string,
    body: {
      spent_cents: number;
      spent_on: string;
      bill_number: string | null;
      supplier_id: string | null;
      due_date: string | null;
    },
  ) => Promise<string>;
  payBack: (
    propertyId: string,
    requestId: string,
    fromCode: string,
    paidOn: string,
  ) => Promise<string>;
  voidRequest: (
    propertyId: string,
    requestId: string,
    reason: string,
  ) => Promise<string>;
  recordExpense: (propertyId: string, body: NewExpense) => Promise<string>;
  voidExpense: (
    propertyId: string,
    expenseId: string,
    reason: string,
  ) => Promise<string>;
  payBill: (
    propertyId: string,
    billId: string,
    body: { from_code: string; paid_on: string; amount_cents: number },
  ) => Promise<string>;
  reverseBillPayment: (
    propertyId: string,
    paymentId: string,
    reason: string,
  ) => Promise<string>;
}

function root(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}`;
}

function flag(value: unknown): boolean {
  return value === true;
}

function maybeWhole(value: unknown): number | null {
  return value === null || value === undefined ? null : whole(value);
}

function accountOf(value: unknown): SpendAccount {
  const row = record(value);
  return {
    code: text(row.code),
    name_en: text(row.name_en),
    name_km: maybeText(row.name_km),
    account_type: text(row.account_type),
  };
}

const STATUSES: readonly RequestStatus[] = [
  "WAITING",
  "APPROVED",
  "REFUSED",
  "PAID_OUT",
  "DONE",
  "VOID",
];
const PAID_HOW: readonly PaidHow[] = [
  "ADVANCE",
  "CASH",
  "PAY_LATER",
  "OWN_MONEY",
];

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  const found = allowed.find((item) => item === value);
  if (found === undefined) throw new LedgerError();
  return found;
}

function requestOf(value: unknown): ExpenseRequest {
  const row = record(value);
  return {
    id: text(row.id),
    request_number: text(row.request_number),
    kind: oneOf(row.kind, ["REQUEST", "URGENT_REPORT"] as const),
    status: oneOf(row.status, STATUSES),
    requested_by: text(row.requested_by),
    requested_by_name: maybeText(row.requested_by_name),
    account_code: text(row.account_code),
    account_name: text(row.account_name),
    account_name_km: maybeText(row.account_name_km),
    description: text(row.description),
    reason: text(row.reason),
    amount_cents: whole(row.amount_cents),
    original_currency: oneOf(row.original_currency, ["USD", "KHR"] as const),
    original_amount_minor: maybeWhole(row.original_amount_minor),
    paid_how: oneOf(row.paid_how, PAID_HOW),
    paid_from_code: maybeText(row.paid_from_code),
    paid_from_name: maybeText(row.paid_from_name),
    paid_from_name_km: maybeText(row.paid_from_name_km),
    supplier_name: maybeText(row.supplier_name),
    unit_number: maybeText(row.unit_number),
    spent_on: maybeText(row.spent_on),
    decided_at: maybeText(row.decided_at),
    decision_note: maybeText(row.decision_note),
    own_spending_note: maybeText(row.own_spending_note),
    void_reason: maybeText(row.void_reason),
    created_at: text(row.created_at),
    is_late: flag(row.is_late),
    advance_late: flag(row.advance_late),
    owed_to_staff_cents: whole(row.owed_to_staff_cents ?? 0),
  };
}

function detailOf(value: unknown): RequestDetail {
  const row = record(value);
  const advance =
    row.advance === null || row.advance === undefined
      ? null
      : record(row.advance);
  return {
    ...requestOf(row),
    steps: list(row.steps).map((item) => {
      const step = record(item);
      return {
        step: text(step.step),
        note: maybeText(step.note),
        at: text(step.at),
        by_name: maybeText(step.by_name),
      };
    }),
    advance:
      advance === null
        ? null
        : {
            amount_cents: whole(advance.amount_cents),
            paid_on: text(advance.paid_on),
            entry_number: maybeText(advance.entry_number),
            by_name: maybeText(advance.by_name),
            from_code: maybeText(advance.from_code),
          },
    expenses: list(row.expenses).map((item) => {
      const expense = record(item);
      return {
        expense_number: text(expense.expense_number),
        expense_date: text(expense.expense_date),
        amount_cents: whole(expense.amount_cents),
        bill_number: maybeText(expense.bill_number),
        status: text(expense.status),
        entry_number: maybeText(expense.entry_number),
        by_name: maybeText(expense.by_name),
      };
    }),
    paybacks: list(row.paybacks).map((item) => {
      const payback = record(item);
      return {
        paid_on: text(payback.paid_on),
        amount_cents: whole(payback.amount_cents),
        from_code: text(payback.from_code),
        entry_number: maybeText(payback.entry_number),
        by_name: maybeText(payback.by_name),
      };
    }),
  };
}

function expenseOf(value: unknown): ExpenseRow {
  const row = record(value);
  return {
    id: text(row.id),
    expense_number: text(row.expense_number),
    expense_date: text(row.expense_date),
    status: text(row.status),
    account_code: text(row.account_code),
    account_name: text(row.account_name),
    account_name_km: maybeText(row.account_name_km),
    description: text(row.description),
    amount_cents: whole(row.amount_cents),
    paid_from_code: maybeText(row.paid_from_code),
    paid_from_name: maybeText(row.paid_from_name),
    paid_from_name_km: maybeText(row.paid_from_name_km),
    bill_number: maybeText(row.bill_number),
    supplier_name: maybeText(row.supplier_name),
    unit_number: maybeText(row.unit_number),
    request_number: maybeText(row.request_number),
    void_reason: maybeText(row.void_reason),
    entry_number: maybeText(row.entry_number),
    supplier_bill_number: maybeText(row.supplier_bill_number),
    voided_by_name: maybeText(row.voided_by_name),
    voided_at: maybeText(row.voided_at),
    void_entry_number: maybeText(row.void_entry_number),
    bill_has_payments: flag(row.bill_has_payments),
  };
}

function billOf(value: unknown): SupplierBill {
  const row = record(value);
  return {
    id: text(row.id),
    bill_number: text(row.bill_number),
    status: text(row.status),
    supplier_name: text(row.supplier_name),
    supplier_reference: maybeText(row.supplier_reference),
    bill_date: text(row.bill_date),
    due_date: text(row.due_date),
    amount_cents: whole(row.amount_cents),
    still_to_pay_cents: whole(row.still_to_pay_cents),
    account_code: maybeText(row.account_code),
    account_name: maybeText(row.account_name),
    account_name_km: maybeText(row.account_name_km),
    entry_number: maybeText(row.entry_number),
    payments: list(row.payments ?? []).map((item) => {
      const payment = record(item);
      return {
        id: text(payment.id),
        paid_on: text(payment.paid_on),
        amount_cents: whole(payment.amount_cents),
        paid_from_code: text(payment.paid_from_code),
        paid_from_name: maybeText(payment.paid_from_name),
        paid_from_name_km: maybeText(payment.paid_from_name_km),
        entry_number: maybeText(payment.entry_number),
        reversed: flag(payment.reversed),
        reversal_reason: maybeText(payment.reversal_reason),
        reversed_at: maybeText(payment.reversed_at),
        reversed_by_name: maybeText(payment.reversed_by_name),
        reversal_entry_number: maybeText(payment.reversal_entry_number),
      };
    }),
  };
}

async function send(path: string, body: object): Promise<string> {
  const data = record(
    await request(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify(body),
    }),
  );
  return text(data.id);
}

function id(value: string): string {
  return encodeURIComponent(value);
}

export const spendingApi: SpendingApi = {
  async form(propertyId) {
    const data = record(
      await request(`${root(propertyId)}/expense-requests/form`),
    );
    const rate =
      data.rate === null || data.rate === undefined ? null : record(data.rate);
    return {
      today: text(data.today),
      expense_limit_cents: maybeWhole(data.expense_limit_cents),
      asset_limit_cents: maybeWhole(data.asset_limit_cents),
      report_days: whole(data.report_days),
      bill_days: whole(data.bill_days),
      rate:
        rate === null
          ? null
          : { id: text(rate.id), khr_per_usd: whole(rate.khr_per_usd) },
      accounts: list(data.accounts).map(accountOf),
      money_accounts: list(data.money_accounts).map(accountOf),
      suppliers: list(data.suppliers).map((item) => {
        const row = record(item);
        return { id: text(row.id), name: text(row.name) };
      }),
      units: list(data.units).map((item) => {
        const row = record(item);
        return { id: text(row.id), unit_number: text(row.unit_number) };
      }),
    };
  },
  async requests(propertyId) {
    return list(await request(`${root(propertyId)}/expense-requests`)).map(
      requestOf,
    );
  },
  async request(propertyId, requestNumber) {
    return detailOf(
      await request(
        `${root(propertyId)}/expense-requests/${id(requestNumber)}`,
      ),
    );
  },
  async expenses(propertyId) {
    return list(await request(`${root(propertyId)}/ledger/expenses`)).map(
      expenseOf,
    );
  },
  async bills(propertyId) {
    return list(await request(`${root(propertyId)}/ledger/supplier-bills`)).map(
      billOf,
    );
  },
  addSupplier(propertyId, name) {
    return send(`${root(propertyId)}/ledger/suppliers`, { name });
  },
  submitRequest(propertyId, body) {
    return send(`${root(propertyId)}/expense-requests`, body);
  },
  decide(propertyId, requestId, approve, note) {
    return send(
      `${root(propertyId)}/expense-requests/${id(requestId)}/decision`,
      { approve, note },
    );
  },
  giveAdvance(propertyId, requestId, fromCode, paidOn) {
    return send(
      `${root(propertyId)}/expense-requests/${id(requestId)}/advance`,
      { from_code: fromCode, paid_on: paidOn },
    );
  },
  recordBill(propertyId, requestId, body) {
    return send(
      `${root(propertyId)}/expense-requests/${id(requestId)}/bill`,
      body,
    );
  },
  payBack(propertyId, requestId, fromCode, paidOn) {
    return send(
      `${root(propertyId)}/expense-requests/${id(requestId)}/pay-back`,
      { from_code: fromCode, paid_on: paidOn },
    );
  },
  voidRequest(propertyId, requestId, reason) {
    return send(`${root(propertyId)}/expense-requests/${id(requestId)}/void`, {
      reason,
    });
  },
  recordExpense(propertyId, body) {
    return send(`${root(propertyId)}/ledger/expenses`, body);
  },
  voidExpense(propertyId, expenseId, reason) {
    return send(`${root(propertyId)}/ledger/expenses/${id(expenseId)}/void`, {
      reason,
    });
  },
  payBill(propertyId, billId, body) {
    return send(
      `${root(propertyId)}/ledger/supplier-bills/${id(billId)}/payments`,
      body,
    );
  },
  reverseBillPayment(propertyId, paymentId, reason) {
    return send(
      `${root(propertyId)}/ledger/bill-payments/${id(paymentId)}/reversal`,
      { reason },
    );
  },
};
