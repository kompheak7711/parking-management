import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { openPageInAddress } from "../shell/useHashPage";
import {
  barRows,
  bodyRows,
  facts,
  headRow,
  INCOME,
  INCOME_U203,
  openReports,
  PROPERTY,
} from "./reportsTestData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const NONE = "—";

describe("Totals by Unit and month", () => {
  it("TEST-FE-1038 Total Income: years newest first with January to December and a Total, — for a month with no record; the Summary gives the total, the highest month and Unit and the money not tied to a Unit; the chart stacks the parts by month beside the Top 5 Units", async () => {
    const page = openReports({ hash: "#/reports/total_income" });
    const table = await screen.findByRole("table", { name: "Total Income" });
    expect(page.totals).toHaveBeenCalledWith(PROPERTY, "total_income", {});
    expect(headRow(table)).toEqual([
      "Year",
      "Jan",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "Jul",
      "Aug",
      "Sep",
      "Oct",
      "Nov",
      "Dec",
      "Total",
    ]);
    expect(bodyRows(table)).toEqual([
      [
        "2026",
        "$1,000.00",
        "$1,000.00",
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        "$980.00",
        NONE,
        NONE,
        "$2,980.00",
      ],
      [
        "2025",
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        NONE,
        "$900.00",
        "$950.00",
        "$1,850.00",
      ],
    ]);
    expect(within(table).getByRole("rowheader", { name: "2026" })).toBeTruthy();
    // The Year column stays in place when the table scrolls sideways.
    expect(table).toHaveClass("ui-grid");
    // Over the table: the scope of the numbers.
    expect(screen.getByText("All Units", { selector: "span" })).toBeTruthy();

    const summary = screen.getByRole("region", { name: "Summary" });
    expect(facts(summary)).toEqual([
      ["Total", "$4,830.00"],
      ["Highest month", "January 2026 · $1,000.00"],
      ["Highest Unit", "U203 · $2,500.00"],
      ["Not tied to a Unit", "$50.00"],
    ]);
    expect(
      within(summary).getByText(/^Each Invoice counts in the month it is for/),
    ).toBeTruthy();
    const chart = within(summary).getByRole("table", {
      name: "Income by month",
    });
    expect(headRow(chart)).toEqual([
      "Month",
      "Rent and Services",
      "Utilities",
      "Move-out and damage",
      "Late charges and kept Deposits",
    ]);
    // A part the screen does not know is added to the last part.
    expect(bodyRows(chart)[4]).toEqual([
      "October 2026",
      "$800.00",
      "$120.00",
      "$0.00",
      "$60.00",
    ]);
    expect(
      within(summary).getByRole("button", {
        name: "October 2026, Rent and Services: $800.00, Utilities: $120.00, Late charges and kept Deposits: $60.00, Total: $980.00",
      }),
    ).toBeTruthy();
    // Only the highest month carries its amount.
    expect(
      [...summary.querySelectorAll(".rp-vc-v")].map(
        (label) => label.textContent,
      ),
    ).toEqual(["$1,000.00"]);
    expect(barRows(summary, "Top 5 Units")).toEqual([
      ["U203", "$2,500.00"],
      ["U101", "$1,800.00"],
      ["U204", "$480.00"],
    ]);
  });

  it("TEST-FE-1039 the Unit filter asks for one Unit's table and All Units for every Unit added together; the scope shows over the table and stays for the other Totals tables", async () => {
    const page = openReports({
      hash: "#/reports/total_income",
      totals: (_property, report, filter) =>
        Promise.resolve(
          report === "total_income" && filter?.unitId === "unit-203"
            ? INCOME_U203
            : INCOME,
        ),
    });
    await screen.findByRole("table", { name: "Total Income" });
    const unit = screen.getByRole("combobox", { name: "Unit" });
    await waitFor(() => {
      expect(
        within(unit)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["All Units", "U101", "U203", "U204"]);
    });
    expect(unit).toHaveValue("");

    fireEvent.change(unit, { target: { value: "unit-203" } });
    await waitFor(() => {
      expect(page.totals).toHaveBeenLastCalledWith(PROPERTY, "total_income", {
        unitId: "unit-203",
      });
    });
    await screen.findByText("U203", { selector: "span.ui-small" });
    const one = screen.getByRole("table", { name: "Total Income" });
    expect(bodyRows(one).map((row) => [row[0], row.at(-1)])).toEqual([
      ["2026", "$1,480.00"],
      ["2025", "$1,020.00"],
    ]);
    // One Unit has no money that is not tied to a Unit.
    expect(facts(screen.getByRole("region", { name: "Summary" }))).toEqual([
      ["Total", "$2,500.00"],
      ["Highest month", "December 2025 · $520.00"],
      ["Highest Unit", "U203 · $2,500.00"],
    ]);

    act(() => {
      openPageInAddress("reports", false, "total_payment");
    });
    await screen.findByRole("table", { name: "Total Payment" });
    expect(page.totals).toHaveBeenLastCalledWith(PROPERTY, "total_payment", {
      unitId: "unit-203",
    });
    expect(screen.getByRole("combobox", { name: "Unit" })).toHaveValue(
      "unit-203",
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Unit" }), {
      target: { value: "" },
    });
    await waitFor(() => {
      expect(page.totals).toHaveBeenLastCalledWith(
        PROPERTY,
        "total_payment",
        {},
      );
    });
    expect(
      await screen.findByText("All Units", { selector: "span" }),
    ).toBeTruthy();
  });

  it("TEST-FE-1040 the period: This month, Last month and picked dates are sent as days and shown as dd/mm/yyyy; dates that are not whole days or run backwards are refused; All sends no dates", async () => {
    const page = openReports({ hash: "#/reports/total_income" });
    await screen.findByRole("table", { name: "Total Income" });
    const period = screen.getByRole("group", { name: "Period" });
    expect(within(period).getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("All dates")).toBeTruthy();

    fireEvent.click(within(period).getByRole("button", { name: "This month" }));
    await waitFor(() => {
      expect(page.totals).toHaveBeenLastCalledWith(PROPERTY, "total_income", {
        from: "2026-10-01",
        to: "2026-10-28",
      });
    });
    expect(screen.getByText("01/10/2026 to 28/10/2026")).toBeTruthy();
    expect(
      within(period).getByRole("button", { name: "This month" }),
    ).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(within(period).getByRole("button", { name: "Last month" }));
    await waitFor(() => {
      expect(page.totals).toHaveBeenLastCalledWith(PROPERTY, "total_income", {
        from: "2026-09-01",
        to: "2026-09-30",
      });
    });
    expect(screen.getByText("01/09/2026 to 30/09/2026")).toBeTruthy();

    // Pick dates starts from the days on screen, so nothing is read again yet.
    const asked = page.totals.mock.calls.length;
    fireEvent.click(within(period).getByRole("button", { name: "Pick dates" }));
    expect(screen.getByLabelText("From")).toHaveValue("01/09/2026");
    expect(screen.getByLabelText("To")).toHaveValue("30/09/2026");
    expect(page.totals.mock.calls.length).toBe(asked);
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "05/09/2026" },
    });
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "20/10/2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    await waitFor(() => {
      expect(page.totals).toHaveBeenLastCalledWith(PROPERTY, "total_income", {
        from: "2026-09-05",
        to: "2026-10-20",
      });
    });
    expect(screen.getByText("05/09/2026 to 20/10/2026")).toBeTruthy();

    const before = page.totals.mock.calls.length;
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "31/02/2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Write both dates as dd/mm/yyyy, with From on or before To.",
    );
    expect(screen.getByLabelText("From")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "21/10/2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Write both dates as dd/mm/yyyy, with From on or before To.",
    );
    expect(page.totals.mock.calls.length).toBe(before);

    fireEvent.click(within(period).getByRole("button", { name: "All" }));
    await waitFor(() => {
      expect(page.totals).toHaveBeenLastCalledWith(
        PROPERTY,
        "total_income",
        {},
      );
    });
    expect(screen.queryByLabelText("From")).toBeNull();
    expect(screen.getByText("All dates")).toBeTruthy();
  });

  it("TEST-FE-1041 Total Electricity shows the amount with the kWh under it and marks an estimated month; the Summary adds the kWh used and the chart splits readings and estimates; Total Water shows m³", async () => {
    openReports({ hash: "#/reports/total_electricity" });
    const table = await screen.findByRole("table", {
      name: "Total Electricity",
    });
    const [row] = bodyRows(table);
    expect(row?.[0]).toBe("2026");
    expect(row?.[8]).toBe(NONE);
    expect(row?.[9]).toBe("$295.001,180 kWh");
    expect(row?.[10]).toBe("$52.63210.5 kWh · Estimate");
    expect(row?.[13]).toBe("$347.631,390.5 kWh");
    expect(within(table).getByText("210.5 kWh · Estimate")).toHaveClass(
      "ui-sub2",
    );
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(facts(summary)).toEqual([
      ["Total", "$347.63"],
      ["Used", "1,390.5 kWh"],
      ["Highest month", "September 2026 · $295.00"],
      ["Highest Unit", "U101 · $200.00"],
    ]);
    expect(
      headRow(
        within(summary).getByRole("table", {
          name: "Electricity billed by reading month",
        }),
      ),
    ).toEqual(["Month", "From readings", "Estimates"]);
    expect(
      within(summary).getByRole("button", {
        name: "October 2026, Estimates: $52.63, Total: $52.63",
      }),
    ).toBeTruthy();
    cleanup();

    openReports({ hash: "#/reports/total_water" });
    const water = await screen.findByRole("table", { name: "Total Water" });
    expect(bodyRows(water)[0]?.[10]).toBe("$4.504.5 m³");
    expect(facts(screen.getByRole("region", { name: "Summary" }))[1]).toEqual([
      "Used",
      "4.5 m³",
    ]);
  });

  it("TEST-FE-1042 a report page names the report with its line and the Owner and Manager tag, and ends with the Generated line in Phnom Penh time with amounts in USD", async () => {
    openReports({ hash: "#/reports/total_water" });
    await screen.findByRole("table", { name: "Total Water" });
    expect(
      screen.getByRole("heading", { level: 2, name: "Total Water" }),
    ).toBeTruthy();
    expect(
      screen.getByText("Water billed for each Unit, reading period by period"),
    ).toBeTruthy();
    expect(screen.getByText("Owner and Manager")).toBeTruthy();
    expect(
      screen.getByText(
        "Generated 28/10/2026, 10:30 · Phnom Penh time · amounts in USD; riel shown as information only",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Amounts in USD. Riel payments are shown with their riel amount and rate; never added to USD.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "All reports" })).toHaveAttribute(
      "href",
      "#/reports",
    );
  });
});
