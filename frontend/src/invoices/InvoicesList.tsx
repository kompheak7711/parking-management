// V1-058 R5: the Invoices list (DESIGN.md "Invoices layout" and "Summary cards (Invoices and
// Meters)"): the period switch and Type select, four summary cards that filter the list, the
// add-up line, and the list with the Drafts at the top.

import { useState } from "react";

import type { InvoiceCategory, InvoiceResource } from "../invoiceClient";
import { dayText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, CountCard, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import { monthText } from "../utilities/text";
import {
  type InvoiceCard,
  type InvoicePeriod,
  type InvoiceState,
  type InvoicesData,
  cardAmount,
  cents,
  filtered,
  inCard,
  periodMonth,
  sortInvoices,
  stateOf,
  unitOf,
} from "./invoicesData";
import { ivt, type InvoicesTextKey } from "./text";

const STATE_CHIPS: Record<
  InvoiceState,
  [Tone, ShellIcon | undefined, InvoicesTextKey]
> = {
  draft: ["info", undefined, "st_draft"],
  void: ["neutral", "x", "st_void"],
  paid: ["ok", "check", "st_paid"],
  overdue: ["err", "alert", "st_overdue"],
  part: ["warn", "clock", "st_part"],
  unpaid: ["neutral", undefined, "st_unpaid"],
};

export function InvoiceChip({
  language,
  state,
}: {
  language: Language;
  state: InvoiceState;
}) {
  const [tone, icon, key] = STATE_CHIPS[state];
  return (
    <Chip icon={icon} tone={tone}>
      {ivt(language, key)}
    </Chip>
  );
}

const CARDS: [InvoiceCard, ShellIcon, Tone | "brand", InvoicesTextKey][] = [
  ["all", "invoice", "brand", "ic_total"],
  ["open", "clock", "warn", "ic_unpaid"],
  ["overdue", "alert", "err", "ic_over"],
  ["paid", "check", "ok", "ic_paid"],
];

const TYPES: (InvoiceCategory | "all")[] = [
  "all",
  "RENT",
  "UTILITIES",
  "SERVICE_CHARGES",
  "MISCELLANEOUS_CHARGES",
  "DAMAGE_CHARGES",
];

function countText(language: Language, count: number): string {
  return count === 1 ? ivt(language, "ic_n1") : ivt(language, "ic_n", count);
}

export function InvoicesList({
  language,
  data,
  today,
  customerId,
  onClearCustomer,
  canCreate,
}: {
  language: Language;
  data: InvoicesData;
  today: string;
  /** Only this Customer's Invoices, from "All Invoices for U201" on an Invoice page. */
  customerId: string | null;
  onClearCustomer: () => void;
  /** Create Invoice shows only to a person who may create one. */
  canCreate: boolean;
}) {
  const [period, setPeriod] = useState<InvoicePeriod>("all");
  const [picked, setPicked] = useState(today.slice(0, 7));
  const [type, setType] = useState<InvoiceCategory | "all">("all");
  const [card, setCard] = useState<InvoiceCard>("all");

  const month = periodMonth(period, today, picked);
  const base = filtered(data.invoices, month, type, customerId);
  const issued = base.filter((invoice) => invoice.status !== "DRAFT");
  // Drafts have no Due Date, so a month never lists them; the add-up line still counts them.
  const drafts = filtered(data.invoices, null, type, customerId).filter(
    (invoice) => invoice.status === "DRAFT",
  );
  const rows = sortInvoices(
    issued.filter(
      (invoice) =>
        // Void Invoices are listed under All only; they count in no card.
        (card === "all" && invoice.status === "VOID") ||
        inCard(invoice, card, today),
    ),
  );
  const shownDrafts =
    card === "all" && month === null ? sortInvoices(drafts) : [];
  const voids = rows.filter((invoice) => invoice.status === "VOID").length;
  const amounts = new Map(
    CARDS.map(([value]) => [value, cardAmount(issued, value, today)]),
  );
  const months = [
    ...new Set([
      today.slice(0, 7),
      ...data.invoices.flatMap((invoice) =>
        invoice.due_date === null ? [] : [invoice.due_date.slice(0, 7)],
      ),
    ]),
  ].sort((left, right) => right.localeCompare(left));
  const paid = amounts.get("paid") ?? 0;
  const owed = amounts.get("open") ?? 0;
  const late = amounts.get("overdue") ?? 0;
  const addUp = [
    ivt(
      language,
      "ic_addup",
      usdFromCents(paid),
      usdFromCents(owed),
      usdFromCents(paid + owed),
    ),
    late > 0 ? ivt(language, "ic_addup_late", usdFromCents(late)) : "",
    drafts.length === 1
      ? ivt(language, "ic_drafts1")
      : drafts.length > 1
        ? ivt(language, "ic_drafts", drafts.length)
        : "",
  ]
    .filter(Boolean)
    .join(" ");
  const who =
    customerId === null
      ? null
      : (data.names.get(customerId) ?? ivt(language, "unknown_customer"));
  const open = (id: string) => {
    openPageInAddress("invoices", false, `inv:${id}`);
  };

  const row = (invoice: InvoiceResource) => {
    const state = stateOf(invoice, today);
    const draft = state === "draft";
    const href = hashForPage("invoices", `inv:${invoice.id}`);
    return (
      <tr
        className="ui-row"
        key={invoice.id}
        onClick={() => {
          open(invoice.id);
        }}
      >
        <td>
          <a
            className="ui-no ui-num"
            href={href}
            onClick={(event) => {
              event.stopPropagation();
              // A plain click opens the Invoice here; with a key held the browser opens the
              // link as it normally does.
              if (
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              )
                return;
              event.preventDefault();
              open(invoice.id);
            }}
          >
            {draft ? ivt(language, "ni_draft_no") : invoice.invoice_number}
          </a>
          {/* On a phone the type, Due Date and amount fold under the number. */}
          <span className="ui-sub2 ui-phone">
            {[
              ivt(language, invoice.category),
              draft || invoice.due_date === null
                ? ivt(language, "ni_due_later")
                : dayText(invoice.due_date),
              usdFromCents(cents(invoice.adjusted_total)),
            ].join(" · ")}
          </span>
        </td>
        <td>
          {data.names.get(invoice.customer_id) ?? (
            <span className="ui-muted">
              {ivt(language, "unknown_customer")}
            </span>
          )}
          <span className="ui-sub2">{unitOf(data, invoice)}</span>
        </td>
        <td className="ui-wide">{ivt(language, invoice.category)}</td>
        <td className={draft ? "ui-wide ui-muted" : "ui-wide ui-num"}>
          {draft || invoice.due_date === null
            ? ivt(language, "ni_due_later")
            : dayText(invoice.due_date)}
        </td>
        <td className="r ui-num ui-wide">
          {usdFromCents(cents(invoice.adjusted_total))}
        </td>
        <td className="r ui-num ui-wide">
          {draft || state === "void" ? (
            <span className="ui-muted">—</span>
          ) : (
            usdFromCents(Math.max(0, cents(invoice.outstanding_balance)))
          )}
        </td>
        <td>
          <InvoiceChip language={language} state={state} />
          {!draft && state !== "void" && state !== "paid" && (
            <span className="ui-sub2 ui-phone ui-num">
              {usdFromCents(Math.max(0, cents(invoice.outstanding_balance)))}
            </span>
          )}
        </td>
      </tr>
    );
  };

  return (
    <>
      <div className="ui-head">
        <p>
          {month === null
            ? ivt(language, "inv_sub")
            : ivt(language, "inv_sub_m", monthText(language, month))}
        </p>
        {canCreate && (
          <div className="ui-actions">
            <a className="ui-btn primary" href={hashForPage("invoices", "new")}>
              <Icon name="plus" />
              {ivt(language, "ni_btn")}
            </a>
          </div>
        )}
      </div>
      <div className="ui-filters">
        <div
          aria-label={ivt(language, "pm_period")}
          className="ui-seg"
          role="group"
        >
          {(
            [
              ["all", "f_all"],
              ["month", "pc_month"],
              ["last", "pc_last"],
              ["pick", "pm_pick"],
            ] as const
          ).map(([value, key]) => (
            <button
              aria-pressed={period === value}
              key={value}
              onClick={() => {
                setPeriod(value);
              }}
              type="button"
            >
              {ivt(language, key)}
            </button>
          ))}
        </div>
        {period === "pick" && (
          <>
            <label className="ui-sr" htmlFor="inv-month">
              {ivt(language, "pm_period")}
            </label>
            <select
              className="ui-sel"
              id="inv-month"
              onChange={(event) => {
                setPicked(event.currentTarget.value);
              }}
              value={picked}
            >
              {months.map((value) => (
                <option key={value} value={value}>
                  {monthText(language, value)}
                </option>
              ))}
            </select>
          </>
        )}
        <label className="ui-sr" htmlFor="inv-type">
          {ivt(language, "col_type")}
        </label>
        <select
          className="ui-sel"
          id="inv-type"
          onChange={(event) => {
            setType(event.currentTarget.value as InvoiceCategory | "all");
          }}
          value={type}
        >
          {TYPES.map((value) => (
            <option key={value} value={value}>
              {ivt(language, value === "all" ? "type_all" : value)}
            </option>
          ))}
        </select>
        {who !== null && (
          <>
            <Chip tone="info">{ivt(language, "for_who", who)}</Chip>
            <button
              className="ui-btn link"
              onClick={onClearCustomer}
              type="button"
            >
              {ivt(language, "clear_filter")}
            </button>
          </>
        )}
      </div>
      <div className="ui-kpis">
        {CARDS.map(([value, icon, tone, key]) => {
          const amount = amounts.get(value) ?? 0;
          const count = issued.filter((invoice) =>
            inCard(invoice, value, today),
          ).length;
          return (
            <CountCard
              icon={icon}
              key={value}
              label={ivt(language, key)}
              note={`${ivt(language, `${key}_s` as InvoicesTextKey)}\n${countText(language, count)}`}
              onPress={() => {
                setCard(card === value && value !== "all" ? "all" : value);
              }}
              pressed={card === value}
              tone={amount === 0 && value !== "all" ? "none" : tone}
              value={amount}
              valueText={usdFromCents(amount)}
            />
          );
        })}
      </div>
      <p className="ui-addup">
        <Icon name="check" small />
        <span>{addUp}</span>
      </p>
      <div className="ui-card pad0">
        {card !== "all" && (
          <div className="ui-listbar">
            {ivt(
              language,
              "ic_showing",
              ivt(
                language,
                CARDS.find(([value]) => value === card)?.[3] ?? "ic_total",
              ),
            )}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {ivt(language, "pc_clear")}
            </button>
          </div>
        )}
        {rows.length + shownDrafts.length === 0 ? (
          <p className="ui-empty">{ivt(language, "none_found")}</p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table ui-invlist">
                <thead>
                  <tr>
                    <th scope="col">{ivt(language, "col_no")}</th>
                    <th scope="col">{ivt(language, "col_cust")}</th>
                    <th className="ui-wide" scope="col">
                      {ivt(language, "col_type")}
                    </th>
                    <th className="ui-wide" scope="col">
                      {ivt(language, "col_due")}
                    </th>
                    <th className="r ui-wide" scope="col">
                      {ivt(language, "col_amount")}
                    </th>
                    <th className="r ui-wide" scope="col">
                      {ivt(language, "col_balance")}
                    </th>
                    <th scope="col">{ivt(language, "col_status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shownDrafts.map(row)}
                  {rows.map(row)}
                </tbody>
              </table>
            </div>
            <div className="ui-tfoot">
              {[
                countText(language, rows.length - voids),
                voids > 0 ? ivt(language, "ic_voids", voids) : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
          </>
        )}
      </div>
    </>
  );
}
