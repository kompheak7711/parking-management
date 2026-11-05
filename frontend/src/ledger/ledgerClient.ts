// General Ledger phase 6 step 6 part 1: the ledger screens read the books, the Needs check list
// and the Financial statements, and set a Payment Method's or Refund method's account. The
// server checks every right and makes every number; this client only reads and sends.

export type AccountType =
  | "ASSET"
  | "LIABILITY"
  | "EQUITY"
  | "INCOME"
  | "COST_OF_SALES"
  | "EXPENSE";

export const ACCOUNT_TYPES: readonly AccountType[] = [
  "ASSET",
  "LIABILITY",
  "EQUITY",
  "INCOME",
  "COST_OF_SALES",
  "EXPENSE",
];

export interface Account {
  code: string;
  name_en: string;
  name_km: string | null;
  account_type: AccountType;
  control_source: string | null;
  /** CASH_USD, CASH_KHR, BANK, BANK_KHR or PETTY for a cash or bank account, else null. */
  cash_kind: string | null;
  tax_locked: boolean;
  active: boolean;
  used: boolean;
  /** The balance on the account's normal side; below 0 when it is on the other side. */
  balance_cents: number;
}

export interface Chart {
  as_of: string;
  accounts: Account[];
}

export interface SourceLink {
  page: "invoices" | "payments";
  detail: string;
}

export interface EntryRow {
  entry_number: string;
  entry_date: string;
  entry_kind: string;
  description: string;
  source_type: string;
  source_number: string | null;
  source_link: SourceLink | null;
  amount_cents: number;
  reverses: string | null;
  reversed_by: string | null;
}

export interface Journal {
  month: string | null;
  months: string[];
  newest_only: boolean;
  entries: EntryRow[];
}

export interface EntryLine {
  account_code: string;
  account_name_en: string;
  account_name_km: string | null;
  debit_cents: number;
  credit_cents: number;
  memo: string | null;
}

export interface Entry extends EntryRow {
  reason: string | null;
  posted_at: string | null;
  posted_by_name: string | null;
  approved_by_name: string | null;
  month_closed: boolean;
  lines: EntryLine[];
}

export interface PostingProblem {
  posting_key: string;
  source_type: string;
  source_id: string;
  event_date: string;
  problem: string;
  first_seen_at: string;
  source_number: string | null;
  source_link: SourceLink | null;
}

export type MethodKind = "PAYMENT" | "REFUND";

export interface MethodAccount {
  kind: MethodKind;
  method_id: string;
  code: string;
  name: string;
  account_code: string | null;
  account_name: string | null;
  effective_from: string | null;
  /** Where a payment in riel goes (owner 04/11/2026); null = as before. */
  riel_account_code: string | null;
  riel_account_name: string | null;
}

export type ReportName =
  | "profit-and-loss"
  | "balance-sheet"
  | "cash-flow"
  | "trial-balance"
  | "account-detail"
  | "customer-aging"
  | "bills-aging"
  | "budget";

export interface ReportColumn {
  key: string;
  label: string;
  kind: string;
}

export type ReportRow = Record<string, string | number | boolean | null>;

export interface Report {
  report: ReportName;
  title: string;
  period: string;
  state: string;
  columns: ReportColumn[];
  rows: ReportRow[];
  check: { ok: boolean; text: string };
}

export interface ReportQuery {
  as_of?: string;
  month?: string;
  from?: string;
  to?: string;
  account?: string;
}

export interface BooksCheckRow {
  check_code: string;
  accounts: string | null;
  in_books: number;
  in_list: number;
  ok: boolean;
}

export interface ReportFile {
  fileName: string;
  file: Blob;
}

export interface LedgerApi {
  accounts: (propertyId: string, asOf?: string) => Promise<Chart>;
  entries: (propertyId: string, month?: string) => Promise<Journal>;
  entry: (propertyId: string, entryNumber: string) => Promise<Entry>;
  needsCheck: (propertyId: string) => Promise<PostingProblem[]>;
  methodAccounts: (propertyId: string) => Promise<MethodAccount[]>;
  setMethodAccount: (
    propertyId: string,
    change: {
      kind: MethodKind;
      method_id: string;
      account_code: string;
      effective_from: string;
      riel_account_code?: string | null;
    },
  ) => Promise<MethodAccount[]>;
  report: (
    propertyId: string,
    name: ReportName,
    query: ReportQuery,
  ) => Promise<Report>;
  reportFile: (
    propertyId: string,
    name: ReportName,
    query: ReportQuery,
    type: "xlsx" | "pdf",
  ) => Promise<ReportFile>;
  booksCheck: (propertyId: string) => Promise<BooksCheckRow[]>;
}

