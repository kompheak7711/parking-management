import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type HomePage,
  ReportsNotAllowedError,
  ReportsUnavailableError,
  type TodoItem,
} from "../reportsClient";
import { hashForPage } from "../shell/navigation";
import { HomeScreen } from "./HomeScreen";

afterEach(() => {
  cleanup();
});

const PAGE: HomePage = {
  as_of: "2026-11-03T03:30:00Z",
  business_date: "2026-11-03",
  timezone: "Asia/Phnom_Penh",
  sections: [
    "units",
    "invoices",
    "payments",
    "leases",
    "approvals",
    "readings",
    "letters",
  ],
  cards: {
    units_occupied: { occupied: 21, reserved: 1, vacant: 1, total: 23 },
    pending_payment: { amount_usd_cents: 609_125, invoice_count: 33 },
    overdue: { amount_usd_cents: 65_120, invoice_count: 3 },
    paid_this_month: {
      billed_usd_cents: 911_125,
      billed_paid_usd_cents: 371_620,
      invoice_count: 41,
      received_usd_cents: 400_000,
      payment_count: 12,
    },
    lease_renewal: { count: 2, end_on_or_before: "2027-01-02" },
    waiting_for_approval: {
      count: 1,
      money_out_usd_cents: 500,
      money_out_count: 1,
    },
    meter_readings_missing: { count: 15, reading_date: "2026-11-24" },
    letters_due: { count: 1, day_20: 1, day_30: 0 },
  },
  todo: [
    {
      kind: "overdue_initial_rent",
      date: "2026-10-05",
      group: "overdue",
      invoice_id: "inv-6",
      invoice_number: "INV260006",
      unit_number: "U201",
      customer_name: "Ouk Chanthy",
      balance_usd_cents: 21_000,
    },
    {
      kind: "letter_day_20",
      date: "2026-10-20",
      group: "overdue",
      invoice_number: "INV260006",
      unit_number: "U201",
      customer_name: "Ouk Chanthy",
    },
    {
      kind: "draft_waiting",
      date: "2026-11-02",
      group: "overdue",
      draft_id: "d-1",
      draft_kind: "REFUND",
    },
    {
      kind: "deposit_decision",
      date: "2026-11-01",
      group: "overdue",
      reservation_id: "res-305",
      unit_number: "U305",
      customer_name: "Long Sreyneang",
    },
    {
      kind: "reservation_expiring",
      date: "2026-11-05",
      group: "this_week",
      reservation_id: "res-406",
      unit_number: "U406",
      customer_name: "Tep Sreymom",
    },
    {
      kind: "lease_ending",
      date: "2026-12-31",
      group: "later",
      lease_id: "lease-204",
      unit_number: "U204",
      customer_name: "Lim Dara",
    },
    {
      kind: "refund_due",
      date: "2027-01-07",
      group: "later",
      lease_id: "lease-110",
      unit_number: "U110",
      customer_name: "Sok Mean",
      held_usd_cents: 40_000,
    },
  ],
  todo_counts: { overdue: 4, today: 0, this_week: 1, later: 2 },
  jobs: {
    last_billing_at: "2026-10-24T23:00:00Z",
    rate_updated_at: "2026-11-03T01:00:00Z",
    next_billing_date: "2026-11-25",
  },
};

function show(
  home: () => Promise<HomePage>,
  {
    capabilities = null as ReadonlySet<string> | null,
    language = "en" as "en" | "km",
  } = {},
) {
  const api = { home: vi.fn(home) };
  const view = render(
    <HomeScreen
      active
      capabilities={capabilities}
      homeApi={api}
      language={language}
      propertyId="property-1"
    />,
  );
  return { api, view };
}

const card = (name: RegExp) => {
  const link = screen
    .getAllByRole("link")
    .find((element) => name.test(element.textContent));
  if (link === undefined) throw new Error(`no card ${String(name)}`);
  return link;
};

