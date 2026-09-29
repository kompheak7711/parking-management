import {
  exactKeys,
  financialCalendarDate,
  financialId,
  financialInstant,
  financialInteger,
  financialObject,
  invalidFinancial,
} from "./financialContracts";

const maximum = 9_000_000_000_000_000n;
const amount = (value: unknown) => BigInt(financialInteger(value, 1n, maximum));
function rows(value: unknown): unknown[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 500)
    return invalidFinancial();
  return value;
}
/** Check captured dated evidence without rewriting its order, bytes or values. */
export function validateDueConfirmation(
  details: unknown,
  total: unknown,
  version: unknown,
): void {
  financialInteger(version, 1n, 9_999_999_999n);
  const expected = amount(total),
    seen = new Set<string>();
  let actual = 0n,
    count = 0;
  for (const value of rows(details)) {
    const detail = financialObject(value);
    exactKeys(detail, [
      "invoice_line_id",
      "amount_usd_cents",
      "due_attribution",
    ]);
    const line = financialId(detail.invoice_line_id);
    if (seen.has(line)) invalidFinancial();
    seen.add(line);
    const selected = amount(detail.amount_usd_cents);
    actual += selected;
    const due = financialObject(detail.due_attribution);
    exactKeys(due, ["basis", "parts"]);
    if (due.basis !== "EARLIEST_DUE" && due.basis !== "CUSTOMER_DESIGNATED")
      invalidFinancial();
    const sources = new Set<string>();
    let applied = 0n;
    for (const value of rows(due.parts)) {
      const part = financialObject(value);
      exactKeys(part, [
        "source_kind",
        "source_id",
        "approved_due_date",
        "source_occurred_at",
        "outstanding_usd_cents",
        "amount_usd_cents",
      ]);
      if (
        part.source_kind !== "ORIGINAL_LINE" &&
        part.source_kind !== "DEBIT_ADJUSTMENT"
      )
        invalidFinancial();
      const identity = financialId(part.source_id),
        key = `${part.source_kind}:${identity}`;
      if (
        sources.has(key) ||
        (part.source_kind === "ORIGINAL_LINE" && identity !== line)
      )
        invalidFinancial();
      sources.add(key);
      financialCalendarDate(part.approved_due_date);
      financialInstant(part.source_occurred_at);
      const partAmount = amount(part.amount_usd_cents);
      if (partAmount > BigInt(financialInteger(part.outstanding_usd_cents, 1n)))
        invalidFinancial();
      applied += partAmount;
      if (++count > 500) invalidFinancial();
    }
    if (applied !== selected) invalidFinancial();
  }
  if (actual !== expected) invalidFinancial();
}
