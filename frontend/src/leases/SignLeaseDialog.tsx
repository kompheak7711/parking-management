// V1-060 B6 (owner 27/10/2026, DL-100): Sign Lease receives the money first. The dialog shows
// what the customer pays at signing: the Security Deposit (the walk-in draft's amount, or the
// rest of a Booking's deposit; a renewal keeps the old one) and the Initial Rent Invoice as
// billing will make it (Rent and Services).
// DL-101 (owner 27/10/2026): the Security Deposit amount is a Lease term recorded on the draft,
// for a walk-in Lease and for a draft from a Booking alike (Edit draft changes it).
// DL-108 (V1-060 B7): one press is one request. The server saves the Payment with its Receipt,
// the signatures, the signing, the Initial Rent Invoice paid by name and the rest of the money
// in the Security Deposit in one database transaction, or nothing. The request keeps its key and
// its exact body (received_at included) while its values stay the same, so "Try again" after a
// lost answer gets the first answer and never saves anything twice.

import { FormEvent, useEffect, useRef, useState } from "react";

import type { LeaseResource } from "../leaseClient";
import {
  type MoneyChoice,
  MoneyFields,
  moneyProblem,
  outcomeOf,
  paymentInput,
  usePaymentMethods,
} from "../payments/depositMoney";
import type { PaymentsApi } from "../payments/paymentsClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import {
  type SettlementApi,
  SettlementRequestError,
  type SignWithPaymentInput,
  type SigningPreview,
} from "../settlementClient";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { useLeaveGuard } from "../shell/leaveGuard";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { Problem } from "./LeaseDialogs";
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
  "signingPreview" | "signWithPayment"
>;

export function SignDialog({
  language,
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
}: {
  language: Language;
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
  /** Everything was saved; the page reads the Lease again. */
  onSaved: (message: string) => void;
  /** The Lease changed after the dialog read it; nothing was saved. */
  onConflict: () => void;
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
  // The last press: the same values keep the same key and the very same body.
  const attempt = useRef<{
    fingerprint: string;
    key: string;
    body: SignWithPaymentInput;
  } | null>(null);
  const today = todayInPhnomPenh();
  useLeaveGuard(true, language);

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
          required: planned ?? held.required_usd_cents,
          received: held.received_usd_cents,
        }
      : booking !== null
        ? {
            required: planned ?? booking.deposit_required_usd_cents,
            received: booking.deposit_received_usd_cents,
          }
        : null;
  // The server works the total out the same way and refuses any other amount.
  const depositDue = renewal
    ? 0
    : bookingDeposit !== null
      ? Math.max(0, bookingDeposit.required - bookingDeposit.received)
      : fromBooking
        ? 0
        : (planned ?? 0);
  // The rest of a Booking's deposit must be known to work out the total. The server finds and
  // completes the Customer's active Booking of the Unit itself.
  const bookingUnknown = !renewal && fromBooking && bookingDeposit === null;
  // The draft's amount becomes the required amount at signing, so it cannot be less than the
  // money the Reservation already received.
  const belowReceived =
    bookingDeposit !== null &&
    bookingDeposit.required < bookingDeposit.received;
  // DL-101: a walk-in draft records its Security Deposit (Edit draft) before it is signed.
  const depositMissing = walkIn && preview.state === "done" && planned === null;
  // The Initial Rent Invoice cannot be issued after its Due Date (BR-RENT-009).
  const duePassed = initial !== null && initial.due_date < today;
  const rentDue = initial?.total_usd_cents ?? 0;
  const total = depositDue + rentDue;
  const ready =
    preview.state === "done" &&
    reservation.state !== "loading" &&
    initial !== null &&
    initial.problem === null &&
    !duePassed &&
    !bookingUnknown &&
    !belowReceived &&
    !depositMissing &&
    mayCollect &&
    (!walkIn || mayCreateDeposit);
  const blocker =
    preview.state === "failed"
      ? lt(language, "sp_failed")
      : preview.state === "done" && initial === null
        ? lt(language, "sp_no_terms")
        : initial?.problem != null
          ? lt(language, "sp_problem", initial.problem.replace(/^[A-Z_]+:/, ""))
          : duePassed
            ? lt(language, "sp_due_passed", dayText(initial.due_date))
            : bookingUnknown && reservation.state !== "loading"
              ? lt(language, "sp_no_booking")
              : belowReceived
                ? lt(
                    language,
                    "sp_deposit_below",
                    usdFromCents(bookingDeposit.received),
                  )
                : depositMissing && reservation.state === "done"
                  ? lt(language, "sp_deposit_missing")
                  : !mayCollect
                    ? lt(language, "sp_no_rights")
                    : walkIn &&
                        !mayCreateDeposit &&
                        reservation.state === "done"
                      ? lt(language, "sp_no_deposit_right")
                      : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready) return;
    const all = unsigned.every((signer) => ticked.has(signer.signer_id));
    setWrong(!all);
    const issue =
      methods === null || methods === "failed"
        ? null
        : moneyProblem(methods, money);
    setMoneyIssue(issue);
    if (
      !all ||
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
    const body: SignWithPaymentInput = {
      signer_ids: unsigned.map((signer) => signer.signer_id),
      reason: SIGN_REASON,
      payment: {
        payment_method_id: payment.payment_method_id,
        received_at: payment.received_at,
        evidence_reference: payment.evidence_reference,
        payer_intent_memo: payment.payer_intent_memo,
        amount: payment.amount,
      },
    };
    // The time the money came is part of the request but not of its values: the same press
    // again sends the first body, so the server answers it from its record.
    const fingerprint = JSON.stringify({
      version: lease.version,
      ...body,
      payment: { ...body.payment, received_at: null },
    });
    if (attempt.current?.fingerprint !== fingerprint)
      attempt.current = { fingerprint, key: crypto.randomUUID(), body };
    const request = attempt.current;
    setBusy(true);
    setOutcome(null);
    signingApi
      .signWithPayment(
        propertyId,
        lease.lease_id,
        lease.version,
        request.body,
        request.key,
      )
      .then((signed) => {
        onSaved(
          lt(
            language,
            "sp_toast",
            lease.unit_number,
            usdFromCents(signed.total_usd_cents),
            signed.receipt_number,
          ),
        );
      })
      .catch((error: unknown) => {
        if (error instanceof SettlementRequestError && error.status === 412) {
          onConflict();
          return;
        }
        setOutcome(
          outcomeOf(error) === "unknown"
            ? { kind: "unknown" }
            : {
                kind: "refused",
                text:
                  error instanceof SettlementRequestError
                    ? error.message
                    : lt(language, "sign_refused"),
              },
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  // After a lost answer only the same request may go again, so nothing can be changed.
  const locked = busy || outcome?.kind === "unknown";
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
                disabled={done || locked}
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
                    {bookingDeposit !== null
                      ? lt(
                          language,
                          "sp_deposit_rest",
                          usdFromCents(bookingDeposit.received),
                          usdFromCents(bookingDeposit.required),
                        )
                      : lt(language, "sp_deposit")}
                  </td>
                  <td>{depositMissing ? "—" : usdFromCents(depositDue)}</td>
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
