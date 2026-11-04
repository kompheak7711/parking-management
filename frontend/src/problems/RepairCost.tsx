// DL-130 (mock-up round 32, A5): the Repair cost box of one Problem report. Staff type what the
// repair cost (parts and outside workers, in dollars or riel; own staff are paid by payroll), or
// No cost. A Manager ("Check repair costs") checks it with the receipt; the server then makes
// one Expense report (money already spent) per currency, which follows the normal Expense
// approval. The server checks every right, state and amount.

import { type FormEvent, useState } from "react";

import { centsFromText } from "../products/productsClient";
import { DateInput } from "../shell/DateInput";
import { momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { problemRefusal } from "./NewProblemReport";
import type {
  CostCurrency,
  CostLine,
  ProblemReport,
  ProblemsApi,
  RepairCost,
} from "./problemsClient";
import { pt, type ProblemsTextKey } from "./text";

/** Riel as typed: whole riel, 1 to 12 digits; commas and spaces are allowed. */
export function rielFromText(typed: string): number | null {
  const value = typed.trim().replace(/[,\s]/g, "");
  if (!/^\d{1,12}$/.test(value)) return null;
  const riel = Number(value);
  return riel > 0 ? riel : null;
}

export function costText(currency: CostCurrency, minor: number): string {
  return currency === "USD"
    ? usdFromCents(minor)
    : `${minor.toLocaleString("en-US")} ៛`;
}

/** The box shows from Repair planned on, or once a cost was typed. */
export function showsCost(report: ProblemReport): boolean {
  return (
    report.cost !== null ||
    ["REPAIR_PLANNED", "WAITING_PARTS", "DONE"].includes(report.state) ||
    (report.state === "CLOSED" && report.done_at !== null)
  );
}

export function RepairCostCard({
  language,
  report,
  mayAdd,
  mayCheck,
  onEnter,
  onCheck,
}: {
  language: Language;
  report: ProblemReport;
  mayAdd: boolean;
  mayCheck: boolean;
  onEnter: () => void;
  onCheck: () => void;
}) {
  const cost: RepairCost | null = report.cost;
  const open = cost === null || cost.can_enter;
  const waiting =
    cost !== null &&
    !cost.no_cost &&
    cost.check === null &&
    cost.lines.length > 0;
  const refused =
    cost?.check != null && cost.can_enter && cost.expense_requests.length > 0;
  return (
    <section aria-labelledby="pr-cost" className="ui-card">
      <h2 id="pr-cost">{pt(language, "cost_h")}</h2>
      {cost === null ? (
        <p className="ui-muted">{pt(language, "cost_none")}</p>
      ) : cost.no_cost ? (
        <p>{pt(language, "cost_no_cost")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{pt(language, "cd_kind")}</th>
                <th scope="col">{pt(language, "cd_what")}</th>
                <th className="num" scope="col">
                  {pt(language, "cd_amount")}
                </th>
              </tr>
            </thead>
            <tbody>
              {cost.lines.map((line, index) => (
                <tr key={index}>
                  <td>{pt(language, `kind_${line.kind}`)}</td>
                  <td>{line.description}</td>
                  <td className="num ui-num">
                    {costText(line.currency, line.amount_minor)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              {cost.totals.map((total) => (
                <tr key={total.currency}>
                  <th colSpan={2} scope="row">
                    {pt(language, "cost_total")} ·{" "}
                    {pt(language, `cur_${total.currency}`)}
                  </th>
                  <td className="num ui-num">
                    {costText(total.currency, total.amount_minor)}
                  </td>
                </tr>
              ))}
            </tfoot>
          </table>
        </div>
      )}
      {cost !== null && (
        <p className="ui-muted ui-small">
          {pt(
            language,
            "cost_by",
            cost.entered_by_name ?? "—",
            momentText(cost.entered_at),
          )}
          {cost.note !== null && ` · ${cost.note}`}
        </p>
      )}
      {waiting && <p>{pt(language, "cost_wait")}</p>}
      {cost?.check != null && (
        <>
          <p>
            <Icon name="check" small />{" "}
            {pt(
              language,
              "cost_checked",
              cost.check.checked_by_name ?? "—",
              momentText(cost.check.checked_at),
            )}
          </p>
          <ul className="ui-plain">
            {cost.expense_requests.map((made) => (
              <li key={made.request_number}>
                <a
                  className="ui-num"
                  href={hashForPage("exreqs", made.request_number)}
                >
                  {made.request_number}
                </a>{" "}
                · {usdFromCents(made.amount_cents)}
                {made.original_amount_minor !== null &&
                  ` (${costText("KHR", made.original_amount_minor)})`}{" "}
                · {pt(language, `est_${made.status}` as ProblemsTextKey)}
              </li>
            ))}
          </ul>
        </>
      )}
      {refused && (
        <p className="ui-muted ui-small">{pt(language, "cost_refused")}</p>
      )}
      {report.pays === "TENANT" && cost !== null && (
        <p className="ui-muted ui-small">{pt(language, "cost_compare")}</p>
      )}
      {((mayAdd && open) || (mayCheck && waiting)) && (
        <div className="ui-actions">
          {mayCheck && waiting && (
            <button className="ui-btn primary" onClick={onCheck} type="button">
              {pt(language, "cost_check")}
            </button>
          )}
          {mayAdd && open && (
            <button
              className={waiting ? "ui-btn" : "ui-btn primary"}
              onClick={onEnter}
              type="button"
            >
              {pt(language, cost === null ? "cost_enter" : "cost_again")}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

interface TypedLine {
  kind: CostLine["kind"] | "";
  description: string;
  currency: CostCurrency;
  amount: string;
}

const EMPTY_LINE: TypedLine = {
  kind: "",
  description: "",
  currency: "USD",
  amount: "",
};

function amountOf(line: TypedLine): number | null {
  return line.currency === "USD"
    ? (() => {
        const cents = centsFromText(line.amount);
        return cents !== null && cents > 0 ? cents : null;
      })()
    : rielFromText(line.amount);
}

export function CostDialog({
  language,
  propertyId,
  report,
  api,
  onClose,
  onDone,
}: {
  language: Language;
  propertyId: string;
  report: ProblemReport;
  api: ProblemsApi;
  onClose: () => void;
  onDone: (changed: ProblemReport) => void;
}) {
  const [noCost, setNoCost] = useState(false);
  const [lines, setLines] = useState<TypedLine[]>([{ ...EMPTY_LINE }]);
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const lineErrors = lines.map((line) => ({
    kind: line.kind === "" ? pt(language, "e_pick") : null,
    description: line.description.trim() === "" ? pt(language, "e_note") : null,
    amount:
      amountOf(line) === null
        ? pt(
            language,
            line.currency === "USD" ? "e_amount_usd" : "e_amount_khr",
          )
        : null,
  }));
  const noLines = !noCost && lines.length === 0;
  const hasError =
    noLines ||
    (!noCost &&
      lineErrors.some((errors) =>
        Object.values(errors).some((error) => error !== null),
      ));
  const change = (index: number, patch: Partial<TypedLine>) => {
    setLines((old) =>
      old.map((line, at) => (at === index ? { ...line, ...patch } : line)),
    );
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    setFailure(null);
    if (hasError) return;
    const sent: CostLine[] = noCost
      ? []
      : lines.map((line) => ({
          kind: line.kind === "" ? "PARTS" : line.kind,
          description: line.description.trim(),
          currency: line.currency,
          amount_minor: amountOf(line) ?? 0,
        }));
    setBusy(true);
    void api
      .cost(propertyId, report, {
        no_cost: noCost,
        lines: sent,
        ...(note.trim() === "" ? {} : { note: note.trim() }),
      })
      .then(onDone)
      .catch((error: unknown) => {
        setBusy(false);
        setFailure(problemRefusal(language, error));
      });
  };

  const error = (text: string | null, id: string) =>
    checked && text !== null ? (
      <p className="ui-error" id={id}>
        <Icon name="alert" small />
        <span>{text}</span>
      </p>
    ) : null;

  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={pt(language, "cd_t", report.report_number)}
      wide
    >
      <label className="ui-chk">
        <input
          checked={noCost}
          disabled={busy}
          onChange={(event) => {
            setNoCost(event.currentTarget.checked);
          }}
          type="checkbox"
        />
        {pt(language, "cd_no_cost")}
      </label>
      {!noCost && (
        <>
          {lines.map((line, index) => {
            const errors = lineErrors[index];
            const n = String(index + 1);
            return (
              <fieldset className="ui-radios" key={index}>
                <legend>{pt(language, "cd_line", n)}</legend>
                <div className="ui-row2">
                  <div className="ui-field">
                    <label htmlFor={`pc-kind-${n}`}>
                      {pt(language, "cd_kind")}
                    </label>
                    <select
                      aria-invalid={checked && errors?.kind != null}
                      className="ui-sel"
                      disabled={busy}
                      id={`pc-kind-${n}`}
                      onChange={(event) => {
                        change(index, {
                          kind: event.currentTarget.value as TypedLine["kind"],
                        });
                      }}
                      value={line.kind}
                    >
                      <option value="">—</option>
                      <option value="PARTS">
                        {pt(language, "kind_PARTS")}
                      </option>
                      <option value="OUTSIDE_WORKER">
                        {pt(language, "kind_OUTSIDE_WORKER")}
                      </option>
                    </select>
                    {error(errors?.kind ?? null, `pc-kind-${n}-err`)}
                  </div>
                  <div className="ui-field">
                    <label htmlFor={`pc-what-${n}`}>
                      {pt(language, "cd_what")}
                    </label>
                    <input
                      aria-invalid={checked && errors?.description != null}
                      autoComplete="off"
                      disabled={busy}
                      id={`pc-what-${n}`}
                      maxLength={200}
                      onChange={(event) => {
                        change(index, {
                          description: event.currentTarget.value,
                        });
                      }}
                      value={line.description}
                    />
                    {error(errors?.description ?? null, `pc-what-${n}-err`)}
                  </div>
                </div>
                <div className="ui-row2">
                  <div className="ui-field">
                    <label htmlFor={`pc-cur-${n}`}>
                      {pt(language, "cd_cur")}
                    </label>
                    <select
                      className="ui-sel"
                      disabled={busy}
                      id={`pc-cur-${n}`}
                      onChange={(event) => {
                        change(index, {
                          currency: event.currentTarget.value as CostCurrency,
                        });
                      }}
                      value={line.currency}
                    >
                      <option value="USD">{pt(language, "cur_USD")}</option>
                      <option value="KHR">{pt(language, "cur_KHR")}</option>
                    </select>
                  </div>
                  <div className="ui-field">
                    <label htmlFor={`pc-amt-${n}`}>
                      {pt(language, "cd_amount")}
                    </label>
                    <input
                      aria-invalid={checked && errors?.amount != null}
                      autoComplete="off"
                      className="ui-num"
                      disabled={busy}
                      id={`pc-amt-${n}`}
                      inputMode={
                        line.currency === "USD" ? "decimal" : "numeric"
                      }
                      onChange={(event) => {
                        change(index, { amount: event.currentTarget.value });
                      }}
                      value={line.amount}
                    />
                    {error(errors?.amount ?? null, `pc-amt-${n}-err`)}
                  </div>
                </div>
                {lines.length > 1 && (
                  <button
                    className="ui-btn"
                    disabled={busy}
                    onClick={() => {
                      setLines((old) => old.filter((_, at) => at !== index));
                    }}
                    type="button"
                  >
                    {pt(language, "cd_remove", n)}
                  </button>
                )}
              </fieldset>
            );
          })}
          {lines.length < 20 && (
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                setLines((old) => [...old, { ...EMPTY_LINE }]);
              }}
              type="button"
            >
              {pt(language, "cd_add")}
            </button>
          )}
          {error(noLines ? pt(language, "e_lines") : null, "pc-lines-err")}
          <div className="ui-notice" role="note">
            <Icon name="invoice" />
            <p>{pt(language, "cd_receipt")}</p>
          </div>
        </>
      )}
      <div className="ui-field">
        <label htmlFor="pc-note">{pt(language, "note")}</label>
        <textarea
          disabled={busy}
          id="pc-note"
          maxLength={500}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
          rows={2}
          value={note}
        />
      </div>
      {failure !== null && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <p>{failure}</p>
        </div>
      )}
    </Dialog>
  );
}

export function CostCheckDialog({
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
  const [paid, setPaid] = useState<"OWN_MONEY" | "CASH" | "">("");
  const [day, setDay] = useState(today);
  const [receipt, setReceipt] = useState(false);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const totals = report.cost?.totals ?? [];
  const errors = {
    paid: paid === "" ? pt(language, "e_pick") : null,
    day: day === "" || day > today ? pt(language, "e_day") : null,
    receipt: receipt ? null : pt(language, "e_receipt"),
  };
  const shown = (key: keyof typeof errors) => (checked ? errors[key] : null);
  const place = report.unit_number ?? pt(language, "k_BUILDING");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    setFailure(null);
    if (Object.values(errors).some((error) => error !== null) || paid === "")
      return;
    setBusy(true);
    void api
      .checkCost(propertyId, report, {
        receipt_seen: true,
        spent_on: day,
        paid_how: paid,
        ...(paid === "CASH" ? { paid_from_code: "1030" } : {}),
      })
      .then(onDone)
      .catch((error: unknown) => {
        setBusy(false);
        setFailure(problemRefusal(language, error));
      });
  };

  const alert = (text: string | null) =>
    text === null ? null : (
      <p className="ui-error">
        <Icon name="alert" small />
        <span>{text}</span>
      </p>
    );

  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={pt(language, "cost_check")}
      title={pt(language, "ck_t", report.report_number)}
    >
      <dl className="ui-kv">
        {totals.map((total) => (
          <div key={total.currency}>
            <dt>
              {pt(language, "cost_total")} ·{" "}
              {pt(language, `cur_${total.currency}`)}
            </dt>
            <dd className="ui-num">
              {costText(total.currency, total.amount_minor)}
            </dd>
          </div>
        ))}
      </dl>
      <div className="ui-notice" role="note">
        <Icon name="invoice" />
        <p>
          {pt(language, "ck_makes", place)}
          {totals.some((total) => total.currency === "KHR") &&
            ` ${pt(language, "ck_rate")}`}
        </p>
      </div>
      <fieldset className="ui-radios">
        <legend>{pt(language, "ck_paid")}</legend>
        {(["OWN_MONEY", "CASH"] as const).map((option) => (
          <label className="ui-chk" key={option}>
            <input
              checked={paid === option}
              disabled={busy}
              name="pk-paid"
              onChange={() => {
                setPaid(option);
              }}
              type="radio"
            />
            {pt(language, `ck_${option}`)}
          </label>
        ))}
        {alert(shown("paid"))}
      </fieldset>
      <div className="ui-field">
        <label htmlFor="pk-day">
          {pt(language, "ck_day")}
          <span className="req">{"*"}</span>
        </label>
        <DateInput
          id="pk-day"
          invalid={shown("day") !== null}
          language={language}
          max={today}
          onChange={setDay}
          value={day}
        />
        {alert(shown("day"))}
      </div>
      <label className="ui-chk">
        <input
          aria-invalid={shown("receipt") !== null}
          checked={receipt}
          disabled={busy}
          onChange={(event) => {
            setReceipt(event.currentTarget.checked);
          }}
          type="checkbox"
        />
        {pt(language, "ck_receipt")}
      </label>
      {alert(shown("receipt"))}
      {failure !== null && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <p>{failure}</p>
        </div>
      )}
    </Dialog>
  );
}
