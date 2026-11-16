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
  createPaymentsApi,
  type PaymentRow,
  type PaymentsApi,
  type PaymentsSummary,
  type ReceiptView,
} from "./paymentsClient";
import { isoDay, PaymentsList, periodRange } from "./PaymentsList";
import { ReceiptPage } from "./ReceiptPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const DATA: InvoicesData = {
  invoices: [],
  names: new Map([
    ["c-lim", "Lim Sophal"],
    ["c-dara", "Dara Kim"],
  ]),
  phones: new Map(),
  leaseUnits: new Map(),
  customerUnits: new Map([
    ["c-lim", "U204"],
    ["c-dara", "U101"],
  ]),
  customerLeases: new Map(),
  capabilities: [],
};

function row(overrides: Partial<PaymentRow>): PaymentRow {
  return {
    paymentId: "p-1",
    receiptNumber: "RCP260045",
    paymentDate: "2026-10-25",
    receivedAt: "2026-10-25T07:42:00+00:00",
    customerId: "c-lim",
    methodName: "ABA PAY",
    methodCode: "ABA",
    status: "RECEIVED",
    currency: "USD",
    receivedMinor: 48_000,
    usdCents: 48_000,
    left: 0,
    refunded: 0,
    kinds: { RENT: 40_000, LATE: 4_000, SVC: 4_000 },
    ...overrides,
  };
}

const ZERO = { cents: 0, payments: 0 };

const SUMMARY: PaymentsSummary = {
  from: "2026-10-01",
  to: "2026-10-25",
  truncated: false,
  payments: 3,
  received: 100_000,
  left: 10_000,
  leftPayments: 1,
  refunded: 0,
  rielMinor: 82_260,
  rielUsd: 2_000,
  kinds: {
    RENT: { cents: 80_000, payments: 2 },
    UTIL: { cents: 2_000, payments: 1 },
    SVC: { cents: 4_000, payments: 1 },
    LATE: { cents: 4_000, payments: 1 },
    DEPOSIT: ZERO,
    SHORT_STAY: ZERO,
    PRODUCTS: ZERO,
    DAMAGE: ZERO,
    OTHER: ZERO,
    CREDIT: ZERO,
  },
  rows: [
    row({}),
    row({
      paymentId: "p-2",
      receiptNumber: "RCP260044",
      customerId: "c-dara",
      currency: "KHR",
      receivedMinor: 82_260,
      usdCents: 2_000,
      methodName: "Cash",
      kinds: { UTIL: 2_000 },
    }),
    row({
      paymentId: "p-3",
      receiptNumber: "RCP260043",
      usdCents: 50_000,
      left: 10_000,
      kinds: { RENT: 40_000 },
    }),
    row({
      paymentId: "p-4",
      receiptNumber: "RCP260042",
      status: "REVERSED",
      kinds: {},
    }),
  ],
};

function api(summary: PaymentsSummary = SUMMARY) {
  return {
    summary: vi.fn<PaymentsApi["summary"]>(() => Promise.resolve(summary)),
  } satisfies Pick<PaymentsApi, "summary">;
}

function showList(paymentsApi = api()) {
  render(
    <PaymentsList
      api={paymentsApi}
      data={DATA}
      language="en"
      mayReceive
      propertyId="property-1"
      today="2026-10-25"
    />,
  );
  return paymentsApi;
}

function receiptRows(): string[] {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map(
      (tableRow) => within(tableRow).getAllByRole("link")[0]?.textContent ?? "",
    );
}

