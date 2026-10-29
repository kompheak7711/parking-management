// V1-058 R3 Move-out M5b: Prepare the Final Settlement (DESIGN.md "Move-out (round 3)": "Staff
// prepare the statement; a Manager confirms it"). The dialog shows the draft the page proposes
// in the DL-032 order (plan.ts), asks what only staff know (the Customer's choice for the rest of
// the Pet Deposit, the refund method and its reference) and records the draft. Nothing moves
// until a Manager confirms it in Waiting for approval; the server checks every step again.
// The refund goes to the Primary Tenant; a refund to another Signer needs all Signers' written
// agreement and stays in the earlier forms.

import { FormEvent, type ReactNode, useEffect, useRef, useState } from "react";

import type { LeaseResource } from "../leaseClient";
import { Problem } from "../leases/LeaseDialogs";
import {
  SettlementRequestError,
  type SettlementApi,
  type SettlementRecord,
} from "../settlementClient";
import type {
  DepositRefundStepInput,
  FinalSettlementDraftInput,
} from "../settlementForms";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import { serverWords } from "../shell/serverText";
import type { Language } from "../signInText";
import { keyFor, type Keys } from "./ChargeDialogs";
import { Kv } from "./parts";
import { planSettlement } from "./plan";
import type { SettlementPreview } from "./settlement";
import { mt } from "./text";

// The server takes at most 200 steps, and the stored draft (the form and its result) must stay
// under 16,000 bytes. SIZE_LIMIT warns early on the steps alone; STORED_LIMIT checks the whole
// form in bytes (Khmer text is 3 bytes a letter) with room for the server's spacing and result.
const STEP_LIMIT = 200;
const SIZE_LIMIT = 11000;
const STORED_LIMIT = 13500;

export type PrepareApi = Pick<
  SettlementApi,
  "refundMethods" | "settlementDraft"
>;

interface Method {
  id: string;
  name: string;
  cash: boolean;
}

function methodsOf(items: SettlementRecord[]): Method[] {
  return items.flatMap((item) =>
    item.active === true &&
    typeof item.id === "string" &&
    typeof item.code === "string" &&
    typeof item.display_name === "string"
      ? [{ id: item.id, name: item.display_name, cash: item.code === "CASH" }]
      : [],
  );
}

type Basis = "CUSTOMER_CHOICE" | "STAFF_REASON";

