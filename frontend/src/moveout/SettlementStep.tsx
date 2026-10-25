// V1-058 R3 Move-out M5: step 5, the Final Settlement (DESIGN.md "Move-out (round 3)"). The
// step reads the Lease's Settlement without opening one; a preparer opens it, and the page then
// shows the statement in the design's fixed order: the open Invoices and charges, the
// Customers' own Credit, the Pet Deposit for pet damage, the Security Deposit (or "Kept", never
// a payment), the rest of the Pet Deposit, and what blocks the Settlement. The money rules are
// the server's: amounts here are what the preview gives, never worked out on the page.

import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type { LeaseResource } from "../leaseClient";
import {
  SettlementRequestError,
  type SettlementApi,
} from "../settlementClient";
import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import { Kv, type Mark, Step } from "./parts";
import {
  type SettlementDeposit,
  type SettlementPreview,
  type SettlementState,
  issueCodes,
  readPreview,
  settlementOf,
} from "./settlement";
import { mt, type MoveOutTextKey } from "./text";

export type SettlementStepApi = Pick<
  SettlementApi,
  "settlements" | "startSettlement" | "settlementPreview"
>;

type Loaded =
  | { state: "loading" }
  | { state: "hidden" }
  | { state: "failed" }
  | { state: "none" }
  | {
      state: "shown";
      settlement: SettlementState;
      /** null: closed, or the preview could not be read. */
      preview: SettlementPreview | null;
    };

const PREPARE = "final_settlements.prepare";
const APPROVE = "financial.approve";

/** What a blocking issue asks for, in plain words. */
function issueText(language: Language, code: string): string {
  const key = `fi_${code}`;
  return mt(language, (key in FI_KEYS ? key : "fi_OTHER") as MoveOutTextKey);
}

const FI_KEYS: Record<string, true> = {
  fi_FINAL_UTILITY_NOT_ISSUED: true,
  fi_UTILITY_PERIOD_NOT_BILLED: true,
  fi_CLEANING_CHARGE_MISSING: true,
  fi_LATE_PAYMENT_DECISION_MISSING: true,
  fi_FORFEITURE_NOT_CONFIRMED: true,
  fi_PENDING_DRAFT: true,
  fi_ONE_TIME_CHARGE_NOT_INVOICED: true,
  fi_INVOICE_DRAFT_NOT_ISSUED: true,
};

