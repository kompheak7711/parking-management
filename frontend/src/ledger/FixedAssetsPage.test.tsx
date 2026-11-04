import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssetRegister, AssetsApi, FixedAsset } from "./assetsClient";
import { FixedAssetsPage } from "./FixedAssetsPage";
import type { ExpenseRow, SpendingApi, SpendingForm } from "./spendingClient";

afterEach(() => {
  cleanup();
});

const SOFA: FixedAsset = {
  id: "fa-1",
  asset_number: "FA260001",
  item: "Sofa, Unit 205",
  account_code: "1520",
  account_name: "Furniture and appliances in Units",
  account_name_km: null,
  unit_number: "U205",
  cost_cents: 60_000,
  bought_on: "2026-01-15",
  useful_life_years: 5,
  status: "IN_USE",
  monthly_cents: 1_000,
  depreciation_cents: 9_000,
  value_cents: 51_000,
  expense_number: "EX260004",
  request_number: "ER260002",
  expense_id: "x-1",
};

const DATA: AssetRegister = {
  today: "2026-11-04",
  assets: [
    SOFA,
    {
      ...SOFA,
      id: "fa-2",
      asset_number: "FA260002",
      item: "Old fridge",
      status: "VOID",
      unit_number: null,
      request_number: null,
      expense_id: "x-9",
    },
  ],
  accumulated_cents: 9_000,
  asset_limit_cents: 50_000,
  years: { "1510": 20, "1520": 5, "1530": 3 },
  last_depreciation: { entry_date: "2026-10-31", entry_number: "JE261031" },
};

const FORM: SpendingForm = {
  today: "2026-11-04",
  expense_limit_cents: 10_000,
  asset_limit_cents: 50_000,
  report_days: 3,
  bill_days: 30,
  rate: null,
  accounts: [
    {
      code: "1520",
      name_en: "Furniture and appliances in Units",
      name_km: null,
      account_type: "ASSET",
    },
    {
      code: "1530",
      name_en: "Office equipment",
      name_km: null,
      account_type: "ASSET",
    },
    {
      code: "6050",
      name_en: "Repairs and maintenance",
      name_km: null,
      account_type: "EXPENSE",
    },
  ],
  money_accounts: [
    {
      code: "1010",
      name_en: "Cash on hand (USD)",
      name_km: null,
      account_type: "ASSET",
    },
    {
      code: "1020",
      name_en: "ABA Bank · USD account",
      name_km: null,
      account_type: "ASSET",
    },
  ],
  suppliers: [{ id: "sup-1", name: "Sok Hardware" }],
  units: [{ id: "unit-1", unit_number: "U205" }],
};

const LAPTOP: FixedAsset = {
  ...SOFA,
  id: "fa-3",
  asset_number: "FA260003",
  item: "Laptop",
  account_code: "1530",
  account_name: "Office equipment",
  unit_number: null,
  cost_cents: 90_000,
  bought_on: "2026-11-04",
  useful_life_years: 3,
  depreciation_cents: 0,
  value_cents: 90_000,
  expense_number: "EX260010",
  request_number: null,
  expense_id: "x-2",
};

const EXPENSE = {
  id: "x-2",
  entry_number: "JE261104",
} as const;

function fakeAssets(extra: Partial<AssetsApi> = {}): AssetsApi {
  return {
    read: vi.fn(() => Promise.resolve(DATA)),
    changeLife: vi.fn(() => Promise.resolve()),
    ...extra,
  };
}

function fakeSpending(extra: Partial<SpendingApi> = {}): SpendingApi {
  const unused = vi.fn(() => Promise.reject(new Error("not used")));
  return {
    form: vi.fn(() => Promise.resolve(FORM)),
    requests: unused,
    request: unused,
    expenses: vi.fn(() =>
      Promise.resolve([{ ...EXPENSE } as unknown as ExpenseRow]),
    ),
    bills: unused,
    addSupplier: vi.fn(() => Promise.resolve("sup-new")),
    submitRequest: unused,
    decide: unused,
    giveAdvance: unused,
    recordBill: unused,
    payBack: unused,
    voidRequest: unused,
    recordExpense: vi.fn(() => Promise.resolve("x-2")),
    voidExpense: unused,
    payBill: unused,
    reverseBillPayment: unused,
    ...extra,
  };
}

function show(
  api: AssetsApi,
  spending: SpendingApi = fakeSpending(),
  capabilities: ReadonlySet<string> | null = null,
) {
  render(
    <FixedAssetsPage
      active
      api={api}
      capabilities={capabilities}
      language="en"
      propertyId="prop-1"
      spendingApi={spending}
    />,
  );
}

