import { describe, expect, it } from "vitest";

import {
  ABA_QR,
  GENERAL_LEDGER,
  HR,
  MONTHLY_SERVICES,
  PRODUCTS,
  PROBLEM_REPORTS,
  SHORT_STAYS,
  TELEGRAM,
} from "../leases/parking";
import {
  MENU,
  allowedPagesOf,
  pageAllowed,
  settingsTabShownOnParking,
  subItemsOf,
  type PageId,
} from "./navigation";

// Parking Step 6 (owner 2026-11-17, "Yes, as recommended"): the V1.1 and V1.2 parts Parking
// does not use are hidden from the menu, its sub-items and Settings; the code stays.
const HIDDEN: readonly PageId[] = [
  "exreqs",
  "expenses",
  "bills",
  "journal",
  "needscheck",
  "chart",
  "statements",
  "budget",
  "fassets",
  "bankcash",
  "lclose",
  "employees",
  "loans",
  "payroll",
  "attendance",
  "visitreqs",
  "tglinks",
  "tgsent",
  "tgcontact",
  "tgfaq",
  "tgnotices",
  "tghealth",
  "shortstays",
  "products",
  "stock",
  "locations",
  "quotations",
  "problems",
];
const EVERYTHING: ReadonlySet<string> | null = null;

describe("Parking Step 6 switches", () => {
  it("TEST-FE-3155 all eight switches are off", () => {
    expect([
      GENERAL_LEDGER,
      HR,
      TELEGRAM,
      SHORT_STAYS,
      PRODUCTS,
      PROBLEM_REPORTS,
      MONTHLY_SERVICES,
      ABA_QR,
    ]).toEqual([false, false, false, false, false, false, false, false]);
  });

  it("TEST-FE-3156 no menu item, tab or sub-item opens a hidden part, even for a person with every right", () => {
    for (const page of HIDDEN) {
      expect(pageAllowed(page, EVERYTHING), page).toBe(false);
    }
    const shown = MENU.flatMap((group) =>
      group.items.flatMap((item) => allowedPagesOf(item, EVERYTHING)),
    );
    for (const page of HIDDEN) expect(shown).not.toContain(page);
    // What Parking uses stays.
    for (const page of [
      "home",
      "payments",
      "invoices",
      "reservations",
      "leases",
      "moveout",
      "customers",
      "units",
      "inspections",
      "reports",
      "settings",
    ] as const) {
      expect(pageAllowed(page, EVERYTHING), page).toBe(true);
    }
    const invoices = MENU.flatMap((group) => group.items).find(
      (item) => item.page === "invoices",
    );
    if (invoices === undefined) throw new Error("no Invoices item");
    expect(allowedPagesOf(invoices, EVERYTHING)).toEqual(["invoices"]);
  });

  it("TEST-FE-3157 Settings shows no Monthly services and no Booking sites", () => {
    expect(settingsTabShownOnParking("services")).toBe(false);
    expect(settingsTabShownOnParking("sites")).toBe(false);
    expect(settingsTabShownOnParking("units")).toBe(true);
    const settings = MENU.flatMap((group) => group.items).find(
      (item) => item.page === "settings",
    );
    if (settings === undefined) throw new Error("no Settings item");
    const keys = subItemsOf(settings, "settings", null, EVERYTHING, "en").map(
      (item) => item.key,
    );
    expect(keys).not.toContain("services");
    expect(keys).not.toContain("sites");
    expect(keys).toContain("units");
  });
});
