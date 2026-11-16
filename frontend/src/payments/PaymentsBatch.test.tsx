// UI v81 module batch 2 (Payments, owner 12/11/2026 07:41 "if all pass, start payment"): Receive
// payment and the Receipt page are on the shared page layout, with the side column of design
// v81 (the payer's Customer card; "Exchange rate for riel"). TEST-FE-2128 to 2134. Layout and
// display only: what the form checks and sends is covered by ReceivePayment.test.tsx.

import { readFileSync } from "node:fs";

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CustomerApi, CustomerDetail } from "../customerClient";
import type { CustomerLedgerApi, LedgerReply } from "../customerLedgerClient";
import type { InvoicesData } from "../invoices/invoicesData";
import type { LeaseResource } from "../leaseClient";
import { FormLayout } from "../shell/layouts";
import { PayerCard, type PayerCardReads } from "./PayerCard";
import type { PayableItem } from "./payFor";
import {
  createPaymentsApi,
  type PaymentsApi,
  type ReceiptView,
} from "./paymentsClient";
import { ReceiptPage } from "./ReceiptPage";
import { ReceivePayment, rielFor } from "./ReceivePayment";
import { markedUp, percentOf, RielRateCard, rielProduct } from "./RielRateCard";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const LIM = "customer-lim";
const DARA = "customer-dara";
const GUEST = "customer-guest";

const lease = (overrides: Partial<LeaseResource>): LeaseResource =>
  ({
    lease_id: "lease-lim",
    status: "SIGNED",
    end_date: null,
    predecessor_lease_id: null,
    ...overrides,
  }) as LeaseResource;

const DATA: InvoicesData = {
  invoices: [],
  names: new Map([
    [LIM, "Lim Sophal"],
    [DARA, "Dara Kim"],
    [GUEST, "Hun Sovann"],
  ]),
  phones: new Map(),
  leaseUnits: new Map(),
  customerUnits: new Map([
    [LIM, "U204"],
    [DARA, "U101"],
    [GUEST, "U402"],
  ]),
  customerLeases: new Map([
    [LIM, "lease-lim"],
    [DARA, "lease-dara"],
  ]),
  leases: [
    lease({ lease_id: "lease-lim" }),
    // Ends within the month after today: "Ending soon".
    lease({ lease_id: "lease-dara", end_date: "2026-11-20" }),
  ],
  capabilities: [],
};

const ITEMS: PayableItem[] = [
  {
    kind: "INVOICE",
    id: "inv-old",
    invoiceId: "inv-old",
    invoiceNumber: "INV260006",
    category: "RENT",
    dueDate: "2026-10-05",
    owed: 35_000,
  },
  {
    kind: "LATE_PAYMENT_CHARGE",
    id: "charge-1",
    invoiceId: "inv-old",
    invoiceNumber: "INV260006",
    category: null,
    dueDate: "2026-10-05",
    owed: 3_500,
  },
];

function reads(overrides: Partial<PayerCardReads> = {}) {
  const get = vi.fn<CustomerApi["get"]>((id) =>
    Promise.resolve({
      customer_id: id,
      legal_name: DATA.names.get(id) ?? "",
      phone_number: "012 345 678",
      active: true,
    } as CustomerDetail),
  );
  const read = vi.fn<CustomerLedgerApi["read"]>().mockResolvedValue({
    section: "history",
    items: [],
    position: { credit_usd_cents: "2500", total_owed_usd_cents: "38500" },
  } as unknown as LedgerReply);
  const customerPaidOnTime = vi
    .fn()
    .mockResolvedValue({ on_time: 9, invoice_count: 11 });
  const card: PayerCardReads = {
    customerApi: { get },
    ledgerApi: { read },
    actorId: "actor-1",
    reports: { customerPaidOnTime },
    mayCustomers: true,
    mayInvoices: true,
    ...overrides,
  };
  return { card, get, read, customerPaidOnTime };
}