async function openDialog(): Promise<HTMLElement> {
  const add = await screen.findByRole("button", { name: "Add fixed asset" });
  await waitFor(() => {
    expect(add).toBeEnabled();
  });
  fireEvent.click(add);
  return screen.findByRole("dialog");
}

describe("Fixed assets", () => {
  it("TEST-FE-1199 shows the register with its totals and the 1590 check", async () => {
    show(fakeAssets());
    expect(await screen.findByText("Sofa, Unit 205")).toBeInTheDocument();
    expect(screen.queryByText("Old fridge")).not.toBeInTheDocument();
    expect(screen.getByText("5 years")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ER260002" })).toHaveAttribute(
      "href",
      "#/exreqs/ER260002",
    );
    expect(screen.getByText("Matches")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Depreciation so far equals Accumulated depreciation (1590): $90.00.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "JE261031" })).toHaveAttribute(
      "href",
      "#/journal/JE261031",
    );
    expect(screen.getByText(/October 2026/)).toBeInTheDocument();
    expect(screen.getAllByText("$510.00").length).toBeGreaterThan(0);
  });

  it("TEST-FE-1200 refuses an item below the Asset limit and adds one at or above it", async () => {
    const read = vi
      .fn<AssetsApi["read"]>()
      .mockResolvedValueOnce(DATA)
      .mockResolvedValue({ ...DATA, assets: [SOFA, LAPTOP] });
    const assets = fakeAssets({ read });
    const spending = fakeSpending();
    show(assets, spending);
    const dialog = await openDialog();
    fireEvent.change(within(dialog).getByLabelText(/^Item/), {
      target: { value: "Laptop" },
    });
    fireEvent.change(within(dialog).getByLabelText("Account"), {
      target: { value: "1530" },
    });
    expect(within(dialog).getByLabelText(/^Useful life/)).toHaveValue("3");
    fireEvent.change(within(dialog).getByLabelText(/^Cost/), {
      target: { value: "400" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "Below $500.00: record it on Expenses instead.",
      ),
    ).toBeInTheDocument();
    expect(spending.recordExpense).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/^Cost/), {
      target: { value: "900" },
    });
    expect(
      within(dialog).getByText(
        "Depreciation: $25.00 each month, first on 31/12/2026.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Fixed asset FA260003 added. Entry JE261104."),
    ).toBeInTheDocument();
    expect(spending.recordExpense).toHaveBeenCalledWith("prop-1", {
      expense_date: "2026-11-04",
      account_code: "1530",
      description: "Laptop",
      amount_cents: 90_000,
      paid_from_code: "1020",
      supplier_id: null,
      bill_number: null,
      due_date: null,
      unit_id: null,
    });
    expect(assets.changeLife).not.toHaveBeenCalled();
  });

  it("TEST-FE-1201 sets other years and a supplier bill when paid later", async () => {
    const read = vi
      .fn<AssetsApi["read"]>()
      .mockResolvedValueOnce(DATA)
      .mockResolvedValue({ ...DATA, assets: [SOFA, LAPTOP] });
    const assets = fakeAssets({ read });
    const spending = fakeSpending();
    show(assets, spending);
    const dialog = await openDialog();
    fireEvent.change(within(dialog).getByLabelText(/^Item/), {
      target: { value: "Laptop" },
    });
    fireEvent.change(within(dialog).getByLabelText("Account"), {
      target: { value: "1530" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Cost/), {
      target: { value: "900" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Useful life/), {
      target: { value: "4" },
    });
    fireEvent.change(within(dialog).getByLabelText("Paid from"), {
      target: { value: "LATER" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("Type the supplier."),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Supplier/), {
      target: { value: "Sok Hardware" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Fixed asset FA260003 added. Entry JE261104."),
    ).toBeInTheDocument();
    expect(spending.recordExpense).toHaveBeenCalledWith(
      "prop-1",
      expect.objectContaining({
        paid_from_code: null,
        supplier_id: "sup-1",
        due_date: "2026-12-04",
      }),
    );
    expect(assets.changeLife).toHaveBeenCalledWith(
      "prop-1",
      "fa-3",
      4,
      "Years set when the item was added.",
    );
  });

  it("TEST-FE-1202 shows the register without Add to a reader who cannot record", async () => {
    show(fakeAssets(), fakeSpending(), new Set(["ledger.read"]));
    expect(await screen.findByText("Sofa, Unit 205")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add fixed asset" }),
    ).not.toBeInTheDocument();
  });
});