export function SettlementStep({
  language,
  propertyId,
  lease,
  api,
  capabilities,
  reachable,
  names,
  version,
  onStarted,
}: {
  language: Language;
  propertyId: string;
  lease: LeaseResource;
  api: SettlementStepApi;
  capabilities: ReadonlySet<string> | null;
  /** The Lease is terminated and the Unit handed back (or never moved into). */
  reachable: boolean;
  /** Customer names by id, for owed lines of more than one Customer. */
  names: Map<string, string>;
  /** Changes when the page reads everything again. */
  version: number;
  onStarted: () => void;
}) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const mayPrepare = may(PREPARE);
  const mayRead = mayPrepare || may(APPROVE);
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<"unknown" | "refused" | null>(null);
  const key = useRef<string | null>(null);
  const sequence = useRef(0);
  const leaseId = lease.lease_id;

  const load = useCallback(() => {
    const operation = ++sequence.current;
    const current = () => operation === sequence.current;
    if (!mayRead) {
      setLoaded({ state: "hidden" });
      return;
    }
    void (async () => {
      const settlement = settlementOf(
        await api.settlements(propertyId, leaseId),
        leaseId,
      );
      if (!current()) return;
      if (settlement === null) {
        setLoaded({ state: "none" });
        return;
      }
      // A closed Settlement's statement is what it applied; step 6 shows what came after.
      const preview = settlement.closed
        ? null
        : await api
            .settlementPreview(propertyId, settlement.id)
            .then(readPreview)
            .catch(() => null);
      if (current()) setLoaded({ state: "shown", settlement, preview });
    })().catch(() => {
      if (current()) setLoaded({ state: "failed" });
    });
  }, [api, propertyId, leaseId, mayRead]);

  useEffect(() => {
    load();
  }, [load, version]);

  function start() {
    if (busy) return;
    setBusy(true);
    setOutcome(null);
    // The Lease is the server's identity for opening its Settlement; one key keeps Try again
    // the same request.
    key.current ??= crypto.randomUUID();
    api
      .startSettlement(propertyId, leaseId, key.current)
      .then(() => {
        onStarted();
        load();
      })
      .catch((error: unknown) => {
        setOutcome(
          // A timeout or "too many requests" may still be done: Try again.
          error instanceof SettlementRequestError &&
            error.status >= 400 &&
            error.status < 500 &&
            error.status !== 408 &&
            error.status !== 429
            ? "refused"
            : "unknown",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const settlement = loaded.state === "shown" ? loaded.settlement : null;
  const mark: Mark = settlement?.closed
    ? "done"
    : settlement !== null || reachable
      ? "now"
      : "todo";
  const actions =
    loaded.state === "none" && reachable && mayPrepare ? (
      <button
        className="ui-btn primary"
        disabled={busy}
        onClick={start}
        type="button"
      >
        <Icon name="list" />
        {busy
          ? mt(language, "saving")
          : outcome === "unknown"
            ? mt(language, "try_again")
            : mt(language, "st5_start")}
      </button>
    ) : undefined;

  return (
    <Step
      actions={actions}
      language={language}
      mark={mark}
      number={5}
      title={mt(language, "st5_t")}
    >
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {mt(language, outcome === "unknown" ? "c_unknown" : "st5_refused")}
          </p>
        </div>
      )}
      {loaded.state === "hidden" ? (
        <p className="ui-small ui-muted">{mt(language, "st5_hidden")}</p>
      ) : loaded.state === "failed" ? (
        <p className="ui-muted">
          {mt(language, "st5_failed")}{" "}
          <button className="ui-btn link" onClick={load} type="button">
            {mt(language, "retry")}
          </button>
        </p>
      ) : loaded.state === "loading" ? (
        <p className="ui-muted" role="status">
          {mt(language, "st5_reading")}
        </p>
      ) : loaded.state === "none" ? (
        <>
          <p>{mt(language, reachable ? "st5_todo" : "st5_wait")}</p>
          {reachable && !mayPrepare && (
            <p className="ui-small ui-muted">
              {mt(language, "st5_not_allowed")}
            </p>
          )}
        </>
      ) : (
        <Shown
          language={language}
          lease={lease}
          mayApprove={may(APPROVE)}
          names={names}
          preview={loaded.preview}
          settlement={loaded.settlement}
        />
      )}
    </Step>
  );
}

function Shown({
  language,
  lease,
  settlement,
  preview,
  names,
  mayApprove,
}: {
  language: Language;
  lease: LeaseResource;
  settlement: SettlementState;
  preview: SettlementPreview | null;
  names: Map<string, string>;
  mayApprove: boolean;
}) {
  if (settlement.closed) {
    const owed = settlement.closing_balance_due_usd_cents ?? 0;
    return (
      <>
        <p>
          {mt(
            language,
            "st5_closed",
            settlement.closed_at === null
              ? "—"
              : momentText(settlement.closed_at),
          )}
        </p>
        {owed > 0 && (
          <p className="ui-small">
            {mt(language, "st5_closed_owed", usdFromCents(owed))}
          </p>
        )}
      </>
    );
  }
  return (
    <>
      <p>{mt(language, "st5_open", momentText(settlement.started_at))}</p>
      {settlement.pending_draft && (
        <div className="ui-notice warn" role="note">
          <Icon name="lock" />
          <p>
            {mt(language, "st5_waiting")}{" "}
            {mayApprove && (
              <a href={hashForPage("approvals")}>
                {mt(language, "st5_open_approvals")}
              </a>
            )}
          </p>
        </div>
      )}
      {preview === null ? (
        <p className="ui-muted">{mt(language, "st5_no_preview")}</p>
      ) : (
        <Statement
          language={language}
          lease={lease}
          names={names}
          preview={preview}
          waiting={settlement.pending_draft}
        />
      )}
    </>
  );
}

function depositRow(
  language: Language,
  deposit: SettlementDeposit,
  petOpen: number,
): [string, ReactNode] {
  const held = usdFromCents(deposit.held_usd_cents);
  const security = deposit.deposit_type === "SECURITY";
  if (deposit.path === "KEPT")
    return [
      mt(language, security ? "fs_sec_kept" : "fs_pet_kept"),
      <span className="ui-num">
        {held}
        <span className="ui-sub2">{mt(language, "fs_kept_n")}</span>
      </span>,
    ];
  if (deposit.path === "FORFEITURE_REQUIRED" || deposit.path === "NOTHING_HELD")
    return [
      mt(language, security ? "dep_SECURITY" : "dep_PET"),
      <span className="ui-num">
        {held}
        <span className="ui-sub2">
          {mt(
            language,
            deposit.path === "NOTHING_HELD" ? "fs_kept_none" : "fs_kept_first",
          )}
        </span>
      </span>,
    ];
  return [
    mt(language, security ? "dep_SECURITY" : "fs_pet_dmg"),
    <span className="ui-num">
      {mt(language, "dep_held", held)}
      <span className="ui-sub2">
        {security
          ? mt(language, "fs_sec_n")
          : mt(language, "fs_pet_dmg_n", usdFromCents(petOpen))}
      </span>
    </span>,
  ];
}

function Statement({
  language,
  lease,
  preview,
  names,
  waiting,
}: {
  language: Language;
  lease: LeaseResource;
  preview: SettlementPreview;
  names: Map<string, string>;
  /** A draft of this Settlement waits for a Manager: nothing more to prepare. */
  waiting: boolean;
}) {
  const many = preview.customers.filter(
    (customer) => customer.open_total_usd_cents > 0,
  ).length;
  // The Customer is named only when more than one owes.
  const who = (customerId: string) =>
    many > 1
      ? (names.get(customerId) ?? mt(language, "fs_other_customer"))
      : null;
  const owed = preview.customers.flatMap((customer) => [
    ...customer.invoice_lines.map((line) => (
      <li key={line.invoice_line_id}>
        <span>
          <a href={hashForPage("invoices", `inv:${line.invoice_id}`)}>
            {line.description}
          </a>
          <small>
            {mt(language, "fs_due", dayText(line.due_date))}
            {line.pet_damage ? ` · ${mt(language, "st4_pet")}` : ""}
            {who(line.customer_id) === null
              ? ""
              : ` · ${who(line.customer_id) ?? ""}`}
          </small>
        </span>
        <b className="ui-num">{usdFromCents(line.outstanding_usd_cents)}</b>
      </li>
    )),
    ...customer.late_payment_charges.map((charge) => (
      <li key={charge.late_payment_charge_id}>
        <span>
          <a href={hashForPage("invoices", `inv:${charge.source_invoice_id}`)}>
            {mt(language, "fs_late")}
          </a>
          {who(charge.customer_id) !== null && (
            <small>{who(charge.customer_id)}</small>
          )}
        </span>
        <b className="ui-num">{usdFromCents(charge.remaining_usd_cents)}</b>
      </li>
    )),
  ]);
  const pets = preview.deposits.filter((item) => item.deposit_type === "PET");
  const security = preview.deposits.filter(
    (item) => item.deposit_type === "SECURITY",
  );
  const petPays = pets.some((item) => item.path === "DL_032");
  const rows: [string, ReactNode][] = [
    [
      mt(language, "fs_owed"),
      <span className="ui-num">
        {usdFromCents(preview.open_total_usd_cents)}
      </span>,
    ],
  ];
  // Each Customer's own Credit pays only that Customer's debt: one row each.
  for (const customer of preview.customers)
    if (customer.credit_may_use_usd_cents > 0)
      rows.push([
        mt(language, "fs_credit"),
        <span className="ui-num">
          {mt(
            language,
            "fs_credit_may",
            usdFromCents(customer.credit_may_use_usd_cents),
          )}
          {who(customer.customer_id) !== null &&
            ` · ${who(customer.customer_id) ?? ""}`}
          <span className="ui-sub2">{mt(language, "fs_credit_n")}</span>
        </span>,
      ]);
  for (const deposit of pets)
    rows.push(depositRow(language, deposit, preview.pet_damage_open_usd_cents));
  for (const deposit of security)
    rows.push(depositRow(language, deposit, preview.pet_damage_open_usd_cents));
  if (petPays)
    rows.push([
      mt(language, "fs_pet_other"),
      <span className="ui-small">
        {mt(
          language,
          preview.pet_remainder_chosen_by === "CUSTOMER_ONLY"
            ? "fs_pet_other_n"
            : "fs_pet_other_staff",
        )}
      </span>,
    ]);
  rows.push([
    mt(language, "fs_balance"),
    <span className="ui-small">{mt(language, "fs_later")}</span>,
  ]);
  const codes = issueCodes(preview.blocking_issues);
  return (
    <>
      <h4>{mt(language, "st5_statement")}</h4>
      <Kv rows={rows} />
      {owed.length > 0 && <ul className="ui-apps">{owed}</ul>}
      {preview.voided_not_billed_usd_cents.length > 0 && (
        <p className="ui-small ui-muted">
          {mt(
            language,
            "fs_voided",
            preview.voided_not_billed_usd_cents.map(usdFromCents).join(", "),
          )}
        </p>
      )}
      {codes.length > 0 ? (
        <div className="ui-notice warn" role="note">
          <Icon name="alert" />
          <div>
            <p>{mt(language, "st5_blocked")}</p>
            <ul>
              {codes.map((code) => (
                <li key={code}>{issueText(language, code)}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : preview.ready && !waiting ? (
        <p className="ui-small">
          {mt(language, "st5_ready", lease.unit_number)}
        </p>
      ) : null}
    </>
  );
}
