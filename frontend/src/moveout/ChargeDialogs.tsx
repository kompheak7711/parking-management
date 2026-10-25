// V1-058 R3 Move-out M4: the move-out charges (DESIGN.md "Move-out (round 3)", step Inspection
// and charges). A Damage charge bills one inspection finding with an amount, a reason and
// evidence; the cleaning charge bills the Unit's cleaning rate once per Lease (BR-MOVEOUT-013).
// Each records its charge source, then a Draft Invoice from it; a Manager issues the Draft on
// the Invoices page. The source takes the finding's id or the Lease's id, so Try again, or a
// second person, never records it twice; a source whose Draft was lost still gets its Draft.

import { FormEvent, useRef, useState } from "react";

import {
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceResource,
} from "../invoiceClient";
import { centsOf } from "../invoices/invoicesData";
import type { LeaseResource } from "../leaseClient";
import { Problem } from "../leases/LeaseDialogs";
import {
  SettlementRequestError,
  type SettlementApi,
} from "../settlementClient";
import { dayText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { oneLine } from "./charges";
import type { InspectionFinding } from "./moveoutClient";
import { mt, type MoveOutTextKey } from "./text";

export type ChargeApi = Pick<InvoiceApi, "recordOneTimeCharge" | "create">;

export type Outcome = "unknown" | "refused" | null;

/** Kept by a dialog (or a step): one idempotency key per set of values. */
export type Keys = Map<string, { fingerprint: string; key: string }>;

export function keyFor(keys: Keys, name: string, fingerprint: string): string {
  const kept = keys.get(name);
  if (kept?.fingerprint === fingerprint) return kept.key;
  const key = crypto.randomUUID();
  keys.set(name, { fingerprint, key });
  return key;
}

/** Answered 409: the charge or its Draft is already there. */
const conflicted = (error: unknown) =>
  error instanceof InvoiceClientError &&
  !error.outcomeUnknown &&
  error.status === 409;

export interface Charged {
  /** null: the charge already had its Draft or Invoice. */
  draft: InvoiceResource | null;
  /** The source was recorded before: its Draft bills the amount recorded then. */
  before: boolean;
}

/**
 * Record a charge source, then its Draft Invoice. A source recorded before (by a lost answer or
 * another person) still gets its Draft, and says so; a Draft already made answers null.
 */
export async function chargeWithDraft(
  api: Pick<InvoiceApi, "create">,
  propertyId: string,
  sourceId: string,
  record: () => Promise<unknown>,
  recordedBefore: (error: unknown) => boolean,
  draftKey: string,
): Promise<Charged> {
  let before = false;
  try {
    await record();
  } catch (error) {
    if (!recordedBefore(error)) throw error;
    before = true;
  }
  try {
    return { draft: await api.create(propertyId, sourceId, draftKey), before };
  } catch (error) {
    if (conflicted(error)) return { draft: null, before };
    throw error;
  }
}

/** A Damage Draft that bills another amount than the one typed now. */
export const otherAmount = (charged: Charged, cents: number): boolean =>
  charged.before &&
  charged.draft !== null &&
  Number(charged.draft.original_total.minor_units) !== cents;

// What the records keep, in English like every stored record.
export const damageReason = (inspectionDate: string) =>
  `Damage found at the move-out inspection on ${inspectionDate}`;

/** The Damage charge of one finding: the finding's id is the charge's id. */
export function chargeFinding(
  api: ChargeApi,
  keys: Keys,
  lease: LeaseResource,
  inspectionDate: string,
  finding: { id: string; description: string },
  cents: number,
  evidence: string,
): Promise<Charged> {
  const input = {
    category: "DAMAGE_CHARGES" as const,
    customer_id: lease.primary_tenant_id,
    lease_id: lease.lease_id,
    inspection_damage_finding_id: finding.id,
    description: oneLine(`Damage: ${finding.description}`, 1000),
    amount: { currency: "USD" as const, minor_units: cents },
    reason: damageReason(inspectionDate),
    evidence_reference: oneLine(evidence, 500),
  };
  const fingerprint = JSON.stringify(input);
  const key = keyFor(keys, `charge:${finding.id}`, fingerprint);
  const draftKey = keyFor(keys, `draft:${finding.id}`, fingerprint);
  return chargeWithDraft(
    api,
    lease.property_id,
    finding.id,
    () =>
      api.recordOneTimeCharge(
        lease.property_id,
        { ...input, charge_id: finding.id },
        key,
      ),
    conflicted,
    draftKey,
  );
}

/** Only a clear refusal says "not saved"; no answer may have saved a step. */
export function outcomeOf(error: unknown): Outcome {
  if (error instanceof InvoiceClientError)
    return error.outcomeUnknown || error.status === null || error.status >= 500
      ? "unknown"
      : "refused";
  // A server failure or an unreadable answer may have saved it.
  if (error instanceof SettlementRequestError)
    return error.status >= 400 && error.status < 500 ? "refused" : "unknown";
  return "unknown";
}

export function DamageChargeDialog({
  language,
  lease,
  inspectionDate,
  finding,
  api,
  onClose,
  onSaved,
}: {
  language: Language;
  lease: LeaseResource;
  inspectionDate: string;
  finding: InspectionFinding;
  api: ChargeApi;
  onClose: () => void;
  /** other: recorded before with another amount, which its Draft bills. */
  onSaved: (draft: InvoiceResource | null, other: boolean) => void;
}) {
  const [amount, setAmount] = useState("");
  const [evidence, setEvidence] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const keys = useRef<Keys>(new Map());
  const cents = centsOf(amount);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (cents === null || evidence.trim() === "") {
      setProblem(mt(language, "fd_err"));
      return;
    }
    setProblem(null);
    setBusy(true);
    setOutcome(null);
    chargeFinding(
      api,
      keys.current,
      lease,
      inspectionDate,
      finding,
      cents,
      evidence,
    )
      .then((charged) => {
        onSaved(charged.draft, otherAmount(charged, cents));
      })
      .catch((error: unknown) => {
        setOutcome(outcomeOf(error));
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
          : outcome === "unknown"
            ? mt(language, "try_again")
            : mt(language, "st4_charge_ok")
      }
      title={`${mt(language, "st4_charge_t")} · ${lease.unit_number}`}
    >
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {mt(language, outcome === "unknown" ? "c_unknown" : "c_refused")}
          </p>
        </div>
      )}
      <p>
        {finding.description}
        {finding.pet_related && (
          <span className="ui-sub2">{mt(language, "st4_pet")}</span>
        )}
      </p>
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="dc-amt">
            {mt(language, "fd_amt")}
            <span className="req">{mt(language, "required")}</span>
          </label>
          <div className="ui-money">
            <span aria-hidden="true">$</span>
            <input
              aria-invalid={problem !== null && cents === null}
              autoComplete="off"
              className="ui-num"
              id="dc-amt"
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
          <label htmlFor="dc-ev">
            {mt(language, "fd_ev")}
            <span className="req">{mt(language, "required")}</span>
          </label>
          <input
            aria-invalid={problem !== null && evidence.trim() === ""}
            autoComplete="off"
            id="dc-ev"
            maxLength={500}
            onChange={(event) => {
              setEvidence(event.target.value);
              setProblem(null);
            }}
            value={evidence}
          />
        </div>
      </div>
      <Problem message={problem} />
      <p className="ui-small ui-muted">
        {mt(language, "st4_charge_c", dayText(inspectionDate))}
      </p>
    </Dialog>
  );
}

