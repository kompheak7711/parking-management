import {
  exactKeys,
  financialCalendarDate,
  financialId,
  financialInstant,
  financialInteger,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";

export type DueSourcesPurpose = "allocation" | "credit_application";
export interface FinancialDueSourcesInput {
  operation: "financialDueSources";
  purpose: DueSourcesPurpose;
  source_id: string;
  invoice_id: string;
  invoice_line_id: string;
  limit?: number;
  cursor?: string;
}
const maximum = 9_223_372_036_854_775_807n;
const revisionPattern = /^[0-9a-f]{64}$/;
function canonicalId(value: unknown): string {
  const id = financialId(value);
  if (id.length !== 36 || id !== value) invalidFinancial();
  return id;
}
function kind(value: unknown): "ORIGINAL_LINE" | "DEBIT_ADJUSTMENT" {
  if (value !== "ORIGINAL_LINE" && value !== "DEBIT_ADJUSTMENT")
    return invalidFinancial();
  return value;
}
function revision(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length !== 64 ||
    !revisionPattern.test(value)
  )
    return invalidFinancial();
  return value;
}
function instant(value: unknown): bigint {
  if (typeof value !== "string" || value.length > 40) return invalidFinancial();
  const match =
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.exec(
      value,
    );
  if (!match || match[0] !== value) return invalidFinancial();
  return financialInstant(value);
}
export function dueSourcesCursor(value: unknown): {
  revision: string;
  kind: "ORIGINAL_LINE" | "DEBIT_ADJUSTMENT";
  id: string;
} {
  if (typeof value !== "string" || value.length > 120)
    return invalidFinancial();
  const fields = value.split(":");
  if (fields.length !== 3) return invalidFinancial();
  return {
    revision: revision(fields[0]),
    kind: kind(fields[1]),
    id: canonicalId(fields[2]),
  };
}

/** Capture a detached finite read; this is not a command or authorization receipt. */
export function captureDueSources(value: unknown): FinancialObject {
  const row = financialObject(
    parseFinancialJson(stringifyFinancialJson(value, 32_768), 32_768),
  );
  exactKeys(
    row,
    ["operation", "purpose", "source_id", "invoice_id", "invoice_line_id"],
    ["limit", "cursor"],
  );
  if (
    row.operation !== "financialDueSources" ||
    (row.purpose !== "allocation" && row.purpose !== "credit_application")
  )
    invalidFinancial();
  for (const key of ["source_id", "invoice_id", "invoice_line_id"])
    row[key] = canonicalId(financialId(row[key]));
  if (row.limit !== undefined) financialInteger(row.limit, 1n, 100n);
  if (row.cursor !== undefined) dueSourcesCursor(row.cursor);
  return row;
}
export function dueSourcesQuery(value: unknown): URLSearchParams {
  const row = captureDueSources(value),
    query = new URLSearchParams();
  query.set("purpose", row.purpose as DueSourcesPurpose);
  for (const key of ["source_id", "invoice_id", "invoice_line_id"])
    query.set(key, canonicalId(row[key]));
  if (row.limit !== undefined)
    query.set("limit", financialInteger(row.limit, 1n, 100n).toString());
  if (row.cursor !== undefined) {
    dueSourcesCursor(row.cursor);
    query.set("cursor", row.cursor as string);
  }
  return query;
}
type SourceOrder = readonly [string, bigint, string, string];
function ordered(before: SourceOrder, after: SourceOrder): boolean {
  for (let index = 0; index < 4; index++) {
    const left = before[index] ?? invalidFinancial(),
      right = after[index] ?? invalidFinancial();
    if (left !== right) return left < right;
  }
  return false;
}

/** Validate server facts without calculating an allocation or inventing missing history. */
export function validateDueSourcesPage(
  value: unknown,
  pagination: unknown,
  captured: unknown,
  propertyId: string,
): {
  data: FinancialObject;
  page: { limit: number; nextCursor: string | null };
} {
  const input = captureDueSources(captured);
  const data = financialObject(
    parseFinancialJson(stringifyFinancialJson(value, 100_000), 100_000),
  );
  const page = financialObject(
    parseFinancialJson(stringifyFinancialJson(pagination, 1024), 1024),
  );
  exactKeys(data, [
    "property_id",
    "purpose",
    "source_id",
    "invoice_id",
    "invoice_line_id",
    "invoice_version",
    "revision",
    "as_of",
    "aggregate_outstanding_usd_cents",
    "item_count",
    "items",
  ]);
  exactKeys(page, ["limit", "next_cursor"]);
  if (
    canonicalId(data.property_id) !== financialId(propertyId) ||
    data.purpose !== input.purpose
  )
    invalidFinancial();
  for (const key of ["source_id", "invoice_id", "invoice_line_id"])
    if (canonicalId(data[key]) !== input[key]) invalidFinancial();
  financialInteger(data.invoice_version, 1n, 9_999_999_999n);
  const current = revision(data.revision),
    at = instant(data.as_of);
  const anchor =
    input.cursor === undefined ? null : dueSourcesCursor(input.cursor);
  if (anchor !== null && anchor.revision !== current) invalidFinancial();
  const limit = Number(financialInteger(input.limit ?? 50, 1n, 100n));
  if (page.limit !== limit) invalidFinancial();
  const aggregate = BigInt(
    financialInteger(data.aggregate_outstanding_usd_cents, 0n, maximum),
  );
  const count = BigInt(financialInteger(data.item_count, 0n, maximum));
  if (!Array.isArray(data.items) || data.items.length > limit)
    return invalidFinancial();
  const length = BigInt(data.items.length),
    more = page.next_cursor !== null;
  if (more) dueSourcesCursor(page.next_cursor);
  if (
    length > count ||
    (count === 0n) !== (aggregate === 0n) ||
    count > aggregate ||
    (anchor === null &&
      (length !== (count < BigInt(limit) ? count : BigInt(limit)) ||
        more !== count > BigInt(limit))) ||
    (anchor !== null && (count < 1n || length >= count)) ||
    (more && (length !== BigInt(limit) || count <= length + (anchor ? 1n : 0n)))
  )
    invalidFinancial();
  const seen = new Set<string>();
  let previous: SourceOrder | null = null,
    total = 0n,
    last: string | null = null;
  for (const value of data.items) {
    const item = financialObject(value);
    exactKeys(item, [
      "source_kind",
      "source_id",
      "approved_due_date",
      "source_occurred_at",
      "remaining_usd_cents",
    ]);
    const sourceKind = kind(item.source_kind),
      id = canonicalId(item.source_id),
      pair = `${sourceKind}:${id}`;
    if (
      seen.has(pair) ||
      (anchor !== null && sourceKind === anchor.kind && id === anchor.id) ||
      (sourceKind === "ORIGINAL_LINE" && id !== input.invoice_line_id)
    )
      invalidFinancial();
    seen.add(pair);
    const occurred = instant(item.source_occurred_at),
      date = financialCalendarDate(item.approved_due_date);
    if (date.length !== 10 || occurred > at) invalidFinancial();
    const order: SourceOrder = [date, occurred, sourceKind, id];
    if (previous !== null && !ordered(previous, order)) invalidFinancial();
    previous = order;
    total += BigInt(financialInteger(item.remaining_usd_cents, 1n, maximum));
    last = pair;
  }
  if (total > aggregate || (anchor === null && !more && total !== aggregate))
    invalidFinancial();
  const next = page.next_cursor;
  if (more && (last === null || next !== `${current}:${last}`))
    invalidFinancial();
  return {
    data,
    page: { limit, nextCursor: next === null ? null : (next as string) },
  };
}
