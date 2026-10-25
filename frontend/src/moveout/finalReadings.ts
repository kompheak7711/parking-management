// V1-058 R3 Move-out M3: what the final readings step reads. The final inputs name one Reading
// per Meter on the hand-back day (BR-UTIL-021); the final Utility Invoice is found among the
// Lease's Utility Invoices by the billing kind its lines keep.

import type { InvoiceResource } from "../invoiceClient";
import { parseReading } from "../utilities/utilitiesData";
import type { UtilityMeter } from "../utilityClient";
import type { EvidenceRecord } from "../utilityLeaseClient";

export interface FinalInputItem {
  meter_id: string;
  utility_type: string;
  resolution: string;
  reading_id: string | null;
  reading_value: string | null;
}

export interface FinalInputs {
  event_id: string;
  move_out_event_id: string;
  actual_move_out_date: string;
  occurred_at: string;
  unresolved: number;
  items: FinalInputItem[];
}

const text = (value: unknown): string | null =>
  typeof value === "string" ? value : null;

/** The current final inputs of the current hand-back, or null when none is recorded. */
export function currentFinalInputs(
  page: EvidenceRecord,
  moveOutEventId: string,
): FinalInputs | null {
  const items = Array.isArray(page.items) ? (page.items as unknown[]) : [];
  for (const value of items) {
    if (typeof value !== "object" || value === null) continue;
    const row = value as EvidenceRecord;
    if (
      row.event_status !== "CURRENT" ||
      row.physical_event_status !== "CURRENT" ||
      row.move_out_event_id !== moveOutEventId
    )
      continue;
    const event = text(row.event_id);
    const day = text(row.actual_move_out_date);
    const at = text(row.occurred_at);
    if (event === null || day === null || at === null) continue;
    const lines = Array.isArray(row.items) ? (row.items as unknown[]) : [];
    return {
      event_id: event,
      move_out_event_id: moveOutEventId,
      actual_move_out_date: day,
      occurred_at: at,
      unresolved:
        typeof row.unresolved_item_count === "number"
          ? row.unresolved_item_count
          : 0,
      items: lines.flatMap((line) => {
        if (typeof line !== "object" || line === null) return [];
        const item = line as EvidenceRecord;
        const reading =
          typeof item.reading === "object" && item.reading !== null
            ? (item.reading as EvidenceRecord)
            : null;
        const meter = text(item.meter_id);
        if (meter === null) return [];
        return [
          {
            meter_id: meter,
            utility_type: text(item.utility_type) ?? "",
            resolution: text(item.resolution) ?? "",
            reading_id: reading === null ? null : text(reading.reading_id),
            reading_value:
              reading === null ? null : text(reading.reading_value),
          },
        ];
      }),
    };
  }
  return null;
}

/** The newest final inputs of the Lease still in force, whatever hand-back they name. */
export function latestInputsId(page: EvidenceRecord): string | null {
  const items = Array.isArray(page.items) ? (page.items as unknown[]) : [];
  for (const value of items) {
    if (typeof value !== "object" || value === null) continue;
    const row = value as EvidenceRecord;
    if (row.event_status === "CURRENT" && typeof row.event_id === "string")
      return row.event_id;
  }
  return null;
}

/**
 * The final Utility Invoice of these final inputs: a FINAL line whose period ends at one of their
 * readings. Only when no line can be tied that way (every period was billed before) does an
 * Invoice issued on or after the day the inputs were saved count.
 */
export function finalInvoiceOf(
  invoices: InvoiceResource[],
  inputs: FinalInputs,
): InvoiceResource | null {
  const readings = new Set(
    inputs.items.flatMap((item) =>
      item.reading_id === null ? [] : [item.reading_id],
    ),
  );
  const finals = invoices.filter(
    (invoice) =>
      invoice.status !== "VOID" &&
      invoice.lines.some(
        (line) => line.calculation_evidence.billing_kind === "FINAL",
      ),
  );
  const tied = finals.find((invoice) =>
    invoice.lines.some((line) => {
      const end = line.calculation_evidence.end_reading_id;
      return typeof end === "string" && readings.has(end);
    }),
  );
  if (tied !== undefined) return tied;
  const since = inputs.occurred_at.slice(0, 10);
  return (
    finals.find(
      (invoice) =>
        invoice.invoice_date >= since &&
        !invoice.lines.some(
          (line) =>
            typeof line.calculation_evidence.end_reading_id === "string",
        ),
    ) ?? null
  );
}

/** The Meters the hand-back day needs a reading from: installed by then and not yet taken out. */
export function metersOn(meters: UtilityMeter[], day: string): UtilityMeter[] {
  return meters
    .filter(
      (meter) =>
        meter.installed_date <= day &&
        (meter.deactivated_date === null || meter.deactivated_date >= day),
    )
    .sort((left, right) =>
      left.utility_type === right.utility_type
        ? left.serial_number.localeCompare(right.serial_number)
        : left.utility_type === "ELECTRICITY"
          ? -1
          : 1,
    );
}

/** A whole-number reading not lower than the last one. */
export function readingProblem(value: string, last: string | null): boolean {
  const typed = parseReading(value);
  return typed === null || (last !== null && typed < Number(last));
}
