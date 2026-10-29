import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import {
  AUDIT,
  barRows,
  bodyRows,
  facts,
  footRow,
  headRow,
  INVOICES,
  OCCUPANCY,
  openReports,
  PROPERTY,
  type RegisterCall,
  STAFF,
  UTILITY_NO_MONEY,
} from "./reportsTestData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const NONE = "—";

function summaryCard(): HTMLElement {
  return screen.getByRole("region", { name: "Summary" });
}

describe("Registers", () => {
  it("TEST-FE-1043 Invoice register: the Summary gives issued, paid, settled another way and still owed with the void count, the overdue groups 1 to 19, 20 to 29 and 30 days or more, and the chart by issue month; every Invoice, Customer and Parking links to its page and the footer adds up the amounts", async () => {
    const page = openReports({ hash: "#/reports/invoice_register" });
    const table = await screen.findByRole("table", {
      name: "Invoice register and balances",
    });
    expect(page.register).toHaveBeenCalledWith(PROPERTY, "invoice_register", {
      limit: 200,
    });
    const summary = summaryCard();
    expect(facts(summary)).toEqual([
      ["Issued", "$1,300.00"],
      ["Paid to these Invoices", "$500.00"],
      ["Settled another way (Credit or Deposit)", "$100.00"],
      ["Still owed", "$700.00"],
      ["Invoices", "4", "1 void, listed but not added up"],
    ]);
    const groups = within(summary).getByRole("table", {
      name: "Overdue groups",
    });
    expect(headRow(groups)).toEqual(["", "Invoices", "Still owed"]);
    expect(bodyRows(groups)).toEqual([
      ["1 to 19 days", "1", "$100.00"],
      ["20 to 29 days", "0", "$0.00"],
      ["30 days or more", "1", "$500.00"],
    ]);
    expect(
      within(summary).getByRole("button", {
        name: "October 2026, Paid: $500.00, Settled another way: $100.00, Still owed: $200.00, Total: $800.00",
      }),
    ).toBeTruthy();

    expect(headRow(table)).toEqual([
      "Invoice No.",
      "Customer",
      "Parking",
      "Type",
      "Issued on",
      "Due date",
      "Amount",
      "Paid",
      "Settled another way",
      "Still owed",
      "Status",
    ]);
    expect(bodyRows(table)).toEqual([
      [
        "INV-0001",
        "Sok Dara",
        "U203",
        "Rent",
        "01/09/2026",
        "05/09/202653 days overdue",
        "$500.00",
        "$0.00",
        "$0.00",
        "$500.00",
        "Overdue",
      ],
      [
        "INV-0002",
        "Chan Sophea",
        "U101",
        "Utilities",
        "25/10/2026",
        "01/11/2026",
        "$400.00",
        "$200.00",
        "$100.00",
        "$100.00",
        "Part paid",
      ],
      [
        "INV-0003",
        "Sok Dara",
        "U204",
        "Services",
        "01/10/2026",
        "05/10/2026",
        "$300.00",
        "$300.00",
        "$0.00",
        "$0.00",
        "Paid",
      ],
      [
        "INV-0004",
        "Keo Mony",
        NONE,
        "Damage",
        "02/10/2026",
        "09/10/2026",
        "$200.00",
        "$0.00",
        "$0.00",
        "$0.00",
        "Void",
      ],
      [
        "INV-0005",
        "Sok Dara",
        "U203",
        "Miscellaneous",
        "20/10/2026",
        "27/10/20261 day overdue",
        "$100.00",
        "$0.00",
        "$0.00",
        "$100.00",
        "Overdue",
      ],
    ]);
    expect(footRow(table)).toEqual([
      "Total",
      "",
      "",
      "",
      "",
      "",
      "$1,300.00",
      "$500.00",
      "$100.00",
      "$700.00",
      "",
    ]);
    expect(
      within(table).getByRole("link", { name: "INV-0001" }),
    ).toHaveAttribute("href", hashForPage("invoices", "inv:inv-1"));
    expect(
      within(table).getByRole("link", { name: "Chan Sophea" }),
    ).toHaveAttribute("href", hashForPage("customers", "cust-2"));
    expect(within(table).getByRole("link", { name: "U101" })).toHaveAttribute(
      "href",
      hashForPage("units", "unit-101"),
    );
    expect(screen.getByText("5 rows")).toBeTruthy();
  });

  it("TEST-FE-1044 Payments: Money received and where the money went (Paid to Invoices with its Rent, Services, Utilities and Move-out charges, Deposits, Customer Credit, Late-payment charges, Not allocated), the sentence tying Paid to Invoices to the Invoice register, riel as information with its rate, and each Receipt linked", async () => {
    openReports({ hash: "#/reports/payments" });
    const table = await screen.findByRole("table", {
      name: "Payments and allocations",
    });
    const summary = summaryCard();
    expect(facts(summary)).toEqual([
      ["Money received", "$1,244.83"],
      ["Payments", "3"],
      ["Reversals", "-$400.00"],
      ["Received less reversals", "$844.83"],
    ]);
    expect(
      within(summary).getByText(
        "Riel received: 184,263 ៛. Counted at the dollar value recorded on the day; never added to USD.",
      ),
    ).toBeTruthy();
    const where = within(summary).getByRole("table", {
      name: "Where the money went",
    });
    expect(bodyRows(where)).toEqual([
      ["Paid to Invoices", "$744.83"],
      ["of which Rent", "$600.00"],
      ["of which Services", "$50.00"],
      ["of which Utilities", "$44.83"],
      ["of which Move-out charges", "$50.00"],
      ["Deposits", "$300.00"],
      ["Customer Credit", "$80.00"],
      ["Late-payment charges", "$20.00"],
      ["Not allocated", "$100.00"],
    ]);
    expect(footRow(where)).toEqual(["Money received", "$1,244.83"]);
    expect(
      within(summary).getByText(
        "Money received also holds deposits, late-payment charges and Credit that are not on an Invoice. Of this, $744.83 paid Invoices. Over the same records (period All), that is the Paid total in the Invoice register.",
      ),
    ).toBeTruthy();

    expect(bodyRows(table)).toEqual([
      [
        "RCPT-0001",
        "03/10/2026",
        "Sok Dara",
        "U203",
        "Cash",
        "$800.00",
        "Rent $600.00Services $50.00Deposits $150.00",
        NONE,
        "Received",
      ],
      [
        "RCPT-0002",
        "10/10/2026",
        "Chan Sophea",
        "U101",
        "ABA",
        "$44.83184,263 ៛ · 4,110 ៛ = $1.00",
        "Utilities $44.83",
        NONE,
        "Received",
      ],
      [
        "RCPT-0003",
        "20/10/2026",
        "Keo Mony",
        "U204",
        "Bank transfer",
        "$400.00",
        "Damage $30.00Miscellaneous $20.00Late-payment charges $20.00Deposits $150.00Customer Credit $80.00",
        "$100.00",
        "Reversed 22/10/2026",
      ],
    ]);
    // Paid for shows one kind per line, as on the Payments list.
    const paidFor = table.querySelectorAll("tbody tr")[0]?.children[6];
    expect(
      [...(paidFor?.querySelectorAll(".rp-line") ?? [])].map(
        (line) => line.textContent,
      ),
    ).toEqual(["Rent $600.00", "Services $50.00", "Deposits $150.00"]);
    expect(footRow(table)).toEqual([
      "Total",
      "",
      "",
      "",
      "",
      "$1,244.83",
      "",
      "$100.00",
      "",
    ]);
    expect(
      within(table).getByRole("link", { name: "RCPT-0002" }),
    ).toHaveAttribute("href", hashForPage("payments", "receipt:pay-2"));
    expect(
      within(table).getByRole("link", { name: "Keo Mony" }),
    ).toHaveAttribute("href", hashForPage("customers", "cust-3"));
  });

  it("TEST-FE-1045 a register reads 200 rows at a time for the chosen floor; the footer adds up every row of the filter; Show more reads the next rows and says when they could not be read", async () => {
    const first = { ...INVOICES, rows: INVOICES.rows.slice(0, 2) };
    const next = { ...INVOICES, rows: INVOICES.rows.slice(2, 3), offset: 2 };
    const shortPage = { ...first, row_count: 3 };
    const nextPage = { ...next, row_count: 3 };
    let failOnce = true;
    const register = vi.fn<RegisterCall>((_property, _name, filter) => {
      if (filter?.offset === undefined) return Promise.resolve(shortPage);
      if (failOnce) {
        failOnce = false;
        return Promise.reject(new Error("offline"));
      }
      return Promise.resolve(nextPage);
    });
    const page = openReports({ hash: "#/reports/invoice_register", register });
    await screen.findByRole("table", { name: "Invoice register and balances" });
    const scope = screen.getByRole("combobox", { name: "Scope" });
    await waitFor(() => {
      expect(
        within(scope)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Whole Property", "Floor 1", "Floor 2"]);
    });
    fireEvent.change(scope, { target: { value: "2" } });
    await waitFor(() => {
      expect(page.register).toHaveBeenLastCalledWith(
        PROPERTY,
        "invoice_register",
        { floor: "2", limit: 200 },
      );
    });
    const table = await screen.findByRole("table", {
      name: "Invoice register and balances",
    });
    expect(screen.getByText("Showing 2 of 3 rows")).toBeTruthy();
    expect(bodyRows(table)).toHaveLength(2);
    expect(footRow(table)[6]).toBe("$1,300.00");

    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(
      await screen.findByText(
        "More rows could not be read just now. Try again.",
      ),
    ).toBeTruthy();
    expect(page.register).toHaveBeenLastCalledWith(
      PROPERTY,
      "invoice_register",
      { floor: "2", offset: 2, limit: 200 },
    );
    expect(bodyRows(table)).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await screen.findByText("3 rows");
    expect(
      bodyRows(
        screen.getByRole("table", { name: "Invoice register and balances" }),
      ).map((row) => row[0]),
    ).toEqual(["INV-0001", "INV-0002", "INV-0003"]);
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
    expect(
      screen.queryByText("More rows could not be read just now. Try again."),
    ).toBeNull();
  });

  it("TEST-FE-1046 Utility consumption: one line for each Parking and reading period with kWh and m³ side by side, estimates and amounts not billed yet marked; the Summary splits by kind with the Utility Rates; without the money right there are no amounts and no Rates", async () => {
    openReports({ hash: "#/reports/utility_consumption" });
    const table = await screen.findByRole("table", {
      name: "Utility consumption",
    });
    expect(headRow(table)).toEqual([
      "Parking",
      "Period",
      "kWh",
      "Electricity",
      "m³",
      "Water",
    ]);
    expect(bodyRows(table)).toEqual([
      ["U101", "25/08/2026 – 24/09/2026", "180", "$45.00", "4.5", "$4.50"],
      [
        "U203",
        "25/09/2026 – 24/10/2026",
        "1,210.5Estimate",
        "$302.63Not billed yet",
        NONE,
        NONE,
      ],
    ]);
    expect(footRow(table)).toEqual([
      "Total",
      "",
      "1,390.5",
      "$347.63",
      "4.5",
      "$4.50",
    ]);
    expect(screen.getByText("2 rows")).toBeTruthy();
    const summary = summaryCard();
    expect(facts(summary)).toEqual([
      ["Reading periods", "3"],
      ["Estimates", "1"],
    ]);
    const kinds = within(summary).getByRole("table", { name: "By kind" });
    expect(headRow(kinds)).toEqual(["", "Used", "Amount"]);
    expect(bodyRows(kinds)).toEqual([
      ["Electricity", "1,390.5 kWh", "$347.63"],
      ["Water", "4.5 m³", "$4.50"],
    ]);
    expect(
      bodyRows(within(summary).getByRole("table", { name: "Utility Rates" })),
    ).toEqual([
      ["Water", "$1.00 / m³", "01/06/2026"],
      ["Electricity", "$0.25 / kWh", "01/01/2026"],
    ]);
    expect(
      within(summary).getByRole("table", { name: "Electricity used (kWh)" }),
    ).toBeTruthy();
    expect(
      within(summary).getByRole("table", { name: "Water used (m³)" }),
    ).toBeTruthy();
    expect(
      within(summary).getByRole("button", {
        name: "October 2026, 1,210.5 kWh",
      }),
    ).toBeTruthy();
    cleanup();

    openReports({
      hash: "#/reports/utility_consumption",
      capabilities: STAFF,
      register: () => Promise.resolve(UTILITY_NO_MONEY),
    });
    const plain = await screen.findByRole("table", {
      name: "Utility consumption",
    });
    expect(headRow(plain)).toEqual(["Parking", "Period", "kWh", "m³"]);
    expect(bodyRows(plain)).toEqual([
      ["U101", "25/08/2026 – 24/09/2026", "180", "4.5"],
      ["U203", "25/09/2026 – 24/10/2026", "1,210.5Estimate", NONE],
    ]);
    expect(footRow(plain)).toEqual(["Total", "", "1,390.5", "4.5"]);
    expect(
      headRow(within(summaryCard()).getByRole("table", { name: "By kind" })),
    ).toEqual(["", "Used"]);
    expect(screen.queryByRole("table", { name: "Utility Rates" })).toBeNull();
  });

  it("TEST-FE-1047 Deposit liability shows today: no period and no dates sent even after a period was chosen; held by kind; each deposit links its Lease or Reservation with its state; the footer adds up received, applied, kept, refunded and held", async () => {
    const page = openReports({ hash: "#/reports/invoice_register" });
    await screen.findByRole("table", { name: "Invoice register and balances" });
    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    await waitFor(() => {
      expect(page.register).toHaveBeenLastCalledWith(
        PROPERTY,
        "invoice_register",
        { from: "2026-10-01", to: "2026-10-28", limit: 200 },
      );
    });

    act(() => {
      openPageInAddress("reports", false, "deposits");
    });
    const table = await screen.findByRole("table", {
      name: "Deposit liability and disposition",
    });
    expect(page.register).toHaveBeenLastCalledWith(PROPERTY, "deposits", {
      limit: 200,
    });
    expect(screen.queryByRole("group", { name: "Period" })).toBeNull();
    expect(
      screen.getByText(
        "As of 28/10/2026. This report shows today, so the period does not apply.",
      ),
    ).toBeTruthy();
    const summary = summaryCard();
    expect(facts(summary)).toEqual([
      ["Held now", "$600.00"],
      ["Deposits", "3"],
    ]);
    expect(
      bodyRows(within(summary).getByRole("table", { name: "By kind" })),
    ).toEqual([
      ["Security Deposit", "$500.00"],
      ["Pet Deposit", "$100.00"],
    ]);
    expect(barRows(summary, "Deposit money by outcome")).toEqual([
      ["Received", "$1,000.00"],
      ["Applied", "$200.00"],
      ["Kept", "$50.00"],
      ["Refunded", "$150.00"],
      ["Held", "$600.00"],
    ]);
    expect(bodyRows(table)).toEqual([
      [
        "U203",
        "Sok Dara",
        "Security Deposit",
        "LeaseSigned",
        "$500.00",
        "$500.00",
        "$0.00",
        "$0.00",
        "$0.00",
        "$500.00",
      ],
      [
        "U101",
        "Chan Sophea",
        "Pet Deposit",
        "ReservationActive",
        "$100.00",
        "$100.00",
        "$0.00",
        "$0.00",
        "$0.00",
        "$100.00",
      ],
      [
        "U204",
        "Keo Mony",
        "Security Deposit",
        "LeaseFinal Settlement closed",
        "$400.00",
        "$400.00",
        "$200.00",
        "$50.00",
        "$150.00",
        "$0.00",
      ],
    ]);
    expect(footRow(table)).toEqual([
      "Total",
      "",
      "",
      "",
      "",
      "$1,000.00",
      "$200.00",
      "$50.00",
      "$150.00",
      "$600.00",
    ]);
    expect(
      within(table).getAllByRole("link", { name: "Lease" })[0],
    ).toHaveAttribute("href", hashForPage("leases", "lease-1"));
    expect(
      within(table).getByRole("link", { name: "Reservation" }),
    ).toHaveAttribute("href", hashForPage("reservations", "res-1"));

    // Back on a register with a period, This month is still chosen.
    act(() => {
      openPageInAddress("reports", false, "invoice_register");
    });
    await screen.findByRole("table", { name: "Invoice register and balances" });
    expect(page.register).toHaveBeenLastCalledWith(
      PROPERTY,
      "invoice_register",
      { from: "2026-10-01", to: "2026-10-28", limit: 200 },
    );
  });

  it("TEST-FE-1048 Parking occupancy lists every Parking with its Parking Type, status, Customer, Lease or Reservation, Monthly Rent and Until, counts the Parking by status, and has no Monthly Rent without the money right", async () => {
    openReports({ hash: "#/reports/unit_occupancy" });
    const table = await screen.findByRole("table", {
      name: "Parking occupancy",
    });
    expect(headRow(table)).toEqual([
      "Parking",
      "Parking Type",
      "Status",
      "Customer",
      "Lease",
      "Monthly Rent",
      "Until",
    ]);
    // The Unit Type names come from the Settings list.
    await waitFor(() => {
      expect(bodyRows(table)[0]?.[1]).toBe("Studio");
    });
    expect(bodyRows(table)).toEqual([
      [
        "U101",
        "Studio",
        "Occupied",
        "Sok Dara",
        "Lease",
        "$450.00",
        "31/03/2027",
      ],
      [
        "U203",
        "Studio",
        "Reserved",
        "Chan Sophea",
        "Reservation",
        "$500.00",
        "15/11/2026",
      ],
      ["U204", "ONE_BED", "Vacant", NONE, NONE, "$400.00", NONE],
      ["U302", "Studio", "Under maintenance", NONE, NONE, NONE, NONE],
    ]);
    expect(footRow(table)).toEqual(["Total", "4 Parking", "", "", "", "", ""]);
    const summary = summaryCard();
    expect(facts(summary)).toEqual([
      ["Parking", "4"],
      ["Occupied", "1"],
      ["Reserved", "1"],
      ["Vacant", "1"],
      ["Not available", "1"],
    ]);
    expect(barRows(summary, "Parking by status")).toEqual([
      ["Occupied", "1"],
      ["Reserved", "1"],
      ["Vacant", "1"],
      ["Not available", "1"],
    ]);
    expect(within(table).getByRole("link", { name: "U302" })).toHaveAttribute(
      "href",
      hashForPage("units", "unit-302"),
    );
    expect(within(table).getByRole("link", { name: "Lease" })).toHaveAttribute(
      "href",
      hashForPage("leases", "lease-1"),
    );
    expect(
      within(table).getByRole("link", { name: "Reservation" }),
    ).toHaveAttribute("href", hashForPage("reservations", "res-1"));
    cleanup();

    openReports({
      hash: "#/reports/unit_occupancy",
      capabilities: STAFF,
      register: () =>
        Promise.resolve({
          ...OCCUPANCY,
          rows: OCCUPANCY.rows.map((row) => {
            const copy = { ...row };
            delete copy.monthly_rent_usd_cents;
            return copy;
          }),
        }),
    });
    const plain = await screen.findByRole("table", {
      name: "Parking occupancy",
    });
    expect(headRow(plain)).toEqual([
      "Parking",
      "Parking Type",
      "Status",
      "Customer",
      "Lease",
      "Until",
    ]);
    expect(footRow(plain)).toEqual(["Total", "4 Parking", "", "", "", ""]);
  });

  it("TEST-FE-1049 Lease dates: each Lease is named by its Parking and opens the Lease; a Lease ending within 60 days shows the days left, an early end and a drafted renewal are shown; the Summary counts current, ending, no renewal and terminated", async () => {
    openReports({ hash: "#/reports/lease_dates" });
    const table = await screen.findByRole("table", { name: "Lease dates" });
    expect(headRow(table)).toEqual([
      "Parking",
      "Customer",
      "Start Date",
      "End Date",
      "Monthly Rent",
      "Renewal",
      "Status",
    ]);
    expect(bodyRows(table)).toEqual([
      [
        "U204",
        "Keo Mony",
        "01/11/2025",
        "15/08/2026Ended early",
        "$400.00",
        NONE,
        "Terminated",
      ],
      [
        "U101",
        "Sok Dara",
        "01/12/2025",
        "30/11/2026in 33 days",
        "$450.00",
        NONE,
        "Signed",
      ],
      [
        "U203",
        "Chan Sophea",
        "01/01/2026",
        "20/12/2026in 53 days",
        "$500.00",
        "Drafted",
        "Signed",
      ],
      [
        "U302",
        "Mao Vanna",
        "01/07/2026",
        "30/06/2027",
        "$450.00",
        NONE,
        "Signed",
      ],
    ]);
    expect(footRow(table)).toEqual(["Total", "4 Leases", "", "", "", "", ""]);
    expect(within(table).getByRole("link", { name: "U101" })).toHaveAttribute(
      "href",
      hashForPage("leases", "lease-1"),
    );
    const summary = summaryCard();
    expect(facts(summary)).toEqual([
      ["Current", "3"],
      ["Ending within 60 days", "2"],
      ["Ending, no renewal drafted", "1"],
      ["Terminated", "1"],
    ]);
    expect(
      within(summary).getByRole("button", { name: "November 2026, 1" }),
    ).toBeTruthy();
  });

  it("TEST-FE-1050 Audit activity counts the whole Property by day, person and action, takes no floor, and links each day and the card to History", async () => {
    const page = openReports({ hash: "#/reports/invoice_register" });
    await screen.findByRole("table", { name: "Invoice register and balances" });
    const scope = screen.getByRole("combobox", { name: "Scope" });
    await waitFor(() => {
      expect(within(scope).getAllByRole("option")).toHaveLength(3);
    });
    fireEvent.change(scope, { target: { value: "1" } });
    await waitFor(() => {
      expect(page.register).toHaveBeenLastCalledWith(
        PROPERTY,
        "invoice_register",
        { floor: "1", limit: 200 },
      );
    });

    act(() => {
      openPageInAddress("reports", false, "audit_activity");
    });
    const table = await screen.findByRole("table", { name: "Audit activity" });
    expect(page.register).toHaveBeenLastCalledWith(PROPERTY, "audit_activity", {
      limit: 200,
    });
    expect(screen.queryByRole("combobox", { name: "Scope" })).toBeNull();
    const summary = summaryCard();
    expect(facts(summary)).toEqual([["Events", "42"]]);
    expect(
      within(summary).getByRole("link", { name: "Open History" }),
    ).toHaveAttribute("href", hashForPage("history"));
    expect(
      bodyRows(within(summary).getByRole("table", { name: "By person" })),
    ).toEqual([
      ["Kompheak", "30"],
      ["System", "12"],
    ]);
    expect(
      bodyRows(within(summary).getByRole("table", { name: "By action" })),
    ).toEqual([
      ["Invoice", "25"],
      ["Payment", "10"],
      ["Parking", "7"],
    ]);
    expect(
      within(summary).getByRole("button", { name: "27/10/2026, 30" }),
    ).toBeTruthy();
    expect(bodyRows(table)).toEqual([
      ["27/10/2026", "30"],
      ["26/10/2026", "12"],
    ]);
    expect(footRow(table)).toEqual(["Total", "42"]);
    expect(
      within(table).getByRole("link", { name: "27/10/2026" }),
    ).toHaveAttribute("href", hashForPage("history"));
  });

  it("TEST-FE-1051 the Customer Credit ledger links each Credit to its Customer, Parking and Receipt and adds up Credit, used, refunded, reversed and left; the Final Settlement register names each by its Parking, opens the Final Settlement and shows open and closed", async () => {
    openReports({ hash: "#/reports/credit_ledger" });
    const credits = await screen.findByRole("table", {
      name: "Customer Credit ledger",
    });
    expect(bodyRows(credits)).toEqual([
      [
        "Sok Dara",
        "U203",
        "RCPT-0003",
        "20/10/2026",
        "$80.00",
        "$30.00",
        "$0.00",
        "$0.00",
        "$50.00",
      ],
      [
        "Chan Sophea",
        "U101",
        "RCPT-0002",
        "10/10/2026",
        "$20.00",
        "$0.00",
        "$10.00",
        "$10.00",
        "$0.00",
      ],
    ]);
    expect(footRow(credits)).toEqual([
      "Total",
      "",
      "",
      "",
      "$100.00",
      "$30.00",
      "$10.00",
      "$10.00",
      "$50.00",
    ]);
    expect(
      within(credits).getByRole("link", { name: "RCPT-0003" }),
    ).toHaveAttribute("href", hashForPage("payments", "receipt:pay-3"));
    expect(
      within(credits).getByRole("link", { name: "Sok Dara" }),
    ).toHaveAttribute("href", hashForPage("customers", "cust-1"));
    let summary = summaryCard();
    expect(facts(summary)).toEqual([
      ["Credits", "2"],
      ["Customer Credit", "$100.00"],
      ["Credit left", "$50.00"],
    ]);
    expect(barRows(summary, "Customer Credit by outcome")).toEqual([
      ["Customer Credit", "$100.00"],
      ["Used", "$30.00"],
      ["Refunded", "$10.00"],
      ["Reversed", "$10.00"],
      ["Left", "$50.00"],
    ]);

    act(() => {
      openPageInAddress("reports", false, "final_settlements");
    });
    const settlements = await screen.findByRole("table", {
      name: "Final Settlement register",
    });
    expect(bodyRows(settlements)).toEqual([
      [
        "U204",
        "Keo Mony",
        "15/08/2026",
        "15/08/2026",
        "30/08/2026",
        "$200.00",
        "$0.00",
        "$50.00",
        "$150.00",
        "$0.00",
        "Closed",
      ],
      [
        "U302",
        "Mao Vanna",
        "25/10/2026",
        NONE,
        NONE,
        "$0.00",
        "$0.00",
        "$0.00",
        "$0.00",
        NONE,
        "Open",
      ],
    ]);
    expect(footRow(settlements)).toEqual([
      "Total",
      "",
      "",
      "",
      "",
      "$200.00",
      "$0.00",
      "$50.00",
      "$150.00",
      "$0.00",
      "",
    ]);
    expect(
      within(settlements).getByRole("link", { name: "U302" }),
    ).toHaveAttribute("href", hashForPage("moveout", "lease-5"));
    summary = summaryCard();
    expect(facts(summary)).toEqual([
      ["Open", "1"],
      ["Closed", "1"],
      ["Refunded", "$150.00"],
      ["Balance still owed", "$0.00"],
    ]);
  });
  it("TEST-FE-1087 while some rows are not shown yet the footer says its Total is for all of them; the Audit chart says when it shows only the last 31 days with events (V1-060 B7)", async () => {
    const first = {
      ...INVOICES,
      rows: INVOICES.rows.slice(0, 2),
      row_count: 3,
    };
    const next = {
      ...INVOICES,
      rows: INVOICES.rows.slice(2, 3),
      offset: 2,
      row_count: 3,
    };
    openReports({
      hash: "#/reports/invoice_register",
      register: (_property, name, filter) =>
        Promise.resolve(
          name === "audit_activity"
            ? {
                ...AUDIT,
                chart: {
                  days: Array.from({ length: 40 }, (_, index) => ({
                    day: `2026-0${String(8 + Math.floor(index / 30))}-${String((index % 30) + 1).padStart(2, "0")}`,
                    count: 1,
                  })),
                },
              }
            : filter?.offset === undefined
              ? first
              : next,
        ),
    });
    const table = await screen.findByRole("table", {
      name: "Invoice register and balances",
    });
    expect(footRow(table)[0]).toBe("Total, all rows");
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await screen.findByText("3 rows");
    expect(
      footRow(
        screen.getByRole("table", { name: "Invoice register and balances" }),
      )[0],
    ).toBe("Total");

    act(() => {
      openPageInAddress("reports", false, "audit_activity");
    });
    await screen.findByRole("table", { name: "Audit activity" });
    expect(
      within(summaryCard()).getByText(
        "Events per day, the last 31 days with events",
        { selector: "figcaption" },
      ),
    ).toBeTruthy();
    expect(within(summaryCard()).getAllByRole("button")).toHaveLength(31);
  });
});
