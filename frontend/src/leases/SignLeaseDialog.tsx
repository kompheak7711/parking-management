// V1-060 B6 (owner 27/10/2026, DL-100): Sign Lease receives the money first. The dialog shows
// what the customer pays at signing: the Security Deposit (the walk-in draft's planned amount,
// or the rest of a Booking's deposit; a renewal keeps the old one) and the Initial Rent Invoice
// as billing will make it (Rent and Services). The full total is saved as one Payment with its
// Receipt; only then are the signatures recorded and the Lease signed. Right after, the Initial
// Rent Invoice is made, the Payment pays it, and the rest goes into the Security Deposit. Each
// step keeps one request identity, so "Try again" carries on where an earlier try stopped and
// never saves anything twice.
// DL-101 (owner 27/10/2026): a draft from a Booking records its own Security Deposit, starting
// at the Reservation's amount; right after signing that amount becomes the required amount of
// the Reservation's Security Deposit, and the rest of it is received.

import { FormEvent, useEffect, useRef, useState } from "react";

import {
  LeaseConflictError,
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
} from "../leaseClient";
import {
  dmt,
  keyFor,
  type MoneyChoice,
  MoneyFields,
  moneyProblem,
  outcomeOf,
  paymentInput,
  usePaymentMethods,
} from "../payments/depositMoney";
import type { ConfirmedPayment, PaymentsApi } from "../payments/paymentsClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import {
  type SettlementApi,
  SettlementRequestError,
  SettlementUnavailableError,
  type SigningPreview,
} from "../settlementClient";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { centsOf, Problem, useIdentities } from "./LeaseDialogs";
import { lt } from "./text";

// The reason stored with each signature; the dialog's tick is the person's statement.
const SIGN_REASON = "Every Signer signed the paper Lease";

type Loaded<T> =
  | { state: "loading" }
  | { state: "failed" }
  | { state: "done"; value: T };

/** The active Reservation of this Lease's Primary Tenant for its Unit, if there is one. */
async function activeReservationOf(
  api: Pick<ReservationApi, "list">,
  lease: LeaseResource,
): Promise<ReservationResource | null> {
  let cursor: string | undefined;
  for (;;) {
    const page = await api.list(lease.property_id, "ACTIVE", cursor);
    const found = page.items.find(
      (item) =>
        item.unit_id === lease.unit_id &&
        item.customer_id === lease.primary_tenant_id,
    );
    if (found !== undefined) return found;
    if (page.next_cursor === null) return null;
    cursor = page.next_cursor;
  }
}

function useLoaded<T>(load: () => Promise<T>): Loaded<T> {
  const [loaded, setLoaded] = useState<Loaded<T>>({ state: "loading" });
  useEffect(() => {
    let live = true;
    load()
      .then((value) => {
        if (live) setLoaded({ state: "done", value });
      })
      .catch(() => {
        if (live) setLoaded({ state: "failed" });
      });
    return () => {
      live = false;
    };
  }, []);
  return loaded;
}

export type SigningApi = Pick<
  SettlementApi,
  | "signingPreview"
  | "makeInitialRentInvoice"
  | "applyPlannedSecurityDeposit"
  | "allocationProposal"
  | "allocateByProposal"
  | "createSecurityDeposit"
  | "receiveIntoDeposit"
>;

