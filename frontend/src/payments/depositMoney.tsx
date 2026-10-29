// V1-060 B6 (owner 27/10/2026): the money part of Make Reservation and Receive Security Deposit.
// The deposit is received as a Payment with its Receipt that pays no Invoice (POST payments);
// the Reservation or the Security Deposit then takes its receipt from that Payment. The Payment
// keeps one request key and its very same body while its values stay the same, so "Try again"
// never saves it twice (V1-060 B7: the server compares the whole stored request). While it is not
// known whether the money was saved, nothing that makes up the Payment may change, and Close asks
// once more, because a closed dialog forgets its requests.

import { useEffect, useState } from "react";

import { InvoiceClientError } from "../invoiceClient";
import {
  SettlementRequestError,
  SettlementUnavailableError,
} from "../settlementClient";
import type { Language } from "../signInText";
import { needsReference } from "./ReceivePayment";
import type { PaymentMethodOption, PaymentsApi } from "./paymentsClient";

const TEXT = {
  method: ["How the money came", "របៀបទទួលប្រាក់"],
  choose_method: ["Choose how", "ជ្រើសរើសរបៀប"],
  no_methods: [
    "No Payment Method is on. Add Cash or Bank transfer in Settings, Business.",
    "មិនមានវិធីបង់ប្រាក់ដែលបើកទេ។ សូមបន្ថែមសាច់ប្រាក់ ឬការផ្ទេរតាមធនាគារ នៅក្នុងការកំណត់ អាជីវកម្ម។",
  ],
  reference: ["Bank or ABA reference", "លេខយោងធនាគារ ឬ ABA"],
  err_method: ["Choose how the money came.", "សូមជ្រើសរើសរបៀបទទួលប្រាក់។"],
  err_reference: [
    "Type the bank reference for this method.",
    "សូមវាយលេខយោងធនាគារសម្រាប់វិធីនេះ។",
  ],
  close_anyway: ["Close anyway", "បិទទោះយ៉ាងណាក៏ដោយ"],
  close_unknown: [
    "We could not tell whether the money was saved. If you close now, look in Payments before you receive it again, so it is not received twice.",
    "យើងមិនអាចដឹងថាប្រាក់ត្រូវបានរក្សាទុកឬអត់ទេ។ ប្រសិនបើអ្នកបិទឥឡូវនេះ សូមមើលក្នុងការបង់ប្រាក់ មុនពេលទទួលវាម្តងទៀត ដើម្បីកុំឱ្យទទួលពីរដង។",
  ],
} as const;

export type DepositMoneyTextKey = keyof typeof TEXT;

export function dmt(
  language: Language,
  key: DepositMoneyTextKey,
  ...values: (string | number)[]
): string {
  return TEXT[key][language === "en" ? 0 : 1].replace(/\{(\d)\}/g, (_, n) =>
    String(values[Number(n)] ?? ""),
  );
}

