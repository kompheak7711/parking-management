// General Ledger phase 6 step 6 part 4: Budget. The Accountant prepares the budget by month
// for the year and sends it whole; the Owner approves it or sends it back. Nobody approves their
// own; the Owner's own budget is approved at once with a note. The server checks each right and
// every number. This client only reads and sends.

import {
  csrfToken,
  list,
  maybeText,
  record,
  request,
  text,
  whole,
} from "./ledgerClient";

export interface BudgetAccount {
  code: string;
  name_en: string;
  name_km: string | null;
  account_type: string;
}

export interface BudgetLine {
  account_code: string;
  month_no: number;
  amount_cents: number;
}

/** DRAFT waits for approval; REPLACED is sent back or replaced by a newer approved one. */
export interface Budget {
  id: string;
  version: number;
  status: string;
  created_by: string;
  created_by_name: string | null;
  created_at: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  decision_note: string | null;
  own_note: string | null;
  lines: BudgetLine[];
}

export interface BudgetSheet {
  today: string;
  years: { fiscal_year: number; status: string }[];
  year: number | null;
  accounts: BudgetAccount[];
  /** The chosen year's budgets, newest first. */
  budgets: Budget[];
  /** Last year's approved lines, a start for a new budget. */
  earlier_lines: BudgetLine[];
}

export interface BudgetApi {
  read: (propertyId: string, year: number | null) => Promise<BudgetSheet>;
  send: (
    propertyId: string,
    year: number,
    lines: BudgetLine[],
    ownNote: string | null,
  ) => Promise<void>;
  decide: (
    propertyId: string,
    budgetId: string,
    approve: boolean,
    note: string | null,
  ) => Promise<void>;
}

function root(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/ledger`;
}

function lineOf(value: unknown): BudgetLine {
  const row = record(value);
  return {
    account_code: text(row.account_code),
    month_no: whole(row.month_no),
    amount_cents: whole(row.amount_cents),
  };
}

async function send(path: string, body: object): Promise<void> {
  await request(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify(body),
  });
}

export const budgetApi: BudgetApi = {
  async read(propertyId, year) {
    const query = year === null ? "" : `?year=${String(year)}`;
    const data = record(
      await request(`${root(propertyId)}/budget-sheet${query}`),
    );
    return {
      today: text(data.today),
      years: list(data.years).map((item) => {
        const row = record(item);
        return {
          fiscal_year: whole(row.fiscal_year),
          status: text(row.status),
        };
      }),
      year:
        data.year === null || data.year === undefined ? null : whole(data.year),
      accounts: list(data.accounts).map((item) => {
        const row = record(item);
        return {
          code: text(row.code),
          name_en: text(row.name_en),
          name_km: maybeText(row.name_km),
          account_type: text(row.account_type),
        };
      }),
      budgets: list(data.budgets).map((item) => {
        const row = record(item);
        return {
          id: text(row.id),
          version: whole(row.version),
          status: text(row.status),
          created_by: text(row.created_by),
          created_by_name: maybeText(row.created_by_name),
          created_at: maybeText(row.created_at),
          approved_by_name: maybeText(row.approved_by_name),
          approved_at: maybeText(row.approved_at),
          decision_note: maybeText(row.decision_note),
          own_note: maybeText(row.own_note),
          lines: list(row.lines).map(lineOf),
        };
      }),
      earlier_lines: list(data.earlier_lines).map(lineOf),
    };
  },
  async send(propertyId, year, lines, ownNote) {
    await send(`${root(propertyId)}/budgets`, {
      fiscal_year: year,
      lines,
      ...(ownNote === null ? {} : { own_note: ownNote }),
    });
  },
  async decide(propertyId, budgetId, approve, note) {
    await send(
      `${root(propertyId)}/budgets/${encodeURIComponent(budgetId)}/decision`,
      { approve, ...(note === null ? {} : { note }) },
    );
  },
};
