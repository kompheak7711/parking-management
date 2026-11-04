// DL-131: Problem reports › Monthly report (mock-up round 29 "Monthly report" and round 32 A7).
// One month in the Property's time zone: reports received (joined ones not counted again), on
// time, done, open, opened again, who pays, by type and place, repeat problems, late now, and
// the repair cost by Unit and by type. Dollars and riel are kept apart; nothing is converted.
// Needs "Plan repairs" (problem_reports.plan); the server checks it again.

import { useCallback, useEffect, useRef, useState } from "react";

import { todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import type { Language } from "../signInText";
import { monthText } from "../utilities/text";
import { typeIcon } from "./ProblemReportsPage";
import {
  type CostRow,
  type ProblemMonth,
  type ProblemsApi,
  ProblemsError,
} from "./problemsClient";
import { costText } from "./RepairCost";
import { pt } from "./text";

/** The last 12 months, newest first, as "yyyy-mm". */
export function lastMonths(today: string): string[] {
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  return Array.from({ length: 12 }, (_, index) => {
    const at = year * 12 + (month - 1) - index;
    return `${String(Math.floor(at / 12))}-${String((at % 12) + 1).padStart(2, "0")}`;
  });
}

function money(row: CostRow, part: "parts" | "outside" | "total"): string {
  const usd =
    part === "parts"
      ? row.parts_usd_cents
      : part === "outside"
        ? row.outside_usd_cents
        : row.parts_usd_cents + row.outside_usd_cents;
  const khr =
    part === "parts"
      ? row.parts_khr
      : part === "outside"
        ? row.outside_khr
        : row.parts_khr + row.outside_khr;
  const shown = [
    usd > 0 ? usdFromCents(usd) : null,
    khr > 0 ? costText("KHR", khr) : null,
  ].filter(Boolean);
  return shown.length === 0 ? usdFromCents(0) : shown.join(" + ");
}

function name(
  language: Language,
  row: { name_en: string; name_kh: string | null },
): string {
  return language === "km" && row.name_kh !== null ? row.name_kh : row.name_en;
}

export function MonthlyReport({
  language,
  propertyId,
  api,
  now,
}: {
  language: Language;
  propertyId: string;
  api: ProblemsApi;
  now?: Date;
}) {
  const today = todayInPhnomPenh(now ?? new Date());
  const months = lastMonths(today);
  const [month, setMonth] = useState(months[0] ?? today.slice(0, 7));
  const [data, setData] = useState<ProblemMonth | null>(null);
  const [problem, setProblem] = useState<"failed" | "right" | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setProblem(null);
    setData(null);
    void api
      .month(propertyId, month)
      .then((found) => {
        if (operation === sequence.current) setData(found);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(
          error instanceof ProblemsError && error.status === 403
            ? "right"
            : "failed",
        );
      });
  }, [api, month, propertyId]);

  useEffect(() => {
    load();
  }, [load]);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("problems");
      }}
      type="button"
    >
      <Icon name="back" small />
      {pt(language, "back")}
    </button>
  );

  const costTable = (
    id: string,
    title: string,
    rows: { key: string; label: string; row: CostRow }[],
  ) => (
    <section aria-labelledby={id} className="ui-card">
      <h2 id={id}>{title}</h2>
      {rows.length === 0 ? (
        <p className="ui-muted">{pt(language, "m_no_cost")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{pt(language, "m_where")}</th>
                <th className="num" scope="col">
                  {pt(language, "m_reports")}
                </th>
                <th className="num" scope="col">
                  {pt(language, "kind_PARTS")}
                </th>
                <th className="num" scope="col">
                  {pt(language, "kind_OUTSIDE_WORKER")}
                </th>
                <th className="num" scope="col">
                  {pt(language, "cost_total")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ key, label, row }) => (
                <tr key={key}>
                  <th scope="row">{label}</th>
                  <td className="num ui-num">{row.reports}</td>
                  <td className="num ui-num">{money(row, "parts")}</td>
                  <td className="num ui-num">{money(row, "outside")}</td>
                  <td className="num ui-num">{money(row, "total")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <h2>{pt(language, "m_title")}</h2>
          <p>{pt(language, "m_sub")}</p>
        </div>
        <div className="ui-field">
          <label htmlFor="pm-month">{pt(language, "m_month")}</label>
          <select
            className="ui-sel"
            id="pm-month"
            onChange={(event) => {
              setMonth(event.currentTarget.value);
            }}
            value={month}
          >
            {months.map((value) => (
              <option key={value} value={value}>
                {monthText(language, `${value}-01`)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {problem !== null && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{pt(language, problem === "right" ? "m_right" : "failed")}</p>
          {problem === "failed" && (
            <button className="ui-btn" onClick={load} type="button">
              {pt(language, "retry")}
            </button>
          )}
        </div>
      )}
      {data === null && problem === null && (
        <p className="ui-muted" role="status">
          {pt(language, "loading")}
        </p>
      )}
      {data !== null && (
        <>
          <dl className="ui-kpis">
            <div className="ui-kpi">
              <dt className="ui-kpi-label">{pt(language, "m_received")}</dt>
              <dd className="ui-kpi-value ui-num">{data.received}</dd>
              <dd className="ui-kpi-note">
                {pt(
                  language,
                  "m_received_s",
                  data.unit_problems,
                  data.building_problems,
                )}
                {data.joined > 0 &&
                  ` · ${pt(language, "m_joined", data.joined)}`}
              </dd>
            </div>
            <div className="ui-kpi">
              <dt className="ui-kpi-label">{pt(language, "m_done")}</dt>
              <dd className="ui-kpi-value ui-num">{data.done}</dd>
              <dd className="ui-kpi-note">
                {data.average_days_to_fix === null
                  ? "—"
                  : pt(language, "m_days", data.average_days_to_fix)}
              </dd>
            </div>
            <div className="ui-kpi">
              <dt className="ui-kpi-label">{pt(language, "m_open")}</dt>
              <dd className="ui-kpi-value ui-num">{data.still_open}</dd>
              <dd className="ui-kpi-note">
                {pt(language, "m_open_s", data.opened_again, data.not_accepted)}
              </dd>
            </div>
            <div className="ui-kpi">
              <dt className="ui-kpi-label">{pt(language, "m_on_time")}</dt>
              <dd className="ui-kpi-value ui-num">
                {data.urgent_on_time} / {data.urgent}
              </dd>
              <dd className="ui-kpi-note">
                {pt(language, "m_on_time_s", data.normal_on_time, data.normal)}
              </dd>
            </div>
          </dl>
          <p>
            {pt(
              language,
              "m_pays",
              data.owner_pays,
              data.tenant_pays,
              usdFromCents(data.damage_usd_cents),
            )}
          </p>
          <div className="ui-split">
            <div className="ui-stack">
              {costTable(
                "pm-cost-unit",
                pt(language, "m_cost_unit"),
                data.cost_by_unit.map((row) => ({
                  key: row.unit_number ?? "building",
                  label: row.unit_number ?? pt(language, "m_building"),
                  row,
                })),
              )}
              {costTable(
                "pm-cost-type",
                pt(language, "m_cost_type"),
                data.cost_by_type.map((row) => ({
                  key: row.code,
                  label: name(language, row),
                  row,
                })),
              )}
              <section aria-labelledby="pm-repeat" className="ui-card">
                <h2 id="pm-repeat">{pt(language, "m_repeats")}</h2>
                {data.repeats.length === 0 ? (
                  <p className="ui-muted">{pt(language, "m_none")}</p>
                ) : (
                  <ul className="ui-plain">
                    {data.repeats.map((row) => (
                      <li key={`${row.unit_number}-${row.code}`}>
                        <Icon name={typeIcon(row)} small /> {row.unit_number} ·{" "}
                        {name(language, row)} ·{" "}
                        {pt(language, "m_times", row.reports)}{" "}
                        {row.found.map((found, index) => (
                          <span key={found.report_id}>
                            {index > 0 && ", "}
                            <a
                              className="ui-num"
                              href={hashForPage(
                                "problems",
                                `pr:${found.report_id}`,
                              )}
                            >
                              {found.report_number}
                            </a>
                          </span>
                        ))}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
            <div className="ui-stack">
              <section aria-labelledby="pm-type" className="ui-card">
                <h2 id="pm-type">{pt(language, "m_by_type")}</h2>
                {data.by_type.length === 0 ? (
                  <p className="ui-muted">{pt(language, "m_none")}</p>
                ) : (
                  <ul className="ui-plain">
                    {data.by_type.map((row) => (
                      <li key={row.code}>
                        <Icon name={typeIcon(row)} small />{" "}
                        {name(language, row)}{" "}
                        <b className="ui-num">{row.reports}</b>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section aria-labelledby="pm-place" className="ui-card">
                <h2 id="pm-place">{pt(language, "m_by_place")}</h2>
                {data.by_place.length === 0 ? (
                  <p className="ui-muted">{pt(language, "m_none")}</p>
                ) : (
                  <ul className="ui-plain">
                    {data.by_place.map((row) => (
                      <li
                        key={`${row.kind}-${row.unit_number ?? row.place_code ?? ""}`}
                      >
                        {row.unit_number ??
                          (language === "km" ? row.place_kh : null) ??
                          row.place_en ??
                          pt(language, "m_building")}{" "}
                        <b className="ui-num">{row.reports}</b>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section aria-labelledby="pm-late" className="ui-card">
                <h2 id="pm-late">{pt(language, "m_late")}</h2>
                {data.late_now.length === 0 ? (
                  <p className="ui-muted">{pt(language, "m_none")}</p>
                ) : (
                  <ul className="ui-plain">
                    {data.late_now.map((row) => (
                      <li key={row.report_id}>
                        <a
                          className="ui-num"
                          href={hashForPage("problems", `pr:${row.report_id}`)}
                        >
                          {row.report_number}
                        </a>{" "}
                        ·{" "}
                        {pt(
                          language,
                          row.late === "URGENT" ? "late_u" : "late_n",
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </>
  );
}
