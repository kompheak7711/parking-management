// V1-058 R3: Record letter and Record warning (DESIGN.md "Letters (round 8)"). Each request
// keeps one identity (idempotency key) while its values stay the same, so "Try again" after an
// unknown result sends the very same request and the server records it once.

import { FormEvent, useEffect, useRef, useState } from "react";

import type { LeaseResource } from "../leaseClient";
import { DateInput } from "../shell/DateInput";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  LettersConflictError,
  LettersUnavailableError,
  type LettersApi,
} from "./lettersClient";
import {
  HOWS,
  type How,
  type RentRow,
  howRecord,
  letterDay,
  nextLetter,
  warnable,
} from "./lettersData";
import { ltr, monthText, storedText } from "./text";

type Outcome = "unknown" | "refused" | null;

function Problem({ message }: { message: string | undefined }) {
  if (message === undefined) return null;
  return (
    <p className="ui-error" role="alert">
      <Icon name="alert" small />
      <span>{message}</span>
    </p>
  );
}

function OutcomeNotice({
  language,
  outcome,
}: {
  language: Language;
  outcome: Outcome;
}) {
  if (outcome === null) return null;
  return (
    <div className="ui-notice warn" role="alert">
      <Icon name="alert" />
      <p>{ltr(language, outcome)}</p>
    </div>
  );
}

/** A new idempotency key whenever the values change; the same one while they stay. */
export function useValuesKey() {
  const kept = useRef<{ fingerprint: string; key: string } | null>(null);
  return (fingerprint: string): string => {
    if (kept.current?.fingerprint !== fingerprint)
      kept.current = { fingerprint, key: crypto.randomUUID() };
    return kept.current.key;
  };
}