export class LedgerError extends Error {
  /** The HTTP status when the server answered: 403 no right, 404 not there, 422 refused. */
  constructor(
    readonly status: number | null = null,
    readonly detail: string | null = null,
  ) {
    super("The ledger command was not completed.");
    this.name = "LedgerError";
  }
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (entry === undefined) throw new LedgerError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new LedgerError();
  return token;
}

async function fetched(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new LedgerError();
  }
}

async function refused(response: Response): Promise<LedgerError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const detail =
    isObject(payload) && typeof payload.detail === "string"
      ? payload.detail
      : isObject(payload) &&
          isObject(payload.error) &&
          typeof payload.error.message === "string"
        ? payload.error.message
        : null;
  return new LedgerError(response.status, detail);
}

export async function request(
  path: string,
  init: RequestInit = { method: "GET" },
): Promise<unknown> {
  const response = await fetched(path, init);
  if (!response.ok) throw await refused(response);
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    throw new LedgerError();
  }
  if (!isObject(payload) || !("data" in payload)) throw new LedgerError();
  return payload.data;
}

function base(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/ledger`;
}

function query(values: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text === "" ? "" : `?${text}`;
}

export function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new LedgerError();
  return value;
}

export function record(value: unknown): Record<string, unknown> {
  if (!isObject(value)) throw new LedgerError();
  return value;
}

export function text(value: unknown): string {
  if (typeof value !== "string") throw new LedgerError();
  return value;
}

export function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

export function whole(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new LedgerError();
  }
  return value;
}

function accountOf(value: unknown): Account {
  const row = record(value);
  const type = text(row.account_type);
  if (!(ACCOUNT_TYPES as readonly string[]).includes(type)) {
    throw new LedgerError();
  }
  return {
    code: text(row.code),
    name_en: text(row.name_en),
    name_km: maybeText(row.name_km),
    account_type: type as AccountType,
    control_source: maybeText(row.control_source),
    cash_kind: maybeText(row.cash_kind),
    tax_locked: row.tax_locked === true,
    active: row.active !== false,
    used: row.used === true,
    balance_cents: whole(row.balance_cents),
  };
}

function linkOf(value: unknown): SourceLink | null {
  if (value === null || value === undefined) return null;
  const row = record(value);
  const page = text(row.page);
  if (page !== "invoices" && page !== "payments") return null;
  return { page, detail: text(row.detail) };
}

function entryRowOf(value: unknown): EntryRow {
  const row = record(value);
  return {
    entry_number: text(row.entry_number),
    entry_date: text(row.entry_date),
    entry_kind: text(row.entry_kind),
    description: text(row.description),
    source_type: text(row.source_type),
    source_number: maybeText(row.source_number),
    source_link: linkOf(row.source_link),
    amount_cents: whole(row.amount_cents),
    reverses: maybeText(row.reverses),
    reversed_by: maybeText(row.reversed_by),
  };
}

function entryOf(value: unknown): Entry {
  const row = record(value);
  return {
    ...entryRowOf(row),
    reason: maybeText(row.reason),
    posted_at: maybeText(row.posted_at),
    posted_by_name: maybeText(row.posted_by_name),
    approved_by_name: maybeText(row.approved_by_name),
    month_closed: row.month_closed === true,
    lines: list(row.lines).map((item) => {
      const line = record(item);
      return {
        account_code: text(line.account_code),
        account_name_en: text(line.account_name_en),
        account_name_km: maybeText(line.account_name_km),
        debit_cents: whole(line.debit_cents),
        credit_cents: whole(line.credit_cents),
        memo: maybeText(line.memo),
      };
    }),
  };
}

function methodOf(value: unknown): MethodAccount {
  const row = record(value);
  return {
    kind: row.kind === "REFUND" ? "REFUND" : "PAYMENT",
    method_id: text(row.method_id),
    code: text(row.code),
    name: text(row.name),
    account_code: maybeText(row.account_code),
    account_name: maybeText(row.account_name),
    effective_from: maybeText(row.effective_from),
    riel_account_code: maybeText(row.riel_account_code),
    riel_account_name: maybeText(row.riel_account_name),
  };
}

function cell(value: unknown): string | number | boolean | null {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  return null;
}

function reportOf(value: unknown): Report {
  const data = record(value);
  const check = record(data.check);
  return {
    report: text(data.report) as ReportName,
    title: text(data.title),
    period: text(data.period),
    state: text(data.state),
    columns: list(data.columns).map((item) => {
      const column = record(item);
      return {
        key: text(column.key),
        label: text(column.label),
        kind: text(column.kind),
      };
    }),
    rows: list(data.rows).map((item) => {
      const row = record(item);
      const out: ReportRow = {};
      for (const [key, raw] of Object.entries(row)) out[key] = cell(raw);
      return out;
    }),
    check: { ok: check.ok === true, text: text(check.text) },
  };
}

function fileNameOf(response: Response, fallback: string): string {
  const header = response.headers.get("Content-Disposition") ?? "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (encoded?.[1] !== undefined) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      return fallback;
    }
  }
  const plain = /filename="([^"]+)"/i.exec(header);
  return plain?.[1] ?? fallback;
}

export const ledgerApi: LedgerApi = {
  async accounts(propertyId, asOf) {
    const data = record(
      await request(`${base(propertyId)}/accounts${query({ as_of: asOf })}`),
    );
    return {
      as_of: text(data.as_of),
      accounts: list(data.accounts).map(accountOf),
    };
  },
  async entries(propertyId, month) {
    const data = record(
      await request(`${base(propertyId)}/entries${query({ month })}`),
    );
    return {
      month: maybeText(data.month),
      months: list(data.months).map(text),
      newest_only: data.newest_only === true,
      entries: list(data.entries).map(entryRowOf),
    };
  },
  async entry(propertyId, entryNumber) {
    return entryOf(
      await request(
        `${base(propertyId)}/entries/${encodeURIComponent(entryNumber)}`,
      ),
    );
  },
  async needsCheck(propertyId) {
    return list(await request(`${base(propertyId)}/needs-check`)).map(
      (item) => {
        const row = record(item);
        return {
          posting_key: text(row.posting_key),
          source_type: text(row.source_type),
          source_id: text(row.source_id),
          event_date: text(row.event_date),
          problem: text(row.problem),
          first_seen_at: text(row.first_seen_at),
          source_number: maybeText(row.source_number),
          source_link: linkOf(row.source_link),
        };
      },
    );
  },
  async methodAccounts(propertyId) {
    return list(await request(`${base(propertyId)}/method-accounts`)).map(
      methodOf,
    );
  },
  async setMethodAccount(propertyId, change) {
    return list(
      await request(`${base(propertyId)}/method-accounts`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: JSON.stringify(change),
      }),
    ).map(methodOf);
  },
  async report(propertyId, name, values) {
    return reportOf(
      await request(
        `${base(propertyId)}/reports/${name}${query({ ...values })}`,
      ),
    );
  },
  async reportFile(propertyId, name, values, type) {
    const response = await fetched(
      `${base(propertyId)}/reports/${name}${query({ ...values, format: type })}`,
      { method: "GET" },
    );
    if (!response.ok) throw await refused(response);
    let file: Blob;
    try {
      file = await response.blob();
    } catch {
      throw new LedgerError();
    }
    return { fileName: fileNameOf(response, `${name}.${type}`), file };
  },
  async booksCheck(propertyId) {
    return list(await request(`${base(propertyId)}/books-check`)).map(
      (item) => {
        const row = record(item);
        return {
          check_code: text(row.check_code),
          accounts: maybeText(row.accounts),
          in_books: Number(row.in_books ?? 0),
          in_list: Number(row.in_list ?? 0),
          ok: row.ok === true,
        };
      },
    );
  },
};
