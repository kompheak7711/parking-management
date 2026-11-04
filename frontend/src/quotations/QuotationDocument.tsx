// V1.1 part 6 (DL-123): the printed Quotation, the same A4 layout as the Invoice (DESIGN.md
// round 16): Khmer above English, the number, the day it was made and the day it is valid
// until, each line with its quantity and price (a lowered price shows the list price under it),
// the total, the due-days sentence, and the Customer and CHETANA signature lines.

import "../invoices/invoiceDocument.css";
import "./quotationDocument.css";

import logoUrl from "../assets/brand/CHETANA_Logo_Horizontal_FullColor.svg";
import { dayText, usdFromCents } from "../shell/format";
import type { Quotation } from "./quotationsClient";

function Label({ kh, en }: { kh: string; en: string }) {
  return (
    <span className="lbl">
      <span className="kh">{kh}</span>
      <span className="en">{en}</span>
    </span>
  );
}

export function QuotationDocument({ quotation }: { quotation: Quotation }) {
  const closed =
    quotation.state === "REPLACED" ||
    quotation.state === "REFUSED" ||
    quotation.state === "EXPIRED";
  return (
    <article className="doc a4 qdoc" lang="en">
      {closed && (
        <div aria-hidden="true" className="stamp">
          {quotation.state === "REPLACED"
            ? "REPLACED · ត្រូវបានជំនួស"
            : quotation.state === "REFUSED"
              ? "DECLINED · បដិសេធ"
              : "EXPIRED · ផុតកំណត់"}
        </div>
      )}
      <div className="top">
        <div>
          <img alt="CHETANA" className="logo" src={logoUrl} />
          <div className="biz">
            <b>CHETANA Residence</b>
          </div>
        </div>
        <div className="title">
          <span className="kh">សម្រង់តម្លៃ</span>
          <span className="en">Quotation</span>
          <dl className="meta">
            <Label en="Quotation No." kh="លេខសម្រង់តម្លៃ" />
            <dd>{quotation.quotation_number}</dd>
            <Label en="Date" kh="កាលបរិច្ឆេទ" />
            <dd>{dayText(quotation.made_on)}</dd>
            <Label en="Valid until" kh="មានសុពលភាពដល់" />
            <dd>{dayText(quotation.valid_until)}</dd>
          </dl>
        </div>
      </div>
      <hr />
      <div className="parties">
        <div>
          <div className="v">
            {quotation.customer_name}
            {quotation.customer_phone !== null && (
              <small>Phone {quotation.customer_phone}</small>
            )}
          </div>
        </div>
        <div>
          <div className="v">
            {quotation.unit_number !== null
              ? `Unit ${quotation.unit_number}`
              : ""}
            {quotation.note !== null && <small>{quotation.note}</small>}
          </div>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>
              <Label en="Description" kh="ការពិពណ៌នា" />
            </th>
            <th className="q">
              <Label en="Qty" kh="ចំនួន" />
            </th>
            <th className="q">
              <Label en="Price" kh="តម្លៃ" />
            </th>
            <th className="r">
              <Label en="Amount (USD)" kh="ចំនួនទឹកប្រាក់" />
            </th>
          </tr>
        </thead>
        <tbody>
          {quotation.lines.map((line) => (
            <tr key={line.position}>
              <td>
                <div className="cat">
                  {line.name_kh !== null && (
                    <span className="kh">{line.name_kh}</span>
                  )}
                  {line.name_en}
                </div>
                {line.price_usd_cents < line.list_price_usd_cents && (
                  <div className="det">
                    List price {usdFromCents(line.list_price_usd_cents)}
                  </div>
                )}
              </td>
              <td className="q">{line.quantity}</td>
              <td className="q">{usdFromCents(line.price_usd_cents)}</td>
              <td className="r">{usdFromCents(line.amount_usd_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="sum">
        <Label en="Total" kh="សរុប" />
        <span className="n">{usdFromCents(quotation.total_usd_cents)}</span>
      </div>
      {quotation.replaces_number !== null && (
        <p className="note">
          This Quotation replaces {quotation.replaces_number}.
        </p>
      )}
      <p className="note">
        <span className="kh">
          ពេលអតិថិជនចុះហត្ថលេខា វិក្កយបត្រនឹងត្រូវចេញ ហើយត្រូវបង់ក្នុង{" "}
          {quotation.due_days} ថ្ងៃ។
        </span>
        When the Customer signs, the Invoice is issued, due in{" "}
        {quotation.due_days} days.
      </p>
      <div className="push" />
      <div className="signs">
        <div>
          <span className="kh" lang="km">
            ហត្ថលេខាអតិថិជន
          </span>
          <br />
          Customer signature · Date
        </div>
        <div>
          <span className="kh" lang="km">
            សម្រាប់ CHETANA
          </span>
          <br />
          For CHETANA
          {quotation.created_by_name !== null &&
            ` · ${quotation.created_by_name}`}
        </div>
      </div>
      <div className="foot">
        <span>{quotation.quotation_number} · Page 1 of 1</span>
        <span className="tag">Live with intention.</span>
      </div>
    </article>
  );
}