export function PrepareDialog({
  language,
  propertyId,
  lease,
  preview,
  api,
  onClose,
  onSaved,
  onWaiting,
}: {
  language: Language;
  propertyId: string;
  lease: LeaseResource;
  preview: SettlementPreview;
  api: PrepareApi;
  onClose: () => void;
  onSaved: () => void;
  /** A draft of this Settlement already waits (someone else, or a lost answer). */
  onWaiting: () => void;
}) {
  const staffMay = preview.pet_remainder_chosen_by !== "CUSTOMER_ONLY";
  const [usePetRest, setUsePetRest] = useState(false);
  const [basis, setBasis] = useState<Basis>("CUSTOMER_CHOICE");
  const [choice, setChoice] = useState("");
  const [staffReason, setStaffReason] = useState("");
  const [methods, setMethods] = useState<Method[] | "failed" | null>(null);
  const [method, setMethod] = useState("");
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState(mt("en", "pd_reason_default"));
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<
    { unknown: true } | { refused: string } | null
  >(null);
  const keys = useRef<Keys>(new Map());

  // Stored records keep English text, like every record.
  // Outside the three early terminations a Pet Deposit left after the Security Deposit must pay
  // the debt before any refund (the server refuses a refund while it could pay), so it is used.
  const base = planSettlement(preview, false);
  const petRestOpen = base.pet_rest_possible;
  const petRestOn = petRestOpen && (staffMay || usePetRest);
  const final = petRestOn ? planSettlement(preview, true) : base;

  useEffect(() => {
    if (final.refunds.length === 0) return;
    let live = true;
    api
      .refundMethods(propertyId)
      .then((items) => {
        if (!live) return;
        const found = methodsOf(items);
        setMethods(found);
        setMethod((current) => current || (found[0]?.id ?? ""));
      })
      .catch(() => {
        if (live) setMethods("failed");
      });
    return () => {
      live = false;
    };
  }, [api, propertyId, final.refunds.length]);

  const chosen = Array.isArray(methods)
    ? methods.find((item) => item.id === method)
    : undefined;
  // The server keeps at most 200 steps and a bounded stored draft; a longer plan is refused,
  // so the dialog says so before staff fill it in.
  const tooLong =
    final.steps.length + final.refunds.length > STEP_LIMIT ||
    JSON.stringify(final.steps).length > SIZE_LIMIT;
  const noMethod =
    final.refunds.length > 0 && Array.isArray(methods) && methods.length === 0;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (tooLong || noMethod || methods === "failed") {
      setProblem(
        mt(
          language,
          tooLong
            ? "pd_too_long"
            : noMethod
              ? "pd_no_methods"
              : "pd_methods_failed",
        ),
      );
      return;
    }
    const needsBasis = petRestOn;
    const missing =
      reason.trim() === "" ||
      (needsBasis &&
        (staffReason.trim() === "" ||
          (basis === "CUSTOMER_CHOICE" && choice.trim() === ""))) ||
      (final.refunds.length > 0 &&
        (chosen === undefined || (!chosen.cash && reference.trim() === "")));
    if (missing) {
      setProblem(mt(language, "pd_err"));
      return;
    }
    const refunds: DepositRefundStepInput[] = final.refunds.map((refund) => ({
      kind: "DEPOSIT_REFUNDS",
      deposit_id: refund.deposit_id,
      amount_usd_cents: refund.amount_usd_cents,
      refund_method_id: chosen?.id ?? "",
      // The server needs a note; cash has no transfer reference.
      reference_note:
        reference.trim() === "" ? mt("en", "pd_cash_note") : reference.trim(),
      recipient_customer_id: lease.primary_tenant_id,
      signer_agreement: null,
    }));
    const form: FinalSettlementDraftInput = {
      steps: [...final.steps, ...refunds],
      reason: reason.trim(),
      pet_remainder: needsBasis
        ? {
            basis: staffMay ? basis : "CUSTOMER_CHOICE",
            staff_reason: staffReason.trim(),
            customer_choice:
              !staffMay || basis === "CUSTOMER_CHOICE" ? choice.trim() : null,
          }
        : null,
    };
    // The reason is kept in its own column, not in the stored draft.
    const stored = { steps: form.steps, pet_remainder: form.pet_remainder };
    if (
      new TextEncoder().encode(JSON.stringify(stored)).length * 1.1 >
      STORED_LIMIT
    ) {
      // The steps fit (tooLong is false here), so the long text is what to shorten.
      setProblem(mt(language, "pd_text_long"));
      return;
    }
    setProblem(null);
    setBusy(true);
    setOutcome(null);
    api
      .settlementDraft(
        propertyId,
        preview.settlement.id,
        form,
        keyFor(keys.current, "draft", JSON.stringify(form)),
      )
      .then(() => {
        onSaved();
      })
      .catch((error: unknown) => {
        if (
          error instanceof SettlementRequestError &&
          error.code === "FINAL_SETTLEMENT_DRAFT_WAITING"
        ) {
          onWaiting();
          return;
        }
        const refused =
          error instanceof SettlementRequestError &&
          error.status >= 400 &&
          error.status < 500 &&
          error.status !== 408 &&
          error.status !== 429;
        // The server names the broken rule in plain words.
        setOutcome(
          refused
            ? { refused: serverWords(language, error) }
            : { unknown: true },
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const security = preview.deposits.filter(
    (item) => item.deposit_type === "SECURITY",
  );
  const kept = security
    .filter((item) => item.path === "KEPT")
    .reduce((total, item) => total + item.held_usd_cents, 0);
  const refundTotal = final.refunds.reduce(
    (total, item) => total + item.amount_usd_cents,
    0,
  );

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
            : mt(language, "pd_ok")
      }
      title={`${mt(language, "pd_t")} · ${lease.unit_number}`}
    >
      {tooLong && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{mt(language, "pd_too_long")}</p>
        </div>
      )}
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {"unknown" in outcome ? mt(language, "c_unknown") : outcome.refused}
          </p>
        </div>
      )}
      <Kv
        rows={[
          [
            mt(language, "fs_owed"),
            <span className="ui-num">
              {usdFromCents(preview.open_total_usd_cents)}
            </span>,
          ],
          [
            mt(language, "fs_credit_used"),
            <span className="ui-num">
              − {usdFromCents(final.credit_used_usd_cents)}
            </span>,
          ],
          ...(preview.deposits.some((item) => item.deposit_type === "PET")
            ? ([
                [
                  mt(language, "fs_pet_dmg"),
                  <span className="ui-num">
                    − {usdFromCents(final.pet_damage_paid_usd_cents)}
                  </span>,
                ],
              ] as [string, ReactNode][])
            : []),
          kept > 0
            ? [
                mt(language, "fs_sec_kept"),
                <span className="ui-num">{usdFromCents(kept)}</span>,
              ]
            : [
                mt(language, "fs_sec_app"),
                <span className="ui-num">
                  − {usdFromCents(final.security_applied_usd_cents)}
                </span>,
              ],
          ...(petRestOn
            ? ([
                [
                  mt(language, "fs_pet_other"),
                  <span className="ui-num">
                    − {usdFromCents(final.pet_rest_applied_usd_cents)}
                  </span>,
                ],
              ] as [string, ReactNode][])
            : []),
          [
            mt(language, "fs_balance_owed"),
            <span className="ui-num">
              {usdFromCents(final.balance_usd_cents)}
            </span>,
          ],
          [
            mt(language, "fs_refund"),
            <span className="ui-num">{usdFromCents(refundTotal)}</span>,
          ],
        ]}
      />
      {petRestOpen && (
        <fieldset className="ui-radios">
          <legend>{mt(language, "fs_pet_other")}</legend>
          {staffMay ? (
            <>
              <p className="ui-small">{mt(language, "pd_pet_staff")}</p>
              <label className="ui-chk">
                <input
                  checked={basis === "CUSTOMER_CHOICE"}
                  name="pd-basis"
                  onChange={() => {
                    setBasis("CUSTOMER_CHOICE");
                  }}
                  type="radio"
                />
                <span>{mt(language, "pd_basis_customer")}</span>
              </label>
              <label className="ui-chk">
                <input
                  checked={basis === "STAFF_REASON"}
                  name="pd-basis"
                  onChange={() => {
                    setBasis("STAFF_REASON");
                  }}
                  type="radio"
                />
                <span>{mt(language, "pd_basis_staff")}</span>
              </label>
            </>
          ) : (
            <label className="ui-chk">
              <input
                checked={usePetRest}
                onChange={(event) => {
                  setUsePetRest(event.target.checked);
                }}
                type="checkbox"
              />
              <span>{mt(language, "fs_pet_choice")}</span>
            </label>
          )}
          {petRestOn && (
            <>
              {(!staffMay || basis === "CUSTOMER_CHOICE") && (
                <div className="ui-field">
                  <label htmlFor="pd-choice">
                    {mt(language, "pd_choice")}
                    <span className="req">{mt(language, "required")}</span>
                  </label>
                  <input
                    autoComplete="off"
                    id="pd-choice"
                    maxLength={2000}
                    onChange={(event) => {
                      setChoice(event.target.value);
                      setProblem(null);
                    }}
                    value={choice}
                  />
                </div>
              )}
              <div className="ui-field">
                <label htmlFor="pd-staff">
                  {mt(language, "pd_staff")}
                  <span className="req">{mt(language, "required")}</span>
                </label>
                <input
                  autoComplete="off"
                  id="pd-staff"
                  maxLength={1000}
                  onChange={(event) => {
                    setStaffReason(event.target.value);
                    setProblem(null);
                  }}
                  value={staffReason}
                />
              </div>
            </>
          )}
        </fieldset>
      )}
      {final.refunds.length > 0 &&
        (methods === "failed" ? (
          <div className="ui-notice warn" role="alert">
            <Icon name="alert" />
            <p>{mt(language, "pd_methods_failed")}</p>
          </div>
        ) : noMethod ? (
          <div className="ui-notice warn" role="alert">
            <Icon name="alert" />
            <p>{mt(language, "pd_no_methods")}</p>
          </div>
        ) : methods === null ? (
          <p className="ui-muted" role="status">
            …
          </p>
        ) : (
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="pd-method">{mt(language, "cf_method")}</label>
              <select
                id="pd-method"
                onChange={(event) => {
                  setMethod(event.target.value);
                  setProblem(null);
                }}
                value={method}
              >
                {methods.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="ui-field">
              <label htmlFor="pd-ref">
                {mt(language, "cf_ref")}
                {chosen !== undefined && !chosen.cash && (
                  <span className="req">{mt(language, "required")}</span>
                )}
              </label>
              <input
                autoComplete="off"
                className="ui-num"
                id="pd-ref"
                maxLength={500}
                onChange={(event) => {
                  setReference(event.target.value);
                  setProblem(null);
                }}
                value={reference}
              />
            </div>
          </div>
        ))}
      {final.refunds.length > 0 && (
        <p className="ui-small">
          {mt(language, "pd_to", lease.primary_tenant_name)}
        </p>
      )}
      <div className="ui-field">
        <label htmlFor="pd-reason">
          {mt(language, "pd_reason")}
          <span className="req">{mt(language, "required")}</span>
        </label>
        <input
          autoComplete="off"
          id="pd-reason"
          maxLength={1000}
          onChange={(event) => {
            setReason(event.target.value);
            setProblem(null);
          }}
          value={reason}
        />
      </div>
      <Problem message={problem} />
      <p className="ui-small ui-muted">{mt(language, "pd_c")}</p>
    </Dialog>
  );
}
