// V1.1 part 7 (DL-124): one Problem report (mock-up round 32). The Next step box shows the steps
// that fit the report's status; a step needs "Plan repairs" (Join and Undo join need "Join
// reports"). When the tenant pays and agrees, the server makes the Damage Invoice draft at once
// for the amount the Manager set; the box links to it.

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { centsFromText } from "../products/productsClient";
import { DateInput } from "../shell/DateInput";
import {
  dayText,
  momentText,
  todayInPhnomPenh,
  usdFromCents,
} from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { problemRefusal } from "./NewProblemReport";
import {
  ageText,
  isOpen,
  StatusChip,
  typeIcon,
  typeName,
  whereText,
} from "./ProblemReportsPage";
import {
  type ProblemReport,
  type ProblemStep,
  type ProblemsApi,
  ProblemsError,
  type StepName,
  type TenantAnswer,
} from "./problemsClient";
import { hasText, pt, type ProblemsTextKey } from "./text";

type Problem = "failed" | "missing";
type DialogName = StepName | "REPLAN" | "ANSWER";

/** The visit times: every 30 minutes from 07:00 to 16:30. */
export const VISIT_TIMES: readonly string[] = Array.from(
  { length: 20 },
  (_, index) => {
    const minutes = 7 * 60 + index * 30;
    return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${minutes % 60 === 0 ? "00" : "30"}`;
  },
);

function addDays(day: string, days: number): string {
  const moment = new Date(`${day}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

function historyText(
  language: Language,
  step: string,
  details: Record<string, unknown> | null,
): string {
  const detail = (key: string) => {
    const value = details?.[key];
    return typeof value === "string" || typeof value === "number"
      ? String(value)
      : "";
  };
  const key = `h_${step}`;
  if (!hasText(key)) return step;
  switch (step) {
    case "RECEIVED":
      return pt(
        language,
        key,
        hasText(`src_${detail("source")}`)
          ? pt(language, `src_${detail("source")}` as ProblemsTextKey)
          : detail("source"),
      );
    case "CONTACTED":
      return pt(
        language,
        key,
        hasText(`con_${detail("how")}`)
          ? pt(language, `con_${detail("how")}` as ProblemsTextKey)
          : detail("how"),
      );
    case "PLANNED":
    case "REPLANNED":
      return pt(
        language,
        key,
        `${detail("technician")}, ${dayText(detail("visit_on"))} ${detail("visit_at")}`,
      );
    case "CLEANING":
      return pt(language, key, detail("cleaner"));
    case "CHECKED":
      return pt(
        language,
        key,
        hasText(`cause_${detail("cause")}`)
          ? pt(language, `cause_${detail("cause")}` as ProblemsTextKey)
          : detail("cause"),
      );
    case "TENANT_PAYS":
      return pt(
        language,
        key,
        usdFromCents(Number(detail("amount_usd_cents"))),
      );
    case "JOINED":
    case "MOVED":
      return pt(language, key, detail("main_number"));
    case "JOINED_IN":
    case "UNJOINED_OUT":
      return pt(language, key, detail("report_number"));
    default:
      return pt(language, key);
  }
}

export function ProblemReportDetail({
  language,
  propertyId,
  reportId,
  api,
  may,
  flash,
  onFlashShown,
  now,
}: {
  language: Language;
  propertyId: string;
  reportId: string;
  api: ProblemsApi;
  may: (capability: string) => boolean;
  flash: string | null;
  onFlashShown: () => void;
  now?: Date;
}) {
  const moment = now ?? new Date();
  const today = todayInPhnomPenh(moment);
  const [report, setReport] = useState<ProblemReport | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [notice, setNotice] = useState<string | null>(flash);
  const [dialog, setDialog] = useState<DialogName | null>(null);
  const [others, setOthers] = useState<ProblemReport[]>([]);
  const sequence = useRef(0);

  useEffect(() => {
    if (flash !== null) onFlashShown();
  }, [flash, onFlashShown]);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setProblem(null);
    void api
      .get(propertyId, reportId)
      .then((found) => {
        if (operation === sequence.current) setReport(found);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(
          error instanceof ProblemsError && error.status === 404
            ? "missing"
            : "failed",
        );
      });
  }, [api, propertyId, reportId]);

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

  if (report === null)
    return (
      <>
        {back}
        {problem === null ? (
          <p className="ui-muted" role="status">
            {pt(language, "loading")}
          </p>
        ) : (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>
              {pt(language, problem === "missing" ? "not_found" : "failed")}
            </p>
            {problem === "failed" && (
              <button className="ui-btn" onClick={load} type="button">
                {pt(language, "retry")}
              </button>
            )}
          </div>
        )}
      </>
    );

  const state = report.state;
  const plan = may("problem_reports.plan");
  const join = may("problem_reports.join");
  const open = (name: DialogName) => {
    setNotice(null);
    setDialog(name);
    if (name === "JOIN")
      void api
        .list(propertyId)
        .then((found) => {
          setOthers(
            found.filter(
              (other) =>
                other.report_id !== report.report_id &&
                isOpen(other) &&
                other.kind === report.kind &&
                (report.kind === "BUILDING" ||
                  other.unit_id === report.unit_id),
            ),
          );
        })
        .catch(() => {
          setOthers([]);
        });
  };
  const button = (name: DialogName, primary = false): ReactNode => (
    <button
      className={primary ? "ui-btn primary" : "ui-btn"}
      key={name}
      onClick={() => {
        open(name);
      }}
      type="button"
    >
      {pt(language, `s_${name}` as ProblemsTextKey)}
    </button>
  );

  let nextText: string;
  const nextButtons: ReactNode[] = [];
  const visit =
    report.visit_on === null
      ? ""
      : `${dayText(report.visit_on)} ${report.visit_at ?? ""}`;
  switch (state) {
    case "RECEIVED":
      if (report.kind === "BUILDING" && !report.repair_job) {
        nextText = `${pt(language, "n_BP")}. ${pt(language, "n_BP_s")}`;
        if (plan)
          nextButtons.push(
            button("MAKE_JOB", true),
            button("CLEANING"),
            button("CLOSE_NOTE"),
          );
      } else {
        nextText =
          report.urgent && report.contacted_at === null
            ? pt(language, "n_RECEIVED_u", 1)
            : pt(language, "n_RECEIVED");
        if (plan) {
          if (report.urgent && report.contacted_at === null)
            nextButtons.push(button("CONTACTED", true));
          nextButtons.push(
            button("PLAN", !report.urgent || report.contacted_at !== null),
          );
          if (report.kind === "UNIT") nextButtons.push(button("NOT_A_REPAIR"));
        }
      }
      break;
    case "PLANNED":
      nextText = pt(language, "n_PLANNED", report.technician ?? "", visit);
      if (plan) nextButtons.push(button("CHECKED", true), button("REPLAN"));
      break;
    case "CHECKED":
      nextText = pt(language, "n_CHECKED");
      if (plan) nextButtons.push(button("DECIDE", true));
      break;
    case "WAITING_TENANT":
      nextText = pt(language, "n_WAITING_TENANT");
      if (plan) nextButtons.push(button("ANSWER", true));
      break;
    case "REPAIR_PLANNED":
      nextText = pt(language, "n_REPAIR_PLANNED");
      if (plan) nextButtons.push(button("DONE", true), button("PARTS"));
      break;
    case "WAITING_PARTS":
      nextText = pt(language, "n_WAITING_PARTS");
      if (plan) nextButtons.push(button("PARTS_ARRIVED", true));
      break;
    case "DONE":
      nextText =
        report.closes_on !== null
          ? pt(language, "n_DONE", dayText(report.closes_on))
          : pt(language, "n_DONE_close");
      if (plan) {
        if (report.customer_id !== null)
          nextButtons.push(
            button("TENANT_FIXED", true),
            button("TENANT_NOT_FIXED"),
          );
        nextButtons.push(button("CLOSE", report.customer_id === null));
      }
      break;
    case "JOINED":
      nextText = pt(
        language,
        "n_JOINED",
        report.joined_to?.report_number ?? "",
      );
      if (join) nextButtons.push(button("UNJOIN"));
      break;
    default:
      nextText = pt(language, "n_closed");
  }
  if (isOpen(report) && join) nextButtons.push(button("JOIN"));

  const tenantPays = report.pays === "TENANT";
  const history = report.history ?? [];

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num">{report.report_number}</h2>
            <StatusChip language={language} state={state} />
            {report.urgent && (
              <Chip icon="alert" tone="err">
                {pt(language, "urgent")}
              </Chip>
            )}
            {report.repeat !== null && (
              <Chip tone="warn">{pt(language, "repeat")}</Chip>
            )}
          </div>
          <p>
            {[
              pt(language, `k_${report.kind}`),
              typeName(language, report.problem_type),
              pt(language, `src_${report.source}`),
              pt(
                language,
                "received_ago",
                ageText(language, report.created_at, moment),
              ),
              report.created_by_name === null
                ? null
                : pt(language, "added_by", report.created_by_name),
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      {report.late !== null && (
        <div className="ui-notice err" role="note">
          <Icon name="clock" />
          <p>{pt(language, report.late === "URGENT" ? "late_u" : "late_n")}</p>
        </div>
      )}
      {report.repeat !== null && (
        <div className="ui-notice warn" role="note">
          <Icon name="alert" />
          <p>
            {pt(language, "repeat_t", report.repeat.length, "")}{" "}
            {report.repeat.map((earlier, index) => (
              <span key={earlier.report_id}>
                {index > 0 && ", "}
                <a
                  className="ui-num"
                  href={hashForPage("problems", `pr:${earlier.report_id}`)}
                >
                  {earlier.report_number}
                </a>
              </span>
            ))}
          </p>
        </div>
      )}
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="pr-next" className="ui-card">
            <h2 id="pr-next">{pt(language, "next")}</h2>
            <p>{nextText}</p>
            {state === "JOINED" && report.joined_to !== null && (
              <p>
                <a
                  className="ui-btn"
                  href={hashForPage(
                    "problems",
                    `pr:${report.joined_to.report_id}`,
                  )}
                >
                  {pt(language, "open_report", report.joined_to.report_number)}
                </a>
              </p>
            )}
            {nextButtons.length > 0 && (
              <div className="ui-actions">{nextButtons}</div>
            )}
            {!plan && isOpen(report) && (
              <p className="ui-muted ui-small">
                <Icon name="lock" small /> {pt(language, "lock_n")}
              </p>
            )}
            {report.customer_id !== null && isOpen(report) && (
              <p className="ui-muted ui-small">{pt(language, "tell_n")}</p>
            )}
          </section>
          <section aria-labelledby="pr-det" className="ui-card">
            <h2 id="pr-det">{pt(language, "det")}</h2>
            <dl className="ui-kv">
              <dt>{pt(language, "d_where")}</dt>
              <dd>
                <Icon name={typeIcon(report.problem_type)} small />{" "}
                {whereText(language, report) || "—"}
              </dd>
              {report.kind === "UNIT" && (
                <>
                  <dt>{pt(language, "d_tenant")}</dt>
                  <dd>
                    {report.customer_name ?? pt(language, "no_lease")}
                    {report.customer_phone !== null && (
                      <span className="ui-sub2 ui-num">
                        {report.customer_phone}
                      </span>
                    )}
                  </dd>
                </>
              )}
              <dt>{pt(language, "d_text")}</dt>
              <dd>{report.description}</dd>
              {report.reported_by !== null && (
                <>
                  <dt>{pt(language, "d_by")}</dt>
                  <dd>{report.reported_by}</dd>
                </>
              )}
              {report.kind === "UNIT" && (
                <>
                  <dt>{pt(language, "d_enter")}</dt>
                  <dd>{pt(language, report.may_enter ? "yes" : "no")}</dd>
                  <dt>{pt(language, "d_best")}</dt>
                  <dd>{pt(language, `b_${report.best_time}`)}</dd>
                </>
              )}
              <dt>{pt(language, "d_tech")}</dt>
              <dd>
                {report.technician === null
                  ? pt(language, "not_planned")
                  : `${report.technician} · ${visit}`}
              </dd>
              {report.cause !== null && (
                <>
                  <dt>{pt(language, "d_cause")}</dt>
                  <dd>
                    {pt(language, `cause_${report.cause}`)}
                    {report.fixed_at_check &&
                      ` · ${pt(language, "fixed_check")}`}
                    {report.cause_note !== null && (
                      <span className="ui-sub2">{report.cause_note}</span>
                    )}
                  </dd>
                </>
              )}
              <dt>{pt(language, "d_pays")}</dt>
              <dd>
                {report.pays === null
                  ? pt(language, "pays_none")
                  : tenantPays
                    ? pt(
                        language,
                        "pays_t",
                        usdFromCents(report.tenant_amount_usd_cents ?? 0),
                        report.tenant_reason ?? "",
                      )
                    : pt(language, "pays_OWNER")}
              </dd>
              {report.close_note !== null && (
                <>
                  <dt>{pt(language, "note")}</dt>
                  <dd>{report.close_note}</dd>
                </>
              )}
            </dl>
          </section>
          {tenantPays && (
            <section aria-labelledby="pr-dmg" className="ui-card">
              <h2 id="pr-dmg">{pt(language, "dmg_h")}</h2>
              <dl className="ui-kv">
                <dt>{pt(language, "dmg_amt")}</dt>
                <dd className="ui-num">
                  {usdFromCents(report.tenant_amount_usd_cents ?? 0)}
                </dd>
              </dl>
              {report.tenant_answer === "AGREED" ? (
                <p>
                  {pt(
                    language,
                    "agreed_n",
                    pt(
                      language,
                      `how_${report.tenant_answer_how ?? "PHONE"}` as ProblemsTextKey,
                    ),
                    dayText(report.tenant_answer_on),
                  )}
                </p>
              ) : report.tenant_answer === "REFUSED" ? (
                <p>{pt(language, "refused_n", report.tenant_said ?? "")}</p>
              ) : (
                <p className="ui-muted">{pt(language, "dmg_wait")}</p>
              )}
              {report.damage?.invoice_id != null && (
                <div className="ui-actions">
                  <a
                    className="ui-btn primary"
                    href={hashForPage(
                      "invoices",
                      `inv:${report.damage.invoice_id}`,
                    )}
                  >
                    <Icon name="invoice" />
                    {pt(
                      language,
                      "dmg_open",
                      report.damage.invoice_number ?? "",
                    )}
                  </a>
                  <span className="ui-muted ui-small">
                    {pt(language, "dmg_made")}
                  </span>
                </div>
              )}
            </section>
          )}
        </div>
        <div className="ui-stack">
          {state === "JOINED" && report.join !== null && (
            <section aria-labelledby="pr-jn" className="ui-card">
              <h2 id="pr-jn">
                {pt(language, "jn_t", report.joined_to?.report_number ?? "")}
              </h2>
              <p>{report.join.reason}</p>
              <p className="ui-muted ui-small">
                {pt(
                  language,
                  "jn_by",
                  report.join.joined_by_name ?? "—",
                  momentText(report.join.joined_at),
                )}
              </p>
              {!join && (
                <p className="ui-muted ui-small">
                  <Icon name="lock" small /> {pt(language, "jn_lock")}
                </p>
              )}
            </section>
          )}
          {report.joined.length > 0 && (
            <section aria-labelledby="pr-kids" className="ui-card">
              <h2 id="pr-kids">
                {pt(language, "kids_h", report.joined.length)}
              </h2>
              <ul className="ui-plain">
                {report.joined.map((kid) => (
                  <li key={kid.report_id}>
                    <a
                      className="ui-num"
                      href={hashForPage("problems", `pr:${kid.report_id}`)}
                    >
                      {kid.report_number}
                    </a>{" "}
                    · {pt(language, `src_${kid.source}`)}
                    <span className="ui-sub2">{kid.description}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section aria-labelledby="pr-hist" className="ui-card">
            <h2 id="pr-hist">{pt(language, "hist")}</h2>
            <ol className="ui-timeline">
              {history.map((entry, index) => (
                <li key={index}>
                  <div>
                    {historyText(language, entry.step, entry.details)}
                    {entry.note !== null && (
                      <span className="ui-sub2">{entry.note}</span>
                    )}
                    <small className="ui-num">
                      {momentText(entry.at)}
                      {entry.by_name !== null && ` · ${entry.by_name}`}
                    </small>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
      {dialog !== null && dialog !== "ANSWER" && (
        <StepDialog
          api={api}
          language={language}
          name={dialog}
          onClose={() => {
            setDialog(null);
          }}
          onDone={(changed) => {
            setDialog(null);
            setReport(changed);
            setNotice(pt(language, "saved", changed.report_number));
          }}
          onStale={() => {
            setDialog(null);
            load();
            setNotice(null);
          }}
          others={others}
          propertyId={propertyId}
          report={report}
          today={today}
        />
      )}
      {dialog === "ANSWER" && (
        <AnswerDialog
          api={api}
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onDone={(changed) => {
            setDialog(null);
            setReport(changed);
            setNotice(
              changed.damage?.invoice_number != null
                ? pt(
                    language,
                    "agreed_done",
                    changed.report_number,
                    changed.damage.invoice_number,
                  )
                : pt(language, "saved", changed.report_number),
            );
          }}
          propertyId={propertyId}
          report={report}
          today={today}
        />
      )}
    </>
  );
}

function Field({
  id,
  label,
  required,
  error,
  help,
  children,
}: {
  id: string;
  label: string;
  required?: boolean;
  error?: string | null;
  help?: string;
  children: ReactNode;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label}
        {required === true && <span className="req">{"*"}</span>}
      </label>
      {children}
      {help !== undefined && <p className="help">{help}</p>}
      {error !== null && error !== undefined && (
        <p className="ui-error" id={`${id}-err`}>
          <Icon name="alert" small />
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}

const NOTE_NEEDED: readonly DialogName[] = [
  "NOT_A_REPAIR",
  "CLOSE_NOTE",
  "UNJOIN",
];

function StepDialog({
  language,
  propertyId,
  report,
  name,
  api,
  others,
  today,
  onClose,
  onDone,
  onStale,
}: {
  language: Language;
  propertyId: string;
  report: ProblemReport;
  name: Exclude<DialogName, "ANSWER">;
  api: ProblemsApi;
  others: ProblemReport[];
  today: string;
  onClose: () => void;
  onDone: (changed: ProblemReport) => void;
  onStale: () => void;
}) {
  const step: StepName = name === "REPLAN" ? "PLAN" : name;
  const [note, setNote] = useState("");
  const [how, setHow] = useState<"PHONE" | "VISIT" | "">("");
  const [technician, setTechnician] = useState(report.technician ?? "");
  const [day, setDay] = useState(report.visit_on ?? today);
  const [time, setTime] = useState(report.visit_at ?? "");
  const [cleaner, setCleaner] = useState("");
  const [cause, setCause] = useState<"WEAR" | "DAMAGE" | "UNSURE" | "">("");
  const [fixed, setFixed] = useState(false);
  const [pays, setPays] = useState<"OWNER" | "TENANT" | "">("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [mainId, setMainId] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const cents = centsFromText(amount);
  const errors: Record<string, string | null> = {
    note:
      NOTE_NEEDED.includes(name) && note.trim() === ""
        ? pt(language, "e_note")
        : null,
    how: step === "CONTACTED" && how === "" ? pt(language, "e_pick") : null,
    technician:
      step === "PLAN" && technician.trim() === ""
        ? pt(language, "e_tech")
        : null,
    day:
      step === "PLAN" && (day < today || day > addDays(today, 60) || day === "")
        ? pt(language, "e_day")
        : null,
    time: step === "PLAN" && time === "" ? pt(language, "e_time") : null,
    cleaner:
      step === "CLEANING" && cleaner.trim() === ""
        ? pt(language, "e_cleaner")
        : null,
    cause: step === "CHECKED" && cause === "" ? pt(language, "e_cause") : null,
    pays: step === "DECIDE" && pays === "" ? pt(language, "e_pays") : null,
    amount:
      step === "DECIDE" && pays === "TENANT" && (cents === null || cents < 1)
        ? pt(language, "e_amount")
        : null,
    reason:
      (step === "DECIDE" && pays === "TENANT") || step === "JOIN"
        ? reason.trim() === ""
          ? pt(language, "e_note")
          : null
        : null,
    main: step === "JOIN" && mainId === "" ? pt(language, "e_pick") : null,
  };
  const shown = (key: string) => (checked ? (errors[key] ?? null) : null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    setFailure(null);
    if (Object.values(errors).some((error) => error !== null)) return;
    const body: ProblemStep = { step };
    if (note.trim() !== "") body.note = note.trim();
    if (step === "CONTACTED" && how !== "") body.how = how;
    if (step === "PLAN") {
      body.technician = technician.trim();
      body.visit_on = day;
      body.visit_at = time;
    }
    if (step === "CLEANING") body.cleaner = cleaner.trim();
    if (step === "CHECKED" && cause !== "") {
      body.cause = cause;
      if (report.urgent) body.fixed = fixed;
    }
    if (step === "DECIDE" && pays !== "") {
      body.pays = pays;
      if (pays === "TENANT" && cents !== null) {
        body.amount_usd_cents = cents;
        body.reason = reason.trim();
      }
    }
    if (step === "JOIN") {
      body.main_id = mainId;
      body.reason = reason.trim();
    }
    setBusy(true);
    void api
      .step(propertyId, report, body)
      .then(onDone)
      .catch((error: unknown) => {
        setBusy(false);
        if (error instanceof ProblemsError && error.status === 412) {
          onStale();
          return;
        }
        setFailure(problemRefusal(language, error));
      });
  };

  const radios = <T extends string>(
    group: string,
    value: T | "",
    set: (value: T) => void,
    options: readonly [T, ProblemsTextKey][],
    legend: string,
    error: string | null,
  ) => (
    <fieldset className="ui-radios">
      <legend>{legend}</legend>
      {options.map(([option, key], index) => (
        <label className="ui-chk" key={option}>
          <input
            checked={value === option}
            disabled={busy}
            id={index === 0 ? `ps-${group}` : undefined}
            name={`ps-${group}`}
            onChange={() => {
              set(option);
            }}
            type="radio"
          />
          {pt(language, key)}
        </label>
      ))}
      {error !== null && (
        <p className="ui-error">
          <Icon name="alert" small />
          <span>{error}</span>
        </p>
      )}
    </fieldset>
  );

  const noteNeeded = NOTE_NEEDED.includes(name);
  const noteLabel =
    name === "NOT_A_REPAIR"
      ? pt(language, "why_tenant")
      : name === "UNJOIN"
        ? pt(language, "join_why")
        : step === "CHECKED"
          ? pt(language, "tech_note")
          : noteNeeded
            ? pt(language, "note")
            : pt(language, "note_opt");

  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={pt(
        language,
        "t_step",
        pt(language, `s_${name}` as ProblemsTextKey),
        report.report_number,
      )}
    >
      {step === "CONTACTED" &&
        radios(
          "how",
          how,
          setHow,
          [
            ["PHONE", "con_PHONE"],
            ["VISIT", "con_VISIT"],
          ],
          pt(language, "con_how"),
          shown("how"),
        )}
      {step === "PLAN" && (
        <>
          <Field
            error={shown("technician")}
            help={pt(language, "tech_h")}
            id="ps-tech"
            label={pt(language, "tech")}
            required
          >
            <input
              aria-invalid={shown("technician") !== null}
              autoComplete="off"
              disabled={busy}
              id="ps-tech"
              maxLength={120}
              onChange={(event) => {
                setTechnician(event.currentTarget.value);
              }}
              value={technician}
            />
          </Field>
          <div className="ui-row2">
            <Field
              error={shown("day")}
              id="ps-day"
              label={pt(language, "day")}
              required
            >
              <DateInput
                id="ps-day"
                invalid={shown("day") !== null}
                language={language}
                max={addDays(today, 60)}
                min={today}
                onChange={setDay}
                value={day}
              />
            </Field>
            <Field
              error={shown("time")}
              id="ps-time"
              label={pt(language, "time")}
              required
            >
              <select
                aria-invalid={shown("time") !== null}
                className="ui-sel"
                disabled={busy}
                id="ps-time"
                onChange={(event) => {
                  setTime(event.currentTarget.value);
                }}
                value={time}
              >
                <option value="">{pt(language, "time_pick")}</option>
                {VISIT_TIMES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {report.kind === "UNIT" && (
            <p className="ui-muted ui-small">
              {pt(language, "best_hint", pt(language, `b_${report.best_time}`))}
            </p>
          )}
        </>
      )}
      {step === "CLEANING" && (
        <>
          <p className="ui-muted">{pt(language, "clean_n")}</p>
          <Field
            error={shown("cleaner")}
            id="ps-cleaner"
            label={pt(language, "cleaner")}
            required
          >
            <input
              aria-invalid={shown("cleaner") !== null}
              autoComplete="off"
              disabled={busy}
              id="ps-cleaner"
              maxLength={120}
              onChange={(event) => {
                setCleaner(event.currentTarget.value);
              }}
              value={cleaner}
            />
          </Field>
        </>
      )}
      {step === "CHECKED" && (
        <>
          {radios(
            "cause",
            cause,
            setCause,
            [
              ["WEAR", "cause_WEAR"],
              ["DAMAGE", "cause_DAMAGE"],
              ["UNSURE", "cause_UNSURE"],
            ],
            pt(language, "cause"),
            shown("cause"),
          )}
          {cause === "UNSURE" && (
            <p className="ui-muted ui-small">{pt(language, "unsure_n")}</p>
          )}
          {report.urgent && (
            <label className="ui-chk">
              <input
                checked={fixed}
                disabled={busy}
                onChange={(event) => {
                  setFixed(event.currentTarget.checked);
                }}
                type="checkbox"
              />
              {pt(language, "fixed_q")}
            </label>
          )}
        </>
      )}
      {step === "DECIDE" && (
        <>
          {radios(
            "pays",
            pays,
            setPays,
            report.lease_id === null
              ? [["OWNER", "pays_OWNER"]]
              : [
                  ["OWNER", "pays_OWNER"],
                  ["TENANT", "pays_TENANT"],
                ],
            pt(language, "pays"),
            shown("pays"),
          )}
          {report.lease_id === null && (
            <p className="ui-muted ui-small">
              {pt(language, "tenant_no_lease")}
            </p>
          )}
          {pays === "TENANT" && (
            <>
              <Field
                error={shown("amount")}
                help={pt(language, "amount_h")}
                id="ps-amount"
                label={pt(language, "amount")}
                required
              >
                <input
                  aria-invalid={shown("amount") !== null}
                  autoComplete="off"
                  disabled={busy}
                  id="ps-amount"
                  inputMode="decimal"
                  onChange={(event) => {
                    setAmount(event.currentTarget.value);
                  }}
                  value={amount}
                />
              </Field>
              <Field
                error={shown("reason")}
                id="ps-reason"
                label={pt(language, "why_tenant")}
                required
              >
                <input
                  aria-invalid={shown("reason") !== null}
                  autoComplete="off"
                  disabled={busy}
                  id="ps-reason"
                  maxLength={500}
                  onChange={(event) => {
                    setReason(event.currentTarget.value);
                  }}
                  value={reason}
                />
              </Field>
            </>
          )}
        </>
      )}
      {step === "JOIN" && (
        <>
          <Field
            error={shown("main")}
            id="ps-main"
            label={pt(language, "join_main")}
            required
          >
            <select
              aria-invalid={shown("main") !== null}
              className="ui-sel"
              disabled={busy}
              id="ps-main"
              onChange={(event) => {
                setMainId(event.currentTarget.value);
              }}
              value={mainId}
            >
              <option value="">{pt(language, "join_pick")}</option>
              {others.map((other) => (
                <option key={other.report_id} value={other.report_id}>
                  {other.report_number} ·{" "}
                  {typeName(language, other.problem_type)} ·{" "}
                  {whereText(language, other)}
                </option>
              ))}
            </select>
          </Field>
          {others.length === 0 && (
            <p className="ui-muted ui-small">{pt(language, "join_none")}</p>
          )}
          <Field
            error={shown("reason")}
            id="ps-reason"
            label={pt(language, "join_why")}
            required
          >
            <input
              aria-invalid={shown("reason") !== null}
              autoComplete="off"
              disabled={busy}
              id="ps-reason"
              maxLength={500}
              onChange={(event) => {
                setReason(event.currentTarget.value);
              }}
              value={reason}
            />
          </Field>
        </>
      )}
      {step !== "JOIN" && (
        <Field
          error={shown("note")}
          help={noteNeeded ? pt(language, "note_h") : undefined}
          id="ps-note"
          label={noteLabel}
          required={noteNeeded}
        >
          <textarea
            aria-invalid={shown("note") !== null}
            disabled={busy}
            id="ps-note"
            maxLength={500}
            onChange={(event) => {
              setNote(event.currentTarget.value);
            }}
            rows={2}
            value={note}
          />
        </Field>
      )}
      {failure !== null && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <p>{failure}</p>
        </div>
      )}
    </Dialog>
  );
}

function AnswerDialog({
  language,
  propertyId,
  report,
  api,
  today,
  onClose,
  onDone,
}: {
  language: Language;
  propertyId: string;
  report: ProblemReport;
  api: ProblemsApi;
  today: string;
  onClose: () => void;
  onDone: (changed: ProblemReport) => void;
}) {
  const [answer, setAnswer] = useState<"AGREED" | "REFUSED" | "">("");
  const [how, setHow] = useState<TenantAnswer["how"] | "">("");
  const [day, setDay] = useState(today);
  const [said, setSaid] = useState("");
  const [after, setAfter] = useState<"OWNER_PAYS" | "MOVE_OUT" | "">("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const amount = usdFromCents(report.tenant_amount_usd_cents ?? 0);
  const from = report.decided_on ?? today;
  const errors = {
    answer: answer === "" ? pt(language, "e_pick") : null,
    how: how === "" ? pt(language, "e_pick") : null,
    day: day === "" || day < from || day > today ? pt(language, "e_day") : null,
    said:
      answer === "REFUSED" && said.trim() === ""
        ? pt(language, "e_note")
        : null,
    after: answer === "REFUSED" && after === "" ? pt(language, "e_pick") : null,
  };
  const shown = (key: keyof typeof errors) => (checked ? errors[key] : null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    setFailure(null);
    if (Object.values(errors).some((error) => error !== null)) return;
    if (answer === "" || how === "") return;
    setBusy(true);
    void api
      .answer(propertyId, report, {
        answer,
        how,
        answered_on: day,
        said: said.trim() === "" ? null : said.trim(),
        after_refusal: answer === "REFUSED" && after !== "" ? after : null,
      })
      .then(onDone)
      .catch((error: unknown) => {
        setBusy(false);
        setFailure(problemRefusal(language, error));
      });
  };

  const group = <T extends string>(
    name: string,
    value: T | "",
    set: (value: T) => void,
    options: readonly [T, ProblemsTextKey][],
    legend: string,
    error: string | null,
  ) => (
    <fieldset className="ui-radios">
      <legend>{legend}</legend>
      {options.map(([option, key]) => (
        <label className="ui-chk" key={option}>
          <input
            checked={value === option}
            disabled={busy}
            name={`pa-${name}`}
            onChange={() => {
              set(option);
            }}
            type="radio"
          />
          {pt(language, key)}
        </label>
      ))}
      {error !== null && (
        <p className="ui-error">
          <Icon name="alert" small />
          <span>{error}</span>
        </p>
      )}
    </fieldset>
  );

  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={pt(language, "ans_t", report.report_number)}
    >
      {group(
        "answer",
        answer,
        setAnswer,
        [
          ["AGREED", "ans_AGREED"],
          ["REFUSED", "ans_REFUSED"],
        ],
        pt(language, "ans_q", amount),
        shown("answer"),
      )}
      {group(
        "how",
        how,
        setHow,
        [
          ["SIGNED", "how_SIGNED"],
          ["TELEGRAM", "how_TELEGRAM"],
          ["PHONE", "how_PHONE"],
          ["IN_PERSON", "how_IN_PERSON"],
        ],
        pt(language, "ans_how"),
        shown("how"),
      )}
      <Field
        error={shown("day")}
        id="pa-day"
        label={pt(language, "ans_on")}
        required
      >
        <DateInput
          id="pa-day"
          invalid={shown("day") !== null}
          language={language}
          max={today}
          min={from}
          onChange={setDay}
          value={day}
        />
      </Field>
      {answer === "AGREED" && (
        <div className="ui-notice" role="note">
          <Icon name="invoice" />
          <p>{pt(language, "ans_agree_n", amount)}</p>
        </div>
      )}
      <Field
        error={shown("said")}
        id="pa-said"
        label={pt(language, "ans_said")}
        required={answer === "REFUSED"}
      >
        <textarea
          aria-invalid={shown("said") !== null}
          disabled={busy}
          id="pa-said"
          maxLength={500}
          onChange={(event) => {
            setSaid(event.currentTarget.value);
          }}
          rows={2}
          value={said}
        />
      </Field>
      {answer === "REFUSED" &&
        group(
          "after",
          after,
          setAfter,
          [
            ["OWNER_PAYS", "after_OWNER_PAYS"],
            ["MOVE_OUT", "after_MOVE_OUT"],
          ],
          pt(language, "ans_next"),
          shown("after"),
        )}
      {failure !== null && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <p>{failure}</p>
        </div>
      )}
    </Dialog>
  );
}
