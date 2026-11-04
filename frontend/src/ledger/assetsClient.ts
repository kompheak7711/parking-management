// General Ledger phase 6 step 6 part 4: Fixed assets. An item is added by recording an Expense
// on an asset account; the server adds it to the register, takes its years from Business rules
// and makes the depreciation entry each month. This client only reads and sends.

import {
  csrfToken,
  list,
  maybeText,
  record,
  request,
  text,
  whole,
} from "./ledgerClient";

export interface FixedAsset {
  id: string;
  asset_number: string;
  item: string;
  account_code: string;
  account_name: string;
  account_name_km: string | null;
  unit_number: string | null;
  cost_cents: number;
  bought_on: string;
  useful_life_years: number | null;
  status: string;
  monthly_cents: number;
  depreciation_cents: number;
  value_cents: number;
  expense_number: string | null;
  request_number: string | null;
  expense_id: string | null;
}

export interface AssetRegister {
  today: string;
  assets: FixedAsset[];
  accumulated_cents: number;
  asset_limit_cents: number | null;
  /** Years for each asset account from Business rules today (1510, 1520, 1530). */
  years: Record<string, number | null>;
  last_depreciation: { entry_date: string; entry_number: string } | null;
}

export interface AssetsApi {
  read: (propertyId: string) => Promise<AssetRegister>;
  changeLife: (
    propertyId: string,
    assetId: string,
    years: number,
    reason: string,
  ) => Promise<void>;
}

function root(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/ledger`;
}

function maybeWhole(value: unknown): number | null {
  return value === null || value === undefined ? null : whole(value);
}

export const assetsApi: AssetsApi = {
  async read(propertyId) {
    const data = record(await request(`${root(propertyId)}/asset-register`));
    const years = record(data.years ?? {});
    const last =
      data.last_depreciation === null || data.last_depreciation === undefined
        ? null
        : record(data.last_depreciation);
    return {
      today: text(data.today),
      assets: list(data.assets).map((item) => {
        const row = record(item);
        return {
          id: text(row.id),
          asset_number: text(row.asset_number),
          item: text(row.item),
          account_code: text(row.account_code),
          account_name: text(row.account_name),
          account_name_km: maybeText(row.account_name_km),
          unit_number: maybeText(row.unit_number),
          cost_cents: whole(row.cost_cents),
          bought_on: text(row.bought_on),
          useful_life_years: maybeWhole(row.useful_life_years),
          status: text(row.status),
          monthly_cents: whole(row.monthly_cents),
          depreciation_cents: whole(row.depreciation_cents),
          value_cents: whole(row.value_cents),
          expense_number: maybeText(row.expense_number),
          request_number: maybeText(row.request_number),
          expense_id: maybeText(row.expense_id),
        };
      }),
      accumulated_cents: whole(data.accumulated_cents),
      asset_limit_cents: maybeWhole(data.asset_limit_cents),
      years: Object.fromEntries(
        Object.entries(years).map(([code, value]) => [code, maybeWhole(value)]),
      ),
      last_depreciation:
        last === null
          ? null
          : {
              entry_date: text(last.entry_date),
              entry_number: text(last.entry_number),
            },
    };
  },
  async changeLife(propertyId, assetId, years, reason) {
    await request(
      `${root(propertyId)}/fixed-assets/${encodeURIComponent(assetId)}/life`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: JSON.stringify({ years, reason }),
      },
    );
  },
};
