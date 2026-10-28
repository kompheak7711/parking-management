// V1-060 B6: the Reports page (DESIGN.md "Reports (round 4)", mock-up app4.js vReports and
// vReport, V1-057 data). "#/reports" lists the reports the person may read in two groups;
// "#/reports/<report>" opens one with the parameter bar (scope, period, Export), its Summary
// card and its table. The scope and period stay the same from one report to the next while the
// page is open. Export makes a spreadsheet or a PDF through the V1-057 export, which writes its
// own History row.

import "../shell/screens.css";
import "./reports.css";

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type DownloadedFile,
  type ExportAnswer,
  type ExportFileType,
  ExportGoneError,
  ExportRefusedError,
  type ExportRequest,
  type RegisterFilter,
  type RegisterName,
  type RegisterPage,
  type RegisterRows,
  ReportsNotAllowedError,
  type TotalsFilter,
  type TotalsPage,
  type TotalsReport,
} from "../reportsClient";
import { DateInput, parseDay } from "../shell/DateInput";
import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, Dialog } from "../shell/ui";
import { useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import type { UnitApi, UnitSetupLists } from "../unitClient";
import { allPages, typeName } from "../units/unitsData";
import { save } from "./parts";
import { RegisterContent } from "./RegisterView";
import {
  floorApplies,
  floorName,
  generatedText,
  mayExport,
  mayRead,
  numberText,
  type Params,
  type Period,
  periodApplies,
  rangeOf,
  rangeText,
  type ReportDef,
  reportDef,
  REPORTS,
  START_PARAMS,
  wholeMonths,
} from "./reportsData";
import { rpt } from "./text";
import { TotalsContent } from "./TotalsView";

export interface ReportApi {
  totals: (
    propertyId: string,
    report: TotalsReport,
    filter?: TotalsFilter,
  ) => Promise<TotalsPage>;
  register: <N extends RegisterName>(
    propertyId: string,
    name: N,
    filter?: RegisterFilter,
  ) => Promise<RegisterPage<N>>;
  exportFile: (
    propertyId: string,
    request: ExportRequest,
  ) => Promise<ExportAnswer>;
  download: (propertyId: string, exportId: string) => Promise<DownloadedFile>;
}

export interface ReportsPageProps {
  language: Language;
  propertyId: string;
  /** The page reads its report each time it is opened. */
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api: ReportApi;
  /** The Units, for the Unit and floor choices and the Unit Type names. */
  units: Pick<UnitApi, "list" | "setupLists">;
  /** Today in Phnom Penh (yyyy-mm-dd), for This month and Last month. */
  today: string;
  /** The clock, for the Generated line. */
  now?: () => number;
}

interface UnitChoice {
  id: string;
  number: string;
  floor: string;
}

// A register reads 200 rows at a time; Show more reads the next 200.
const PAGE_ROWS = 200;

const PERIODS: readonly (readonly [
  Period,
  "p_all" | "p_month" | "p_last" | "p_pick",
])[] = [
  ["all", "p_all"],
  ["month", "p_month"],
  ["last", "p_last"],
  ["pick", "p_pick"],
];

export function ReportsPage({
  language,
  propertyId,
  active,
  capabilities,
  api,
  units,
  today,
  now = Date.now,
}: ReportsPageProps) {
  const detail = useHashDetail("reports");
  const [params, setParams] = useState<Params>(START_PARAMS);
  const [unitList, setUnitList] = useState<UnitChoice[]>([]);
  const [lists, setLists] = useState<UnitSetupLists | null>(null);
  const [shownProperty, setShownProperty] = useState(propertyId);
  const latestProperty = useRef(propertyId);
  const loadedFor = useRef<string | null>(null);

  // Another Property starts again from the whole Property, all dates and its own Units, before
  // its first report is asked for.
  if (shownProperty !== propertyId) {
    setShownProperty(propertyId);
    setParams(START_PARAMS);
    setUnitList([]);
    setLists(null);
  }

  useEffect(() => {
    latestProperty.current = propertyId;
    if (!active || propertyId === "" || loadedFor.current === propertyId) {
      return;
    }
    loadedFor.current = propertyId;
    const asked = propertyId;
    // The Units give the Unit and floor choices; without them the bar offers the whole
    // Property and All Units only.
    allPages(async (cursor) =>
      units.list(propertyId, cursor === undefined ? {} : { cursor }),
    )
      .then((list) => {
        if (latestProperty.current !== asked) return;
        setUnitList(
          list
            .map((unit) => ({
              id: unit.unit_id,
              number: unit.unit_number,
              floor: unit.floor,
            }))
            .sort((left, right) =>
              left.number.localeCompare(right.number, undefined, {
                numeric: true,
              }),
            ),
        );
      })
      .catch(() => undefined);
    units
      .setupLists(propertyId)
      .then((value) => {
        if (latestProperty.current === asked) setLists(value);
      })
      .catch(() => undefined);
  }, [active, propertyId, units]);

  if (!active || propertyId === "") return null;

  const def = reportDef(detail);
  if (def === null) {
    return <ReportsList capabilities={capabilities} language={language} />;
  }

  // Floors in the Settings order, then any other floor a Unit uses (as on the Units list).
  const floorOrder = (lists?.lists.FLOOR ?? []).map((item) => item.name_en);
  const floors = [...new Set(unitList.map((unit) => unit.floor))]
    .filter((floor) => floor !== "")
    .sort((left, right) => {
      const a = floorOrder.indexOf(left);
      const b = floorOrder.indexOf(right);
      if (a !== b) return (a < 0 ? 1e9 : a) - (b < 0 ? 1e9 : b);
      return left.localeCompare(right, undefined, { numeric: true });
    });

  return (
    <ReportView
      api={api}
      capabilities={capabilities}
      def={def}
      floors={floors}
      key={`${def.key}:${propertyId}`}
      language={language}
      now={now}
      onParams={setParams}
      params={params}
      propertyId={propertyId}
      today={today}
      typeName={(code) => typeName(lists, code, language === "km")}
      unitList={unitList}
    />
  );
}

function ReportsList({
  language,
  capabilities,
}: {
  language: Language;
  capabilities: ReadonlySet<string> | null;
}) {
  const allowed = REPORTS.filter((def) => mayRead(def, capabilities));
  const groups = [
    ["g_totals", allowed.filter((def) => def.kind === "totals")],
    ["g_registers", allowed.filter((def) => def.kind === "register")],
  ] as const;
  return (
    <>
      <div className="ui-head">
        <p>{rpt(language, "rp_sub")}</p>
      </div>
      {allowed.length === 0 && (
        <div className="ui-notice warn" role="note">
          <Icon name="lock" />
          <p>{rpt(language, "none_allowed")}</p>
        </div>
      )}
      {groups.map(
        ([group, defs]) =>
          defs.length > 0 && (
            <section
              aria-labelledby={`rp-${group}`}
              className="rp-groupsec"
              key={group}
            >
              <h2 className="rp-group" id={`rp-${group}`}>
                {rpt(language, group)}
              </h2>
              <ul className="rp-cards">
                {defs.map((def) => (
                  <li key={def.key}>
                    <a
                      className="rp-card"
                      href={hashForPage("reports", def.key)}
                    >
                      <span className="rp-card-name">
                        <span className="rp-card-icon">
                          <Icon name={def.icon} small />
                        </span>
                        {rpt(language, `r_${def.key}`)}
                      </span>
                      <span className="rp-card-desc">
                        {rpt(language, `d_${def.key}`)}
                      </span>
                      <span className="rp-card-foot">
                        {def.tagged && (
                          <span className="rp-tag">{rpt(language, "tag")}</span>
                        )}
                        <span className="rp-card-open">
                          {rpt(language, "open")}
                        </span>
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ),
      )}
      <p className="ui-small ui-muted">
        {rpt(language, "staff_note")} {rpt(language, "currency")}
      </p>
    </>
  );
}

type Loaded =
  | { kind: "totals"; page: TotalsPage; at: number }
  | {
      kind: "register";
      page: RegisterPage<RegisterName>;
      rows: RegisterRows[RegisterName][];
      at: number;
    };

function ReportView({
  def,
  language,
  propertyId,
  capabilities,
  api,
  params,
  onParams,
  today,
  now,
  unitList,
  floors,
  typeName: unitTypeName,
}: {
  def: ReportDef;
  language: Language;
  propertyId: string;
  capabilities: ReadonlySet<string> | null;
  api: ReportApi;
  params: Params;
  onParams: (params: Params) => void;
  today: string;
  now: () => number;
  unitList: UnitChoice[];
  floors: string[];
  typeName: (code: string) => string;
}) {
  const allowed = mayRead(def, capabilities);
  const picked = periodApplies(def.key) ? rangeOf(params, today) : null;
  // V1-060 B7: a Totals table counts whole months, so it shows and asks for the whole months
  // of the picked days (the real range of its figures).
  const range =
    picked !== null && def.kind === "totals" && params.period === "pick"
      ? wholeMonths(picked)
      : picked;
  const from = range?.[0];
  const to = range?.[1];
  const floor =
    def.kind === "register" && floorApplies(def.key) ? params.floor : "";
  const unitId = def.kind === "totals" ? params.unitId : "";
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<"failed" | "not_allowed" | null>(
    allowed ? null : "not_allowed",
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreFailed, setMoreFailed] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setLoaded(null);
    setLoadingMore(false);
    setMoreFailed(false);
    // A report the person may not read is not asked for.
    if (!allowed) {
      setFailure("not_allowed");
      return;
    }
    setFailure(null);
    const dates = from === undefined ? {} : { from, to };
    const request: Promise<Loaded> =
      def.kind === "totals"
        ? api
            .totals(propertyId, def.key, {
              ...(unitId === "" ? {} : { unitId }),
              ...dates,
            })
            .then((page) => ({ kind: "totals", page, at: now() }))
        : api
            .register(propertyId, def.key, {
              ...(floor === "" ? {} : { floor }),
              ...dates,
              limit: PAGE_ROWS,
            })
            .then((page) => ({
              kind: "register",
              page,
              rows: page.rows,
              at: now(),
            }));
    request
      .then((answer) => {
        if (operation === sequence.current) setLoaded(answer);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setFailure(
          error instanceof ReportsNotAllowedError ? "not_allowed" : "failed",
        );
      });
  }, [allowed, api, def, floor, from, now, propertyId, to, unitId]);

  useEffect(load, [load]);

  function more() {
    if (def.kind !== "register" || loaded?.kind !== "register") return;
    const operation = sequence.current;
    setLoadingMore(true);
    setMoreFailed(false);
    api
      .register(propertyId, def.key, {
        ...(floor === "" ? {} : { floor }),
        ...(from === undefined ? {} : { from, to }),
        offset: loaded.rows.length,
        limit: PAGE_ROWS,
      })
      .then((page) => {
        if (operation !== sequence.current) return;
        setLoaded({ ...loaded, rows: [...loaded.rows, ...page.rows] });
      })
      .catch(() => {
        if (operation === sequence.current) setMoreFailed(true);
      })
      .finally(() => {
        if (operation === sequence.current) setLoadingMore(false);
      });
  }

  async function runExport(fileType: ExportFileType): Promise<void> {
    const request: ExportRequest = {
      report: def.key,
      fileType,
      ...(floor === "" ? {} : { floor }),
      ...(unitId === "" ? {} : { unitId }),
      ...(range === null ? {} : { from: range[0], to: range[1] }),
    };
    const answer = await api.exportFile(propertyId, request);
    // A big file is kept 24 hours as an export job and fetched from there.
    const file =
      answer.kind === "file"
        ? answer
        : await api.download(propertyId, answer.exportId);
    save(file);
    setExporting(false);
    setNote(rpt(language, "ex_saved", answer.fileName));
  }

  const name = rpt(language, `r_${def.key}`);
  const scope =
    def.kind === "totals"
      ? unitId === ""
        ? rpt(language, "all_units")
        : (unitList.find((unit) => unit.id === unitId)?.number ?? "—")
      : floor === ""
        ? rpt(language, "whole")
        : floorName(language, floor);
  const period = periodApplies(def.key)
    ? rangeText(language, range)
    : rpt(language, "as_of", dayText(today));

  const head = (
    <>
      <a className="ui-crumb" href={hashForPage("reports")}>
        <Icon name="back" small />
        {rpt(language, "back")}
      </a>
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2>{name}</h2>
            {def.tagged && (
              <Chip icon="lock" tone="info">
                {rpt(language, "tag")}
              </Chip>
            )}
          </div>
          <p>{rpt(language, `d_${def.key}`)}</p>
        </div>
      </div>
    </>
  );

  if (failure === "not_allowed") {
    return (
      <>
        {head}
        <div className="ui-notice warn" role="alert">
          <Icon name="lock" />
          <p>{rpt(language, "not_allowed")}</p>
        </div>
      </>
    );
  }

  let body: ReactNode;
  if (failure === "failed") {
    body = (
      <div className="ui-notice warn" role="alert">
        <Icon name="alert" />
        <p>{rpt(language, "failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {rpt(language, "retry")}
        </button>
      </div>
    );
  } else if (loaded === null) {
    body = (
      <p className="ui-card ui-empty" role="status">
        {rpt(language, "loading")}
      </p>
    );
  } else {
    const generated = generatedText(loaded.at);
    const empty =
      loaded.kind === "totals"
        ? loaded.page.years.length === 0
        : loaded.page.row_count === 0;
    if (empty) {
      body = (
        <section aria-label={name} className="ui-card pad0">
          <p className="ui-empty">
            {rpt(language, periodApplies(def.key) ? "none" : "none_now")}
          </p>
          <div className="ui-tfoot">
            {rpt(language, "generated", generated)}
          </div>
        </section>
      );
    } else if (loaded.kind === "totals" && def.kind === "totals") {
      body = (
        <TotalsContent
          frame={{
            language,
            title: name,
            icon: def.icon,
            count: scope,
            generated,
          }}
          language={language}
          page={loaded.page}
          report={def.key}
        />
      );
    } else if (loaded.kind === "register" && def.kind === "register") {
      const all = loaded.page.row_count;
      const read = loaded.rows.length;
      body = (
        <RegisterContent
          count={(lines) =>
            read < all
              ? rpt(language, "showing", read, all)
              : lines === 1
                ? rpt(language, "rows1")
                : rpt(language, "rows", lines)
          }
          frame={{
            language,
            title: name,
            icon: def.icon,
            generated,
            ...(read < all ? { totalLabel: rpt(language, "total_all") } : {}),
            more: read < all && (
              <span className="ui-hrow">
                {moreFailed && (
                  <span className="ui-sub2 warn" role="alert">
                    {rpt(language, "more_failed")}
                  </span>
                )}
                <button
                  className="ui-btn"
                  disabled={loadingMore}
                  onClick={more}
                  type="button"
                >
                  {rpt(language, "more")}
                </button>
              </span>
            ),
          }}
          language={language}
          name={def.key}
          page={loaded.page}
          rows={loaded.rows}
          typeName={unitTypeName}
        />
      );
    }
  }

  return (
    <>
      {head}
      <ParameterBar
        def={def}
        exportDisabled={loaded === null}
        floors={floors}
        language={language}
        onExport={
          mayExport(def, capabilities)
            ? () => {
                setNote(null);
                setExporting(true);
              }
            : null
        }
        onParams={onParams}
        params={params}
        range={range}
        today={today}
        unitList={unitList}
      />
      <div aria-live="polite" role="status">
        {note !== null && (
          <div className="ui-notice ok">
            <Icon name="check" />
            <p>{note}</p>
          </div>
        )}
      </div>
      {body}
      {exporting && (
        <ExportDialog
          language={language}
          name={name}
          onClose={() => {
            setExporting(false);
          }}
          period={period}
          rows={loaded?.kind === "register" ? loaded.page.row_count : null}
          run={runExport}
          scope={scope}
        />
      )}
    </>
  );
}

function ParameterBar({
  def,
  language,
  params,
  onParams,
  today,
  range,
  unitList,
  floors,
  onExport,
  exportDisabled,
}: {
  def: ReportDef;
  language: Language;
  params: Params;
  onParams: (params: Params) => void;
  today: string;
  range: [string, string] | null;
  unitList: UnitChoice[];
  floors: string[];
  /** Null when the person may not export this report. */
  onExport: (() => void) | null;
  exportDisabled: boolean;
}) {
  let scope: ReactNode = null;
  if (def.kind === "totals") {
    scope = (
      <>
        <label className="ui-sr" htmlFor="rp-unit">
          {rpt(language, "unit")}
        </label>
        <select
          className="ui-sel"
          id="rp-unit"
          onChange={(event) => {
            onParams({ ...params, unitId: event.currentTarget.value });
          }}
          value={params.unitId}
        >
          <option value="">{rpt(language, "all_units")}</option>
          {unitList.map((unit) => (
            <option key={unit.id} value={unit.id}>
              {unit.number}
            </option>
          ))}
        </select>
      </>
    );
  } else if (floorApplies(def.key)) {
    scope = (
      <>
        <label className="ui-sr" htmlFor="rp-scope">
          {rpt(language, "scope")}
        </label>
        <select
          className="ui-sel"
          id="rp-scope"
          onChange={(event) => {
            onParams({ ...params, floor: event.currentTarget.value });
          }}
          value={params.floor}
        >
          <option value="">{rpt(language, "whole")}</option>
          {floors.map((floor) => (
            <option key={floor} value={floor}>
              {floorName(language, floor)}
            </option>
          ))}
        </select>
      </>
    );
  }
  const choose = (period: Period) => {
    if (period !== "pick") {
      onParams({ ...params, period });
      return;
    }
    // Pick dates starts from the days on screen, or this month. Pressed again it keeps the days
    // typed: a Totals table shows them widened to whole months (V1-060 B7).
    if (params.period === "pick") return;
    const [first, last] = range ?? [`${today.slice(0, 7)}-01`, today];
    onParams({ ...params, period, from: first, to: last });
  };
  return (
    <div className="ui-filters">
      {scope}
      {periodApplies(def.key) ? (
        <>
          <div
            aria-label={rpt(language, "period")}
            className="ui-seg"
            role="group"
          >
            {PERIODS.map(([value, key]) => (
              <button
                aria-pressed={params.period === value}
                key={value}
                onClick={() => {
                  choose(value);
                }}
                type="button"
              >
                {rpt(language, key)}
              </button>
            ))}
          </div>
          {params.period === "pick" && (
            <PickDates
              from={params.from}
              key={`${params.from}:${params.to}`}
              language={language}
              onPick={(first, last) => {
                onParams({ ...params, period: "pick", from: first, to: last });
              }}
              to={params.to}
            />
          )}
          <span className="rp-range ui-num">{rangeText(language, range)}</span>
          {def.kind === "totals" && params.period === "pick" && (
            <span className="rp-range">{rpt(language, "months_note")}</span>
          )}
        </>
      ) : (
        <span className="rp-range">
          {rpt(language, "today_only", dayText(today))}
        </span>
      )}
      {onExport !== null && (
        <button
          className="ui-btn ui-push"
          disabled={exportDisabled}
          onClick={onExport}
          type="button"
        >
          <Icon name="upload" small />
          {rpt(language, "export")}
        </button>
      )}
    </div>
  );
}

function PickDates({
  language,
  from,
  to,
  onPick,
}: {
  language: Language;
  from: string;
  to: string;
  onPick: (from: string, to: string) => void;
}) {
  const [first, setFirst] = useState(from);
  const [last, setLast] = useState(to);
  const [bad, setBad] = useState(false);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const start = parseDay(first);
    const end = parseDay(last);
    if (start === "" || end === "" || start > end) {
      setBad(true);
      return;
    }
    setBad(false);
    onPick(start, end);
  };
  return (
    <form className="ui-pick" noValidate onSubmit={submit}>
      <label htmlFor="rp-from">{rpt(language, "from")}</label>
      <DateInput
        calendarLabel={`${rpt(language, "calendar")} · ${rpt(language, "from")}`}
        describedBy={bad ? "rp-dates-error" : undefined}
        id="rp-from"
        invalid={bad}
        language={language}
        onChange={setFirst}
        value={first}
      />
      <label htmlFor="rp-to">{rpt(language, "to")}</label>
      <DateInput
        calendarLabel={`${rpt(language, "calendar")} · ${rpt(language, "to")}`}
        describedBy={bad ? "rp-dates-error" : undefined}
        id="rp-to"
        invalid={bad}
        language={language}
        onChange={setLast}
        value={last}
      />
      <button className="ui-btn" type="submit">
        {rpt(language, "show")}
      </button>
      {bad && (
        <p className="ui-perr" id="rp-dates-error" role="alert">
          <Icon name="alert" small />
          {rpt(language, "bad_dates")}
        </p>
      )}
    </form>
  );
}

function ExportDialog({
  language,
  name,
  scope,
  period,
  rows,
  onClose,
  run,
}: {
  language: Language;
  name: string;
  scope: string;
  period: string;
  /** The rows of a register; null for a Totals table. */
  rows: number | null;
  onClose: () => void;
  run: (fileType: ExportFileType) => Promise<void>;
}) {
  const [fileType, setFileType] = useState<ExportFileType>("xlsx");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    run(fileType).catch((error: unknown) => {
      setBusy(false);
      setProblem(
        rpt(
          language,
          error instanceof ExportRefusedError
            ? "ex_refused"
            : error instanceof ReportsNotAllowedError
              ? "ex_not_allowed"
              : error instanceof ExportGoneError
                ? "ex_gone"
                : "ex_failed",
        ),
      );
    });
  };
  return (
    <Dialog
      busy={busy}
      closeLabel={rpt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={rpt(language, "ex_ok")}
      title={rpt(language, "ex_title", name)}
    >
      <dl className="ui-kv">
        <dt>{rpt(language, "ex_report")}</dt>
        <dd>{name}</dd>
        <dt>{rpt(language, "scope")}</dt>
        <dd>{scope}</dd>
        <dt>{rpt(language, "period")}</dt>
        <dd className="ui-num">{period}</dd>
        {rows !== null && (
          <>
            <dt>{rpt(language, "ex_rows")}</dt>
            <dd className="ui-num">{numberText(rows)}</dd>
          </>
        )}
      </dl>
      <fieldset className="ui-radios">
        <legend>{rpt(language, "ex_type")}</legend>
        {(["xlsx", "pdf"] as const).map((type) => (
          <label className="ui-chk" key={type}>
            <input
              checked={fileType === type}
              name="rp-file-type"
              onChange={() => {
                setFileType(type);
              }}
              type="radio"
            />
            {rpt(language, type === "xlsx" ? "ex_xlsx" : "ex_pdf")}
          </label>
        ))}
      </fieldset>
      {fileType === "pdf" && (
        <p className="ui-small ui-muted">{rpt(language, "ex_pdf_note")}</p>
      )}
      <div className="ui-notice warn">
        <Icon name="alert" />
        <p>{rpt(language, "ex_sens")}</p>
      </div>
      <p className="ui-small">{rpt(language, "ex_logged")}</p>
      {problem !== null && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <p>{problem}</p>
        </div>
      )}
    </Dialog>
  );
}