describe("V1-058 R5c-3 Payments list", () => {
  it("TEST-FE-914 shows Total received and the category cards, the add-up line, and filters the list by a card or by money not matched yet", async () => {
    showList();
    await screen.findByText("RCP260045");

    expect(
      screen.getByRole("button", { name: /^Total received: \$1,000\.00/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", {
        name: /^Rent: \$800\.00\.$/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The category cards ($900.00) and $100.00 not matched yet add up to $1,000.00. Riel payments (82,260 ៛) count at the dollar value recorded when they were received ($20.00).",
      ),
    ).toBeInTheDocument();
    expect(receiptRows()).toEqual([
      "RCP260045",
      "RCP260044",
      "RCP260043",
      "RCP260042",
    ]);
    expect(screen.getByText("82,260 ៛")).toBeInTheDocument();
    expect(screen.getAllByText("Lim Sophal", { selector: "td" })).toHaveLength(
      3,
    );
    // Each chip shows twice in the page: in its column, and folded under the number for phones.
    expect(screen.getAllByText("Reversed")).toHaveLength(2);
    expect(screen.getAllByText("Part matched")).toHaveLength(2);
    expect(screen.getByText("1 reversed, not counted")).toBeInTheDocument();
    expect(screen.getByText("$100.00 left")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Utilities:/ }));
    expect(receiptRows()).toEqual(["RCP260044"]);
    expect(
      screen.getByText(/Showing payments with Utilities\./),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(receiptRows()).toHaveLength(4);

    fireEvent.click(screen.getByRole("button", { name: /^Not matched/ }));
    expect(receiptRows()).toEqual(["RCP260043"]);
    expect(screen.getByRole("link", { name: "RCP260043" })).toHaveAttribute(
      "href",
      "#/payments/receipt%3Ap-3",
    );
  });

  it("TEST-FE-915 reads each period from the server, and Pick dates needs two real days in order", async () => {
    expect(periodRange("today", "2026-10-25")).toEqual([
      "2026-10-25",
      "2026-10-25",
    ]);
    expect(periodRange("month", "2026-10-25")).toEqual([
      "2026-10-01",
      "2026-10-25",
    ]);
    expect(periodRange("last", "2026-03-15")).toEqual([
      "2026-02-01",
      "2026-02-28",
    ]);
    expect(periodRange("last", "2026-01-10")).toEqual([
      "2025-12-01",
      "2025-12-31",
    ]);
    expect(periodRange("all", "2026-10-25")).toEqual([
      "2024-10-25",
      "2026-10-25",
    ]);
    expect(isoDay("29/02/2028")).toBe("2028-02-29");
    expect(isoDay("31/02/2026")).toBeNull();
    expect(isoDay("2026-10-01")).toBeNull();

    const paymentsApi = showList(
      api({
        ...SUMMARY,
        rows: [],
        payments: 0,
        received: 0,
        left: 0,
        rielMinor: 0,
        kinds: {
          RENT: ZERO,
          UTIL: ZERO,
          SVC: ZERO,
          LATE: ZERO,
          DEPOSIT: ZERO,
          SHORT_STAY: ZERO,
          PRODUCTS: ZERO,
          DAMAGE: ZERO,
          OTHER: ZERO,
          CREDIT: ZERO,
        },
      }),
    );
    await screen.findByText("No payments in this period.");
    expect(paymentsApi.summary).toHaveBeenLastCalledWith(
      "property-1",
      "2026-10-01",
      "2026-10-25",
    );
    expect(
      screen.getByText("The category cards add up to $0.00."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Last month" }));
    await waitFor(() => {
      expect(paymentsApi.summary).toHaveBeenLastCalledWith(
        "property-1",
        "2026-09-01",
        "2026-09-30",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Custom range" }));
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "20/10/2026" },
    });
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "10/10/2026" },
    });
    const calls = paymentsApi.summary.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Write both dates as dd/mm/yyyy, with From on or before To.",
    );
    expect(screen.getByLabelText("From")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "24/10/2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    await waitFor(() => {
      expect(paymentsApi.summary).toHaveBeenLastCalledWith(
        "property-1",
        "2026-10-20",
        "2026-10-24",
      );
    });
    expect(paymentsApi.summary.mock.calls.length).toBeGreaterThan(calls);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("TEST-FE-916 adds refunded money to the add-up line, and a failed read offers Retry", async () => {
    showList(api({ ...SUMMARY, refunded: 5_000, received: 105_000 }));
    expect(
      await screen.findByText(
        /The category cards \(\$900\.00\), \$50\.00 refunded and \$100\.00 not matched yet add up to \$1,050\.00\./,
      ),
    ).toBeInTheDocument();
    cleanup();

    const failing = {
      summary: vi
        .fn()
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValue(SUMMARY),
    };
    render(
      <PaymentsList
        api={failing}
        data={null}
        language="en"
        mayReceive={false}
        propertyId="property-1"
        today="2026-10-25"
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await screen.findByText("RCP260045");
    expect(screen.queryByRole("link", { name: "Receive payment" })).toBeNull();
  });
});

