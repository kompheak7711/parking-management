import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InvoiceApi, InvoiceResource } from "../invoiceClient";
import {
  SettlementRequestError,
  type SettlementApi,
} from "../settlementClient";
import {
  HandBackRentStep,
  assessmentOf,
  handBackRentMonth,
} from "./HandBackRentStep";

afterEach(cleanup);

const money = (cents: number) => ({
  currency: "USD" as const,
  minor_units: cents,
});

/** The monthly Rent Invoice of a month: Rent 800.00 and Trash Collection 10.00. */
function rentInvoice(
  start: string,
  status: InvoiceResource["status"] = "UNPAID",
): InvoiceResource {
  return {
    id: `invoice-${start}`,
    property_id: "property-1",
    customer_id: "customer-1",
    lease_id: "lease-1",
    invoice_number: `INV-${start.slice(0, 7)}`,
    category: "RENT",
    status,
    invoice_date: "2026-07-25",
    due_date: "2026-08-05",
    billing_period: { start, end: "2026-08-31", end_inclusive: true },
    version: 4,
    original_total: money(81000),
    adjusted_total: money(81000),
    active_application_total: money(0),
    outstanding_balance: money(81000),
    lines: [],
    adjustments: [],
    void_event: null,
    evidence: {},
  };
}

/** The server's assessment of the example: handed back on 3 August, nothing paid. */
const unpaid = {
  invoice_id: "invoice-2026-08-01",
  invoice_version: 4,
  invoice_status: "UNPAID",
  coverage: "HAND_BACK_MONTH",
  action: "CREDIT_ADJUSTMENT",
  days_used: 3,
  days_in_month: 31,
  applied_usd_cents: 0,
  outstanding_usd_cents: 81000,
  kept_usd_cents: 7839,
  credit_usd_cents: 73161,
  released_usd_cents: 0,
  lines: [],
};

function setup(
  options: {
    day?: string;
    invoices?: InvoiceResource[];
    assessment?: SettlementApi["handBackAssessment"];
    resolve?: SettlementApi["resolveHandBack"];
    capabilities?: ReadonlySet<string> | null;
  } = {},
) {
  const invoiceApi = {
    list: vi.fn<InvoiceApi["list"]>(() =>
      Promise.resolve({
        items: options.invoices ?? [rentInvoice("2026-08-01")],
        next_cursor: null,
        capabilities: [],
      }),
    ),
  };
  const settlementApi = {
    handBackAssessment: vi.fn<SettlementApi["handBackAssessment"]>(
      options.assessment ?? (() => Promise.resolve(unpaid)),
    ),
    resolveHandBack: vi.fn<SettlementApi["resolveHandBack"]>(
      options.resolve ?? (() => Promise.resolve({ action: "done" })),
    ),
  };
  const onDone = vi.fn<(message: string) => void>();
  render(
    <HandBackRentStep
      capabilities={options.capabilities ?? null}
      handBackDay={options.day ?? "2026-08-03"}
      invoiceApi={invoiceApi}
      language="en"
      leaseId="lease-1"
      onDone={onDone}
      propertyId="property-1"
      settlementApi={settlementApi}
    />,
  );
  return { invoiceApi, settlementApi, onDone };
}

const amountOf = (term: string) =>
  screen.getByText(term).nextElementSibling?.textContent;

