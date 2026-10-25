// V1-058 R5: one Invoice (DESIGN.md "Invoice page"): the head with its number and status, the
// overdue, void or draft notice, what is billed, the Invoice status card with the bar from the
// issue date to the Due Date, the Customer, and the History. The printed Invoice, Receive
// payment, Adjust, Void and the late-payment card come in the next steps.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceResource,
  type JsonValue,
} from "../invoiceClient";
import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import type { Language } from "../signInText";
import { InvoiceChip } from "./InvoicesList";
import {
  type InvoicesData,
  cents,
  dayAfter,
  daysBetween,
  paidOf,
  stateOf,
  unitOf,
} from "./invoicesData";
import { ivt } from "./text";

function textOf(value: JsonValue | undefined): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

/** A line's period as "01/11/2026 to 30/11/2026", when it has one. */
function periodText(language: Language, period: JsonValue): string | null {
  if (typeof period !== "object" || period === null || Array.isArray(period))
    return null;
  const start = textOf(period.start);
  const end = textOf(period.end);
  if (start === null || end === null) return null;
  return ivt(language, "line_period", dayText(start), dayText(end));
}

/** The bar from the issue date to the later of the Due Date and today, with a dot for each. */
function AgeBar({
  language,
  issued,
  due,
  today,
  late,
}: {
  language: Language;
  issued: string;
  due: string;
  today: string;
  late: boolean;
}) {
  const marks: [string, string][] = late
    ? [
        [issued, ivt(language, "is_issued")],
        [due, ivt(language, "is_due")],
        [today, ivt(language, "is_today", daysBetween(due, today))],
      ]
    : [
        [issued, ivt(language, "is_issued")],
        [today < issued ? issued : today, ivt(language, "is_now")],
        [due, ivt(language, "is_due")],
      ];
  const low = issued;
  const high = late ? today : due;
  const span = Math.max(1, daysBetween(low, high));
  const at = (day: string) =>
    Math.min(
      100,
      Math.max(0, Math.round((daysBetween(low, day) * 100) / span)),
    );
  // A middle label too close to an end label is left out; its dot stays on the bar.
  const [first, middle, last] = marks;
  const labels = [first, middle, last].filter(
    (mark, index) =>
      mark !== undefined &&
      (index !== 1 || (at(mark[0]) >= 20 && at(mark[0]) <= 80)),
  ) as [string, string][];
  return (
    <>
      <div aria-hidden="true" className="ui-agebar">
        {late ? (
          <>
            <i
              className="ok"
              style={{ left: 0, width: `${String(at(due))}%` }}
            />
            <i
              className="late"
              style={{
                left: `${String(at(due))}%`,
                width: `${String(100 - at(due))}%`,
              }}
            />
          </>
        ) : (
          <i
            className="ok"
            style={{
              left: 0,
              width: `${String(at(today < low ? low : today))}%`,
            }}
          />
        )}
        {marks.map(([day], index) => (
          <em key={index} style={{ left: `${String(at(day))}%` }} />
        ))}
      </div>
      <div className="ui-agelbl">
        {labels.map(([day, label], index) => (
          <span key={index} style={{ left: `${String(at(day))}%` }}>
            <b className="ui-num">{dayText(day).slice(0, 5)}</b>
            <small>{label}</small>
          </span>
        ))}
      </div>
    </>
  );
}

