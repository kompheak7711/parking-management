// V1-058 R3 Move-out M6: step 6, after closure (DESIGN.md "Move-out (round 3)": "corrections as
// a new extra charge or a new refund, confirmed by a Manager"; BR-SETTLE-013). A closed Final
// Settlement is never reopened: a later charge is a correction draft linked to it, with a
// reason, that a financial.approve holder confirms in Waiting for approval. The server checks
// every rule again. V1-060 B6: once the Settlement is closed the move-out is finished, so the
// step says "If needed", not "Now".
// A refund after closure is not offered here yet: the amount the server takes is what comes off
// the charge, and value a Deposit paid goes back to that Deposit and must be paid out by a DL-032
// step. The page cannot read what paid each Invoice line, so it could not build that plan.

import { FormEvent, useRef, useState } from "react";

import { centsOf } from "../invoices/invoicesData";
import type { LeaseResource } from "../leaseClient";
import { Problem } from "../leases/LeaseDialogs";
import {
  SettlementRequestError,
  type SettlementApi,
} from "../settlementClient";
import type { ExtraChargeInput } from "../settlementForms";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Dialog } from "../shell/ui";
import { serverWords } from "../shell/serverText";
import type { Language } from "../signInText";
import { keyFor, type Keys } from "./ChargeDialogs";
import type { InspectionFinding } from "./moveoutClient";
import { Step } from "./parts";
import type { SettlementState } from "./settlement";
import { mt } from "./text";

export type AfterClosureApi = Pick<SettlementApi, "extraCharge">;

type Outcome = { unknown: true } | { refused: string } | null;

/** A clear refusal shows the server's plain words; anything else may have saved it. */
function outcomeOf(error: unknown, language: Language): Outcome {
  return error instanceof SettlementRequestError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 408 &&
    error.status !== 429
    ? { refused: serverWords(language, error) }
    : { unknown: true };
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
      <p>
        {"unknown" in outcome ? mt(language, "c_unknown") : outcome.refused}
      </p>
    </div>
  );
}