describe("the Rent for the days used after a hand-back (DL-229)", () => {
  it("TEST-FE-2240 the hand-back day names the month whose Rent Invoice is decided: before the 5th its own month, from the 25th the next month, in between none", () => {
    expect(handBackRentMonth("2026-08-01")).toBe("2026-08-01");
    expect(handBackRentMonth("2026-08-04")).toBe("2026-08-01");
    expect(handBackRentMonth("2026-08-05")).toBeNull();
    expect(handBackRentMonth("2026-08-24")).toBeNull();
    expect(handBackRentMonth("2026-08-25")).toBe("2026-09-01");
    expect(handBackRentMonth("2026-12-31")).toBe("2027-01-01");
    expect(handBackRentMonth("soon")).toBeNull();
    // An answer the screen cannot read is not shown as numbers.
    expect(assessmentOf({ ...unpaid, credit_usd_cents: "73161" })).toBeNull();
    expect(assessmentOf({ ...unpaid, action: "WAIT" })).toBeNull();
  });

  it("TEST-FE-2241 an unpaid Invoice handed back on the 3rd shows 3 of 31 days and the amounts, and Lower the Invoice sends back exactly what was shown with the Invoice version", async () => {
    const { invoiceApi, settlementApi, onDone } = setup();
    await screen.findByText("Invoice INV-2026-08: 3 of 31 days used.");
    expect(invoiceApi.list).toHaveBeenCalledWith("property-1", {
      lease_id: "lease-1",
      category: "RENT",
    });
    expect(settlementApi.handBackAssessment).toHaveBeenCalledWith(
      "invoice-2026-08-01",
    );
    expect(amountOf("Invoice charges now")).toBe("$810.00");
    expect(amountOf("For the days used")).toBe("$78.39");
    expect(amountOf("To take off the Invoice")).toBe("$731.61");
    expect(amountOf("Paid before, goes to Customer Credit")).toBe("$0.00");
    expect(amountOf("Still to pay after this")).toBe("$78.39");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Lower the Invoice to the days used",
      }),
    );
    await waitFor(() => {
      expect(onDone).toHaveBeenCalledWith(
        "Invoice INV-2026-08 now charges $78.39, for the days used.",
      );
    });
    const [invoice, version, form, key] =
      settlementApi.resolveHandBack.mock.calls[0] ?? [];
    expect([invoice, version]).toEqual(["invoice-2026-08-01", 4]);
    expect(form).toEqual({
      action: "CREDIT_ADJUSTMENT",
      expected_outstanding_usd_cents: 81000,
      expected_credit_usd_cents: 73161,
      reason: "Unit handed back on 03/08/2026: Rent for 3 of 31 days",
    });
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("TEST-FE-2242 a fully paid Invoice shows what goes back to the Customer as Customer Credit and sends 0 as the unpaid amount, with the reason staff typed", async () => {
    const { settlementApi } = setup({
      invoices: [rentInvoice("2026-08-01", "PAID")],
      assessment: () =>
        Promise.resolve({
          ...unpaid,
          invoice_status: "PAID",
          applied_usd_cents: 81000,
          outstanding_usd_cents: 0,
          released_usd_cents: 73161,
        }),
    });
    await screen.findByText("Invoice INV-2026-08: 3 of 31 days used.");
    expect(amountOf("Paid before, goes to Customer Credit")).toBe("$731.61");
    expect(amountOf("Still to pay after this")).toBe("$0.00");
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "  Keys returned on the 3rd  " },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Lower the Invoice to the days used",
      }),
    );
    await waitFor(() => {
      expect(settlementApi.resolveHandBack).toHaveBeenCalled();
    });
    expect(settlementApi.resolveHandBack.mock.calls[0]?.[2]).toEqual({
      action: "CREDIT_ADJUSTMENT",
      expected_outstanding_usd_cents: 0,
      expected_credit_usd_cents: 73161,
      reason: "Keys returned on the 3rd",
    });
  });

  it("TEST-FE-2243 a hand-back from the 25th reads next month's Invoice: unpaid it is made Void, and a person who cannot make an Invoice Void sees why there is no button", async () => {
    const next = {
      ...unpaid,
      invoice_id: "invoice-2026-09-01",
      coverage: "NEXT_MONTH",
      action: "VOID",
      days_used: 0,
      days_in_month: 30,
      kept_usd_cents: 0,
      credit_usd_cents: 81000,
    };
    const invoices = [rentInvoice("2026-08-01"), rentInvoice("2026-09-01")];
    const { settlementApi, onDone } = setup({
      day: "2026-08-26",
      invoices,
      assessment: () => Promise.resolve(next),
    });
    await screen.findByText(
      "Invoice INV-2026-09 is for next month: no day used.",
    );
    expect(settlementApi.handBackAssessment).toHaveBeenCalledWith(
      "invoice-2026-09-01",
    );
    expect(amountOf("Still to pay after this")).toBe("$0.00");
    fireEvent.click(
      screen.getByRole("button", { name: "Make next month's Invoice Void" }),
    );
    await waitFor(() => {
      expect(onDone).toHaveBeenCalledWith("Invoice INV-2026-09 is now Void.");
    });
    expect(settlementApi.resolveHandBack.mock.calls[0]?.[2]).toMatchObject({
      action: "VOID",
      expected_outstanding_usd_cents: 81000,
      expected_credit_usd_cents: 81000,
    });
    cleanup();

    setup({
      day: "2026-08-26",
      invoices,
      assessment: () => Promise.resolve(next),
      capabilities: new Set([
        "invoices.read",
        "leases.read",
        "invoices.adjust",
      ]),
    });
    await screen.findByText(
      "Your account cannot make an Invoice Void. Ask a Manager to do this step.",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("TEST-FE-2244 nothing is asked or shown when the rule does not apply: a hand-back from the 5th to the 24th, no Invoice for the month, a Lease the rule does not cover, or a person who may not read Invoices; an Invoice already at the days used says so", async () => {
    const middle = setup({ day: "2026-08-12" });
    expect(middle.invoiceApi.list).not.toHaveBeenCalled();
    cleanup();

    const none = setup({ invoices: [rentInvoice("2026-07-01")] });
    await waitFor(() => {
      expect(none.invoiceApi.list).toHaveBeenCalled();
    });
    expect(none.settlementApi.handBackAssessment).not.toHaveBeenCalled();
    cleanup();

    // A VOID Invoice is not asked about.
    const voided = setup({ invoices: [rentInvoice("2026-08-01", "VOID")] });
    await waitFor(() => {
      expect(voided.invoiceApi.list).toHaveBeenCalled();
    });
    expect(voided.settlementApi.handBackAssessment).not.toHaveBeenCalled();
    cleanup();

    const other = setup({
      assessment: () =>
        Promise.reject(
          new SettlementRequestError(
            409,
            "HAND_BACK_NOT_EARLY_TERMINATION",
            "The hand-back rule covers only a Lease the Customer chose to end early.",
          ),
        ),
    });
    await waitFor(() => {
      expect(other.settlementApi.handBackAssessment).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.queryByRole("status")).toBeNull();
    });
    expect(screen.queryByText(/days used/)).toBeNull();
    cleanup();

    const reader = setup({ capabilities: new Set(["leases.read"]) });
    expect(reader.invoiceApi.list).not.toHaveBeenCalled();
    cleanup();

    setup({
      assessment: () =>
        Promise.resolve({
          ...unpaid,
          action: "KEEP",
          outstanding_usd_cents: 7839,
          credit_usd_cents: 0,
        }),
    });
    await screen.findByText(
      "Invoice INV-2026-08 charges $78.39: only the days used.",
    );
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();

    // A failure of the server is said; it is not taken as "the rule does not apply".
    setup({
      assessment: () =>
        Promise.reject(new SettlementRequestError(503, null, "Unavailable")),
    });
    await screen.findByText(
      "The Rent Invoice could not be checked. Reload the page.",
    );
  });

  it("TEST-FE-2245 a refusal shows the server's words and reads the amounts again; after a lost answer the next try sends the same key", async () => {
    const answers: (() => ReturnType<SettlementApi["resolveHandBack"]>)[] = [
      () =>
        Promise.reject(new SettlementRequestError(503, null, "Unavailable")),
      () =>
        Promise.reject(
          new SettlementRequestError(
            409,
            "HAND_BACK_ASSESSMENT_CHANGED",
            "The amounts changed since you looked. Reload and try again.",
          ),
        ),
    ];
    const { settlementApi, onDone } = setup({
      resolve: () => (answers.shift() ?? (() => Promise.resolve({})))(),
    });
    const button = await screen.findByRole("button", {
      name: "Lower the Invoice to the days used",
    });
    fireEvent.click(button);
    await screen.findByRole("alert");
    expect(settlementApi.handBackAssessment).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Lower the Invoice to the days used",
      }),
    );
    await screen.findByText(
      "The amounts changed since you looked. Reload and try again.",
    );
    const keys = settlementApi.resolveHandBack.mock.calls.map(
      (call) => call[3],
    );
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    await waitFor(() => {
      expect(settlementApi.handBackAssessment).toHaveBeenCalledTimes(2);
    });
    expect(onDone).not.toHaveBeenCalled();
  });
});
