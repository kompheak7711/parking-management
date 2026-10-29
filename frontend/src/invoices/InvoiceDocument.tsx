// V1-058 R5: the printed Invoice (DESIGN.md "Printed documents"; the approved template
// brand-kit/05_Templates/invoice-template.html). It is A4, Khmer above English in every
// language of the app, dates dd/mm/yyyy, and the ABA KHQR code at the bottom. The Invoice page
// shows it at once, scaled to its column; Print Invoice prints only this sheet.

import "./invoiceDocument.css";

import { type ReactNode, useEffect, useRef } from "react";

import qrUrl from "../../assets/brand/ABA_KHQR_CHETANA_APARTMENT.png";
import logoUrl from "../assets/brand/CHETANA_Logo_Horizontal_FullColor.svg";
import type { InvoiceLine, InvoiceResource, JsonValue } from "../invoiceClient";
import { dayText, usdFromCents } from "../shell/format";
import { cents, paidOf } from "./invoicesData";

function textOf(value: JsonValue | undefined): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function numberOf(value: JsonValue | undefined): number | null {
  const number =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim() !== ""
        ? Number(value)
        : NaN;
  return Number.isFinite(number) ? number : null;
}

/** "01/11/2026 - 30/11/2026", the way the template writes a period. */
function periodOf(period: JsonValue | undefined): string | null {
  if (typeof period !== "object" || period === null || Array.isArray(period))
    return null;
  const start = textOf(period.start);
  const end = textOf(period.end);
  return start === null || end === null
    ? null
    : `${dayText(start)} - ${dayText(end)}`;
}

/** The Khmer name printed before each line, by what the line bills. */
function khmerOf(line: InvoiceLine): string {
  const type = textOf(line.calculation_evidence.utility_type);
  if (line.category === "UTILITIES")
    return type === "WATER"
      ? "ថ្លៃទឹក"
      : type === "ELECTRICITY"
        ? "ថ្លៃភ្លើង"
        : "ថ្លៃទឹកភ្លើង";
  return {
    RENT: "ថ្លៃឈ្នួល",
    SERVICE_CHARGES: "ថ្លៃសេវា",
    MISCELLANEOUS_CHARGES: "ថ្លៃផ្សេងៗ",
    DAMAGE_CHARGES: "ថ្លៃខូចខាត",
  }[line.category];
}

/** A Utility line's "240 kWh × $0.25", from what the app recorded when it billed the line. */
function utilityDetail(line: InvoiceLine): string | null {
  if (line.category !== "UTILITIES") return null;
  const evidence = line.calculation_evidence;
  const quantity = numberOf(evidence.consumption_quantity);
  const rate = numberOf(evidence.rate_usd_per_unit);
  if (quantity === null || rate === null) return null;
  const unit = textOf(evidence.utility_type) === "WATER" ? "m³" : "kWh";
  // The rate can have more than two decimals, so it is written as the server sent it.
  return `${quantity.toLocaleString("en-US")} ${unit} × $${String(rate)}`;
}

/** A typed item's "2 × $15.00" (DL-103): its whole quantity and its unit price. */
function itemDetail(line: InvoiceLine): string | null {
  if (line.category !== "MISCELLANEOUS_CHARGES") return null;
  const quantity = numberOf(line.calculation_evidence.quantity);
  const price = numberOf(line.calculation_evidence.unit_price_usd_cents);
  if (
    quantity === null ||
    price === null ||
    !Number.isSafeInteger(quantity) ||
    !Number.isSafeInteger(price)
  )
    return null;
  return `${quantity.toLocaleString("en-US")} × ${usdFromCents(price)}`;
}

/** The Initial Rent Invoice: its Rent line was billed as INITIAL when the Lease was signed. */
function initialRent(invoice: InvoiceResource): boolean {
  return invoice.lines.some(
    (line) =>
      line.category === "RENT" &&
      textOf(line.calculation_evidence.billing_kind) === "INITIAL",
  );
}

function Label({ kh, en }: { kh: string; en: string }) {
  return (
    <span className="lbl">
      <span className="kh">{kh}</span>
      <span className="en">{en}</span>
    </span>
  );
}

