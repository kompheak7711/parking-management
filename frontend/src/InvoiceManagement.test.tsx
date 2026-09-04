import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InvoiceManagement } from "./InvoiceManagement";
import {
  BillingJournal,
  InvoiceApi,
  InvoiceClientError,
  InvoiceResource,
  PendingBillingCommand,
  parseUsd,
} from "./invoiceClient";
const propertyId = "property-one";
const capabilities = [
  "invoices.create",
  "invoices.issue",
  "invoices.adjust",
  "invoices.void",
  "billing.generate",
  "late_payment.review",
  "late_payment.final_decision",
  "late_payment.charge_correction",
];
function resource(
  status: InvoiceResource["status"] = "DRAFT",
): InvoiceResource {
  const amount = parseUsd("310");
  return {
    id: "invoice-one",
    property_id: propertyId,
    customer_id: "customer-one",
    lease_id: "lease-one",
    invoice_number: "INV-047",
    category: "RENT",
    status,
    invoice_date: "2026-09-01",
    due_date: "2026-09-05",
    billing_period: { start: "2026-09-01", end: "2026-09-30" },
    version: 2,
    original_total: amount,
    adjusted_total: amount,
    active_application_total: parseUsd("0"),
    outstanding_balance: status === "DRAFT" ? parseUsd("0") : amount,
    lines: [
      {
        id: "line-one",
        sequence: 1,
        description: "Approved rent",
        category: "RENT",
        original_amount: amount,
        adjusted_amount: amount,
        outstanding_balance: amount,
        source: { id: "approved-lease" },
        calculation_evidence: { source: "rate-one" },
        period: null,
      },
    ],
    adjustments: [],
    void_event: null,
    evidence: {
      customer_id: "customer-one",
      due_date: "2026-09-05",
      source: "approved-lease",
      original_total: { currency: "USD", minor_units: 31000 },
      applications: [],
      adjustments: [],
    },
  };
}
function memoryJournal(initial: PendingBillingCommand | null = null) {
  let saved = initial;
  return {
    load: vi.fn((_actor: string) => {
      void _actor;
      return Promise.resolve(saved);
    }),
    begin: vi.fn((_actor: string, pending: PendingBillingCommand) => {
      if (saved) return Promise.reject(new Error("occupied"));
      saved = structuredClone(pending);
      return Promise.resolve();
    }),
    clear: vi.fn((_actor: string, key: string) => {
      if (saved && saved.key !== key)
        return Promise.reject(new Error("different request"));
      saved = null;
      return Promise.resolve();
    }),
  } satisfies BillingJournal;
}
function setup(
  status: InvoiceResource["status"] = "DRAFT",
  grants = capabilities,
) {
  const invoice = resource(status);
  const api: InvoiceApi = {
    list: vi.fn().mockResolvedValue({
      items: [invoice],
      next_cursor: null,
      capabilities: grants,
    }),
    get: vi.fn().mockResolvedValue(invoice),
    create: vi.fn().mockResolvedValue(invoice),
    correctDraft: vi.fn().mockResolvedValue({ ...invoice, version: 3 }),
    issue: vi
      .fn()
      .mockResolvedValue({ ...invoice, version: 3, status: "UNPAID" }),
    adjust: vi.fn().mockResolvedValue({ ...invoice, version: 3 }),
    void: vi.fn().mockResolvedValue({ ...invoice, version: 3, status: "VOID" }),
    lateReview: vi.fn().mockResolvedValue({
      invoice_id: invoice.id,
      property_id: propertyId,
      overdue_balance: parseUsd("310"),
      default_rate_basis_points: 1000,
      calculated_default_amount: parseUsd("31"),
      eligible: true,
      blocking_conditions: [],
      prior_decision: null,
    }),
    lateDecision: vi.fn(),
    decide: vi.fn().mockResolvedValue({
      id: "decision",
      property_id: propertyId,
      customer_id: invoice.customer_id,
      source_invoice: { id: invoice.id },
      outcome: "REDUCED",
      approved_amount: parseUsd("15"),
      calculated_default_amount: parseUsd("31"),
      charge: { id: "charge" },
      evidence: { outcome: "REDUCED" },
    }),
    charge: vi.fn().mockResolvedValue({
      id: "charge",
      property_id: propertyId,
      customer_id: invoice.customer_id,
      original_amount: parseUsd("15"),
      adjusted_obligation: parseUsd("15"),
      remaining_balance: parseUsd("15"),
      corrections: [],
      evidence: { id: "charge" },
    }),
    correctCharge: vi.fn().mockResolvedValue({
      id: "charge",
      property_id: propertyId,
      customer_id: invoice.customer_id,
      original_amount: parseUsd("15"),
      adjusted_obligation: parseUsd("10"),
      remaining_balance: parseUsd("10"),
      corrections: [],
      evidence: { id: "charge" },
    }),
    run: vi.fn().mockResolvedValue({
      id: "run",
      property_id: propertyId,
      run_kind: "RENT",
      logical_run_key: "rent-september",
      business_date: "2026-09-01",
      status: "RETRYABLE",
      period: { start: "2026-09-01", end: "2026-09-30" },
      attempts: [],
      evidence: {},
    }),
    getRun: vi.fn(),
  };
  const journal = memoryJournal();
  return { api, invoice, journal };
}
const fill = (label: string, text: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value: text } });
async function loadInvoice() {
  await screen.findByText("Load authorized invoices to begin.");
  fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
  fireEvent.click(await screen.findByRole("button", { name: "INV-047" }));
  await screen.findByRole("heading", { name: "Invoice INV-047" });
}
async function confirm() {
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm billing action" }),
  );
  await waitFor(() => {
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
describe("V1-047 staff billing workflows", () => {
  it("TEST-FE-235 hides commands without server-granted capabilities while preserving invoice inspection", async () => {
    const { api, journal } = setup("DRAFT", []);
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    expect(
      screen.queryByRole("button", { name: "Review invoice issuance" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Review billing run" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Approved rent")).toBeInTheDocument();
  });
  it("TEST-FE-236 requires explicit issue confirmation and binds the displayed invoice version", async () => {
    const { api, journal } = setup();
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    expect(api.issue).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("customer-one")).toBeInTheDocument();
    expect(within(dialog).getByText("USD 310.00")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Cancel billing action" }),
    );
    expect(api.issue).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    await confirm();
    await waitFor(() => {
      expect(api.issue).toHaveBeenCalledWith(
        "invoice-one",
        2,
        expect.any(String),
      );
    });
    expect(journal.begin).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(journal.clear).toHaveBeenCalledTimes(1);
    });
  });
  it("TEST-FE-237 seals intent before sending, prevents duplicate clicks and replays unchanged after a lost response", async () => {
    const { api, journal } = setup();
    vi.mocked(api.issue).mockRejectedValueOnce(
      new InvoiceClientError(null, "NETWORK", true),
    );
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    const button = screen.getByRole("button", {
      name: "Confirm billing action",
    });
    fireEvent.click(button);
    fireEvent.click(button);
    await screen.findByRole("button", { name: "Retry exact saved request" });
    expect(api.issue).toHaveBeenCalledTimes(1);
    expect(journal.clear).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry exact saved request" }),
    );
    await waitFor(() => {
      expect(api.issue).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(api.issue).mock.calls[0]).toEqual(
      vi.mocked(api.issue).mock.calls[1],
    );
    await waitFor(() => {
      expect(journal.clear).toHaveBeenCalledTimes(1);
    });
  });
  it("TEST-FE-238 recovers the same saved request after remount and never sends automatically", async () => {
    const { api, journal } = setup();
    vi.mocked(api.issue).mockRejectedValueOnce(
      new InvoiceClientError(null, "NETWORK", true),
    );
    const view = render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    await confirm();
    await screen.findByRole("button", { name: "Retry exact saved request" });
    view.unmount();
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    const retry = await screen.findByRole("button", {
      name: "Retry exact saved request",
    });
    expect(api.issue).toHaveBeenCalledTimes(1);
    fireEvent.click(retry);
    await waitFor(() => {
      expect(api.issue).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(api.issue).mock.calls[0]).toEqual(
      vi.mocked(api.issue).mock.calls[1],
    );
  });
  it("TEST-FE-239 does not release an earlier unknown request merely because replay is now forbidden", async () => {
    const { api } = setup();
    vi.mocked(api.issue).mockRejectedValue(
      new InvoiceClientError(403, "FORBIDDEN", false),
    );
    const journal = memoryJournal({
      key: "original",
      command: { action: "issue", propertyId, id: "invoice-one", version: 2 },
    });
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Retry exact saved request" }),
    );
    await screen.findByRole("alert");
    expect(journal.clear).not.toHaveBeenCalled();
    expect(await journal.load("actor")).not.toBeNull();
  });
  it("TEST-FE-240 blocks transmission if durable storage cannot reserve the command", async () => {
    const { api, journal } = setup();
    journal.begin.mockRejectedValue(new Error("storage failed"));
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm billing action" }),
    );
    await screen.findByRole("alert");
    expect(api.issue).not.toHaveBeenCalled();
  });
  it("TEST-FE-241 clears a definitively rejected new command but requires fresh invoice authority", async () => {
    const { api, journal } = setup();
    vi.mocked(api.issue).mockRejectedValue(
      new InvoiceClientError(412, "VERSION_CONFLICT", false, 3),
    );
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    await confirm();
    await screen.findByRole("alert");
    expect(journal.clear).toHaveBeenCalled();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    ).not.toBeDisabled();
    expect(api.issue).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-242 does not repeat a successful command when a later list refresh fails", async () => {
    const { api, journal } = setup();
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    await confirm();
    await waitFor(() => {
      expect(journal.clear).toHaveBeenCalled();
    });
    vi.mocked(api.list).mockRejectedValue(
      new InvoiceClientError(503, "UNAVAILABLE", false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByRole("alert");
    expect(api.issue).toHaveBeenCalledTimes(1);
    expect(await journal.load("actor")).toBeNull();
  });
  it("TEST-FE-243 creates drafts only from an approved obligation and corrects a draft with a reason", async () => {
    const { api, journal } = setup();
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fill("Authorized obligation ID", "approved-obligation");
    fireEvent.click(
      screen.getByRole("button", { name: "Review draft creation" }),
    );
    await confirm();
    await waitFor(() => {
      expect(api.create).toHaveBeenCalledWith(
        propertyId,
        "approved-obligation",
        expect.any(String),
      );
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Review draft correction" }),
      ).not.toBeDisabled();
    });
    fill("Corrected authorized obligation ID", "replacement");
    fill("Draft correction reason", "source correction");
    fireEvent.click(
      screen.getByRole("button", { name: "Review draft correction" }),
    );
    await confirm();
    await waitFor(() => {
      expect(api.correctDraft).toHaveBeenCalledWith(
        "invoice-one",
        "replacement",
        "source correction",
        2,
        expect.any(String),
      );
    });
  });
  it("TEST-FE-244 requires line, exact amount, source and reason for an append-only adjustment", async () => {
    const { api, journal } = setup("UNPAID");
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fill("Adjustment direction", "CREDIT");
    fill("Adjustment amount (USD)", "15.00");
    fill("Adjustment source reference", "approved-source");
    fill("Adjustment reason", "correct invoice");
    fireEvent.click(screen.getByRole("button", { name: "Review adjustment" }));
    await confirm();
    await waitFor(() => {
      expect(api.adjust).toHaveBeenCalledWith(
        "invoice-one",
        {
          invoice_line_id: "line-one",
          adjustment_type: "CREDIT",
          amount: parseUsd("15"),
          source_reference: "approved-source",
          reason: "correct invoice",
        },
        2,
        expect.any(String),
      );
    });
  });
  it("TEST-FE-245 blocks invoice void when active applications must first be reversed", async () => {
    const { api, journal, invoice } = setup("PAID");
    vi.mocked(api.get).mockResolvedValue({
      ...invoice,
      active_application_total: parseUsd("310"),
    });
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    expect(
      screen.getByRole("button", { name: "Review invoice void" }),
    ).toBeDisabled();
    expect(api.void).not.toHaveBeenCalled();
  });
  it.each(["REDUCED", "WAIVED", "CONFIRMED_DEFAULT"])(
    "confirms one exact %s late-payment decision separately from the invoice",
    async (outcome) => {
      const { api, journal } = setup("UNPAID");
      render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId="actor"
          propertyId={propertyId}
        />,
      );
      await loadInvoice();
      fireEvent.click(
        screen.getByRole("button", { name: "Review late payment" }),
      );
      await screen.findByRole("heading", { name: "Late-payment review" });
      fill("Final decision", outcome);
      fill("Exact reduced amount (USD; REDUCED only)", "15");
      fill("Late-payment decision reason", "approved");
      fireEvent.click(
        screen.getByRole("button", { name: "Review final decision" }),
      );
      expect(api.decide).not.toHaveBeenCalled();
      await confirm();
      await waitFor(() => {
        expect(api.decide).toHaveBeenCalledWith(
          "invoice-one",
          outcome,
          parseUsd(
            outcome === "REDUCED" ? "15" : outcome === "WAIVED" ? "0" : "31",
          ),
          "approved",
          expect.any(String),
        );
      });
      expect(api.adjust).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-246 hides the final-decision action for an ineligible invoice and displays blockers", async () => {
    const { api, journal } = setup("UNPAID");
    vi.mocked(api.lateReview).mockResolvedValue({
      invoice_id: "invoice-one",
      property_id: propertyId,
      overdue_balance: parseUsd("0"),
      default_rate_basis_points: 1000,
      calculated_default_amount: parseUsd("0"),
      eligible: false,
      blocking_conditions: ["NO_OVERDUE_BALANCE"],
      prior_decision: null,
    });
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(
      screen.getByRole("button", { name: "Review late payment" }),
    );
    await screen.findByText("Not eligible: NO_OVERDUE_BALANCE");
    expect(
      screen.queryByRole("button", { name: "Review final decision" }),
    ).not.toBeInTheDocument();
  });
  it("TEST-FE-247 preserves billing run identity for an explicit retry", async () => {
    const { api, journal } = setup();
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fill("Logical billing run key", "rent-september");
    fill("Billing business date", "2026-09-01");
    fill("Billing period start", "2026-09-01");
    fill("Billing period end", "2026-09-30");
    fireEvent.click(screen.getByRole("button", { name: "Review billing run" }));
    await confirm();
    const retry = await screen.findByRole("button", {
      name: "Review retry of same billing run",
    });
    await waitFor(() => {
      expect(retry).not.toBeDisabled();
    });
    fireEvent.click(retry);
    await confirm();
    await waitFor(() => {
      expect(api.run).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(api.run).mock.calls[0]).toEqual(
      vi.mocked(api.run).mock.calls[1],
    );
  });
  it("TEST-FE-248 rejects wrong-property resources without displaying their customer data", async () => {
    const { api, journal, invoice } = setup();
    vi.mocked(api.list).mockResolvedValue({
      items: [
        { ...invoice, property_id: "other", customer_id: "private-other" },
      ],
      next_cursor: null,
      capabilities,
    });
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("private-other")).not.toBeInTheDocument();
  });
  it("TEST-FE-249 ignores an old Property read after the workspace changes", async () => {
    const { api, journal, invoice } = setup();
    let resolve: (
      value: Awaited<ReturnType<InvoiceApi["list"]>>,
    ) => void = () => undefined;
    vi.mocked(api.list).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const view = render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    view.rerender(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId="other"
      />,
    );
    await act(async () => {
      await Promise.resolve();
      resolve({ items: [invoice], next_cursor: null, capabilities });
    });
    expect(screen.queryByText("INV-047")).not.toBeInTheDocument();
  });

  it("TEST-FE-250 confirms exceptional void with reason and unchanged version", async () => {
    const { api, journal } = setup("UNPAID");
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fill("Invoice void reason", "Source obligation invalid");
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice void" }),
    );
    expect(api.void).not.toHaveBeenCalled();
    expect(
      within(screen.getByRole("dialog")).getByText("Source obligation invalid"),
    ).toBeInTheDocument();
    await confirm();
    await waitFor(() => {
      expect(api.void).toHaveBeenCalledWith(
        "invoice-one",
        "Source obligation invalid",
        2,
        expect.any(String),
      );
    });
  });
  it("TEST-FE-251 confirms all append-only charge correction variants without altering the final decision", async () => {
    for (const kind of [
      "REDUCTION",
      "CHARGE_REVERSAL",
      "REDUCTION_REVERSAL",
    ] as const) {
      const { api, journal } = setup("UNPAID");
      if (kind === "REDUCTION_REVERSAL")
        vi.mocked(api.charge).mockResolvedValue({
          id: "charge",
          property_id: propertyId,
          customer_id: "customer-one",
          original_amount: parseUsd("15"),
          adjusted_obligation: parseUsd("10"),
          remaining_balance: parseUsd("10"),
          corrections: [
            {
              id: "prior-reduction",
              kind: "REDUCTION",
              active: true,
              amount: { currency: "USD", minor_units: 500 },
              reverses_correction_id: null,
            },
          ],
          evidence: { id: "charge" },
        });
      render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId="actor"
          propertyId={propertyId}
        />,
      );
      await loadInvoice();
      fireEvent.click(
        screen.getByRole("button", { name: "Review late payment" }),
      );
      await screen.findByRole("heading", { name: "Late-payment review" });
      fill("Final decision", "REDUCED");
      fill("Exact reduced amount (USD; REDUCED only)", "15");
      fill("Late-payment decision reason", "Approved");
      fireEvent.click(
        screen.getByRole("button", { name: "Review final decision" }),
      );
      await confirm();
      const open = await screen.findByRole("button", {
        name: "Open separate Late-payment Charge",
      });
      await waitFor(() => {
        expect(open).not.toBeDisabled();
      });
      fireEvent.click(open);
      await screen.findByRole("heading", {
        name: "Separate Late-payment Charge",
      });
      fill("Charge correction kind", kind);
      fill("Charge reduction amount (USD)", "5");
      fill("Reduction correction ID to reverse", "prior-reduction");
      fill("Charge correction reason", "Correction approved");
      fireEvent.click(
        screen.getByRole("button", { name: "Review charge correction" }),
      );
      const dialog = screen.getByRole("dialog");
      const resultAmount =
        kind === "REDUCTION"
          ? "USD 10.00"
          : kind === "CHARGE_REVERSAL"
            ? "USD 0.00"
            : "USD 15.00";
      expect(
        within(dialog).getByText("estimated resulting obligation")
          .nextElementSibling,
      ).toHaveTextContent(resultAmount);
      expect(
        within(dialog).getByText("estimated remaining balance")
          .nextElementSibling,
      ).toHaveTextContent(resultAmount);
      expect(
        within(dialog).getByText("estimated effect").nextElementSibling,
      ).toHaveTextContent(
        kind === "REDUCTION"
          ? "USD -5.00"
          : kind === "CHARGE_REVERSAL"
            ? "USD -15.00"
            : "USD 5.00",
      );
      expect(
        within(dialog).getByText(/Snapshot estimate only/),
      ).toHaveTextContent("immutable correction");
      expect(api.correctCharge).not.toHaveBeenCalled();
      await confirm();
      const input =
        kind === "REDUCTION"
          ? { kind, amount: parseUsd("5"), reason: "Correction approved" }
          : kind === "REDUCTION_REVERSAL"
            ? {
                kind,
                reverses_correction_id: "prior-reduction",
                reason: "Correction approved",
              }
            : { kind, reason: "Correction approved" };
      await waitFor(() => {
        expect(api.correctCharge).toHaveBeenCalledWith(
          "charge",
          input,
          expect.any(String),
        );
      });
      expect(api.decide).toHaveBeenCalledTimes(1);
      expect(api.adjust).not.toHaveBeenCalled();
      cleanup();
    }
  });
  it("TEST-FE-252 rejects a credit below zero before sending and previews a zero-balance PAID result", async () => {
    const { api, journal } = setup("UNPAID");
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fill("Adjustment direction", "CREDIT");
    fill("Adjustment amount (USD)", "310.01");
    fill("Adjustment source reference", "approved");
    fill("Adjustment reason", "correction");
    fireEvent.click(screen.getByRole("button", { name: "Review adjustment" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.adjust).not.toHaveBeenCalled();
    fill("Adjustment amount (USD)", "310");
    fireEvent.click(screen.getByRole("button", { name: "Review adjustment" }));
    expect(
      within(screen.getByRole("dialog")).getByText("PAID"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("dialog")).getAllByText("USD 0.00"),
    ).toHaveLength(2);
    expect(api.adjust).not.toHaveBeenCalled();
  });
  it("TEST-FE-253 shows an empty state and preserves opaque pagination cursor", async () => {
    const { api, journal, invoice } = setup();
    vi.mocked(api.list)
      .mockResolvedValueOnce({
        items: [invoice],
        next_cursor: "opaque-next",
        capabilities,
      })
      .mockResolvedValueOnce({ items: [], next_cursor: null, capabilities })
      .mockResolvedValueOnce({
        items: [],
        next_cursor: null,
        capabilities: [],
      });
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(screen.getByRole("button", { name: "Load more invoices" }));
    await waitFor(() => {
      expect(api.list).toHaveBeenCalledWith(
        propertyId,
        expect.objectContaining({ cursor: "opaque-next" }),
      );
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Load invoices" }),
      ).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByText("No matching invoices.");
  });
});

describe("V1-047 bounded correction regressions", () => {
  it.each(["actor", "property", "unmount"])(
    "does not transmit after %s invalidation while journal reservation is pending",
    async (change) => {
      const { api, journal } = setup();
      let reserved!: () => void;
      journal.begin.mockImplementation(
        () =>
          new Promise<void>((resolve) => {
            reserved = resolve;
          }),
      );
      const view = render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId="actor"
          propertyId={propertyId}
        />,
      );
      await loadInvoice();
      fireEvent.click(
        screen.getByRole("button", { name: "Review invoice issuance" }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Confirm billing action" }),
      );
      expect(journal.begin).toHaveBeenCalledTimes(1);
      if (change === "unmount") view.unmount();
      else
        view.rerender(
          <InvoiceManagement
            api={api}
            journal={journal}
            actorId={change === "actor" ? "actor-B" : "actor"}
            propertyId={change === "property" ? "property-B" : propertyId}
          />,
        );
      await act(() => {
        reserved();
        return Promise.resolve();
      });
      expect(api.issue).not.toHaveBeenCalled();
      expect(journal.clear).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-254 passes original actor and cancellable workspace to real transmission binding", async () => {
    const { api, journal } = setup();
    const boundIssue = vi.fn().mockResolvedValue({ ...resource(), version: 3 });
    api.forActor = vi.fn().mockReturnValue({ ...api, issue: boundIssue });
    const view = render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor-A"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    await confirm();
    expect(vi.mocked(api.forActor).mock.calls[0]?.[0].actorId).toBe("actor-A");
    expect(boundIssue).toHaveBeenCalledTimes(1);
    const binding = vi.mocked(api.forActor).mock.calls[0]?.[0];
    expect(binding?.signal).toBeInstanceOf(AbortSignal);
    view.unmount();
    expect(binding?.signal.aborted).toBe(true);
  });
  it("TEST-FE-255 reconciles a saved exact 412 and requires fresh review at the current version", async () => {
    const { api } = setup();
    const saved: PendingBillingCommand = {
      key: "saved",
      command: { action: "issue", propertyId, id: "invoice-one", version: 2 },
    };
    const journal = memoryJournal(saved);
    vi.mocked(api.issue).mockRejectedValueOnce(
      new InvoiceClientError(412, "PRECONDITION_FAILED", false, 3),
    );
    vi.mocked(api.get).mockResolvedValue({ ...resource(), version: 3 });
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Retry exact saved request" }),
    );
    await waitFor(() => {
      expect(journal.clear).toHaveBeenCalledWith("actor", "saved");
    });
    await screen.findByRole("heading", { name: "Invoice INV-047" });
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByRole("button", { name: "INV-047" });
    const review = screen.getByRole("button", {
      name: "Review invoice issuance",
    });
    await waitFor(() => {
      expect(review).not.toBeDisabled();
    });
    expect(api.issue).toHaveBeenCalledTimes(1);
    fireEvent.click(review);
    await confirm();
    expect(vi.mocked(api.issue).mock.calls[1]).toEqual([
      "invoice-one",
      3,
      expect.any(String),
    ]);
    expect(vi.mocked(api.issue).mock.calls[1]?.[2]).not.toBe("saved");
  });
  it.each([
    new InvoiceClientError(412, "PRECONDITION_FAILED", false),
    new InvoiceClientError(409, "IDEMPOTENCY_KEY_REUSED", false),
    new InvoiceClientError(403, "FORBIDDEN", false),
    new InvoiceClientError(503, "UNAVAILABLE", true),
  ])("preserves unresolved saved outcomes: $code", async (error) => {
    const { api } = setup();
    const journal = memoryJournal({
      key: "saved",
      command: { action: "issue", propertyId, id: "invoice-one", version: 2 },
    });
    vi.mocked(api.issue).mockRejectedValue(error);
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Retry exact saved request" }),
    );
    await screen.findByRole("alert");
    expect(journal.clear).not.toHaveBeenCalled();
    expect(await journal.load("actor")).not.toBeNull();
  });
  it("TEST-FE-256 shows reasoned confirmed DRAFT voiding and preserves its history consequence", async () => {
    const { api, journal } = setup("DRAFT", ["invoices.void"]);
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    const reason = screen.getByLabelText("Invoice void reason");
    expect(reason).toBeRequired();
    fill("Invoice void reason", "Invalid approved source");
    fireEvent.click(
      screen.getByRole("button", { name: "Review invoice void" }),
    );
    expect(api.void).not.toHaveBeenCalled();
    expect(
      within(screen.getByRole("dialog")).getByText(
        /Voiding ends this obligation/,
      ),
    ).toHaveTextContent("immutable void event");
    await confirm();
    expect(api.void).toHaveBeenCalledWith(
      "invoice-one",
      "Invalid approved source",
      2,
      expect.any(String),
    );
    expect(
      screen.queryByRole("button", { name: "Review invoice void" }),
    ).not.toBeInTheDocument();
  });
  it("TEST-FE-257 exposes billing generation and inspection when invoice reads are forbidden", async () => {
    const { api, journal } = setup("DRAFT", []);
    api.capabilities = vi.fn().mockResolvedValue(["billing.generate"]);
    vi.mocked(api.list).mockRejectedValue(
      new InvoiceClientError(403, "FORBIDDEN", false),
    );
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    expect(
      await screen.findByRole("button", { name: "Review billing run" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByRole("alert");
    expect(
      screen.getByRole("button", { name: "Inspect billing run" }),
    ).not.toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Review billing run" }),
    ).not.toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Review draft creation" }),
    ).not.toBeInTheDocument();
  });
  it("TEST-FE-258 contains dialog keyboard focus and restores cancellation and completion focus", async () => {
    // Real browsers blur a focused descendant when its fieldset is disabled.
    // JSDOM does not, so reproduce that transition before passive dialog effects.
    const setAttribute = HTMLFieldSetElement.prototype.setAttribute;
    vi.spyOn(HTMLFieldSetElement.prototype, "setAttribute").mockImplementation(
      function (this: HTMLFieldSetElement, name: string, value: string) {
        setAttribute.call(this, name, value);
        if (
          name === "disabled" &&
          document.activeElement instanceof HTMLElement &&
          this.contains(document.activeElement)
        ) {
          document.activeElement.blur();
        }
      },
    );
    const { api, journal } = setup();
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    const opener = screen.getByRole("button", {
      name: "Review invoice issuance",
    });
    opener.focus();
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", {
      name: "Confirm billing action",
    });
    expect(dialog).toHaveFocus();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    const cancel = screen.getByRole("button", {
      name: "Cancel billing action",
    });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: "Tab" });
    expect(
      within(dialog).getByText("Evidence reviewed for this action"),
    ).toHaveFocus();
    fireEvent.keyDown(screen.getByText("Evidence reviewed for this action"), {
      key: "Escape",
    });
    expect(opener).toHaveFocus();
    expect(api.issue).not.toHaveBeenCalled();
    fireEvent.click(opener);
    await confirm();
    // Issuance removes its initiating button; restore to the result announcement.
    expect(screen.getByRole("status")).toHaveFocus();
  });
  it("TEST-FE-259 associates safe field details with the originating form and exposes the support ID", async () => {
    const { api, journal } = setup();
    vi.mocked(api.correctDraft).mockRejectedValue(
      new InvoiceClientError(
        422,
        "VALIDATION_ERROR",
        false,
        null,
        ["reason", "authorized_nonrecurring_obligation_id"],
        "request-safe-123",
      ),
    );
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fill("Corrected authorized obligation ID", "approved");
    fill("Draft correction reason", "reason");
    fireEvent.click(
      screen.getByRole("button", { name: "Review draft correction" }),
    );
    await confirm();
    expect(
      screen.getByText("Support request ID: request-safe-123"),
    ).toBeInTheDocument();
    const field = screen.getByLabelText("Draft correction reason");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription("reason: Check this value.");
    expect(screen.getByLabelText("Invoice void reason")).not.toHaveAttribute(
      "aria-invalid",
    );
    expect(
      screen.getByLabelText("Authorized obligation ID"),
    ).not.toHaveAttribute("aria-invalid");
    fireEvent.click(
      screen.getByRole("button", { name: "Review draft correction" }),
    );
    expect(field).not.toHaveAttribute("aria-invalid");
  });
  it.each([1n, 2n])(
    "previews near-bigint-limit adjustments with exact arithmetic (delta %s)",
    async (delta) => {
      const { api, journal } = setup("UNPAID");
      const exact = {
        ...resource("UNPAID"),
        adjusted_total: {
          currency: "USD" as const,
          minor_units: 9223372036854775805n,
        },
        outstanding_balance: {
          currency: "USD" as const,
          minor_units: 9223372036854775805n,
        },
      };
      const line = exact.lines[0];
      if (!line) throw new Error("Missing line fixture");
      line.adjusted_amount = exact.adjusted_total;
      vi.mocked(api.get).mockResolvedValue(exact);
      render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId="actor"
          propertyId={propertyId}
        />,
      );
      await loadInvoice();
      fill("Adjustment amount (USD)", delta === 1n ? "0.01" : "0.02");
      fill("Adjustment reason", "approved");
      fill("Adjustment source reference", "source");
      fireEvent.click(
        screen.getByRole("button", { name: "Review adjustment" }),
      );
      const preview = within(screen.getByRole("dialog"));
      expect(
        preview.getByText("estimated adjusted total").nextElementSibling,
      ).toHaveTextContent(
        delta === 1n ? "USD 92233720368547758.06" : "USD 92233720368547758.07",
      );
      expect(api.adjust).not.toHaveBeenCalled();
    },
  );
});

