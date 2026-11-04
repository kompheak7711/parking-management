// V1.1 part 7 (DL-124): Building › Problem reports (mock-up round 32). "#/problems" is the one
// list of Unit Problems (UP) and Building problems (BP) with the tabs Open, Urgent, Late and Done;
// "#/problems/pr:<id>" one report; "#/problems/new" New Problem report; "#/problems/month" the
// Monthly report (DL-131); "#/problems/finding:<id>" a report from a move-out inspection finding
// (DL-132). Buttons show only to a
// person who holds the right; the server checks every right again.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import { Chip, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import { MonthlyReport } from "./MonthlyReport";
import {
  NewProblemReportForm,
  NewProblemReportFromFinding,
} from "./NewProblemReport";
import { ProblemReportDetail } from "./ProblemReportDetail";
import {
  type ProblemReport,
  type ProblemStatus,
  type ProblemType,
  type ProblemsApi,
  problemsApi as defaultProblemsApi,
} from "./problemsClient";
import { pt } from "./text";

export interface ProblemReportsPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api?: ProblemsApi;
  /** Now, for the age and the visit times; tests pass a fixed moment. */
  now?: Date;
}

const CHIPS: Record<ProblemStatus, Tone> = {
  RECEIVED: "warn",
  PLANNED: "info",
  CHECKED: "info",
  WAITING_TENANT: "warn",
  REPAIR_PLANNED: "info",
  WAITING_PARTS: "warn",
  DONE: "ok",
  CLOSED: "neutral",
  NOT_ACCEPTED: "neutral",
  JOINED: "neutral",
};

export function StatusChip({
  language,
  state,
}: {
  language: Language;
  state: ProblemStatus;
}) {
  return <Chip tone={CHIPS[state]}>{pt(language, `st_${state}`)}</Chip>;
}

/** The line icon of a problem type; a type without its own icon shows the wrench. */
export function typeIcon(type: Pick<ProblemType, "icon">): ShellIcon {
  const icons: Record<string, ShellIcon> = {
    drop: "drop",
    zap: "zap",
    lock: "lock",
    flame: "alert",
    window: "door",
  };
  return icons[type.icon] ?? "wrench";
}

export function typeName(language: Language, type: ProblemType): string {
  return language === "km" && type.name_kh !== null
    ? type.name_kh
    : type.name_en;
}

/** "B101 · Bedroom 1", or the shared place and floor. */
export function whereText(language: Language, report: ProblemReport): string {
  if (report.kind === "UNIT") {
    const place =
      report.place === null
        ? null
        : `${
            language === "km" && report.place.name_kh !== null
              ? report.place.name_kh
              : report.place.name_en
          } ${String(report.place.number)}`;
    return [report.unit_number, place].filter(Boolean).join(" · ");
  }
  const shared =
    report.problem_place === null
      ? ""
      : language === "km" && report.problem_place.name_kh !== null
        ? report.problem_place.name_kh
        : report.problem_place.name_en;
  return [
    shared,
    report.floor === null ? null : pt(language, "floor", report.floor),
  ]
    .filter(Boolean)
    .join(" · ");
}

/** How long ago, as "35 min", "2 h 5 min" or "3 d 4 h". */
export function ageText(language: Language, since: string, now: Date): string {
  const minutes = Math.max(
    0,
    Math.floor((now.getTime() - new Date(since).getTime()) / 60000),
  );
  if (minutes < 60) return pt(language, "w_m", minutes);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return pt(language, "w_hm", hours, minutes % 60);
  return pt(language, "w_dh", Math.floor(hours / 24), hours % 24);
}

const CLOSED: readonly ProblemStatus[] = ["DONE", "CLOSED", "NOT_ACCEPTED"];

export function isOpen(report: ProblemReport): boolean {
  return !CLOSED.includes(report.state) && report.state !== "JOINED";
}

type Tab = "open" | "urgent" | "late" | "done";

function inTab(report: ProblemReport, tab: Tab): boolean {
  if (report.state === "JOINED") return false;
  if (tab === "done") return CLOSED.includes(report.state);
  if (!isOpen(report)) return false;
  if (tab === "urgent") return report.urgent;
  if (tab === "late") return report.late !== null;
  return true;
}

