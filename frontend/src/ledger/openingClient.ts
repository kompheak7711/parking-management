// General Ledger phase 6 step 6 (mock-up lopen): Opening balances. The Owner starts the books on
// 1 January of the first year, types the accounts that are not control accounts and posts them;
// the app works out the control accounts from its own lists. The server checks each right and
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

export interface OpeningAccount {
  code: string;
  name_en: string;
  name_km: string | null;
  account_type: string;
  normal_side: string;
}

export interface OpeningLine {
  account_code: string;
  name_en: string;
  name_km: string | null;
  debit_cents: number;
  credit_cents: number;
  memo: string | null;
}

/** DRAFT waits to be posted; POSTED is locked. */
export interface Opening {
  id: string;
  start_date: string;
  status: string;
  entry_number: string | null;
  posted_by_name: string | null;
  posted_at: string | null;
}

export interface OpeningSheet {
  today: string;
  first_year: number | null;
  opening: Opening | null;
  /** The accounts the Owner may type: not control accounts, not tax accounts. */
  accounts: OpeningAccount[];
  typed: OpeningLine[];
  /** The control accounts the app works out now from its own lists. */
  worked_out: OpeningLine[];
  /** The posted entry's lines, once posted. */
  posted: OpeningLine[];
  /** Records waiting in Needs check; posting is refused until there are none. */
  needs_check: number;
}

export interface TypedLine {
  account_code: string;
  debit_cents: number;
  credit_cents: number;
  memo: string | null;
}

export interface OpeningApi {
  read: (propertyId: string) => Promise<OpeningSheet>;
  begin: (propertyId: string, firstYear: number) => Promise<void>;
  setLines: (propertyId: string, lines: TypedLine[]) => Promise<void>;
  post: (propertyId: string) => Promise<void>;
}

function root(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/ledger`;
}

function lineOf(value: unknown): OpeningLine {
  const row = record(value);
  return {
    account_code: text(row.account_code),
    name_en: text(row.account_name),
    name_km: maybeText(row.account_name_km),
    debit_cents: whole(row.debit_cents),
    credit_cents: whole(row.credit_cents),
    memo: maybeText(row.memo),
  };
}

async function change(path: string, method: string, body: object) {
  await request(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify(body),
  });
}

export const openingApi: OpeningApi = {
  async read(propertyId) {
    const data = record(await request(`${root(propertyId)}/opening-sheet`));
    const opening =
      data.opening === null || data.opening === undefined
        ? null
        : record(data.opening);
    return {
      today: text(data.today),
      first_year:
        data.first_year === null || data.first_year === undefined
          ? null
          : whole(data.first_year),
      opening:
        opening === null
          ? null
          : {
              id: text(opening.id),
              start_date: text(opening.start_date),
              status: text(opening.status),
              entry_number: maybeText(opening.entry_number),
              posted_by_name: maybeText(opening.posted_by_name),
              posted_at: maybeText(opening.posted_at),
            },
      accounts: list(data.accounts).map((item) => {
        const row = record(item);
        return {
          code: text(row.code),
          name_en: text(row.name_en),
          name_km: maybeText(row.name_km),
          account_type: text(row.account_type),
          normal_side: text(row.normal_side),
        };
      }),
      typed: list(data.typed).map(lineOf),
      worked_out: list(data.worked_out).map(lineOf),
      posted: list(data.posted).map(lineOf),
      needs_check: whole(data.needs_check),
    };
  },
  async begin(propertyId, firstYear) {
    await change(`${root(propertyId)}/opening-balances`, "POST", {
      first_year: firstYear,
    });
  },
  async setLines(propertyId, lines) {
    await change(`${root(propertyId)}/opening-balances/lines`, "PUT", {
      lines: lines.map((line) => ({
        account_code: line.account_code,
        ...(line.debit_cents > 0 ? { debit_cents: line.debit_cents } : {}),
        ...(line.credit_cents > 0 ? { credit_cents: line.credit_cents } : {}),
        ...(line.memo === null ? {} : { memo: line.memo }),
      })),
    });
  },
  async post(propertyId) {
    await change(`${root(propertyId)}/opening-balances/post`, "POST", {});
  },
};