const RECEIPT: ReceiptView = {
  paymentId: "p-1",
  receiptId: "r-1",
  receiptNumber: "RCP260045",
  status: "RECEIVED",
  customerId: "c-lim",
  receivedAt: "2026-10-25T07:42:00+00:00",
  currency: "KHR",
  receivedMinor: 2_014_330,
  usdCents: 49_000,
  rate: "4111",
  methodName: "ABA PAY",
  methodCode: "ABA",
  reference: "100245789",
  payerNote: null,
  receivedBy: "Chan Sophea",
  left: 1_000,
  lines: [
    {
      kind: "INVOICE",
      invoiceId: "inv-7",
      invoiceNumber: "INV260007",
      category: "RENT",
      dueDate: "2026-10-05",
      depositType: null,
      amount: 40_000,
    },
    {
      kind: "LATE_PAYMENT_CHARGE",
      invoiceId: "inv-7",
      invoiceNumber: "INV260007",
      category: null,
      dueDate: "2026-10-05",
      depositType: null,
      amount: 4_000,
    },
    {
      kind: "INVOICE",
      invoiceId: "inv-9",
      invoiceNumber: "INV260009",
      category: "RENT",
      dueDate: "2026-11-05",
      depositType: null,
      amount: 4_000,
    },
  ],
  reprints: [],
  reprintCount: 0,
};

function receiptApi(view: ReceiptView = RECEIPT) {
  return {
    receipt: vi.fn<PaymentsApi["receipt"]>(() => Promise.resolve(view)),
    reprint: vi.fn<PaymentsApi["reprint"]>(() => Promise.resolve()),
  } satisfies Pick<PaymentsApi, "receipt" | "reprint">;
}

function showReceipt(
  paymentsApi: Pick<PaymentsApi, "receipt" | "reprint">,
  mayReprint = true,
  data: InvoicesData | null = DATA,
  namesFailed = false,
  onRetryNames: () => void = () => undefined,
) {
  render(
    <ReceiptPage
      api={paymentsApi}
      data={data}
      language="en"
      mayReprint={mayReprint}
      namesFailed={namesFailed}
      onRetryNames={onRetryNames}
      paymentId="p-1"
      propertyId="property-1"
    />,
  );
}

