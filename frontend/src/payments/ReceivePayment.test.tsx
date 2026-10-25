import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InvoiceClientError } from "../invoiceClient";
import type { InvoicesData } from "../invoices/invoicesData";
import {
  type PayableItem,
  payProblem,
  paysOf,
  pickedTotal,
  planFor,
} from "./payFor";
import type {
  PaymentsApi,
  ReceiveInput,
  ReceiveResult,
} from "./paymentsClient";
import {
  ReceivePayment,
  centsForRiel,
  nowText,
  receivedAt,
  rielFor,
} from "./ReceivePayment";

afterEach(() => {
  cleanup();
});

const LIM = "customer-lim";
const ITEMS: PayableItem[] = [
  {
    kind: "INVOICE",
    id: "inv-old",
    invoiceId: "inv-old",
    invoiceNumber: "INV260006",
    category: "RENT",
    dueDate: "2026-10-05",
    owed: 35_300,
  },
  {
    kind: "LATE_PAYMENT_CHARGE",
    id: "charge-1",
    invoiceId: "inv-old",
    invoiceNumber: "INV260006",
    category: null,
    dueDate: "2026-10-05",
    owed: 3_530,
  },
  {
    kind: "INVOICE",
    id: "inv-new",
    invoiceId: "inv-new",
    invoiceNumber: "INV260071",
    category: "UTILITIES",
    dueDate: "2026-11-05",
    owed: 4_700,
  },
];

const DATA: InvoicesData = {
  invoices: [],
  names: new Map([
    [LIM, "Lim Sophal"],
    ["customer-dara", "Dara Kim"],
  ]),
  phones: new Map([[LIM, "012 345 678"]]),
  leaseUnits: new Map(),
  customerUnits: new Map([
    [LIM, "U204"],
    ["customer-dara", "U101"],
  ]),
  customerLeases: new Map([
    [LIM, "lease-lim"],
    ["customer-dara", "lease-dara"],
  ]),
  capabilities: [],
};

const RESULT: ReceiveResult = {
  paymentId: "payment-1",
  receiptNumber: "RCP260045",
  currency: "USD",
  receivedMinor: 40_000,
  usdCents: 40_000,
  allocations: [
    { kind: "INVOICE", invoiceNumber: "INV260006", amount: 35_300 },
    { kind: "LATE_PAYMENT_CHARGE", invoiceNumber: "INV260006", amount: 3_530 },
    { kind: "INVOICE", invoiceNumber: "INV260071", amount: 1_170 },
  ],
  left: 0,
};

function api(overrides: Partial<PaymentsApi> = {}) {
  return {
    payable: vi.fn((_property: string, customer: string) =>
      Promise.resolve(customer === LIM ? ITEMS : []),
    ),
    methods: vi.fn(() =>
      Promise.resolve([
        { id: "method-aba", code: "ABA", displayName: "ABA PAY" },
        { id: "method-cash", code: "CASH", displayName: "Cash" },
      ]),
    ),
    khrRate: vi.fn(() => Promise.resolve({ rate: 4_083 })),
    receive: vi.fn(() => Promise.resolve(RESULT)),
    ...overrides,
  } satisfies PaymentsApi;
}

function show(paymentsApi: PaymentsApi, onSaved = vi.fn()) {
  render(
    <ReceivePayment
      api={paymentsApi}
      data={DATA}
      language="en"
      onSaved={onSaved}
      propertyId="property-1"
    />,
  );
  return onSaved;
}

async function choose(customer = LIM) {
  fireEvent.change(screen.getByLabelText(/^Customer/), {
    target: { value: customer },
  });
  await screen.findByText(
    customer === LIM ? "INV260071" : /has nothing unpaid/,
  );
}

function type(id: string, value: string) {
  const field = document.getElementById(id);
  if (field === null) throw new Error(`no field ${id}`);
  fireEvent.change(field, { target: { value } });
}

function tickBox(index: number): HTMLInputElement {
  return document.querySelectorAll(".ui-pf-row input")[
    index
  ] as HTMLInputElement;
}

