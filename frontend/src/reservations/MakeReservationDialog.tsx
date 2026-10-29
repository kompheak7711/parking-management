// V1-060 B6 (owner 27/10/2026): Make Reservation in the new design. It replaces the earlier
// English form, which asked for record identifiers. The deposit received now is saved first as
// a Payment with its Receipt (it pays no Invoice); the Reservation then takes its deposit receipt
// from that Payment (docs/001 §89: the money is the Security Deposit from the first day). Each
// step keeps one request identity while its values stay the same, so "Try again" never saves
// anything twice; once the money is saved, the money fields are fixed.
// V1-060 B7: the Payment is sent again with the very same body; the Rent is fixed with the money
// it was taken against; less than the suggestion is stopped before any money when this person
// may not accept it (the server would refuse the Reservation after the money was saved).
// While it is not known whether a step was saved, every box stays fixed, so Try again sends the
// very same requests; a refusal after a lost Reservation answer first looks for that Reservation;
// Close asks once more while the money may be saved and the Reservation is not.
// V1-061 (DL-112, owner bug list 29/10/2026): one press sends one request; the server saves the
// money, its Receipt and the Reservation in one database transaction, or nothing. The request
// keeps one key and one body while the values stay the same, so Try again never saves twice.

import { FormEvent, useEffect, useRef, useState } from "react";

import type { CustomerApi, CustomerListItem } from "../customerClient";
import type { CustomerCommandGate } from "../customers/commands";
import { NewCustomerDialog } from "../customers/CustomerDialogs";
import {
  centsOf,
  dmt,
  keyFor,
  type MoneyChoice,
  MoneyFields,
  moneyProblem,
  outcomeOf,
  paymentInput,
  requestFor,
  useCloseGuard,
  usePaymentMethods,
} from "../payments/depositMoney";
import type { PaymentsApi } from "../payments/paymentsClient";
import {
  ReservationConflictError,
  ReservationRequestError,
  ReservationUnavailableError,
  type ReservationApi,
  type ReservationResource,
  type ReservationWithPaymentSource,
} from "../reservationClient";
import { DateInput, parseDay } from "../shell/DateInput";
import { todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { useLeaveGuard } from "../shell/leaveGuard";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi, UnitResource } from "../unitClient";
import { allPages } from "../units/unitsData";
import { addDays } from "./reservationsData";
import { rt, type ReservationTextKey } from "./text";

type Field =
  | "unit"
  | "customer"
  | "date"
  | "expires"
  | "rent"
  | "required"
  | "received"
  | "reason"
  | "rentReason";

/** The normal suggestion: 20% of the agreed Rent, to the nearest cent (as the server checks). */
export function suggestedDeposit(rentCents: number): number {
  return Math.floor((rentCents + 2) / 5);
}

