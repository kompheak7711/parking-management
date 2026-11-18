import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  GENERAL_LEDGER,
  HR,
  PROBLEM_REPORTS,
  PRODUCTS,
  SHORT_STAYS,
  TELEGRAM,
} from "../leases/parking";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type HomePage,
  ReportsNotAllowedError,
  ReportsUnavailableError,
  type TodoItem,
} from "../reportsClient";
import { hashForPage } from "../shell/navigation";
import { HomeScreen, partsText, readingsMissing } from "./HomeScreen";

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
    // UI v81 round 4
    birthdays: { count: 3, from: "2026-11-03", to: "2026-11-10" },
    paid_on_time: { on_time: 95, invoice_count: 120 },
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
  it("TEST-FE-928 shows the cards in the owner's order (12/11/2026) with their notes and links, and the head buttons", async () => {
    const { api } = show(() => Promise.resolve(PAGE));
    expect(await screen.findByText("Vacant Parking")).toBeTruthy();
    expect(api.home).toHaveBeenCalledWith("property-1");
    // UI v81 round 4 (owner 08/11/2026): no line under the title any more.
    expect(screen.queryByText(/As of 10:30/)).toBeNull();

    const labels = Array.from(
      document.querySelectorAll(".ui-home-kpi .ui-kpi-label"),
    ).map((element) => element.textContent);
    // Owner 12/11/2026: Vacant Units takes the place of Occupancy and there is no Paid on time
    // card; the cards from other reads are in TEST-FE-1931.
    expect(labels).toEqual([
      "Vacant Parking",
      "Leases ending soon",
      "Unpaid",
      "Paid this month",
      "Overdue",
      "Approvals",
      "Missing readings",
      "Notices due",
      "Birthdays",
    ]);
    expect(screen.queryByText("Paid on time")).toBeNull();
    expect(screen.queryByText("Occupancy")).toBeNull();
    expect(card(/Birthdays/).textContent).toContain("3Today to 10/11/2026");
    // UI v81 round 11: each card opens the part of the page that it counts (TEST-FE-1942).
    expect(card(/Birthdays/).getAttribute("href")).toBe(
      "#/customers?show=birthdays",
    );
    // Only the vacant Units are counted; the note says how many Units there are.
    expect(card(/Vacant Parking/).textContent).toBe(
      "Vacant Parking123 Parking · 1 reserved",
    );
    expect(card(/Vacant Parking/).getAttribute("href")).toBe(
      "#/units?show=vacant",
    );
    // Owner 14/11/2026: a card has a note only when it tells something the number does not.
    expect(card(/Approvals/).textContent).toBe(
      "Approvals1Refunds pending $5.00",
    );
    expect(card(/^Unpaid/).textContent).toBe("Unpaid$6,091.25");
    // Paid this month is the money received this month (owner 16/11/2026); no note, no bar.
    expect(card(/Paid this month/).textContent).toBe(
      "Paid this month$4,000.00",
    );
    expect(document.querySelector(".ui-home-meter")).toBeNull();
    expect(card(/Overdue/).getAttribute("href")).toBe(
      "#/invoices?show=overdue",
    );
    expect(card(/Leases ending soon/).textContent).toContain(
      "End before 02/01/2027",
    );
    expect(card(/Approvals/).getAttribute("href")).toBe("#/approvals");
    // The business date (03/11) is before the Reading day (24/11): nothing is missing yet.
    expect(card(/Missing readings/).textContent).toBe("Missing readings0");
    expect(card(/Missing readings/)).toHaveClass("none");
    expect(card(/Notices due/).getAttribute("href")).toBe("#/letters?show=due");
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

  it("TEST-FE-1912 (UI v81 round 2, order of 12/11/2026) adds the Viewing requests waiting card after Vacant Parking, and Problem reports before Birthdays, for a person who may read them", async ({
    skip,
  }) => {
    // Parking Step 6: no Viewing requests on Parking (TELEGRAM).
    skip(!TELEGRAM);
    const problemsApi = {
      summary: vi.fn().mockResolvedValue({
        open: 4,
        urgent: 1,
        late: 0,
        costs_to_check: [],
      }),
    };
    const visitsApi = {
      visitRequests: vi.fn().mockResolvedValue({
        today: "2026-11-03",
        requests: [
          { status: "NEW", late: true, visit_local: null },
          { status: "NEW", late: false, visit_local: "2026-11-05T10:00" },
          { status: "CONTACTED", late: false, visit_local: "2026-11-07T15:00" },
          { status: "CLOSED", late: false, visit_local: "2026-10-20T15:00" },
        ],
      }),
    };
    render(
      <HomeScreen
        active
        capabilities={
          new Set([
            "reports.home",
            "problem_reports.read",
            "visit_requests.read",
          ])
        }
        homeApi={{ home: vi.fn(() => Promise.resolve(PAGE)) }}
        language="en"
        problemsApi={problemsApi as never}
        propertyId="property-1"
        visitsApi={visitsApi}
      />,
    );
    expect(await screen.findByText("Viewing requests")).toBeTruthy();
    expect(visitsApi.visitRequests).toHaveBeenCalledWith("property-1");
    const labels = Array.from(
      document.querySelectorAll(".ui-home-kpi .ui-kpi-label"),
    ).map((element) => element.textContent);
    // Owner 12/11/2026: Viewing requests waiting is the second card, after Vacant Units;
    // Problem reports sits before Birthdays.
    expect(labels.slice(0, 3)).toEqual([
      "Vacant Parking",
      "Viewing requests",
      "Leases ending soon",
    ]);
    expect(labels.slice(-2)).toEqual(["Problem reports", "Birthdays"]);
    const visits = card(/Viewing requests/);
    expect(visits.textContent).toContain("21 late · 2 visits this week");
    expect(visits.getAttribute("href")).toBe("#/visitreqs?show=waiting");
    expect(visits.className).toContain("err");
  });

  it("TEST-FE-929 shows the Tasks as four cards with a count and a line each, Overdue open at first (red when above 0), one list at a time (a wait that began earlier is for today; dates, late or ago words and a named link per row), and keeps the chosen card in the address", async () => {
    window.history.replaceState(null, "", "#/home");
    show(() => Promise.resolve(PAGE));
    const list = await screen.findByRole("region", { name: "Tasks" });
    // UI v81 round 4 (owner 08/11/2026): no summary line under "Tasks".
    expect(within(list).queryByText(/Do them from the top down/)).toBeNull();
    const taskCard = (name: RegExp) =>
      within(list).getByRole("button", { name });
    const titles = () =>
      within(list)
        .queryAllByRole("listitem")
        .map((row) => row.querySelector("b")?.textContent);

    expect(taskCard(/^Overdue/).textContent).toBe(
      "Overdue2Oldest: 29 days late",
    );
    expect(taskCard(/^Today/).textContent).toBe("Today2");
    expect(taskCard(/^This week/).textContent).toBe(
      "This week1Next: in 2 days",
    );
    expect(taskCard(/^Later/).textContent).toBe("Later2Next: in 58 days");
    expect(taskCard(/^Overdue/).className).toContain("err");
    expect(taskCard(/^Overdue/).getAttribute("aria-pressed")).toBe("true");
    expect(taskCard(/^Today/).getAttribute("aria-pressed")).toBe("false");

    // Overdue is open: its two rows, oldest first, each with a named link.
    const rows = within(list).getAllByRole("listitem");
    expect(titles()).toEqual([
      "INV260006: $210.00 not paid",
      "Rent notice due: U201",
    ]);
    expect(rows[0]?.textContent).toContain("Ouk Chanthy · U201 · Initial Rent");
    expect(rows[0]?.textContent).toContain("05/10/202629 days late");
    expect(
      within(list)
        .getByRole("link", {
          name: "Open Invoice: INV260006: $210.00 not paid",
        })
        .getAttribute("href"),
    ).toBe(hashForPage("invoices", "inv:inv-6"));
    expect(
      within(list)
        .getByRole("link", { name: "Open Notices: Rent notice due: U201" })
        .getAttribute("href"),
    ).toBe("#/letters");

    fireEvent.click(taskCard(/^Today/));
    expect(window.location.hash).toBe("#/home?tasks=today");
    expect(taskCard(/^Today/).getAttribute("aria-pressed")).toBe("true");
    expect(taskCard(/^Overdue/).getAttribute("aria-pressed")).toBe("false");
    expect(titles()).toEqual([
      "Refund pending approval",
      "Deposit pending a decision: U305",
    ]);
    const today = within(list).getAllByRole("listitem");
    expect(today[0]?.textContent).toContain("yesterday");
    expect(today[1]?.textContent).toContain("2 days ago");
    expect(
      within(list)
        .getByRole("link", {
          name: "Open Reservation: Deposit pending a decision: U305",
        })
        .getAttribute("href"),
    ).toBe("#/reservations/res-305");

    fireEvent.click(taskCard(/^This week/));
    expect(window.location.hash).toBe("#/home?tasks=week");
    expect(titles()).toEqual(["Reservation for U406 ends"]);
    expect(within(list).getByRole("listitem").textContent).toContain(
      "in 2 days",
    );

    fireEvent.click(taskCard(/^Later/));
    expect(window.location.hash).toBe("#/home?tasks=later");
    expect(titles()).toEqual([
      "Lease for U204 ends",
      "Deposit refund due: U110",
    ]);
    expect(within(list).getAllByRole("listitem")[1]?.textContent).toContain(
      "Sok Mean · $400.00 held",
    );
    expect(
      within(list)
        .getByRole("link", { name: "Open Lease: Lease for U204 ends" })
        .getAttribute("href"),
    ).toBe("#/leases/lease-204");

    // The same card again closes the list.
    fireEvent.click(taskCard(/^Later/));
    expect(window.location.hash).toBe("#/home");
    expect(taskCard(/^Later/).getAttribute("aria-pressed")).toBe("false");
    expect(titles()).toEqual([]);
    // Owner 14/11/2026: no help line under the Tasks.
    expect(screen.queryByText(/Tap a card to see its list/)).toBeNull();
  });

  it("TEST-FE-1915 the Tasks card named in the address opens at once (#/home?tasks=later); with nothing overdue no list is open and the Overdue count is not red", async () => {
    window.history.replaceState(null, "", "#/home?tasks=later");
    show(() => Promise.resolve(PAGE));
    const list = await screen.findByRole("region", { name: "Tasks" });
    expect(
      within(list)
        .getByRole("button", { name: /^Later/ })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((row) => row.querySelector("b")?.textContent),
    ).toEqual(["Lease for U204 ends", "Deposit refund due: U110"]);
    cleanup();

    window.history.replaceState(null, "", "#/home");
    show(() =>
      Promise.resolve({
        ...PAGE,
        todo: PAGE.todo.filter((item) => item.group !== "overdue"),
      }),
    );
    const quiet = await screen.findByRole("region", { name: "Tasks" });
    const overdue = within(quiet).getByRole("button", { name: /^Overdue/ });
    expect(overdue.textContent).toBe("Overdue0");
    expect(overdue.className).not.toContain("err");
    expect(overdue.getAttribute("aria-pressed")).toBe("false");
    expect(
      within(quiet).getByRole("button", { name: /^Today/ }).textContent,
    ).toBe("Today0");
    expect(within(quiet).queryAllByRole("listitem")).toHaveLength(0);
    expect(window.location.hash).toBe("#/home");
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
    expect(
      (await screen.findByText("Vacant Parking")).closest("a"),
    ).toHaveClass("none");
    expect(document.querySelectorAll(".ui-home-kpi")).toHaveLength(2);
    expect(screen.queryByText("Unpaid")).toBeNull();
    // Owner 14/11/2026: an empty Tasks card has no "Nothing here" line.
    expect(screen.queryByText("Nothing overdue")).toBeNull();
    expect(screen.queryByText("Nothing here")).toBeNull();
    expect(screen.queryByText(/Do them from the top down/)).toBeNull();
    // The warning is a slim bar under the title, before the cards (owner 14/11/2026).
    const jobs = screen.getByText(
      "No billing run has finished yet · Next Invoices: 25/11/2026",
    ).parentElement;
    expect(jobs).toHaveClass("ui-notice", "warn", "ui-home-jobs");
    expect(
      jobs?.compareDocumentPosition(
        document.querySelector(".ui-home-kpis") as Node,
      ),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
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
        "Home could not be loaded. Check the connection and try again.",
      ),
    ).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Vacant Parking")).toBeTruthy();
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
    expect(await screen.findByText("ចំណតទំនេរ")).toBeTruthy();
    expect(screen.getByText("ការងារត្រូវធ្វើ")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText("បានបង់ខែនេះ")).toBeTruthy();
    });
  });

  it("TEST-FE-1294 the Problem reports card shows open, urgent and late to a person who may read them; a Manager who checks repair costs sees each cost still waiting with a link; a person without the right reads nothing", async ({
    skip,
  }) => {
    // Parking Step 6: no Problem reports on Parking.
    skip(!PROBLEM_REPORTS);
    const summary = vi.fn(() =>
      Promise.resolve({
        open: 4,
        urgent: 1,
        late: 2,
        costs_to_check: [
          {
            report_id: "r-7",
            report_number: "UP260007",
            kind: "UNIT" as const,
            unit_number: "U101",
            place_en: null,
            place_kh: null,
            entered_at: "2026-11-04T02:40:00Z",
            totals: [
              { currency: "USD" as const, amount_minor: 1400 },
              { currency: "KHR" as const, amount_minor: 40000 },
            ],
          },
        ],
      }),
    );
    const showWith = (capabilities: ReadonlySet<string>) =>
      render(
        <HomeScreen
          active
          capabilities={capabilities}
          homeApi={{ home: vi.fn(() => Promise.resolve(PAGE)) }}
          language="en"
          problemsApi={{ summary }}
          propertyId="property-1"
        />,
      );

    showWith(new Set(["reports.read"]));
    expect(await screen.findByText("Vacant Parking")).toBeTruthy();
    expect(summary).not.toHaveBeenCalled();
    expect(screen.queryByText("Problem reports")).toBeNull();
    cleanup();

    showWith(new Set(["reports.read", "problem_reports.read"]));
    expect(await screen.findByText("1 urgent · 2 late")).toBeTruthy();
    expect(summary).toHaveBeenCalledWith("property-1");
    expect(card(/Problem reports/).getAttribute("href")).toBe(
      "#/problems?show=open",
    );
    expect(screen.queryByText("Repair costs to check")).toBeNull();
    cleanup();

    showWith(
      new Set([
        "reports.read",
        "problem_reports.read",
        "problem_reports.costs",
      ]),
    );
    const costs = await screen.findByRole("region", {
      name: "Repair costs to check",
    });
    expect(
      within(costs)
        .getByRole("link", { name: "UP260007" })
        .getAttribute("href"),
    ).toBe(hashForPage("problems", "pr:r-7"));
    expect(within(costs).getByText(/U101 · \$14\.00 \+ 40,000 ៛/)).toBeTruthy();
  });

  it("TEST-FE-1925 Home batch (owner 08/11/2026): Home is drawn with the shared PageHeader (one title, the two buttons beside it) and its cards with the shared CardGrid, the Tasks cards as one named group", async () => {
    show(() => Promise.resolve(PAGE));
    expect(await screen.findByText("Vacant Parking")).toBeTruthy();
    const head = document.querySelector("header.ui-pagehead");
    if (!(head instanceof HTMLElement)) throw new Error("no page header");
    expect(
      within(head).getByRole("heading", { level: 1, name: "Home" }),
    ).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(
      within(head)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Receive payment", "Enter meter readings"]);
    const cards = document.querySelector(".ui-kpis.ui-home-kpis");
    expect(cards?.querySelectorAll(".ui-home-kpi")).toHaveLength(9);
    // Owner 12/11/2026 10:47: the Home cards are five in a row; the Tasks cards stay four.
    expect(cards).toHaveClass("ui-five");
    const tasks = screen.getByRole("group", { name: "Tasks" });
    expect(tasks).toHaveClass("ui-kpis", "ui-tasks");
    expect(tasks).not.toHaveClass("ui-five");
    expect(within(tasks).getAllByRole("button")).toHaveLength(4);
  });

  it("TEST-FE-1931 (owner 12/11/2026) an Owner sees the fifteen cards in the owner's order: the two Short stays cards, Low stock in place of Paid on time, and Attendance last as a card; a read that fails leaves only its own card out", async ({
    skip,
  }) => {
    // Parking Step 6: this test counts the cards of parts hidden on Parking.
    skip(
      !(
        GENERAL_LEDGER &&
        HR &&
        PRODUCTS &&
        PROBLEM_REPORTS &&
        SHORT_STAYS &&
        TELEGRAM
      ),
    );
    const all = new Set([
      "reports.home",
      "visit_requests.read",
      "short_stays.read",
      "problem_reports.read",
      "products.read",
      "hr.attendance.read",
    ]);
    const booking = (
      status: string,
      check_in_on: string,
      check_out_on: string,
    ) => ({ status, check_in_on, check_out_on });
    const reads = {
      problemsApi: {
        summary: vi.fn().mockResolvedValue({
          open: 4,
          urgent: 0,
          late: 0,
          costs_to_check: [],
        }),
      },
      visitsApi: {
        visitRequests: vi
          .fn()
          .mockResolvedValue({ today: "2026-11-03", requests: [] }),
      },
      shortStaysApi: {
        list: vi.fn().mockResolvedValue([
          booking("BOOKED", "2026-11-03", "2026-11-05"),
          booking("BOOKED", "2026-11-09", "2026-11-12"),
          booking("BOOKED", "2026-11-20", "2026-11-21"),
          booking("CHECKED_IN", "2026-11-01", "2026-11-04"),
          booking("CHECKED_IN", "2026-11-02", "2026-11-06"),
          // Stays that ended or never began are not counted.
          booking("CHECKED_OUT", "2026-10-30", "2026-11-03"),
          booking("CANCELLED", "2026-11-03", "2026-11-04"),
          booking("NO_SHOW", "2026-11-02", "2026-11-03"),
        ]),
      },
      productsApi: {
        catalogue: vi.fn().mockResolvedValue({
          rules: {},
          categories: [],
          products: [
            { low_stock: true, discontinued: false },
            { low_stock: true, discontinued: false },
            { low_stock: false, discontinued: false },
            // A product no longer sold is not counted.
            { low_stock: true, discontinued: true },
          ],
        }),
      },
      attendanceApi: {
        day: vi.fn().mockResolvedValue({
          people: [
            { no_check_out: true, scans: [] },
            {
              no_check_out: false,
              scans: [{ needs_check: true, accepted: false }],
            },
            {
              no_check_out: true,
              scans: [{ needs_check: true, accepted: false }],
            },
            {
              no_check_out: false,
              scans: [{ needs_check: true, accepted: true }],
            },
          ],
        }),
      },
    };
    const showAll = (
      over: Record<string, unknown> = {},
      capabilities: ReadonlySet<string> = all,
    ) =>
      render(
        <HomeScreen
          active
          capabilities={capabilities}
          homeApi={{ home: vi.fn(() => Promise.resolve(PAGE)) }}
          language="en"
          propertyId="property-1"
          {...({ ...reads, ...over } as object)}
        />,
      );
    const names = () =>
      Array.from(
        document.querySelectorAll(".ui-home-kpis .ui-home-kpi .ui-kpi-label"),
      ).map((element) => element.textContent);

    showAll();
    expect(await screen.findByText("Attendance")).toBeTruthy();
    await waitFor(() => {
      expect(names()).toEqual([
        "Vacant Parking",
        "Viewing requests",
        "Leases ending soon",
        "Bookings",
        "Checked in",
        "Unpaid",
        "Paid this month",
        "Overdue",
        "Approvals",
        "Missing readings",
        "Notices due",
        "Problem reports",
        "Birthdays",
        "Low stock",
        "Attendance",
      ]);
    });
    expect(reads.shortStaysApi.list).toHaveBeenCalledWith("property-1");
    expect(reads.productsApi.catalogue).toHaveBeenCalledWith("property-1");
    expect(reads.attendanceApi.day).toHaveBeenCalledWith("property-1", null);

    // Booked and not checked in yet; one of the three arrives on the business date.
    const booked = card(/Bookings/);
    expect(booked.textContent).toBe("Bookings31 arrives today");
    expect(booked.getAttribute("href")).toBe("#/shortstays?show=booked");
    // Staying now; nobody checks out on the business date.
    const staying = card(/Checked in/);
    // Owner 14/11/2026: "None check out today" is not drawn.
    expect(staying.textContent).toBe("Checked in2");
    expect(staying.getAttribute("href")).toBe("#/shortstays?show=checked_in");
    const low = card(/Low stock/);
    expect(low.textContent).toBe("Low stock2");
    expect(low.getAttribute("href")).toBe("#/products?show=low");
    // Three people need a look: two scans to check, two with no check-out (one has both).
    const attendance = card(/Attendance/);
    expect(attendance.textContent).toBe(
      "Attendance3Needs check 2 · No check-out 2",
    );
    expect(attendance.getAttribute("href")).toBe("#/attendance?show=day");
    expect(attendance).toHaveClass("warn");
    // The old banner above the cards is gone.
    expect(screen.queryByText(/Attendance needs attention/)).toBeNull();
    expect(
      screen.queryByRole("link", { name: "Open the daily sheet" }),
    ).toBeNull();
    cleanup();

    // Each of these reads can fail by itself; the other cards still show.
    showAll({
      shortStaysApi: { list: vi.fn().mockRejectedValue(new Error("down")) },
      productsApi: {
        catalogue: vi.fn().mockRejectedValue(new Error("down")),
      },
      attendanceApi: {
        day: vi.fn().mockResolvedValue({ people: [] }),
      },
    });
    expect(await screen.findByText("Attendance")).toBeTruthy();
    expect(card(/Attendance/).textContent).toBe("Attendance0");
    expect(card(/Attendance/)).toHaveClass("none");
    expect(names()).not.toContain("Bookings");
    expect(names()).not.toContain("Checked in");
    expect(names()).not.toContain("Low stock");
    cleanup();

    // A person without the three rights reads none of them.
    const quiet = {
      shortStaysApi: { list: vi.fn() },
      productsApi: { catalogue: vi.fn() },
      attendanceApi: { day: vi.fn() },
    };
    showAll(quiet, new Set(["reports.home"]));
    expect(await screen.findByText("Vacant Parking")).toBeTruthy();
    expect(quiet.shortStaysApi.list).not.toHaveBeenCalled();
    expect(quiet.productsApi.catalogue).not.toHaveBeenCalled();
    expect(quiet.attendanceApi.day).not.toHaveBeenCalled();
    expect(names()).not.toContain("Attendance");
  });

  it("TEST-FE-1932 (owner 12/11/2026) every Home card and Tasks card holds its number beside its name, in the card's head, with the note under it; only Paid this month has a bar", async () => {
    show(() => Promise.resolve(PAGE));
    expect(await screen.findByText("Vacant Parking")).toBeTruthy();
    const cards = Array.from(
      document.querySelectorAll(".ui-home-kpis .ui-kpi, .ui-tasks .ui-kpi"),
    );
    expect(cards).toHaveLength(13);
    for (const each of cards) {
      expect(each).toHaveClass("ui-kpi-top");
      const head = each.firstElementChild;
      expect(head).toHaveClass("ui-kpi-head");
      expect(
        Array.from(head?.children ?? []).map((part) => part.className),
      ).toEqual(["ui-kpi-label", "ui-kpi-value ui-num"]);
      // Owner 14/11/2026: the note, when there is one, is under the head.
      const note = head?.nextElementSibling;
      if (note !== null && note !== undefined)
        expect(note).toHaveClass("ui-kpi-note");
    }
    // No bar under Paid this month any more (owner 14/11/2026).
    expect(document.querySelectorAll(".ui-home-meter")).toHaveLength(0);
  });

  it('TEST-FE-1942 (owner 12/11/2026: "check all card is link to correct place") each Home card opens the part of its page that the card counts, named by a word in the address; Approvals, which has one view, opens the page', async ({
    skip,
  }) => {
    // Parking Step 6: this test opens the cards of parts hidden on Parking.
    skip(
      !(
        GENERAL_LEDGER &&
        HR &&
        PRODUCTS &&
        PROBLEM_REPORTS &&
        SHORT_STAYS &&
        TELEGRAM
      ),
    );
    render(
      <HomeScreen
        active
        capabilities={
          new Set([
            "reports.home",
            "visit_requests.read",
            "short_stays.read",
            "problem_reports.read",
            "products.read",
            "hr.attendance.read",
          ])
        }
        homeApi={{ home: vi.fn(() => Promise.resolve(PAGE)) }}
        language="en"
        propertyId="property-1"
        {...({
          problemsApi: {
            summary: vi.fn().mockResolvedValue({
              open: 4,
              urgent: 0,
              late: 0,
              costs_to_check: [],
            }),
          },
          visitsApi: {
            visitRequests: vi
              .fn()
              .mockResolvedValue({ today: "2026-11-03", requests: [] }),
          },
          shortStaysApi: { list: vi.fn().mockResolvedValue([]) },
          productsApi: {
            catalogue: vi
              .fn()
              .mockResolvedValue({ rules: {}, categories: [], products: [] }),
          },
          attendanceApi: { day: vi.fn().mockResolvedValue({ people: [] }) },
        } as object)}
      />,
    );
    const addresses = () =>
      Array.from(document.querySelectorAll(".ui-home-kpis a.ui-home-kpi")).map(
        (link) => [
          link.querySelector(".ui-kpi-label")?.textContent,
          link.getAttribute("href"),
        ],
      );
    await waitFor(() => {
      expect(addresses()).toEqual([
        ["Vacant Parking", "#/units?show=vacant"],
        ["Viewing requests", "#/visitreqs?show=waiting"],
        ["Leases ending soon", "#/leases?show=ending"],
        ["Bookings", "#/shortstays?show=booked"],
        ["Checked in", "#/shortstays?show=checked_in"],
        ["Unpaid", "#/invoices?show=open"],
        // The money received this month: the Payments page, which opens on This month.
        ["Paid this month", "#/payments"],
        ["Overdue", "#/invoices?show=overdue"],
        ["Approvals", "#/approvals"],
        ["Missing readings", "#/utilities?show=missing"],
        ["Notices due", "#/letters?show=due"],
        ["Problem reports", "#/problems?show=open"],
        ["Birthdays", "#/customers?show=birthdays"],
        ["Low stock", "#/products?show=low"],
        ["Attendance", "#/attendance?show=day"],
      ]);
    });
  });

  it("TEST-FE-2220 (Home screen review, owner 14/11/2026) Missing readings is 0 before the Reading day and the server's count from that day; a note says only the parts above 0", async () => {
    const readings = { count: 46, reading_date: "2026-11-24" };
    expect(readingsMissing(readings, "2026-11-13")).toBe(0);
    expect(readingsMissing(readings, "2026-11-24")).toBe(46);
    expect(readingsMissing(readings, "2026-11-30")).toBe(46);
    expect(
      partsText([
        [0, "0 urgent"],
        [0, "0 late"],
      ]),
    ).toBeUndefined();
    expect(
      partsText([
        [1, "1 urgent"],
        [0, "0 late"],
      ]),
    ).toBe("1 urgent");
    expect(
      partsText([
        [1, "1 urgent"],
        [2, "2 late"],
      ]),
    ).toBe("1 urgent · 2 late");

    // On the Reading day the card shows the server's count.
    show(() =>
      Promise.resolve({
        ...PAGE,
        business_date: "2026-11-24",
      }),
    );
    expect(await screen.findByText("Vacant Parking")).toBeTruthy();
    expect(card(/Missing readings/).textContent).toBe("Missing readings15");
    // No card note that only says what the card opens.
    expect(screen.queryByText("Day-20 and day-30 notices")).toBeNull();
    expect(card(/Notices due/).querySelector(".ui-kpi-note")).toBeNull();
  });

  it("TEST-FE-2221 (Home screen review, owner 14/11/2026) the two head buttons share one equal-width group; a calm jobs line stays under the Tasks and no warning bar shows", async () => {
    show(() => Promise.resolve(PAGE));
    expect(await screen.findByText("Vacant Parking")).toBeTruthy();
    const buttons = [
      screen.getByRole("link", { name: "Receive payment" }),
      screen.getByRole("link", { name: "Enter meter readings" }),
    ];
    for (const button of buttons) expect(button).toHaveClass("ui-homeact");
    expect(buttons[0]?.parentElement).toBe(buttons[1]?.parentElement);
    expect(buttons[0]?.parentElement).toHaveClass("ui-pagehead-actions");
    expect(document.querySelector(".ui-home-jobs")).toBeNull();
    const calm = screen.getByText(/Rent and Utility Invoices made on/)
      .parentElement as Node;
    expect(
      document.querySelector(".ui-todo-card")?.compareDocumentPosition(calm),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});
