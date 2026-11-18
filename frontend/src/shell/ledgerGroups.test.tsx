import { describe, expect, it } from "vitest";

import { GENERAL_LEDGER } from "../leases/parking";
import { MENU, allowedGroupsOf, subItemsOf, switchName } from "./navigation";

const ledger = MENU.flatMap((group) => group.items).find(
  (item) => item.page === "exreqs",
);

describe("Ledger tab groups (owner 16/11/2026)", () => {
  it("TEST-FE-2233 the 11 Ledger pages show as 5 tabs, the menu lists the 5, and a staff member sees only Spending", ({
    skip,
  }) => {
    // Parking Step 6: no General Ledger on Parking.
    skip(!GENERAL_LEDGER);
    expect(ledger).toBeDefined();
    if (ledger === undefined) return;
    const groups = allowedGroupsOf(ledger, null, "en");
    expect(groups.map((group) => group.label)).toEqual([
      "Spending",
      "Books",
      "Reports",
      "Assets and cash",
      "Month-end close",
    ]);
    expect(groups.flatMap((group) => group.pages)).toEqual(ledger.tabs);
    const subs = subItemsOf(ledger, "bills", null, null, "en");
    expect(subs.map((sub) => sub.label)).toEqual(
      groups.map((group) => group.label),
    );
    expect(subs.find((sub) => sub.current)?.label).toBe("Spending");
    expect(subs[1]?.href).toBe("#/journal");
    expect(switchName("exreqs", "en")).toBe("Requests");
    // Without ledger.read only Expense requests is open: one group with one page, no sub-items.
    const staff = new Set<string>(["expenses.request"]);
    const own = allowedGroupsOf(ledger, staff, "en");
    expect(own.map((group) => group.pages)).toEqual([["exreqs"]]);
    expect(subItemsOf(ledger, "exreqs", null, staff, "en")).toEqual([]);
  });
});