export function MakeReservationDialog({
  language,
  propertyId,
  api,
  unitApi,
  customerApi,
  paymentsApi,
  gate,
  mayOverride,
  mayLowerRent = null,
  unitId: chosenUnit,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: ReservationApi;
  unitApi: Pick<UnitApi, "list">;
  customerApi: CustomerApi;
  paymentsApi: PaymentsApi;
  /** Leave out when this person may not add Customers. */
  gate?: CustomerCommandGate;
  /** False when this person may not accept less than the suggestion (DL-099); null while their
   * rights are not known. */
  mayOverride: boolean | null;
  /** V1-061 (DL-110): may agree a Rent below the Unit's default Rent; null while not known. */
  mayLowerRent?: boolean | null;
  unitId?: string;
  onClose: () => void;
  onSaved: (saved: ReservationResource) => void;
}) {
  const today = todayInPhnomPenh();
  const [units, setUnits] = useState<UnitResource[] | null>(null);
  const [customers, setCustomers] = useState<CustomerListItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const methods = usePaymentMethods(paymentsApi, propertyId);
  const [unitId, setUnitId] = useState(chosenUnit ?? "");
  const [customerId, setCustomerId] = useState("");
  const [date, setDate] = useState(today);
  const [expires, setExpires] = useState(addDays(today, 21));
  const [rent, setRent] = useState("");
  const [required, setRequired] = useState("");
  const [received, setReceived] = useState("");
  const [reason, setReason] = useState("");
  const [rentReason, setRentReason] = useState("");
  const [money, setMoney] = useState<MoneyChoice>({
    methodId: "",
    reference: "",
  });
  const [problems, setProblems] = useState<Partial<Record<Field, string>>>({});
  const [moneyIssue, setMoneyIssue] = useState<
    "err_method" | "err_reference" | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<
    "unknown" | "refused" | "conflict" | null
  >(null);
  const [adding, setAdding] = useState(false);
  const paymentRequest = useRef<{
    fingerprint: string;
    key: string;
    body: ReturnType<typeof paymentInput>;
  } | null>(null);
  const reservationKey = useRef<{ fingerprint: string; key: string } | null>(
    null,
  );
  const ids = useRef({
    reservation: crypto.randomUUID(),
    acceptance: crypto.randomUUID(),
    deposit: crypto.randomUUID(),
    receipt: crypto.randomUUID(),
  });
  // A lost answer: it may be saved, so nothing may change before Try again.
  const pending = outcome === "unknown";
  const guard = useCloseGuard(pending, onClose);
  useLeaveGuard(true, language);

  const load = () => {
    setFailed(false);
    void Promise.all([
      allPages((cursor) =>
        unitApi.list(
          propertyId,
          cursor === undefined
            ? { status: "VACANT" }
            : { status: "VACANT", cursor },
        ),
      ),
      allPages((cursor) =>
        customerApi.list(
          propertyId,
          cursor === undefined ? { active: true } : { active: true, cursor },
        ),
      ),
    ])
      .then(([foundUnits, foundCustomers]) => {
        const vacant = foundUnits
          .filter((unit) => unit.status === "VACANT")
          .sort((left, right) =>
            left.unit_number.localeCompare(right.unit_number),
          );
        setUnits(vacant);
        // V1-060 B7: a Unit named in the address that is not free now is not kept.
        setUnitId((current) =>
          vacant.some((unit) => unit.unit_id === current) ? current : "",
        );
        setCustomers(
          foundCustomers.sort((left, right) =>
            left.legal_name.localeCompare(right.legal_name),
          ),
        );
      })
      .catch(() => {
        setFailed(true);
      });
  };
  useEffect(load, [customerApi, propertyId, unitApi]);

  const rentCents = centsOf(rent);
  // V1-061 (DL-110): the Rent starts at the Unit's default Rent until it is typed; less needs a
  // Manager or the Owner and a reason, checked here before any money is taken.
  const defaultRent =
    units?.find((unit) => unit.unit_id === unitId)
      ?.default_monthly_rent_usd_cents ?? null;
  const typedRent = useRef(false);
  useEffect(() => {
    if (typedRent.current) return;
    setRent(defaultRent === null ? "" : (defaultRent / 100).toFixed(2));
  }, [defaultRent]);
  const rentBelow =
    rentCents !== null && defaultRent !== null && rentCents < defaultRent;
  const suggestion = rentCents === null ? null : suggestedDeposit(rentCents);
  const receivedCents = centsOf(received);
  // DL-099 (owner 2026-10-27): only less than the suggestion needs a reason and the Manager.
  const below =
    suggestion !== null && receivedCents !== null && receivedCents < suggestion;
  const above =
    suggestion !== null && receivedCents !== null && receivedCents > suggestion;

  // The suggestions follow the Rent until someone types their own amount.
  const typedReceived = useRef(false);
  const typedRequired = useRef(false);
  useEffect(() => {
    if (rentCents === null) return;
    if (!typedReceived.current)
      setReceived((suggestedDeposit(rentCents) / 100).toFixed(2));
    if (!typedRequired.current) setRequired((rentCents / 100).toFixed(2));
  }, [rentCents]);

  function check(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    guard.reset();
    const found: Partial<Record<Field, string>> = {};
    const say = (key: ReservationTextKey) => rt(language, key);
    if (unitId === "") found.unit = say("mk_err_unit");
    if (customerId === "") found.customer = say("mk_err_customer");
    const day = parseDay(date);
    const end = parseDay(expires);
    if (day === "") found.date = say("mk_err_date");
    if (day !== "" && (end === "" || end <= day || end > addDays(day, 21)))
      found.expires = say("mk_err_expires");
    if (rentCents === null) found.rent = say("mk_err_rent");
    else if (rentBelow && mayLowerRent !== true)
      found.rent = rt(
        language,
        mayLowerRent === null ? "mk_err_rent_rights" : "mk_err_rent_below",
        usdFromCents(defaultRent),
      );
    else if (rentBelow && rentReason.trim() === "")
      found.rentReason = say("mk_err_rent_reason");
    if (receivedCents === null) found.received = say("mk_err_received");
    const requiredCents = centsOf(required);
    if (
      requiredCents === null ||
      (receivedCents !== null && requiredCents < receivedCents)
    )
      found.required = say("mk_err_required");
    if (below && reason.trim() === "") found.reason = say("mk_err_reason");
    if (below && mayOverride !== true)
      found.received = rt(
        language,
        mayOverride === null ? "mk_err_rights" : "mk_err_override",
        usdFromCents(suggestion),
      );
    const issue =
      methods === null || methods === "failed"
        ? null
        : moneyProblem(methods, money);
    setProblems(found);
    setMoneyIssue(issue);
    if (
      Object.keys(found).length > 0 ||
      issue !== null ||
      methods === null ||
      methods === "failed" ||
      rentCents === null ||
      receivedCents === null ||
      requiredCents === null
    )
      return;
    const unit = units?.find((item) => item.unit_id === unitId);
    void save({
      payment: paymentInput(
        methods,
        money,
        customerId,
        receivedCents,
        rt("en", "mk_memo", unit?.unit_number ?? ""),
      ),
      reservation: {
        reservation_id: ids.current.reservation,
        unit_id: unitId,
        customer_id: customerId,
        reservation_date: day,
        agreed_monthly_rent_usd_cents: rentCents,
        expiration_date: end,
        acceptance_id: ids.current.acceptance,
        accepted_initial_deposit_usd_cents: receivedCents,
        required_security_deposit_usd_cents: requiredCents,
        acceptance_reason: `${(below
          ? reason.trim()
          : rt("en", above ? "mk_reason_more" : "mk_reason_default")
        ).replace(
          /\.$/,
          "",
        )}${rentBelow ? `. Rent below the Unit default: ${rentReason.trim()}` : ""}`.slice(
          0,
          500,
        ),
        deposit_id: ids.current.deposit,
        receipt_id: ids.current.receipt,
      },
    });
  }

  async function save(values: {
    payment: ReturnType<typeof paymentInput>;
    reservation: Omit<ReservationWithPaymentSource, "payment">;
  }) {
    // The try before this one: unknown means its answer was lost.
    const earlierUnknown = outcome === "unknown";
    setBusy(true);
    setOutcome(null);
    // The same values keep the same body (its received time too) and the same key.
    const body = requestFor(paymentRequest, values.payment).body;
    const source: ReservationWithPaymentSource = {
      ...values.reservation,
      payment: {
        payment_method_id: body.payment_method_id,
        received_at: body.received_at,
        evidence_reference: body.evidence_reference,
        payer_intent_memo: body.payer_intent_memo,
        amount: body.amount,
      },
    };
    try {
      const saved = await api.createWithPayment(
        propertyId,
        source,
        keyFor(reservationKey, source),
      );
      onSaved(saved.reservation);
    } catch (error: unknown) {
      const status =
        error instanceof ReservationRequestError ? error.status : null;
      const result =
        error instanceof ReservationConflictError
          ? "conflict"
          : error instanceof ReservationUnavailableError ||
              (earlierUnknown &&
                (status === null ||
                  status === 401 ||
                  status === 403 ||
                  status === 404))
            ? "unknown"
            : outcomeOf(error);
      // After a lost answer, the server's own refusal may be meeting this very Reservation (its
      // Unit is no longer free), so look for it by its own id before saying it was not saved.
      if (result !== "unknown" && earlierUnknown) {
        const found = await savedBefore();
        if (found === "unknown") {
          setOutcome("unknown");
          return;
        }
        if (found !== "absent") {
          onSaved(found);
          return;
        }
      }
      setOutcome(result);
    } finally {
      setBusy(false);
    }
  }

  /** The Reservation a lost answer may have saved; "absent" when the server says there is none. */
  async function savedBefore(): Promise<
    ReservationResource | "absent" | "unknown"
  > {
    try {
      return await api.get(ids.current.reservation);
    } catch (error: unknown) {
      return error instanceof ReservationRequestError && error.status === 404
        ? "absent"
        : "unknown";
    }
  }

  if (adding && gate !== undefined)
    return (
      <NewCustomerDialog
        api={customerApi}
        gate={gate}
        language={language}
        onClose={() => {
          setAdding(false);
        }}
        onSaved={(customer) => {
          setCustomers((current) =>
            [
              ...(current ?? []).filter(
                (item) => item.customer_id !== customer.customer_id,
              ),
              {
                customer_id: customer.customer_id,
                legal_name: customer.legal_name,
                phone_number: customer.phone_number ?? null,
                active: true,
                relationship_indicators: [],
              },
            ].sort((left, right) =>
              left.legal_name.localeCompare(right.legal_name),
            ),
          );
          setCustomerId(customer.customer_id);
          setAdding(false);
        }}
        propertyId={propertyId}
      />
    );

  const error = (field: Field) =>
    problems[field] === undefined ? null : (
      <p className="ui-error" role="alert">
        <Icon name="alert" small />
        <span>{problems[field]}</span>
      </p>
    );
  const locked = busy || pending;
  const fixed = busy || pending;

  return (
    <Dialog
      busy={busy}
      closeLabel={
        guard.asked ? dmt(language, "close_anyway") : rt(language, "close")
      }
      onClose={guard.close}
      onEscape={guard.escape}
      onSubmit={units !== null && customers !== null ? check : undefined}
      submitLabel={
        busy
          ? rt(language, "saving")
          : outcome !== null
            ? rt(language, "try_again")
            : rt(language, "mk_save")
      }
      title={rt(language, "mk_title")}
      wide
    >
      {failed ? (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{rt(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {rt(language, "retry")}
          </button>
        </div>
      ) : units === null || customers === null ? (
        <p className="ui-muted" role="status">
          {rt(language, "mk_loading")}
        </p>
      ) : (
        <>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="mk-unit">{rt(language, "mk_unit")}</label>
              <select
                aria-invalid={problems.unit !== undefined}
                disabled={locked}
                id="mk-unit"
                onChange={(event) => {
                  setUnitId(event.currentTarget.value);
                }}
                value={unitId}
              >
                <option value="">{rt(language, "mk_choose_unit")}</option>
                {units.map((unit) => (
                  <option key={unit.unit_id} value={unit.unit_id}>
                    {unit.unit_number}
                  </option>
                ))}
              </select>
              {units.length === 0 && (
                <p className="help">{rt(language, "mk_no_units")}</p>
              )}
              {error("unit")}
            </div>
            <div className="ui-field">
              <label htmlFor="mk-customer">{rt(language, "mk_customer")}</label>
              <div className="ui-pickrow">
                <select
                  aria-invalid={problems.customer !== undefined}
                  disabled={locked}
                  id="mk-customer"
                  onChange={(event) => {
                    setCustomerId(event.currentTarget.value);
                  }}
                  value={customerId}
                >
                  <option value="">{rt(language, "mk_choose_customer")}</option>
                  {customers.map((customer) => (
                    <option
                      key={customer.customer_id}
                      value={customer.customer_id}
                    >
                      {customer.legal_name}
                      {customer.phone_number
                        ? ` · ${customer.phone_number}`
                        : ""}
                    </option>
                  ))}
                </select>
                {gate !== undefined && !locked && (
                  <button
                    aria-label={rt(language, "mk_new_customer")}
                    className="ui-btn ui-iconbtn"
                    onClick={() => {
                      setAdding(true);
                    }}
                    title={rt(language, "mk_new_customer")}
                    type="button"
                  >
                    <Icon name="userplus" />
                  </button>
                )}
              </div>
              {error("customer")}
            </div>
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="mk-date">{rt(language, "mk_date")}</label>
              <DateInput
                language={language}
                disabled={fixed}
                id="mk-date"
                invalid={problems.date !== undefined}
                onChange={(value) => {
                  setDate(value);
                  const day = parseDay(value);
                  if (day !== "") setExpires(addDays(day, 21));
                }}
                value={date}
              />
              {error("date")}
            </div>
            <div className="ui-field">
              <label htmlFor="mk-expires">{rt(language, "mk_expires")}</label>
              <DateInput
                language={language}
                disabled={fixed}
                id="mk-expires"
                invalid={problems.expires !== undefined}
                max={parseDay(date) === "" ? undefined : addDays(date, 21)}
                min={parseDay(date) === "" ? undefined : addDays(date, 1)}
                onChange={setExpires}
                value={expires}
              />
              <p className="help">{rt(language, "mk_expires_help")}</p>
              {error("expires")}
            </div>
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="mk-rent">{rt(language, "mk_rent")}</label>
              <input
                aria-invalid={problems.rent !== undefined}
                disabled={locked}
                id="mk-rent"
                inputMode="decimal"
                onChange={(event) => {
                  typedRent.current = true;
                  setRent(event.currentTarget.value);
                }}
                value={rent}
              />
              {defaultRent !== null && (
                <p className="help">
                  {rt(language, "mk_rent_default", usdFromCents(defaultRent))}
                </p>
              )}
              {error("rent")}
            </div>
            {rentBelow && mayLowerRent === true && (
              <div className="ui-field">
                <label htmlFor="mk-rent-reason">
                  {rt(language, "mk_rent_reason", usdFromCents(defaultRent))}
                </label>
                <input
                  aria-invalid={problems.rentReason !== undefined}
                  disabled={locked}
                  id="mk-rent-reason"
                  maxLength={300}
                  onChange={(event) => {
                    setRentReason(event.currentTarget.value);
                  }}
                  value={rentReason}
                />
                {error("rentReason")}
              </div>
            )}
            <div className="ui-field">
              <label htmlFor="mk-required">{rt(language, "mk_required")}</label>
              <input
                aria-invalid={problems.required !== undefined}
                disabled={fixed}
                id="mk-required"
                inputMode="decimal"
                onChange={(event) => {
                  typedRequired.current = true;
                  setRequired(event.currentTarget.value);
                }}
                value={required}
              />
              <p className="help">{rt(language, "mk_required_help")}</p>
              {error("required")}
            </div>
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="mk-received">{rt(language, "mk_received")}</label>
              <input
                aria-invalid={problems.received !== undefined}
                disabled={locked}
                id="mk-received"
                inputMode="decimal"
                onChange={(event) => {
                  typedReceived.current = true;
                  setReceived(event.currentTarget.value);
                }}
                value={received}
              />
              {suggestion !== null && (
                <p className="help">
                  {rt(language, "mk_received_help", usdFromCents(suggestion))}
                </p>
              )}
              {error("received")}
            </div>
            <div className="ui-field">
              <MoneyFields
                choice={money}
                disabled={locked}
                idPrefix="mk"
                language={language}
                methods={methods}
                onChange={setMoney}
                problem={moneyIssue}
              />
            </div>
          </div>
          {below && (
            <div className="ui-field">
              <label htmlFor="mk-reason">{rt(language, "mk_reason")}</label>
              <input
                aria-invalid={problems.reason !== undefined}
                disabled={fixed}
                id="mk-reason"
                maxLength={500}
                onChange={(event) => {
                  setReason(event.currentTarget.value);
                }}
                value={reason}
              />
              {error("reason")}
            </div>
          )}
          {outcome !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>
                {rt(language, outcome !== "conflict" ? outcome : "mk_conflict")}
              </p>
            </div>
          )}
          {guard.asked && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{dmt(language, "close_unknown")}</p>
            </div>
          )}
        </>
      )}
    </Dialog>
  );
}
