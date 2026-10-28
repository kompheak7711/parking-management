import { describe, expect, it } from "vitest";

import { planSettlement } from "./plan";
import type { SettlementPreview } from "./settlement";

function line(
  id: string,
  invoice: string,
  category: string,
  cents: number,
  options: { customer?: string; pet?: boolean } = {},
) {
  return {
    invoice_id: invoice,
    invoice_line_id: id,
    customer_id: options.customer ?? "tenant",
    category,
    description: id,
    due_date: "2026-10-05",
    outstanding_usd_cents: cents,
    pet_damage: options.pet ?? false,
  };
}

function preview(change: Partial<SettlementPreview> = {}): SettlementPreview {
  return {
    settlement: {
      id: "fs-1",
      lease_id: "lease-1",
      started_at: "2026-10-20T03:00:00Z",
      closed: false,
      closed_at: null,
      closing_balance_due_usd_cents: null,
      pending_draft: false,
    },
    customers: [
      {
        customer_id: "tenant",
        primary_tenant: true,
        // On the October Invoice the water line comes first, Rent second.
        invoice_lines: [
          line("water", "inv-oct", "UTILITIES", 2000),
          line("rent", "inv-oct", "RENT", 30000),
          line("dog", "inv-dmg", "DAMAGE_CHARGES", 12500, { pet: true }),
          line("window", "inv-dmg", "DAMAGE_CHARGES", 12500),
        ],
        late_payment_charges: [
          {
            late_payment_charge_id: "late",
            source_invoice_id: "inv-oct",
            customer_id: "tenant",
            remaining_usd_cents: 1500,
          },
        ],
        open_total_usd_cents: 58500,
        credits: [{ customer_credit_id: "credit", available_usd_cents: 400 }],
        credit_available_usd_cents: 400,
        credit_may_use_usd_cents: 400,
      },
    ],
    deposits: [
      {
        deposit_id: "pet",
        deposit_type: "PET",
        customer_id: "tenant",
        held_usd_cents: 20000,
        path: "DL_032",
        ground: null,
      },
      {
        deposit_id: "security",
        deposit_type: "SECURITY",
        customer_id: "tenant",
        held_usd_cents: 30000,
        path: "DL_032",
        ground: null,
      },
    ],
    open_total_usd_cents: 58500,
    pet_damage_open_usd_cents: 12500,
    pet_remainder_chosen_by: "CUSTOMER_OR_STAFF_WITH_REASON",
    blocking_issues: [],
    voided_not_billed_usd_cents: [],
    ready: true,
    ...change,
  };
}

const brief = (plan: ReturnType<typeof planSettlement>) =>
  plan.steps.map((step) => [
    step.kind,
    "customer_credit_id" in step ? step.customer_credit_id : step.deposit_id,
    step.target_id,
    step.amount_usd_cents,
  ]);

