import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceResource,
} from "../invoiceClient";
import type { LateChargeCard, PaymentsApi } from "../payments/paymentsClient";
import { InvoiceDetail } from "./InvoiceDetail";
import type { InvoicesData } from "./invoicesData";

afterEach(() => {
  cleanup();
});

const usd = (cents: number) => ({
  currency: "USD" as const,
  minor_units: cents,
});

const INVOICE: InvoiceResource = {
  id: "inv-6",
  property_id: "property-1",
  customer_id: "cust-lim",
  lease_id: "lease-204",
  invoice_number: "INV260006",
  category: "RENT",
  status: "PARTIALLY_PAID",
  invoice_date: "2026-09-25",
  due_date: "2026-10-05",
  billing_period: null,
  version: 1,
  original_total: usd(45_000),
  adjusted_total: usd(45_000),
  active_application_total: usd(9_700),
  outstanding_balance: usd(35_300),
  lines: [
    {
      id: "line-1",
      sequence: 1,
      description: "Rent, October",
      category: "RENT",
      original_amount: usd(45_000),
      adjusted_amount: usd(45_000),
      outstanding_balance: usd(35_300),
      source: {},
      calculation_evidence: {},
      period: { start: "2026-10-01", end: "2026-10-31" },
    },
  ],
  adjustments: [],
  void_event: null,
  evidence: { issued_at: "2026-09-25T00:00:00Z" },
};

const DATA: InvoicesData = {
  invoices: [INVOICE],
  names: new Map([["cust-lim", "Lim Sophal"]]),
  phones: new Map(),
  leaseUnits: new Map([["lease-204", "U204"]]),
  customerUnits: new Map([["cust-lim", "U204"]]),
  customerLeases: new Map([["cust-lim", "lease-204"]]),
  capabilities: [],
};

const CARD: LateChargeCard = {
  chargeId: "charge-6",
  invoiceId: "inv-6",
  customerId: "cust-lim",
  payableAt: "2026-10-05T17:00:00Z",
  chargedAt: "2026-10-05T17:00:00Z",
  fullRate: true,
  byApp: true,
  addedBy: null,
  unpaidAtCharge: 35_300,
  rateBasisPoints: 1000,
  original: 3_530,
  now: 3_530,
  stillOwed: 2_530,
  paid: 1_000,
  changes: [],
  paidBy: [
    {
      kind: "PAYMENT",
      paymentId: "pay-31",
      receiptNumber: "RCP260031",
      amount: 1_000,
      at: "2026-10-10T03:00:00Z",
    },
  ],
};

function invoiceApi(): Pick<InvoiceApi, "get" | "issue" | "adjust" | "void"> {
  return {
    get: vi.fn(() => Promise.resolve(INVOICE)),
    issue: vi.fn(),
    adjust: vi.fn(),
    void: vi.fn(),
  };
}

function lateApi(card: LateChargeCard | null = CARD) {
  return {
    lateCharge: vi.fn<PaymentsApi["lateCharge"]>(() => Promise.resolve(card)),
    reduceLateCharge: vi.fn<PaymentsApi["reduceLateCharge"]>(() =>
      Promise.resolve(),
    ),
  };
}

function show(
  late: Pick<PaymentsApi, "lateCharge" | "reduceLateCharge">,
  capabilities: ReadonlySet<string> | null = null,
) {
  render(
    <InvoiceDetail
      api={invoiceApi()}
      capabilities={capabilities}
      data={DATA}
      invoiceId="inv-6"
      language="en"
      lateApi={late}
      onChanged={vi.fn()}
      propertyId="property-1"
      today="2026-10-25"
    />,
  );
}

function card() {
  return screen.getByRole("region", { name: "Late-payment charge" });
}

