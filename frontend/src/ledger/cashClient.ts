// General Ledger phase 6 step 6 part 3: Bank and cash. The server reads the months that have
// ended, the bank lines not yet matched, the cash counts, the petty cash float and the riel
// held; it checks every right and every amount again and makes each journal entry. This client
// only reads and sends.

import {
  csrfToken,
  list,
  maybeText,
  record,
  request,
  text,
  whole,
} from "./ledgerClient";

export interface CashMonth {
  id: string;
  starts_on: string;
  ends_on: string;
  status: string;
  matched: boolean;
  counted: boolean;
}

export interface MoneyAccount {
  code: string;
  name_en: string;
  name_km: string | null;
  cash_kind: string;
  balance_cents: number;
}

export interface BankLine {
  line_id: string;
  entry_number: string;
  entry_date: string;
  description: string;
  memo: string | null;
  debit_cents: number;
  credit_cents: number;
  /** The riel of a riel bank account's line (migration 320); null on a dollar bank. */
  riel_minor: number | null;
}

export interface BankBook {
  code: string;
  name_en: string;
  name_km: string | null;
  /** "BANK" for dollars, "BANK_KHR" for the riel bank account (owner 04/11/2026). */
  cash_kind: string;
  book_cents: number;
  /** The riel the riel bank account holds at the month's end; null on a dollar bank. */
  riel_held: number | null;
  lines: BankLine[];
  match: {
    statement_balance_cents: number;
    statement_riel: number | null;
    status: string;
    by_name: string | null;
    at: string;
    lines: number;
  } | null;
}

export interface CashBook {
  code: string;
  name_en: string;
  name_km: string | null;
  cash_kind: string;
  book_cents: number;
  count: {
    counted_on: string;
    counted_cents: number;
    book_cents: number;
    counted_riel: number | null;
    note: string | null;
    entry_number: string | null;
    by_name: string | null;
    at: string;
  } | null;
}

export interface RielHeld {
  code: string;
  held_riel: number;
  book_cents: number;
  last_month_end: string | null;
  last_entry_number: string | null;
}

export interface BankCash {
  today: string;
  months: CashMonth[];
  month: CashMonth | null;
  rate: { id: string; khr_per_usd: number } | null;
  petty: {
    code: string;
    float_cents: number | null;
    balance_cents: number;
    waiting: { request_number: string; amount_cents: number }[];
  } | null;
  riel: RielHeld | null;
  /** The riel bank account (1021), when the chart has one. */
  riel_bank: RielHeld | null;
  money_accounts: MoneyAccount[];
  banks: BankBook[];
  cash: CashBook[];
}

export type MoneyRecordKind =
  | "money-move"
  | "owner-money"
  | "petty-cash-top-up";

export interface NewMove {
  moved_on: string;
  from_code: string;
  to_code: string;
  amount_cents: number;
  received_cents: number | null;
  riel_amount_minor: number | null;
  exchange_rate_record_id: string | null;
}

export interface NewCount {
  account_code: string;
  counted_on: string;
  counted_cents: number | null;
  counted_riel: number | null;
  exchange_rate_record_id: string | null;
  reason: string | null;
}

export interface CashApi {
  read: (propertyId: string, month: string | null) => Promise<BankCash>;
  entryOf: (
    propertyId: string,
    kind: MoneyRecordKind,
    recordId: string,
  ) => Promise<string>;
  moveMoney: (propertyId: string, body: NewMove) => Promise<string>;
  ownerMoney: (
    propertyId: string,
    body: {
      direction: "IN" | "OUT";
      moved_on: string;
      account_code: string;
      amount_cents: number;
      note: string;
    },
  ) => Promise<string>;
  topUp: (
    propertyId: string,
    body: { topped_up_on: string; from_code: string; amount_cents: number },
  ) => Promise<string>;
  countCash: (propertyId: string, body: NewCount) => Promise<string>;
  matchBank: (
    propertyId: string,
    body: {
      account_code: string;
      period_id: string;
      /** A dollar bank is matched in cents, the riel bank account in riel. */
      statement_balance_cents: number | null;
      statement_riel: number | null;
      lines: { line_id: string }[];
    },
  ) => Promise<string>;
}

