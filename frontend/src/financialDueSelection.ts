import {
  financialId,
  financialInteger,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { FinancialInputError, parseFinancialAmount } from "./financialUi";

export interface FinancialDueSelectedPart extends FinancialObject {
  source_kind: "ORIGINAL_LINE" | "DEBIT_ADJUSTMENT";
  source_id: string;
  amount_usd_cents: bigint;
}
export interface FinancialDueSelection {
  parts: FinancialDueSelectedPart[];
  amount: bigint;
}
const maximum = 9_000_000_000_000_000n;

export function dueSourceKey(source: FinancialObject): string {
  if (
    source.source_kind !== "ORIGINAL_LINE" &&
    source.source_kind !== "DEBIT_ADJUSTMENT"
  )
    return invalidFinancial();
  const id = financialId(source.source_id);
  if (id !== source.source_id) return invalidFinancial();
  return `${source.source_kind}:${id}`;
}
export function dueAmountText(value: bigint): string {
  const amount = BigInt(financialInteger(value, 0n, maximum));
  return `${(amount / 100n).toString()}.${(amount % 100n).toString().padStart(2, "0")}`;
}

/** Preserve explicit source amounts; never calculate an allocation policy. */
export function selectedDueSources(
  data: FinancialObject,
  values: Readonly<Record<string, string>>,
): FinancialDueSelection {
  if (!Array.isArray(data.items)) return invalidFinancial();
  const rows = data.items.map(financialObject);
  if (rows.length !== Number(financialInteger(data.item_count, 0n, 32767n)))
    return invalidFinancial();
  const sources = new Map<string, FinancialObject>();
  let remaining = 0n;
  for (const row of rows) {
    const key = dueSourceKey(row);
    if (sources.has(key)) return invalidFinancial();
    sources.set(key, row);
    remaining += BigInt(financialInteger(row.remaining_usd_cents, 1n));
  }
  if (
    remaining !== BigInt(financialInteger(data.aggregate_outstanding_usd_cents))
  )
    return invalidFinancial();
  const selected = new Map<string, bigint>();
  let amount = 0n;
  for (const [key, text] of Object.entries(values)) {
    if (!text) continue;
    const value = parseFinancialAmount(text, "USD", true);
    if (value === 0n) continue;
    const row = sources.get(key);
    if (!row || value > BigInt(financialInteger(row.remaining_usd_cents, 1n)))
      throw new FinancialInputError(
        "A selected dated source changed or its amount exceeds the current balance. Reload and review the source selection.",
      );
    selected.set(key, value);
    amount += value;
  }
  if (selected.size < 1 || selected.size > 500 || amount > maximum)
    throw new FinancialInputError(
      "Select positive USD amounts from one to 500 dated sources within the permitted amount.",
    );
  const parts: FinancialDueSelectedPart[] = [];
  // Preserve the server's source display order, without changing any chosen amount.
  for (const row of rows) {
    const value = selected.get(dueSourceKey(row));
    if (value === undefined) continue;
    const kind = row.source_kind;
    if (kind !== "ORIGINAL_LINE" && kind !== "DEBIT_ADJUSTMENT")
      return invalidFinancial();
    parts.push({
      source_kind: kind,
      source_id: financialId(row.source_id),
      amount_usd_cents: value,
    });
  }
  return { parts, amount };
}