describe("V1-058 R5d late-payment card", () => {
  it("TEST-FE-923 shows what was unpaid, the charge the app added, what paid it and what is still owed; a Manager-only change is locked for Staff", async () => {
    const late = lateApi({
      ...CARD,
      now: 3_000,
      stillOwed: 2_000,
      changes: [
        {
          kind: "REDUCTION",
          previous: 3_530,
          resulting: 3_000,
          at: "2026-10-12T02:00:00Z",
          by: "Chan Sophea",
          reasonCode: "PAID_ON_TIME_RECORDED_LATE",
          whatHappened: "Paid at the desk on the 4th.",
          reason: "Paid on time but recorded late",
        },
      ],
    });
    show(late, new Set(["invoices.read", "payments.record"]));
    await screen.findByRole("region", { name: "Late-payment charge" });
    expect(late.lateCharge).toHaveBeenCalledWith("property-1", "inv-6");
    const section = card();
    // The chip and the change row.
    expect(within(section).getAllByText("Reduced")).toHaveLength(2);
    expect(
      within(section).getByText("Unpaid on 06/10/2026"),
    ).toBeInTheDocument();
    expect(
      within(section).getByText("Added by the app on 06/10/2026, 00:00."),
    ).toBeInTheDocument();
    expect(
      within(section).getByText(
        "By Chan Sophea on 12/10/2026 09:00. Paid on time but recorded late. Paid at the desk on the 4th.",
      ),
    ).toBeInTheDocument();
    expect(
      within(section).getByRole("link", { name: "RCP260031" }),
    ).toHaveAttribute("href", "#/payments/receipt%3Apay-31");
    expect(within(section).getByText("$20.00")).toBeInTheDocument();
    expect(
      within(section).getByRole("link", { name: /Receive payment/ }),
    ).toHaveAttribute("href", "#/payments/receive%3Acust-lim%3Acharge-6");
    expect(
      screen.getByText(
        "This Invoice is overdue. The app added a late-payment charge of $35.30 on 06/10/2026.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Late-payment charge reduced to $30.00 by Chan Sophea. Paid on time but recorded late",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("$10.00 paid to the late-payment charge from RCP260031"),
    ).toBeInTheDocument();

    const locked = within(section).getByRole("button", {
      name: /Reduce or waive/,
    });
    expect(locked).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(locked);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      screen.getByText("Only a Manager or the Owner can do this."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-924 Reduce or waive needs a choice, an amount between what is paid and the charge, a reason and what happened, and saves once", async () => {
    const late = lateApi();
    late.reduceLateCharge
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockResolvedValue(undefined);
    show(late);
    await screen.findByRole("region", { name: "Late-payment charge" });
    fireEvent.click(
      within(card()).getByRole("button", { name: /Reduce or waive/ }),
    );
    const dialog = screen.getByRole("dialog");
    // Something is paid, so Waive is not possible (owner, round 6).
    expect(within(dialog).getByLabelText(/^Waive/)).toBeDisabled();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save change" }),
    );
    expect(
      within(dialog).getByText("Choose Reduce or Waive."),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Choose a reason.")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Write what happened."),
    ).toBeInTheDocument();

    fireEvent.click(within(dialog).getByLabelText(/^Reduce/));
    fireEvent.change(within(dialog).getByLabelText("Reduced amount"), {
      target: { value: "5.00" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "WRONG_INVOICE" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^What happened/), {
      target: { value: "RCP260031 was recorded on the wrong Invoice." },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save change" }),
    );
    expect(
      within(dialog).getByText(
        "Enter an amount of at least $10.00 and less than $35.30.",
      ),
    ).toBeInTheDocument();
    expect(late.reduceLateCharge).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Reduced amount"), {
      target: { value: "12.50" },
    });
    expect(
      within(dialog).getByText(
        "The charge goes from $35.30 to $12.50. The Customer still owes $2.50 of it.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save change" }),
    );
    await within(dialog).findByText(/We could not tell if this was saved/);
    expect(within(dialog).getByLabelText(/^Reason/)).toBeDisabled();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save change" }),
    );
    await screen.findByText("Late-payment charge changed for INV260006.");

    expect(late.reduceLateCharge).toHaveBeenCalledTimes(2);
    const [first, second] = late.reduceLateCharge.mock.calls;
    expect(first?.slice(0, 4)).toEqual([
      "charge-6",
      1_250,
      "WRONG_INVOICE",
      "RCP260031 was recorded on the wrong Invoice.",
    ]);
    expect(second?.[4]).toBe(first?.[4]);
    await waitFor(() => {
      expect(late.lateCharge).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-926 waives an unpaid charge to $0.00; no charge shows no card; a failed read offers Retry", async () => {
    const late = lateApi({ ...CARD, paid: 0, stillOwed: 3_530, paidBy: [] });
    show(late);
    await screen.findByRole("region", { name: "Late-payment charge" });
    fireEvent.click(
      within(card()).getByRole("button", { name: /Reduce or waive/ }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText(/^Waive/));
    expect(
      within(dialog).getByText(
        "The charge on INV260006 becomes $0.00. Nothing is owed.",
      ),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "OTHER_STAFF_MISTAKE" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^What happened/), {
      target: { value: "Typed the wrong Due Date." },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save change" }),
    );
    await screen.findByText("Late-payment charge changed for INV260006.");
    expect(late.reduceLateCharge.mock.calls[0]?.slice(1, 3)).toEqual([
      0,
      "OTHER_STAFF_MISTAKE",
    ]);
    cleanup();

    show(lateApi(null));
    await screen.findByText(/It became overdue on 06\/10\/2026/);
    expect(
      screen.queryByRole("region", { name: "Late-payment charge" }),
    ).toBeNull();
    cleanup();

    const failing = {
      lateCharge: vi
        .fn<PaymentsApi["lateCharge"]>()
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValue(CARD),
      reduceLateCharge: vi.fn<PaymentsApi["reduceLateCharge"]>(),
    };
    show(failing);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await screen.findByRole("region", { name: "Late-payment charge" });
  });

  it("TEST-FE-927 names a person-made charge, an undone reduction and a late job run; a Deposit-paid charge is not offered for reduction; the chips follow the amounts", async () => {
    show(
      lateApi({
        ...CARD,
        byApp: false,
        addedBy: "Kompheak",
        fullRate: false,
        // The job ran two days late; what was unpaid was measured on 06/10.
        payableAt: "2026-10-07T20:12:00Z",
        changes: [
          {
            kind: "REDUCTION",
            previous: 3_530,
            resulting: 3_000,
            at: "2026-10-12T02:00:00Z",
            by: "Chan Sophea",
            reasonCode: null,
            whatHappened: null,
            reason: "Typed in the wrong amount",
          },
          {
            kind: "REDUCTION_REVERSAL",
            previous: 3_000,
            resulting: 3_530,
            at: "2026-10-13T02:00:00Z",
            by: "Kompheak",
            reasonCode: null,
            whatHappened: null,
            reason: "The reduction was a mistake",
          },
        ],
        paidBy: [
          {
            kind: "DEPOSIT",
            paymentId: null,
            receiptNumber: null,
            amount: 1_000,
            at: "2026-10-20T03:00:00Z",
          },
        ],
      }),
      new Set(["invoices.read", "late_payment.charge_correction"]),
    );
    const section = await screen.findByRole("region", {
      name: "Late-payment charge",
    });
    expect(
      within(section).getByText("Unpaid on 06/10/2026"),
    ).toBeInTheDocument();
    expect(within(section).getByText("Added")).toBeInTheDocument();
    expect(
      within(section).getByText("Added by Kompheak on 06/10/2026, 00:00."),
    ).toBeInTheDocument();
    expect(within(section).getByText("Reduction undone")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This Invoice is overdue. A late-payment charge of $35.30 was added on 06/10/2026.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Late-payment charge $35.30 added by Kompheak"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Late-payment charge reduction undone: back to $35.30, by Kompheak. The reduction was a mistake",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("$10.00 paid to the late-payment charge from Deposit"),
    ).toBeInTheDocument();
    expect(
      within(section).queryByRole("button", { name: /Reduce or waive/ }),
    ).toBeNull();
    expect(
      within(section).getByText(/A Deposit paid part of this charge/),
    ).toBeInTheDocument();
    // Without payments.record there is no Receive payment link.
    expect(
      within(section).queryByRole("link", { name: /Receive payment/ }),
    ).toBeNull();
    cleanup();

    show(lateApi({ ...CARD, stillOwed: 0, paid: 3_530 }));
    expect(
      within(
        await screen.findByRole("region", { name: "Late-payment charge" }),
      ).getAllByText("Paid")[0],
    ).toHaveClass("ui-chip");
    cleanup();

    show(lateApi({ ...CARD, now: 0, stillOwed: 0, paid: 0, paidBy: [] }));
    const waived = await screen.findByRole("region", {
      name: "Late-payment charge",
    });
    expect(within(waived).getAllByText("Waived")[0]).toHaveClass("ui-chip");
    expect(
      within(waived).queryByRole("button", { name: /Reduce or waive/ }),
    ).toBeNull();
  });
});
