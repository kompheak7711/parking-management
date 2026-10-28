// V1-060 B6 (owner 27/10/2026): Receive Security Deposit on the Lease page. A walk-in Lease (one
// made without a Reservation) has no Security Deposit until one is set here; a Lease whose
// Security Deposit is not fully received takes the rest here. The money is saved first as a
// Payment with its Receipt (it pays no Invoice); the Security Deposit is then made (walk-in only)
// and takes its receipt from that Payment. Each step keeps one request identity while its values
// stay the same, so "Try again" never saves anything twice; the Payment is sent again with the
// very same body (V1-060 B7). While it is not known whether the money was saved, the boxes stay
// fixed, and Close asks once more while the money may be saved and the rest is not.

import { FormEvent, useRef, useState } from "react";

import type { DepositResource } from "../depositClient";
import type { LeaseResource } from "../leaseClient";
import {
  centsOf,
  dmt,
  keyFor,
  type MoneyChoice,
  MoneyFields,
  moneyProblem,
  outcomeAfter,
  paymentInput,
  requestFor,
  useCloseGuard,
  usePaymentMethods,
} from "../payments/depositMoney";
import type { ConfirmedPayment, PaymentsApi } from "../payments/paymentsClient";
import {
  type SettlementApi,
  SettlementRequestError,
} from "../settlementClient";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { lt } from "./text";