export function InvoiceDocument({
  invoice,
  name,
  phone,
  unit,
}: {
  invoice: InvoiceResource;
  name: string | null;
  phone: string | null;
  unit: string;
}) {
  const draft = invoice.status === "DRAFT";
  const voided = invoice.status === "VOID";
  const number = draft ? "—" : invoice.invoice_number;
  const paid = paidOf(invoice);
  const owed = voided ? 0 : Math.max(0, cents(invoice.outstanding_balance));
  const lines = [...invoice.lines].sort(
    (left, right) => left.sequence - right.sequence,
  );
  const period =
    periodOf(invoice.billing_period) ??
    lines.map((line) => periodOf(line.period)).find(Boolean) ??
    null;
  return (
    <article className="doc a4" lang="en">
      {(draft || voided) && (
        <div aria-hidden="true" className="stamp">
          {draft ? "DRAFT · សេចក្តីព្រាង" : "VOID · ទុកជាមោឃៈ"}
        </div>
      )}
      <div className="top">
        <div>
          <img alt="CHETANA" className="logo" src={logoUrl} />
          <div className="biz">
            <b>CHETANA Parking</b>
          </div>
        </div>
        <div className="title">
          <span className="kh">វិក្កយបត្រ</span>
          <span className="en">Invoice</span>
          <dl className="meta">
            <Label en="Invoice No." kh="លេខវិក្កយបត្រ" />
            <dd>{number}</dd>
            <Label en="Invoice date" kh="កាលបរិច្ឆេទ" />
            <dd>{draft ? "—" : dayText(invoice.invoice_date)}</dd>
            <Label en="Due date" kh="ថ្ងៃកំណត់បង់" />
            <dd>
              {invoice.due_date === null ? "—" : dayText(invoice.due_date)}
            </dd>
          </dl>
        </div>
      </div>
      <hr />
      <div className="parties">
        <div>
          <div className="v">
            {name ?? "—"}
            {phone !== null && <small>Phone {phone}</small>}
          </div>
        </div>
        <div>
          <div className="v">
            {unit !== "" ? `Unit ${unit}` : ""}
            {period !== null && <small>{period}</small>}
          </div>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>
              <Label en="Description" kh="ការពិពណ៌នា" />
            </th>
            <th className="r">
              <Label en="Amount (USD)" kh="ចំនួនទឹកប្រាក់" />
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const detail = utilityDetail(line) ?? itemDetail(line);
            return (
              <tr key={line.id}>
                <td>
                  <div className="cat">
                    <span className="kh">{khmerOf(line)}</span>
                    {line.description}
                  </div>
                  {detail !== null && <div className="det">{detail}</div>}
                </td>
                <td className="r">
                  {usdFromCents(cents(line.adjusted_amount))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="sum">
        <Label en="Total" kh="សរុប" />
        <span className="n">{usdFromCents(cents(invoice.adjusted_total))}</span>
        {paid > 0 && (
          <>
            <Label en="Paid so far" kh="បានបង់រួច" />
            <span className="n">− {usdFromCents(paid)}</span>
          </>
        )}
        <div className="due">
          <Label en="Balance due" kh="សមតុល្យត្រូវបង់" />
          <span className="n">{usdFromCents(owed)}</span>
        </div>
      </div>
      {invoice.category === "RENT" && !initialRent(invoice) && (
        // The approved template's words; the rate is the Settings rate (10%, DL-076). The Initial
        // Rent Invoice never gets a late-payment charge (BR-RENT-009, BR-RENT-029), so no note.
        <p className="note">
          <span className="kh">
            ប្រសិនបើមិនបង់ទាន់ថ្ងៃកំណត់ អាចមានការគិតថ្លៃបង់យឺត ១០%
            នៃសមតុល្យមិនទាន់បង់។
          </span>
          If this Invoice is not paid by the Due Date, a late-payment charge of
          10% of the unpaid balance may be added.
        </p>
      )}
      <div className="push" />
      {!draft && !voided && owed > 0 && (
        <section className="pay">
          <img alt="ABA KHQR code for CHETANA APARTMENT" src={qrUrl} />
          <div>
            <p>
              <span className="kh">
                សូមបង់ប្រាក់តាមរយៈ ឃ្យូអកូដ នៅលើវិក្កយបត្រ។ បញ្ចូលទឹកប្រាក់{" "}
                <b>{usdFromCents(owed)}</b> និងសរសេរលេខ{" "}
                <span className="ref">{number}</span> នៅក្នុងកំណត់សម្គាល់។
              </span>
              Pay via QR Code on invoice. Enter <b>{usdFromCents(owed)}</b> and
              write <span className="ref">{number}</span> in the payment note.
            </p>
          </div>
        </section>
      )}
      <div className="foot">
        <span>{number} · Page 1 of 1</span>
        <span className="tag">Live with intention.</span>
      </div>
    </article>
  );
}

/**
 * The sheet at the width of its column, at most 1.6 times its size; printing shows it at its
 * real size.
 */
export function SheetFrame({ children }: { children: ReactNode }) {
  const frame = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const outer = frame.current;
    const inner = sheet.current;
    if (outer === null || inner === null) return;
    const fit = () => {
      inner.style.transform = "none";
      inner.style.marginBottom = "0";
      const width = inner.offsetWidth;
      const height = inner.offsetHeight;
      if (width === 0) return;
      const scale = Math.min(1.6, (outer.clientWidth - 4) / width);
      inner.style.transform = `scale(${String(scale)})`;
      inner.style.marginBottom = `${String(height * scale - height)}px`;
    };
    fit();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(fit);
    observer.observe(outer);
    return () => {
      observer.disconnect();
    };
  }, []);
  return (
    <figure className="ui-sheetwrap" ref={frame}>
      <div className="ui-sheet" ref={sheet}>
        {children}
      </div>
    </figure>
  );
}
