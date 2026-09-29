import {
  financialId,
  financialInteger,
  type FinancialObject,
} from "./financialContracts";
import {
  dueSourceKey,
  type FinancialDueSelection,
} from "./financialDueSelection";
import {
  FinancialInputError,
  selectedFinancialLineIntent,
} from "./financialUi";

export type FinancialDueLineSelections = Readonly<
  Record<string, FinancialDueSelection>
>;

function checkedSelections(
  choices: FinancialDueLineSelections,
): Record<string, FinancialDueSelection> {
  const checked: Record<string, FinancialDueSelection> = {};
  let count = 0;
  for (const [line, selection] of Object.entries(choices)) {
    if (financialId(line) !== line || !selection.parts.length)
      throw new FinancialInputError("Review the selected dated sources.");
    const seen = new Set<string>();
    let total = 0n;
    const parts = selection.parts.map((part) => {
      const key = dueSourceKey(part);
      if (seen.has(key))
        throw new FinancialInputError("A dated source is selected twice.");
      seen.add(key);
      const amount = BigInt(
        financialInteger(part.amount_usd_cents, 1n, 9_000_000_000_000_000n),
      );
      total += amount;
      return {
        source_kind: part.source_kind,
        source_id: part.source_id,
        amount_usd_cents: amount,
      };
    });
    if (total !== selection.amount || total > 9_000_000_000_000_000n)
      throw new FinancialInputError(
        "The dated-source total changed. Review the line's source selection.",
      );
    count += parts.length;
    if (count > 500)
      throw new FinancialInputError(
        "Select at most 500 dated sources across all Invoice lines.",
      );
    checked[line] = { parts, amount: total };
  }
  return checked;
}

/** Replace only the explicit choice for one line; never allocate by policy. */
export function replaceDueLineSelection(
  choices: FinancialDueLineSelections,
  line: string,
  selection: FinancialDueSelection,
): Record<string, FinancialDueSelection> {
  return checkedSelections({ ...choices, [line]: selection });
}

/** Reject lost or inconsistent choices instead of silently using earliest due. */
export function selectedDueLineIntent(
  data: FinancialObject,
  values: Record<string, string>,
  choices: FinancialDueLineSelections,
): { total: bigint; details: FinancialObject[] } {
  const selected = selectedFinancialLineIntent(data, values);
  const checked = checkedSelections(choices);
  for (const [line, choice] of Object.entries(checked)) {
    const detail = selected.details.find(
      (item) => item.invoice_line_id === line,
    );
    if (
      !detail ||
      BigInt(financialInteger(detail.amount_usd_cents)) !== choice.amount
    )
      throw new FinancialInputError(
        "A selected dated source no longer matches its Invoice line amount. Review or explicitly clear that selection.",
      );
  }
  return {
    total: selected.total,
    details: selected.details.map((detail) => {
      const choice = checked[financialId(detail.invoice_line_id)];
      return choice ? { ...detail, source_parts: choice.parts } : { ...detail };
    }),
  };
}
