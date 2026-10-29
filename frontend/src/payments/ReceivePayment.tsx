// V1-058 R5c-2: Receive payment (DESIGN.md "What this money pays for"; DL-077, DL-029). Money pays
// Invoices when it is received: the app ticks the oldest Due Date first, a late-payment charge
// right after its own Invoice, and staff change the ticks only when the Customer names what to
// pay. Pressing Receive payment in the dialog is the staff confirmation; the server saves the
// payment, its Receipt and what it pays in one step, and the same values keep one key, so
// pressing again after no answer saves once.

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type { InvoicesData } from "../invoices/invoicesData";
import { centsOf } from "../invoices/invoicesData";
import { InvoiceClientError } from "../invoiceClient";
import { dayText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { useLeaveGuard } from "../shell/leaveGuard";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type PayableItem,
  type PayProblem,
  payProblem,
  paysOf,
  pickedTotal,
  planFor,
} from "./payFor";
import type {
  PaymentMethodOption,
  PaymentsApi,
  ReceiveInput,
  ReceiveResult,
} from "./paymentsClient";
import { pyt, type PaymentsTextKey } from "./text";

type Field = "cust" | "amt" | "method" | "when" | "ref" | "payfor";
type Currency = "USD" | "KHR";
type Outcome =
  | "out_unknown"
  | "out_refused"
  | "out_changed"
  | "out_too_many"
  | "out_reused"
  | "pf_err_more"
  | null;

const IDS: Record<Field, string> = {
  cust: "rp-cust",
  amt: "rp-amt",
  method: "rp-method",
  when: "rp-when",
  ref: "rp-ref",
  payfor: "rp-pf-first",
};

/** Cash needs no reference; every other method does (DESIGN.md Payment Methods). */
export function needsReference(
  method: PaymentMethodOption | undefined,
): boolean {
  return method !== undefined && method.code.trim().toUpperCase() !== "CASH";
}