function paymentsApi(overrides: Partial<PaymentsApi> = {}): PaymentsApi {
  return {
    payable: vi.fn((_property: string, customer: string) =>
      Promise.resolve(customer === LIM ? ITEMS : []),
    ),
    methods: vi.fn(() =>
      Promise.resolve([
        { id: "method-cash", code: "CASH", displayName: "Cash" },
      ]),
    ),
    khrRate: vi.fn(() => Promise.resolve(null)),
    receive: vi.fn(() => Promise.reject(new Error("not used"))),
    confirm: vi.fn(() => Promise.reject(new Error("not used"))),
    summary: vi.fn(() => Promise.reject(new Error("not used"))),
    receipt: vi.fn(() => Promise.reject(new Error("not used"))),
    reprint: vi.fn(() => Promise.resolve()),
    lateCharge: vi.fn(() => Promise.resolve(null)),
    reduceLateCharge: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
}

const RECEIPT: ReceiptView = {
  paymentId: "p-1",
  receiptId: "r-1",
  receiptNumber: "RCP260045",
  status: "RECEIVED",
  customerId: LIM,
  receivedAt: "2026-11-12T03:38:00+00:00",
  currency: "USD",
  receivedMinor: 73_567,
  usdCents: 73_567,
  rate: null,
  methodName: "Cash",
  methodCode: "CASH",
  reference: null,
  payerNote: null,
  receivedBy: "Chan Sophea",
  left: 0,
  lines: [
    {
      kind: "INVOICE",
      invoiceId: "inv-20",
      invoiceNumber: "INV260020",
      category: "RENT",
      dueDate: "2026-11-17",
      depositType: null,
      amount: 33_567,
    },
    {
      kind: "DEPOSIT",
      invoiceId: null,
      invoiceNumber: null,
      category: null,
      dueDate: null,
      depositType: "SECURITY",
      amount: 40_000,
    },
  ],
  reprints: [],
  reprintCount: 0,
} as ReceiptView;

describe("UI v81 module batch 2: Receive payment on the shared page layout", () => {
  it("TEST-FE-2128 Receive payment has Back to Payments on top, the title as the page's heading and one form named by it; the payer's Customer card and the riel rate card sit beside the form, and the Customer card comes only with a chosen Customer", async () => {
    const { card, get } = reads();
    render(
      <ReceivePayment
        api={paymentsApi()}
        data={DATA}
        language="en"
        now={new Date("2026-11-12T03:00:00Z")}
        onSaved={vi.fn()}
        payerCard={card}
        propertyId="property-1"
      />,
    );
    // The Back link is the first thing of the page head, above the title.
    const head = document.querySelector("header.ui-pagehead");
    const back = screen.getByRole("button", { name: "Back to Payments" });
    expect(head?.firstElementChild).toBe(back);
    expect(
      screen.getByRole("heading", { level: 1, name: "Receive payment" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/^Record money only after it has arrived/),
    ).toHaveClass("ui-pagehead-sub");

    // One form, named as the page; the fields card on the left and the side column on the right.
    const form = screen.getByRole("form", { name: "Receive payment" });
    expect(form).toHaveClass("ui-formlayout");
    const side = form.querySelector(".ui-formlayout-side");
    expect(side).not.toBeNull();
    const rate = screen.getByRole("heading", {
      level: 2,
      name: "Exchange rate for riel",
    });
    expect(side).toContainElement(rate);
    // The fields sit two per row (FieldGrid); the buttons are inside the form.
    expect(form.querySelector(".ui-fields")).toContainElement(
      screen.getByRole("button", { name: "Receive payment" }),
    );

    // No Customer yet: no Customer card, and nothing was read for it.
    expect(screen.queryByRole("heading", { name: "Customer" })).toBeNull();
    expect(get).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/^Customer/), {
      target: { value: LIM },
    });
    const title = await screen.findByRole("heading", {
      level: 2,
      name: "Customer",
    });
    expect(side).toContainElement(title);
    // The Customer card comes first in the side column, as in the design.
    expect(side?.firstElementChild).toContainElement(title);
    const cardBox = title.closest("section");
    if (cardBox === null) throw new Error("no Customer card");
    const inCard = within(cardBox);
    expect(await inCard.findByText("012 345 678")).toBeInTheDocument();
    expect(inCard.getByText("Lim Sophal")).toBeInTheDocument();
    expect(inCard.getByText("Lease active")).toBeInTheDocument();
    expect(inCard.getByText("Primary Tenant · U204")).toBeInTheDocument();
    expect(await inCard.findByText("9 of 11 Invoices")).toBeInTheDocument();
    expect(await inCard.findByText("$25.00")).toBeInTheDocument();
    expect(inCard.getByText("$385.00")).toBeInTheDocument();
    expect(inCard.getByRole("link", { name: "Open Customer" })).toHaveAttribute(
      "href",
      `#/customers/${LIM}`,
    );
    expect(get).toHaveBeenCalledWith(LIM);
  });

  it("TEST-FE-2128 without the Customer card's reads (an older caller) the form still shows the riel rate card and no Customer card", async () => {
    render(
      <ReceivePayment
        api={paymentsApi()}
        data={DATA}
        initialCustomer={LIM}
        language="en"
        onSaved={vi.fn()}
        propertyId="property-1"
      />,
    );
    await screen.findAllByText(/INV260006/);
    expect(
      screen.getByRole("heading", { name: "Exchange rate for riel" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Customer" })).toBeNull();
  });
});

describe('UI v81 module batch 2: the "Exchange rate for riel" card', () => {
  it("TEST-FE-2129 with a rate the card shows the published rate with its time, the server's markup, the app rate, the typed amount in riel and what each unpaid item costs in riel, with the form's own rounding", () => {
    render(
      <RielRateCard
        items={ITEMS}
        language="en"
        rate={{
          rate: 4_113,
          reference: "4092.000000",
          at: "2026-11-12T01:00:00Z",
          markupBp: 50,
        }}
        toRiel={rielFor}
        typedCents={35_000}
        typedRiel={null}
        when="12/11/2026, 08:00"
      />,
    );
    const card = screen
      .getByRole("heading", { level: 2, name: "Exchange rate for riel" })
      .closest("section");
    if (card === null) throw new Error("no rate card");
    const lines = [...card.querySelectorAll(".ui-well .line")].map(
      (line) => line.textContent,
    );
    expect(lines).toEqual([
      "ABA sell rateAutomatic, 12/11/2026, 08:004,092 ៛",
      "Plus 0.5%4,112.46",
      "App rate (rounded up)4,113 ៛ = $1.00",
      "In riel at this rate1,439,550 ៛",
    ]);
    // What each unpaid item costs in riel: the same rounding as the form (rielFor).
    expect(
      [...card.querySelectorAll(".ui-fxpay li")].map((row) => row.textContent),
    ).toEqual([
      `To pay $350.00 in riel · INV260006${rielFor(35_000, 4_113).toLocaleString("en-US")} ៛$350.00 × 4,113 ៛ = 1,439,550 ៛`,
      `To pay $35.00 in riel · Late-payment charge on INV260006${rielFor(3_500, 4_113).toLocaleString("en-US")} ៛$35.00 × 4,113 ៛ = 143,955 ៛`,
    ]);
    // An amount that is not whole riel says that it was rounded up.
    expect(rielProduct(4_480, 4_113)).toEqual({
      text: "184,262.4",
      whole: false,
    });
    expect(rielFor(4_480, 4_113)).toBe(184_263);
    expect(rielProduct(35_300, 4_113)).toEqual({
      text: "1,451,889",
      whole: true,
    });
    expect(rielProduct(1, 4_113)).toEqual({ text: "41.13", whole: false });
    expect(rielProduct(5, 4_101)).toEqual({ text: "205.05", whole: false });
    expect(
      within(card).getByText(/The app works these out\. Nobody can change/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2144 with no markup (DL-228, a rate saved after PR #35) there is no Plus line: the ABA sell rate, then the app rate", () => {
    render(
      <RielRateCard
        items={[]}
        language="en"
        rate={{ rate: 4_092, reference: "4091.200000", markupBp: 0 }}
        toRiel={rielFor}
        typedCents={null}
        typedRiel={null}
        when={null}
      />,
    );
    expect(
      [...document.querySelectorAll(".ui-well .line")].map(
        (line) => line.textContent,
      ),
    ).toEqual([
      "ABA sell rate4,091.2 ៛",
      "App rate (rounded up)4,092 ៛ = $1.00",
    ]);
    expect(screen.queryByText(/^Plus /)).toBeNull();
  });

  it("TEST-FE-2129 a payment typed in riel shows its worth in US dollars; a server that names no published rate or no markup shows the app rate alone; the markup is the server's own number", () => {
    const { rerender } = render(
      <RielRateCard
        items={[]}
        language="en"
        rate={{ rate: 4_113, reference: "4092.000000", markupBp: 50 }}
        toRiel={rielFor}
        typedCents={null}
        typedRiel={{ riel: 1_439_550, cents: 35_000 }}
        when={null}
      />,
    );
    const lines = () =>
      [...document.querySelectorAll(".ui-well .line")].map(
        (line) => line.textContent,
      );
    expect(lines()).toEqual([
      "ABA sell rate4,092 ៛",
      "Plus 0.5%4,112.46",
      "App rate (rounded up)4,113 ៛ = $1.00",
      "Worth in US dollars$350.00",
    ]);
    expect(document.querySelector(".ui-fxpay")).toBeNull();

    // Riel that is not an exact dollar value: a dash, never a guessed amount.
    rerender(
      <RielRateCard
        items={[]}
        language="en"
        rate={{ rate: 4_113 }}
        toRiel={rielFor}
        typedCents={null}
        typedRiel={{ riel: 1_000, cents: null }}
        when={null}
      />,
    );
    expect(lines()).toEqual([
      "App rate (rounded up)4,113 ៛ = $1.00",
      "Worth in US dollars—",
    ]);

    // The published rate without the markup: no "Plus" line is made up.
    rerender(
      <RielRateCard
        items={[]}
        language="en"
        rate={{ rate: 4_113, reference: "4092.000000" }}
        toRiel={rielFor}
        typedCents={null}
        typedRiel={null}
        when={null}
      />,
    );
    expect(lines()).toEqual([
      "ABA sell rate4,092 ៛",
      "App rate (rounded up)4,113 ៛ = $1.00",
    ]);

    // Another markup from the server is shown as the server gives it.
    expect(markedUp("4092.000000", 50)).toBe("4,112.46");
    expect(markedUp("4092.000000", 100)).toBe("4,132.92");
    expect(markedUp("4100", 0)).toBe("4,100");
    expect(markedUp("4092.5", 50)).toBe("4,112.963");
    expect(markedUp("not a rate", 50)).toBeNull();
    expect(markedUp("4092.000000", -1)).toBeNull();
    expect(markedUp("4092.000000", 0.5)).toBeNull();
    expect(percentOf(50)).toBe("0.5");
    expect(percentOf(100)).toBe("1");
    expect(percentOf(125)).toBe("1.25");
  });

  it("TEST-FE-2130 while the rate is read the card says so; when the server has no rate the card says Not available and to record in US dollars, and shows no riel amounts", () => {
    const { rerender } = render(
      <RielRateCard
        items={ITEMS}
        language="en"
        rate={undefined}
        toRiel={rielFor}
        typedCents={35_000}
        typedRiel={null}
        when={null}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    expect(document.querySelector(".ui-well")).toBeNull();

    rerender(
      <RielRateCard
        items={ITEMS}
        language="en"
        rate={null}
        toRiel={rielFor}
        typedCents={35_000}
        typedRiel={null}
        when={null}
      />,
    );
    expect(document.querySelector(".ui-well .line")?.textContent).toBe(
      "App rate (rounded up)Not available",
    );
    expect(
      screen.getByText(/^Today's riel rate is not available yet/),
    ).toBeInTheDocument();
    expect(document.querySelector(".ui-fxpay")).toBeNull();
    expect(document.body.textContent).not.toContain("៛");
  });

  it("TEST-FE-2131 the client reads the app rate with the published rate, its time and the markup when the server names them, the app rate alone when it does not, and no rate when none is available", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=payments-token",
    });
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    const answer = (data: unknown) =>
      fetchMock.mockResolvedValueOnce(
        new Response(JSON.stringify({ data }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    const client = createPaymentsApi();

    answer({
      status: "available",
      system_rate_khr_per_usd: 4_113,
      reference_rate_khr_per_usd: "4092.000000",
      applicable_at: "2026-11-12T01:00:00Z",
      markup_basis_points: 50,
    });
    await expect(client.khrRate("property-1")).resolves.toEqual({
      rate: 4_113,
      reference: "4092.000000",
      at: "2026-11-12T01:00:00Z",
      markupBp: 50,
    });
    // A preview of one dollar: nothing is saved, so no key is sent.
    const [path, init] = fetchMock.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/properties/property-1/payments/khr-preview");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ usd_amount_cents: 100 }));
    expect(
      (init?.headers as Record<string, string>)["Idempotency-Key"],
    ).toBeUndefined();

    answer({ status: "available", system_rate_khr_per_usd: 4_113 });
    await expect(client.khrRate("property-1")).resolves.toEqual({
      rate: 4_113,
    });

    // A markup that is not a whole number of hundredths of a percent is left out, not guessed.
    answer({
      status: "available",
      system_rate_khr_per_usd: 4_113,
      reference_rate_khr_per_usd: "4092.000000",
      markup_basis_points: "50",
    });
    await expect(client.khrRate("property-1")).resolves.toEqual({
      rate: 4_113,
      reference: "4092.000000",
    });

    answer({ status: "unavailable" });
    await expect(client.khrRate("property-1")).resolves.toBeNull();
  });
});

describe("UI v81 module batch 2: the payer's Customer card", () => {
  it("TEST-FE-2132 the card names the payer's Lease status and Unit from their newest signed Lease; a payer without a Lease shows the Unit alone and no status; a deactivated Customer says so instead", async () => {
    const { card } = reads();
    const { rerender } = render(
      <PayerCard
        customerId={DARA}
        data={DATA}
        headingId="payer"
        language="en"
        propertyId="property-1"
        reads={card}
        today="2026-11-12"
      />,
    );
    expect(await screen.findByText("012 345 678")).toBeInTheDocument();
    expect(screen.getByText("Dara Kim")).toBeInTheDocument();
    expect(screen.getByText("Primary Tenant · U101")).toBeInTheDocument();
    // The Lease ends on 20/11/2026: the chip is the Lease list's own.
    expect(screen.getByText("Ending soon")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Customer" })).toHaveAttribute(
      "id",
      "payer",
    );

    // A short-stay guest: a Unit, no Lease.
    rerender(
      <PayerCard
        customerId={GUEST}
        data={DATA}
        headingId="payer"
        language="en"
        propertyId="property-1"
        reads={card}
        today="2026-11-12"
      />,
    );
    expect(await screen.findByText("Hun Sovann")).toBeInTheDocument();
    expect(screen.getByText("U402")).toBeInTheDocument();
    expect(screen.queryByText(/Primary Tenant/)).toBeNull();
    expect(screen.queryByText(/Lease active|Ending soon/)).toBeNull();

    // A deactivated Customer: the card says so in place of the Lease status.
    const off = reads();
    off.get.mockResolvedValue({
      customer_id: LIM,
      legal_name: "Lim Sophal",
      phone_number: null,
      active: false,
    } as CustomerDetail);
    rerender(
      <PayerCard
        customerId={LIM}
        data={DATA}
        headingId="payer"
        language="en"
        propertyId="property-1"
        reads={off.card}
        today="2026-11-12"
      />,
    );
    expect(await screen.findByText("Deactivated")).toBeInTheDocument();
    expect(screen.queryByText("Lease active")).toBeNull();

    // Before the names are read the card still stands, with a dash for the name.
    rerender(
      <PayerCard
        customerId="customer-unknown"
        data={null}
        headingId="payer"
        language="en"
        propertyId="property-1"
        reads={reads({ mayCustomers: false }).card}
        today="2026-11-12"
      />,
    );
    expect(screen.getByText("—", { selector: ".ui-who-name" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open Customer" })).toBeNull();
  });
});

describe("UI v81 module batch 2: the Receipt page on the shared page layout", () => {
  it('TEST-FE-2133 the Receipt page has Back to Payments on top, the Receipt number as the page\'s heading with its status and a one-line summary, the print buttons on the right, the sheet on the left and "Paid for", the Customer card and "Reprints" beside it; an Invoice line names its Due date', async () => {
    const { card } = reads();
    render(
      <ReceiptPage
        api={{
          receipt: vi.fn<PaymentsApi["receipt"]>(() =>
            Promise.resolve(RECEIPT),
          ),
          reprint: vi.fn<PaymentsApi["reprint"]>(() => Promise.resolve()),
        }}
        data={DATA}
        language="en"
        mayReprint
        namesFailed={false}
        onRetryNames={() => undefined}
        payerCard={card}
        paymentId="p-1"
        propertyId="property-1"
      />,
    );
    // While the Receipt is read the page already has its head with the Back link.
    expect(
      screen.getByRole("heading", { level: 1, name: "Receipt" }),
    ).toBeInTheDocument();
    const title = await screen.findByRole("heading", {
      level: 1,
      name: "Receipt RCP260045",
    });
    const head = title.closest("header");
    if (head === null) throw new Error("no page head");
    expect(head.firstElementChild).toBe(
      screen.getByRole("button", { name: "Back to Payments" }),
    );
    expect(title).toHaveClass("ui-num");
    expect(within(head).getByText("Matched")).toBeInTheDocument();
    expect(within(head).getByText("Lim Sophal · U204 · $735.67")).toHaveClass(
      "ui-pagehead-sub",
    );
    const actions = head.querySelector(".ui-pagehead-actions");
    expect(actions).toContainElement(
      screen.getByRole("button", { name: "Print Receipt" }),
    );
    expect(actions).toContainElement(
      screen.getByRole("button", { name: "Reprint" }),
    );

    // The sheet on the left; the side cards in the design's order, each with a level 2 title.
    const layout = document.querySelector(".ui-detail");
    const sheet = document.querySelector<HTMLElement>(".ui-sheetwrap");
    const side = layout?.querySelector<HTMLElement>(".ui-detail-side");
    if (sheet === null || side === null || side === undefined)
      throw new Error("no sheet or no side column");
    expect(layout?.firstElementChild).toContainElement(sheet);
    expect([...side.querySelectorAll("h2")].map((h) => h.textContent)).toEqual([
      "Paid for",
      "Customer",
      "Reprints",
    ]);
    expect(await within(side).findByText("012 345 678")).toBeInTheDocument();
    expect(within(side).getByText("Primary Tenant · U204")).toBeInTheDocument();

    // An Invoice line says what its date is; the Invoice number opens the Invoice.
    const paidFor = screen
      .getByRole("heading", { level: 2, name: "Paid for" })
      .closest("section");
    if (paidFor === null) throw new Error("no Paid for card");
    expect(paidFor.textContent).toContain("Due date 17/11/2026");
    expect(
      within(paidFor).getByRole("link", { name: "INV260020" }),
    ).toHaveAttribute("href", "#/invoices/inv%3Ainv-20");
    expect(within(side).getByText("Not reprinted.")).toHaveClass("ui-tight");
  });

  it("TEST-FE-2133 without the Customer card's reads the Receipt page shows Paid for and Reprints only; a Receipt that cannot be found keeps the Back link", async () => {
    const { rerender } = render(
      <ReceiptPage
        api={{
          receipt: vi.fn<PaymentsApi["receipt"]>(() =>
            Promise.resolve(RECEIPT),
          ),
          reprint: vi.fn<PaymentsApi["reprint"]>(() => Promise.resolve()),
        }}
        data={DATA}
        language="en"
        mayReprint={false}
        namesFailed={false}
        onRetryNames={() => undefined}
        paymentId="p-1"
        propertyId="property-1"
      />,
    );
    await screen.findByRole("heading", { name: "Receipt RCP260045" });
    expect(
      [...document.querySelectorAll(".ui-detail-side h2")].map(
        (h) => h.textContent,
      ),
    ).toEqual(["Paid for", "Reprints"]);
    expect(screen.queryByRole("button", { name: "Reprint" })).toBeNull();

    rerender(
      <ReceiptPage
        api={{
          receipt: vi.fn<PaymentsApi["receipt"]>(() =>
            Promise.reject(new Error("offline")),
          ),
          reprint: vi.fn<PaymentsApi["reprint"]>(() => Promise.resolve()),
        }}
        data={DATA}
        key="again"
        language="en"
        mayReprint={false}
        namesFailed={false}
        onRetryNames={() => undefined}
        paymentId="p-2"
        propertyId="property-1"
      />,
    );
    expect(
      await screen.findByRole("button", { name: "Retry" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Back to Payments" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Receipt" }),
    ).toBeInTheDocument();
  });
});

describe("UI v81 module batch 2: what a person presses is 44 px tall on every screen", () => {
  const css = readFileSync("src/shell/screens.css", "utf8");
  /** The declarations of every rule written as "<selector> {". */
  const rules = (selector: string): string[] => {
    const found: string[] = [];
    for (
      let at = css.indexOf(`${selector} {`);
      at >= 0;
      at = css.indexOf(`${selector} {`, at + 1)
    ) {
      // Only a selector at the start of a line (or after a list's comma) counts.
      const before = css.slice(Math.max(0, at - 1), at);
      if (before !== "" && !/\s/.test(before)) continue;
      const open = css.indexOf("{", at);
      found.push(css.slice(open + 1, css.indexOf("}", open)));
    }
    return found;
  };

  it("TEST-FE-2134 a switch button is 44 px tall on a computer and on a phone, and the tighter look of a short desktop screen makes no button, switch, tab or number card shorter than 44 px", () => {
    const seg = rules(".ui-seg button");
    expect(seg.length).toBeGreaterThanOrEqual(2);
    for (const block of seg) {
      const height = /min-height:\s*(\d+)px/.exec(block);
      if (height !== null) expect(Number(height[1])).toBeGreaterThanOrEqual(44);
    }
    expect(seg.some((block) => block.includes("min-height: 44px"))).toBe(true);

    // Every rule of the short look: no pressable thing is given a height under 44 px.
    const short = [
      ...css.matchAll(/body\.ui-fit\.ui-short ([^{]+)\{([^}]*)\}/g),
    ];
    expect(short.length).toBeGreaterThan(10);
    for (const [, selector = "", block = ""] of short) {
      const height = /min-height:\s*(\d+)px/.exec(block);
      if (height === null) continue;
      expect(
        Number(height[1]),
        `min-height of "${selector.trim()}"`,
      ).toBeGreaterThanOrEqual(44);
    }
    expect(
      rules("body.ui-fit.ui-short .ui-kpis:not(.ui-tasks) .ui-kpi").some(
        (block) => block.includes("min-height: 44px"),
      ),
    ).toBe(true);

    // A document number in a list (the Receipt's "Paid for") is pressed on a 44 px area.
    const inText = css.slice(
      css.indexOf(".shell-view a.ui-no,"),
      css.indexOf("}", css.indexOf(".shell-view a.ui-no,")),
    );
    expect(inText).toContain(".shell-view .ui-apps a.ui-num");
    expect(inText).toContain("padding: 13px 6px;");
    // A paragraph inside a card adds no margin of its own to the card's spacing.
    expect(rules(".ui-card > p.ui-tight")).toEqual(["\n  margin: 0;\n"]);
  });

  it("TEST-FE-2134 a form page can name its form for a screen reader", () => {
    render(
      <FormLayout
        label="Receive payment"
        main={<p>fields</p>}
        onSubmit={(event) => {
          event.preventDefault();
        }}
        side={<p>side</p>}
      />,
    );
    expect(screen.getByRole("form", { name: "Receive payment" })).toHaveClass(
      "ui-formlayout",
    );
    cleanup();
    render(
      <FormLayout
        main={<p>fields</p>}
        onSubmit={(event) => {
          event.preventDefault();
        }}
        side={<p>side</p>}
      />,
    );
    expect(document.querySelector("form")).not.toHaveAttribute("aria-label");
  });
});