/** The Unit's current cleaning rate, as the cleaning-rate read gives it. */
export interface CleaningRate {
  id: string;
  cents: number;
}

/** Why the cleaning charge was refused, from the server's stable reason code. */
function cleaningRefusal(language: Language, error: unknown): string {
  if (error instanceof SettlementRequestError && error.code !== null) {
    const key = `cr_${error.code}`;
    if (
      [
        "cr_CLEANING_RATE_CHANGED",
        "cr_CLEANING_RATE_NOT_SET",
        "cr_CLEANING_RATE_ZERO",
        "cr_CLEANING_CHARGE_NEEDS_MOVE_OUT",
        "cr_CLEANING_CHARGE_NOT_MOVED_IN",
      ].includes(key)
    )
      return mt(language, key as MoveOutTextKey);
  }
  if (error instanceof InvoiceClientError && error.status === 404)
    return mt(language, "cr_elsewhere");
  return mt(language, "c_refused");
}

export function CleaningChargeDialog({
  language,
  lease,
  rate,
  settlementApi,
  invoiceApi,
  onClose,
  onSaved,
}: {
  language: Language;
  lease: LeaseResource;
  rate: CleaningRate;
  settlementApi: Pick<SettlementApi, "chargeCleaning">;
  invoiceApi: Pick<InvoiceApi, "create">;
  onClose: () => void;
  /** other: recorded before at another rate, which its Draft bills. */
  onSaved: (draft: InvoiceResource | null, other: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const keys = useRef<Keys>(new Map());

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setOutcome(null);
    setRefusal(null);
    // The cleaning charge takes the Lease's id: one per Lease.
    chargeWithDraft(
      invoiceApi,
      lease.property_id,
      lease.lease_id,
      () =>
        settlementApi.chargeCleaning(lease.property_id, lease.lease_id, {
          charge_id: lease.lease_id,
          expected_rate_id: rate.id,
        }),
      // Recorded before by this Lease's id: "already recorded", or the same id from another
      // person or at another rate ("identity reused").
      (error) =>
        error instanceof SettlementRequestError &&
        (error.code === "CLEANING_CHARGE_ALREADY_RECORDED" ||
          error.code === "IDEMPOTENCY_KEY_REUSED"),
      keyFor(keys.current, "draft", rate.id),
    )
      .then((charged) => {
        onSaved(charged.draft, otherAmount(charged, rate.cents));
      })
      .catch((error: unknown) => {
        const found = outcomeOf(error);
        setOutcome(found);
        if (found === "refused") setRefusal(cleaningRefusal(language, error));
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
          : outcome === "unknown"
            ? mt(language, "try_again")
            : mt(language, "st4_clean_btn")
      }
      title={`${mt(language, "st4_clean_btn")} · ${lease.unit_number}`}
    >
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{refusal ?? mt(language, "c_unknown")}</p>
        </div>
      )}
      <p>
        {mt(
          language,
          "st4_clean_c",
          usdFromCents(rate.cents),
          lease.unit_number,
          lease.primary_tenant_name,
        )}
      </p>
      <p className="ui-small ui-muted">{mt(language, "st4_drafts_note")}</p>
    </Dialog>
  );
}
