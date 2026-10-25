// V1-058 R5c: "What this money pays for" on Receive payment (DESIGN.md; DL-077, DL-076 answer 5).
// Money pays Invoices when it is received. The app ticks the oldest Due Date first until the
// money is used, a late-payment charge right after its own Invoice; staff change the ticks only
// when the Customer names what to pay (BR-PAY-024). The server checks the same order again and
// refuses ticks that no longer match, so nothing is saved from an old list.

export interface PayableItem {
  kind: "INVOICE" | "LATE_PAYMENT_CHARGE";
  /** The Invoice id, or the late-payment charge id. */
  id: string;
  /** The Invoice, or the Invoice the charge came from. */
  invoiceId: string;
  invoiceNumber: string;
  category: string | null;
  dueDate: string | null;
  /** What is still owed, in cents. */
  owed: number;
}

export interface PlanRow {
  item: PayableItem;
  on: boolean;
  /** What this money pays on the row, in cents. */
  pays: number;
}

export interface PayPlan {
  rows: PlanRow[];
  /** Money left after the ticked rows, in cents. */
  rest: number;
  /** True while the app chooses the ticks (oldest first). */
  auto: boolean;
  /** True when a row is not ticked. */
  more: boolean;
}

/** Walks the rows in order; `picks` is null while the app ticks oldest first. */
export function planFor(
  items: readonly PayableItem[],
  cents: number | null,
  picks: ReadonlySet<string> | null,
): PayPlan {
  let rest = cents ?? 0;
  const rows = items.map((item) => {
    const on = picks === null ? cents !== null && rest > 0 : picks.has(item.id);
    const pays = on ? Math.max(0, Math.min(rest, item.owed)) : 0;
    rest -= pays;
    return { item, on, pays };
  });
  return {
    rows,
    rest,
    auto: picks === null,
    more: rows.some((row) => !row.on),
  };
}

/** The total of the ticked rows: ticking by hand sets the amount (owner, 13/10/2026). */
export function pickedTotal(
  items: readonly PayableItem[],
  picks: ReadonlySet<string>,
): number {
  return items
    .filter((item) => picks.has(item.id))
    .reduce((total, item) => total + item.owed, 0);
}

export type PayProblem =
  | { kind: "pick" }
  | { kind: "zero"; item: PayableItem }
  | { kind: "more"; rest: number };

/** Why these ticks cannot be saved, in the order the mock-up names them. */
export function payProblem(
  plan: PayPlan,
  cents: number | null,
): PayProblem | null {
  if (cents === null || plan.rows.length === 0) return null;
  const ticked = plan.rows.filter((row) => row.on);
  if (ticked.length === 0) return { kind: "pick" };
  const empty = ticked.find((row) => row.pays === 0);
  if (empty !== undefined) return { kind: "zero", item: empty.item };
  if (plan.rest > 0 && plan.more) return { kind: "more", rest: plan.rest };
  return null;
}

export interface PaysTargetInput {
  invoice_id?: string;
  late_payment_charge_id?: string;
  amount_usd_cents: number;
}

/** What the server is asked to pay: the ticks the screen showed. */
export function paysOf(plan: PayPlan): {
  mode: "OLDEST_FIRST" | "NAMED";
  targets: PaysTargetInput[];
} {
  const targets = plan.rows
    .filter((row) => row.on && row.pays > 0)
    .map((row) =>
      row.item.kind === "INVOICE"
        ? { invoice_id: row.item.id, amount_usd_cents: row.pays }
        : { late_payment_charge_id: row.item.id, amount_usd_cents: row.pays },
    );
  return { mode: plan.auto ? "OLDEST_FIRST" : "NAMED", targets };
}