/** A plain click opens the record here; with a key held the browser opens the link itself. */
function plainClick(event: React.MouseEvent): boolean {
  return !(
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

export function ProblemReportsPage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultProblemsApi,
  now,
}: ProblemReportsPageProps) {
  const detail = useHashDetail("problems");
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const [reports, setReports] = useState<ProblemReport[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<Tab>("open");
  const [kind, setKind] = useState("");
  const [type, setType] = useState("");
  const [flash, setFlash] = useState<string | null>(null);
  const sequence = useRef(0);
  const moment = now ?? new Date();

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void api
      .list(propertyId)
      .then((found) => {
        if (operation === sequence.current) setReports(found);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId]);

  // Another Property never shows the reports of the one before.
  useEffect(() => {
    sequence.current++;
    setReports(null);
  }, [propertyId]);

  // Read again each time the list is opened, so it shows what others changed meanwhile.
  useEffect(() => {
    if (
      active &&
      (detail === null || detail === "new" || detail.startsWith("finding:"))
    )
      load();
  }, [active, detail, load]);

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{pt(language, "no_property")}</p>
      </div>
    );
  }

  if (detail?.startsWith("pr:") === true) {
    const reportId = detail.slice(3);
    return (
      <ProblemReportDetail
        api={api}
        flash={flash}
        key={`${reportId}:${propertyId}`}
        language={language}
        may={may}
        now={now}
        onFlashShown={() => {
          setFlash(null);
        }}
        propertyId={propertyId}
        reportId={reportId}
      />
    );
  }
  if (detail === "month" && may("problem_reports.plan")) {
    return (
      <MonthlyReport
        api={api}
        key={propertyId}
        language={language}
        now={now}
        propertyId={propertyId}
      />
    );
  }
  const saved = (made: ProblemReport) => {
    setFlash(
      made.joined_to === null
        ? pt(language, "added", made.report_number)
        : pt(
            language,
            "added_same",
            made.report_number,
            made.joined_to.report_number,
          ),
    );
    openPageInAddress("problems", true, `pr:${made.report_id}`);
  };
  if (detail?.startsWith("finding:") === true && may("problem_reports.add")) {
    return (
      <NewProblemReportFromFinding
        api={api}
        findingId={detail.slice(8)}
        key={`${detail}:${propertyId}`}
        language={language}
        onSaved={saved}
        propertyId={propertyId}
        reports={reports ?? []}
      />
    );
  }
  if (detail === "new" && may("problem_reports.add")) {
    return (
      <NewProblemReportForm
        api={api}
        key={propertyId}
        language={language}
        onSaved={saved}
        propertyId={propertyId}
        reports={reports ?? []}
      />
    );
  }

  const failure = failed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{pt(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {pt(language, "retry")}
      </button>
    </div>
  );
  if (reports === null)
    return (
      failure || (
        <p className="ui-muted" role="status">
          {pt(language, "loading")}
        </p>
      )
    );

  const types = new Map<string, ProblemType>();
  for (const report of reports)
    types.set(report.problem_type.id, report.problem_type);
  const filtered = (report: ProblemReport) =>
    (kind === "" || report.kind === kind) &&
    (type === "" || report.problem_type.id === type);
  const rows = reports
    .filter((report) => inTab(report, tab) && filtered(report))
    .sort((a, b) =>
      tab === "done"
        ? b.created_at.localeCompare(a.created_at)
        : a.created_at.localeCompare(b.created_at),
    );
  const joinedTo = new Map<string, ProblemReport[]>();
  for (const report of reports)
    if (report.state === "JOINED" && report.joined_to !== null) {
      const kids = joinedTo.get(report.joined_to.report_id) ?? [];
      kids.push(report);
      joinedTo.set(report.joined_to.report_id, kids);
    }
  const open = (id: string) => {
    openPageInAddress("problems", false, `pr:${id}`);
  };
  const link = (report: ProblemReport) => (
    <a
      className="ui-no ui-num"
      href={hashForPage("problems", `pr:${report.report_id}`)}
      onClick={(event) => {
        event.stopPropagation();
        if (!plainClick(event)) return;
        event.preventDefault();
        open(report.report_id);
      }}
    >
      {report.report_number}
    </a>
  );
  const filtering = kind !== "" || type !== "";

  return (
    <>
      {failure}
      <div className="ui-head">
        <p>{pt(language, "sub")}</p>
        {(may("problem_reports.plan") || may("problem_reports.add")) && (
          <div className="ui-actions">
            {may("problem_reports.plan") && (
              <a className="ui-btn" href={hashForPage("problems", "month")}>
                <Icon name="reports" />
                {pt(language, "m_title")}
              </a>
            )}
            {may("problem_reports.add") && (
              <a
                className="ui-btn primary"
                href={hashForPage("problems", "new")}
              >
                <Icon name="plus" />
                {pt(language, "add")}
              </a>
            )}
          </div>
        )}
      </div>
      <div className="ui-filters">
        <div aria-label={pt(language, "tabs")} className="ui-seg" role="group">
          {(["open", "urgent", "late", "done"] as const).map((value) => (
            <button
              aria-pressed={tab === value}
              key={value}
              onClick={() => {
                setTab(value);
              }}
              type="button"
            >
              {pt(language, `tab_${value}`)}{" "}
              <span className="ui-num ui-muted">
                {reports.filter((report) => inTab(report, value)).length}
              </span>
            </button>
          ))}
        </div>
        <label className="ui-sr" htmlFor="pr-f-kind">
          {pt(language, "f_kind")}
        </label>
        <select
          className="ui-sel"
          id="pr-f-kind"
          onChange={(event) => {
            setKind(event.currentTarget.value);
          }}
          value={kind}
        >
          <option value="">
            {pt(language, "f_kind")}: {pt(language, "f_all")}
          </option>
          <option value="UNIT">{pt(language, "k_UNIT")}</option>
          <option value="BUILDING">{pt(language, "k_BUILDING")}</option>
        </select>
        <label className="ui-sr" htmlFor="pr-f-type">
          {pt(language, "f_type")}
        </label>
        <select
          className="ui-sel"
          id="pr-f-type"
          onChange={(event) => {
            setType(event.currentTarget.value);
          }}
          value={type}
        >
          <option value="">
            {pt(language, "f_type")}: {pt(language, "f_all")}
          </option>
          {[...types.values()].map((entry) => (
            <option key={entry.id} value={entry.id}>
              {typeName(language, entry)}
            </option>
          ))}
        </select>
        {filtering && (
          <button
            className="ui-btn link"
            onClick={() => {
              setKind("");
              setType("");
            }}
            type="button"
          >
            {pt(language, "f_clear")}
          </button>
        )}
      </div>
      <div className="ui-card pad0">
        {rows.length === 0 ? (
          <p className="ui-empty">
            {pt(language, filtering ? "f_none" : "none")}
          </p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{pt(language, "c_no")}</th>
                    <th className="ui-wide" scope="col">
                      {pt(language, "c_kind")}
                    </th>
                    <th scope="col">{pt(language, "c_type")}</th>
                    <th scope="col">{pt(language, "c_where")}</th>
                    <th className="ui-wide" scope="col">
                      {pt(language, "c_src")}
                    </th>
                    <th scope="col">{pt(language, "c_status")}</th>
                    <th className="ui-wide" scope="col">
                      {pt(language, "c_who")}
                    </th>
                    <th className="ui-wide" scope="col">
                      {pt(language, "c_age")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.flatMap((report) => {
                    const kids = joinedTo.get(report.report_id) ?? [];
                    return [
                      <tr
                        className="ui-row"
                        key={report.report_id}
                        onClick={() => {
                          open(report.report_id);
                        }}
                      >
                        <td>
                          {link(report)}
                          <span className="ui-sub2">
                            {report.urgent && (
                              <Chip icon="alert" tone="err">
                                {pt(language, "urgent")}
                              </Chip>
                            )}{" "}
                            {report.repeat !== null && (
                              <Chip tone="warn">{pt(language, "repeat")}</Chip>
                            )}{" "}
                            {kids.length > 0 && (
                              <Chip tone="neutral">
                                {pt(language, "joined_n", kids.length)}
                              </Chip>
                            )}
                          </span>
                        </td>
                        <td className="ui-wide">
                          {pt(language, `k_${report.kind}`)}
                        </td>
                        <td>
                          <Icon name={typeIcon(report.problem_type)} small />{" "}
                          {typeName(language, report.problem_type)}
                          <span className="ui-sub2">{report.description}</span>
                        </td>
                        <td>
                          {whereText(language, report)}
                          {report.kind === "UNIT" && (
                            <span className="ui-sub2">
                              {report.customer_name ?? pt(language, "no_lease")}
                            </span>
                          )}
                        </td>
                        <td className="ui-wide">
                          {pt(language, `src_${report.source}`)}
                        </td>
                        <td>
                          <StatusChip
                            language={language}
                            state={report.state}
                          />
                          {report.late !== null && (
                            <span className="ui-sub2 warn">
                              {pt(
                                language,
                                report.late === "URGENT" ? "late_u" : "late_n",
                              )}
                            </span>
                          )}
                        </td>
                        <td className="ui-wide">
                          {report.technician === null ? (
                            <span className="ui-muted">
                              {pt(language, "not_planned")}
                            </span>
                          ) : (
                            <>
                              {report.technician}
                              {report.visit_on !== null && (
                                <span className="ui-sub2 ui-num">
                                  {report.visit_on
                                    .split("-")
                                    .reverse()
                                    .join("/")}{" "}
                                  {report.visit_at ?? ""}
                                </span>
                              )}
                            </>
                          )}
                        </td>
                        <td className="ui-wide ui-num">
                          {ageText(language, report.created_at, moment)}
                        </td>
                      </tr>,
                      ...kids.map((kid) => (
                        <tr
                          className="ui-row ui-joined"
                          key={kid.report_id}
                          onClick={() => {
                            open(kid.report_id);
                          }}
                        >
                          <td>
                            {link(kid)}
                            <span className="ui-sub2">
                              {pt(language, "joined_to", report.report_number)}
                            </span>
                          </td>
                          <td className="ui-wide">
                            {pt(language, `k_${kid.kind}`)}
                          </td>
                          <td>
                            <span className="ui-muted">{kid.description}</span>
                          </td>
                          <td>{whereText(language, kid)}</td>
                          <td className="ui-wide">
                            {pt(language, `src_${kid.source}`)}
                          </td>
                          <td>
                            <StatusChip language={language} state="JOINED" />
                          </td>
                          <td className="ui-wide ui-muted">
                            {pt(language, "follows", report.report_number)}
                          </td>
                          <td className="ui-wide ui-num">
                            {ageText(language, kid.created_at, moment)}
                          </td>
                        </tr>
                      )),
                    ];
                  })}
                </tbody>
              </table>
            </div>
            <div className="ui-tfoot">
              {rows.length === 1
                ? pt(language, "n1")
                : pt(language, "n", rows.length)}
            </div>
          </>
        )}
      </div>
    </>
  );
}