function rows() {
  return [...document.querySelectorAll(".ui-pf-row")].map((row) => ({
    text: row.textContent,
    ticked: row.querySelector("input")?.checked === true,
  }));
}

describe("What this money pays for", () => {
  it("TEST-FE-908 ticks the oldest Due Date first, a late-payment charge right after its own Invoice, and names what cannot be saved", () => {
    const auto = planFor(ITEMS, 40_000, null);
    expect(auto.rows.map((row) => [row.item.id, row.on, row.pays])).toEqual([
      ["inv-old", true, 35_300],
      ["charge-1", true, 3_530],
      ["inv-new", true, 1_170],
    ]);
    expect(auto.rest).toBe(0);
    expect(paysOf(auto)).toEqual({
      mode: "OLDEST_FIRST",
      targets: [
        { invoice_id: "inv-old", amount_usd_cents: 35_300 },
        { late_payment_charge_id: "charge-1", amount_usd_cents: 3_530 },
        { invoice_id: "inv-new", amount_usd_cents: 1_170 },
      ],
    });
    // Money that runs out stops before the newer Invoice; nothing is ticked before an amount.
    const short = planFor(ITEMS, 36_000, null);
    expect(short.rows.map((row) => row.on)).toEqual([true, true, false]);
    expect(paysOf(short).targets).toHaveLength(2);
    expect(planFor(ITEMS, null, null).rows.every((row) => !row.on)).toBe(true);
    // Money left after everything is a true overpayment, not an error.
    const over = planFor(ITEMS, 50_000, null);
    expect(over.rest).toBe(6_470);
    expect(payProblem(over, 50_000)).toBeNull();

    // Ticks the Customer named.
    const named = new Set(["inv-new"]);
    expect(pickedTotal(ITEMS, named)).toBe(4_700);
    const own = planFor(ITEMS, 4_700, named);
    expect(paysOf(own)).toEqual({
      mode: "NAMED",
      targets: [{ invoice_id: "inv-new", amount_usd_cents: 4_700 }],
    });
    expect(payProblem(own, 4_700)).toBeNull();
    expect(payProblem(planFor(ITEMS, 9_400, named), 9_400)).toEqual({
      kind: "more",
      rest: 4_700,
    });
    expect(payProblem(planFor(ITEMS, 100, new Set()), 100)).toEqual({
      kind: "pick",
    });
    expect(
      payProblem(
        planFor(ITEMS, 35_300, new Set(["inv-old", "charge-1"])),
        35_300,
      ),
    ).toEqual({ kind: "zero", item: ITEMS[1] });

    // Times and riel.
    expect(nowText(new Date("2026-10-25T07:05:00Z"))).toBe("25/10/2026, 14:05");
    expect(receivedAt("25/10/2026, 14:05")).toBe("2026-10-25T14:05:00+07:00");
    expect(receivedAt("31/02/2026, 14:05")).toBeNull();
    expect(receivedAt("25/10/2026 2pm")).toBeNull();
    expect(rielFor(1_001, 4_083)).toBe(40_871);
    expect(centsForRiel(40_871, 4_083)).toBe(1_001);
    expect(centsForRiel(40_872, 4_083)).toBeNull();
  });
});

