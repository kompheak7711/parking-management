// V1-060 B6 (DL-106): Record kept Deposit on the Final Settlement step. A termination that keeps a
// Deposit (leaving before the End Date, broken pet rules, unpaid Initial Rent, a broken Lease or a
// 30-day Rent default) blocks the Settlement until the kept record is confirmed, and no screen
// recorded it before. The Owner or a Manager (deposits.dispose) records here a draft that keeps
// the whole held amount; nothing is kept until the Owner or a Manager confirms it in Waiting for
// approval. The server works out the ground and the amount again; the page only names them.

import { FormEvent, useRef, useState } from "react";

import type { LeaseResource } from "../leaseClient";
import { Problem } from "../leases/LeaseDialogs";
import {
  SettlementRequestError,
  type SettlementApi,
} from "../settlementClient";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import { serverWords } from "../shell/serverText";
import type { Language } from "../signInText";
import { keyFor, type Keys } from "./ChargeDialogs";
import { Kv } from "./parts";
import type { SettlementDeposit } from "./settlement";
import { mt, type MoveOutTextKey } from "./text";

export type KeepDepositApi = Pick<SettlementApi, "forfeitureDraft">;

// The termination grounds of app.lease_deposit_forfeiture_rule.
const GROUNDS: Record<string, MoveOutTextKey> = {
  "BR-DEP-023": "kd_g_early",
  "BR-DEP-022": "kd_g_pet",
  "BR-LEASE-005": "kd_g_initial",
  "BR-LEASE-025": "kd_g_broken",
  "BR-LEASE-028": "kd_g_default",
};

// Refusals named in plain words; any other shows the server's own words.
const REFUSALS: Record<string, MoveOutTextKey> = {
  DEPOSIT_FORFEITURE_NO_GROUND: "kd_r_DEPOSIT_FORFEITURE_NO_GROUND",
  DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED:
    "kd_r_DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED",
  DEPOSIT_FORFEITURE_NOTHING_HELD: "kd_r_DEPOSIT_FORFEITURE_NOTHING_HELD",
  DEPOSIT_FORFEITURE_PET_AT_SETTLEMENT:
    "kd_r_DEPOSIT_FORFEITURE_PET_AT_SETTLEMENT",
  FINAL_SETTLEMENT_CLOSED: "kd_r_FINAL_SETTLEMENT_CLOSED",
  DRAFT_RECORD_ID_IN_USE: "kd_r_DRAFT_RECORD_ID_IN_USE",
};

/** Why the termination keeps the Deposit, from the ground's rule id. */
export function groundText(language: Language, ground: string | null): string {
  return mt(language, GROUNDS[ground ?? ""] ?? "kd_g_other");
}

export function keepLabel(
  language: Language,
  deposit: SettlementDeposit,
): string {
  return mt(
    language,
    deposit.deposit_type === "SECURITY" ? "kd_btn_SECURITY" : "kd_btn_PET",
  );
}

export function KeepDepositDialog({
  language,
  propertyId,
  lease,
  deposit,
  api,
  onClose,
  onSaved,
  onWaiting,
}: {
  language: Language;
  propertyId: string;
  lease: LeaseResource;
  deposit: SettlementDeposit;
  api: KeepDepositApi;
  onClose: () => void;
  onSaved: () => void;
  /** A draft that keeps this Deposit already waits (someone else, or a lost answer). */
  onWaiting: () => void;
}) {
  // Stored records keep English text, like every record.
  const [reason, setReason] = useState(
    mt("en", "kd_reason_default", groundText("en", deposit.ground)),
  );
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<
    { unknown: true } | { refused: string } | null
  >(null);
  const keys = useRef<Keys>(new Map());

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const text = reason.trim();
    if (text === "") {
      setProblem(mt(language, "kd_err"));
      return;
    }
    setProblem(null);
    setBusy(true);
    setOutcome(null);
    // Try again with the same reason sends the very same request: the same record id and key.
    // A changed reason is a new request, so the server never sees one key with two forms.
    api
      .forfeitureDraft(
        propertyId,
        deposit.deposit_id,
        {
          reason: text,
          disposition_id: keyFor(keys.current, "disposition", text),
        },
        keyFor(keys.current, "keep", text),
      )
      .then(() => {
        onSaved();
      })
      .catch((error: unknown) => {
        if (
          error instanceof SettlementRequestError &&
          error.code === "DEPOSIT_FORFEITURE_DRAFT_WAITING"
        ) {
          onWaiting();
          return;
        }
        // A timeout or "too many requests" may still be done: Try again.
        const refused =
          error instanceof SettlementRequestError &&
          error.status >= 400 &&
          error.status < 500 &&
          error.status !== 408 &&
          error.status !== 429;
        if (!refused) {
          setOutcome({ unknown: true });
          return;
        }
        const named = REFUSALS[error.code ?? ""];
        setOutcome({
          refused:
            error.status === 403
              ? mt(language, "ur_FORBIDDEN")
              : named === undefined
                ? serverWords(language, error)
                : mt(language, named),
        });
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
            : mt(language, "pd_ok")
      }
      title={`${keepLabel(language, deposit)} · ${lease.unit_number}`}
    >
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
            mt(language, "kd_deposit"),
            mt(
              language,
              deposit.deposit_type === "SECURITY" ? "dep_SECURITY" : "dep_PET",
            ),
          ],
          [
            mt(language, "kd_amount"),
            <span className="ui-num">
              {mt(language, "kd_all", usdFromCents(deposit.held_usd_cents))}
            </span>,
          ],
          [mt(language, "kd_why"), groundText(language, deposit.ground)],
        ]}
      />
      <div className="ui-field">
        <label htmlFor="kd-reason">
          {mt(language, "pd_reason")}
          <span className="req">{mt(language, "required")}</span>
        </label>
        <input
          autoComplete="off"
          id="kd-reason"
          maxLength={1000}
          onChange={(event) => {
            setReason(event.target.value);
            setProblem(null);
          }}
          value={reason}
        />
      </div>
      <Problem message={problem} />
      <p className="ui-small ui-muted">{mt(language, "kd_note")}</p>
    </Dialog>
  );
}
