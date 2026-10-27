// V1-058 R3 Move-out M4: Record inspection (DESIGN.md "Move-out (round 3)", step Inspection and
// charges). The inspection lists what was found; a finding alone charges nothing
// (BR-MOVEOUT-006). For a person who may make Damage charges, a finding with an amount and
// evidence is then charged at once (see ChargeDialogs). An inspection is never changed: a
// correction is a new inspection that replaces it, offered only while none of its findings is
// charged. Each request keeps one identity while its values stay the same, so Try again never
// saves anything twice.

import { FormEvent, useRef, useState } from "react";

import type { InvoiceResource } from "../invoiceClient";
import { centsOf } from "../invoices/invoicesData";
import type { LeaseResource } from "../leaseClient";
import { Problem } from "../leases/LeaseDialogs";
import { DateInput } from "../shell/DateInput";
import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type ChargeApi,
  type Charged,
  type Keys,
  type Outcome,
  chargeFinding,
  otherAmount,
  outcomeOf,
} from "./ChargeDialogs";
import { oneLine } from "./charges";
import {
  MoveOutConflictError,
  MoveOutNotAllowedError,
  MoveOutRequestError,
  type MoveOutApi,
  type MoveOutInspection,
} from "./moveoutClient";
import { mt } from "./text";

// What the records keep, in English like every stored record.
const AUTHORITY = "Recorded in the app by the signed-in user (leases.inspect)";
const EVIDENCE = "Move-out inspection recorded in the app";
const REASON = "Move-out inspection after the hand-back";

const MAX_FINDINGS = 50;

interface Row {
  /** Stable for the life of the dialog: the React key and the field ids. */
  row: string;
  description: string;
  pet: boolean;
  amount: string;
  evidence: string;
}

const newRow = (description = "", pet = false): Row => ({
  row: crypto.randomUUID(),
  description,
  pet,
  amount: "",
  evidence: "",
});

type Bad = "date" | "reason" | `desc:${string}` | `amt:${string}`;

