// V1-058 R5c-3: the printed Receipt (DESIGN.md "Printed documents"; the approved template
// brand-kit/05_Templates/receipt-template.html). It is A5, Khmer above English in every language
// of the app, dates dd/mm/yyyy and 24-hour times. What the money paid is listed line by line: an
// Invoice first and its late-payment charge right after it, then Deposits, Credit, refunds and
// money not used yet (owner, 17/10/2026).

import "../invoices/invoiceDocument.css";
import "./receiptDocument.css";

import logoUrl from "../assets/brand/CHETANA_Logo_Horizontal_FullColor.svg";
import { momentText, usdFromCents } from "../shell/format";
import type { ReceiptLine, ReceiptView } from "./paymentsClient";
import { rielText } from "./PaymentsList";

function Label({ kh, en }: { kh: string; en: string }) {
  return (
    <span className="lbl">
      <span className="kh" lang="km">
        {kh}
      </span>
      <span className="en">{en}</span>
    </span>
  );
}

const CATEGORY: Record<string, [string, string]> = {
  RENT: ["ថ្លៃឈ្នួល", "Rent"],
  UTILITIES: ["ថ្លៃទឹកភ្លើង", "Utilities"],
  SERVICE_CHARGES: ["ថ្លៃសេវា", "Services"],
  MISCELLANEOUS_CHARGES: ["ថ្លៃផ្សេងៗ", "Miscellaneous"],
  DAMAGE_CHARGES: ["ថ្លៃខូចខាត", "Damage"],
};

/** The Khmer and English names of a line and its detail. */
export function lineWords(line: ReceiptLine): [string, string, string] {
  switch (line.kind) {
    case "INVOICE": {
      const [kh, en] = CATEGORY[line.category ?? ""] ?? [
        "វិក្កយបត្រ",
        "Invoice",
      ];
      return [kh, en, line.invoiceNumber ?? ""];
    }
    case "LATE_PAYMENT_CHARGE":
      return [
        "ថ្លៃពិន័យបង់យឺត",
        "Late-payment charge",
        `on ${line.invoiceNumber ?? ""}`,
      ];
    case "DEPOSIT":
      return [
        "ប្រាក់កក់",
        "Deposit",
        line.depositType === "PET" ? "Pet Deposit" : "Security Deposit",
      ];
    case "CREDIT":
      return ["ឥណទានអតិថិជន", "Customer Credit", "Kept as Credit"];
    case "REFUND":
      return ["ប្រាក់សងវិញ", "Refunded", "Given back to the payer"];
  }
}

export function ReceiptDocument({
  receipt,
  name,
  unit,
  reprint,
}: {
  receipt: ReceiptView;
  name: string | null;
  unit: string;
  /** The day of the reprint this copy is for, or null for the first print. */
  reprint: string | null;
}) {
  const number = receipt.receiptNumber ?? "—";
  const lines: [string, string, string, number][] = receipt.lines.map(
    (line) => [...lineWords(line), line.amount],
  );
  if (receipt.left > 0)
    lines.push([
      "ប្រាក់មិនទាន់ប្រើ",
      "Not used yet",
      "Credit or refund, as the Customer chooses",
      receipt.left,
    ]);
  const invoices = [
    ...new Set(
      receipt.lines.flatMap((line) =>
        line.kind === "INVOICE" && line.invoiceNumber !== null
          ? [line.invoiceNumber]
          : [],
      ),
    ),
  ];
  const note =
    receipt.payerNote ?? (invoices.length > 0 ? invoices.join(", ") : "—");
  const reference =
    receipt.reference === null
      ? "None"
      : receipt.methodCode === "ABA"
        ? `ABA transaction ${receipt.reference}`
        : receipt.reference;
  return (
    <article className="doc a5" lang="en">
      {receipt.status === "REVERSED" && (
        <div aria-hidden="true" className="stamp">
          REVERSED · ត្រឡប់វិញ
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
          <span className="kh" lang="km">
            បង្កាន់ដៃទទួលប្រាក់
          </span>
          <span className="en">Receipt</span>
          <dl className="meta">
            <Label en="Receipt No." kh="លេខបង្កាន់ដៃ" />
            <dd>{number}</dd>
            <Label en="Received on" kh="កាលបរិច្ឆេទទទួល" />
            <dd>{momentText(receipt.receivedAt).replace(" ", ", ")}</dd>
          </dl>
          {reprint !== null && (
            <span className="reprint">
              REPRINT ·{" "}
              <span className="kh" lang="km">
                ច្បាប់ចម្លង
              </span>{" "}
              · {reprint}
            </span>
          )}
        </div>
      </div>
      <hr />
      <div className="parties">
        <div>
          <Label en="Received from" kh="ទទួលពី" />
          <div className="v">
            {name ?? "—"}
            {unit !== "" && <small>Unit {unit}</small>}
          </div>
        </div>
        <div>
          <Label en="Payer note" kh="សម្រាប់" />
          <div className="v">{note}</div>
        </div>
      </div>
      <div className="amount">
        <Label en="Amount received" kh="ចំនួនទឹកប្រាក់ដែលបានទទួល" />
        <div>
          <div className="n">{usdFromCents(receipt.usdCents)}</div>
          {receipt.currency === "KHR" && (
            <div className="khr">
              Received <b>{rielText(receipt.receivedMinor)}</b>
              {receipt.rate !== null && (
                <>
                  <br />
                  Rate {Number(receipt.rate).toLocaleString("en-US")} ៛ = $1.00
                </>
              )}
            </div>
          )}
        </div>
      </div>
      <table className={lines.length > 4 ? "paidfor many" : "paidfor"}>
        <thead>
          <tr>
            <th>
              <Label en="Paid for" kh="បង់សម្រាប់" />
            </th>
            <th className="r">
              <Label en="Amount (USD)" kh="ចំនួនទឹកប្រាក់" />
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map(([kh, en, detail, amount], index) => (
            <tr key={index}>
              <td>
                <div className="cat">
                  <span className="kh" lang="km">
                    {kh}
                  </span>
                  {en}
                </div>
                {detail !== "" && <div className="det">{detail}</div>}
              </td>
              <td className="r">{usdFromCents(amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="rows">
        <Label en="Payment method" kh="វិធីបង់ប្រាក់" />
        <dd>{receipt.methodName}</dd>
        <Label en="Reference" kh="លេខយោង" />
        <dd>{reference}</dd>
        <Label en="Received by" kh="អ្នកទទួល" />
        <dd>
          {receipt.receivedBy ?? "—"} <small>(Staff)</small>
        </dd>
      </dl>
      <div className="push" />
      <div className="sign">
        <div>
          <span className="kh" lang="km">
            ហត្ថលេខាអ្នកទទួល
          </span>
          <br />
          Received by
        </div>
        <div>
          <span className="kh" lang="km">
            ហត្ថលេខាអ្នកបង់
          </span>
          <br />
          Paid by
        </div>
      </div>
      <div className="foot">
        <span>{number}</span>
        <span className="tag">Live with intention.</span>
      </div>
    </article>
  );
}
