// DL-131: Problem reports › Monthly report (mock-up round 29 "Monthly report" and round 32 A7).
// One month in the Property's time zone: reports received (joined ones not counted again), on
// time, done, open, opened again, who pays, by type and place, repeat problems, late now, and
// the repair cost by Unit and by type. Dollars and riel are kept apart; nothing is converted.
// Needs "Plan repairs" (problem_reports.plan); the server checks it again.

import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
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
import type { Tone } from "../shell/ui";
import { PageHead } from "../shell/pageHead";

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

/** One fact card of the month, drawn like the Home cards: name at the left, number at the top
 * right, a short line under them. It is not a button: the report only shows the month. */
function Fact({
  icon,
  tone,
  label,
  value,
  note,
  money = false,
}: {
  icon: ShellIcon;
  tone: Tone | "brand" | "none";
  label: string;
  value: string;
  note?: string;
  money?: boolean;
}) {
  return (
    <div
      className={`ui-kpi ui-kpi-top${money ? " ui-kpi-amount" : ""} ${tone}`}
    >
      <span className="ui-kpi-head">
        <span className="ui-kpi-label">
          <span className="ui-kpi-icon">
            <Icon name={icon} small />
          </span>
          <span>{label}</span>
        </span>
        <span className="ui-kpi-value ui-num">{value}</span>
      </span>
      {note !== undefined && note !== "" && (
        <span className="ui-kpi-note">{note}</span>
      )}
    </div>
  );
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

  const costTable = (
    id: string,
    title: string,
    first: string,
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
                <th scope="col">{first}</th>
                <th className="num r" scope="col">
                  {pt(language, "m_reports")}
                </th>
                <th className="num r" scope="col">
                  {pt(language, "kind_PARTS")}
                </th>
                <th className="num r" scope="col">
                  {pt(language, "kind_OUTSIDE_WORKER")}
                </th>
                <th className="num r" scope="col">
                  {pt(language, "cost_total")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ key, label, row }) => (
                <tr key={key}>
                  <th scope="row">{label}</th>
                  <td className="num r ui-num">{row.reports}</td>
                  <td className="num r ui-num">{money(row, "parts")}</td>
                  <td className="num r ui-num">{money(row, "outside")}</td>
                  <td className="num r ui-num">{money(row, "total")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );

  /* Property screen review (owner 16/11/2026): "Reports by type" and "Reports by place" are
     narrow cards, each a small table whose number column says "Reports", so it is clear the
     number is how many problem reports came in this month. */
  const countTable = (
    id: string,
    title: string,
    first: string,
    rows: { key: string; label: ReactNode; reports: number }[],
  ) => (
    <section aria-labelledby={id} className="ui-card">
      <h2 id={id}>{title}</h2>
      {rows.length === 0 ? (
        <p className="ui-muted">{pt(language, "m_none")}</p>
      ) : (
        <table className="ui-table ui-mcount">
          <thead>
            <tr>
              <th scope="col">{first}</th>
              <th className="num r" scope="col">
                {pt(language, "m_reports")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, label, reports }) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                <td className="num r ui-num">{reports}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );

  return (
    <>
      {/* Property fix 4 (owner 14/11/2026): the tab row is the head; the month box sits at its
          right end, and the Reports tab is the way back. */}
      <h2 className="ui-sr">{pt(language, "m_title")}</h2>
      <PageHead
        actions={
          <div className="ui-headfield">
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
        }
      />
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
          {/* Owner 16/11/2026: the Home card look on every card; the damage charges and who
              pays are the fifth card, not a loose line. */}
          <div className="ui-kpis">
            <Fact
              icon="wrench"
              label={pt(language, "m_received")}
              note={`${pt(
                language,
                "m_received_s",
                data.unit_problems,
                data.building_problems,
              )}${data.joined > 0 ? ` · ${pt(language, "m_joined", data.joined)}` : ""}`}
              tone={data.received > 0 ? "brand" : "none"}
              value={String(data.received)}
            />
            <Fact
              icon="check"
              label={pt(language, "m_done")}
              note={
                data.average_days_to_fix === null
                  ? undefined
                  : pt(language, "m_days", data.average_days_to_fix)
              }
              tone={data.done > 0 ? "ok" : "none"}
              value={String(data.done)}
            />
            <Fact
              icon="clock"
              label={pt(language, "m_open")}
              note={pt(
                language,
                "m_open_s",
                data.opened_again,
                data.not_accepted,
              )}
              tone={data.still_open > 0 ? "warn" : "none"}
              value={String(data.still_open)}
            />
            <Fact
              icon="zap"
              label={pt(language, "m_on_time")}
              note={pt(
                language,
                "m_on_time_s",
                data.normal_on_time,
                data.normal,
              )}
              tone={
                data.urgent === 0
                  ? "none"
                  : data.urgent_on_time < data.urgent
                    ? "err"
                    : "ok"
              }
              value={`${String(data.urgent_on_time)} / ${String(data.urgent)}`}
            />
            <Fact
              icon="payments"
              label={pt(language, "m_damage")}
              money
              note={pt(language, "m_pays", data.owner_pays, data.tenant_pays)}
              tone={data.damage_usd_cents > 0 ? "info" : "none"}
              value={usdFromCents(data.damage_usd_cents)}
            />
          </div>
          <div className="ui-mrow ui-mrow-lists">
            {countTable(
              "pm-type",
              pt(language, "m_by_type"),
              pt(language, "m_type"),
              data.by_type.map((row) => ({
                key: row.code,
                label: (
                  <span className="ui-mname">
                    <Icon name={typeIcon(row)} small />
                    <span>{name(language, row)}</span>
                  </span>
                ),
                reports: row.reports,
              })),
            )}
            {countTable(
              "pm-place",
              pt(language, "m_by_place"),
              pt(language, "m_place"),
              data.by_place.map((row) => ({
                key: `${row.kind}-${row.unit_number ?? row.place_code ?? ""}`,
                label:
                  row.unit_number ??
                  (language === "km" ? row.place_kh : null) ??
                  row.place_en ??
                  pt(language, "m_building"),
                reports: row.reports,
              })),
            )}
            <section aria-labelledby="pm-late" className="ui-card">
              <h2 id="pm-late">{pt(language, "m_late")}</h2>
              {data.late_now.length === 0 ? (
                <p className="ui-muted">{pt(language, "m_none")}</p>
              ) : (
                <table className="ui-table ui-mcount">
                  <thead>
                    <tr>
                      <th scope="col">{pt(language, "m_report")}</th>
                      <th scope="col">{pt(language, "m_late_why")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.late_now.map((row) => (
                      <tr key={row.report_id}>
                        <th scope="row">
                          <a
                            className="ui-num"
                            href={hashForPage(
                              "problems",
                              `pr:${row.report_id}`,
                            )}
                          >
                            {row.report_number}
                          </a>
                        </th>
                        <td className="wrap">
                          {pt(
                            language,
                            row.late === "URGENT" ? "m_late_u" : "m_late_n",
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </div>
          <div className="ui-mrow ui-mrow-cost">
            {costTable(
              "pm-cost-unit",
              pt(language, "m_cost_unit"),
              pt(language, "m_unit"),
              data.cost_by_unit.map((row) => ({
                key: row.unit_number ?? "building",
                label: row.unit_number ?? pt(language, "m_building"),
                row,
              })),
            )}
            {costTable(
              "pm-cost-type",
              pt(language, "m_cost_type"),
              pt(language, "m_type"),
              data.cost_by_type.map((row) => ({
                key: row.code,
                label: name(language, row),
                row,
              })),
            )}
          </div>
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
        </>
      )}
    </>
  );
}