describe("Receive payment", () => {
  it("TEST-FE-909 pays oldest first, confirms in a dialog, sends one command and shows the Receipt", async () => {
    const payments = api();
    const onSaved = show(payments);
    expect(screen.getByText("Choose the Customer first.")).toBeTruthy();
    await choose();
    expect(payments.payable).toHaveBeenCalledWith("property-1", LIM);
    expect(screen.getByText(/Enter the amount first/)).toBeTruthy();
    expect(rows().every((row) => !row.ticked)).toBe(true);
    expect(
      screen.getByText(/A late-payment charge is paid right after/),
    ).toBeTruthy();

    type("rp-amt", "400.00");
    expect(rows().map((row) => row.ticked)).toEqual([true, true, true]);
    expect(rows()[1]?.text).toContain("Late-payment charge");
    expect(rows()[1]?.text).toContain("on INV260006 · not an Invoice");
    expect(rows()[1]?.text).toContain("Pays $35.30");
    expect(rows()[2]?.text).toContain("Pays $11.70");
    expect(screen.getByText("All the money is used.")).toBeTruthy();
    type("rp-ref", "100245789");
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));

    const dialog = await screen.findByRole("dialog", {
      name: "Receive this payment?",
    });
    expect(within(dialog).getByText("Lim Sophal · U204")).toBeTruthy();
    expect(within(dialog).getByText("$400.00")).toBeTruthy();
    expect(
      within(dialog).getByText(/Late-payment charge on INV260006/),
    ).toBeTruthy();
    expect(within(dialog).getByText(/two separate records/)).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive payment" }),
    );

    await screen.findByText("Payment recorded");
    expect(
      screen.getByText(
        /\$400\.00 from Lim Sophal\. Receipt RCP260045 is ready\. It paid INV260006 \(\$353\.00\), Late-payment charge on INV260006 \(\$35\.30\), INV260071 \(\$11\.70\)\./,
      ),
    ).toBeTruthy();
    expect(onSaved).toHaveBeenCalled();
    const [, body, key] = vi.mocked(payments.receive).mock
      .calls[0] as unknown as [string, ReceiveInput, string];
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(body).toMatchObject({
      payer_customer_id: LIM,
      payment_method_id: "method-aba",
      evidence_reference: "100245789",
      payer_intent_memo: null,
      amount: { currency: "USD", minor_units: 40_000 },
      pays: {
        mode: "OLDEST_FIRST",
        targets: [
          { invoice_id: "inv-old", amount_usd_cents: 35_300 },
          { late_payment_charge_id: "charge-1", amount_usd_cents: 3_530 },
          { invoice_id: "inv-new", amount_usd_cents: 1_170 },
        ],
      },
    });
    expect(body.received_at).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+07:00$/,
    );
  });

  it("TEST-FE-910 a tick by hand sets the amount, sends named ticks, and money may not wait while something is owed", async () => {
    const payments = api();
    show(payments);
    await choose();
    type("rp-amt", "400.00");
    // Untick the newer Invoice: the amount becomes the ticked total.
    fireEvent.click(tickBox(2));
    expect((document.getElementById("rp-amt") as HTMLInputElement).value).toBe(
      "388.30",
    );
    expect(screen.getByText(/You changed the ticks/)).toBeTruthy();
    // Typing more afterwards keeps the ticks and leaves money while INV260071 is unpaid.
    type("rp-amt", "400.00");
    expect(
      screen.getByText("$11.70 is left. Tick another Invoice."),
    ).toBeTruthy();
    type("rp-ref", "100245789");
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    expect(
      (
        await screen.findAllByText(
          "$11.70 is left and other Invoices are still unpaid. Tick another Invoice.",
        )
      ).length,
    ).toBeGreaterThan(0);
    expect(payments.receive).not.toHaveBeenCalled();
    // Back to oldest first ticks them all again.
    fireEvent.click(
      screen.getByRole("button", { name: "Back to oldest first" }),
    );
    expect(rows().map((row) => row.ticked)).toEqual([true, true, true]);
    // Only the newer Invoice, as the Customer named it.
    for (const index of [0, 1]) fireEvent.click(tickBox(index));
    expect((document.getElementById("rp-amt") as HTMLInputElement).value).toBe(
      "47.00",
    );
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive payment" }),
    );
    await screen.findByText("Payment recorded");
    const body = (
      vi.mocked(payments.receive).mock.calls[0] as unknown as [
        string,
        ReceiveInput,
      ]
    )[1];
    expect(body.pays).toEqual({
      mode: "NAMED",
      targets: [{ invoice_id: "inv-new", amount_usd_cents: 4_700 }],
    });
  });

  it("TEST-FE-911 names each missing value, needs a reference except for cash, refuses a later time, and waits money from a Customer who owes nothing", async () => {
    const payments = api();
    show(payments);
    await waitFor(() => {
      expect(screen.getAllByRole("option", { name: "ABA PAY" })).toHaveLength(
        1,
      );
    });
    type("rp-when", "25/10/2099, 10:00");
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    const summary = await screen.findByRole("alert");
    expect(
      within(summary).getByText("Fix 4 thing(s) before recording."),
    ).toBeTruthy();
    expect(within(summary).getByText("Choose who paid.")).toBeTruthy();
    expect(
      within(summary).getByText(/Enter the amount in dollars and cents/),
    ).toBeTruthy();
    expect(within(summary).getByText(/later than now/)).toBeTruthy();
    expect(
      within(summary).getByText("Enter the transaction number or reference."),
    ).toBeTruthy();
    type("rp-when", "today");
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    expect(await screen.findAllByText(/Use day\/month\/year/)).not.toHaveLength(
      0,
    );

    // Cash has no reference field; the Customer owes nothing, so the money waits.
    fireEvent.change(screen.getByLabelText(/^Payment method/), {
      target: { value: "method-cash" },
    });
    expect(document.getElementById("rp-ref")).toBeNull();
    await choose("customer-dara");
    type("rp-amt", "194.40");
    type("rp-when", nowText(new Date(Date.now() - 3_600_000)));
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/Nothing to pay yet\. \$194\.40 waits/),
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive payment" }),
    );
    await screen.findByText("Payment recorded");
    const body = (
      vi.mocked(payments.receive).mock.calls[0] as unknown as [
        string,
        ReceiveInput,
      ]
    )[1];
    expect(body.evidence_reference).toBe("Cash received, Cash");
    expect(body.pays).toEqual({ mode: "OLDEST_FIRST", targets: [] });
  });

  it("TEST-FE-912 a change meanwhile reads the list again, and pressing again after no answer keeps the same key", async () => {
    const receive = vi
      .fn<PaymentsApi["receive"]>()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockRejectedValueOnce(
        new InvoiceClientError(409, "RECEIVE_PAYMENT_CHANGED", false),
      )
      .mockResolvedValue(RESULT);
    const payments = api({ receive });
    show(payments);
    await choose();
    type("rp-amt", "400.00");
    type("rp-ref", "100245789");
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    let dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive payment" }),
    );
    expect(await within(dialog).findByText(/No answer came back/)).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive payment" }),
    );
    expect(await screen.findByText(/Invoices changed meanwhile/)).toBeTruthy();
    expect(receive.mock.calls[0]?.[2]).toBe(receive.mock.calls[1]?.[2]);
    expect(payments.payable).toHaveBeenCalledTimes(2);
    await screen.findByText("INV260071");
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive payment" }),
    );
    await screen.findByText("Payment recorded");
  });

  it("TEST-FE-913 riel counts at the app rate and is sent with its dollar value", async () => {
    const payments = api();
    show(payments);
    await choose();
    fireEvent.click(screen.getByRole("button", { name: /Riel/ }));
    await screen.findByText(/App rate \(rounded up\): 4,083 ៛ = \$1\.00/);
    type("rp-amt", "40872");
    type("rp-ref", "100245789");
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    expect(
      (
        await screen.findAllByText(
          /40,872 ៛ is not an exact dollar amount\. Enter 40,871 ៛ \(\$10\.01\) or 40,912 ៛ \(\$10\.02\)/,
        )
      ).length,
    ).toBeGreaterThan(0);
    type("rp-amt", "40871");
    expect(screen.getByText(/Worth in US dollars: \$10\.01/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Receive payment/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("40,871 ៛ ($10.01)")).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive payment" }),
    );
    await screen.findByText("Payment recorded");
    const body = (
      vi.mocked(payments.receive).mock.calls[0] as unknown as [
        string,
        ReceiveInput,
      ]
    )[1];
    expect(body.amount).toEqual({ currency: "KHR", minor_units: 40_871 });
    expect(body.usd_accounting_amount).toEqual({
      currency: "USD",
      minor_units: 1_001,
    });
    expect(body.pays.targets).toEqual([
      { invoice_id: "inv-old", amount_usd_cents: 1_001 },
    ]);
  });
});
