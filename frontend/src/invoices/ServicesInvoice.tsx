// V1.1 (DL-115 (I); mock-up round 13): Create Invoice › Services. Staff pick Regular services and
// How many; each price comes from Settings › Regular services and cannot be typed here. Picking a
// service that is already on the Invoice adds to its line. Saving makes one Draft; the request
// keeps its ids and key while the form is unchanged, so "Save" again after an unknown result is
// saved once. Owner 2026-10-29: such an Invoice counts in the "Rent and Services" report bar.

import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";

import {
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceResource,
} from "../invoiceClient";
import type {
  RegularService,
  RegularServicesApi,
} from "../settings/serviceSettingsClient";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { ivt, type InvoicesTextKey } from "./text";

const MAX_LINES = 20;
const MAX_QUANTITY = 9_999;

interface Line {
  key: string;
  serviceId: string;
  quantity: string;
}

export interface CustomerChoice {
  id: string;
  name: string;
  unit: string;
}

type Problem = "cust" | "none" | `s:${string}` | `q:${string}`;

function blankLine(): Line {
  return { key: crypto.randomUUID(), serviceId: "", quantity: "1" };
}

function quantityOf(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,4}$/.test(value)) return null;
  const number = Number(value);
  return number >= 1 && number <= MAX_QUANTITY ? number : null;
}

function nameOf(language: Language, service: RegularService): string {
  return language === "km" && service.name_km !== null
    ? service.name_km
    : service.name_en;
}

/** The same service picked on two lines becomes one line with both counts (round 13). */
export function mergeLines(lines: readonly Line[]): Line[] {
  const merged: Line[] = [];
  for (const line of lines) {
    const earlier =
      line.serviceId === ""
        ? undefined
        : merged.find((item) => item.serviceId === line.serviceId);
    const here = quantityOf(line.quantity);
    const there = earlier === undefined ? null : quantityOf(earlier.quantity);
    if (earlier !== undefined && here !== null && there !== null) {
      earlier.quantity = String(Math.min(MAX_QUANTITY, here + there));
    } else {
      merged.push({ ...line });
    }
  }
  return merged;
}