/** Now in Phnom Penh as "25/10/2026, 14:05". */
export function nowText(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Phnom_Penh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const part = (type: string) =>
    parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("day")}/${part("month")}/${part("year")}, ${part("hour")}:${part("minute")}`;
}

/** "25/10/2026, 14:05" in Phnom Penh → an RFC 3339 time, or null. */
export function receivedAt(value: string): string | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4}),? (\d{2}):(\d{2})$/.exec(
    value.trim(),
  );
  if (match === null) return null;
  const [, day = "", month = "", year = "", hour = "", minute = ""] = match;
  const iso = `${year}-${month}-${day}T${hour}:${minute}:00+07:00`;
  const date = new Date(iso);
  if (
    Number.isNaN(date.getTime()) ||
    Number(hour) > 23 ||
    nowText(date) !== `${day}/${month}/${year}, ${hour}:${minute}`
  )
    return null;
  return iso;
}

/** Whole riel, or null. */
export function rielOf(text: string): number | null {
  const plain = text.trim().replace(/,/g, "");
  if (!/^[1-9]\d{0,14}$/.test(plain)) return null;
  const value = Number(plain);
  return Number.isSafeInteger(value) ? value : null;
}

/** Riel to pay for a dollar amount at the app rate, rounded up (BR-MONEY-005 to 008). */
export function rielFor(cents: number, rate: number): number {
  return Math.ceil((cents * rate) / 100);
}

/** The dollar value of riel at the app rate, when the riel is exactly what that value costs. */
export function centsForRiel(riel: number, rate: number): number | null {
  const cents = Math.floor((riel * 100) / rate);
  if (cents > 0 && rielFor(cents, rate) === riel) return cents;
  if (rielFor(cents + 1, rate) === riel) return cents + 1;
  return null;
}

export function ReceivePayment({
  language,
  propertyId,
  api,
  data,
  initialCustomer = "",
  initialPick = "",
  now: fixedNow,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: PaymentsApi;
  data: InvoicesData;
  initialCustomer?: string;
  /** One item to tick alone when the list arrives (the late-payment card's Receive payment). */
  initialPick?: string;
  /** Tests pass a fixed moment. */
  now?: Date;
  /** The lists read again, so they show the new payment. */
  onSaved: () => void;
}) {
  const now = useRef(fixedNow ?? new Date()).current;
  const [customer, setCustomer] = useState(initialCustomer);
  const [currency, setCurrency] = useState<Currency>("USD");
  const [amount, setAmount] = useState("");
  const [methodId, setMethodId] = useState("");
  const [when, setWhen] = useState(nowText(now));
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [picks, setPicks] = useState<ReadonlySet<string> | null>(null);
  const [items, setItems] = useState<PayableItem[] | null>(null);
  const [itemsFailed, setItemsFailed] = useState(false);
  const [methods, setMethods] = useState<PaymentMethodOption[] | null>(null);
  const [rate, setRate] = useState<number | null | undefined>(undefined);
  const [problems, setProblems] = useState<Field[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [done, setDone] = useState<ReceiveResult | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const identity = useRef<{ sent: string; key: string } | null>(null);
  const reading = useRef(0);
  const firstPick = useRef(initialPick);
  // A payment being typed or sent is a money window: Back or reload asks first.
  useLeaveGuard(
    done === null &&
      (amount.trim() !== "" || confirming || busy || outcome === "out_unknown"),
    language,
  );

  const customers = [...data.customerLeases.keys()]
    .map((id) => ({
      id,
      name: data.names.get(id) ?? pyt(language, "unknown_customer"),
      unit: data.customerUnits.get(id) ?? "",
    }))
    .sort(
      (left, right) =>
        left.unit.localeCompare(right.unit, undefined, { numeric: true }) ||
        left.name.localeCompare(right.name),
    );
  const chosen = customers.find((entry) => entry.id === customer);
  const method = methods?.find((entry) => entry.id === methodId);

  useEffect(() => {
    void api
      .methods(propertyId)
      .then((found) => {
        setMethods(found);
        setMethodId((current) => current || (found[0]?.id ?? ""));
      })
      .catch(() => {
        setMethods([]);
      });
  }, [api, propertyId]);

  useEffect(() => {
    if (currency !== "KHR" || rate !== undefined) return;
    void api
      .khrRate(propertyId)
      .then((found) => {
        setRate(found?.rate ?? null);
      })
      .catch(() => {
        setRate(null);
      });
  }, [api, currency, propertyId, rate]);

  const readItems = useCallback(
    (id: string) => {
      const operation = ++reading.current;
      setItems(null);
      setItemsFailed(false);
      if (id === "") return;
      void api
        .payable(propertyId, id)
        .then((found) => {
          if (operation !== reading.current) return;
          setItems(found);
          // The late-payment card asks for its charge alone, with its amount, once.
          const only = found.find((item) => item.id === firstPick.current);
          firstPick.current = "";
          if (only !== undefined && id === initialCustomer) {
            setPicks(new Set([only.id]));
            setAmount((only.owed / 100).toFixed(2));
          }
        })
        .catch(() => {
          if (operation === reading.current) setItemsFailed(true);
        });
    },
    [api, propertyId],
  );

  useEffect(() => {
    readItems(customer);
  }, [customer, readItems]);

  // The dollar value of the typed amount; riel counts at the app rate.
  const typedRiel = currency === "KHR" ? rielOf(amount) : null;
  const cents =
    currency === "USD"
      ? centsOf(amount)
      : typedRiel === null || !rate
        ? null
        : centsForRiel(typedRiel, rate);
  const list = items ?? [];
  const plan = planFor(list, cents, picks);
  const payIssue: PayProblem | null =
    items === null ? null : payProblem(plan, cents);

  const showAmount = (value: number) => {
    if (currency === "USD") return (value / 100).toFixed(2);
    return rate ? String(rielFor(value, rate)) : "";
  };

  const chooseCustomer = (id: string) => {
    // Another Customer clears the amount, reference, note and ticks (owner, 13/10/2026).
    setCustomer(id);
    setAmount("");
    setReference("");
    setNote("");
    setPicks(null);
    setProblems(null);
    setOutcome(null);
  };

  const toggle = (item: PayableItem) => {
    const next = new Set(
      picks ?? plan.rows.filter((row) => row.on).map((row) => row.item.id),
    );
    if (next.has(item.id)) next.delete(item.id);
    else next.add(item.id);
    setPicks(next);
    // Ticking by hand sets the amount to the ticked total, in dollars or riel.
    setAmount(next.size === 0 ? "" : showAmount(pickedTotal(list, next)));
  };

  const fieldErrors = (): Field[] => {
    const found: Field[] = [];
    if (chosen === undefined) found.push("cust");
    if (cents === null) found.push("amt");
    if (method === undefined) found.push("method");
    const at = receivedAt(when);
    if (at === null || new Date(at).getTime() > Date.now() + 60_000)
      found.push("when");
    if (needsReference(method) && reference.trim() === "") found.push("ref");
    if (payIssue !== null) found.push("payfor");
    return found;
  };

  const check = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (items === null && chosen !== undefined) return;
    const found = fieldErrors();
    setProblems(found);
    if (found.length > 0) {
      setTimeout(() => summary.current?.focus(), 0);
      return;
    }
    setOutcome(null);
    setConfirming(true);
  };

  const input = (): ReceiveInput | null => {
    const at = receivedAt(when);
    if (
      chosen === undefined ||
      cents === null ||
      method === undefined ||
      at === null
    )
      return null;
    return {
      payer_customer_id: chosen.id,
      payment_method_id: method.id,
      received_at: at,
      evidence_reference: needsReference(method)
        ? reference.trim()
        : `Cash received, ${method.displayName}`,
      payer_intent_memo: note.trim() === "" ? null : note.trim(),
      amount:
        currency === "USD"
          ? { currency: "USD", minor_units: cents }
          : { currency: "KHR", minor_units: typedRiel ?? 0 },
      ...(currency === "KHR"
        ? {
            usd_accounting_amount: {
              currency: "USD" as const,
              minor_units: cents,
            },
          }
        : {}),
      pays: paysOf(plan),
    };
  };

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const body = input();
    if (body === null || busy) return;
    const sent = JSON.stringify(body);
    if (identity.current?.sent !== sent)
      identity.current = { sent, key: crypto.randomUUID() };
    const { key } = identity.current;
    setBusy(true);
    setOutcome(null);
    void api
      .receive(propertyId, body, key)
      .then((result) => {
        setDone(result);
        setConfirming(false);
        onSaved();
      })
      .catch((error: unknown) => {
        if (!(error instanceof InvoiceClientError) || error.outcomeUnknown) {
          setOutcome("out_unknown");
          return;
        }
        if (error.code === "RECEIVE_PAYMENT_CHANGED") {
          // The list is read again and the app ticks oldest first from it.
          setOutcome("out_changed");
          setConfirming(false);
          setPicks(null);
          readItems(chosen?.id ?? "");
          return;
        }
        setOutcome(
          error.code === "RECEIVE_PAYMENT_TOO_MANY"
            ? "out_too_many"
            : error.code === "RECEIVE_PAYMENT_LEFT_WHILE_OWING"
              ? "pf_err_more"
              : error.code === "IDEMPOTENCY_KEY_REUSED"
                ? "out_reused"
                : "out_refused",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const clear = () => {
    chooseCustomer("");
    setWhen(nowText(new Date()));
    identity.current = null;
  };

  const money = (value: number) => usdFromCents(value);
  const amountText = () =>
    currency === "USD" || typedRiel === null
      ? money(cents ?? 0)
      : `${typedRiel.toLocaleString("en-US")} ៛ (${money(cents ?? 0)})`;
  const paidRows = plan.rows.filter((row) => row.on && row.pays > 0);
  const rowName = (item: PayableItem) =>
    item.kind === "INVOICE"
      ? item.category !== null && isCategory(item.category)
        ? `${item.invoiceNumber} · ${pyt(language, item.category)}`
        : item.invoiceNumber
      : pyt(language, "pfl_d", item.invoiceNumber);

  if (done !== null) {
    const paid = done.allocations
      .map((entry) =>
        entry.kind === "INVOICE"
          ? `${entry.invoiceNumber} (${money(entry.amount)})`
          : `${pyt(language, "pfl_d", entry.invoiceNumber)} (${money(entry.amount)})`,
      )
      .join(", ");
    const received =
      done.currency === "USD"
        ? money(done.usdCents)
        : `${done.receivedMinor.toLocaleString("en-US")} ៛`;
    return (
      <>
        <div className="ui-head">
          <h2>{pyt(language, "done_pay_t")}</h2>
        </div>
        <section className="ui-card">
          <div className="ui-notice ok" role="status">
            <Icon name="check" />
            <p>
              {done.allocations.length === 0
                ? pyt(
                    language,
                    "done_pay_kept",
                    received,
                    chosen?.name ?? "",
                    done.receiptNumber,
                  )
                : pyt(
                    language,
                    "done_pay_paid",
                    received,
                    chosen?.name ?? "",
                    done.receiptNumber,
                    paid,
                  )}
            </p>
          </div>
          {done.allocations.length > 0 && done.left > 0 && (
            <div className="ui-notice warn" role="note">
              <Icon name="alert" />
              <p>{pyt(language, "pf_left", money(done.left))}</p>
            </div>
          )}
          <div className="ui-actions">
            <button
              className="ui-btn primary"
              onClick={() => {
                setDone(null);
                clear();
              }}
              type="button"
            >
              <Icon name="payments" />
              {pyt(language, "done_again")}
            </button>
            <a
              className="ui-btn"
              href={hashForPage("payments", `receipt:${done.paymentId}`)}
            >
              <Icon name="invoice" />
              {pyt(language, "view_receipt")}
            </a>
            <a className="ui-btn" href={hashForPage("payments")}>
              {pyt(language, "back")}
            </a>
          </div>
        </section>
      </>
    );
  }

  const shown = new Set(problems ?? []);
  const errorText = (name: Field): string => {
    switch (name) {
      case "cust":
        return pyt(language, "err_cust");
      case "amt":
        if (currency === "KHR" && rate === null)
          return pyt(language, "err_rate");
        if (currency === "KHR" && typedRiel !== null && rate) {
          const lower = Math.floor((typedRiel * 100) / rate);
          return pyt(
            language,
            "err_riel_grid",
            typedRiel.toLocaleString("en-US"),
            rielFor(lower, rate).toLocaleString("en-US"),
            money(lower),
            rielFor(lower + 1, rate).toLocaleString("en-US"),
            money(lower + 1),
          );
        }
        return pyt(
          language,
          currency === "USD" ? "err_amount" : "err_amount_khr",
        );
      case "method":
        return pyt(language, "err_method");
      case "when":
        return receivedAt(when) === null
          ? pyt(language, "err_when")
          : pyt(language, "err_future");
      case "ref":
        return pyt(language, "err_ref");
      case "payfor":
        return payIssue === null
          ? ""
          : payIssue.kind === "pick"
            ? pyt(language, "pf_err_pick")
            : payIssue.kind === "more"
              ? pyt(language, "pf_err_more", money(payIssue.rest))
              : payIssue.item.kind === "INVOICE"
                ? pyt(language, "pf_err_zero", payIssue.item.invoiceNumber)
                : pyt(language, "pf_err_zero_l", payIssue.item.invoiceNumber);
    }
  };
  const error = (name: Field) =>
    shown.has(name) && (
      <p className="ui-error" id={`${IDS[name]}-err`}>
        <Icon name="alert" small />
        <span>{errorText(name)}</span>
      </p>
    );
  const describedBy = (name: Field, help: boolean) =>
    [help ? `${IDS[name]}-help` : "", shown.has(name) ? `${IDS[name]}-err` : ""]
      .filter(Boolean)
      .join(" ") || undefined;
  const label = (name: Field, key: PaymentsTextKey, required = true) => (
    <label htmlFor={IDS[name]}>
      {pyt(language, key)}
      <span className="req">
        {pyt(language, required ? "required" : "optional")}
      </span>
    </label>
  );

  const payFor = (): ReactNode => {
    if (chosen === undefined)
      return <p className="ui-small ui-muted">{pyt(language, "pf_nocust")}</p>;
    if (itemsFailed)
      return (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{pyt(language, "failed")}</p>
          <button
            className="ui-btn"
            onClick={() => {
              readItems(chosen.id);
            }}
            type="button"
          >
            {pyt(language, "retry")}
          </button>
        </div>
      );
    if (items === null)
      return (
        <p className="ui-muted" role="status">
          {pyt(language, "loading")}
        </p>
      );
    if (list.length === 0)
      return <p className="ui-small">{pyt(language, "pf_none")}</p>;
    const late = list.some((item) => item.kind === "LATE_PAYMENT_CHARGE");
    return (
      <>
        <p className="help">
          {pyt(language, plan.auto ? "pf_help" : "pf_help_own")}
          {late ? ` ${pyt(language, "pfl_hint")}` : ""}
        </p>
        <div className="ui-pf-list">
          {plan.rows.map((row, index) => (
            <label
              className={`ui-pf-row${row.item.kind === "INVOICE" ? "" : " late"}`}
              key={row.item.id}
            >
              <input
                aria-describedby={
                  shown.has("payfor") ? `${IDS.payfor}-err` : undefined
                }
                checked={row.on}
                id={index === 0 ? IDS.payfor : undefined}
                onChange={() => {
                  toggle(row.item);
                }}
                type="checkbox"
              />
              <span className="ui-pf-name">
                {row.item.kind === "INVOICE" ? (
                  <>
                    <b className="ui-num">{row.item.invoiceNumber}</b>
                    {row.item.category !== null && isCategory(row.item.category)
                      ? ` · ${pyt(language, row.item.category)}`
                      : ""}
                    <small className="ui-num">
                      {pyt(language, "due_on")} {dayText(row.item.dueDate)} ·{" "}
                      {pyt(language, "pf_owed", money(row.item.owed))}
                    </small>
                  </>
                ) : (
                  <>
                    <b>{pyt(language, "pfl_row")}</b>
                    <small className="ui-num">
                      {pyt(
                        language,
                        "pfl_on",
                        row.item.invoiceNumber,
                        money(row.item.owed),
                      )}
                    </small>
                  </>
                )}
              </span>
              <span className="ui-pf-pays ui-num">
                {row.on && cents !== null
                  ? pyt(language, "pf_pays", money(row.pays))
                  : ""}
              </span>
            </label>
          ))}
          <div className="ui-pf-foot">
            {!plan.auto && (
              <button
                className="ui-btn link"
                onClick={() => {
                  setPicks(null);
                }}
                type="button"
              >
                {pyt(language, "pf_oldest")}
              </button>
            )}
            <span className="ui-small" role="status">
              {cents === null
                ? pyt(language, "pf_amt_first")
                : plan.rest === 0
                  ? pyt(language, "pf_all_used")
                  : plan.more
                    ? pyt(language, "pf_left_more", money(plan.rest))
                    : pyt(language, "pf_left", money(plan.rest))}
            </span>
          </div>
        </div>
      </>
    );
  };

  return (
    <>
      <button
        className="ui-crumb"
        onClick={() => {
          openPageInAddress("payments");
        }}
        type="button"
      >
        <Icon name="back" small />
        {pyt(language, "back")}
      </button>
      <div className="ui-head">
        <div>
          <h2>{pyt(language, "rp_title")}</h2>
          <p>{pyt(language, "rp_intro")}</p>
        </div>
      </div>
      <div className="ui-split ui-split-form">
        <form
          aria-label={pyt(language, "rp_title")}
          className="ui-card ui-form ui-pageform"
          noValidate
          onSubmit={check}
        >
          {outcome === "out_changed" && !confirming && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{pyt(language, "out_changed")}</p>
            </div>
          )}
          {problems !== null && problems.length > 0 && (
            <div
              className="ui-notice err"
              ref={summary}
              role="alert"
              tabIndex={-1}
            >
              <Icon name="alert" />
              <div>
                <b>{pyt(language, "err_sum", problems.length)}</b>
                <ul>
                  {problems.map((name) => (
                    <li key={name}>
                      <a
                        href={`#${IDS[name]}`}
                        onClick={(event) => {
                          event.preventDefault();
                          document.getElementById(IDS[name])?.focus();
                        }}
                      >
                        {errorText(name)}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          <div className="ui-field">
            {label("cust", "f_customer")}
            <select
              aria-describedby={describedBy("cust", false)}
              aria-invalid={shown.has("cust")}
              id={IDS.cust}
              onChange={(event) => {
                chooseCustomer(event.currentTarget.value);
              }}
              value={customer}
            >
              <option value="">{pyt(language, "f_choose")}</option>
              {customers.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.unit === ""
                    ? entry.name
                    : `${entry.name} · ${entry.unit}`}
                </option>
              ))}
            </select>
            {error("cust")}
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              <span className="lbl" id="rp-cur">
                {pyt(language, "f_currency")}
              </span>
              <div aria-labelledby="rp-cur" className="ui-seg" role="group">
                {(["USD", "KHR"] as const).map((value) => (
                  <button
                    aria-pressed={currency === value}
                    key={value}
                    onClick={() => {
                      setCurrency(value);
                      setAmount("");
                      setPicks(null);
                    }}
                    type="button"
                  >
                    {value === "USD" ? "$" : "៛"}{" "}
                    {pyt(language, value === "USD" ? "cur_USD" : "cur_KHR")}
                  </button>
                ))}
              </div>
            </div>
            <div className="ui-field">
              {label("amt", "f_amount")}
              <div className="ui-money">
                <span aria-hidden="true">{currency === "USD" ? "$" : "៛"}</span>
                <input
                  aria-describedby={describedBy("amt", currency === "KHR")}
                  aria-invalid={shown.has("amt")}
                  autoComplete="off"
                  id={IDS.amt}
                  inputMode={currency === "USD" ? "decimal" : "numeric"}
                  onChange={(event) => {
                    setAmount(event.currentTarget.value);
                  }}
                  value={amount}
                />
              </div>
              {currency === "KHR" && (
                <p className="help" id={`${IDS.amt}-help`}>
                  {rate
                    ? `${pyt(language, "fx_system")}: ${rate.toLocaleString("en-US")} ៛ = $1.00 · ${pyt(language, "fx_usd")}: ${cents === null ? "—" : money(cents)}`
                    : rate === null
                      ? pyt(language, "err_rate")
                      : pyt(language, "loading")}
                </p>
              )}
              {error("amt")}
            </div>
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              {label("method", "f_method")}
              <select
                aria-describedby={describedBy("method", false)}
                aria-invalid={shown.has("method")}
                id={IDS.method}
                onChange={(event) => {
                  setMethodId(event.currentTarget.value);
                }}
                value={methodId}
              >
                {(methods ?? []).map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.displayName}
                  </option>
                ))}
              </select>
              {error("method")}
            </div>
            <div className="ui-field">
              {label("when", "f_when")}
              <input
                aria-describedby={describedBy("when", true)}
                aria-invalid={shown.has("when")}
                autoComplete="off"
                className="ui-num"
                id={IDS.when}
                onChange={(event) => {
                  setWhen(event.currentTarget.value);
                }}
                value={when}
              />
              <p className="help" id={`${IDS.when}-help`}>
                {pyt(language, "f_when_help")}
              </p>
              {error("when")}
            </div>
          </div>
          <div className="ui-row2">
            {needsReference(method) && (
              <div className="ui-field">
                {label("ref", "f_ref")}
                <input
                  aria-describedby={describedBy("ref", false)}
                  aria-invalid={shown.has("ref")}
                  autoComplete="off"
                  id={IDS.ref}
                  maxLength={500}
                  onChange={(event) => {
                    setReference(event.currentTarget.value);
                  }}
                  value={reference}
                />
                {error("ref")}
              </div>
            )}
            <div className="ui-field">
              <label htmlFor="rp-note">
                {pyt(language, "f_note")}
                <span className="req">{pyt(language, "optional")}</span>
              </label>
              <input
                aria-describedby="rp-note-help"
                autoComplete="off"
                id="rp-note"
                maxLength={2000}
                onChange={(event) => {
                  setNote(event.currentTarget.value);
                }}
                value={note}
              />
              <p className="help" id="rp-note-help">
                {pyt(language, "f_note_help")}
              </p>
            </div>
          </div>
          <fieldset aria-invalid={shown.has("payfor")} className="ui-payfor">
            <legend>{pyt(language, "pf_t")}</legend>
            {payFor()}
            {error("payfor")}
          </fieldset>
          <div className="ui-actions">
            <button className="ui-btn primary" type="submit">
              <Icon name="check" />
              {pyt(language, "rp_submit")}
            </button>
            <button className="ui-btn" onClick={clear} type="button">
              {pyt(language, "clear")}
            </button>
          </div>
        </form>
        <div className="ui-stack">
          {chosen !== undefined && (
            <section aria-labelledby="rp-cust-card" className="ui-card">
              <h2 id="rp-cust-card">{chosen.name}</h2>
              <dl className="ui-kv">
                {chosen.unit !== "" && (
                  <>
                    <dt>{pyt(language, "unit")}</dt>
                    <dd className="ui-num">{chosen.unit}</dd>
                  </>
                )}
                {data.phones.get(chosen.id) !== undefined && (
                  <>
                    <dt>{pyt(language, "phone")}</dt>
                    <dd className="ui-num">{data.phones.get(chosen.id)}</dd>
                  </>
                )}
                {items !== null && (
                  <>
                    <dt>{pyt(language, "unpaid")}</dt>
                    <dd className="ui-num">
                      {money(
                        list.reduce((total, item) => total + item.owed, 0),
                      )}
                    </dd>
                  </>
                )}
              </dl>
            </section>
          )}
        </div>
      </div>
      {confirming && chosen !== undefined && cents !== null && (
        <Dialog
          busy={busy}
          closeLabel={pyt(language, "cancel")}
          onClose={() => {
            setConfirming(false);
          }}
          onSubmit={save}
          submitLabel={pyt(language, "rp_submit")}
          title={pyt(language, "dlg_pay_t")}
        >
          <dl className="ui-kv">
            <dt>{pyt(language, "f_customer")}</dt>
            <dd>
              {chosen.unit === ""
                ? chosen.name
                : `${chosen.name} · ${chosen.unit}`}
            </dd>
            <dt>{pyt(language, "f_amount")}</dt>
            <dd className="ui-num">{amountText()}</dd>
            <dt>{pyt(language, "f_method")}</dt>
            <dd>{method?.displayName ?? ""}</dd>
            <dt>{pyt(language, "f_when")}</dt>
            <dd className="ui-num">{when.trim()}</dd>
            <dt>{pyt(language, "rc_matched_to")}</dt>
            <dd>
              {paidRows.length === 0 ? (
                pyt(language, "pf_kept", money(cents))
              ) : (
                <ul className="ui-plain">
                  {paidRows.map((row) => (
                    <li key={row.item.id}>
                      {rowName(row.item)}:{" "}
                      <span className="ui-num">{money(row.pays)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </dd>
            {paidRows.length > 0 && plan.rest > 0 && (
              <>
                <dt>{pyt(language, "pf_left_t")}</dt>
                <dd>
                  <span className="ui-num">{money(plan.rest)}</span> ·{" "}
                  {pyt(language, "pf_ask")}
                </dd>
              </>
            )}
          </dl>
          <p>{pyt(language, "dlg_pay_c")}</p>
          <p className="ui-small ui-muted">{pyt(language, "pf_two")}</p>
          {outcome !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>
                {outcome === "pf_err_more"
                  ? pyt(language, "pf_err_more", money(plan.rest))
                  : pyt(language, outcome)}
              </p>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}

const CATEGORIES = [
  "RENT",
  "UTILITIES",
  "SERVICE_CHARGES",
  "MISCELLANEOUS_CHARGES",
  "DAMAGE_CHARGES",
] as const;

function isCategory(value: string): value is (typeof CATEGORIES)[number] {
  return (CATEGORIES as readonly string[]).includes(value);
}