describe("Home", () => {
  it("TEST-FE-928 shows the eight cards in the mock-up order with their notes and links, and the head buttons", async () => {
    const { api } = show(() => Promise.resolve(PAGE));
    expect(await screen.findByText("21 / 23")).toBeTruthy();
    expect(api.home).toHaveBeenCalledWith("property-1");
    expect(screen.getByText("Tuesday 03/11/2026 · As of 10:30")).toBeTruthy();

    const labels = Array.from(
      document.querySelectorAll(".ui-home-kpi .ui-kpi-label"),
    ).map((element) => element.textContent);
    expect(labels).toEqual([
      "Parking occupied",
      "Pending payment",
      "Paid for November",
      "Overdue",
      "Lease renewal",
      "Waiting for approval",
      "Meter readings missing",
      "Letters due",
    ]);
    expect(card(/Parking occupied/).textContent).toContain(
      "1 reserved · 1 vacant",
    );
    expect(card(/Waiting for approval/).textContent).toContain(
      "1 to confirm · $5.00 money out",
    );
    expect(card(/Pending payment/).textContent).toContain(
      "$6,091.2533 Invoices not fully paid",
    );
    // Paid for this month counts Invoices due this month: 371,620 of 911,125 is 40.8%.
    expect(card(/Paid for November/).textContent).toContain(
      "$3,716.2040% of $9,111.25 billed",
    );
    expect(card(/Overdue/).getAttribute("href")).toBe("#/invoices");
    expect(card(/Lease renewal/).textContent).toContain(
      "End before 02/01/2027",
    );
    expect(card(/Waiting for approval/).getAttribute("href")).toBe(
      "#/approvals",
    );
    expect(card(/Meter readings missing/).textContent).toContain(
      "Reading day 24/11/2026",
    );
    expect(card(/Letters due/).getAttribute("href")).toBe("#/letters");
    expect(
      screen.getByText(
        "Rent and Utility Invoices made on 25/10/2026 06:00 · ABA exchange rate updated on 03/11/2026 08:00 · Next Invoices: 25/11/2026",
      ),
    ).toBeTruthy();

    expect(
      screen
        .getByRole("link", { name: "Receive payment" })
        .getAttribute("href"),
    ).toBe("#/payments/receive");
    expect(
      screen
        .getByRole("link", { name: "Enter meter readings" })
        .getAttribute("href"),
    ).toBe("#/utilities");
  });

  it("TEST-FE-929 lists what to do by group, top down (a wait that began earlier is for today), with dates, late or ago words and a named link for each row; Later folds", async () => {
    show(() => Promise.resolve(PAGE));
    const list = await screen.findByRole("region", { name: "What to do" });
    expect(
      within(list).getByText(
        "2 overdue, 2 for today, 1 this week. Do them from the top down.",
      ),
    ).toBeTruthy();

    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((row) => row.querySelector("b")?.textContent)).toEqual([
      "INV260006: $210.00 not paid",
      "Day 20 letter due: U201",
      "Refund waiting for approval",
      "Deposit waiting for a decision: U305",
      "Reservation for U406 ends",
    ]);
    expect(rows[0]?.textContent).toContain("Ouk Chanthy · U201 · Initial Rent");
    expect(rows[0]?.textContent).toContain("05/10/202629 days late");
    expect(rows[2]?.textContent).toContain("yesterday");
    expect(rows[3]?.textContent).toContain("2 days ago");
    expect(rows[4]?.textContent).toContain("in 2 days");
    expect(
      within(list)
        .getByRole("link", {
          name: "Open Invoice: INV260006: $210.00 not paid",
        })
        .getAttribute("href"),
    ).toBe(hashForPage("invoices", "inv:inv-6"));
    expect(
      within(list)
        .getByRole("link", { name: "Open Letters: Day 20 letter due: U201" })
        .getAttribute("href"),
    ).toBe("#/letters");
    expect(
      within(list)
        .getByRole("link", {
          name: "Open Reservation: Deposit waiting for a decision: U305",
        })
        .getAttribute("href"),
    ).toBe("#/reservations/res-305");

    fireEvent.click(within(list).getByRole("button", { name: "Show 2" }));
    const later = within(list).getAllByRole("listitem").slice(5);
    expect(later.map((row) => row.querySelector("b")?.textContent)).toEqual([
      "Lease for U204 ends",
      "Deposit refund due: U110",
    ]);
    expect(later[1]?.textContent).toContain("Sok Mean · $400.00 held");
    expect(
      within(list)
        .getByRole("link", { name: "Open Lease: Lease for U204 ends" })
        .getAttribute("href"),
    ).toBe("#/leases/lease-204");
    fireEvent.click(within(list).getByRole("button", { name: "Hide" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
  });

  it("TEST-FE-930 shows only the cards the answer holds, leaves out unknown to-do kinds, empty groups say so, the jobs line says when no billing ran, and the head buttons follow the rights", async () => {
    show(
      () =>
        Promise.resolve({
          ...PAGE,
          sections: ["units", "readings"],
          cards: {
            units_occupied: { occupied: 0, reserved: 0, vacant: 0, total: 0 },
            meter_readings_missing: { count: 0, reading_date: "2026-11-24" },
          },
          // A kind this screen does not know yet is left out, not shown broken.
          todo: [
            {
              kind: "something_new" as TodoItem["kind"],
              date: "2026-11-03",
              group: "today",
            },
          ],
          todo_counts: { overdue: 0, today: 1, this_week: 0, later: 0 },
          jobs: { last_billing_at: null, next_billing_date: "2026-11-25" },
        }),
      { capabilities: new Set(["units.read", "utility.read"]) },
    );
    expect(await screen.findByText("0 / 0")).toBeTruthy();
    expect(document.querySelectorAll(".ui-home-kpi")).toHaveLength(2);
    expect(screen.queryByText("Pending payment")).toBeNull();
    expect(screen.getByText("Nothing is overdue.")).toBeTruthy();
    expect(screen.getAllByText("Nothing here.")).toHaveLength(3);
    expect(
      screen.getByText(
        "0 overdue, 0 for today, 0 this week. Do them from the top down.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "No billing run has finished yet · Next Invoices: 25/11/2026",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Receive payment" })).toBeNull();
    expect(
      screen.queryByRole("link", { name: "Enter meter readings" }),
    ).toBeNull();
  });

  it("TEST-FE-931 a failed read offers Retry and shows no old numbers; no right to read says so; Khmer words come from the mock-up", async () => {
    let fail = true;
    const { api } = show(() =>
      fail
        ? Promise.reject(new ReportsUnavailableError())
        : Promise.resolve(PAGE),
    );
    expect(
      await screen.findByText(
        "Home could not be read just now. Check the connection and try again.",
      ),
    ).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("21 / 23")).toBeTruthy();
    expect(api.home).toHaveBeenCalledTimes(2);
    cleanup();

    show(() => Promise.reject(new ReportsNotAllowedError()));
    expect(
      await screen.findByText(
        "Your account cannot see the Home numbers. Use the menu to open your work.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();

    show(() => Promise.resolve(PAGE), { language: "km" });
    expect(await screen.findByText("ចំណតមានអ្នកជួល")).toBeTruthy();
    expect(screen.getByText("អ្វីដែលត្រូវធ្វើ")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText("បានបង់សម្រាប់ខែវិច្ឆិកា")).toBeTruthy();
    });
  });
});