export function ServicesInvoice({
  language,
  propertyId,
  api,
  servicesApi,
  customers,
  leaseOf,
  kindPicker,
  back,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: Pick<InvoiceApi, "createWithServices">;
  servicesApi: Pick<RegularServicesApi, "read">;
  customers: CustomerChoice[];
  leaseOf: (customerId: string) => string | null;
  kindPicker: ReactNode;
  back: ReactNode;
  onSaved: () => void;
}) {
  const [services, setServices] = useState<RegularService[] | "failed" | null>(
    null,
  );
  const [customer, setCustomer] = useState("");
  const [lines, setLines] = useState<Line[]>(() => [blankLine()]);
  const [problems, setProblems] = useState<Problem[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<
    "unknown" | "refused" | "sv_gone" | null
  >(null);
  const [done, setDone] = useState<InvoiceResource | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const sequence = useRef(0);
  const identity = useRef<{
    sent: string;
    key: string;
    charges: Map<string, string>;
  } | null>(null);

  const load = () => {
    const operation = ++sequence.current;
    void servicesApi.read(propertyId).then(
      (found) => {
        if (operation === sequence.current) setServices(found.regular_services);
      },
      () => {
        if (operation === sequence.current)
          setServices((before) => (Array.isArray(before) ? before : "failed"));
      },
    );
  };
  useEffect(load, [servicesApi, propertyId]);

  const label = (entry: CustomerChoice) =>
    entry.unit === "" ? entry.name : `${entry.name} · ${entry.unit}`;
  const chosen = customers.find((entry) => entry.id === customer);
  const known = Array.isArray(services) ? services : [];
  const values = lines.map((line) => {
    const service = known.find(
      (item) => item.regular_service_id === line.serviceId,
    );
    const quantity = quantityOf(line.quantity);
    return {
      line,
      service,
      quantity,
      amount:
        service === undefined || quantity === null
          ? null
          : service.price_usd_cents * quantity,
    };
  });
  const total = values.reduce((sum, value) => sum + (value.amount ?? 0), 0);
  const shown = new Set<Problem>(problems ?? []);
  const number = (key: string) =>
    lines.findIndex((line) => line.key === key) + 1;
  const problemText = (problem: Problem): string => {
    if (problem === "cust") return ivt(language, "ni_err_cust");
    if (problem === "none") return ivt(language, "sv_err_svc");
    const [part, key] = problem.split(":") as ["s" | "q", string];
    const text: InvoicesTextKey = part === "s" ? "sv_err_pick" : "sv_err_qty";
    return ivt(language, text, number(key));
  };
  const problemId = (problem: Problem): string => {
    if (problem === "cust") return "ns-cust";
    if (problem === "none") return "ns-add";
    const [part, key] = problem.split(":") as ["s" | "q", string];
    return `ns-${part}-${key}`;
  };
  const update = (key: string, patch: Partial<Line>) => {
    setLines((current) =>
      mergeLines(
        current.map((line) => (line.key === key ? { ...line, ...patch } : line)),
      ),
    );
  };

  const check = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const found: Problem[] = [];
    if (chosen === undefined) found.push("cust");
    if (lines.length === 0) found.push("none");
    for (const value of values) {
      if (value.service === undefined) found.push(`s:${value.line.key}`);
      if (value.quantity === null) found.push(`q:${value.line.key}`);
    }
    setProblems(found);
    if (found.length > 0) {
      setTimeout(() => summary.current?.focus(), 0);
      return;
    }
    setOutcome(null);
    setConfirming(true);
  };

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (chosen === undefined || busy) return;
    const items = values.flatMap((value) =>
      value.service === undefined || value.quantity === null
        ? []
        : [
            {
              key: value.line.key,
              regular_service_id: value.service.regular_service_id,
              quantity: value.quantity,
            },
          ],
    );
    if (items.length !== values.length || items.length === 0) return;
    const leaseId = leaseOf(chosen.id);
    const sent = JSON.stringify({
      customer: chosen.id,
      leaseId,
      items: items.map((item) => [item.key, item.regular_service_id, item.quantity]),
    });
    if (identity.current?.sent !== sent) {
      identity.current = {
        sent,
        key: crypto.randomUUID(),
        charges: new Map(items.map((item) => [item.key, crypto.randomUUID()])),
      };
    }
    const { key, charges } = identity.current;
    setBusy(true);
    setOutcome(null);
    void api
      .createWithServices(
        propertyId,
        {
          customer_id: chosen.id,
          lease_id: leaseId,
          items: items.map((item) => ({
            charge_id: charges.get(item.key) ?? crypto.randomUUID(),
            regular_service_id: item.regular_service_id,
            quantity: item.quantity,
          })),
        },
        key,
      )
      .then((draft) => {
        setDone(draft);
        setConfirming(false);
        onSaved();
      })
      .catch((error: unknown) => {
        if (error instanceof InvoiceClientError && error.status === 404) {
          // A service was removed meanwhile: read the list again before another try.
          setOutcome("sv_gone");
          load();
          return;
        }
        setOutcome(
          error instanceof InvoiceClientError && !error.outcomeUnknown
            ? "refused"
            : "unknown",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const backToList = () => {
    openPageInAddress("invoices");
  };

  if (done !== null) {
    return (
      <>
        <div className="ui-head">
          <div className="ui-hrow">
            <h2>{ivt(language, "ni_done_t")}</h2>
            <Chip tone="info">{ivt(language, "st_draft")}</Chip>
          </div>
        </div>
        <section className="ui-card">
          <div className="ui-notice ok" role="status">
            <Icon name="check" />
            <p>
              {ivt(
                language,
                "ni_done_b",
                chosen?.name ?? "",
                chosen?.unit ?? "",
                values.length,
                usdFromCents(total),
              )}
            </p>
          </div>
          <div className="ui-actions">
            <a
              className="ui-btn primary"
              href={hashForPage("invoices", `inv:${done.id}`)}
            >
              <Icon name="invoice" />
              {ivt(language, "ni_open")}
            </a>
            <button className="ui-btn" onClick={backToList} type="button">
              {ivt(language, "ni_to_list")}
            </button>
          </div>
        </section>
      </>
    );
  }

  let body: ReactNode;
  if (services === null) {
    body = (
      <p className="ui-muted" role="status">
        {ivt(language, "loading")}
      </p>
    );
  } else if (services === "failed") {
    body = (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ivt(language, "sv_failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {ivt(language, "retry")}
        </button>
      </div>
    );
  } else if (services.length === 0) {
    body = (
      <div className="ui-notice" role="note">
        <Icon name="info" />
        <p>{ivt(language, "sv_none")}</p>
      </div>
    );
  } else if (customers.length === 0) {
    body = (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ivt(language, "ni_none")}</p>
      </div>
    );
  } else {
    body = (
      <>
        <div className="ui-field">
          <label htmlFor="ns-cust">
            {ivt(language, "f_customer")}
            <span className="req">{ivt(language, "required")}</span>
          </label>
          <select
            aria-describedby={shown.has("cust") ? "ns-cust-err" : undefined}
            aria-invalid={shown.has("cust")}
            id="ns-cust"
            onChange={(event) => {
              setCustomer(event.currentTarget.value);
            }}
            value={customer}
          >
            <option value="">{ivt(language, "f_choose")}</option>
            {customers.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {label(entry)}
              </option>
            ))}
          </select>
          {shown.has("cust") && (
            <p className="ui-error" id="ns-cust-err">
              <Icon name="alert" small />
              <span>{ivt(language, "ni_err_cust")}</span>
            </p>
          )}
        </div>
        <div className="ui-field">
          <span className="lbl" id="ns-items">
            {ivt(language, "ni_items")}
            <span className="req">{ivt(language, "required")}</span>
          </span>
          <p className="help" id="ns-items-help">
            {ivt(language, "sv_note")}
          </p>
          <div
            aria-describedby="ns-items-help"
            aria-labelledby="ns-items"
            className="ui-items"
            role="group"
          >
            <div aria-hidden="true" className="ui-items-head">
              <span>{ivt(language, "sv_svc")}</span>
              <span>{ivt(language, "sv_how_many")}</span>
              <span>{ivt(language, "ni_price")}</span>
              <span className="r">{ivt(language, "ni_line_amt")}</span>
              <span />
            </div>
            {values.map((value, index) => {
              const { line } = value;
              const n = index + 1;
              const badS = shown.has(`s:${line.key}`);
              const badQ = shown.has(`q:${line.key}`);
              const errorId = `ns-row-${line.key}-err`;
              return (
                <div className="ui-item" key={line.key}>
                  <div className="desc">
                    <label className="ui-item-lbl" htmlFor={`ns-s-${line.key}`}>
                      {ivt(language, "sv_item_n", n)}
                    </label>
                    <select
                      aria-describedby={badS ? errorId : undefined}
                      aria-invalid={badS}
                      id={`ns-s-${line.key}`}
                      onChange={(event) => {
                        update(line.key, {
                          serviceId: event.currentTarget.value,
                        });
                      }}
                      value={line.serviceId}
                    >
                      <option value="">{ivt(language, "sv_pick")}</option>
                      {known.map((service) => (
                        <option
                          key={service.regular_service_id}
                          value={service.regular_service_id}
                        >
                          {nameOf(language, service)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="qty">
                    <label className="ui-item-lbl" htmlFor={`ns-q-${line.key}`}>
                      {`${ivt(language, "sv_how_many")}, ${ivt(language, "sv_item_n", n)}`}
                    </label>
                    <input
                      aria-describedby={badQ ? errorId : undefined}
                      aria-invalid={badQ}
                      autoComplete="off"
                      id={`ns-q-${line.key}`}
                      inputMode="numeric"
                      maxLength={4}
                      onChange={(event) => {
                        const quantity = event.currentTarget.value;
                        setLines((current) =>
                          current.map((item) =>
                            item.key === line.key ? { ...item, quantity } : item,
                          ),
                        );
                      }}
                      value={line.quantity}
                    />
                  </div>
                  <output
                    aria-label={`${ivt(language, "ni_price")}, ${ivt(language, "sv_item_n", n)}`}
                    className="price ui-num"
                  >
                    {value.service === undefined
                      ? "—"
                      : usdFromCents(value.service.price_usd_cents)}
                  </output>
                  <output
                    aria-label={`${ivt(language, "ni_line_amt")}, ${ivt(language, "sv_item_n", n)}`}
                    className="amt ui-num"
                  >
                    {value.amount === null ? "—" : usdFromCents(value.amount)}
                  </output>
                  <button
                    aria-label={ivt(language, "sv_remove", n)}
                    className="ui-btn rm"
                    disabled={lines.length === 1}
                    onClick={() => {
                      setLines((current) =>
                        current.filter((item) => item.key !== line.key),
                      );
                    }}
                    type="button"
                  >
                    <Icon name="x" small />
                  </button>
                  {(badS || badQ) && (
                    <div className="ui-item-errs" id={errorId}>
                      {badS && (
                        <p className="ui-error">
                          <Icon name="alert" small />
                          <span>{ivt(language, "sv_err_pick", n)}</span>
                        </p>
                      )}
                      {badQ && (
                        <p className="ui-error">
                          <Icon name="alert" small />
                          <span>{ivt(language, "sv_err_qty", n)}</span>
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            <div className="ui-items-foot">
              <button
                className="ui-btn"
                disabled={lines.length >= MAX_LINES}
                id="ns-add"
                onClick={() => {
                  setLines((current) => [...current, blankLine()]);
                }}
                type="button"
              >
                <Icon name="plus" small />
                {ivt(language, "sv_add")}
              </button>
              <span className="ui-items-total">
                <span>{ivt(language, "ni_total")}</span>
                <b className="ui-num" role="status">
                  {usdFromCents(total)}
                </b>
              </span>
            </div>
            {lines.length >= MAX_LINES && (
              <p className="help">{ivt(language, "ni_items_max")}</p>
            )}
          </div>
        </div>
        <div className="ui-actions">
          <button className="ui-btn primary" type="submit">
            <Icon name="check" />
            {ivt(language, "ni_submit")}
          </button>
          <button className="ui-btn" onClick={backToList} type="button">
            {ivt(language, "cancel")}
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <h2>{ivt(language, "ni_btn")}</h2>
          <p>{ivt(language, "ni_intro")}</p>
        </div>
      </div>
      <div className="ui-split ui-split-wide">
        <form
          aria-label={ivt(language, "ni_btn")}
          className="ui-card ui-form ui-pageform"
          noValidate
          onSubmit={check}
        >
          {problems !== null && problems.length > 0 && (
            <div
              className="ui-notice err"
              ref={summary}
              role="alert"
              tabIndex={-1}
            >
              <Icon name="alert" />
              <div>
                <b>{ivt(language, "err_sum", problems.length)}</b>
                <ul>
                  {problems.map((problem) => (
                    <li key={problem}>
                      <a
                        href={`#${problemId(problem)}`}
                        onClick={(event) => {
                          event.preventDefault();
                          document.getElementById(problemId(problem))?.focus();
                        }}
                      >
                        {problemText(problem)}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {kindPicker}
          {body}
        </form>
        <div className="ui-stack">
          <section aria-labelledby="ns-next" className="ui-card">
            <h2 id="ns-next">{ivt(language, "ni_what_t")}</h2>
            <ol className="ui-steps">
              <li>{ivt(language, "ni_w1")}</li>
              <li>{ivt(language, "ni_w2")}</li>
              <li>{ivt(language, "ni_w3")}</li>
              <li>{ivt(language, "ni_w4")}</li>
            </ol>
          </section>
        </div>
      </div>
      {confirming && chosen !== undefined && (
        <Dialog
          busy={busy}
          closeLabel={ivt(language, "cancel")}
          onClose={() => {
            setConfirming(false);
          }}
          onSubmit={save}
          submitLabel={ivt(language, "ni_submit")}
          title={ivt(language, "ni_dlg_t")}
          wide
        >
          <dl className="ui-kv">
            <dt>{ivt(language, "ni_kind")}</dt>
            <dd>{ivt(language, "SERVICES")}</dd>
            <dt>{ivt(language, "f_customer")}</dt>
            <dd>{label(chosen)}</dd>
          </dl>
          <div className="ui-tablewrap">
            <table className="ui-table fit">
              <caption className="ui-sr">{ivt(language, "ni_items")}</caption>
              <thead>
                <tr>
                  <th scope="col">{ivt(language, "sv_svc")}</th>
                  <th className="r" scope="col">
                    {ivt(language, "sv_how_many")}
                  </th>
                  <th className="r" scope="col">
                    {ivt(language, "ni_price")}
                  </th>
                  <th className="r" scope="col">
                    {ivt(language, "ni_line_amt")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {values.map((value) => (
                  <tr key={value.line.key}>
                    <td className="wrap">
                      {value.service === undefined
                        ? ""
                        : nameOf(language, value.service)}
                    </td>
                    <td className="r ui-num">{value.quantity}</td>
                    <td className="r ui-num">
                      {usdFromCents(value.service?.price_usd_cents ?? 0)}
                    </td>
                    <td className="r ui-num">
                      {usdFromCents(value.amount ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th colSpan={3} scope="row">
                    {ivt(language, "ni_total")}
                  </th>
                  <td className="r ui-num">
                    <b>{usdFromCents(total)}</b>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p>{ivt(language, "ni_dlg_c")}</p>
          {outcome !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{ivt(language, outcome)}</p>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}
