// V1-058 R3 Move-out M4: what the Inspection and charges step reads. A finding charges nothing
// by itself (BR-MOVEOUT-006); a Damage charge is recorded once per finding and the cleaning
// charge once per Lease (BR-MOVEOUT-013). Each is a one-time charge source with a Draft Invoice
// made from it. The page gives a Damage charge its finding's id and the cleaning charge the
// Lease's id, so it finds each charge again on the Invoice line that bills it.

import type { InvoiceResource } from "../invoiceClient";
import type { MoveOutInspection } from "./moveoutClient";

/** The text the server gives every Unit cleaning charge line. */
export const CLEANING_DESCRIPTION = "Unit cleaning charge";

/** The inspections still in force: those no later inspection replaced (normally one). */
export function currentInspections(
  items: MoveOutInspection[],
): MoveOutInspection[] {
  const replaced = new Set(
    items.flatMap((item) =>
      item.supersedes_inspection_id === null
        ? []
        : [item.supersedes_inspection_id],
    ),
  );
  return items.filter(
    (item) => item.current_effect !== "SUPERSEDED" && !replaced.has(item.id),
  );
}

/** The newest inspection still in force. */
export function currentInspection(
  items: MoveOutInspection[],
): MoveOutInspection | null {
  return currentInspections(items).at(-1) ?? null;
}

/** The one-time charge source an Invoice line bills, when it bills one. */
export function sourceOf(
  line: InvoiceResource["lines"][number],
): string | null {
  return line.source.type === "AUTHORIZED_NONRECURRING_OBLIGATION" &&
    typeof line.source.id === "string"
    ? line.source.id
    : null;
}

/** Not VOID first: a VOID Invoice stands for its charge only when no other bills it. */
const liveFirst = (invoices: InvoiceResource[]) => [
  ...invoices.filter((invoice) => invoice.status !== "VOID"),
  ...invoices.filter((invoice) => invoice.status === "VOID"),
];

/**
 * The Invoice billing each one-time charge source. A charge whose Invoice was voided keeps it:
 * its source is recorded, so billing it again is a choice made on the Invoices page.
 */
export function billedSources(
  invoices: InvoiceResource[],
): Map<string, InvoiceResource> {
  const found = new Map<string, InvoiceResource>();
  for (const invoice of liveFirst(invoices)) {
    for (const line of invoice.lines) {
      const source = sourceOf(line);
      if (source !== null && !found.has(source)) found.set(source, invoice);
    }
  }
  return found;
}

/** The Invoice of the Lease's cleaning charge, recorded here or elsewhere (VOID last). */
export function cleaningInvoice(
  invoices: InvoiceResource[],
  leaseId: string,
): InvoiceResource | null {
  return (
    liveFirst(invoices).find(
      (invoice) =>
        invoice.category === "MISCELLANEOUS_CHARGES" &&
        invoice.lines.some(
          (line) =>
            sourceOf(line) === leaseId ||
            line.description === CLEANING_DESCRIPTION,
        ),
    ) ?? null
  );
}

/** One line of text: an Invoice line description cannot hold a line break. */
export function oneLine(text: string, max: number): string {
  return text.replace(/\s+/g, " ").trim().slice(0, max).trim();
}
