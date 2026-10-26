// V1-058 R3 Move-out M5b: the Final Settlement draft the page proposes, in the DL-032 order
// (DESIGN.md "Move-out (round 3)", Statement): each Customer's own Credit pays that Customer's
// open debt first (BR-CREDIT-008), the Pet Deposit pays pet damage, the Security Deposit pays
// what is left, the rest of the Pet Deposit pays other debt only by the Customer's choice or a
// staff reason (BR-SETTLE-005), the balance stays owed, and what each Deposit still holds is
// refunded. Debt is paid oldest Due Date first; on one Invoice Rent comes first, then services,
// as the Rent-first proposal (BR-CREDIT-006); a late-payment charge right after its Invoice.
// The server checks the whole plan again when the draft is recorded and when it is confirmed;
// this only spares staff from choosing every amount by hand.

import type { CreditStepInput, DepositStepInput } from "../settlementForms";
import type { SettlementPreview } from "./settlement";

interface Target {
  kind: "INVOICE_LINE" | "LATE_PAYMENT_CHARGE";
  id: string;
  customer_id: string;
  pet_damage: boolean;
  open: number;
}

/** A Deposit's refund, before the method, reference and recipient are chosen. */
export interface PlannedRefund {
  deposit_id: string;
  deposit_type: "SECURITY" | "PET";
  amount_usd_cents: number;
}

export interface SettlementPlan {
  steps: (CreditStepInput | DepositStepInput)[];
  refunds: PlannedRefund[];
  credit_used_usd_cents: number;
  pet_damage_paid_usd_cents: number;
  security_applied_usd_cents: number;
  pet_rest_applied_usd_cents: number;
  /** What the Customers still owe after the draft (stays open; no write-off in V1). */
  balance_usd_cents: number;
  /** Debt is left after the Security Deposit and a Pet Deposit still holds money. */
  pet_rest_possible: boolean;
}

const RANK: Record<string, number> = { RENT: 0, SERVICE_CHARGES: 1 };
const rank = (category: string) =>
  Object.hasOwn(RANK, category) ? (RANK[category] ?? 2) : 2;

/** Every open obligation of the Settlement, in the order the money pays it. */
function targets(preview: SettlementPreview): Target[] {
  const lines = preview.customers.flatMap((customer) => customer.invoice_lines);
  const charges = preview.customers.flatMap(
    (customer) => customer.late_payment_charges,
  );
  // Invoices oldest Due Date first across every Customer of the Lease (the preview lists them
  // per Customer); the sort is stable, so equal dates keep the preview's order.
  const due = new Map<string, string>();
  for (const line of lines)
    if (
      !due.has(line.invoice_id) ||
      line.due_date < (due.get(line.invoice_id) ?? "")
    )
      due.set(line.invoice_id, line.due_date);
  const invoices = [...due.keys()].sort((left, right) =>
    (due.get(left) ?? "").localeCompare(due.get(right) ?? ""),
  );
  const ordered: Target[] = invoices.flatMap((invoice) => {
    const own = lines.filter((line) => line.invoice_id === invoice);
    const mixed = own.some((line) => Object.hasOwn(RANK, line.category));
    const sorted = mixed
      ? [...own].sort(
          (left, right) => rank(left.category) - rank(right.category),
        )
      : own;
    return [
      ...sorted.map((line) => ({
        kind: "INVOICE_LINE" as const,
        id: line.invoice_line_id,
        customer_id: line.customer_id,
        pet_damage: line.pet_damage,
        open: line.outstanding_usd_cents,
      })),
      ...charges
        .filter((charge) => charge.source_invoice_id === invoice)
        .map((charge) => ({
          kind: "LATE_PAYMENT_CHARGE" as const,
          id: charge.late_payment_charge_id,
          customer_id: charge.customer_id,
          pet_damage: false,
          open: charge.remaining_usd_cents,
        })),
    ];
  });
  // A late-payment charge whose Invoice is paid comes last, in the preview's order.
  for (const charge of charges)
    if (!invoices.includes(charge.source_invoice_id))
      ordered.push({
        kind: "LATE_PAYMENT_CHARGE",
        id: charge.late_payment_charge_id,
        customer_id: charge.customer_id,
        pet_damage: false,
        open: charge.remaining_usd_cents,
      });
  return ordered;
}

