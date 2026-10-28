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
    MOVEOUT: ZERO,
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
  it("TEST-FE-914 shows Total received and the seven cards, the add-up line, and filters the list by a card or by money not matched yet", async () => {
    showList();
    await screen.findByText("RCP260045");

    expect(
      screen.getByRole("button", { name: /^Total received: \$1,000\.00/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", {
        name: /^Rent: \$800\.00\. Rent lines\n2 payments/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The seven category cards ($900.00) and $100.00 not matched yet add up to $1,000.00. Riel payments (82,260 ៛) count at the dollar value recorded when they were received ($20.00).",
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
          MOVEOUT: ZERO,
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
      screen.getByText("The seven category cards add up to $0.00."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Last month" }));
    await waitFor(() => {
      expect(paymentsApi.summary).toHaveBeenLastCalledWith(
        "property-1",
        "2026-09-01",
        "2026-09-30",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Pick dates" }));
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
        /The seven category cards \(\$900\.00\), \$50\.00 refunded and \$100\.00 not matched yet add up to \$1,050\.00\./,
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
    expect(within(sheet).getByText("Unit U204")).toBeInTheDocument();
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
    expect(print).toHaveBeenCalled();
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
        /The seven category cards \(\$900\.00\), \$0\.00 refunded and \$100\.00 not matched yet add up to \$1,000\.00, not \$1,200\.00\. Tell the Owner\./,
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
        "The Customer names could not be read, so the Receipt cannot print yet.",
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