export function InspectionDialog({
  language,
  lease,
  handBackDay,
  today,
  replaces,
  mayCharge,
  moveOutApi,
  chargeApi,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  lease: LeaseResource;
  handBackDay: string;
  today: string;
  /** The inspection a correction replaces; its findings fill the form. */
  replaces: MoveOutInspection | null;
  /** damage_charges.bill and invoices.create: amounts are asked for. */
  mayCharge: boolean;
  moveOutApi: Pick<MoveOutApi, "inspect">;
  chargeApi: ChargeApi;
  onClose: () => void;
  /** check: a charge got no new Draft, or its Draft bills an amount recorded before. */
  onSaved: (drafts: InvoiceResource[], check: boolean) => void;
  onConflict: () => void;
}) {
  const [day, setDay] = useState(today < handBackDay ? handBackDay : today);
  const [rows, setRows] = useState<Row[]>(() =>
    replaces === null
      ? []
      : replaces.findings.map((finding) =>
          newRow(finding.description, finding.pet_related),
        ),
  );
  const [notes, setNotes] = useState(replaces?.result_text ?? "");
  const [why, setWhy] = useState("");
  const [bad, setBad] = useState<ReadonlySet<Bad>>(new Set());
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  // Kept for the life of the dialog: the saved inspection, the charges made, one identity per
  // set of values.
  const saved = useRef<MoveOutInspection | null>(null);
  const drafts = useRef(new Map<string, Charged & { other: boolean }>());
  // The rows whose charge is made: their amount and evidence no longer change.
  const [charged, setCharged] = useState<ReadonlySet<string>>(new Set());
  const identity = useRef<{
    fingerprint: string;
    id: string;
    key: string;
    findings: string[];
  } | null>(null);
  const keys = useRef<Keys>(new Map());
  // Saved: only the charges may still change. Unknown: Try again sends the very same inspection.
  const [locked, setLocked] = useState(false);
  const [held, setHeld] = useState(false);
  const frozen = locked || held;

  const change = (row: string, patch: Partial<Row>) => {
    setRows((current) =>
      current.map((item) => (item.row === row ? { ...item, ...patch } : item)),
    );
    setBad(new Set());
    setProblem(null);
  };

  function check(): Bad[] {
    const found: Bad[] = [];
    if (day < handBackDay || day > today) found.push("date");
    if (replaces !== null && why.trim() === "") found.push("reason");
    for (const item of rows) {
      if (oneLine(item.description, 1000) === "")
        found.push(`desc:${item.row}`);
      if (!mayCharge) continue;
      const empty = item.amount.trim() === "" && item.evidence.trim() === "";
      if (
        !empty &&
        (centsOf(item.amount) === null || item.evidence.trim() === "")
      )
        found.push(`amt:${item.row}`);
    }
    return found;
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found = check();
    setBad(new Set(found));
    if (found.length > 0) {
      setProblem(
        mt(
          language,
          found.includes("date")
            ? "st4_bad_date"
            : found.includes("reason")
              ? "st4_bad_reason"
              : found.some((item) => item.startsWith("desc:"))
                ? "st4_bad_desc"
                : "fd_err",
        ),
      );
      return;
    }
    setProblem(null);
    setBusy(true);
    setOutcome(null);
    void (async () => {
      if (saved.current === null) {
        const shown = rows.map((item) => ({
          description: oneLine(item.description, 1000),
          pet_related: item.pet,
        }));
        const result = notes.trim()
          ? notes.trim().slice(0, 5000)
          : shown.length === 0
            ? "No damage found."
            : `${String(shown.length)} damage finding(s).`;
        const source = {
          expected_lease_version: lease.version,
          inspection_date: day,
          result_text: result,
          authorization_reference: AUTHORITY,
          evidence_reference: EVIDENCE,
          reason: replaces === null ? REASON : oneLine(why, 500),
          supersedes_inspection_id: replaces?.id ?? null,
        };
        const fingerprint = JSON.stringify({ source, shown });
        if (identity.current?.fingerprint !== fingerprint)
          identity.current = {
            fingerprint,
            id: crypto.randomUUID(),
            key: crypto.randomUUID(),
            findings: shown.map(() => crypto.randomUUID()),
          };
        const { id, key, findings } = identity.current;
        saved.current = await moveOutApi.inspect(
          lease.property_id,
          lease.lease_id,
          {
            inspection_id: id,
            ...source,
            findings: shown.map((item, index) => ({
              finding_id: findings[index] ?? "",
              ...item,
            })),
          },
          key,
        );
        // The findings are recorded: only the charges may still change.
        setLocked(true);
      }
      const inspection = saved.current;
      if (!mayCharge) return { made: [], other: false };
      // The rows keep the finding ids this dialog chose for them.
      const ids = identity.current?.findings ?? [];
      for (const [index, item] of rows.entries()) {
        const cents = centsOf(item.amount);
        const finding = inspection.findings.find(
          (found) => found.id === ids[index],
        );
        if (cents === null || finding === undefined) continue;
        if (drafts.current.has(finding.id)) continue;
        const made = await chargeFinding(
          chargeApi,
          keys.current,
          lease,
          inspection.inspection_date,
          finding,
          cents,
          item.evidence,
        );
        drafts.current.set(finding.id, {
          ...made,
          other: otherAmount(made, cents),
        });
        setCharged((current) => new Set([...current, item.row]));
      }
      const all = [...drafts.current.values()];
      return {
        made: all.flatMap((item) => (item.draft === null ? [] : [item.draft])),
        other: all.some((item) => item.other || item.draft === null),
      };
    })()
      .then(({ made, other }) => {
        onSaved(made, other);
      })
      .catch((error: unknown) => {
        if (error instanceof MoveOutConflictError) {
          onConflict();
          return;
        }
        const found =
          error instanceof MoveOutNotAllowedError ||
          error instanceof MoveOutRequestError
            ? "refused"
            : outcomeOf(error);
        setOutcome(found);
        if (saved.current === null) setHeld(found === "unknown");
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const title = mt(language, replaces === null ? "st4_btn" : "st4_fix_btn");
  return (
    <Dialog
      busy={busy}
      closeLabel={mt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? mt(language, "saving")
          : outcome === "unknown"
            ? mt(language, "try_again")
            : mt(
                language,
                mayCharge && rows.some((item) => centsOf(item.amount) !== null)
                  ? "st4_ok_charges"
                  : "st4_ok",
              )
      }
      title={`${title} · ${lease.unit_number}`}
      wide
    >
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {mt(
              language,
              locked
                ? outcome === "unknown"
                  ? "st4_saved_charge_failed"
                  : "st4_saved_charge_refused"
                : outcome === "unknown"
                  ? "c_unknown"
                  : "c_refused",
            )}
          </p>
        </div>
      )}
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="in-day">
            {mt(language, "st4_date")}
            <span className="req">{mt(language, "required")}</span>
          </label>
          <DateInput
            describedBy="in-day-help"
            invalid={bad.has("date")}
            disabled={frozen}
            id="in-day"
            max={today}
            min={handBackDay}
            onChange={(value) => {
              setDay(value);
              setBad(new Set());
              setProblem(null);
            }}
            value={day}
          />
          <p className="help" id="in-day-help">
            {mt(language, "st4_date_help", dayText(handBackDay))}
          </p>
        </div>
        {replaces !== null && (
          <div className="ui-field">
            <label htmlFor="in-why">
              {mt(language, "st4_reason")}
              <span className="req">{mt(language, "required")}</span>
            </label>
            <input
              aria-invalid={bad.has("reason")}
              autoComplete="off"
              disabled={frozen}
              id="in-why"
              maxLength={500}
              onChange={(event) => {
                setWhy(event.target.value);
                setBad(new Set());
                setProblem(null);
              }}
              value={why}
            />
          </div>
        )}
      </div>
      <fieldset className="ui-radios">
        <legend>{mt(language, "st4_findings")}</legend>
        {rows.length === 0 && (
          <p className="ui-small ui-muted">{mt(language, "st4_nofind")}</p>
        )}
        {rows.map((item, index) => {
          const id = `in-${item.row}`;
          const amountBad = bad.has(`amt:${item.row}`);
          return (
            <div className="ui-finding" key={item.row}>
              <div className="ui-mhead">
                <p className="ui-flabel">{mt(language, "fd_n", index + 1)}</p>
                {!frozen && (
                  <button
                    aria-label={mt(language, "fd_remove_n", index + 1)}
                    className="ui-btn link"
                    onClick={() => {
                      setRows((current) =>
                        current.filter((other) => other.row !== item.row),
                      );
                      setBad(new Set());
                      setProblem(null);
                    }}
                    type="button"
                  >
                    {mt(language, "fd_remove")}
                  </button>
                )}
              </div>
              <div className="ui-field">
                <label htmlFor={`${id}-desc`}>
                  {mt(language, "fd_desc")}
                  <span className="req">{mt(language, "required")}</span>
                </label>
                <input
                  aria-invalid={bad.has(`desc:${item.row}`)}
                  autoComplete="off"
                  disabled={frozen}
                  id={`${id}-desc`}
                  maxLength={1000}
                  onChange={(event) => {
                    change(item.row, { description: event.target.value });
                  }}
                  value={item.description}
                />
              </div>
              <label className="ui-chk">
                <input
                  checked={item.pet}
                  disabled={frozen}
                  onChange={(event) => {
                    change(item.row, { pet: event.target.checked });
                  }}
                  type="checkbox"
                />
                <span>{mt(language, "fd_pet")}</span>
              </label>
              {mayCharge && (
                <div className="ui-row2">
                  <div className="ui-field">
                    <label htmlFor={`${id}-amt`}>
                      {mt(language, "fd_amt")}
                    </label>
                    <div className="ui-money">
                      <span aria-hidden="true">$</span>
                      <input
                        aria-describedby={`${id}-amt-help`}
                        aria-invalid={
                          amountBad && centsOf(item.amount) === null
                        }
                        autoComplete="off"
                        className="ui-num"
                        disabled={charged.has(item.row)}
                        id={`${id}-amt`}
                        inputMode="decimal"
                        onChange={(event) => {
                          change(item.row, { amount: event.target.value });
                        }}
                        value={item.amount}
                      />
                    </div>
                    <p className="help" id={`${id}-amt-help`}>
                      {mt(language, "fd_amt_help")}
                    </p>
                  </div>
                  <div className="ui-field">
                    <label htmlFor={`${id}-ev`}>{mt(language, "fd_ev")}</label>
                    <input
                      aria-invalid={amountBad && item.evidence.trim() === ""}
                      autoComplete="off"
                      disabled={charged.has(item.row)}
                      id={`${id}-ev`}
                      maxLength={500}
                      onChange={(event) => {
                        change(item.row, { evidence: event.target.value });
                      }}
                      value={item.evidence}
                    />
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </fieldset>
      {!frozen && rows.length < MAX_FINDINGS && (
        <div className="ui-actions">
          <button
            className="ui-btn"
            onClick={() => {
              setRows((current) => [...current, newRow()]);
            }}
            type="button"
          >
            <Icon name="plus" />
            {mt(language, "st4_add")}
          </button>
        </div>
      )}
      <div className="ui-field">
        <label htmlFor="in-notes">{mt(language, "st4_notes")}</label>
        <textarea
          disabled={frozen}
          id="in-notes"
          maxLength={5000}
          onChange={(event) => {
            setNotes(event.target.value);
          }}
          rows={2}
          value={notes}
        />
      </div>
      <Problem message={problem} />
      <p className="ui-small ui-muted">
        {mt(language, mayCharge ? "st4_c" : "st4_c_no_charge")}
      </p>
    </Dialog>
  );
}