/**
 * The proposed draft. usePetRest: the rest of the Pet Deposit pays the debt left after the
 * Security Deposit (the Customer's choice, or a staff reason where the termination allows it).
 */
export function planSettlement(
  preview: SettlementPreview,
  usePetRest: boolean,
): SettlementPlan {
  const open = targets(preview);
  const steps: (CreditStepInput | DepositStepInput)[] = [];
  const pay = (
    from: number,
    eligible: (target: Target) => boolean,
    step: (
      target: Target,
      amount: number,
    ) => CreditStepInput | DepositStepInput,
  ): number => {
    let left = from;
    for (const target of open) {
      if (left === 0) break;
      if (target.open === 0 || !eligible(target)) continue;
      const amount = Math.min(left, target.open);
      steps.push(step(target, amount));
      target.open -= amount;
      left -= amount;
    }
    return from - left;
  };

  // Step 2: each Customer's own Credit, up to what it may pay.
  let creditUsed = 0;
  for (const customer of preview.customers) {
    let mayUse = customer.credit_may_use_usd_cents;
    for (const credit of customer.credits) {
      if (mayUse === 0) break;
      const used = pay(
        Math.min(mayUse, credit.available_usd_cents),
        (target) => target.customer_id === customer.customer_id,
        (target, amount) => ({
          kind: "CUSTOMER_CREDIT",
          customer_credit_id: credit.customer_credit_id,
          target_kind: target.kind,
          target_id: target.id,
          amount_usd_cents: amount,
          customer_designation: null,
        }),
      );
      mayUse -= used;
      creditUsed += used;
    }
  }

  const usable = preview.deposits.filter(
    (deposit) => deposit.path === "DL_032" && deposit.held_usd_cents > 0,
  );
  const left = new Map(
    usable.map((deposit) => [deposit.deposit_id, deposit.held_usd_cents]),
  );
  const depositStep =
    (kind: DepositStepInput["kind"], depositId: string) =>
    (target: Target, amount: number): DepositStepInput => ({
      kind,
      deposit_id: depositId,
      target_kind: target.kind,
      target_id: target.id,
      amount_usd_cents: amount,
    });
  const spend = (
    type: "SECURITY" | "PET",
    kind: DepositStepInput["kind"],
    eligible: (target: Target) => boolean,
  ): number => {
    let total = 0;
    for (const deposit of usable.filter((item) => item.deposit_type === type)) {
      const used = pay(
        left.get(deposit.deposit_id) ?? 0,
        eligible,
        depositStep(kind, deposit.deposit_id),
      );
      left.set(deposit.deposit_id, (left.get(deposit.deposit_id) ?? 0) - used);
      total += used;
    }
    return total;
  };

  // Step 3: the Pet Deposit pays pet damage; step 4: the Security Deposit pays all debt.
  const petDamage = spend(
    "PET",
    "PET_DEPOSIT_PET_DAMAGE",
    (target) => target.pet_damage,
  );
  const security = spend("SECURITY", "SECURITY_DEPOSIT", () => true);
  const owedAfterSecurity = open.reduce((total, item) => total + item.open, 0);
  const petLeft = usable
    .filter((deposit) => deposit.deposit_type === "PET")
    .reduce((total, deposit) => total + (left.get(deposit.deposit_id) ?? 0), 0);
  // Step 5: the rest of the Pet Deposit, only when chosen.
  const petRest =
    usePetRest && owedAfterSecurity > 0
      ? spend("PET", "PET_DEPOSIT_REMAINDER", () => true)
      : 0;

  return {
    steps,
    refunds: usable
      .map((deposit) => ({
        deposit_id: deposit.deposit_id,
        deposit_type: deposit.deposit_type,
        amount_usd_cents: left.get(deposit.deposit_id) ?? 0,
      }))
      .filter((refund) => refund.amount_usd_cents > 0),
    credit_used_usd_cents: creditUsed,
    pet_damage_paid_usd_cents: petDamage,
    security_applied_usd_cents: security,
    pet_rest_applied_usd_cents: petRest,
    balance_usd_cents: open.reduce((total, item) => total + item.open, 0),
    pet_rest_possible: owedAfterSecurity > 0 && petLeft > 0,
  };
}
