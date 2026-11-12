// DL-221 (owner 11/11/2026): the Invoice types are Rent, Utilities, Short stay, Products, Damage
// and Other charges, as Settings › Invoice types lists them.

import { describe, expect, it } from "vitest";

import { invoiceTypeCode, type InvoiceResource } from "../invoiceClient";
import { lineWords } from "../payments/ReceiptDocument";
import { typeCategory } from "../payments/paymentsClient";
import { pyt } from "../payments/text";
import { filtered } from "./invoicesData";
import { invoiceType, invoiceTypeOf, ivt } from "./text";

function invoiceOf(
  id: string,
  category: InvoiceResource["category"],
  extra: Partial<InvoiceResource> = {},
): InvoiceResource {
  return {
    id,
    customer_id: "c-1",
    category,
    due_date: "2026-11-20",
    ...extra,
  } as InvoiceResource;
}

describe("Invoice types (DL-221)", () => {
  it("TEST-FE-2000 names an Invoice by the type the server sends", () => {
    const products = {
      category: "MISCELLANEOUS_CHARGES" as const,
      invoice_type: "PRODUCTS" as const,
    };
    expect(ivt("en", invoiceType(products))).toBe("Products");
    expect(ivt("km", invoiceType(products))).toBe("ផលិតផល");
    const stayDamage = {
      category: "MISCELLANEOUS_CHARGES" as const,
      short_stay: "SHORT_STAY_DAMAGE" as const,
      invoice_type: "DAMAGE" as const,
    };
    expect(ivt("en", invoiceType(stayDamage))).toBe("Damage");
    const other = {
      category: "MISCELLANEOUS_CHARGES" as const,
      invoice_type: "MISCELLANEOUS" as const,
    };
    expect(ivt("en", invoiceType(other))).toBe("Other charges");
    expect(invoiceTypeCode("SERVICES")).toBeNull();
    expect(invoiceTypeCode("FIRST_RENT")).toBeNull();
  });

  it("TEST-FE-2001 works the type out from the category when the server sends none", () => {
    expect(invoiceTypeOf({ category: "RENT" })).toBe("RENT");
    expect(invoiceTypeOf({ category: "SERVICE_CHARGES" })).toBe("RENT");
    expect(invoiceTypeOf({ category: "DAMAGE_CHARGES" })).toBe("DAMAGE");
    expect(
      invoiceTypeOf({
        category: "MISCELLANEOUS_CHARGES",
        short_stay: "SHORT_STAY",
      }),
    ).toBe("SHORT_STAY");
    expect(
      invoiceTypeOf({
        category: "MISCELLANEOUS_CHARGES",
        short_stay: "SHORT_STAY_DAMAGE",
      }),
    ).toBe("DAMAGE");
    expect(invoiceTypeOf({ category: "MISCELLANEOUS_CHARGES" })).toBe(
      "MISCELLANEOUS",
    );
  });

  it("TEST-FE-2002 the Invoices type filter picks by type", () => {
    const invoices = [
      invoiceOf("rent", "RENT", { invoice_type: "RENT" }),
      invoiceOf("product", "MISCELLANEOUS_CHARGES", {
        invoice_type: "PRODUCTS",
      }),
      invoiceOf("stay", "MISCELLANEOUS_CHARGES", {
        invoice_type: "SHORT_STAY",
      }),
      invoiceOf("stay-damage", "MISCELLANEOUS_CHARGES", {
        invoice_type: "DAMAGE",
      }),
      invoiceOf("damage", "DAMAGE_CHARGES", { invoice_type: "DAMAGE" }),
      invoiceOf("cleaning", "MISCELLANEOUS_CHARGES", {
        invoice_type: "MISCELLANEOUS",
      }),
    ];
    const ids = (type: Parameters<typeof filtered>[2]) =>
      filtered(invoices, null, type, null).map((invoice) => invoice.id);
    expect(ids("PRODUCTS")).toEqual(["product"]);
    expect(ids("SHORT_STAY")).toEqual(["stay"]);
    expect(ids("DAMAGE")).toEqual(["stay-damage", "damage"]);
    expect(ids("MISCELLANEOUS")).toEqual(["cleaning"]);
    expect(ids("all")).toHaveLength(6);
  });

  it("TEST-FE-2003 Receive payment and the Receipt name the type", () => {
    expect(typeCategory("PRODUCTS")).toBe("PRODUCTS");
    expect(typeCategory("DAMAGE")).toBe("DAMAGE_CHARGES");
    expect(typeCategory("SHORT_STAY")).toBe("SHORT_STAY");
    expect(typeCategory("NOTHING")).toBeNull();
    expect(pyt("en", "PRODUCTS")).toBe("Products");
    expect(pyt("en", "MISCELLANEOUS_CHARGES")).toBe("Other charges");
    expect(
      lineWords({
        kind: "INVOICE",
        invoiceId: "i-1",
        invoiceNumber: "INV260020",
        category: "PRODUCTS",
        dueDate: null,
        depositType: null,
        amount: 1500,
      }),
    ).toEqual(["ផលិតផល", "Products", "INV260020"]);
  });
});