function StatusCard({
  language,
  invoice,
  today,
}: {
  language: Language;
  invoice: InvoiceResource;
  today: string;
}) {
  const state = stateOf(invoice, today);
  const billed = cents(invoice.adjusted_total);
  const paid = paidOf(invoice);
  const owed = Math.max(0, cents(invoice.outstanding_balance));
  const percent = billed > 0 ? Math.round((paid * 100) / billed) : 0;
  const issued = invoice.invoice_date;
  const due = invoice.due_date;
  const late = state === "overdue";
  return (
    <section aria-labelledby="inv-status" className="ui-card">
      <div className="ui-chead">
        <h2 id="inv-status">{ivt(language, "is_t")}</h2>
        <InvoiceChip language={language} state={state} />
      </div>
      {due !== null &&
        (state === "overdue" || state === "part" || state === "unpaid") && (
          <div className={late ? "ui-aging late" : "ui-aging"}>
            <div className="ui-big">
              <span>
                {ivt(language, late ? "is_past_due" : "is_until_due")}
              </span>
              <span className="val">
                <b className="ui-num">
                  {Math.max(
                    0,
                    late ? daysBetween(due, today) : daysBetween(today, due),
                  )}
                </b>{" "}
                {ivt(language, "is_days")}
              </span>
            </div>
            <AgeBar
              due={due}
              issued={issued}
              language={language}
              late={late}
              today={today}
            />
          </div>
        )}
      {state === "paid" && (
        <div className="ui-aging">
          <div className="ui-big">
            <span>{ivt(language, "is_paid_full")}</span>
          </div>
        </div>
      )}
      <dl className="ui-kv ui-is">
        <dt>{ivt(language, "is_billed")}</dt>
        <dd className="ui-num">{usdFromCents(billed)}</dd>
        <dt>{ivt(language, "is_received")}</dt>
        <dd className={`ui-num${paid > 0 ? " okv" : " ui-muted"}`}>
          {usdFromCents(paid)} ({percent}%)
        </dd>
        {state !== "draft" && state !== "void" && (
          <>
            <dt className="tot">
              {ivt(language, late ? "is_overdue_amt" : "balance_due")}
            </dt>
            <dd className={`ui-num tot${late ? " errv" : ""}`}>
              {usdFromCents(owed)}
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}

export function InvoiceDetail({
  language,
  api,
  invoiceId,
  data,
  today,
  capabilities,
  propertyId,
}: {
  language: Language;
  api: Pick<InvoiceApi, "get">;
  invoiceId: string;
  /** An Invoice of another Property is not shown here. */
  propertyId: string;
  /** The list data, for the Customer name and Unit; null while it loads. */
  data: InvoicesData | null;
  today: string;
  capabilities: ReadonlySet<string> | null;
}) {
  const [invoice, setInvoice] = useState<InvoiceResource | null>(null);
  const [problem, setProblem] = useState<"missing" | "failed" | null>(null);
  const sequence = useRef(0);
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setProblem(null);
    void api
      .get(invoiceId)
      .then((found) => {
        if (operation !== sequence.current) return;
        if (found.property_id === propertyId) setInvoice(found);
        else setProblem("missing");
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(
          error instanceof InvoiceClientError &&
            (error.status === 403 || error.status === 404)
            ? "missing"
            : "failed",
        );
      });
  }, [api, invoiceId, propertyId]);

  useEffect(() => {
    load();
  }, [load]);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("invoices");
      }}
      type="button"
    >
      <Icon name="back" small />
      {ivt(language, "back")}
    </button>
  );

  if (invoice === null) {
    return (
      <>
        {back}
        {problem === null ? (
          <p className="ui-muted" role="status">
            {ivt(language, "loading_one")}
          </p>
        ) : (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>
              {ivt(language, problem === "missing" ? "not_found" : "failed")}
            </p>
            {problem === "failed" && (
              <button className="ui-btn" onClick={load} type="button">
                {ivt(language, "retry")}
              </button>
            )}
          </div>
        )}
      </>
    );
  }

  const state = stateOf(invoice, today);
  const name = data?.names.get(invoice.customer_id) ?? null;
  const unit = data === null ? "" : unitOf(data, invoice);
  const owed = Math.max(0, cents(invoice.outstanding_balance));
  const changed =
    cents(invoice.adjusted_total) !== cents(invoice.original_total);
  const history: [string, string][] = [];
  const made =
    textOf(invoice.evidence.issued_at) ?? textOf(invoice.evidence.created_at);
  history.push([made ?? invoice.invoice_date, ivt(language, "h_made")]);
  for (const adjustment of invoice.adjustments) {
    const reason = textOf(adjustment.reason) ?? "";
    history.push([
      textOf(adjustment.occurred_at) ?? "",
      ivt(language, "h_adjusted", reason),
    ]);
  }
  if (state === "overdue" && invoice.due_date !== null)
    history.push([
      dayAfter(invoice.due_date),
      ivt(language, "h_overdue", usdFromCents(owed)),
    ]);
  const voidEvent =
    typeof invoice.void_event === "object" &&
    invoice.void_event !== null &&
    !Array.isArray(invoice.void_event)
      ? invoice.void_event
      : null;
  if (voidEvent !== null)
    history.push([
      textOf(voidEvent.occurred_at) ?? "",
      ivt(language, "h_voided", textOf(voidEvent.reason) ?? ""),
    ]);
  // A plain date is a day in Phnom Penh; the moments are UTC. Both are compared as moments.
  const momentOf = (when: string) =>
    Date.parse(when.length === 10 ? `${when}T00:00:00+07:00` : when);
  history.sort((left, right) => momentOf(left[0]) - momentOf(right[0]));

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num">
              {state === "draft"
                ? ivt(language, "ni_draft_no")
                : invoice.invoice_number}
            </h2>
            <InvoiceChip language={language} state={state} />
          </div>
          <p>
            {[ivt(language, invoice.category), name, unit]
              .filter((part) => part !== null && part !== "")
              .join(" · ")}
          </p>
        </div>
      </div>
      {state === "overdue" && invoice.due_date !== null && (
        <div className="ui-notice err" role="note">
          <Icon name="alert" />
          <p>
            {ivt(language, "late_banner", dayText(dayAfter(invoice.due_date)))}
          </p>
        </div>
      )}
      {state === "void" && (
        <div className="ui-notice" role="note">
          <Icon name="info" />
          <p>{ivt(language, "void_banner")}</p>
        </div>
      )}
      {state === "draft" && (
        <div className="ui-notice" role="note">
          <Icon name="info" />
          <p>{ivt(language, "draft_banner")}</p>
        </div>
      )}
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="inv-lines" className="ui-card">
            <h2 id="inv-lines">{ivt(language, "lines_t")}</h2>
            <div className="ui-tablewrap">
              <table className="ui-table fit">
                <thead>
                  <tr>
                    <th scope="col">{ivt(language, "line_desc")}</th>
                    <th className="r" scope="col">
                      {ivt(language, "col_amount")}
                    </th>
                    <th className="r" scope="col">
                      {ivt(language, "col_balance")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[...invoice.lines]
                    .sort((left, right) => left.sequence - right.sequence)
                    .map((line) => {
                      const period = periodText(language, line.period);
                      const was = cents(line.original_amount);
                      const now = cents(line.adjusted_amount);
                      return (
                        <tr key={line.id}>
                          <td className="wrap">
                            <b>{line.description}</b>
                            <span className="ui-sub2">
                              {[ivt(language, line.category), period]
                                .filter(Boolean)
                                .join(" · ")}
                            </span>
                          </td>
                          <td className="r ui-num">
                            {usdFromCents(now)}
                            {was !== now && (
                              <span className="ui-sub2">
                                {ivt(
                                  language,
                                  "line_adjusted",
                                  usdFromCents(was),
                                )}
                              </span>
                            )}
                          </td>
                          <td className="r ui-num">
                            {state === "draft" || state === "void" ? (
                              <span className="ui-muted">—</span>
                            ) : (
                              usdFromCents(
                                Math.max(0, cents(line.outstanding_balance)),
                              )
                            )}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row">
                      {ivt(language, changed ? "adjusted_total" : "total")}
                    </th>
                    <td className="r ui-num">
                      <b>{usdFromCents(cents(invoice.adjusted_total))}</b>
                    </td>
                    <td className="r ui-num">
                      {state === "draft" || state === "void" ? (
                        <span className="ui-muted">—</span>
                      ) : (
                        <b>{usdFromCents(owed)}</b>
                      )}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <dl className="ui-kv">
              <dt>{ivt(language, "is_issued")}</dt>
              <dd className="ui-num">{dayText(invoice.invoice_date)}</dd>
              <dt>{ivt(language, "col_due")}</dt>
              <dd className="ui-num">
                {invoice.due_date === null
                  ? ivt(language, "ni_due_later")
                  : dayText(invoice.due_date)}
              </dd>
            </dl>
          </section>
        </div>
        <div className="ui-stack">
          <StatusCard invoice={invoice} language={language} today={today} />
          <section aria-labelledby="inv-cust" className="ui-card">
            <h2 id="inv-cust">{ivt(language, "cust_t")}</h2>
            <p>
              <b>{name ?? ivt(language, "unknown_customer")}</b>
              {unit !== "" && <span className="ui-sub2">{unit}</span>}
            </p>
            <div className="ui-actions">
              {may("customers.read") && (
                <a
                  className="ui-btn"
                  href={hashForPage("customers", invoice.customer_id)}
                >
                  {ivt(language, "open_customer")}
                </a>
              )}
              {invoice.lease_id !== null && may("leases.read") && (
                <a
                  className="ui-btn"
                  href={hashForPage("leases", invoice.lease_id)}
                >
                  {ivt(language, "open_lease")}
                </a>
              )}
              <a
                className="ui-btn"
                href={hashForPage("invoices", `for:${invoice.customer_id}`)}
              >
                {unit !== ""
                  ? ivt(language, "all_for", unit)
                  : name !== null
                    ? ivt(language, "all_for", name)
                    : ivt(language, "all_for_cust")}
              </a>
            </div>
          </section>
          <section aria-labelledby="inv-hist" className="ui-card">
            <h2 id="inv-hist">{ivt(language, "history_t")}</h2>
            <ol className="ui-timeline">
              {history.map(([when, what], index) => (
                <li key={index}>
                  <div>
                    {what}
                    {when !== "" && (
                      <small className="ui-num">
                        {when.length > 10 ? momentText(when) : dayText(when)}
                      </small>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
    </>
  );
}