describe("billing-run recovery after reload", () => {
  const actor = "11111111-1111-4111-8111-111111111111";
  const property = "22222222-2222-4222-8222-222222222222";
  const id = "33333333-3333-4333-8333-333333333333";
  const key = "44444444-4444-4444-8444-444444444444";
  it.each(["API", "SCHEDULED", "FOREIGN", "MISSING"])(
    "inspects RETRYABLE %s runs and allows only original-actor API retries",
    async (source) => {
      const { api, journal } = setup();
      const run = {
        id,
        property_id: property,
        run_kind: "RENT" as const,
        logical_run_key: "rent/2026-09",
        business_date: "2026-08-25",
        status: "RETRYABLE",
        period: { start: "2026-09-01", end: "2026-09-30" },
        attempts: [],
        evidence: {
          idempotency_key: source === "MISSING" ? null : key,
          requester_actor_id:
            source === "FOREIGN"
              ? "55555555-5555-4555-8555-555555555555"
              : actor,
          invocation_source: source === "SCHEDULED" ? "SCHEDULED" : "API",
        },
      };
      api.capabilities = vi.fn().mockResolvedValue(["billing.generate"]);
      vi.mocked(api.getRun).mockResolvedValue(run);
      vi.mocked(api.run).mockResolvedValue(run);
      const first = render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId={actor}
          propertyId={property}
        />,
      );
      await screen.findByRole("button", { name: "Inspect billing run" });
      first.unmount();
      render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId={actor}
          propertyId={property}
        />,
      );
      await screen.findByRole("button", { name: "Inspect billing run" });
      await screen.findByText("Load authorized invoices to begin.");
      fill("Billing run ID", id);
      fireEvent.click(
        screen.getByRole("button", { name: "Inspect billing run" }),
      );
      await screen.findByRole("heading", {
        name: "Run rent/2026-09: RETRYABLE",
      });
      expect(api.run).not.toHaveBeenCalled();
      if (source === "API") {
        const retry = screen.getByRole("button", {
          name: "Review retry of same billing run",
        });
        await waitFor(() => {
          expect(retry).not.toBeDisabled();
        });
        fireEvent.click(retry);
        await confirm();
        expect(api.run).toHaveBeenCalledWith(
          property,
          "rent",
          {
            logical_run_key: "rent/2026-09",
            business_date: "2026-08-25",
            period_start: "2026-09-01",
            period_end: "2026-09-30",
          },
          key,
        );
        expect(journal.begin).toHaveBeenCalledWith(
          actor,
          expect.objectContaining({ key }),
        );
      } else
        expect(
          screen.queryByRole("button", {
            name: "Review retry of same billing run",
          }),
        ).not.toBeInTheDocument();
    },
  );
});
