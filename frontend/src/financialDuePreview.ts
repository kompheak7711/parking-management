import {
  exactKeys,
  financialCalendarDate,
  financialId,
  financialInstant,
  financialInteger,
  financialObject,
  financialText,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import {
  ExactJsonNumber,
  parseFinancialJson,
  stringifyFinancialJson,
  type FinancialJson,
} from "./financialJson";

export type DuePreviewKind = "PAYMENT" | "CREDIT";
const maximum = 9_000_000_000_000_000n;
const amount = (v: unknown) => BigInt(financialInteger(v, 1n, maximum));
function rows(value: unknown, limit: number): FinancialObject[] {
  if (!Array.isArray(value) || !value.length || value.length > limit)
    return invalidFinancial();
  return value.map(financialObject);
}
function sameId(a: unknown, b: unknown): void {
  if (financialId(a) !== financialId(b)) invalidFinancial();
}
function unique(seen: Set<string>, id: string): void {
  if (seen.has(id)) invalidFinancial();
  seen.add(id);
}
function source(row: FinancialObject): string {
  if (
    row.source_kind !== "ORIGINAL_LINE" &&
    row.source_kind !== "DEBIT_ADJUSTMENT"
  )
    return invalidFinancial();
  return `${row.source_kind}:${financialId(row.source_id)}`;
}
function exactValues(value: FinancialJson, depth = 0): void {
  if (depth > 24) invalidFinancial();
  if (typeof value === "string") {
    if (value.includes("\0")) invalidFinancial();
  } else if (typeof value === "number" || typeof value === "bigint") {
    financialInteger(value, -maximum, maximum);
  } else if (Array.isArray(value)) {
    for (const child of value) exactValues(child, depth + 1);
  } else if (
    value !== null &&
    typeof value === "object" &&
    !(value instanceof ExactJsonNumber)
  ) {
    for (const [key, child] of Object.entries(value)) {
      exactValues(key, depth + 1);
      exactValues(child, depth + 1);
    }
  } else invalidFinancial();
}
function targets(kind: unknown, intent: FinancialObject): FinancialObject[] {
  if (kind !== "PAYMENT" && kind !== "CREDIT") return invalidFinancial();
  if (intent.mode !== "DESIGNATED") return invalidFinancial();
  financialText(intent.designation_reference, 500);
  if (kind === "PAYMENT") {
    exactKeys(intent, ["mode", "designation_reference", "targets"]);
    return rows(intent.targets, 100);
  }
  const target = { ...intent };
  delete target.mode;
  delete target.designation_reference;
  return [target];
}
function targetField(
  target: FinancialObject,
): "invoice_id" | "late_payment_charge_id" {
  return Object.hasOwn(target, "invoice_id")
    ? "invoice_id"
    : "late_payment_charge_id";
}

/** Parse a detached exact body; computed due facts belong only in the response. */
export function duePreviewBody(
  kind: DuePreviewKind,
  raw: string,
): FinancialObject {
  const body = financialObject(parseFinancialJson(raw));
  exactKeys(body, kind === "CREDIT" ? ["currency", "intent"] : ["intent"]);
  if (kind === "CREDIT" && body.currency !== "USD") invalidFinancial();
  const intent = financialObject(body.intent);
  stringifyFinancialJson(intent, 250_000);
  exactValues(intent);
  const seen = new Set<string>();
  let total = 0n,
    lineCount = 0,
    partCount = 0;
  for (const target of targets(kind, intent)) {
    const field = targetField(target),
      invoice = field === "invoice_id";
    exactKeys(target, [
      field,
      "amount_usd_cents",
      ...(invoice ? ["details"] : []),
    ]);
    unique(seen, `${field}:${financialId(target[field])}`);
    const expected = amount(target.amount_usd_cents);
    total += expected;
    if (total > maximum) invalidFinancial();
    if (!invoice) continue;
    const lines = new Set<string>();
    let lineTotal = 0n;
    for (const detail of rows(target.details, 500)) {
      exactKeys(
        detail,
        ["invoice_line_id", "amount_usd_cents"],
        ["source_parts"],
      );
      unique(lines, financialId(detail.invoice_line_id));
      const selected = amount(detail.amount_usd_cents);
      lineTotal += selected;
      if (++lineCount > 500) invalidFinancial();
      if (!Object.hasOwn(detail, "source_parts")) continue;
      const sources = new Set<string>();
      let sourceTotal = 0n;
      for (const part of rows(detail.source_parts, 500)) {
        exactKeys(part, ["source_kind", "source_id", "amount_usd_cents"]);
        unique(sources, source(part));
        sourceTotal += amount(part.amount_usd_cents);
        if (++partCount > 500) invalidFinancial();
      }
      if (sourceTotal !== selected) invalidFinancial();
    }
    if (lineTotal !== expected) invalidFinancial();
  }
  return body;
}

/** Bind dated confirmation to captured selections without calculating allocation policy. */
export function validateDuePreviewReply(
  kind: DuePreviewKind,
  capturedBody: string,
  value: unknown,
  propertyId: string,
  sourceId: string,
): FinancialObject {
  const selection = financialObject(duePreviewBody(kind, capturedBody).intent);
  const reply = financialObject(
    parseFinancialJson(stringifyFinancialJson(value)),
  );
  const sourceField = kind === "PAYMENT" ? "payment_id" : "credit_id";
  exactKeys(reply, [
    "property_id",
    sourceField,
    "available_usd_cents",
    "amount_usd_cents",
    "part_count",
    "intent",
  ]);
  sameId(reply.property_id, propertyId);
  sameId(reply[sourceField], sourceId);
  const confirmed = financialObject(reply.intent);
  stringifyFinancialJson(confirmed, 200_000);
  if (confirmed.designation_reference !== selection.designation_reference)
    invalidFinancial();
  const selectedTargets = targets(kind, selection),
    confirmedTargets = targets(kind, confirmed);
  if (selectedTargets.length !== confirmedTargets.length) invalidFinancial();
  let total = 0n,
    partCount = 0,
    detailCount = 0;
  for (let index = 0; index < selectedTargets.length; index++) {
    const selected = selectedTargets[index] ?? invalidFinancial();
    const target = confirmedTargets[index] ?? invalidFinancial();
    const field = targetField(selected),
      invoice = field === "invoice_id";
    exactKeys(target, [
      field,
      "amount_usd_cents",
      ...(invoice ? ["invoice_version", "details"] : []),
    ]);
    sameId(target[field], selected[field]);
    const expected = amount(selected.amount_usd_cents);
    if (amount(target.amount_usd_cents) !== expected) invalidFinancial();
    total += expected;
    if (!invoice) {
      if (++detailCount > 500) invalidFinancial();
      continue;
    }
    financialInteger(target.invoice_version, 1n, 9_999_999_999n);
    const wanted = rows(selected.details, 500),
      details = rows(target.details, 500);
    if (wanted.length !== details.length) invalidFinancial();
    for (let n = 0; n < details.length; n++) {
      const detail = details[n] ?? invalidFinancial(),
        input = wanted[n] ?? invalidFinancial();
      exactKeys(detail, [
        "invoice_line_id",
        "amount_usd_cents",
        "due_attribution",
      ]);
      sameId(detail.invoice_line_id, input.invoice_line_id);
      const lineAmount = amount(input.amount_usd_cents);
      if (amount(detail.amount_usd_cents) !== lineAmount || ++detailCount > 500)
        invalidFinancial();
      const due = financialObject(detail.due_attribution);
      exactKeys(due, ["basis", "parts"]);
      const explicit = Object.hasOwn(input, "source_parts")
        ? rows(input.source_parts, 500)
        : null;
      if (due.basis !== (explicit ? "CUSTOMER_DESIGNATED" : "EARLIEST_DUE"))
        invalidFinancial();
      const parts = rows(due.parts, 500);
      if (explicit && explicit.length !== parts.length) invalidFinancial();
      const seen = new Set<string>();
      let applied = 0n;
      for (let p = 0; p < parts.length; p++) {
        const part = parts[p] ?? invalidFinancial();
        exactKeys(part, [
          "source_kind",
          "source_id",
          "approved_due_date",
          "source_occurred_at",
          "outstanding_usd_cents",
          "amount_usd_cents",
        ]);
        unique(seen, source(part));
        if (part.source_kind === "ORIGINAL_LINE")
          sameId(part.source_id, detail.invoice_line_id);
        financialCalendarDate(part.approved_due_date);
        financialInstant(part.source_occurred_at);
        const appliedAmount = amount(part.amount_usd_cents);
        if (
          appliedAmount >
          BigInt(financialInteger(part.outstanding_usd_cents, 1n))
        )
          invalidFinancial();
        if (explicit) {
          const chosen = explicit[p] ?? invalidFinancial();
          if (
            source(part) !== source(chosen) ||
            appliedAmount !== amount(chosen.amount_usd_cents)
          )
            invalidFinancial();
        }
        applied += appliedAmount;
        if (++partCount > 500) invalidFinancial();
      }
      if (applied !== lineAmount) invalidFinancial();
    }
  }
  if (
    amount(reply.amount_usd_cents) !== total ||
    total > BigInt(financialInteger(reply.available_usd_cents)) ||
    BigInt(financialInteger(reply.part_count, 0n, 500n)) !== BigInt(partCount)
  )
    invalidFinancial();
  return reply;
}