function root(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}`;
}

function maybeWhole(value: unknown): number | null {
  return value === null || value === undefined ? null : whole(value);
}

function optional<T>(
  value: unknown,
  read: (row: Record<string, unknown>) => T,
): T | null {
  return value === null || value === undefined ? null : read(record(value));
}

function monthOf(row: Record<string, unknown>): CashMonth {
  return {
    id: text(row.id),
    starts_on: text(row.starts_on),
    ends_on: text(row.ends_on),
    status: text(row.status),
    matched: row.matched === true,
    counted: row.counted === true,
  };
}

function rielHeldOf(riel: Record<string, unknown>): RielHeld {
  return {
    code: text(riel.code),
    held_riel: whole(riel.held_riel),
    book_cents: whole(riel.book_cents),
    last_month_end: maybeText(riel.last_month_end),
    last_entry_number: maybeText(riel.last_entry_number),
  };
}

function bankOf(value: unknown): BankBook {
  const row = record(value);
  return {
    code: text(row.code),
    name_en: text(row.name_en),
    name_km: maybeText(row.name_km),
    cash_kind: row.cash_kind === "BANK_KHR" ? "BANK_KHR" : "BANK",
    book_cents: whole(row.book_cents),
    riel_held: maybeWhole(row.riel_held),
    lines: list(row.lines).map((item) => {
      const line = record(item);
      return {
        line_id: text(line.line_id),
        entry_number: text(line.entry_number),
        entry_date: text(line.entry_date),
        description: text(line.description),
        memo: maybeText(line.memo),
        debit_cents: whole(line.debit_cents),
        credit_cents: whole(line.credit_cents),
        riel_minor: maybeWhole(line.riel_minor),
      };
    }),
    match: optional(row.match, (match) => ({
      statement_balance_cents: whole(match.statement_balance_cents),
      statement_riel: maybeWhole(match.statement_riel),
      status: text(match.status),
      by_name: maybeText(match.by_name),
      at: text(match.at),
      lines: whole(match.lines),
    })),
  };
}

function cashOf(value: unknown): CashBook {
  const row = record(value);
  return {
    code: text(row.code),
    name_en: text(row.name_en),
    name_km: maybeText(row.name_km),
    cash_kind: text(row.cash_kind),
    book_cents: whole(row.book_cents),
    count: optional(row.count, (count) => ({
      counted_on: text(count.counted_on),
      counted_cents: whole(count.counted_cents),
      book_cents: whole(count.book_cents),
      counted_riel: maybeWhole(count.counted_riel),
      note: maybeText(count.note),
      entry_number: maybeText(count.entry_number),
      by_name: maybeText(count.by_name),
      at: text(count.at),
    })),
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

export const cashApi: CashApi = {
  async read(propertyId, month) {
    const query = month === null ? "" : `?month=${encodeURIComponent(month)}`;
    const data = record(
      await request(`${root(propertyId)}/ledger/bank-cash${query}`),
    );
    return {
      today: text(data.today),
      months: list(data.months).map((item) => monthOf(record(item))),
      month: optional(data.month, monthOf),
      rate: optional(data.rate, (rate) => ({
        id: text(rate.id),
        khr_per_usd: whole(rate.khr_per_usd),
      })),
      petty: optional(data.petty, (petty) => ({
        code: text(petty.code),
        float_cents: maybeWhole(petty.float_cents),
        balance_cents: whole(petty.balance_cents),
        waiting: list(petty.waiting).map((item) => {
          const row = record(item);
          return {
            request_number: text(row.request_number),
            amount_cents: whole(row.amount_cents),
          };
        }),
      })),
      riel: optional(data.riel, rielHeldOf),
      riel_bank: optional(data.riel_bank, rielHeldOf),
      money_accounts: list(data.money_accounts).map((item) => {
        const row = record(item);
        return {
          code: text(row.code),
          name_en: text(row.name_en),
          name_km: maybeText(row.name_km),
          cash_kind: text(row.cash_kind),
          balance_cents: whole(row.balance_cents),
        };
      }),
      banks: list(data.banks).map(bankOf),
      cash: list(data.cash).map(cashOf),
    };
  },
  async entryOf(propertyId, kind, recordId) {
    const data = record(
      await request(
        `${root(propertyId)}/ledger/money-entries/${kind}/${encodeURIComponent(recordId)}`,
      ),
    );
    return text(data.entry_number);
  },
  moveMoney(propertyId, body) {
    return send(`${root(propertyId)}/ledger/money-moves`, body);
  },
  ownerMoney(propertyId, body) {
    return send(`${root(propertyId)}/ledger/owner-money`, body);
  },
  topUp(propertyId, body) {
    return send(`${root(propertyId)}/ledger/petty-cash-top-ups`, body);
  },
  countCash(propertyId, body) {
    return send(`${root(propertyId)}/ledger/cash-counts`, body);
  },
  matchBank(propertyId, body) {
    return send(`${root(propertyId)}/ledger/bank-matches`, body);
  },
};