describe("Final Settlement plan", () => {
  it("TEST-FE-991 follows DL-032: own Credit first (Rent first on its Invoice), Pet Deposit for pet damage, Security Deposit oldest first with the late charge after its Invoice, then the rest of the Pet Deposit only when chosen, and refunds what is left", () => {
    const without = planSettlement(preview(), false);
    expect(brief(without)).toEqual([
      ["CUSTOMER_CREDIT", "credit", "rent", 400],
      ["PET_DEPOSIT_PET_DAMAGE", "pet", "dog", 12500],
      ["SECURITY_DEPOSIT", "security", "rent", 29600],
      ["SECURITY_DEPOSIT", "security", "water", 400],
    ]);
    expect(without.balance_usd_cents).toBe(1600 + 1500 + 12500);
    expect(without.pet_rest_possible).toBe(true);
    expect(without.refunds).toEqual([
      { deposit_id: "pet", deposit_type: "PET", amount_usd_cents: 7500 },
    ]);

    const chosen = planSettlement(preview(), true);
    expect(brief(chosen).slice(4)).toEqual([
      ["PET_DEPOSIT_REMAINDER", "pet", "water", 1600],
      ["PET_DEPOSIT_REMAINDER", "pet", "late", 1500],
      ["PET_DEPOSIT_REMAINDER", "pet", "window", 4400],
    ]);
    expect(chosen.refunds).toEqual([]);
    expect(chosen.balance_usd_cents).toBe(8100);
    expect(chosen.credit_used_usd_cents).toBe(400);
    expect(chosen.pet_damage_paid_usd_cents).toBe(12500);
    expect(chosen.security_applied_usd_cents).toBe(30000);
    expect(chosen.pet_rest_applied_usd_cents).toBe(7500);
  });

  it("TEST-FE-992 a kept Deposit pays nothing and is not refunded; a Customer's Credit pays only that Customer's debt; with no debt every Deposit is refunded in full", () => {
    const kept = planSettlement(
      preview({
        deposits: [
          {
            deposit_id: "security",
            deposit_type: "SECURITY",
            customer_id: "tenant",
            held_usd_cents: 30000,
            path: "KEPT",
            ground: null,
          },
        ],
      }),
      false,
    );
    expect(kept.steps.every((step) => step.kind === "CUSTOMER_CREDIT")).toBe(
      true,
    );
    expect(kept.refunds).toEqual([]);
    expect(kept.pet_rest_possible).toBe(false);

    const two = preview({
      customers: [
        {
          customer_id: "tenant",
          primary_tenant: true,
          invoice_lines: [],
          late_payment_charges: [],
          open_total_usd_cents: 0,
          credits: [],
          credit_available_usd_cents: 0,
          credit_may_use_usd_cents: 0,
        },
        {
          customer_id: "signer",
          primary_tenant: false,
          invoice_lines: [
            line("signer-rent", "inv-s", "RENT", 900, { customer: "signer" }),
          ],
          late_payment_charges: [],
          open_total_usd_cents: 900,
          credits: [
            { customer_credit_id: "c1", available_usd_cents: 500 },
            { customer_credit_id: "c2", available_usd_cents: 500 },
          ],
          credit_available_usd_cents: 1000,
          credit_may_use_usd_cents: 900,
        },
      ],
      deposits: [],
    });
    expect(brief(planSettlement(two, false))).toEqual([
      ["CUSTOMER_CREDIT", "c1", "signer-rent", 500],
      ["CUSTOMER_CREDIT", "c2", "signer-rent", 400],
    ]);

    // Oldest Due Date first across the Customers: the Signer's July Invoice before the
    // Primary Tenant's October one, though the preview lists the Primary Tenant first.
    const july = preview({
      customers: [
        {
          customer_id: "tenant",
          primary_tenant: true,
          open_total_usd_cents: 500,
          invoice_lines: [line("oct-rent", "inv-oct", "RENT", 500)],
          late_payment_charges: [],
          credits: [],
          credit_available_usd_cents: 0,
          credit_may_use_usd_cents: 0,
        },
        {
          customer_id: "signer",
          primary_tenant: false,
          late_payment_charges: [],
          open_total_usd_cents: 500,
          invoice_lines: [
            {
              ...line("jul-rent", "inv-jul", "RENT", 500, {
                customer: "signer",
              }),
              due_date: "2026-07-05",
            },
          ],
          credits: [],
          credit_available_usd_cents: 0,
          credit_may_use_usd_cents: 0,
        },
      ],
      deposits: [
        {
          deposit_id: "security",
          deposit_type: "SECURITY",
          customer_id: "tenant",
          held_usd_cents: 700,
          path: "DL_032",
          ground: null,
        },
      ],
    });
    expect(brief(planSettlement(july, false))).toEqual([
      ["SECURITY_DEPOSIT", "security", "jul-rent", 500],
      ["SECURITY_DEPOSIT", "security", "oct-rent", 200],
    ]);

    const clean = planSettlement(preview({ customers: [] }), false);
    expect(clean.steps).toEqual([]);
    expect(clean.balance_usd_cents).toBe(0);
    expect(clean.refunds.map((item) => item.amount_usd_cents)).toEqual([
      20000, 30000,
    ]);
  });
});