export function SignDialog({
  language,
  api,
  lease,
  propertyId,
  reservationApi,
  signingApi,
  paymentsApi,
  mayCollect,
  mayCreateDeposit,
  onClose,
  onSaved,
  onConflict,
  onProgress,
}: {
  language: Language;
  api: LeaseApi;
  lease: LeaseResource;
  propertyId: string;
  reservationApi: Pick<ReservationApi, "list">;
  signingApi: SigningApi;
  paymentsApi: PaymentsApi;
  /** payments.record and payments.allocate: the money is received in this dialog. */
  mayCollect: boolean;
  /** deposits.manage: a walk-in Lease's Security Deposit is made in this dialog. */
  mayCreateDeposit: boolean;
  onClose: () => void;
  onSaved: (saved: LeaseResource, message: string) => void;
  onConflict: () => void;
  /** Each recorded signature, so the page shows it even if a later step fails. */
  onProgress: (current: LeaseResource) => void;
}) {
  const unsigned = lease.signers.filter((signer) => signer.signed_at === null);
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const [wrong, setWrong] = useState(false);
  const preview = useLoaded<SigningPreview>(() =>
    signingApi.signingPreview(lease.lease_id),
  );
  const reservation = useLoaded<ReservationResource | null>(() =>
    activeReservationOf(reservationApi, lease),
  );
  const methods = usePaymentMethods(paymentsApi, propertyId);
  const [deposit, setDeposit] = useState<string | null>(null);
  const [depositProblem, setDepositProblem] = useState<string | null>(null);
  const [money, setMoney] = useState<MoneyChoice>({
    methodId: "",
    reference: "",
  });
  const [moneyIssue, setMoneyIssue] = useState<
    "err_method" | "err_reference" | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<
    { kind: "unknown" } | { kind: "refused"; text: string } | null
  >(null);
  const [paid, setPaid] = useState<ConfirmedPayment | null>(null);
  const identity = useIdentities();
  const paymentKey = useRef<{ fingerprint: string; key: string } | null>(null);
  // How far an earlier try got, so a retry carries on from there.
  const progress = useRef<{
    lease: LeaseResource;
    signed: LeaseResource | null;
    applied: boolean;
    invoiced: boolean;
    proposal: Record<string, unknown> | null;
    allocated: boolean;
    depositId: string | null;
  }>({
    lease,
    signed: null,
    applied: false,
    invoiced: false,
    proposal: null,
    allocated: false,
    depositId: null,
  });

  const initial = preview.state === "done" ? preview.value.initial : null;
  // Reservations that cannot be read are treated as none, as before: the server refuses to sign
  // a Reserved Unit without its Reservation.
  const booking = reservation.state === "done" ? reservation.value : null;
  const renewal = lease.predecessor_lease_id !== null;
  // A draft from a Booking names the Booking's deposit, and signing completes the Customer's
  // active Booking of this Unit; either way the Booking's deposit continues and its rest is paid.
  const held =
    preview.state === "done" ? preview.value.held_security_deposit : null;
  const fromBooking =
    lease.security_deposit_id !== null || booking !== null || held !== null;
  const walkIn = !renewal && !fromBooking;
  const planned =
    preview.state === "done"
      ? preview.value.planned_security_deposit_usd_cents
      : null;
  // A Booking's Security Deposit: the draft's amount (DL-101), or the Reservation's.
  const bookingDeposit =
    held !== null
      ? {
          depositId: held.deposit_id,
          required: planned ?? held.required_usd_cents,
          received: held.received_usd_cents,
        }
      : booking !== null
        ? {
            depositId: booking.deposit_id,
            required: planned ?? booking.deposit_required_usd_cents,
            received: booking.deposit_received_usd_cents,
          }
        : null;
  const depositText =
    deposit ??
    ((planned ?? lease.monthly_rent_usd_cents ?? 0) / 100).toFixed(2);
  const depositDue = renewal
    ? 0
    : bookingDeposit !== null
      ? Math.max(0, bookingDeposit.required - bookingDeposit.received)
      : fromBooking
        ? 0
        : (centsOf(depositText) ?? 0);
  // Signing completes the Booking, so it must be read (the server refuses a Reserved Unit
  // without its Reservation).
  const bookingUnknown = fromBooking && booking === null;
  // The draft's amount becomes the required amount after signing, so it cannot be less than
  // the money the Reservation already received.
  const belowReceived =
    bookingDeposit !== null &&
    bookingDeposit.required < bookingDeposit.received;
  const rentDue = initial?.total_usd_cents ?? 0;
  const total = depositDue + rentDue;
  const ready =
    preview.state === "done" &&
    reservation.state !== "loading" &&
    initial !== null &&
    initial.problem === null &&
    !bookingUnknown &&
    !belowReceived &&
    mayCollect &&
    (!walkIn || mayCreateDeposit);
  const blocker =
    preview.state === "failed"
      ? lt(language, "sp_failed")
      : preview.state === "done" && initial === null
        ? lt(language, "sp_no_terms")
        : initial?.problem != null
          ? lt(language, "sp_problem", initial.problem.replace(/^[A-Z_]+:/, ""))
          : bookingUnknown && reservation.state !== "loading"
            ? lt(language, "sp_no_booking")
            : belowReceived
              ? lt(
                  language,
                  "sp_deposit_below",
                  usdFromCents(bookingDeposit.received),
                )
              : !mayCollect
                ? lt(language, "sp_no_rights")
                : walkIn && !mayCreateDeposit && reservation.state === "done"
                  ? lt(language, "sp_no_deposit_right")
                  : null;

  async function sign(reservationId: string | null): Promise<LeaseResource> {
    let current = progress.current.lease;
    for (const signer of unsigned) {
      const now = current.signers.find(
        (entry) => entry.signer_id === signer.signer_id,
      );
      if (typeof now?.signed_at === "string") continue;
      const step = identity(`signer:${signer.signer_id}`);
      current = await api.recordSignature(
        current,
        signer.signer_id,
        { event_id: step.id, reason: SIGN_REASON },
        step.key,
      );
      progress.current.lease = current;
      onProgress(current);
    }
    const step = identity("sign");
    return api.sign(
      current,
      reservationId === null
        ? { event_id: step.id, reason: SIGN_REASON }
        : {
            event_id: step.id,
            reason: SIGN_REASON,
            reservation_id: reservationId,
          },
      step.key,
    );
  }

  async function run(payment: ReturnType<typeof paymentInput>) {
    const done = progress.current;
    let money = paid;
    if (money === null) {
      money = await paymentsApi.confirm(
        propertyId,
        payment,
        keyFor(paymentKey, { ...payment, received_at: null }),
      );
      setPaid(money);
    }
    if (done.signed === null) {
      done.signed = await sign(booking?.reservation_id ?? null);
      onProgress(done.signed);
    }
    if (bookingDeposit !== null && planned !== null && !done.applied) {
      await signingApi.applyPlannedSecurityDeposit(
        lease.lease_id,
        identity("apply").key,
      );
      done.applied = true;
    }
    if (rentDue > 0 && !done.invoiced) {
      await signingApi.makeInitialRentInvoice(
        lease.lease_id,
        identity("invoice").key,
      );
      done.invoiced = true;
    }
    if (rentDue > 0 && !done.allocated) {
      done.proposal ??= await signingApi.allocationProposal(
        propertyId,
        money.paymentId,
      );
      await signingApi.allocateByProposal(
        propertyId,
        money.paymentId,
        done.proposal,
        identity("allocate").key,
      );
      done.allocated = true;
    }
    if (depositDue > 0) {
      if (done.depositId === null) {
        if (bookingDeposit !== null) done.depositId = bookingDeposit.depositId;
        else {
          const step = identity("deposit");
          await signingApi.createSecurityDeposit(
            lease.lease_id,
            {
              deposit_id: step.id,
              required_usd_cents: depositDue,
              reason: lt("en", "sp_reason_create"),
            },
            step.key,
          );
          done.depositId = step.id;
        }
      }
      const step = identity("receipt");
      await signingApi.receiveIntoDeposit(
        done.depositId,
        {
          receipt_id: step.id,
          payment_id: money.paymentId,
          amount_usd_cents: depositDue,
          reason: lt("en", "sp_reason_receipt"),
        },
        step.key,
      );
    }
    onSaved(
      done.signed,
      lt(
        language,
        "sp_toast",
        lease.unit_number,
        usdFromCents(total),
        money.receiptNumber,
      ),
    );
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready) return;
    const all = unsigned.every(
      (signer) =>
        ticked.has(signer.signer_id) ||
        progress.current.lease.signers.some(
          (entry) =>
            entry.signer_id === signer.signer_id && entry.signed_at !== null,
        ),
    );
    setWrong(!all);
    const badDeposit = walkIn && centsOf(depositText) === null;
    setDepositProblem(badDeposit ? lt(language, "err_deposit") : null);
    const issue =
      paid !== null || methods === null || methods === "failed"
        ? null
        : moneyProblem(methods, money);
    setMoneyIssue(issue);
    if (
      !all ||
      badDeposit ||
      issue !== null ||
      methods === null ||
      methods === "failed" ||
      total <= 0
    )
      return;
    const payment = paymentInput(
      methods,
      money,
      lease.primary_tenant_id,
      total,
      lt("en", "sp_memo", lease.unit_number),
    );
    setBusy(true);
    setOutcome(null);
    run(payment)
      .catch((error: unknown) => {
        if (error instanceof LeaseConflictError) {
          onConflict();
          return;
        }
        setOutcome(
          error instanceof SettlementRequestError
            ? { kind: "refused", text: error.message }
            : error instanceof SettlementUnavailableError ||
                error instanceof LeaseUnavailableError ||
                outcomeOf(error) === "unknown"
              ? { kind: "unknown" }
              : { kind: "refused", text: lt(language, "sign_refused") },
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const locked = paid !== null || busy;
  const rent = lease.monthly_rent_usd_cents;

  return (
    <Dialog
      busy={
        busy || preview.state === "loading" || reservation.state === "loading"
      }
      closeLabel={lt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? lt(language, "saving")
          : outcome !== null
            ? lt(language, "try_again")
            : lt(language, "sp_ok", usdFromCents(total))
      }
      title={lt(language, "sign_title", lease.unit_number)}
      wide
    >
      <p className="ui-small ui-num">
        {lease.primary_tenant_name} ·{" "}
        {lt(
          language,
          "from_to",
          dayText(lease.start_date),
          dayText(lease.end_date),
        )}
        {rent !== null &&
          ` · ${lt(language, "rent_month", usdFromCents(rent))}`}
      </p>
      <fieldset className="ui-radios">
        <legend>{lt(language, "sign_confirm")}</legend>
        {lease.signers.map((signer) => {
          const done = signer.signed_at !== null;
          return (
            <label className="ui-chk" key={signer.signer_id}>
              <input
                checked={done || ticked.has(signer.signer_id)}
                disabled={done || busy}
                onChange={(event) => {
                  const next = new Set(ticked);
                  if (event.currentTarget.checked) next.add(signer.signer_id);
                  else next.delete(signer.signer_id);
                  setTicked(next);
                }}
                type="checkbox"
              />
              <span>
                {signer.customer_name}
                {signer.is_primary_tenant &&
                  ` · ${lt(language, "primary_tag")}`}
                {signer.signed_at !== null &&
                  ` · ${lt(language, "sign_already", dayText(todayInPhnomPenh(new Date(signer.signed_at))))}`}
              </span>
            </label>
          );
        })}
        <Problem message={wrong ? lt(language, "sign_all") : null} />
      </fieldset>
      <h3>{lt(language, "sp_money")}</h3>
      {preview.state === "loading" || reservation.state === "loading" ? (
        <p className="ui-small ui-muted" role="status">
          {lt(language, "sp_loading")}
        </p>
      ) : (
        initial !== null && (
          <table className="ui-table ui-num">
            <tbody>
              {!renewal && (
                <tr>
                  <td>
                    {bookingDeposit !== null ? (
                      lt(
                        language,
                        "sp_deposit_rest",
                        usdFromCents(bookingDeposit.received),
                        usdFromCents(bookingDeposit.required),
                      )
                    ) : (
                      <label htmlFor="sign-deposit">
                        {lt(language, "sp_deposit")}
                      </label>
                    )}
                  </td>
                  <td>
                    {walkIn ? (
                      <input
                        aria-invalid={depositProblem !== null}
                        disabled={locked}
                        id="sign-deposit"
                        inputMode="decimal"
                        onChange={(event) => {
                          setDeposit(event.currentTarget.value);
                        }}
                        value={depositText}
                      />
                    ) : (
                      usdFromCents(depositDue)
                    )}
                    <Problem message={depositProblem} />
                  </td>
                </tr>
              )}
              <tr>
                <td>
                  {lt(
                    language,
                    "sp_rent",
                    dayText(initial.period_start),
                    dayText(initial.period_end),
                  )}
                </td>
                <td>{usdFromCents(initial.rent_usd_cents)}</td>
              </tr>
              {initial.service_lines.map((line) => (
                <tr key={`${line.name}/${line.period_start}`}>
                  <td>
                    {lt(
                      language,
                      "sp_service",
                      line.name,
                      dayText(line.period_start),
                      dayText(line.period_end),
                    )}
                  </td>
                  <td>{usdFromCents(line.amount_usd_cents)}</td>
                </tr>
              ))}
              <tr>
                <th scope="row">{lt(language, "sp_total")}</th>
                <th>{usdFromCents(total)}</th>
              </tr>
            </tbody>
          </table>
        )
      )}
      <h3>{lt(language, "sign_what")}</h3>
      <ul className="ui-small">
        <li>{lt(language, "sign_s1", lease.unit_number)}</li>
        {booking !== null && <li>{lt(language, "sign_s2")}</li>}
      </ul>
      {blocker !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{blocker}</p>
        </div>
      )}
      {ready && (
        <>
          <MoneyFields
            choice={money}
            disabled={locked}
            idPrefix="sign"
            language={language}
            methods={methods}
            onChange={setMoney}
            problem={moneyIssue}
          />
          <div className="ui-notice">
            <Icon name="info" />
            <p>{lt(language, "sp_note")}</p>
          </div>
        </>
      )}
      {reservation.state === "failed" && (
        <p className="ui-small ui-muted" role="status">
          {lt(language, "sign_res_failed")}
        </p>
      )}
      {paid !== null && (
        <div className="ui-notice info" role="status">
          <Icon name="check" />
          <p>
            {dmt(language, "paid_saved", paid.receiptNumber)}
            {progress.current.signed !== null &&
              ` ${lt(language, "sp_signed_saved")}`}
          </p>
        </div>
      )}
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {outcome.kind === "unknown"
              ? lt(language, "sp_unknown")
              : outcome.text}
          </p>
        </div>
      )}
    </Dialog>
  );
}