export function ReceiveDepositDialog({
  language,
  propertyId,
  lease,
  security,
  settlementApi,
  paymentsApi,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  lease: LeaseResource;
  /** The Lease's Security Deposit, or null for a walk-in Lease that has none yet. */
  security: DepositResource | null;
  settlementApi: Pick<
    SettlementApi,
    "createSecurityDeposit" | "receiveIntoDeposit"
  >;
  paymentsApi: PaymentsApi;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const methods = usePaymentMethods(paymentsApi, propertyId);
  const rent = lease.monthly_rent_usd_cents;
  const startRequired = rent === null ? "" : (rent / 100).toFixed(2);
  const [required, setRequired] = useState(startRequired);
  const [received, setReceived] = useState(
    security === null
      ? startRequired
      : (security.outstanding_required_usd_cents / 100).toFixed(2),
  );
  const [money, setMoney] = useState<MoneyChoice>({
    methodId: "",
    reference: "",
  });
  const [problems, setProblems] = useState<{
    required?: string;
    received?: string;
  }>({});
  const [moneyIssue, setMoneyIssue] = useState<
    "err_method" | "err_reference" | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<
    { kind: "unknown" } | { kind: "refused"; text: string } | null
  >(null);
  const [paid, setPaid] = useState<ConfirmedPayment | null>(null);
  const [depositId, setDepositId] = useState(security?.deposit_id ?? null);
  const paymentRequest = useRef<{
    fingerprint: string;
    key: string;
    body: ReturnType<typeof paymentInput>;
  } | null>(null);
  const depositKey = useRef<{ fingerprint: string; key: string } | null>(null);
  const receiptKey = useRef<{ fingerprint: string; key: string } | null>(null);
  const ids = useRef({
    deposit: crypto.randomUUID(),
    receipt: crypto.randomUUID(),
  });
  // The Payment's answer was lost: it may be saved, so nothing that makes it up may change.
  const pending = paid === null && outcome?.kind === "unknown";
  const guard = useCloseGuard(pending || paid !== null, onClose);

  const requiredCents = security === null ? centsOf(required) : null;
  const outstanding =
    security === null ? requiredCents : security.outstanding_required_usd_cents;

  function check(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    guard.reset();
    const found: typeof problems = {};
    const receivedCents = centsOf(received);
    if (security === null && requiredCents === null)
      found.required = lt(language, "rd_err_required");
    if (
      receivedCents === null ||
      (outstanding !== null && receivedCents > outstanding)
    )
      found.received = lt(language, "rd_err_received");
    const issue =
      paid !== null || methods === null || methods === "failed"
        ? null
        : moneyProblem(methods, money);
    setProblems(found);
    setMoneyIssue(issue);
    if (
      Object.keys(found).length > 0 ||
      issue !== null ||
      methods === null ||
      methods === "failed" ||
      receivedCents === null
    )
      return;
    void save(
      paymentInput(
        methods,
        money,
        lease.primary_tenant_id,
        receivedCents,
        lt("en", "rd_memo", lease.unit_number),
      ),
      receivedCents,
    );
  }

  async function save(
    payment: ReturnType<typeof paymentInput>,
    receivedCents: number,
  ) {
    // The try before this one: unknown means its answer was lost.
    const earlierUnknown = outcome?.kind === "unknown";
    setBusy(true);
    setOutcome(null);
    let money = paid;
    if (money === null) {
      try {
        const request = requestFor(paymentRequest, payment);
        money = await paymentsApi.confirm(
          propertyId,
          request.body,
          request.key,
        );
      } catch (error: unknown) {
        setOutcome(
          outcomeAfter(error, earlierUnknown) === "unknown"
            ? { kind: "unknown" }
            : { kind: "refused", text: lt(language, "rd_refused") },
        );
        setBusy(false);
        return;
      }
      setPaid(money);
    }
    try {
      let target = depositId;
      if (target === null) {
        const form = {
          deposit_id: ids.current.deposit,
          required_usd_cents: requiredCents ?? receivedCents,
          reason: lt("en", "rd_reason_create"),
        };
        await settlementApi.createSecurityDeposit(
          lease.lease_id,
          form,
          keyFor(depositKey, form),
        );
        target = form.deposit_id;
        setDepositId(target);
      }
      const receipt = {
        receipt_id: ids.current.receipt,
        payment_id: money.paymentId,
        amount_usd_cents: receivedCents,
        reason: lt("en", "rd_reason_receipt"),
      };
      await settlementApi.receiveIntoDeposit(
        target,
        receipt,
        keyFor(receiptKey, receipt),
      );
      onSaved(
        lt(
          language,
          "rd_toast",
          usdFromCents(receivedCents),
          money.receiptNumber,
        ),
      );
    } catch (error: unknown) {
      setOutcome(
        outcomeAfter(error, earlierUnknown) === "unknown"
          ? { kind: "unknown" }
          : {
              kind: "refused",
              text:
                error instanceof SettlementRequestError
                  ? error.message
                  : lt(language, "rd_refused"),
            },
      );
    } finally {
      setBusy(false);
    }
  }

  const error = (text: string | undefined) =>
    text === undefined ? null : (
      <p className="ui-error" role="alert">
        <Icon name="alert" small />
        <span>{text}</span>
      </p>
    );
  const locked = paid !== null || busy || pending;
  const stuck = outcome?.kind === "refused";

  return (
    <Dialog
      busy={busy}
      closeLabel={
        guard.asked ? dmt(language, "close_anyway") : lt(language, "close")
      }
      onClose={guard.close}
      onEscape={guard.escape}
      onSubmit={check}
      submitLabel={
        busy
          ? lt(language, "saving")
          : outcome !== null
            ? lt(language, "try_again")
            : lt(language, "rd_save")
      }
      title={lt(language, "rd_title", lease.unit_number)}
      wide
    >
      <p className="ui-muted">
        {lt(language, "rd_intro", lease.primary_tenant_name)}
      </p>
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="rd-required">{lt(language, "rd_required")}</label>
          {security === null ? (
            <>
              <input
                aria-invalid={problems.required !== undefined}
                disabled={locked || depositId !== null}
                id="rd-required"
                inputMode="decimal"
                onChange={(event) => {
                  setRequired(event.currentTarget.value);
                }}
                value={required}
              />
              <p className="help">{lt(language, "rd_required_help")}</p>
              {error(problems.required)}
            </>
          ) : (
            <p className="ui-num" id="rd-required">
              {usdFromCents(security.required_usd_cents)}
              <span className="ui-sub2">
                {lt(
                  language,
                  "rd_outstanding",
                  usdFromCents(security.outstanding_required_usd_cents),
                )}
              </span>
            </p>
          )}
        </div>
        <div className="ui-field">
          <label htmlFor="rd-received">{lt(language, "rd_received")}</label>
          <input
            aria-invalid={problems.received !== undefined}
            disabled={locked}
            id="rd-received"
            inputMode="decimal"
            onChange={(event) => {
              setReceived(event.currentTarget.value);
            }}
            value={received}
          />
          <p className="help">{lt(language, "rd_received_help")}</p>
          {error(problems.received)}
        </div>
      </div>
      <MoneyFields
        choice={money}
        disabled={locked}
        idPrefix="rd"
        language={language}
        methods={methods}
        onChange={setMoney}
        problem={moneyIssue}
      />
      <div className="ui-notice">
        <Icon name="info" />
        <p>{lt(language, "rd_note")}</p>
      </div>
      {paid !== null && (
        <div
          className={stuck ? "ui-notice warn" : "ui-notice info"}
          role="status"
        >
          <Icon name={stuck ? "alert" : "check"} />
          <p>
            {dmt(
              language,
              stuck ? "paid_stuck" : "paid_saved",
              paid.receiptNumber,
            )}
          </p>
        </div>
      )}
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {outcome.kind === "unknown"
              ? lt(language, "rd_unknown")
              : outcome.text}
          </p>
        </div>
      )}
      {guard.asked && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {paid === null
              ? dmt(language, "close_unknown")
              : dmt(language, "close_paid", paid.receiptNumber)}
          </p>
        </div>
      )}
    </Dialog>
  );
}
