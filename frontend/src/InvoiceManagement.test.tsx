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
  InitialRentDueDateInput,
  InvoiceApi,
  InvoiceClientError,
  InvoiceResource,
  LatePaymentDecision,
  OneTimeChargeInput,
  PendingBillingCommand,
  parseUsd,
  invoiceApi,
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
    createWithItems: vi.fn().mockResolvedValue(invoice),
    replaceItems: vi.fn().mockResolvedValue({ ...invoice, version: 3 }),
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
    setInitialRentDueDate: vi.fn(
      (_property: string, leaseId: string, input: InitialRentDueDateInput) =>
        Promise.resolve({
          override_id: input.override_id,
          property_id: propertyId,
          lease_id: leaseId,
          due_date: input.due_date,
          proposed_due_date: "2026-09-06",
          reason: input.reason,
          evidence: { proposed_due_date: "2026-09-06" },
        }),
    ),
    setDueDays: vi.fn(
      (
        _property: string,
        days: number,
        _reason: string,
        propertyVersion: number,
      ) =>
        Promise.resolve({
          property_id: propertyId,
          one_time_charge_due_days: days,
          version: propertyVersion + 1,
        }),
    ),
    recordOneTimeCharge: vi.fn((_property: string, input: OneTimeChargeInput) =>
      Promise.resolve({
        obligation_id: input.charge_id,
        category: input.category,
        customer_id: input.customer_id,
        lease_id: input.lease_id,
        inspection_damage_finding_id: input.inspection_damage_finding_id,
        description: input.description,
        amount: input.amount,
        reason: input.reason,
        evidence_reference: input.evidence_reference,
        evidence: { evidence_reference: input.evidence_reference },
      }),
    ),
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
  it.each(["decide", "correctCharge"] as const)(
    "keeps the exact %s receipt recovery through pre-lookup failure, key conflict and failed clearance",
    async (action) => {
      const { api } = setup("UNPAID");
      const saved: PendingBillingCommand = {
        key: "successful-request-with-lost-response",
        command:
          action === "decide"
            ? {
                action,
                propertyId,
                id: "invoice-one",
                outcome: "REDUCED",
                amount: parseUsd("15"),
                reason: "approved original decision",
              }
            : {
                action,
                propertyId,
                id: "charge",
                input: {
                  kind: "REDUCTION",
                  amount: parseUsd("5"),
                  reason: "approved original reduction",
                },
              },
      };
      const original =
        action === "decide"
          ? {
              id: "own-original-decision",
              property_id: propertyId,
              customer_id: "customer-one",
              source_invoice: { id: "invoice-one" },
              outcome: "REDUCED",
              approved_amount: parseUsd("15"),
              calculated_default_amount: parseUsd("31"),
              charge: { id: "charge" },
            }
          : {
              id: "charge",
              property_id: propertyId,
              customer_id: "customer-one",
              original_amount: parseUsd("15"),
              adjusted_obligation: parseUsd("10"),
              remaining_balance: parseUsd("10"),
              corrections: [
                {
                  id: "own-reduction",
                  kind: "REDUCTION",
                  active: true,
                  amount: parseUsd("5"),
                },
              ],
            };
      const terminal =
        action === "decide"
          ? original
          : {
              ...original,
              adjusted_obligation: parseUsd("0"),
              remaining_balance: parseUsd("0"),
              corrections: [
                {
                  id: "other-actor-reversal",
                  kind: "CHARGE_REVERSAL",
                  active: true,
                  amount: parseUsd("10"),
                  resulting_obligation: parseUsd("0"),
                },
              ],
            };
      const wire = (body: object, status: number) =>
        new Response(JSON.stringify(body), { status });
      const success = () =>
        wire(
          { data: original, meta: { request_id: "original-success" } },
          action === "decide" ? 201 : 200,
        );
      const fetcher = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(
          wire(
            {
              error: {
                code: "SERVICE_UNAVAILABLE",
                fields: [],
                current_version: null,
              },
              meta: { request_id: "pre-receipt-lock-timeout" },
            },
            503,
          ),
        )
        .mockResolvedValueOnce(
          wire(
            {
              error: {
                code: "IDEMPOTENCY_KEY_REUSED",
                current_state: terminal,
              },
              meta: { request_id: "key-conflict" },
            },
            409,
          ),
        )
        .mockImplementation(() => Promise.resolve(success()));
      vi.spyOn(document, "cookie", "get").mockReturnValue(
        "__Host-prm_csrf=synthetic",
      );
      api.decide = invoiceApi.decide;
      api.correctCharge = invoiceApi.correctCharge;
      const journal = memoryJournal(saved);
      const mount = () =>
        render(
          <InvoiceManagement
            api={api}
            journal={journal}
            actorId="actor"
            propertyId={propertyId}
          />,
        );
      let mounted = mount();
      const retry = async () => {
        const button = await screen.findByRole("button", {
          name: "Retry exact saved request",
        });
        await waitFor(() => {
          expect(button).not.toBeDisabled();
        });
        fireEvent.click(button);
      };
      await retry();
      await screen.findByText("Support request ID: pre-receipt-lock-timeout");
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Outcome not confirmed",
      );
      expect(await journal.load("actor")).toEqual(saved);
      expect(journal.clear).not.toHaveBeenCalled();
      mounted.unmount();
      mounted = mount();
      await retry();
      await screen.findByText("Support request ID: key-conflict");
      expect(await journal.load("actor")).toEqual(saved);
      expect(journal.clear).not.toHaveBeenCalled();
      journal.clear.mockRejectedValueOnce(new Error("clearance unavailable"));
      await retry();
      await waitFor(() => {
        expect(journal.clear).toHaveBeenCalledTimes(1);
      });
      await screen.findByRole("alert");
      expect(await journal.load("actor")).toEqual(saved);
      expect(
        screen.getByRole("region", { name: "Billing reconciliation" }),
      ).toBeInTheDocument();
      mounted.unmount();
      mount();
      await retry();
      await screen.findByText(/Command confirmed/);
      expect(await journal.load("actor")).toBeNull();
      expect(
        screen.queryByRole("region", { name: "Billing reconciliation" }),
      ).not.toBeInTheDocument();
      expect(journal.begin).not.toHaveBeenCalled();
      expect(journal.clear).toHaveBeenLastCalledWith("actor", saved.key);
      expect(fetcher).toHaveBeenCalledTimes(4);
      const firstRequest = fetcher.mock.calls[0];
      for (const call of fetcher.mock.calls) {
        expect(call[0]).toBe(firstRequest?.[0]);
        expect(call[1]?.body).toBe(firstRequest?.[1]?.body);
        expect(call[1]?.headers).toMatchObject({
          "Idempotency-Key": saved.key,
        });
      }
      if (action === "decide")
        expect(
          screen.getByRole("heading", { name: "Final decision: REDUCED" }),
        ).toBeInTheDocument();
      else {
        expect(
          screen.getByRole("heading", { name: "Separate Late-payment Charge" }),
        ).toBeInTheDocument();
        expect(screen.getByText(/Remaining USD 10.00/)).toBeInTheDocument();
        expect(
          screen.queryByText("other-actor-reversal"),
        ).not.toBeInTheDocument();
      }
    },
  );
  it.each([
    "first-confirmation",
    "reload",
    "already-reversed-reduction",
    "lost-success",
    "foreign-property",
    "foreign-charge",
    "malformed",
    "nonterminal",
    "forbidden",
    "unknown",
    "key-conflict",
    "clear-failure",
  ])(
    "actual client and UI recover only exact terminal charge conflicts: %s",
    async (variant) => {
      const { api } = setup("UNPAID");
      const input =
        variant === "already-reversed-reduction"
          ? {
              kind: "REDUCTION_REVERSAL" as const,
              reverses_correction_id: "prior-reduction",
              reason: "approved",
            }
          : {
              kind: "REDUCTION" as const,
              amount: parseUsd("5"),
              reason: "approved",
            };
      const saved: PendingBillingCommand = {
        key: "saved-charge",
        command: { action: "correctCharge", propertyId, id: "charge", input },
      };
      const journal = memoryJournal(
        variant === "first-confirmation" ? null : saved,
      );
      const corrections =
        variant === "already-reversed-reduction"
          ? [
              {
                id: "prior-reduction",
                kind: "REDUCTION",
                active: false,
                amount: parseUsd("5"),
              },
              {
                id: "reversal",
                kind: "REDUCTION_REVERSAL",
                reverses_correction_id: "prior-reduction",
                amount: parseUsd("5"),
              },
            ]
          : [
              {
                id: "reversal",
                kind: "CHARGE_REVERSAL",
                active: true,
                amount: parseUsd("15"),
                resulting_obligation:
                  variant === "malformed" ? null : parseUsd("0"),
              },
            ];
      const current = {
        id: variant === "foreign-charge" ? "other" : "charge",
        property_id: variant === "foreign-property" ? "other" : propertyId,
        customer_id: "customer-one",
        original_amount: parseUsd("15"),
        adjusted_obligation: parseUsd(
          variant === "already-reversed-reduction" ? "15" : "0",
        ),
        remaining_balance: parseUsd(
          variant === "already-reversed-reduction" ? "15" : "0",
        ),
        corrections: variant === "nonterminal" ? [] : corrections,
      };
      const unresolved = [
        "foreign-property",
        "foreign-charge",
        "malformed",
        "nonterminal",
        "forbidden",
        "unknown",
        "key-conflict",
        "clear-failure",
      ].includes(variant);
      const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              variant === "lost-success"
                ? { data: current }
                : {
                    error: {
                      code:
                        variant === "key-conflict"
                          ? "IDEMPOTENCY_KEY_REUSED"
                          : "CONFLICT",
                      current_state: current,
                    },
                    meta: { request_id: "charge-conflict" },
                  },
            ),
            {
              status:
                variant === "lost-success"
                  ? 200
                  : variant === "forbidden"
                    ? 403
                    : variant === "unknown"
                      ? 503
                      : 409,
            },
          ),
        ),
      );
      vi.spyOn(document, "cookie", "get").mockReturnValue(
        "__Host-prm_csrf=synthetic",
      );
      api.correctCharge = invoiceApi.correctCharge;
      if (variant === "clear-failure")
        journal.clear.mockRejectedValue(new Error("storage unavailable"));
      let mounted = render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId="actor"
          propertyId={propertyId}
        />,
      );
      if (variant === "first-confirmation") {
        await loadInvoice();
        fireEvent.click(
          screen.getByRole("button", { name: "Review late payment" }),
        );
        await screen.findByRole("heading", { name: "Late-payment review" });
        fill("Final decision", "REDUCED");
        fill("Exact reduced amount (USD; REDUCED only)", "15");
        fill("Late-payment decision reason", "approved");
        fireEvent.click(
          screen.getByRole("button", { name: "Review final decision" }),
        );
        await confirm();
        fireEvent.click(
          await screen.findByRole("button", {
            name: "Open separate Late-payment Charge",
          }),
        );
        await screen.findByRole("heading", {
          name: "Separate Late-payment Charge",
        });
        fill("Charge reduction amount (USD)", "5");
        fill("Charge correction reason", "approved");
        fireEvent.click(
          screen.getByRole("button", { name: "Review charge correction" }),
        );
        await confirm();
      } else {
        await screen.findByRole("button", {
          name: "Retry exact saved request",
        });
        mounted.unmount();
        mounted = render(
          <InvoiceManagement
            api={api}
            journal={journal}
            actorId="actor"
            propertyId={propertyId}
          />,
        );
        fireEvent.click(
          await screen.findByRole("button", {
            name: "Retry exact saved request",
          }),
        );
      }
      await waitFor(() => {
        expect(fetcher).toHaveBeenCalledTimes(1);
      });
      if (unresolved) {
        await screen.findByRole("alert");
        expect(await journal.load("actor")).toEqual(saved);
        expect(
          screen.queryByRole("heading", {
            name: "Separate Late-payment Charge",
          }),
        ).not.toBeInTheDocument();
        if (variant !== "clear-failure")
          expect(journal.clear).not.toHaveBeenCalled();
      } else {
        await waitFor(() => {
          expect(
            screen.queryByRole("region", { name: "Billing reconciliation" }),
          ).not.toBeInTheDocument();
        });
        expect(await journal.load("actor")).toBeNull();
        await screen.findByRole("heading", {
          name: "Separate Late-payment Charge",
        });
        expect(journal.clear).toHaveBeenLastCalledWith(
          "actor",
          variant === "first-confirmation"
            ? expect.any(String)
            : "saved-charge",
        );
      }
      expect(fetcher.mock.calls[0]?.[0]).toBe(
        "/api/v1/late-payment-charges/charge/corrections",
      );
      expect(fetcher.mock.calls[0]?.[1]?.headers).toHaveProperty(
        "Idempotency-Key",
        variant === "first-confirmation" ? expect.any(String) : "saved-charge",
      );
      mounted.unmount();
    },
  );
  it.each(["capability-read-503", "<unsafe>"])(
    "reports capability read failure separately and explicitly retries: %s",
    async (requestId) => {
      const { api, journal } = setup();
      api.capabilities = invoiceApi.capabilities;
      const fetcher = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              error: { code: "UNAVAILABLE", fields: ["reason"] },
              meta: { request_id: requestId },
            }),
            { status: 503 },
          ),
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              data: {
                property_id: propertyId,
                billing_capabilities: ["billing.generate"],
              },
            }),
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
      const error = await screen.findByRole("alert", {
        name: "Billing action availability",
      });
      if (requestId === "<unsafe>")
        expect(error).not.toHaveTextContent("Support request ID");
      else
        expect(error).toHaveTextContent(
          "Support request ID: capability-read-503",
        );
      expect(
        screen.queryByRole("heading", { name: "Billing runs" }),
      ).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
      await screen.findByRole("button", { name: "INV-047" });
      expect(error).toBeInTheDocument();
      expect(
        screen.getByLabelText("Invoice ID to inspect"),
      ).not.toHaveAttribute("aria-invalid");
      expect(fetcher).toHaveBeenCalledTimes(1);
      fireEvent.click(
        screen.getByRole("button", {
          name: "Retry billing action availability",
        }),
      );
      await screen.findByRole("heading", { name: "Billing runs" });
      expect(
        screen.queryByRole("alert", { name: "Billing action availability" }),
      ).not.toBeInTheDocument();
      expect(screen.queryByText(/Support request ID:/)).not.toBeInTheDocument();
      expect(fetcher).toHaveBeenCalledTimes(2);
      expect(api.list).toHaveBeenCalledTimes(1);
      expect(
        screen.getByLabelText("Logical billing run key"),
      ).not.toHaveAttribute("aria-invalid");
    },
  );
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
  it("TEST-FE-S11G-001 hides the free charge correction form once the automatic pass runs", async () => {
    const { api, journal } = setup("UNPAID");
    vi.mocked(api.charge).mockResolvedValue({
      id: "charge",
      property_id: propertyId,
      customer_id: "customer-one",
      original_amount: parseUsd("15"),
      adjusted_obligation: parseUsd("15"),
      remaining_balance: parseUsd("15"),
      corrections: [],
      evidence: { id: "charge" },
      manual_corrections_open: false,
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
    expect(screen.queryByLabelText("Charge correction kind")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Review charge correction" }),
    ).toBeNull();
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
    const setAttribute = (
      element: HTMLFieldSetElement,
      name: string,
      value: string,
    ) => {
      Element.prototype.setAttribute.call(element, name, value);
    };
    vi.spyOn(HTMLFieldSetElement.prototype, "setAttribute").mockImplementation(
      function (this: HTMLFieldSetElement, name: string, value: string) {
        setAttribute(this, name, value);
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
    // Issuance removes its initiating button; restore to the result announcement. The focus
    // moves after the answer renders, so a busy machine is waited for (V1-061 Fix 5).
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveFocus();
    });
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
      screen.getByRole("button", { name: "Review invoice issuance" }),
    );
    expect(field).not.toHaveAttribute("aria-invalid");
    await confirm();
    await screen.findByText(/Command confirmed/);
    expect(
      screen.queryByText("Support request ID: request-safe-123"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("reason: Check this value."),
    ).not.toBeInTheDocument();
  });
  it("replaces read feedback and never associates read errors with a previous form", async () => {
    const { api, journal } = setup();
    vi.mocked(api.list).mockRejectedValueOnce(
      new InvoiceClientError(
        503,
        "UNAVAILABLE",
        false,
        null,
        ["reason"],
        "read-failure-1",
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
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByText("Support request ID: read-failure-1");
    expect(screen.getByLabelText("Invoice ID to inspect")).not.toHaveAttribute(
      "aria-invalid",
    );
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByRole("button", { name: "INV-047" });
    expect(
      screen.queryByText("Support request ID: read-failure-1"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("reason: Check this value."),
    ).not.toBeInTheDocument();
  });
  it.each([
    "first-confirmation",
    "reload",
    "lost-success",
    "foreign-property",
    "foreign-invoice",
    "unknown",
    "forbidden",
    "key-conflict",
    "clear-failure",
  ])(
    "reconciles only an exact final late-payment decision: %s",
    async (variant) => {
      const { api } = setup("UNPAID");
      const saved: PendingBillingCommand = {
        key: "saved-decision",
        command: {
          action: "decide",
          propertyId,
          id: "invoice-one",
          outcome: "WAIVED",
          amount: parseUsd("0"),
          reason: "reviewed waiver",
        },
      };
      const journal = memoryJournal(
        variant === "first-confirmation" ? null : saved,
      );
      const current: LatePaymentDecision = {
        id: "decision-by-other-actor",
        property_id: variant === "foreign-property" ? "other" : propertyId,
        customer_id: "customer-one",
        source_invoice: {
          id: variant === "foreign-invoice" ? "other" : "invoice-one",
        },
        outcome: "REDUCED",
        approved_amount: parseUsd("15"),
        calculated_default_amount: parseUsd("31"),
        charge: { id: "charge" },
        evidence: { actor: "actor-B" },
      };
      const unresolved = [
        "foreign-property",
        "foreign-invoice",
        "unknown",
        "forbidden",
        "key-conflict",
        "clear-failure",
      ].includes(variant);
      if (variant === "lost-success")
        vi.mocked(api.decide).mockResolvedValue({
          ...current,
          id: "own-replayed-decision",
          outcome: "WAIVED",
          approved_amount: parseUsd("0"),
          charge: null,
        });
      else
        vi.mocked(api.decide).mockRejectedValue(
          new InvoiceClientError(
            variant === "unknown" ? 503 : variant === "forbidden" ? 403 : 409,
            variant === "key-conflict" ? "IDEMPOTENCY_KEY_REUSED" : "CONFLICT",
            variant === "unknown",
            null,
            [],
            "decision-conflict",
            current,
          ),
        );
      if (variant === "clear-failure")
        journal.clear.mockRejectedValue(new Error("storage unavailable"));
      render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId="actor"
          propertyId={propertyId}
        />,
      );
      if (variant === "first-confirmation") {
        await loadInvoice();
        fireEvent.click(
          screen.getByRole("button", { name: "Review late payment" }),
        );
        await screen.findByRole("heading", { name: "Late-payment review" });
        fill("Final decision", "WAIVED");
        fill("Late-payment decision reason", "reviewed waiver");
        fireEvent.click(
          screen.getByRole("button", { name: "Review final decision" }),
        );
        await confirm();
      } else
        fireEvent.click(
          await screen.findByRole("button", {
            name: "Retry exact saved request",
          }),
        );
      if (unresolved) {
        await screen.findByRole("alert");
        expect(await journal.load("actor")).not.toBeNull();
        expect(
          screen.queryByRole("region", { name: "Final late-payment decision" }),
        ).not.toBeInTheDocument();
        if (variant !== "clear-failure")
          expect(journal.clear).not.toHaveBeenCalled();
      } else {
        await screen.findByRole("heading", {
          name:
            variant === "lost-success"
              ? "Final decision: WAIVED"
              : "Final decision: REDUCED",
        });
        expect(await journal.load("actor")).toBeNull();
        expect(
          screen.queryByRole("region", { name: "Billing reconciliation" }),
        ).not.toBeInTheDocument();
        expect(journal.clear).toHaveBeenCalledWith(
          "actor",
          variant === "first-confirmation"
            ? expect.any(String)
            : "saved-decision",
        );
      }
      expect(api.decide).toHaveBeenCalledTimes(1);
      expect(api.adjust).not.toHaveBeenCalled();
    },
  );
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
  it.each(["command", "read"])(
    "clears obsolete %s feedback on retry review, cancellation and confirmation without changing identity",
    async (priorError) => {
      const { api, journal } = setup();
      const invoice = { ...resource(), property_id: property };
      const run = {
        id,
        property_id: property,
        run_kind: "RENT",
        logical_run_key: "rent/2026-09",
        business_date: "2026-08-25",
        status: "RETRYABLE",
        period: { start: "2026-09-01", end: "2026-09-30" },
        attempts: [],
        idempotency_key: key,
        requester_actor_id: actor,
        invocation_source: "API",
      };
      api.capabilities = vi.fn().mockResolvedValue(capabilities);
      vi.mocked(api.list).mockResolvedValue({
        items: [invoice],
        next_cursor: null,
        capabilities,
      });
      vi.mocked(api.get).mockResolvedValue(invoice);
      api.getRun = invoiceApi.getRun;
      api.run = invoiceApi.run;
      api.correctDraft = invoiceApi.correctDraft;
      const fetcher = vi
        .spyOn(globalThis, "fetch")
        .mockImplementation((path, init) => {
          if (typeof path === "string" && path.endsWith("/billing-runs/" + id))
            return Promise.resolve(new Response(JSON.stringify({ data: run })));
          if (init?.method === "POST")
            return Promise.resolve(
              new Response(
                JSON.stringify({ data: { ...run, status: "COMPLETED" } }),
              ),
            );
          return Promise.resolve(
            new Response(
              JSON.stringify({
                error: {
                  code:
                    priorError === "command"
                      ? "VALIDATION_ERROR"
                      : "SERVICE_UNAVAILABLE",
                  fields: ["reason"],
                },
                meta: { request_id: "obsolete-" + priorError },
              }),
              { status: priorError === "command" ? 422 : 503 },
            ),
          );
        });
      vi.spyOn(document, "cookie", "get").mockReturnValue(
        "__Host-prm_csrf=synthetic",
      );
      render(
        <InvoiceManagement
          api={api}
          journal={journal}
          actorId={actor}
          propertyId={property}
        />,
      );
      await loadInvoice();
      fill("Billing run ID", id);
      fireEvent.click(
        screen.getByRole("button", { name: "Inspect billing run" }),
      );
      await screen.findByRole("heading", {
        name: "Run rent/2026-09: RETRYABLE",
      });
      if (priorError === "command") {
        fill("Corrected authorized obligation ID", "approved");
        fill("Draft correction reason", "correct source");
        fireEvent.click(
          screen.getByRole("button", { name: "Review draft correction" }),
        );
        await confirm();
      } else {
        api.list = invoiceApi.list;
        fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
      }
      await screen.findByText("Support request ID: obsolete-" + priorError);
      expect(screen.getByText("reason: Check this value.")).toBeInTheDocument();
      const field = screen.getByLabelText("Draft correction reason");
      if (priorError === "command") {
        expect(field).toHaveAttribute("aria-invalid", "true");
        expect(field).toHaveAttribute(
          "aria-describedby",
          "billing-field-error-0",
        );
      } else expect(field).not.toHaveAttribute("aria-invalid");
      const assertFeedbackCleared = () => {
        expect(field).not.toHaveAttribute("aria-invalid");
        expect(field).not.toHaveAttribute("aria-describedby");
        expect(
          screen.queryByText("Support request ID: obsolete-" + priorError),
        ).not.toBeInTheDocument();
        expect(
          screen.queryByText("reason: Check this value."),
        ).not.toBeInTheDocument();
        expect(document.getElementById("billing-field-error-0")).toBeNull();
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      };
      const retry = screen.getByRole("button", {
        name: "Review retry of same billing run",
      });
      const beforeReview = fetcher.mock.calls.length;
      retry.focus();
      fireEvent.click(retry);
      assertFeedbackCleared();
      const firstPreview = screen.getByRole("dialog").textContent;
      expect(firstPreview).toContain(key);
      expect(firstPreview).toContain("rent/2026-09");
      fireEvent.click(
        screen.getByRole("button", { name: "Cancel billing action" }),
      );
      assertFeedbackCleared();
      expect(retry).toHaveFocus();
      expect(fetcher).toHaveBeenCalledTimes(beforeReview);
      expect(await journal.load(actor)).toBeNull();
      fireEvent.click(retry);
      assertFeedbackCleared();
      expect(screen.getByRole("dialog").textContent).toBe(firstPreview);
      await confirm();
      await screen.findByText(/Command confirmed/);
      assertFeedbackCleared();
      expect(fetcher).toHaveBeenCalledTimes(beforeReview + 1);
      const request = fetcher.mock.calls.at(-1);
      expect(request?.[0]).toBe(
        "/api/v1/properties/" + property + "/billing-runs/rent",
      );
      expect(request?.[1]?.headers).toMatchObject({ "Idempotency-Key": key });
      const input = {
        logical_run_key: "rent/2026-09",
        business_date: "2026-08-25",
        period_start: "2026-09-01",
        period_end: "2026-09-30",
      };
      const requestBody = request?.[1]?.body;
      if (typeof requestBody !== "string")
        throw new Error("Expected JSON request body");
      expect(JSON.parse(requestBody)).toEqual(input);
      expect(journal.begin).toHaveBeenLastCalledWith(actor, {
        key,
        command: { action: "run", propertyId: property, kind: "rent", input },
      });
      expect(await journal.load(actor)).toBeNull();
    },
  );
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

describe("V1-055 one-time charge", () => {
  const renderCharges = (grants: string[]) => {
    const made = setup("DRAFT", grants);
    render(
      <InvoiceManagement
        api={made.api}
        journal={made.journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    return made;
  };
  it("TEST-FE-629 records a Damage charge in exact cents only after confirmation and then offers the draft", async () => {
    const { api, journal } = renderCharges([
      "damage_charges.bill",
      "invoices.create",
    ]);
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByText("Authorized invoices loaded.");
    fill("One-time charge category", "DAMAGE_CHARGES");
    fill("One-time charge Customer ID", "customer-one");
    fill("One-time charge description", "Broken window");
    fill("One-time charge amount (USD)", "45.50");
    fill("One-time charge reason", "Tenant damage");
    fill("One-time charge evidence reference", "INSPECTION-9");
    fireEvent.click(
      screen.getByRole("button", { name: "Review one-time charge" }),
    );
    expect(api.recordOneTimeCharge).not.toHaveBeenCalled();
    await confirm();
    await waitFor(() => {
      expect(api.recordOneTimeCharge).toHaveBeenCalledTimes(1);
    });
    const [sentProperty, input, key] =
      vi.mocked(api.recordOneTimeCharge).mock.calls[0] ?? [];
    expect(sentProperty).toBe(propertyId);
    expect(input).toMatchObject({
      category: "DAMAGE_CHARGES",
      customer_id: "customer-one",
      lease_id: null,
      inspection_damage_finding_id: null,
      amount: { currency: "USD", minor_units: 4550 },
      evidence_reference: "INSPECTION-9",
    });
    expect(input?.charge_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(key).toBe(journal.begin.mock.calls[0]?.[1].key);
    await screen.findByRole("heading", { name: "Recorded one-time charge" });
    expect(journal.clear).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Review draft from this charge" }),
    );
    await confirm();
    await waitFor(() => {
      expect(api.create).toHaveBeenCalledWith(
        propertyId,
        input?.charge_id,
        expect.any(String),
      );
    });
  });
  it("TEST-FE-630 offers only the categories the server granted and hides the form without them", async () => {
    renderCharges(["invoices.create"]);
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByText("Authorized invoices loaded.");
    const category = screen.getByLabelText("One-time charge category");
    expect(
      within(category).queryByRole("option", { name: "DAMAGE_CHARGES" }),
    ).not.toBeInTheDocument();
    expect(
      within(category).getByRole("option", { name: "MISCELLANEOUS_CHARGES" }),
    ).toBeInTheDocument();
    cleanup();
    renderCharges(["invoices.issue"]);
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByText("Authorized invoices loaded.");
    expect(
      screen.queryByRole("button", { name: "Review one-time charge" }),
    ).not.toBeInTheDocument();
  });
  it("TEST-FE-631 refuses an invalid amount before any review or request", async () => {
    const { api } = renderCharges(["invoices.create"]);
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByText("Authorized invoices loaded.");
    fill("One-time charge Customer ID", "customer-one");
    fill("One-time charge description", "Cleaning");
    fill("One-time charge amount (USD)", "0");
    fill("One-time charge reason", "Extra cleaning");
    fill("One-time charge evidence reference", "TICKET-1");
    fireEvent.click(
      screen.getByRole("button", { name: "Review one-time charge" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.recordOneTimeCharge).not.toHaveBeenCalled();
  });
});

describe("V1-055 one-time charge due days", () => {
  const renderDueDays = (grants: string[]) => {
    const made = setup("DRAFT", grants);
    render(
      <InvoiceManagement
        api={made.api}
        journal={made.journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    return made;
  };
  const open = async () => {
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByText("Authorized invoices loaded.");
  };
  it("TEST-FE-633 changes the due days with the exact Property version only after confirmation and shows the new version", async () => {
    const { api, journal } = renderDueDays(["settings.manage"]);
    await open();
    fill("Due days for one-time charges (1 to 90)", "14");
    fill("Current Property version", "7");
    fill("Due days change reason", "Owner policy");
    fireEvent.click(
      screen.getByRole("button", { name: "Review due days change" }),
    );
    expect(api.setDueDays).not.toHaveBeenCalled();
    await confirm();
    await waitFor(() => {
      expect(api.setDueDays).toHaveBeenCalledWith(
        propertyId,
        14,
        "Owner policy",
        7,
        journal.begin.mock.calls[0]?.[1].key,
      );
    });
    await screen.findByText(/Current setting: 14 days, Property version 8\./);
    expect(screen.getByLabelText("Current Property version")).toHaveValue(8);
    expect(journal.clear).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-634 hides the due days form without settings.manage", async () => {
    renderDueDays(["invoices.issue"]);
    await open();
    expect(
      screen.queryByRole("button", { name: "Review due days change" }),
    ).not.toBeInTheDocument();
  });
  // Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): the due days are a Settings item.
  it("TEST-FE-685 hides the due days form with property.manage alone", async () => {
    renderDueDays(["property.manage"]);
    await open();
    expect(
      screen.queryByRole("button", { name: "Review due days change" }),
    ).not.toBeInTheDocument();
  });
  it("TEST-FE-635 refuses days outside 1 to 90 and a malformed version before any review", async () => {
    const { api } = renderDueDays(["settings.manage"]);
    await open();
    fill("Due days change reason", "Owner policy");
    for (const [days, version] of [
      ["0", "1"],
      ["91", "1"],
      ["14", "0"],
      ["14", "2147483648"],
    ] as const) {
      fill("Due days for one-time charges (1 to 90)", days);
      fill("Current Property version", version);
      fireEvent.click(
        screen.getByRole("button", { name: "Review due days change" }),
      );
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    }
    expect(api.setDueDays).not.toHaveBeenCalled();
  });
  it("TEST-FE-636 clears a retried due days command rejected for a stale Property version so the gate cannot stick", async () => {
    const { api } = setup("DRAFT", ["settings.manage"]);
    const journal = memoryJournal({
      key: "due-key",
      command: {
        action: "dueDays",
        propertyId,
        days: 20,
        reason: "Owner policy",
        propertyVersion: 7,
      },
    });
    vi.mocked(api.setDueDays).mockRejectedValue(
      new InvoiceClientError(412, "PRECONDITION_FAILED", false, 9),
    );
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
      expect(journal.clear).toHaveBeenCalledWith("actor", "due-key");
    });
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Retry exact saved request" }),
      ).not.toBeInTheDocument();
    });
  });
});

describe("V1-055 issue Due Date override", () => {
  it("TEST-FE-638 issues with an authorized Due Date and mandatory reason bound to the displayed version", async () => {
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
    fill("Authorized Due Date", "2026-09-20");
    fill("Due Date reason", "Customer pays on the 20th");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review invoice issuance with Due Date",
      }),
    );
    expect(api.issue).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("2026-09-20")).toBeInTheDocument();
    await confirm();
    await waitFor(() => {
      expect(api.issue).toHaveBeenCalledWith(
        "invoice-one",
        2,
        journal.begin.mock.calls[0]?.[1].key,
        {
          due_date: "2026-09-20",
          due_date_reason: "Customer pays on the 20th",
        },
      );
    });
    expect(journal.clear).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-639 refuses a Due Date without a reason before any review", async () => {
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
    fill("Authorized Due Date", "2026-09-20");
    fill("Due Date reason", "   ");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review invoice issuance with Due Date",
      }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.issue).not.toHaveBeenCalled();
  });
  it("TEST-FE-640 hides the Due Date issue form without invoices.issue", async () => {
    const { api, journal } = setup("DRAFT", ["invoices.create"]);
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
      screen.queryByRole("button", {
        name: "Review invoice issuance with Due Date",
      }),
    ).not.toBeInTheDocument();
  });
});

