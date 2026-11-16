// UI v81 (design v81 Home; owner 12/11/2026): the Financial summary box and what the
// Attendance card counts. TEST-FE-1907, TEST-FE-1908, TEST-FE-1943.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AttendanceDay } from "../hr/hrClient";
import type { Report, ReportName } from "../ledger/ledgerClient";
import { OwnerMoney, attendanceToCheck } from "./OwnerMoney";

afterEach(() => {
  cleanup();
});

function report(name: ReportName, rows: Report["rows"]): Report {
  return {
    report: name,
    title: name,
    period: "",
    state: "",
    columns: [],
    rows,
    check: { ok: true, text: "" },
  };
}

const REPORTS: Partial<Record<ReportName, Report>> = {
  "balance-sheet": report("balance-sheet", [
    { line: "heading", code: null, name: "Assets" },
    { line: "account", code: "1010", name: "Cash", amount: 120000 },
    { line: "account", code: "1020", name: "ABA USD", amount: 350000 },
    {
      line: "account",
      code: "1100",
      name: "Accounts receivable",
      amount: 90000,
    },
    { line: "total", code: null, name: "Total assets", amount: 560000 },
  ]),
  "customer-aging": report("customer-aging", [
    { line: "account", customer_name: "Kong Heng", total: 90000 },
    {
      line: "total",
      customer_name: "Total",
      not_due: 20000,
      days_1_30: 30000,
      days_31_60: 25000,
      days_61_90: 0,
      over_90: 15000,
      total: 90000,
    },
  ]),
  budget: report("budget", [
    {
      line: "account",
      code: "4000",
      name: "Rent",
      actual_month: 999999,
      budget_month: 1,
    },
    {
      line: "account",
      code: "6010",
      name: "Repairs",
      actual_month: 30000,
      budget_month: 50000,
    },
    {
      line: "account",
      code: "6020",
      name: "Power",
      actual_month: 12000,
      budget_month: 10000,
    },
  ]),
  "profit-and-loss": report("profit-and-loss", [
    { line: "total", code: null, name: "Total income", year_to_date: 900000 },
    {
      line: "total",
      code: null,
      name: "Profit (or loss)",
      year_to_date: 412500,
    },
  ]),
};

describe("Home Financial summary and Attendance (UI v81)", () => {
  it('TEST-FE-1907 the Financial summary (owner 12/11/2026: no longer named Owner money, no "Only the Owner sees this") shows cash and bank, what customers owe, the part over 30 days, spent against budget and profit this year', async () => {
    const api = {
      report: vi.fn((_: string, name: ReportName) =>
        REPORTS[name] === undefined
          ? Promise.reject(new Error("not read"))
          : Promise.resolve(REPORTS[name]),
      ),
    };
    render(
      <OwnerMoney
        active
        api={api}
        language="en"
        propertyId="property-1"
        today="2026-11-07"
      />,
    );
    const box = await screen.findByRole("region", {
      name: "Financial summary",
    });
    expect(screen.queryByText("Owner money")).toBeNull();
    expect(screen.queryByText("Only the Owner sees this")).toBeNull();
    const cards = within(box)
      .getAllByRole("link")
      .map((card) => card.textContent);
    expect(cards).toEqual([
      // Owner 14/11/2026: no "Opens the Balance sheet" or "2026 so far" line; the budget stays.
      // Owner 14/11/2026: shorter names, and no "Customers owe" (same as Unpaid).
      "Cash & bank$4,700.00",
      "30+ days late$400.00",
      "Spent this month$420.00Budget $600.00",
      "Profit this year$4,125.00",
    ]);
    // Owner 12/11/2026 10:47: the five cards are one row from an iPad up.
    expect(box.querySelector(".ui-kpis.ui-om")).toHaveClass("ui-five");
    expect(api.report).toHaveBeenCalledWith("property-1", "budget", {
      month: "2026-11-01",
    });
  });

  it("TEST-FE-1943 (owner 12/11/2026) each Financial summary card opens the statement its number comes from: the Balance sheet, Accounts receivable aging (both owed cards), Budget vs actual, and Profit and loss", async () => {
    const api = {
      report: vi.fn((_: string, name: ReportName) =>
        REPORTS[name] === undefined
          ? Promise.reject(new Error("not read"))
          : Promise.resolve(REPORTS[name]),
      ),
    };
    render(
      <OwnerMoney
        active
        api={api}
        language="en"
        propertyId="property-1"
        today="2026-11-07"
      />,
    );
    const box = await screen.findByRole("region", {
      name: "Financial summary",
    });
    expect(
      within(box)
        .getAllByRole("link")
        .map((card) => card.getAttribute("href")),
    ).toEqual([
      "#/statements?show=balance-sheet",
      "#/statements?show=customer-aging",
      "#/statements?show=budget",
      "#/statements?show=profit-and-loss",
    ]);
  });

  it("TEST-FE-1908 the Attendance card counts the people to check: scans to check and people with no check-out, a person with both once", () => {
    const day = {
      people: [
        { no_check_out: true, scans: [] },
        {
          no_check_out: false,
          scans: [{ needs_check: true, accepted: false }],
        },
        { no_check_out: true, scans: [{ needs_check: true, accepted: false }] },
        { no_check_out: false, scans: [{ needs_check: true, accepted: true }] },
      ],
    } as unknown as AttendanceDay;
    expect(attendanceToCheck(day)).toEqual({ total: 3, scans: 2, noOut: 2 });
    expect(
      attendanceToCheck({ people: [] } as unknown as AttendanceDay),
    ).toEqual({ total: 0, scans: 0, noOut: 0 });
  });
});
