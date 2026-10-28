// V1-060 B6: a Totals report (DESIGN.md "Crosstab reports", owner 14/10/2026): years down the
// side, newest first and only the years with records; January to December across and a Total
// for each year; "—" for a month with no record. Electricity and Water show the amount with the
// kWh or m³ under it. The summary gives the total, the highest month and the highest Unit; the
// chart is the money by month beside the Top 5 Units.

import type { TotalsPage, TotalsReport } from "../reportsClient";
import { usdFromCents } from "../shell/format";
import type { Language } from "../signInText";
import { BarList, type ChartColumn, StackedBars } from "./charts";
import { type Fact, ReportTable, SummaryCard, type TableFrame } from "./parts";
import { axisUsd, decimalText, measureText } from "./reportsData";
import {
  monthHead,
  monthName,
  monthShort,
  type ReportsTextKey,
  rpt,
} from "./text";

// The parts of each chart as the server names them; a part not listed folds into Other.
const PARTS: Record<
  TotalsReport,
  readonly (readonly [string, ReportsTextKey])[]
> = {
  total_income: [
    ["rent", "s_rent"],
    ["utilities", "s_utilities"],
    ["move_out_and_damage", "s_move_out_and_damage"],
    ["other", "s_other_income"],
  ],
  total_payment: [
    ["paid_to_invoices", "s_paid_to_invoices"],
    ["deposits", "s_deposits"],
    ["other", "s_other_payment"],
  ],
  total_electricity: [
    ["reading", "s_reading"],
    ["estimate", "s_estimate"],
  ],
  total_water: [
    ["reading", "s_reading"],
    ["estimate", "s_estimate"],
  ],
};

function chartOf(
  language: Language,
  report: TotalsReport,
  months: TotalsPage["chart"]["months"],
): { series: string[]; columns: ChartColumn[] } {
  const known = PARTS[report];
  const names = known.map(([, key]) => rpt(language, key));
  let other = known.findIndex(([key]) => key === "other");
  const listed = new Set(known.map(([key]) => key));
  const columns = months.map((entry) => {
    const values = known.map(([key]) => entry.parts[key] ?? 0);
    const rest = Object.entries(entry.parts)
      .filter(([key]) => !listed.has(key))
      .reduce((sum, [, amount]) => sum + amount, 0);
    if (rest !== 0) {
      if (other < 0) {
        names.push(rpt(language, "s_other"));
        other = names.length - 1;
      }
      values[other] = (values[other] ?? 0) + rest;
    }
    return {
      label: monthShort(language, entry.month),
      tip: monthName(language, entry.month),
      values,
    };
  });
  return { series: names, columns };
}

const MONTHS = Array.from({ length: 12 }, (_, index) => index);

export function TotalsContent({
  language,
  report,
  page,
  frame,
}: {
  language: Language;
  report: TotalsReport;
  page: TotalsPage;
  frame: TableFrame;
}) {
  const utility = report === "total_electricity" || report === "total_water";
  const measure = measureText(
    page.summary.measurement_unit ?? (report === "total_water" ? "M3" : "KWH"),
  );
  const { summary } = page;
  const facts: Fact[] = [
    [rpt(language, "total"), usdFromCents(summary.total)],
    ...(utility && summary.total_quantity !== undefined
      ? [
          [
            rpt(language, "used"),
            `${decimalText(summary.total_quantity)} ${measure}`,
          ] as const,
        ]
      : []),
    [
      rpt(language, "best_m"),
      summary.highest_month === null
        ? "—"
        : `${monthName(language, summary.highest_month.month)} · ${usdFromCents(summary.highest_month.amount)}`,
    ],
    [
      rpt(language, "best_u"),
      summary.highest_unit === null
        ? "—"
        : `${summary.highest_unit.unit_number ?? "—"} · ${usdFromCents(summary.highest_unit.amount)}`,
    ],
    ...(summary.no_unit_amount === 0
      ? []
      : [
          [
            rpt(language, "no_unit"),
            usdFromCents(summary.no_unit_amount),
          ] as const,
        ]),
  ];
  const chart = chartOf(language, report, page.chart.months);
  const years = [...page.years].sort((left, right) => right.year - left.year);

  const cell = (
    amount: number | null,
    quantity: string | null | undefined,
    estimate: boolean,
    key: string,
    total = false,
  ) =>
    amount === null ? (
      <td className="r ui-muted" key={key}>
        —
      </td>
    ) : (
      <td className={total ? "r ui-num tot" : "r ui-num"} key={key}>
        {usdFromCents(amount)}
        {utility && quantity !== undefined && quantity !== null && (
          <span className="ui-sub2">
            {decimalText(quantity)} {measure}
            {estimate && ` · ${rpt(language, "estimate")}`}
          </span>
        )}
      </td>
    );

  return (
    <>
      <SummaryCard
        chart={
          <div className="rp-pair">
            <StackedBars
              axisFormat={axisUsd}
              columns={chart.columns}
              format={usdFromCents}
              head={rpt(language, "month")}
              series={chart.series}
              title={rpt(language, `ch_${report}`)}
              totalLabel={rpt(language, "total")}
            />
            <BarList
              format={usdFromCents}
              rows={page.chart.top_units.slice(0, 5).map((unit) => ({
                label: unit.unit_number ?? unit.unit_id.slice(0, 8),
                value: unit.amount,
              }))}
              title={rpt(language, "top5")}
            />
          </div>
        }
        facts={facts}
        language={language}
        side={
          <p className="ui-small ui-muted">{rpt(language, `note_${report}`)}</p>
        }
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "year") },
          ...MONTHS.map((month) => ({
            label: monthHead(language, month),
            right: true,
          })),
          { label: rpt(language, "total"), right: true },
        ]}
        footer={null}
        grid
      >
        {years.map((year) => (
          <tr key={year.year}>
            <th className="ui-num" scope="row">
              {year.year}
            </th>
            {MONTHS.map((month) =>
              cell(
                year.months[month] ?? null,
                year.quantities?.[month],
                year.estimate_months?.[month] === true,
                String(month),
              ),
            )}
            {cell(year.total, year.total_quantity, false, "total", true)}
          </tr>
        ))}
      </ReportTable>
    </>
  );
}