/** "500.00" or "500" as cents; null when it is not a whole-cent amount above zero. */
export function centsOf(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  const [dollars = "0", part = ""] = value.split(".");
  const cents = Number(dollars) * 100 + Number(part.padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

/** "unknown" when the answer was lost or cannot say whether the request was saved (no answer,
 * a timeout, too many requests, a server failure, or a saved answer that could not be read);
 * "refused" when the server named why it saved nothing. */
export function outcomeOf(error: unknown): "unknown" | "refused" {
  if (error instanceof InvoiceClientError)
    return error.outcomeUnknown || error.status === 408 || error.status === 429
      ? "unknown"
      : "refused";
  if (error instanceof SettlementUnavailableError) return "unknown";
  if (error instanceof SettlementRequestError)
    return error.status < 400 ||
      error.status >= 500 ||
      error.status === 408 ||
      error.status === 429
      ? "unknown"
      : "refused";
  return error instanceof TypeError ? "unknown" : "refused";
}

/** As outcomeOf, for a request sent again after a lost answer. The server answers "sign in", "not
 * allowed" and "not found" before it looks up the request, so they cannot say that the lost
 * request was not saved; the outcome stays unknown. V1-060 B7 (third review): so does a request
 * that never left the browser (no status, for example when the sign-in cookie is gone). */
export function outcomeAfter(
  error: unknown,
  earlierUnknown: boolean,
): "unknown" | "refused" {
  const outcome = outcomeOf(error);
  if (outcome === "unknown" || !earlierUnknown) return outcome;
  const status =
    error instanceof InvoiceClientError ||
    error instanceof SettlementRequestError
      ? error.status
      : null;
  return status === null || status === 401 || status === 403 || status === 404
    ? "unknown"
    : "refused";
}

/** Close asks once more while it is not known whether the money was saved: a closed
 * dialog forgets its requests, so starting again could receive the same money twice. V1-060 B7
 * (third review): Escape only asks; only the "Close anyway" button closes such a dialog. */
export function useCloseGuard(risky: boolean, onClose: () => void) {
  const [asked, setAsked] = useState(false);
  return {
    asked: asked && risky,
    close: () => {
      if (risky && !asked) setAsked(true);
      else onClose();
    },
    escape: () => {
      if (risky) setAsked(true);
      else onClose();
    },
    reset: () => {
      setAsked(false);
    },
  };
}

export function usePaymentMethods(
  api: PaymentsApi,
  propertyId: string,
): PaymentMethodOption[] | null | "failed" {
  const [methods, setMethods] = useState<
    PaymentMethodOption[] | null | "failed"
  >(null);
  useEffect(() => {
    let live = true;
    api
      .methods(propertyId)
      .then((found) => {
        if (live) setMethods(found);
      })
      .catch(() => {
        if (live) setMethods("failed");
      });
    return () => {
      live = false;
    };
  }, [api, propertyId]);
  return methods;
}

export interface MoneyChoice {
  methodId: string;
  reference: string;
}

/** What is wrong with the method part, or null. */
export function moneyProblem(
  methods: PaymentMethodOption[],
  choice: MoneyChoice,
): "err_method" | "err_reference" | null {
  const method = methods.find((item) => item.id === choice.methodId);
  if (method === undefined) return "err_method";
  if (needsReference(method) && choice.reference.trim() === "")
    return "err_reference";
  return null;
}

/** The Payment body: cash is "Cash received"; every other method carries its reference. */
export function paymentInput(
  methods: PaymentMethodOption[],
  choice: MoneyChoice,
  customerId: string,
  cents: number,
  memo: string,
) {
  const method = methods.find((item) => item.id === choice.methodId);
  return {
    payer_customer_id: customerId,
    payment_method_id: choice.methodId,
    received_at: new Date().toISOString(),
    evidence_reference:
      method !== undefined && needsReference(method)
        ? choice.reference.trim()
        : `Cash received, ${method?.displayName ?? ""}`.trim(),
    payer_intent_memo: memo,
    amount: { currency: "USD" as const, minor_units: cents },
  };
}

export function MoneyFields({
  language,
  idPrefix,
  methods,
  choice,
  onChange,
  problem,
  disabled,
}: {
  language: Language;
  idPrefix: string;
  methods: PaymentMethodOption[] | null | "failed";
  choice: MoneyChoice;
  onChange: (choice: MoneyChoice) => void;
  problem: "err_method" | "err_reference" | null;
  disabled: boolean;
}) {
  if (methods === null || methods === "failed" || methods.length === 0)
    return (
      <p className="ui-small ui-muted" role="status">
        {methods === null ? "…" : dmt(language, "no_methods")}
      </p>
    );
  const method = methods.find((item) => item.id === choice.methodId);
  return (
    <>
      <div className="ui-field">
        <label htmlFor={`${idPrefix}-method`}>{dmt(language, "method")}</label>
        <select
          aria-invalid={problem === "err_method"}
          disabled={disabled}
          id={`${idPrefix}-method`}
          onChange={(event) => {
            onChange({ ...choice, methodId: event.currentTarget.value });
          }}
          value={choice.methodId}
        >
          <option value="">{dmt(language, "choose_method")}</option>
          {methods.map((item) => (
            <option key={item.id} value={item.id}>
              {item.displayName}
            </option>
          ))}
        </select>
        {problem === "err_method" && (
          <p className="ui-error" role="alert">
            {dmt(language, "err_method")}
          </p>
        )}
      </div>
      {method !== undefined && needsReference(method) && (
        <div className="ui-field">
          <label htmlFor={`${idPrefix}-reference`}>
            {dmt(language, "reference")}
          </label>
          <input
            aria-invalid={problem === "err_reference"}
            autoComplete="off"
            disabled={disabled}
            id={`${idPrefix}-reference`}
            maxLength={200}
            onChange={(event) => {
              onChange({ ...choice, reference: event.currentTarget.value });
            }}
            value={choice.reference}
          />
          {problem === "err_reference" && (
            <p className="ui-error" role="alert">
              {dmt(language, "err_reference")}
            </p>
          )}
        </div>
      )}
    </>
  );
}

/** One request for the life of a Payment's values: the same values send the very same body
 * with the same key, so the server answers a lost request from its record. received_at is not
 * one of the values; it is set once, when the values are first sent. New values are a new
 * request. */
export function requestFor<Body extends { received_at: string }>(
  current: {
    current: { fingerprint: string; key: string; body: Body } | null;
  },
  body: Body,
): { key: string; body: Body } {
  const fingerprint = JSON.stringify({ ...body, received_at: null });
  if (current.current?.fingerprint !== fingerprint)
    current.current = { fingerprint, key: crypto.randomUUID(), body };
  return current.current;
}

/** One key for the life of a set of values; new values get a new key. */
export function keyFor(
  current: { current: { fingerprint: string; key: string } | null },
  values: unknown,
): string {
  const fingerprint = JSON.stringify(values);
  if (current.current?.fingerprint !== fingerprint)
    current.current = { fingerprint, key: crypto.randomUUID() };
  return current.current.key;
}