describe("V1-058 R5c-3 Receipt page", () => {
  it("TEST-FE-917 prints what the payment paid line by line, an Invoice before its late-payment charge, and the money not used yet", async () => {
    const paymentsApi = receiptApi();
    showReceipt(paymentsApi);
    await screen.findByRole("heading", { name: "Receipt RCP260045" });
    expect(paymentsApi.receipt).toHaveBeenCalledWith("property-1", "p-1");

    const sheet = screen.getByRole("article");
    expect(within(sheet).getByText("Lim Sophal")).toBeInTheDocument();
    expect(within(sheet).getByText("Parking U204")).toBeInTheDocument();
    // No Payer note on the paper: the Paid for lines say what the money paid (owner, 28/10/2026).
    expect(within(sheet).queryByText("Payer note")).toBeNull();
    expect(within(sheet).queryByText("INV260007, INV260009")).toBeNull();
    expect(within(sheet).getByText("$490.00")).toBeInTheDocument();
    expect(within(sheet).getByText("2,014,330 ៛")).toBeInTheDocument();
    expect(
      within(sheet).getByText(/Rate 4,111 ៛ = \$1\.00/),
    ).toBeInTheDocument();
    expect(
      within(sheet).getByText("ABA transaction 100245789"),
    ).toBeInTheDocument();
    const paid = within(sheet)
      .getAllByRole("row")
      .slice(1)
      .map((tableRow) => tableRow.textContent);
    expect(paid).toEqual([
      "ថ្លៃឈ្នួលRentINV260007$400.00",
      "ថ្លៃពិន័យបង់យឺតLate-payment chargeon INV260007$40.00",
      "ថ្លៃឈ្នួលRentINV260009$40.00",
      "ប្រាក់មិនទាន់ប្រើNot used yetCredit or refund, as the Customer chooses$10.00",
    ]);
    expect(within(sheet).queryByText(/REPRINT/)).toBeNull();

    expect(
      screen.getAllByRole("link", { name: "INV260007" })[0],
    ).toHaveAttribute("href", "#/invoices/inv%3Ainv-7");
    expect(
      screen.getByText(
        "Left over: $10.00. Ask the Customer: keep it as Credit, or refund it.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Not reprinted.")).toBeInTheDocument();
    expect(screen.getByText("Part matched")).toBeInTheDocument();
  });

  it("TEST-FE-918 a reprint needs a reason, keeps one key for one reason, records it and prints a copy marked REPRINT", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const paymentsApi = receiptApi();
    paymentsApi.reprint
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockResolvedValue(undefined);
    showReceipt(paymentsApi);
    fireEvent.click(await screen.findByRole("button", { name: "Reprint" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(
      "The copy keeps number RCP260045 and is marked REPRINT. It does not record new money.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Reprint" }));
    expect(within(dialog).getByText("Choose a reason.")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "reason_other" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reprint" }));
    expect(
      within(dialog).getByText("Write what happened when the reason is Other."),
    ).toBeInTheDocument();
    expect(paymentsApi.reprint).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText(/^More detail/), {
      target: { value: "Copy for the bank" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reprint" }));
    await within(dialog).findByText(
      "No answer came back, so the reprint may already be recorded. Press Reprint again: it records once.",
    );
    // The reason cannot change after a press with no answer, so the next press is the same record.
    expect(within(dialog).getByLabelText(/^Reason/)).toBeDisabled();
    expect(within(dialog).getByLabelText(/^More detail/)).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Reprint" }));
    await screen.findByText("Reprint recorded. Print the copy now.");

    expect(paymentsApi.reprint).toHaveBeenCalledTimes(2);
    const [first, second] = paymentsApi.reprint.mock.calls;
    expect(first?.[0]).toBe("r-1");
    expect(first?.[1]).toBe("Other: Copy for the bank");
    expect(second?.[2]).toBe(first?.[2]);
    expect(paymentsApi.receipt).toHaveBeenCalledTimes(2);
    expect(
      within(screen.getByRole("article")).getByText(/REPRINT/),
    ).toBeInTheDocument();
    // The page prints in an effect after it shows the copy marked REPRINT. On a busy machine the
    // message can be on screen a moment before that effect has run.
    await waitFor(() => {
      expect(print).toHaveBeenCalled();
    });
  });

  it("TEST-FE-919 a missing payment is named, a reversed one is stamped, and Reprint shows only to a person who may reprint", async () => {
    showReceipt({
      receipt: vi.fn(() =>
        Promise.reject(new InvoiceClientError(404, "NOT_FOUND", false)),
      ),
      reprint: vi.fn(),
    });
    await screen.findByText(
      "This payment was not found. It may belong to another Property.",
    );
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();

    showReceipt(
      receiptApi({ ...RECEIPT, status: "REVERSED", left: 0, lines: [] }),
      false,
    );
    await screen.findByText(
      "This payment was reversed. The Receipt stays with its number; the money pays nothing.",
    );
    expect(
      within(screen.getByRole("article")).getByText(/REVERSED/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Not matched to an Invoice yet."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reprint" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Print Receipt" }),
    ).toBeInTheDocument();
  });
});

describe("V1-058 R5c-3 review round 1", () => {
  it("TEST-FE-920 the add-up line warns when the cards do not add up, and the Not matched filter names why the list is empty", async () => {
    showList(api({ ...SUMMARY, received: 120_000 }));
    expect(
      await screen.findByText(
        /The category cards \(\$900\.00\), \$0\.00 refunded and \$100\.00 not matched yet add up to \$1,000\.00, not \$1,200\.00\. Tell the Owner\./,
      ),
    ).toBeInTheDocument();
    cleanup();

    showList(api({ ...SUMMARY, left: 0, rows: [row({})], received: 90_000 }));
    await screen.findByText("RCP260045");
    fireEvent.click(screen.getByRole("button", { name: /^Not matched/ }));
    expect(
      screen.getByText("No payment in this list is waiting to be matched."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-921 once reprinted, Print Receipt prints a copy marked REPRINT on A5, and each new reprint prints again", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {
      // The A5 size is in the page while it prints.
      expect(document.head.textContent).toContain("size: A5");
    });
    const paymentsApi = receiptApi({
      ...RECEIPT,
      reprints: [
        {
          at: "2026-10-20T03:00:00+00:00",
          by: "Chan Sophea",
          reason: "Lost",
        },
      ],
      reprintCount: 1,
    });
    showReceipt(paymentsApi);
    await screen.findByRole("heading", { name: "Receipt RCP260045" });
    expect(
      within(screen.getByRole("article")).getByText(/REPRINT/),
    ).toHaveTextContent("20/10/2026");
    fireEvent.click(screen.getByRole("button", { name: "Print Receipt" }));
    expect(print).toHaveBeenCalledTimes(1);

    for (const round of [2, 3]) {
      fireEvent.click(screen.getByRole("button", { name: "Reprint" }));
      const dialog = screen.getByRole("dialog");
      fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
        target: { value: "reason_copy" },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Reprint" }));
      await waitFor(() => {
        expect(print).toHaveBeenCalledTimes(round);
      });
    }
    expect(paymentsApi.reprint).toHaveBeenCalledTimes(2);
  });

  it("TEST-FE-2277 Receive payment reads the Credit made from the extra money, and an older answer without it as none", async () => {
    const answer = (extra: Record<string, unknown>) =>
      new Response(
        JSON.stringify({
          data: {
            payment: {
              id: "p-2",
              received_currency: "USD",
              received_amount_minor: 45_000,
              usd_accounting_value_cents: 45_000,
            },
            receipt: { receipt_number: "RCP260046" },
            allocations: [],
            left_usd_cents: 0,
            ...extra,
          },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      );
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(answer({ credit_usd_cents: 45_000 }))
      .mockResolvedValueOnce(answer({}));
    vi.stubGlobal("fetch", fetcher);
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=payments-token",
      writable: true,
    });
    try {
      const input = {} as Parameters<
        ReturnType<typeof createPaymentsApi>["receive"]
      >[1];
      const first = await createPaymentsApi().receive(
        "property-1",
        input,
        "k-1",
      );
      expect([first.left, first.credit]).toEqual([0, 45_000]);
      const older = await createPaymentsApi().receive(
        "property-1",
        input,
        "k-2",
      );
      expect(older.credit).toBe(0);
    } finally {
      vi.unstubAllGlobals();
      Reflect.deleteProperty(document, "cookie");
    }
  });

  it("TEST-FE-922 the Receipt does not print without the Customer names, and a reversed Receipt shows no money waiting", async () => {
    const retry = vi.fn();
    showReceipt(receiptApi(), true, null, true, retry);
    await screen.findByRole("heading", { name: "Receipt RCP260045" });
    expect(
      screen.getByRole("button", { name: "Print Receipt" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reprint" })).toBeDisabled();
    expect(
      screen.getByText(
        "The Customer names could not be loaded, so the Receipt cannot print yet.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalled();

    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              data: {
                payment_id: "p-1",
                receipt_id: "r-1",
                receipt_number: "RCP260045",
                status: "REVERSED",
                customer_id: "c-lim",
                payment_date: "2026-10-25",
                received_at: "2026-10-25T07:42:00+00:00",
                received_currency: "USD",
                received_amount_minor: 1000,
                usd_cents: 1000,
                system_rate_khr_per_usd: null,
                method_name: "Cash",
                method_code: "CASH",
                reference: null,
                payer_note: null,
                received_by: "Chan Sophea",
                left_usd_cents: 1000,
                lines: [],
                reprints: [],
                reprint_count: 0,
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );
    try {
      const view = await createPaymentsApi().receipt("property-1", "p-1");
      expect(view.status).toBe("REVERSED");
      expect(view.left).toBe(0);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

// The owner saw a Receipt the list called "Move-out charges" and its page called "Short stay",
// and one the list called "Rent, Services, Deposits" and its page called "Rent".
describe("UI v81 round 9 (owner 12/11/2026) the list and the Receipt page say the same Paid for", () => {
  it("TEST-FE-1937 (owner 12/11/2026) the cards and the list name the type of the Invoice: Short stay, Products, Damage and Other charges take the place of Move-out charges", async () => {
    showList(
      api({
        ...SUMMARY,
        payments: 5,
        received: 115_780,
        kinds: {
          ...SUMMARY.kinds,
          SHORT_STAY: { cents: 5_280, payments: 1 },
          PRODUCTS: { cents: 3_000, payments: 1 },
          DAMAGE: { cents: 6_000, payments: 1 },
          OTHER: { cents: 1_500, payments: 1 },
        },
        rows: [
          row({
            paymentId: "p-8",
            receiptNumber: "RCP260020",
            usdCents: 5_280,
            receivedMinor: 5_280,
            kinds: { SHORT_STAY: 5_280 },
          }),
          row({
            paymentId: "p-9",
            receiptNumber: "RCP260018",
            kinds: { RENT: 36_000, SVC: 4_000, DEPOSIT: 8_000 },
          }),
          row({
            paymentId: "p-10",
            receiptNumber: "RCP260017",
            usdCents: 10_500,
            receivedMinor: 10_500,
            kinds: { PRODUCTS: 3_000, DAMAGE: 6_000, OTHER: 1_500 },
          }),
        ],
      }),
    );
    await screen.findByText("RCP260020");

    // The cards, in order: the four types stand where Move-out charges stood. Operations fix 1:
    // the $0.00 cards are folded until "More cards" is pressed.
    fireEvent.click(screen.getByRole("button", { name: /More cards/ }));
    expect(
      Array.from(
        document.querySelectorAll(
          ".ui-kpis-pay .ui-kpi:not(.ui-kpi-more) .ui-kpi-label",
        ),
      ).map((label) => label.textContent),
    ).toEqual([
      "Total received",
      "Rent",
      "Utilities",
      "Services",
      // Owner 12/11/2026 11:03: the card is named "Late-payment" (it was "Late-payment charges").
      "Late-payment",
      "Deposits",
      "Short stay",
      "Products",
      "Damage",
      "Other charges",
      "Customer Credit",
    ]);
    expect(screen.queryByText(/Move-out charges/)).toBeNull();
    expect(
      screen.getByRole("button", {
        name: /^Short stay: \$52\.80\.$/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /^Other charges: \$15\.00\.$/,
      }),
    ).toBeInTheDocument();
    // The cards still add up to the money received.
    expect(
      screen.getByText(
        /^The category cards \(\$1,057\.80\) and \$100\.00 not matched yet add up to \$1,157\.80\./,
      ),
    ).toBeInTheDocument();

    // The list: what each Receipt paid, in the words its page uses.
    const paidFor = (receipt: string) => {
      const line = screen.getByRole("link", { name: receipt }).closest("tr");
      if (line === null) throw new Error(`No row ${receipt}`);
      return Array.from(line.querySelectorAll(".ui-pf")).map(
        (part) => part.textContent,
      );
    };
    expect(paidFor("RCP260020")).toEqual(["Short stay"]);
    expect(paidFor("RCP260018")).toEqual(["Rent", "Services", "Deposits"]);
    expect(paidFor("RCP260017")).toEqual([
      "Products",
      "Damage",
      "Other charges",
    ]);

    // A card shows only its payments.
    fireEvent.click(screen.getByRole("button", { name: /^Short stay:/ }));
    expect(receiptRows()).toEqual(["RCP260020"]);
    expect(
      screen.getByText(/Showing payments with Short stay\./),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1938 (owner 12/11/2026) the Receipt page lists Rent and Services under a Rent Invoice, as the list names them, and nothing under an Invoice that is one thing", async () => {
    showReceipt(
      receiptApi({
        ...RECEIPT,
        currency: "USD",
        receivedMinor: 53_280,
        usdCents: 53_280,
        rate: null,
        left: 0,
        lines: [
          {
            kind: "INVOICE",
            invoiceId: "inv-7",
            invoiceNumber: "INV260007",
            category: "RENT",
            dueDate: "2026-10-05",
            depositType: null,
            amount: 40_000,
            parts: [
              { kind: "RENT", amount: 36_000 },
              { kind: "SVC", amount: 4_000 },
            ],
          },
          {
            kind: "INVOICE",
            invoiceId: "inv-19",
            invoiceNumber: "INV260019",
            category: "SHORT_STAY",
            dueDate: "2026-11-19",
            depositType: null,
            amount: 5_280,
            parts: [],
          },
          {
            kind: "DEPOSIT",
            invoiceId: null,
            invoiceNumber: null,
            category: null,
            dueDate: null,
            depositType: "SECURITY",
            amount: 8_000,
          },
        ],
      }),
    );
    await screen.findByRole("heading", { name: "Receipt RCP260045" });
    const card = screen.getByRole("heading", {
      name: "Paid for",
    }).parentElement;
    if (card === null) throw new Error("No Paid for card");
    const lines = Array.from(card.querySelectorAll(".ui-apps > li"));
    expect(lines.map((line) => line.textContent)).toEqual([
      "INV260007 · RentDue date 05/10/2026$400.00Rent$360.00Services$40.00",
      "INV260019 · Short stayDue date 19/11/2026$52.80",
      "Deposits$80.00",
    ]);
    const [rent, stay] = lines;
    expect(
      Array.from(rent?.querySelectorAll(".ui-app-parts > li") ?? []).map(
        (part) => part.textContent,
      ),
    ).toEqual(["Rent$360.00", "Services$40.00"]);
    expect(stay?.querySelector(".ui-app-parts")).toBeNull();

    // The printed Receipt is as before: one line for the Invoice, no parts.
    const sheet = screen.getByRole("article");
    expect(within(sheet).queryByText("Services")).toBeNull();
  });

  it("TEST-FE-1939 (owner 12/11/2026) the client reads the new kinds and the parts of an Invoice line; a part that is the Invoice itself gives no parts", async () => {
    const answer = (data: unknown) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(() =>
          Promise.resolve(
            new Response(JSON.stringify({ data }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          ),
        ),
      );
    };
    const card = (usd_cents: number, payments: number) => ({
      usd_cents,
      payments,
    });
    const serverSummary = (kinds: Record<string, unknown>) => ({
      property_id: "property-1",
      from: "2026-11-01",
      to: "2026-11-12",
      truncated: false,
      totals: {
        payments: 1,
        received_usd_cents: 5_280,
        left_usd_cents: 0,
        left_payments: 0,
        refunded_usd_cents: 0,
        riel_received_minor: 0,
        riel_usd_cents: 0,
        kinds,
      },
      rows: [
        {
          payment_id: "p-8",
          receipt_number: "RCP260020",
          payment_date: "2026-11-12",
          received_at: "2026-11-12T04:52:00+07:00",
          customer_id: "c-lim",
          method_name: "Cash",
          method_code: "CASH",
          status: "RECEIVED",
          received_currency: "USD",
          received_amount_minor: 5_280,
          usd_cents: 5_280,
          left_usd_cents: 0,
          refunded_usd_cents: 0,
          kinds: { SHORT_STAY: 5_280 },
        },
      ],
    });
    const kinds = {
      RENT: card(0, 0),
      UTIL: card(0, 0),
      SVC: card(0, 0),
      LATE: card(0, 0),
      DEPOSIT: card(0, 0),
      SHORT_STAY: card(5_280, 1),
      PRODUCTS: card(0, 0),
      DAMAGE: card(0, 0),
      OTHER: card(0, 0),
      CREDIT: card(0, 0),
    };
    const line = (
      invoice_type: string,
      parts: Record<string, number> | undefined,
    ) => ({
      kind: "INVOICE",
      invoice_id: "inv-1",
      invoice_number: "INV260001",
      category: "RENT",
      short_stay: null,
      invoice_type,
      due_date: "2026-11-05",
      amount_usd_cents: 40_000,
      ...(parts === undefined ? {} : { parts }),
    });
    const serverReceipt = (lines: unknown[]) => ({
      payment_id: "p-1",
      receipt_id: "r-1",
      receipt_number: "RCP260045",
      status: "RECEIVED",
      customer_id: "c-lim",
      payment_date: "2026-11-12",
      received_at: "2026-11-12T04:52:00+07:00",
      received_currency: "USD",
      received_amount_minor: 40_000,
      usd_cents: 40_000,
      system_rate_khr_per_usd: null,
      method_name: "Cash",
      method_code: "CASH",
      reference: null,
      payer_note: null,
      received_by: "Chan Sophea",
      left_usd_cents: 0,
      lines,
      reprints: [],
      reprint_count: 0,
    });
    try {
      answer(serverSummary(kinds));
      const summary = await createPaymentsApi().summary(
        "property-1",
        "2026-11-01",
        "2026-11-12",
      );
      expect(summary.kinds.SHORT_STAY).toEqual({ cents: 5_280, payments: 1 });
      expect(summary.kinds.OTHER).toEqual({ cents: 0, payments: 0 });
      expect(summary.rows[0]?.kinds).toEqual({ SHORT_STAY: 5_280 });

      // A database that still sends the old kind is not read as if it were right.
      answer(
        serverSummary(
          Object.fromEntries(
            Object.entries(kinds).map(([kind, value]) => [
              kind === "OTHER" ? "MOVEOUT" : kind,
              value,
            ]),
          ),
        ),
      );
      await expect(
        createPaymentsApi().summary("property-1", "2026-11-01", "2026-11-12"),
      ).rejects.toBeInstanceOf(InvoiceClientError);

      answer(
        serverReceipt([
          // Rent and Services under a Rent Invoice.
          line("RENT", { RENT: 36_000, SERVICE_CHARGES: 4_000 }),
          // Only Rent: the Invoice's own name says it.
          line("RENT", { RENT: 40_000 }),
          // Only its Services were paid: the part says so.
          line("RENT", { SERVICE_CHARGES: 40_000 }),
          // A one-time charge line takes the name of its Invoice's type.
          line("SHORT_STAY", { MISCELLANEOUS_CHARGES: 40_000 }),
          line("DAMAGE", {
            DAMAGE_CHARGES: 30_000,
            MISCELLANEOUS_CHARGES: 10_000,
          }),
          // A database that sends no parts yet.
          line("RENT", undefined),
          {
            kind: "DEPOSIT",
            deposit_type: "SECURITY",
            amount_usd_cents: 8_000,
          },
        ]),
      );
      const receipt = await createPaymentsApi().receipt("property-1", "p-1");
      expect(receipt.lines.map((each) => each.parts)).toEqual([
        [
          { kind: "RENT", amount: 36_000 },
          { kind: "SVC", amount: 4_000 },
        ],
        [],
        [{ kind: "SVC", amount: 40_000 }],
        [],
        [],
        [],
        [],
      ]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("Operations screen (owner 13/11/2026)", () => {
  it("TEST-FE-2195 (owner 13/11/2026) the $0.00 cards fold behind one More cards card; a pressed card stays shown", async () => {
    showList(
      api({
        ...SUMMARY,
        kinds: {
          ...SUMMARY.kinds,
          SHORT_STAY: { cents: 5_280, payments: 1 },
        },
      }),
    );
    await screen.findByRole("button", { name: /More cards/ });
    const labels = () =>
      Array.from(
        document.querySelectorAll(
          ".ui-kpis-pay .ui-kpi:not(.ui-kpi-more) .ui-kpi-label",
        ),
      ).map((label) => label.textContent);
    const folded = labels();
    expect(folded).toContain("Total received");
    expect(folded).toContain("Short stay");
    expect(folded).not.toContain("Products");
    expect(folded.length).toBeLessThan(11);

    fireEvent.click(screen.getByRole("button", { name: /More cards/ }));
    expect(labels()).toHaveLength(11);
    expect(screen.getByRole("button", { name: /Fewer cards/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    // A card pressed while shown stays on screen after folding again.
    fireEvent.click(screen.getByRole("button", { name: /^Products:/ }));
    fireEvent.click(screen.getByRole("button", { name: /Fewer cards/ }));
    expect(labels()).toContain("Products");
  });

  it("TEST-FE-2198 (owner 16/11/2026) a large screen shows every card and no More cards card", async () => {
    const before = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query === "(min-width: 1600px)",
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;
    try {
      showList(api(SUMMARY));
      await screen.findByRole("button", { name: /^Total received:/ });
      expect(document.querySelectorAll(".ui-kpis-pay .ui-kpi")).toHaveLength(
        11,
      );
      expect(
        screen.queryByRole("button", { name: /More cards/ }),
      ).not.toBeInTheDocument();
    } finally {
      window.matchMedia = before;
    }
  });
});