export function AfterClosureStep({
  language,
  propertyId,
  lease,
  settlement,
  mayPrepare,
  mayApprove,
  findings,
  api,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  lease: LeaseResource;
  /** null: no Settlement yet, or it could not be read. */
  settlement: SettlementState | null;
  mayPrepare: boolean;
  mayApprove: boolean;
  /** Findings of the inspection in force with no charge yet. */
  findings: InspectionFinding[];
  api: AfterClosureApi;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  // Kept while the page is open: saving the same charge again after no answer, even after
  // closing the dialog, sends the same key, so the server never records it twice.
  const keys = useRef<Keys>(new Map());
  const closed = settlement?.closed === true ? settlement : null;
  const actions =
    closed !== null && mayPrepare ? (
      <button
        className="ui-btn"
        onClick={() => {
          setOpen(true);
        }}
        type="button"
      >
        <Icon name="plus" />
        {mt(language, "st6_charge")}
      </button>
    ) : undefined;
  return (
    <Step
      actions={actions}
      language={language}
      mark={closed === null ? "todo" : "optional"}
      number={6}
      title={mt(language, "st6_t")}
    >
      {closed !== null && <p>{mt(language, "st6_finished")}</p>}
      <p className="ui-small ui-muted">{mt(language, "st6_note")}</p>
      {closed !== null && (
        <p className="ui-small ui-muted">{mt(language, "st6_refund_later")}</p>
      )}
      {closed !== null && !mayPrepare && (
        <p className="ui-small ui-muted">{mt(language, "st6_not_allowed")}</p>
      )}
      {closed !== null && mayApprove && (
        <p className="ui-small">
          <a href={hashForPage("approvals")}>{mt(language, "st6_approvals")}</a>
        </p>
      )}
      {closed !== null && open && (
        <ExtraChargeDialog
          api={api}
          findings={findings}
          keys={keys.current}
          language={language}
          lease={lease}
          onClose={() => {
            setOpen(false);
          }}
          onSaved={() => {
            // A new charge with the same values later is a new draft, not this one again.
            keys.current.delete("charge");
            setOpen(false);
            onSaved();
          }}
          propertyId={propertyId}
          settlementId={closed.id}
        />
      )}
    </Step>
  );
}

function ExtraChargeDialog({
  language,
  propertyId,
  lease,
  settlementId,
  findings,
  keys,
  api,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  lease: LeaseResource;
  settlementId: string;
  findings: InspectionFinding[];
  keys: Keys;
  api: AfterClosureApi;
  onClose: () => void;
  onSaved: () => void;
}) {
  // "" is a Miscellaneous charge; a finding's id makes it that finding's Damage charge.
  const [finding, setFinding] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [evidence, setEvidence] = useState("");
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const cents = centsOf(amount);
  const chosen = findings.find((item) => item.id === finding);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const text =
      chosen === undefined
        ? description.trim()
        : // The server keeps at most 1,000 characters (whole letters).
          Array.from(`Damage: ${chosen.description}`)
            .slice(0, 1000)
            .join("")
            .trim();
    if (
      cents === null ||
      text === "" ||
      evidence.trim() === "" ||
      reason.trim() === ""
    ) {
      setProblem(mt(language, "c6_err"));
      return;
    }
    const form: ExtraChargeInput = {
      category:
        chosen === undefined ? "MISCELLANEOUS_CHARGES" : "DAMAGE_CHARGES",
      description: text,
      amount_usd_cents: cents,
      evidence_reference: evidence.trim(),
      reason: reason.trim(),
      inspection_damage_finding_id: chosen?.id ?? null,
    };
    setProblem(null);
    setBusy(true);
    setOutcome(null);
    api
      .extraCharge(
        propertyId,
        settlementId,
        form,
        keyFor(keys, "charge", JSON.stringify(form)),
      )
      .then(onSaved)
      .catch((error: unknown) => {
        setOutcome(outcomeOf(error, language));
      })
      .finally(() => {
        setBusy(false);
      });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={mt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? mt(language, "saving")
          : outcome !== null && "unknown" in outcome
            ? mt(language, "try_again")
            : mt(language, "c6_ok")
      }
      title={`${mt(language, "st6_charge")} · ${lease.unit_number}`}
    >
      <OutcomeNotice language={language} outcome={outcome} />
      {findings.length > 0 && (
        <div className="ui-field">
          <label htmlFor="c6-kind">{mt(language, "c6_kind")}</label>
          <select
            id="c6-kind"
            onChange={(event) => {
              setFinding(event.target.value);
              setProblem(null);
            }}
            value={finding}
          >
            <option value="">{mt(language, "c6_misc")}</option>
            {findings.map((item) => (
              <option key={item.id} value={item.id}>
                {mt(language, "c6_damage", item.description)}
              </option>
            ))}
          </select>
        </div>
      )}
      {chosen === undefined && (
        <div className="ui-field">
          <label htmlFor="c6-what">
            {mt(language, "c6_what")}
            <span className="req">{mt(language, "required")}</span>
          </label>
          <input
            aria-invalid={problem !== null && description.trim() === ""}
            autoComplete="off"
            id="c6-what"
            maxLength={500}
            onChange={(event) => {
              setDescription(event.target.value);
              setProblem(null);
            }}
            value={description}
          />
        </div>
      )}
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="c6-amt">
            {mt(language, "fd_amt")}
            <span className="req">{mt(language, "required")}</span>
          </label>
          <div className="ui-money">
            <span aria-hidden="true">$</span>
            <input
              aria-invalid={problem !== null && cents === null}
              autoComplete="off"
              className="ui-num"
              id="c6-amt"
              inputMode="decimal"
              onChange={(event) => {
                setAmount(event.target.value);
                setProblem(null);
              }}
              value={amount}
            />
          </div>
        </div>
        <div className="ui-field">
          <label htmlFor="c6-ev">
            {mt(language, "fd_ev")}
            <span className="req">{mt(language, "required")}</span>
          </label>
          <input
            aria-invalid={problem !== null && evidence.trim() === ""}
            autoComplete="off"
            id="c6-ev"
            maxLength={500}
            onChange={(event) => {
              setEvidence(event.target.value);
              setProblem(null);
            }}
            value={evidence}
          />
        </div>
      </div>
      <ReasonField
        invalid={problem !== null && reason.trim() === ""}
        language={language}
        onChange={(value) => {
          setReason(value);
          setProblem(null);
        }}
        value={reason}
      />
      <Problem message={problem} />
      <p className="ui-small ui-muted">
        {mt(language, "c6_c", lease.primary_tenant_name)}
      </p>
    </Dialog>
  );
}

function ReasonField({
  language,
  value,
  invalid,
  onChange,
}: {
  language: Language;
  value: string;
  invalid: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="ui-field">
      <label htmlFor="c6-reason">
        {mt(language, "c6_reason")}
        <span className="req">{mt(language, "required")}</span>
      </label>
      <textarea
        aria-invalid={invalid}
        id="c6-reason"
        maxLength={500}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        rows={2}
        value={value}
      />
    </div>
  );
}