/** Sends a request and sorts its ending: saved, changed meanwhile, unknown, refused. */
export function useLettersSend(onSaved: () => void, onConflict: () => void) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  function send(request: () => Promise<unknown>) {
    setBusy(true);
    setOutcome(null);
    void request()
      .then(onSaved)
      .catch((error: unknown) => {
        if (error instanceof LettersConflictError) {
          onConflict();
          return;
        }
        setOutcome(
          error instanceof LettersUnavailableError ? "unknown" : "refused",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }
  return { busy, outcome, send };
}

export function HowSelect({
  id,
  language,
  value,
  invalid,
  onChange,
}: {
  id: string;
  language: Language;
  value: How | "";
  invalid: boolean;
  onChange: (value: How | "") => void;
}) {
  return (
    <select
      aria-invalid={invalid}
      id={id}
      onChange={(event) => {
        const chosen = HOWS.find((how) => how === event.currentTarget.value);
        onChange(chosen ?? "");
      }}
      value={value}
    >
      <option value="">—</option>
      {HOWS.map((how) => (
        <option key={how} value={how}>
          {ltr(language, `h_${how}`)}
        </option>
      ))}
    </select>
  );
}

const LETTER_REASON = {
  20: "Day-20 warning letter given",
  30: "Day-30 default notice given",
} as const;
const CASE_REASON = "Rent letter";
const WARNING_REASON = "Lease rule warning given";

export function RecordLetterDialog({
  language,
  api,
  row,
  unit,
  businessDate,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: Pick<LettersApi, "openCase" | "recordLetter">;
  row: RentRow;
  unit: string;
  businessDate: string;
  /** openedCase: this dialog opened the case, so the page must read it again. */
  onClose: (openedCase: boolean) => void;
  onSaved: (message: string) => void;
  onConflict: () => void;
}) {
  const a = row.alert.assessment;
  const [which, setWhich] = useState<20 | 30 | null>(nextLetter(row));
  const [how, setHow] = useState<How | "">("");
  const [details, setDetails] = useState("");
  const [number, setNumber] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  // The case is opened once; a retry after an unknown result reuses its key.
  const caseId = useRef<string | null>(row.alert.case_id);
  const caseKey = useRef(crypto.randomUUID());
  const letterKey = useValuesKey();
  const name = (n: 20 | 30) => ltr(language, n === 20 ? "d_20" : "d_30");
  const { busy, outcome, send } = useLettersSend(() => {
    if (which !== null) onSaved(ltr(language, "d_toast", name(which), unit));
  }, onConflict);

  const option = (n: 20 | 30) => {
    const given = n === 20 ? a.warning_recorded : a.serious_default_recorded;
    const due =
      n === 20 ? a.twenty_day_warning_eligible : a.thirty_day_default_eligible;
    const event = n === 20 ? row.letters?.d20 : row.letters?.d30;
    return (
      <label className="ui-chk" key={n}>
        <input
          checked={which === n}
          disabled={given || !due}
          name="letter-which"
          onChange={() => {
            setWhich(n);
          }}
          type="radio"
        />
        <span>
          {name(n)}
          <small className="ui-sub2">
            {given
              ? `${ltr(language, "given", dayText(event?.event_date ?? null))} · ${ltr(language, "d_given")}`
              : ltr(language, "on", dayText(letterDay(row.monthStart, n)))}
          </small>
        </span>
      </label>
    );
  };

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const detail = details.trim();
    const reference = number.trim();
    const found: Record<string, string> = {};
    if (which === null) found.which = ltr(language, "d_which_e");
    if (how === "") found.how = ltr(language, "d_how_e");
    if (detail === "") found.details = ltr(language, "d_detail_e");
    if (which === 20 && reference === "")
      found.number = ltr(language, "d_no_e");
    setProblems(found);
    if (which === null || how === "" || Object.keys(found).length > 0) return;
    const source = {
      event_kind:
        which === 20
          ? ("TWENTY_DAY_WARNING" as const)
          : ("THIRTY_DAY_SERIOUS_DEFAULT" as const),
      reason: LETTER_REASON[which],
      communication_record: howRecord(how, detail),
      ...(reference === "" ? {} : { notice_document_reference: reference }),
    };
    const key = letterKey(JSON.stringify(source));
    send(async () => {
      if (caseId.current === null) {
        const opened = await api.openCase(
          row.alert.lease_id,
          {
            rent_invoice_line_id: row.alert.rent_invoice_line_id,
            reason: CASE_REASON,
          },
          caseKey.current,
        );
        caseId.current = opened.id;
      }
      return api.recordLetter(caseId.current, source, key);
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={ltr(language, "close")}
      onClose={() => {
        onClose(caseId.current !== row.alert.case_id);
      }}
      onSubmit={submit}
      submitLabel={
        busy
          ? ltr(language, "saving")
          : outcome === "unknown"
            ? ltr(language, "try_again")
            : ltr(language, "d_save")
      }
      title={ltr(language, "d_t", unit)}
    >
      <dl className="ui-kv">
        <dt>{ltr(language, "customer")}</dt>
        <dd>{row.lease?.primary_tenant_name ?? "—"}</dd>
        <dt>{ltr(language, "col_month")}</dt>
        <dd>{monthText(language, row.monthStart)}</dd>
        <dt>{ltr(language, "d_owed")}</dt>
        <dd className="ui-num">{usdFromCents(a.remaining_rent.minor_units)}</dd>
      </dl>
      <p className="ui-small ui-muted">
        {ltr(language, "d_owed_note", dayText(row.monthStart))}
      </p>
      <fieldset className="ui-radios">
        <legend>{ltr(language, "d_which")}</legend>
        {option(20)}
        {option(30)}
        <Problem message={problems.which} />
      </fieldset>
      <div className="ui-field">
        <span className="ui-label">{ltr(language, "d_date")}</span>
        <p className="ui-small">
          {ltr(language, "d_date_today", dayText(businessDate))}
        </p>
      </div>
      <div className="ui-field">
        <label htmlFor="letter-how">
          {ltr(language, "d_how")}
          <span className="req">{ltr(language, "required")}</span>
        </label>
        <HowSelect
          id="letter-how"
          invalid={problems.how !== undefined}
          language={language}
          onChange={setHow}
          value={how}
        />
        <Problem message={problems.how} />
      </div>
      <div className="ui-field">
        <label htmlFor="letter-details">
          {ltr(language, "d_detail")}
          <span className="req">{ltr(language, "required")}</span>
        </label>
        <input
          aria-invalid={problems.details !== undefined}
          autoComplete="off"
          id="letter-details"
          maxLength={1900}
          onChange={(event) => {
            setDetails(event.currentTarget.value);
          }}
          value={details}
        />
        <p className="help">{ltr(language, "d_detail_h")}</p>
        <Problem message={problems.details} />
      </div>
      <div className="ui-field">
        <label htmlFor="letter-number">
          {ltr(language, "d_no")}
          <span className="req">
            {ltr(language, which === 30 ? "optional" : "required")}
          </span>
        </label>
        <input
          aria-invalid={problems.number !== undefined}
          autoComplete="off"
          id="letter-number"
          maxLength={500}
          onChange={(event) => {
            setNumber(event.currentTarget.value);
          }}
          placeholder={ltr(language, "d_no_ph")}
          value={number}
        />
        <Problem message={problems.number} />
      </div>
      <p className="ui-small ui-muted">{ltr(language, "nothing")}</p>
      <OutcomeNotice language={language} outcome={outcome} />
    </Dialog>
  );
}

export function RecordWarningDialog({
  language,
  api,
  leases,
  counts,
  leaseId,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: Pick<LettersApi, "warningContext" | "recordWarning">;
  leases: LeaseResource[];
  counts: ReadonlyMap<string, number>;
  leaseId: string | null;
  onClose: () => void;
  onSaved: (message: string) => void;
  onConflict: () => void;
}) {
  const today = todayInPhnomPenh();
  const live = leases
    .filter((lease) => warnable(lease, today))
    .sort((x, y) => x.unit_number.localeCompare(y.unit_number));
  const [chosen, setChosen] = useState(
    live.find((lease) => lease.lease_id === leaseId)?.lease_id ??
      live[0]?.lease_id ??
      "",
  );
  const [context, setContext] = useState<
    | { state: "loading" }
    | { state: "done"; leaseId: string; sequence: number | null }
    | { state: "failed" }
  >({ state: "loading" });
  const [breach, setBreach] = useState(today);
  const [given, setGiven] = useState(today);
  const [what, setWhat] = useState("");
  const [article, setArticle] = useState("");
  const [how, setHow] = useState<How | "">("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const warningKey = useValuesKey();
  const lease = live.find((item) => item.lease_id === chosen);
  const sequence =
    context.state === "done" && context.leaseId === chosen
      ? context.sequence
      : null;
  const { busy, outcome, send } = useLettersSend(() => {
    if (lease !== undefined && sequence !== null)
      onSaved(ltr(language, "lw_toast", sequence, lease.unit_number));
  }, onConflict);

  // The next warning number comes from the server for the chosen Lease.
  useEffect(() => {
    if (chosen === "") return;
    const alive = { current: true };
    setContext({ state: "loading" });
    api
      .warningContext(chosen)
      .then((found) => {
        if (alive.current)
          setContext({
            state: "done",
            leaseId: chosen,
            sequence: found.suggested_sequence,
          });
      })
      .catch(() => {
        if (alive.current) setContext({ state: "failed" });
      });
    return () => {
      alive.current = false;
    };
  }, [api, chosen]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || lease === undefined || sequence === null) return;
    const description = what.trim();
    const provision = article.trim();
    const found: Record<string, string> = {};
    if (breach === "" || given === "" || breach > given || given > today)
      found.dates = ltr(language, "lw_d_date_e");
    if (description === "") found.what = ltr(language, "lw_d_what_e");
    if (provision === "") found.article = ltr(language, "lw_d_clause_e");
    if (how === "") found.how = ltr(language, "d_how_e");
    setProblems(found);
    if (how === "" || Object.keys(found).length > 0) return;
    const source = {
      warning_sequence: sequence,
      violation_date: breach,
      warning_date: given,
      violation_description: description,
      lease_provision: provision,
      communication_record: storedText(`h_${how}`),
      reason: WARNING_REASON,
    };
    const key = warningKey(`${lease.lease_id}:${JSON.stringify(source)}`);
    send(() => api.recordWarning(lease.lease_id, source, key));
  }

  const number = sequence ?? (counts.get(chosen) ?? 0) + 1;
  return (
    <Dialog
      busy={busy}
      closeLabel={ltr(language, "close")}
      onClose={onClose}
      onSubmit={live.length === 0 ? undefined : submit}
      submitLabel={
        busy
          ? ltr(language, "saving")
          : outcome === "unknown"
            ? ltr(language, "try_again")
            : ltr(language, "lw_new")
      }
      title={ltr(language, "lw_d_t")}
    >
      {live.length === 0 ? (
        <p>{ltr(language, "lw_d_no_lease")}</p>
      ) : (
        <>
          <div className="ui-field">
            <label htmlFor="warning-lease">
              {ltr(language, "lw_lease")}
              <span className="req">{ltr(language, "required")}</span>
            </label>
            <select
              id="warning-lease"
              onChange={(event) => {
                setChosen(event.currentTarget.value);
              }}
              value={chosen}
            >
              {live.map((item) => (
                <option key={item.lease_id} value={item.lease_id}>
                  {ltr(language, "lease_name", item.unit_number)} ·{" "}
                  {item.primary_tenant_name}
                </option>
              ))}
            </select>
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="warning-breach">
                {ltr(language, "lw_d_vdate")}
                <span className="req">{ltr(language, "required")}</span>
              </label>
              <DateInput
                language={language}
                invalid={problems.dates !== undefined}
                id="warning-breach"
                max={today}
                onChange={(value) => {
                  setBreach(value);
                }}
                value={breach}
              />
            </div>
            <div className="ui-field">
              <label htmlFor="warning-given">
                {ltr(language, "lw_d_wdate")}
                <span className="req">{ltr(language, "required")}</span>
              </label>
              <DateInput
                language={language}
                invalid={problems.dates !== undefined}
                id="warning-given"
                max={today}
                onChange={(value) => {
                  setGiven(value);
                }}
                value={given}
              />
            </div>
          </div>
          <Problem message={problems.dates} />
          <div className="ui-field">
            <label htmlFor="warning-what">
              {ltr(language, "lw_d_what")}
              <span className="req">{ltr(language, "required")}</span>
            </label>
            <textarea
              aria-invalid={problems.what !== undefined}
              id="warning-what"
              maxLength={2000}
              onChange={(event) => {
                setWhat(event.currentTarget.value);
              }}
              rows={2}
              value={what}
            />
            <Problem message={problems.what} />
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="warning-article">
                {ltr(language, "lw_d_clause")}
                <span className="req">{ltr(language, "required")}</span>
              </label>
              <input
                aria-invalid={problems.article !== undefined}
                autoComplete="off"
                id="warning-article"
                maxLength={2000}
                onChange={(event) => {
                  setArticle(event.currentTarget.value);
                }}
                value={article}
              />
              <Problem message={problems.article} />
            </div>
            <div className="ui-field">
              <label htmlFor="warning-how">
                {ltr(language, "d_how")}
                <span className="req">{ltr(language, "required")}</span>
              </label>
              <HowSelect
                id="warning-how"
                invalid={problems.how !== undefined}
                language={language}
                onChange={setHow}
                value={how}
              />
              <Problem message={problems.how} />
            </div>
          </div>
          {context.state === "failed" ? (
            <p className="ui-error" role="alert">
              <Icon name="alert" small />
              <span>{ltr(language, "lw_d_ctx_failed")}</span>
            </p>
          ) : (
            <p className="ui-small ui-muted">
              {ltr(language, "lw_d_note", number)}
            </p>
          )}
          <OutcomeNotice language={language} outcome={outcome} />
        </>
      )}
    </Dialog>
  );
}
