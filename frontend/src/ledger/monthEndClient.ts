// General Ledger phase 6 step 6 part 4: Month-end close. The server checks each line itself,
// closes a month only when every line is green and in order, and makes the year-end entry.
// This client only reads and sends.

import {
  csrfToken,
  list,
  maybeText,
  record,
  request,
  text,
  whole,
} from "./ledgerClient";

export interface LedgerMonth {
  id: string;
  starts_on: string;
  ends_on: string;
  status: string;
  fiscal_year: number;
  closed_by_name: string | null;
  closed_at: string | null;
}

export interface LedgerYear {
  id: string;
  fiscal_year: number;
  status: string;
  entry_number: string | null;
  profit_cents: number | null;
  december_closed: boolean;
}

export interface CloseCheck {
  code: string;
  ok: boolean;
  open_items: number;
}

export interface MonthEnd {
  today: string;
  months: LedgerMonth[];
  years: LedgerYear[];
  month: LedgerMonth | null;
  checks: CloseCheck[];
  depreciation_entry: string | null;
  riel: { entry_number: string | null } | null;
}

export interface MonthEndApi {
  read: (propertyId: string, month: string | null) => Promise<MonthEnd>;
  /** True when the month closed; false when a check is still red. */
  closeMonth: (propertyId: string, periodId: string) => Promise<boolean>;
  closeYear: (propertyId: string, yearId: string) => Promise<void>;
}

function root(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/ledger`;
}

function monthOf(value: unknown): LedgerMonth {
  const row = record(value);
  return {
    id: text(row.id),
    starts_on: text(row.starts_on),
    ends_on: text(row.ends_on),
    status: text(row.status),
    fiscal_year: whole(row.fiscal_year),
    closed_by_name: maybeText(row.closed_by_name),
    closed_at: maybeText(row.closed_at),
  };
}

async function send(path: string): Promise<Record<string, unknown>> {
  return record(
    await request(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: "{}",
    }),
  );
}

export const monthEndApi: MonthEndApi = {
  async read(propertyId, month) {
    const query = month === null ? "" : `?month=${encodeURIComponent(month)}`;
    const data = record(await request(`${root(propertyId)}/month-end${query}`));
    return {
      today: text(data.today),
      months: list(data.months).map(monthOf),
      years: list(data.years).map((item) => {
        const row = record(item);
        return {
          id: text(row.id),
          fiscal_year: whole(row.fiscal_year),
          status: text(row.status),
          entry_number: maybeText(row.entry_number),
          profit_cents:
            row.profit_cents === null || row.profit_cents === undefined
              ? null
              : whole(row.profit_cents),
          december_closed: row.december_closed === true,
        };
      }),
      month:
        data.month === null || data.month === undefined
          ? null
          : monthOf(data.month),
      checks: list(data.checks).map((item) => {
        const row = record(item);
        return {
          code: text(row.code),
          ok: row.ok === true,
          open_items: whole(row.open_items),
        };
      }),
      depreciation_entry: maybeText(data.depreciation_entry),
      riel:
        data.riel === null || data.riel === undefined
          ? null
          : { entry_number: maybeText(record(data.riel).entry_number) },
    };
  },
  async closeMonth(propertyId, periodId) {
    const data = await send(
      `${root(propertyId)}/periods/${encodeURIComponent(periodId)}/close`,
    );
    return data.closed === true;
  },
  async closeYear(propertyId, yearId) {
    await send(
      `${root(propertyId)}/fiscal-years/${encodeURIComponent(yearId)}/close`,
    );
  },
};