describe("V1-055 Initial Rent Due Date override", () => {
  const renderInitial = (grants: string[]) => {
    const made = setup("DRAFT", grants);
    render(
      <InvoiceManagement
        api={made.api}
        journal={made.journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    return made;
  };
  const open = async () => {
    await screen.findByText("Load authorized invoices to begin.");
    fireEvent.click(screen.getByRole("button", { name: "Load invoices" }));
    await screen.findByText("Authorized invoices loaded.");
  };
  it("TEST-FE-642 records an authorized Initial Rent Due Date with a sealed identity and shows the standard date", async () => {
    const { api, journal } = renderInitial(["invoices.issue"]);
    await open();
    fill("Initial Rent Lease ID", "lease-one");
    fill("Initial Rent authorized Due Date", "2026-09-10");
    fill("Initial Rent Due Date reason", "Customer is paid on the 10th");
    fireEvent.click(
      screen.getByRole("button", { name: "Review Initial Rent Due Date" }),
    );
    expect(api.setInitialRentDueDate).not.toHaveBeenCalled();
    await confirm();
    await waitFor(() => {
      expect(api.setInitialRentDueDate).toHaveBeenCalledTimes(1);
    });
    const [property, lease, input, key] =
      vi.mocked(api.setInitialRentDueDate).mock.calls[0] ?? [];
    expect(property).toBe(propertyId);
    expect(lease).toBe("lease-one");
    expect(input).toMatchObject({
      due_date: "2026-09-10",
      reason: "Customer is paid on the 10th",
    });
    expect(input?.override_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(key).toBe(journal.begin.mock.calls[0]?.[1].key);
    await screen.findByRole("heading", {
      name: "Recorded Initial Rent Due Date",
    });
    expect(screen.getByText(/standard date 2026-09-06/)).toBeInTheDocument();
    expect(journal.clear).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-643 hides the Initial Rent Due Date form without invoices.issue", async () => {
    renderInitial(["invoices.create"]);
    await open();
    expect(
      screen.queryByRole("button", { name: "Review Initial Rent Due Date" }),
    ).not.toBeInTheDocument();
  });
  it("TEST-FE-644 refuses a missing reason before any review or request", async () => {
    const { api } = renderInitial(["invoices.issue"]);
    await open();
    fill("Initial Rent Lease ID", "lease-one");
    fill("Initial Rent authorized Due Date", "2026-09-10");
    fill("Initial Rent Due Date reason", "   ");
    fireEvent.click(
      screen.getByRole("button", { name: "Review Initial Rent Due Date" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.setInitialRentDueDate).not.toHaveBeenCalled();
  });
  it("TEST-FE-645 keeps the saved request when the response does not match what was sent", async () => {
    const { api, journal } = renderInitial(["invoices.issue"]);
    vi.mocked(api.setInitialRentDueDate).mockResolvedValue({
      override_id: "another-override",
      property_id: propertyId,
      lease_id: "lease-one",
      due_date: "2026-09-10",
      proposed_due_date: "2026-09-06",
      reason: "r",
      evidence: {},
    });
    await open();
    fill("Initial Rent Lease ID", "lease-one");
    fill("Initial Rent authorized Due Date", "2026-09-10");
    fill("Initial Rent Due Date reason", "Customer is paid on the 10th");
    fireEvent.click(
      screen.getByRole("button", { name: "Review Initial Rent Due Date" }),
    );
    await confirm();
    await screen.findByRole("button", { name: "Retry exact saved request" });
    expect(journal.clear).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("heading", { name: "Recorded Initial Rent Due Date" }),
    ).not.toBeInTheDocument();
  });
});

describe("V1-055 Adjustment and run diagnostics text", () => {
  async function adjustWithRefusal(error: InvoiceClientError) {
    const { api, journal } = setup("UNPAID");
    vi.mocked(api.adjust).mockRejectedValue(error);
    render(
      <InvoiceManagement
        api={api}
        journal={journal}
        actorId="actor"
        propertyId={propertyId}
      />,
    );
    await loadInvoice();
    fill("Adjustment direction", "DEBIT");
    fill("Adjustment amount (USD)", "15.00");
    fill("Adjustment source reference", "approved-source");
    fill("Adjustment reason", "missed amount");
    fireEvent.click(screen.getByRole("button", { name: "Review adjustment" }));
    await confirm();
    return screen.findByRole("alert");
  }

  it("TEST-FE-667 explains that a debit on a fully paid line is refused and points to a one-time charge", async () => {
    const alert = await adjustWithRefusal(
      new InvoiceClientError(409, "INVOICE_LINE_FULLY_PAID", false),
    );
    expect(alert).toHaveTextContent("fully paid");
    expect(alert).toHaveTextContent("one-time charge");
  });

  it("TEST-FE-668 explains the two Adjustment balance rules when the server refuses the amount", async () => {
    const alert = await adjustWithRefusal(
      new InvoiceClientError(422, "VALIDATION_ERROR", false, null, ["amount"]),
    );
    expect(alert).toHaveTextContent("A debit needs a remaining balance");
    expect(alert).toHaveTextContent("a credit cannot exceed");
  });

  it("TEST-FE-669 shows plain run diagnostics with item counts and the reason each item was skipped", async () => {
    const { api, journal } = setup();
    vi.mocked(api.getRun).mockResolvedValue({
      id: "run-1",
      property_id: propertyId,
      run_kind: "UTILITIES",
      logical_run_key: "utilities-october",
      business_date: "2026-10-31",
      status: "SUCCEEDED",
      period: { start: "2026-10-01", end: "2026-10-31" },
      attempts: [
        {
          attempt_number: 1,
          outcome: "SUCCEEDED",
          diagnostic_code: null,
          items: [
            {
              source_kind: "UTILITY_CONSUMPTION_PERIOD",
              source_id: "period-1",
              period_start: "2026-10-01",
              period_end: "2026-10-31",
              outcome: "GENERATED",
              diagnostic_code: null,
              invoice_id: "invoice-1",
            },
            {
              source_kind: "UTILITY_CONSUMPTION_PERIOD",
              source_id: "period-2",
              period_start: "2026-10-01",
              period_end: "2026-10-31",
              outcome: "SKIPPED",
              diagnostic_code: "NOT_MOVED_IN",
              invoice_id: null,
            },
            {
              source_kind: "UTILITY_CONSUMPTION_PERIOD",
              source_id: "period-3",
              period_start: "2026-10-01",
              period_end: "2026-10-31",
              outcome: "SKIPPED",
              diagnostic_code: "PROPERTY_BORNE_CONSUMPTION",
              invoice_id: null,
            },
            {
              source_kind: "UTILITY_CONSUMPTION_PERIOD",
              source_id: "period-4",
              period_start: "2026-10-01",
              period_end: "2026-10-31",
              outcome: "SKIPPED",
              diagnostic_code: "A_NEW_CODE",
              invoice_id: null,
            },
          ],
        },
      ],
      evidence: {},
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
    fill("Billing run ID", "run-1");
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect billing run" }),
    );
    const region = await screen.findByRole("region", {
      name: "Run diagnostics",
    });
    expect(region).toHaveTextContent("Items: Generated 1, Skipped 3.");
    const table = within(region).getByRole("table", {
      name: "Run item outcomes",
    });
    expect(table).toHaveTextContent("had not moved in yet");
    expect(table).toHaveTextContent("the Property bears it");
    expect(table).toHaveTextContent("Diagnostic code A_NEW_CODE.");
    expect(
      within(region).getByText(/Attempt 1: Succeeded/),
    ).toBeInTheDocument();
  });
});
