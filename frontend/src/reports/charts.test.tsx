import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { usdFromCents } from "../shell/format";
import { BarList, niceMax, StackedBars } from "./charts";
import {
  axisUsd,
  decimalText,
  floorName,
  generatedText,
  mayExport,
  mayRead,
  measureText,
  numberText,
  rangeOf,
  rangeText,
  reportDef,
  rielText,
} from "./reportsData";
import { barRows, bodyRows, NOW } from "./reportsTestData";

afterEach(() => {
  cleanup();
});

function texts(selector: string): string[] {
  return [...document.querySelectorAll(selector)].map(
    (element) => element.textContent,
  );
}

describe("Report charts and helpers", () => {
  it("TEST-FE-1057 the month chart: a round axis top, one column for each month stacked in the fixed series order with a legend, a tooltip with each part and the total, a label on the highest column only, no bar for a part below zero, about eight month labels on a long run, and a hidden table for screen readers", () => {
    expect([0, 1, 1.5, 2.2, 3, 7, 98000, 125000].map(niceMax)).toEqual([
      1, 1, 2, 2.5, 5, 10, 100000, 200000,
    ]);

    render(
      <StackedBars
        axisFormat={axisUsd}
        columns={[
          {
            label: "Sep 26",
            tip: "September 2026",
            values: [30000, 10000, -5000],
          },
          { label: "Oct 26", tip: "October 2026", values: [60000, 20000, 0] },
        ]}
        format={usdFromCents}
        head="Month"
        series={["Paid", "Deposits", "Other"]}
        title="Money by month"
        totalLabel="Total"
      />,
    );
    const columns = screen.getAllByRole("button");
    expect(columns.map((column) => column.getAttribute("aria-label"))).toEqual([
      "September 2026, Paid: $300.00, Deposits: $100.00, Other: -$50.00, Total: $350.00",
      "October 2026, Paid: $600.00, Deposits: $200.00, Total: $800.00",
    ]);
    expect(columns[1]?.getAttribute("data-tip")).toBe(
      "October 2026\nPaid: $600.00\nDeposits: $200.00\nTotal: $800.00",
    );
    // The part below zero is in the tooltip, not drawn.
    expect(
      [...(columns[0]?.querySelectorAll(".rp-vc-seg") ?? [])].map(
        (part) => part.className,
      ),
    ).toEqual(["rp-vc-seg rp-s1", "rp-vc-seg rp-s2"]);
    // The axis top is $1,000, so the October column is 80% high.
    expect(texts(".rp-vc-y span")).toEqual(["$1,000", "$500", "$0"]);
    expect(
      Number.parseFloat(
        columns[1]?.querySelector<HTMLElement>(".rp-vc-bar")?.style.height ??
          "",
      ),
    ).toBe(80);
    expect(texts(".rp-vc-v")).toEqual(["$800.00"]);
    expect(texts(".rp-legend li")).toEqual(["Paid", "Deposits", "Other"]);
    expect(texts(".rp-vc-x span")).toEqual(["Sep 26", "Oct 26"]);
    expect(
      bodyRows(screen.getByRole("table", { name: "Money by month" })),
    ).toEqual([
      ["September 2026", "$300.00", "$100.00", "-$50.00"],
      ["October 2026", "$600.00", "$200.00", "$0.00"],
    ]);
    cleanup();

    // One series: no legend and no Total line; two years of months show eight labels.
    render(
      <StackedBars
        color={2}
        columns={Array.from({ length: 24 }, (_, index) => ({
          label: `M${String(index + 1)}`,
          tip: `Month ${String(index + 1)}`,
          values: [index === 5 ? 0 : 10],
        }))}
        format={numberText}
        head="Month"
        series={["Leases"]}
        title="Leases ending by month"
        totalLabel="Total"
      />,
    );
    expect(document.querySelector(".rp-legend")).toBeNull();
    expect(screen.getByRole("button", { name: "Month 1, 10" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Month 6, 0" })).toBeTruthy();
    expect(document.querySelector(".rp-vc-seg")).toHaveClass("rp-s2");
    expect(texts(".rp-vc-x span").filter((label) => label !== "")).toEqual([
      "M1",
      "M4",
      "M7",
      "M10",
      "M13",
      "M16",
      "M19",
      "M22",
    ]);
    // Several months share the highest value: the first of them is labelled.
    expect(texts(".rp-vc-v")).toEqual(["10"]);
    cleanup();

    const { container } = render(
      <StackedBars
        columns={[]}
        format={numberText}
        head="Month"
        series={["Leases"]}
        title="Nothing"
        totalLabel="Total"
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("TEST-FE-1058 the bar list writes each value at the end of its bar; the report helpers: who may read and export, This month and Last month across a year end and in a leap year, picked dates, decimals grouped without rounding, riel, axis dollars, the Generated time in Phnom Penh, floors and measures", () => {
    render(
      <BarList
        format={usdFromCents}
        rows={[
          { label: "U203", value: 250000 },
          { label: "U101", value: 125000 },
          { label: "No Unit", value: -100 },
        ]}
        title="Top 5 Units"
      />,
    );
    expect(barRows(document.body, "Top 5 Units")).toEqual([
      ["U203", "$2,500.00"],
      ["U101", "$1,250.00"],
      ["No Unit", "-$1.00"],
    ]);
    expect(
      [...document.querySelectorAll<HTMLElement>(".rp-hc-b i")].map((bar) =>
        Number.parseFloat(bar.style.width),
      ),
    ).toEqual([100, 50, 0]);
    cleanup();
    const { container } = render(
      <BarList format={usdFromCents} rows={[]} title="Nothing" />,
    );
    expect(container.innerHTML).toBe("");

    const income = reportDef("total_income");
    const occupancy = reportDef("unit_occupancy");
    if (income === null || occupancy === null) throw new Error("no report");
    expect(reportDef("something_else")).toBeNull();
    expect(mayRead(income, null)).toBe(true);
    expect(mayRead(income, new Set(["payments.read"]))).toBe(false);
    expect(mayRead(occupancy, new Set(["units.read", "leases.read"]))).toBe(
      false,
    );
    expect(
      mayRead(
        occupancy,
        new Set(["units.read", "leases.read", "reservations.read"]),
      ),
    ).toBe(true);
    expect(mayExport(income, null)).toBe(true);
    expect(mayExport(income, new Set(["reports.read"]))).toBe(false);
    expect(mayExport(income, new Set(["data.export"]))).toBe(false);
    expect(mayExport(income, new Set(["reports.read", "data.export"]))).toBe(
      true,
    );

    const all = { period: "all", from: "", to: "" } as const;
    expect(rangeOf(all, "2026-10-28")).toBeNull();
    expect(rangeOf({ ...all, period: "month" }, "2026-01-15")).toEqual([
      "2026-01-01",
      "2026-01-15",
    ]);
    expect(rangeOf({ ...all, period: "last" }, "2026-01-15")).toEqual([
      "2025-12-01",
      "2025-12-31",
    ]);
    expect(rangeOf({ ...all, period: "last" }, "2028-03-10")).toEqual([
      "2028-02-01",
      "2028-02-29",
    ]);
    expect(
      rangeOf(
        { period: "pick", from: "2026-09-05", to: "2026-10-20" },
        "2026-10-28",
      ),
    ).toEqual(["2026-09-05", "2026-10-20"]);
    expect(
      rangeOf({ period: "pick", from: "2026-09-05", to: "" }, "2026-10-28"),
    ).toBeNull();
    expect(rangeText("en", ["2026-09-05", "2026-10-20"])).toBe(
      "05/09/2026 to 20/10/2026",
    );
    expect(rangeText("km", ["2026-09-05", "2026-10-20"])).toBe(
      "05/09/2026 ដល់ 20/10/2026",
    );
    expect(rangeText("en", null)).toBe("All dates");

    expect(decimalText("1234567.125")).toBe("1,234,567.125");
    expect(decimalText("-1180")).toBe("-1,180");
    expect(decimalText("12.5")).toBe("12.5");
    expect(decimalText("n/a")).toBe("n/a");
    expect(rielText(184263)).toBe("184,263 ៛");
    expect(axisUsd(125000)).toBe("$1,250");
    expect(axisUsd(-5050)).toBe("-$51");
    expect(generatedText(NOW)).toBe("28/10/2026, 10:30");
    expect(generatedText(Date.parse("2026-12-31T17:05:00Z"))).toBe(
      "01/01/2027, 00:05",
    );
    expect(floorName("en", "2")).toBe("Floor 2");
    expect(floorName("km", "2")).toBe("ជាន់ទី 2");
    expect(floorName("en", "Ground")).toBe("Ground");
    expect(measureText("M3")).toBe("m³");
    expect(measureText("kwh")).toBe("kWh");
  });
  it("TEST-FE-1088 the label on the highest column is its total with a reversal taken off, as in its tooltip; the column is as high as what is drawn (V1-060 B7)", () => {
    render(
      <StackedBars
        columns={[
          { label: "Sep 26", tip: "September 2026", values: [550000, -50000] },
          { label: "Oct 26", tip: "October 2026", values: [300000, 0] },
        ]}
        format={usdFromCents}
        head="Month"
        series={["Received", "Reversals"]}
        title="Money received by month"
        totalLabel="Total"
      />,
    );
    const [september] = screen.getAllByRole("button");
    expect(september?.getAttribute("aria-label")).toBe(
      "September 2026, Received: $5,500.00, Reversals: -$500.00, Total: $5,000.00",
    );
    expect(texts(".rp-vc-v")).toEqual(["$5,000.00"]);
    // The axis top is $10,000; the drawn part is $5,500, so the column is 55% high.
    expect(
      Number.parseFloat(
        september?.querySelector<HTMLElement>(".rp-vc-bar")?.style.height ?? "",
      ),
    ).toBe(55);
  });
});
