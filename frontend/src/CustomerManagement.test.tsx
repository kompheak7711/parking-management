import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CustomerManagement,
  customerCreateRequestFingerprint,
  customerCreateResultFingerprint,
  customerReconciliationResultFingerprint,
  customerUpdateRequestFingerprint,
  normalizeCustomerText,
  type CustomerReconciliationRequirement,
} from "./CustomerManagement";
import {
  CustomerApi,
  CustomerConflictError,
  CustomerIdNumberInUseError,
  CustomerDetail,
  CustomerIdempotencyReuseError,
  CustomerRequestError,
  CustomerUnavailableError,
} from "./customerClient";

const customer: CustomerDetail = {
  customer_id: "customer-1",
  legal_name: "Dara Sok",
  phone_number: "012345678",
  email_address: "dara@example.com",
  contact_address: "Phnom Penh",
  memo: null,
  id_document_number: "N0123456",
  version: 1,
  active: true,
  deactivated_at: null,
  deactivation_reason: null,
  relationships: {
    reservations: [],
    primary_tenant_leases: [],
    signer_leases: [],
    occupancies: [],
    invoices: [],
    payments: [],
    customer_credit: [],
    refunds: [],
  },
  audit_history: [
    {
      event_id: "event-1",
      occurred_at: "2026-08-24T00:00:00Z",
      actor_id: "actor-1",
      action: "customer.created",
      reason: "Authorized Customer creation",
      previous_state: null,
      resulting_state: { customer_id: "customer-1" },
      correlation_id: "event-1",
      outcome: "SUCCEEDED",
    },
  ],
  audit_history_next_cursor: null,
  can_manage: true,
  can_deactivate: true,
  can_view_audit: true,
  audit_history_available: true,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function client(overrides: Partial<CustomerApi> = {}): CustomerApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: [
        {
          customer_id: customer.customer_id,
          legal_name: customer.legal_name,
          active: true,
          relationship_indicators: [],
        },
      ],
      next_cursor: null,
      can_manage: true,
    }),
    get: vi.fn().mockResolvedValue(customer),
    commandStatus: vi.fn().mockResolvedValue({
      recorded: true,
      customer,
    }),
    create: vi
      .fn()
      .mockResolvedValue({ ...customer, customer_id: "customer-2" }),
    update: vi
      .fn()
      .mockResolvedValue({ ...customer, legal_name: "Dara S.", version: 2 }),
    deactivate: vi.fn().mockResolvedValue({
      ...customer,
      active: false,
      version: 2,
      deactivated_at: "2026-08-24T01:00:00Z",
      deactivation_reason: "Duplicate entered distinctly",
      can_manage: true,
      can_deactivate: false,
    }),
    financialSummary: vi.fn().mockResolvedValue({
      source_status: "UNAVAILABLE_UNTIL_FINANCIAL_SOURCES_ARE_IMPLEMENTED",
      source_availability: {
        deposits: "UNAVAILABLE_NOT_IMPLEMENTED",
        invoices: "UNAVAILABLE_NOT_IMPLEMENTED",
        late_charges: "UNAVAILABLE_NOT_IMPLEMENTED",
        payments: "UNAVAILABLE_NOT_IMPLEMENTED",
        customer_credit: "UNAVAILABLE_NOT_IMPLEMENTED",
      },
      currency_summaries: [],
      deposit_liabilities: [],
      deposit_liabilities_page: { next_cursor: null, limit: 50 },
      deposit_aggregate: {
        count: 0,
        required_usd_cents: 0,
        received_usd_cents: 0,
        held_refundable_usd_cents: 0,
        outstanding_required_usd_cents: 0,
      },
      customer_credit_is_separate_from_deposit: true,
    }),
    ...overrides,
  };
}

async function loadCustomers(api: CustomerApi) {
  render(<CustomerManagement api={api} />);
  fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
    target: { value: "property-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
  await screen.findByText("Dara Sok");
}

describe("CustomerManagement", () => {
  it("TEST-FE-V059B-03 asks for the ID number and shows when an older Customer has none", async () => {
    const api = client({
      get: vi.fn().mockResolvedValue({ ...customer, id_document_number: null }),
    });
    await loadCustomers(api);
    const createInput = screen.getByLabelText("ID number / Passport number", {
      selector: "#customer-id-number",
    });
    expect(createInput).toBeRequired();
    expect(createInput).toHaveAttribute("maxlength", "64");
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    expect(
      await screen.findByText("Not recorded yet. Add it with Update Customer."),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#edit-customer-id-number",
      }),
    ).not.toBeRequired();
  });

  it("TEST-FE-V059B-04 keeps the update draft when another Customer has the ID number", async () => {
    const api = client({
      update: vi.fn().mockRejectedValue(
        new CustomerIdNumberInUseError([
          {
            customer_id: "customer-9",
            legal_name: "Srey Mom",
            active: true,
            relationship_indicators: [],
          },
        ]),
      ),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    const input = await screen.findByLabelText("ID number / Passport number", {
      selector: "#edit-customer-id-number",
    });
    expect(input).toBeRequired();
    fireEvent.change(input, { target: { value: "P 7788" } });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    expect(
      await screen.findByText(
        "Another Customer (Srey Mom) already has this ID number or passport number. Use the existing Customer.",
      ),
    ).toBeInTheDocument();
    expect(api.update).toHaveBeenCalledWith(
      expect.objectContaining({ customer_id: "customer-1" }),
      { id_document_number: "P 7788" },
      expect.any(String),
    );
    expect(
      screen.getByRole("button", { name: "Review existing Srey Mom" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-116 exposes the API Customer limits and phone format in both forms", async () => {
    const api = client();
    await loadCustomers(api);

    expect(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
    ).toHaveAttribute("maxlength", "255");
    expect(screen.getByLabelText("Phone (optional)")).toHaveAttribute(
      "maxlength",
      "100",
    );
    expect(screen.getByLabelText("Phone (optional)")).toHaveAttribute(
      "pattern",
      String.raw`(?=.*[0-9])[0-9+\(\). \-]*`,
    );
    expect(
      () =>
        new RegExp(
          screen.getByLabelText("Phone (optional)").getAttribute("pattern") ??
            "",
          "v",
        ),
    ).not.toThrow();
    expect(screen.getByLabelText("Email (optional)")).toHaveAttribute(
      "maxlength",
      "320",
    );
    expect(screen.getByLabelText("Contact address (optional)")).toHaveAttribute(
      "maxlength",
      "1000",
    );
    expect(screen.getByLabelText("Memo (optional)")).toHaveAttribute(
      "maxlength",
      "5000",
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    expect(
      screen.getByLabelText("Legal name", {
        selector: "#edit-customer-legal-name",
      }),
    ).toHaveAttribute("maxlength", "255");
    expect(
      screen.getByLabelText("Phone", { selector: "#edit-customer-phone" }),
    ).toHaveAttribute("pattern", String.raw`(?=.*[0-9])[0-9+\(\). \-]*`);
    expect(
      screen.getByLabelText("Email", { selector: "#edit-customer-email" }),
    ).toHaveAttribute("maxlength", "320");
    expect(
      screen.getByLabelText("Contact address", {
        selector: "#edit-customer-address",
      }),
    ).toHaveAttribute("maxlength", "1000");
    expect(
      screen.getByLabelText("Memo", { selector: "#edit-customer-memo" }),
    ).toHaveAttribute("maxlength", "5000");
    expect(screen.getByLabelText("Reason")).toHaveAttribute(
      "maxlength",
      "1000",
    );
  });

  it("TEST-FE-114 keeps Customer A's unsaved update and deactivation drafts when reconciling Customer B", async () => {
    for (const kind of ["update", "deactivate"] as const) {
      const reconciled = vi.fn();
      const recorded = {
        ...customer,
        customer_id: "customer-2",
        legal_name: "Recorded Customer",
        version: 2,
        active: kind === "update",
        deactivated_at: kind === "deactivate" ? "2026-08-24T02:00:00Z" : null,
        deactivation_reason:
          kind === "deactivate" ? "Recorded deactivation" : null,
      };
      const resultFingerprint = await customerReconciliationResultFingerprint(
        kind,
        recorded,
      );
      expect(resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
      const requirement: CustomerReconciliationRequirement = {
        actorId: "test-actor",
        commandNonce: `command-customer-b-${kind}`,
        kind,
        customerId: recorded.customer_id,
        propertyId: "property-1",
        resultFingerprint: resultFingerprint ?? "",
        requestFingerprint: "e".repeat(64),
      };
      const api = client({
        get: vi.fn((customerId: string) =>
          Promise.resolve(
            customerId === recorded.customer_id ? recorded : customer,
          ),
        ),
        commandStatus: vi.fn().mockResolvedValue({
          recorded: true,
          customer: recorded,
        }),
      });
      const view = render(
        <CustomerManagement
          actorId="test-actor"
          api={api}
          onReconciled={reconciled}
          reconciliationRequirement={null}
        />,
      );
      fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
        target: { value: "property-1" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
      fireEvent.click(
        await screen.findByRole("button", { name: "Open Dara Sok" }),
      );
      await screen.findByText("dara@example.com");
      if (kind === "update") {
        fireEvent.change(screen.getByLabelText("Memo"), {
          target: { value: "Customer A draft" },
        });
      } else {
        fireEvent.change(screen.getByLabelText("Reason"), {
          target: { value: "Customer A reason" },
        });
      }

      view.rerender(
        <CustomerManagement
          actorId="test-actor"
          api={api}
          onReconciled={reconciled}
          reconciliationRequirement={requirement}
        />,
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: "Check the prior Customer command status",
        }),
      );
      fireEvent.click(
        await screen.findByRole("button", {
          name: "I verified the prior Customer command result",
        }),
      );
      expect(
        screen.getByRole("heading", { name: "Customer detail: Dara Sok" }),
      ).toBeInTheDocument();
      expect(reconciled).toHaveBeenCalledWith(requirement);

      view.rerender(
        <CustomerManagement
          actorId="test-actor"
          api={api}
          onReconciled={reconciled}
          reconciliationRequirement={null}
        />,
      );
      if (kind === "update") {
        expect(screen.getByLabelText("Memo")).toHaveValue("Customer A draft");
      } else {
        expect(screen.getByLabelText("Reason")).toHaveValue(
          "Customer A reason",
        );
      }
      view.unmount();
    }
  });

  it("TEST-FE-123 preserves a different same-Customer draft after a recorded command is reconciled", async () => {
    const recorded = { ...customer, memo: "Other tab update", version: 2 };
    const patch = { memo: "Other tab update" };
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "12312312-3123-4123-8123-123123123123",
      kind: "update",
      customerId: customer.customer_id,
      propertyId: "property-1",
      resultFingerprint:
        (await customerReconciliationResultFingerprint("update", recorded)) ??
        "",
      requestFingerprint:
        (await customerUpdateRequestFingerprint(customer, patch)) ?? "",
      expectedVersion: 1,
      updateSource: patch,
    };
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: recorded,
      }),
      get: vi.fn().mockResolvedValueOnce(customer).mockResolvedValue(recorded),
    });
    const reconciled = vi.fn();
    const view = render(
      <CustomerManagement api={api} onReconciled={reconciled} />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    fireEvent.change(await screen.findByLabelText("Memo"), {
      target: { value: "Unrelated local memo" },
    });

    view.rerender(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    view.rerender(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={null}
      />,
    );

    expect(screen.getByLabelText("Memo")).toHaveValue("Unrelated local memo");
    expect(screen.getByRole("status")).toHaveTextContent(
      "different unsaved Customer values were preserved",
    );
  });

  it("TEST-FE-124 preserves a different same-Customer draft when the other command is absent", async () => {
    const patch = { memo: "Other tab update" };
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "12412412-4124-4124-8124-124124124124",
      kind: "update",
      customerId: customer.customer_id,
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint:
        (await customerUpdateRequestFingerprint(customer, patch)) ?? "",
      expectedVersion: 1,
      updateSource: patch,
    };
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        expired: false,
        customer: null,
      }),
    });
    const reconciled = vi.fn();
    const view = render(
      <CustomerManagement api={api} onReconciled={reconciled} />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    fireEvent.change(await screen.findByLabelText("Memo"), {
      target: { value: "Unrelated local memo" },
    });

    view.rerender(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer update was not committed",
      }),
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "different unsaved values for the same Customer",
    );
    expect(reconciled).not.toHaveBeenCalled();
  });

  it("TEST-FE-117 preserves an unrelated create draft after another tab's create is reconciled", async () => {
    const recorded = {
      ...customer,
      customer_id: "customer-recorded-elsewhere",
      legal_name: "Recorded Elsewhere",
    };
    const recordedSource = { legal_name: recorded.legal_name };
    const resultFingerprint = await customerCreateResultFingerprint(
      recorded.customer_id,
      recorded,
    );
    const requestFingerprint =
      await customerCreateRequestFingerprint(recordedSource);
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "command-recorded-elsewhere",
      kind: "create",
      customerId: recorded.customer_id,
      propertyId: "property-1",
      resultFingerprint: resultFingerprint ?? "",
      requestFingerprint: requestFingerprint ?? "",
      createSource: recordedSource,
    };
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: recorded,
      }),
      get: vi.fn().mockResolvedValue(recorded),
    });
    const reconciled = vi.fn();
    const view = render(
      <CustomerManagement
        actorId="test-actor"
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Unrelated local draft" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );

    view.rerender(
      <CustomerManagement
        actorId="test-actor"
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    await waitFor(() => {
      expect(reconciled).toHaveBeenCalledWith(requirement);
    });
    view.rerender(
      <CustomerManagement
        actorId="test-actor"
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={null}
      />,
    );

    expect(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("Unrelated local draft");
  });

  it("TEST-FE-118 explicitly restores sealed create input before an absent retry", async () => {
    const sealedSource = { legal_name: "Sealed absent Customer" };
    const requestFingerprint =
      await customerCreateRequestFingerprint(sealedSource);
    const resultFingerprint = await customerCreateResultFingerprint(
      "customer-sealed-absent",
      sealedSource,
    );
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "command-sealed-absent",
      kind: "create",
      customerId: "customer-sealed-absent",
      propertyId: "property-1",
      resultFingerprint: resultFingerprint ?? "",
      requestFingerprint: requestFingerprint ?? "",
      createSource: sealedSource,
    };
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
    });
    const reconciled = vi.fn();
    const view = render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Unrelated local draft" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    view.rerender(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer was not created",
      }),
    );
    expect(
      await screen.findByText(/unrelated create draft was preserved/),
    ).toBeInTheDocument();
    expect(reconciled).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Restore the exact Customer creation values",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "I verified the Customer was not created",
      }),
    );
    expect(
      await screen.findByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("Sealed absent Customer");
    expect(reconciled).not.toHaveBeenCalled();
  });

  it("TEST-FE-074 invalidates pending command callbacks on unmount", async () => {
    let finishCreate!: (value: CustomerDetail) => void;
    const pendingCreate = new Promise<CustomerDetail>((resolve) => {
      finishCreate = resolve;
    });
    const busy = vi.fn();
    const api = client({ create: vi.fn().mockReturnValue(pendingCreate) });
    const view = render(
      <CustomerManagement api={api} onCommandBusyChange={busy} />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "Pending Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    expect(busy).toHaveBeenLastCalledWith(true);

    view.unmount();
    const callsAfterUnmount = busy.mock.calls.length;
    finishCreate({ ...customer, customer_id: "customer-created" });
    await Promise.resolve();
    await Promise.resolve();

    expect(busy).toHaveBeenLastCalledWith(false);
    expect(busy).toHaveBeenCalledTimes(callsAfterUnmount);
  });

  it.each(["create", "update", "deactivate"] as const)(
    "TEST-FE-097 does not send a %s command when reconciliation reservation outlives unmount",
    async (kind) => {
      let finishReservation!: (reserved: boolean) => void;
      const reservation = new Promise<boolean>((resolve) => {
        finishReservation = resolve;
      });
      const required = vi.fn().mockReturnValue(reservation);
      const reconciled = vi.fn();
      const api = client();
      const view = render(
        <CustomerManagement
          api={api}
          onReconciled={reconciled}
          onReconciliationRequired={required}
        />,
      );
      fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
        target: { value: "property-1" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
      await screen.findByText("Dara Sok");
      if (kind === "create") {
        fireEvent.change(
          screen.getByLabelText("Legal name", {
            selector: "#customer-legal-name",
          }),
          { target: { value: "Pending Customer" } },
        );
        fireEvent.change(
          screen.getByLabelText("ID number / Passport number", {
            selector: "#customer-id-number",
          }),
          { target: { value: "N0123456" } },
        );
        fireEvent.click(
          screen.getByRole("button", { name: "Create Customer" }),
        );
      } else {
        fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
        await screen.findByText("dara@example.com");
        if (kind === "update") {
          fireEvent.change(screen.getByLabelText("Memo"), {
            target: { value: "Pending update" },
          });
          fireEvent.click(
            screen.getByRole("button", { name: "Update Customer" }),
          );
        } else {
          fireEvent.change(screen.getByLabelText("Reason"), {
            target: { value: "Pending deactivation" },
          });
          fireEvent.click(
            screen.getByRole("button", { name: "Deactivate Customer" }),
          );
        }
      }
      await waitFor(() => {
        expect(required).toHaveBeenCalledOnce();
      });

      view.unmount();
      finishReservation(true);
      await Promise.resolve();
      await Promise.resolve();

      expect(api[kind]).not.toHaveBeenCalled();
      expect(reconciled).toHaveBeenCalledOnce();
    },
  );

  it("TEST-FE-098 omits unchanged oversized legacy fields from an update", async () => {
    const legacy = { ...customer, legal_name: "L".repeat(10_000) };
    const api = client({
      get: vi.fn().mockResolvedValue(legacy),
      update: vi.fn().mockResolvedValue({
        ...legacy,
        memo: "Allowed memo change",
        version: 2,
      }),
    });
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Allowed memo change" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    await waitFor(() => {
      expect(api.update).toHaveBeenCalledWith(
        legacy,
        { memo: "Allowed memo change" },
        expect.any(String),
      );
    });
  });

  it("TEST-FE-119 preserves untouched invalid legacy contact values during an unrelated update", async () => {
    const legacy = {
      ...customer,
      legal_name: "\tLegacy Customer\u00a0",
      phone_number: "012/345",
      email_address: "user@a..com",
      contact_address: "\u00a0Historic address\t",
    };
    const api = client({
      get: vi.fn().mockResolvedValue(legacy),
      update: vi.fn().mockResolvedValue({
        ...legacy,
        memo: "Allowed memo change",
        version: 2,
      }),
    });
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByDisplayValue("user@a..com");

    const phone = screen.getByLabelText("Phone", {
      selector: "#edit-customer-phone",
    });
    const email = screen.getByLabelText("Email", {
      selector: "#edit-customer-email",
    });
    expect(phone).not.toHaveAttribute("pattern");
    expect(email).toHaveAttribute("type", "text");

    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Allowed memo change" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    await waitFor(() => {
      expect(api.update).toHaveBeenCalledWith(
        legacy,
        { memo: "Allowed memo change" },
        expect.any(String),
      );
    });
  });

  it("TEST-FE-140 preserves an untouched multiline contact address during an unrelated update", async () => {
    const multiline = {
      ...customer,
      contact_address: "Building A\r\nFloor 2\r\nPhnom Penh",
    };
    const api = client({
      get: vi.fn().mockResolvedValue(multiline),
      update: vi.fn().mockResolvedValue({
        ...multiline,
        memo: "Allowed memo change",
        version: 2,
      }),
    });
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByDisplayValue(/Building A/);
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Allowed memo change" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    await waitFor(() => {
      expect(api.update).toHaveBeenCalledWith(
        multiline,
        { memo: "Allowed memo change" },
        expect.any(String),
      );
    });
  });

  it("TEST-FE-120 enables strict browser constraints when a legacy contact field is edited", async () => {
    const legacy = {
      ...customer,
      phone_number: "012/345",
      email_address: "user@a..com",
    };
    const api = client({ get: vi.fn().mockResolvedValue(legacy) });
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByDisplayValue("user@a..com");

    fireEvent.change(
      screen.getByLabelText("Phone", { selector: "#edit-customer-phone" }),
      { target: { value: "012345678" } },
    );
    fireEvent.change(
      screen.getByLabelText("Email", { selector: "#edit-customer-email" }),
      { target: { value: "legacy@example.com" } },
    );

    expect(
      screen.getByLabelText("Phone", { selector: "#edit-customer-phone" }),
    ).toHaveAttribute("pattern", String.raw`(?=.*[0-9])[0-9+\(\). \-]*`);
    expect(
      screen.getByLabelText("Email", { selector: "#edit-customer-email" }),
    ).toHaveAttribute("type", "email");
  });

  it("TEST-FE-031 keeps contact data out of the minimized list until explicit navigation", async () => {
    const api = client();
    await loadCustomers(api);

    expect(screen.queryByText("012345678")).not.toBeInTheDocument();
    expect(screen.queryByText("dara@example.com")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));

    expect(await screen.findByText("012345678")).toBeInTheDocument();
    expect(screen.getByText("dara@example.com")).toBeInTheDocument();
    expect(screen.getByText(/customer\.created/)).toBeInTheDocument();
    expect(
      screen.getByText("Reason: Authorized Customer creation"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Deposit liabilities are not available yet; no zero balance is implied. Other financial sources are also unavailable.",
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-032 creates a distinct Customer only through an explicit control", async () => {
    const api = client();
    await loadCustomers(api);

    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      {
        target: { value: "Dara Sok" },
      },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N7654321" } },
    );
    fireEvent.click(
      screen.getByLabelText(
        "Confirm a distinct person after reviewing a possible match",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    await waitFor(() => {
      expect(api.create).toHaveBeenCalledWith(
        "property-1",
        expect.any(String),
        expect.objectContaining({
          legal_name: "Dara Sok",
          id_document_number: "N7654321",
          confirmed_distinct: true,
        }),
        expect.any(String),
      );
    });
  });

  it("TEST-FE-033 uses the loaded version for updates and preserves history on deactivation", async () => {
    const api = client();
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("012345678");

    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#edit-customer-legal-name",
      }),
      {
        target: { value: "Dara S." },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    await waitFor(() => {
      expect(api.update).toHaveBeenCalledWith(
        customer,
        expect.objectContaining({ legal_name: "Dara S." }),
        expect.any(String),
      );
    });

    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Duplicate entered distinctly" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate Customer" }),
    );
    await waitFor(() => {
      expect(api.deactivate).toHaveBeenCalled();
    });
    expect(
      await screen.findByText(
        "Customer deactivated without deleting identity or audit history. Reload Customer detail to refresh the current history view.",
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-034 fails closed without exposing management controls", async () => {
    const api = client({
      list: vi.fn().mockRejectedValue(new CustomerUnavailableError()),
    });
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));

    expect(
      await screen.findByText(
        "Customer access is unavailable for this session.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-035 continues through the opaque Customer cursor", async () => {
    const api = client({
      list: vi
        .fn()
        .mockResolvedValueOnce({
          items: [
            {
              customer_id: customer.customer_id,
              legal_name: customer.legal_name,
              active: true,
              relationship_indicators: [],
            },
          ],
          next_cursor: "opaque-next",
          can_manage: true,
        })
        .mockResolvedValueOnce({
          items: [
            {
              customer_id: "customer-2",
              legal_name: "Sokha Chan",
              active: true,
              relationship_indicators: [],
            },
          ],
          next_cursor: null,
          can_manage: true,
        }),
    });
    await loadCustomers(api);
    fireEvent.click(
      screen.getByRole("button", { name: "Load more Customers" }),
    );

    expect(await screen.findByText("Sokha Chan")).toBeInTheDocument();
    expect(api.list).toHaveBeenLastCalledWith("property-1", {
      cursor: "opaque-next",
    });
  });

  it("TEST-FE-125 removes stale management actions when a later page reports revoked access", async () => {
    const api = client({
      list: vi
        .fn()
        .mockResolvedValueOnce({
          items: [
            {
              customer_id: customer.customer_id,
              legal_name: customer.legal_name,
              active: true,
              relationship_indicators: [],
            },
          ],
          next_cursor: "opaque-next",
          can_manage: true,
        })
        .mockResolvedValueOnce({
          items: [],
          next_cursor: null,
          can_manage: false,
        }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByRole("button", { name: "Update Customer" });
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Unsaved stale action" },
    });
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Sensitive create draft" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load more Customers" }),
    );

    expect(
      await screen.findByText(/Management access changed/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Update Customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Deactivate Customer" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Memo")).not.toBeInTheDocument();
    expect(
      screen.queryByDisplayValue("Sensitive create draft"),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-126 blocks normalized blank Customer names and deactivation reasons locally", async () => {
    const api = client();
    await loadCustomers(api);
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: " \u00a0 " } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    expect(api.create).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Legal name must contain a non-whitespace character",
    );

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByLabelText("Memo");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#edit-customer-legal-name",
      }),
      { target: { value: " \u00a0 " } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    expect(api.update).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Legal name must contain a non-whitespace character",
    );

    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: " \u00a0 " },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate Customer" }),
    );
    expect(api.deactivate).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Deactivation reason must contain a non-whitespace character",
    );
  });

  it("TEST-FE-036 offers explicit navigation to a possible reused Customer", async () => {
    const api = client({
      create: vi.fn().mockRejectedValue(
        new CustomerConflictError([
          {
            customer_id: customer.customer_id,
            legal_name: customer.legal_name,
            active: true,
            relationship_indicators: [],
          },
        ]),
      ),
    });
    await loadCustomers(api);
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "Dara S." } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    const review = await screen.findByRole("button", {
      name: "Review existing Dara Sok",
    });
    expect(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("Dara S.");
    fireEvent.click(review);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(customer.customer_id);
    });
  });

  it("TEST-FE-040 clears sensitive Customer state when mutation access is revoked", async () => {
    const api = client({
      update: vi.fn().mockRejectedValue(new CustomerUnavailableError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Revoked update" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    expect(
      await screen.findByText(
        "Customer access is unavailable for this session.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("dara@example.com")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-041 exposes reuse candidates returned by an update conflict", async () => {
    const api = client({
      update: vi.fn().mockRejectedValue(
        new CustomerConflictError([
          {
            customer_id: "customer-2",
            legal_name: "Existing Dara",
            active: true,
            relationship_indicators: [],
          },
        ]),
      ),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Possible duplicate update" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    expect(
      await screen.findByRole("button", {
        name: "Review existing Existing Dara",
      }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-042 invalidates rows and cursors when the search changes", async () => {
    const api = client({
      list: vi.fn().mockResolvedValue({
        items: [
          {
            customer_id: customer.customer_id,
            legal_name: customer.legal_name,
            active: true,
            relationship_indicators: [],
          },
        ],
        next_cursor: "opaque-next",
        can_manage: true,
      }),
    });
    await loadCustomers(api);
    expect(
      screen.getByRole("button", { name: "Load more Customers" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search Customers"), {
      target: { value: "Sokha" },
    });

    expect(screen.queryByText("Dara Sok")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Load more Customers" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-043 resets the paginated list after Customer creation", async () => {
    const api = client({
      list: vi.fn().mockResolvedValue({
        items: [
          {
            customer_id: customer.customer_id,
            legal_name: customer.legal_name,
            active: true,
            relationship_indicators: [],
          },
        ],
        next_cursor: "opaque-next",
        can_manage: true,
      }),
    });
    await loadCustomers(api);
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "New Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    await screen.findByText(
      "Customer created without assigning a permanent type.",
    );
    expect(api.financialSummary).toHaveBeenCalledWith("customer-2");

    expect(
      screen.queryByRole("button", { name: "Load more Customers" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Minimized Customer identity and relationship indicators",
      ),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-044 locks Property and filter inputs while a mutation is pending", async () => {
    let completeCreate: ((value: CustomerDetail) => void) | undefined;
    const pendingCreate = new Promise<CustomerDetail>((resolve) => {
      completeCreate = resolve;
    });
    const api = client({ create: vi.fn().mockReturnValue(pendingCreate) });
    await loadCustomers(api);
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "Pending Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    expect(
      screen.getByLabelText("Customer Property identifier"),
    ).toBeDisabled();
    expect(screen.getByLabelText("Search Customers")).toBeDisabled();
    for (const label of [
      "Phone (optional)",
      "Email (optional)",
      "Contact address (optional)",
      "Memo (optional)",
      "Confirm a distinct person after reviewing a possible match",
    ]) {
      expect(screen.getByLabelText(label)).toBeDisabled();
    }
    expect(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toBeDisabled();

    completeCreate?.({ ...customer, customer_id: "customer-pending" });
    await screen.findByText(
      "Customer created without assigning a permanent type.",
    );
  });

  it("TEST-FE-045 clears loaded Customer data when a paginated read loses access", async () => {
    const api = client({
      list: vi
        .fn()
        .mockResolvedValueOnce({
          items: [
            {
              customer_id: customer.customer_id,
              legal_name: customer.legal_name,
              active: true,
              relationship_indicators: [],
            },
          ],
          next_cursor: "opaque-next",
          can_manage: true,
        })
        .mockRejectedValueOnce(new CustomerUnavailableError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.click(
      screen.getByRole("button", { name: "Load more Customers" }),
    );

    await screen.findByText("Customer access is unavailable for this session.");
    expect(screen.queryByText("dara@example.com")).not.toBeInTheDocument();
    expect(screen.queryByText("Dara Sok")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-046 resets rows and cursor after a Customer update", async () => {
    const api = client({
      list: vi.fn().mockResolvedValue({
        items: [
          {
            customer_id: customer.customer_id,
            legal_name: customer.legal_name,
            active: true,
            relationship_indicators: [],
          },
        ],
        next_cursor: "opaque-next",
        can_manage: true,
      }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Updated Customer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    await screen.findByText(
      "Customer source fields updated. Reload Customer detail to refresh its current audit history.",
    );

    expect(
      screen.queryByRole("button", { name: "Load more Customers" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Minimized Customer identity and relationship indicators",
      ),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-122 marks cached audit history stale when a stable mutation response omits the new event", async () => {
    const api = client({
      update: vi.fn().mockResolvedValue({
        ...customer,
        memo: "Updated Customer",
        version: 2,
        audit_history: [],
        audit_history_next_cursor: null,
        audit_history_available: false,
      }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    expect(await screen.findByText("Actor: actor-1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Updated Customer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    await screen.findByText(
      "Customer source fields updated. Reload Customer detail to refresh its current audit history.",
    );
    expect(screen.queryByText("Actor: actor-1")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Audit history is temporarily unavailable; the Customer command outcome shown above is unchanged.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No audit events recorded."),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-047 renders memo and deactivation metadata for read-only detail", async () => {
    const deactivated = {
      ...customer,
      memo: "Identity retained for historical leases",
      active: false,
      deactivated_at: "2026-08-24T01:00:00Z",
      deactivation_reason: "Duplicate entered distinctly",
      can_manage: false,
      can_deactivate: false,
    };
    const api = client({
      get: vi.fn().mockResolvedValue(deactivated),
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: deactivated,
      }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));

    expect(
      await screen.findByText("Identity retained for historical leases"),
    ).toBeInTheDocument();
    expect(screen.getByText("2026-08-24T01:00:00Z")).toBeInTheDocument();
    expect(
      screen.getByText("Duplicate entered distinctly"),
    ).toBeInTheDocument();
  });

  it("TEST-FE-048 follows Customer audit-history continuation", async () => {
    const olderEvent = {
      ...customer.audit_history[0],
      event_id: "event-older",
      action: "customer.imported",
    };
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce({
          ...customer,
          audit_history_next_cursor: "history-next",
        })
        .mockResolvedValueOnce({
          ...customer,
          audit_history: [olderEvent],
          audit_history_next_cursor: null,
        }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText(/customer\.created/);
    fireEvent.click(
      screen.getByRole("button", { name: "Load older Customer audit history" }),
    );

    expect(await screen.findByText(/customer\.imported/)).toBeInTheDocument();
    expect(api.get).toHaveBeenLastCalledWith("customer-1", "history-next");
    expect(
      screen.queryByRole("button", {
        name: "Load older Customer audit history",
      }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-055 adopts fresh Customer state and clears history when audit access changes", async () => {
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce({
          ...customer,
          audit_history_next_cursor: "history-next",
        })
        .mockResolvedValueOnce({
          ...customer,
          active: false,
          version: 2,
          deactivated_at: "2026-08-24T02:00:00Z",
          deactivation_reason: "Server-side deactivation",
          audit_history: [],
          audit_history_next_cursor: null,
          can_manage: false,
          can_deactivate: false,
          can_view_audit: false,
          audit_history_available: false,
        }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText(/customer\.created/);
    fireEvent.click(
      screen.getByRole("button", { name: "Load older Customer audit history" }),
    );

    expect(
      await screen.findByText(
        "Audit history requires separate audit-view access.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/customer\.created/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Update Customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Deactivate Customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Server-side deactivation")).toBeInTheDocument();
  });

  it("TEST-FE-057 restarts audit history when Customer state changes between pages", async () => {
    const changedEvent = {
      ...customer.audit_history[0],
      event_id: "event-changed",
      action: "customer.updated",
    };
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce({
          ...customer,
          audit_history_next_cursor: "history-next",
        })
        .mockResolvedValueOnce({
          ...customer,
          version: 2,
          audit_history: [],
          audit_history_next_cursor: null,
        })
        .mockResolvedValueOnce({
          ...customer,
          version: 2,
          audit_history: [changedEvent],
          audit_history_next_cursor: null,
        }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText(/customer\.created/);
    fireEvent.click(
      screen.getByRole("button", { name: "Load older Customer audit history" }),
    );

    expect(await screen.findByText(/customer\.updated/)).toBeInTheDocument();
    expect(screen.queryByText(/customer\.created/)).not.toBeInTheDocument();
    expect(api.get).toHaveBeenNthCalledWith(2, "customer-1", "history-next");
    expect(api.get).toHaveBeenNthCalledWith(3, "customer-1");
    expect(
      screen.queryByRole("button", { name: "Open Dara Sok" }),
    ).not.toBeInTheDocument();
  });

  it.each(["update", "deactivate"] as const)(
    "TEST-FE-099 preserves loaded audit history and its cursor after %s",
    async (kind) => {
      const prior = { ...customer, audit_history_next_cursor: "history-next" };
      const commandEvent = {
        ...customer.audit_history[0],
        event_id: `event-${kind}`,
        action: `customer.${kind === "update" ? "updated" : "deactivated"}`,
      };
      const result = {
        ...prior,
        ...(kind === "update"
          ? { memo: "Updated memo" }
          : {
              active: false,
              deactivation_reason: "Authorized deactivation",
              can_manage: true,
              can_deactivate: false,
            }),
        version: 2,
        audit_history: [commandEvent],
        audit_history_next_cursor: null,
      };
      const api = client({
        get: vi.fn().mockResolvedValue(prior),
        update: vi.fn().mockResolvedValue(result),
        deactivate: vi.fn().mockResolvedValue(result),
      });
      render(<CustomerManagement api={api} />);
      fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
        target: { value: "property-1" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
      fireEvent.click(
        await screen.findByRole("button", { name: "Open Dara Sok" }),
      );
      await screen.findByText("dara@example.com");
      if (kind === "update") {
        fireEvent.change(screen.getByLabelText("Memo"), {
          target: { value: "Updated memo" },
        });
        fireEvent.click(
          screen.getByRole("button", { name: "Update Customer" }),
        );
      } else {
        fireEvent.change(screen.getByLabelText("Reason"), {
          target: { value: "Authorized deactivation" },
        });
        fireEvent.click(
          screen.getByRole("button", { name: "Deactivate Customer" }),
        );
      }

      expect(
        await screen.findByText(new RegExp(commandEvent.action)),
      ).toBeInTheDocument();
      expect(screen.getByText(/customer\.created/)).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: "Load older Customer audit history",
        }),
      ).toBeInTheDocument();
    },
  );

  it("TEST-FE-058 keeps Customer detail available when financial summary fails", async () => {
    const api = client({
      financialSummary: vi.fn().mockRejectedValue(new CustomerRequestError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));

    expect(await screen.findByText("dara@example.com")).toBeInTheDocument();
    expect(
      screen.getByText(/Financial summary is temporarily unavailable/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Update Customer" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-050 reloads stale updates while preserving entered source values", async () => {
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValueOnce({
          ...customer,
          legal_name: "Server-updated name",
          version: 2,
        }),
      update: vi.fn().mockRejectedValue(new CustomerConflictError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Preserve this unsent memo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    await screen.findByText(/Current server data was reloaded/);
    expect(
      screen.getByLabelText("Legal name", {
        selector: "#edit-customer-legal-name",
      }),
    ).toHaveValue("Dara Sok");
    expect(screen.getByLabelText("Memo")).toHaveValue(
      "Preserve this unsent memo",
    );
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByRole("button", { name: "Open Dara Sok" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-056 preserves intentionally cleared optional fields after a stale reload", async () => {
    const initial = { ...customer, memo: "Existing memo" };
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(initial)
        .mockResolvedValueOnce({
          ...initial,
          phone_number: "server-phone",
          email_address: "server@example.com",
          contact_address: "Server address",
          memo: "Server memo",
          version: 2,
        }),
      update: vi.fn().mockRejectedValue(new CustomerConflictError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByDisplayValue("Existing memo");
    for (const label of ["Phone", "Email", "Contact address", "Memo"]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: "" } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    await screen.findByText(/Current server data was reloaded/);
    for (const label of ["Phone", "Email", "Contact address", "Memo"]) {
      expect(screen.getByLabelText(label)).toHaveValue("");
    }
  });

  it("TEST-FE-051 reloads stale deactivation while preserving its reason", async () => {
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValueOnce({ ...customer, version: 2 }),
      deactivate: vi.fn().mockRejectedValue(new CustomerConflictError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Preserve this deactivation reason" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate Customer" }),
    );

    await screen.findByText(/deactivation reason is preserved/);
    expect(screen.getByLabelText("Reason")).toHaveValue(
      "Preserve this deactivation reason",
    );
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByRole("button", { name: "Open Dara Sok" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-052 renders complete authorized Customer audit evidence", async () => {
    const api = client();
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));

    expect(await screen.findByText("Actor: actor-1")).toBeInTheDocument();
    expect(screen.getByText("Correlation ID: event-1")).toBeInTheDocument();
    expect(screen.getByText(/customer_id/)).toBeInTheDocument();
    expect(screen.getByText(/SUCCEEDED/)).toBeInTheDocument();
  });

  it("TEST-FE-054 presents validation fields and correlation details", async () => {
    const api = client({
      list: vi
        .fn()
        .mockRejectedValue(
          new CustomerRequestError(
            "The request did not match the required schema.",
            ["query"],
            "request-validation-2",
          ),
        ),
    });
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));

    expect(
      await screen.findByText(/Invalid field\(s\): query/),
    ).toHaveTextContent("Correlation ID: request-validation-2");
  });

  it("TEST-FE-059 clears Customer detail when summary reports access loss", async () => {
    const api = client({
      financialSummary: vi
        .fn()
        .mockRejectedValue(new CustomerUnavailableError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));

    expect(
      await screen.findByText(
        "Customer access is unavailable for this session.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("dara@example.com")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-208 renders separate authoritative Customer Deposit liabilities", async () => {
    const api = client({
      financialSummary: vi.fn().mockResolvedValue({
        source_status: "PARTIALLY_AVAILABLE",
        source_availability: {
          deposits: "AVAILABLE",
          invoices: "UNAVAILABLE_NOT_IMPLEMENTED",
          late_charges: "UNAVAILABLE_NOT_IMPLEMENTED",
          payments: "UNAVAILABLE_NOT_IMPLEMENTED",
          customer_credit: "UNAVAILABLE_NOT_IMPLEMENTED",
        },
        currency_summaries: [],
        deposit_liabilities: [
          {
            deposit_id: "deposit-1",
            deposit_type: "SECURITY",
            reservation_id: "reservation-1",
            lease_id: "lease-1",
            pet_approval_id: null,
            required_usd_cents: Number.MAX_SAFE_INTEGER,
            received_usd_cents: 50000,
            held_refundable_usd_cents: 45000,
            outstanding_required_usd_cents: 0,
          },
        ],
        deposit_liabilities_page: { next_cursor: null, limit: 50 },
        deposit_aggregate: {
          count: 1,
          required_usd_cents: 50000,
          received_usd_cents: 50000,
          held_refundable_usd_cents: 45000,
          outstanding_required_usd_cents: 0,
        },
        customer_credit_is_separate_from_deposit: true,
      }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));

    expect(
      await screen.findByText(/SECURITY Deposit deposit-1/),
    ).toHaveTextContent(
      "required $90,071,992,547,409.91, received $500.00, held $450.00, outstanding $0.00; source Reservation reservation-1",
    );
    expect(
      screen.getByText(
        "Customer credit and deposit liability remain separate balances.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Invoice, late-charge, unallocated-Payment, and Customer Credit summaries are not available yet/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0 currency summary/)).not.toBeInTheDocument();
  });

  it("TEST-FE-060 restores an update draft after reviewing a reuse candidate", async () => {
    const possibleMatch = {
      ...customer,
      customer_id: "customer-2",
      legal_name: "Existing Dara",
    };
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValueOnce(possibleMatch)
        .mockResolvedValueOnce(customer),
      update: vi.fn().mockRejectedValue(
        new CustomerConflictError([
          {
            customer_id: possibleMatch.customer_id,
            legal_name: possibleMatch.legal_name,
            active: true,
            relationship_indicators: [],
          },
        ]),
      ),
    });
    const dirty = vi.fn();
    render(<CustomerManagement api={api} onDirtyStateChange={dirty} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Preserve while reviewing reuse" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    await screen.findByRole("button", {
      name: "Review existing Existing Dara",
    });
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Latest draft while considering reuse" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review existing Existing Dara",
      }),
    );
    await screen.findByText("Customer detail: Existing Dara");
    expect(dirty).toHaveBeenLastCalledWith(true);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Unrelated Existing Dara draft" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Return to pending update for Dara Sok",
      }),
    );

    expect(confirm).toHaveBeenCalledOnce();
    expect(
      screen.getByText("Customer detail: Existing Dara"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Memo")).toHaveValue(
      "Unrelated Existing Dara draft",
    );

    confirm.mockReturnValue(true);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Return to pending update for Dara Sok",
      }),
    );

    expect(await screen.findByLabelText("Memo")).toHaveValue(
      "Latest draft while considering reuse",
    );
  });

  it("TEST-FE-095 preserves the original draft when a reuse candidate is updated", async () => {
    const possibleMatch = {
      ...customer,
      customer_id: "customer-2",
      legal_name: "Existing Dara",
    };
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValueOnce(possibleMatch)
        .mockResolvedValueOnce(customer),
      update: vi
        .fn()
        .mockRejectedValueOnce(
          new CustomerConflictError([
            {
              customer_id: possibleMatch.customer_id,
              legal_name: possibleMatch.legal_name,
              active: true,
              relationship_indicators: [],
            },
          ]),
        )
        .mockResolvedValueOnce({
          ...possibleMatch,
          memo: "Candidate corrected separately",
          version: 2,
        }),
    });
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Original pending update" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review existing Existing Dara",
      }),
    );
    await screen.findByText("Customer detail: Existing Dara");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Candidate corrected separately" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    const returnToOriginal = await screen.findByRole("button", {
      name: "Return to pending update for Dara Sok",
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(returnToOriginal);

    expect(await screen.findByLabelText("Memo")).toHaveValue(
      "Original pending update",
    );
  });

  it("TEST-FE-078 confirms before a successful create clears another Customer draft", async () => {
    const api = client();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Preserve this update" },
    });
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "New Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );

    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    expect(confirm).toHaveBeenCalledOnce();
    expect(api.create).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Memo")).toHaveValue("Preserve this update");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Customer creation was cancelled",
    );

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));
    await waitFor(() => {
      expect(api.create).toHaveBeenCalledOnce();
    });
  });

  it("TEST-FE-061 preserves the Customer state filter across bounded pages", async () => {
    const api = client({
      list: vi
        .fn()
        .mockResolvedValueOnce({
          items: [
            {
              customer_id: customer.customer_id,
              legal_name: customer.legal_name,
              active: false,
              relationship_indicators: [],
            },
          ],
          next_cursor: "deactivated-next",
          can_manage: true,
        })
        .mockResolvedValueOnce({
          items: [],
          next_cursor: null,
          can_manage: true,
        }),
    });
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.change(screen.getByLabelText("Customer state"), {
      target: { value: "deactivated" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.click(
      screen.getByRole("button", { name: "Load more Customers" }),
    );

    expect(api.list).toHaveBeenNthCalledWith(1, "property-1", {
      active: false,
    });
    expect(api.list).toHaveBeenNthCalledWith(2, "property-1", {
      active: false,
      cursor: "deactivated-next",
    });
  });

  it("TEST-FE-062 clears another Customer's draft after confirmed creation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = client({
      update: vi.fn().mockRejectedValue(
        new CustomerConflictError([
          {
            customer_id: "customer-existing",
            legal_name: "Existing Customer",
            active: true,
            relationship_indicators: [],
          },
        ]),
      ),
      create: vi.fn().mockResolvedValue({
        ...customer,
        customer_id: "customer-created",
        legal_name: "Created Customer",
        memo: null,
      }),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Draft belonging only to Dara" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    await screen.findByRole("button", {
      name: "Review existing Existing Customer",
    });

    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "Created Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    await screen.findByText("Customer detail: Created Customer");
    expect(confirm).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("Memo")).toHaveValue("");
    expect(
      screen.queryByRole("button", {
        name: "Return to pending update for Dara Sok",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Review existing Existing Customer",
      }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-063 removes a deactivated Customer from active-only results", async () => {
    const api = client();
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.change(screen.getByLabelText("Customer state"), {
      target: { value: "active" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "No longer active" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate Customer" }),
    );

    await screen.findByText(
      "Customer deactivated without deleting identity or audit history. Reload Customer detail to refresh the current history view.",
    );
    expect(
      screen.queryByRole("button", { name: "Open Dara Sok" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-064 locks update fields while the Customer command is pending", async () => {
    let completeUpdate: ((value: CustomerDetail) => void) | undefined;
    const pendingUpdate = new Promise<CustomerDetail>((resolve) => {
      completeUpdate = resolve;
    });
    const api = client({ update: vi.fn().mockReturnValue(pendingUpdate) });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Pending update" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    for (const label of [
      "Phone",
      "Email",
      "Contact address",
      "Memo",
      "Confirm distinct after reviewing a possible match",
    ]) {
      expect(screen.getByLabelText(label)).toBeDisabled();
    }
    expect(
      screen.getByLabelText("Legal name", {
        selector: "#edit-customer-legal-name",
      }),
    ).toBeDisabled();

    completeUpdate?.({ ...customer, version: 2 });
    await screen.findByText(
      "Customer source fields updated. Reload Customer detail to refresh its current audit history.",
    );
  });

  it("TEST-FE-065 locks the deactivation reason while the command is pending", async () => {
    let completeDeactivation: ((value: CustomerDetail) => void) | undefined;
    const pendingDeactivation = new Promise<CustomerDetail>((resolve) => {
      completeDeactivation = resolve;
    });
    const api = client({
      deactivate: vi.fn().mockReturnValue(pendingDeactivation),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Pending reason" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate Customer" }),
    );

    expect(screen.getByLabelText("Reason")).toBeDisabled();

    completeDeactivation?.({
      ...customer,
      active: false,
      version: 2,
      can_manage: true,
      can_deactivate: false,
    });
    await screen.findByText(
      "Customer deactivated without deleting identity or audit history. Reload Customer detail to refresh the current history view.",
    );
  });

  it("TEST-FE-066 keeps dirty Customer values when view invalidation is declined", async () => {
    const api = client();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await loadCustomers(api);
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "Unsent Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.change(screen.getByLabelText("Search Customers"), {
      target: { value: "new search" },
    });

    expect(confirm).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("Search Customers")).toHaveValue("");
    expect(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("Unsent Customer");
    expect(screen.getByRole("status")).toHaveTextContent(
      "unsaved Customer values were preserved",
    );
  });

  it("TEST-FE-067 displays an update draft when a stale Customer became deactivated", async () => {
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValueOnce({
          ...customer,
          active: false,
          version: 2,
          can_manage: true,
          can_deactivate: false,
        }),
      update: vi.fn().mockRejectedValue(new CustomerConflictError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Visible preserved memo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    await screen.findByText(/Customer became deactivated/);
    expect(
      screen.getByRole("heading", {
        name: "Preserved unsent Customer command",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Visible preserved memo")).toBeInTheDocument();
  });

  it("TEST-FE-068 displays a deactivation draft after a lifecycle conflict", async () => {
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValueOnce({
          ...customer,
          active: false,
          version: 2,
          can_manage: true,
          can_deactivate: false,
        }),
      deactivate: vi.fn().mockRejectedValue(new CustomerConflictError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Visible preserved reason" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate Customer" }),
    );

    await screen.findByText(/Customer was already deactivated/);
    expect(
      screen.getByText("Draft deactivation reason: Visible preserved reason"),
    ).toBeInTheDocument();
  });

  it("TEST-FE-069 preserves other dirty forms after one Customer command succeeds", async () => {
    const api = client();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "Unsent create draft" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Unsent deactivation draft" },
    });
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Submitted update" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    await screen.findByText(
      "Customer source fields updated. Reload Customer detail to refresh its current audit history.",
    );

    expect(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
    ).toHaveValue("Unsent create draft");
    expect(screen.getByLabelText("Reason")).toHaveValue(
      "Unsent deactivation draft",
    );
    fireEvent.change(screen.getByLabelText("Search Customers"), {
      target: { value: "discard attempt" },
    });
    expect(confirm).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("Search Customers")).toHaveValue("");
  });

  it("TEST-FE-081 preserves the exact ambiguous update reconciliation target", async () => {
    const required = vi.fn();
    const reconciled = vi.fn();
    const attempted = { ...customer, memo: "Possibly updated", version: 2 };
    const api = client({
      update: vi
        .fn()
        .mockRejectedValue(
          new CustomerIdempotencyReuseError("request-idempotency-reuse"),
        ),
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: attempted,
      }),
      get: vi.fn().mockResolvedValueOnce(customer).mockResolvedValue(attempted),
    });
    const rendered = render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        onReconciliationRequired={required}
      />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Possibly updated" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    expect(
      await screen.findByText(/Customer update outcome is unknown/),
    ).toBeInTheDocument();
    const requirement = required.mock.lastCall?.[0] as
      | CustomerReconciliationRequirement
      | undefined;
    expect(requirement).toMatchObject({
      actorId: "test-actor",
      kind: "update",
      customerId: "customer-1",
      propertyId: "property-1",
    });
    expect(requirement?.commandNonce.length).toBeGreaterThan(0);
    expect(requirement?.resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(requirement?.updateSource).toEqual({ memo: "Possibly updated" });
    expect(reconciled).not.toHaveBeenCalled();
    expect(requirement).toBeDefined();
    if (requirement === undefined) return;
    reconciled.mockImplementation(() => {
      rendered.rerender(
        <CustomerManagement
          api={api}
          onReconciled={reconciled}
          onReconciliationRequired={required}
          reconciliationRequirement={null}
        />,
      );
    });
    rendered.rerender(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        onReconciliationRequired={required}
        reconciliationRequirement={requirement}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    expect(await screen.findByLabelText("Memo")).toHaveValue(
      "Possibly updated",
    );
    expect(
      screen.queryByText("Preserved unsent Customer command"),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-082 only offers reconciliation after the exact Customer detail loads", async () => {
    const reconciled = vi.fn();
    const deactivated = {
      ...customer,
      active: false,
      version: 2,
      deactivated_at: "2026-08-24T01:00:00Z",
      deactivation_reason: "Duplicate entered distinctly",
      can_manage: true,
      can_deactivate: false,
    };
    const resultFingerprint = await customerReconciliationResultFingerprint(
      "deactivate",
      deactivated,
    );
    expect(resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValue(deactivated),
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: deactivated,
      }),
    });
    render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "command-nonce-deactivate",
          kind: "deactivate",
          customerId: "customer-1",
          propertyId: "property-1",
          resultFingerprint: resultFingerprint ?? "",
          requestFingerprint: resultFingerprint ?? "",
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    expect(
      screen.queryByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    expect(screen.getByLabelText("Customer Property identifier")).toHaveValue(
      "property-1",
    );
    expect(reconciled).toHaveBeenCalledOnce();
  });

  it("TEST-FE-083 preserves the exact ambiguous deactivation reconciliation target", async () => {
    const required = vi.fn();
    const reconciled = vi.fn();
    const deactivated = {
      ...customer,
      active: false,
      version: 2,
      deactivated_at: "2026-08-24T01:00:00Z",
      deactivation_reason: "Possibly deactivated",
      can_manage: true,
      can_deactivate: false,
    };
    const api = client({
      deactivate: vi
        .fn()
        .mockRejectedValue(
          new CustomerRequestError("Outcome unknown", [], null, true),
        ),
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: deactivated,
      }),
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValue(deactivated),
    });
    const rendered = render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        onReconciliationRequired={required}
      />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Possibly deactivated" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate Customer" }),
    );

    expect(
      await screen.findByText(/Customer deactivation outcome is unknown/),
    ).toBeInTheDocument();
    const requirement = required.mock.lastCall?.[0] as
      | CustomerReconciliationRequirement
      | undefined;
    expect(requirement).toMatchObject({
      actorId: "test-actor",
      kind: "deactivate",
      customerId: "customer-1",
      propertyId: "property-1",
    });
    expect(requirement?.commandNonce.length).toBeGreaterThan(0);
    expect(requirement?.resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(requirement).toBeDefined();
    if (requirement === undefined) return;
    reconciled.mockImplementation(() => {
      rendered.rerender(
        <CustomerManagement
          api={api}
          onReconciled={reconciled}
          onReconciliationRequired={required}
          reconciliationRequirement={null}
        />,
      );
    });
    rendered.rerender(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        onReconciliationRequired={required}
        reconciliationRequirement={requirement}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    expect(await screen.findByText("Possibly deactivated")).toBeInTheDocument();
    expect(
      screen.queryByText("Preserved unsent Customer command"),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-096 reconciles the recorded update after a later authorized mutation", async () => {
    const attempted = {
      ...customer,
      legal_name: "Dara Updated",
      version: 2,
    };
    const resultFingerprint = await customerReconciliationResultFingerprint(
      "update",
      attempted,
    );
    expect(resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
    const current = {
      ...attempted,
      legal_name: "Dara Later Deactivated",
      active: false,
      version: 3,
      deactivated_at: "2026-08-24T02:00:00Z",
      deactivation_reason: "Later authorized deactivation",
      can_manage: true,
      can_deactivate: false,
    };
    const reconciled = vi.fn();
    const api = client({
      get: vi.fn().mockResolvedValue(current),
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: attempted,
      }),
    });
    render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "command-nonce-update",
          kind: "update",
          customerId: "customer-1",
          propertyId: "property-restored",
          resultFingerprint: resultFingerprint ?? "",
          requestFingerprint: resultFingerprint ?? "",
        }}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );

    expect(
      await screen.findByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Customer detail: Dara Later Deactivated",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Update Customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Deactivate Customer" }),
    ).not.toBeInTheDocument();
    expect(reconciled).not.toHaveBeenCalled();
  });

  it("TEST-FE-127 rejects a recorded result that does not match the pending command", async () => {
    const attempted = {
      ...customer,
      legal_name: "Dara Attempted",
      version: 2,
    };
    const resultFingerprint = await customerReconciliationResultFingerprint(
      "update",
      attempted,
    );
    const reconciled = vi.fn();
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: { ...attempted, legal_name: "Different Result" },
      }),
    });
    render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "command-nonce-mismatch",
          kind: "update",
          customerId: "customer-1",
          propertyId: "property-1",
          resultFingerprint: resultFingerprint ?? "",
          requestFingerprint: resultFingerprint ?? "",
        }}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );

    expect(
      await screen.findByText(/does not match the exact pending command/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    ).not.toBeInTheDocument();
    expect(reconciled).not.toHaveBeenCalled();
  });

  it("TEST-FE-128 retains an authoritatively absent command identity for its explicit retry", async () => {
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
    });
    const createSource = {
      legal_name: "Retried Customer",
      id_document_number: "N0123456",
    };
    const requestFingerprint =
      await customerCreateRequestFingerprint(createSource);
    const resultFingerprint = await customerCreateResultFingerprint(
      "customer-absent",
      createSource,
    );
    expect(requestFingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "command-nonce-absent",
      kind: "create",
      customerId: "customer-absent",
      propertyId: "property-1",
      resultFingerprint: resultFingerprint ?? "",
      requestFingerprint: requestFingerprint ?? "",
      createSource,
    };
    const reconciled = vi.fn();
    const rendered = render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );
    reconciled.mockImplementation(() => {
      rendered.rerender(
        <CustomerManagement
          api={api}
          onReconciled={reconciled}
          reconciliationRequirement={null}
        />,
      );
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer was not created",
      }),
    );
    expect(reconciled).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Retried Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    await waitFor(() => {
      expect(api.create).toHaveBeenCalledWith(
        "property-1",
        "customer-absent",
        expect.objectContaining({ legal_name: "Retried Customer" }),
        "command-nonce-absent",
      );
    });
    expect(reconciled).toHaveBeenCalledOnce();
  });

  it("TEST-FE-130 discards an exact retry identity when another tab clears its durable gate", async () => {
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
    });
    const createSource = { legal_name: "Abandoned retry" };
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "command-nonce-cleared-elsewhere",
      kind: "create",
      customerId: "customer-cleared-elsewhere",
      propertyId: "property-1",
      resultFingerprint:
        (await customerCreateResultFingerprint(
          "customer-cleared-elsewhere",
          createSource,
        )) ?? "",
      requestFingerprint:
        (await customerCreateRequestFingerprint(createSource)) ?? "",
      createSource,
    };
    const rendered = render(
      <CustomerManagement
        actorId="test-actor"
        api={api}
        reconciliationRequirement={requirement}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer was not created",
      }),
    );

    rendered.rerender(
      <CustomerManagement
        actorId="test-actor"
        api={api}
        reconciliationRequirement={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Fresh Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    await waitFor(() => {
      expect(api.create).toHaveBeenCalledOnce();
    });
    expect(api.create).not.toHaveBeenCalledWith(
      "property-1",
      "customer-cleared-elsewhere",
      expect.anything(),
      "command-nonce-cleared-elsewhere",
    );
  });

  it("TEST-FE-131 removes creation controls when Customer detail reports downgraded access", async () => {
    const api = client({
      get: vi.fn().mockResolvedValue({
        ...customer,
        can_manage: false,
        can_deactivate: false,
      }),
    });
    await loadCustomers(api);
    expect(
      screen.getByRole("button", { name: "Create Customer" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText(
      "Customer detail loaded through explicit navigation.",
    );

    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-121 reconciles an expired successful command through its archived audit result", async () => {
    const reconciled = vi.fn();
    const archived = {
      ...customer,
      memo: "Possibly committed",
      version: 2,
    };
    const resultFingerprint = await customerReconciliationResultFingerprint(
      "update",
      archived,
    );
    expect(resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        expired: true,
        customer: archived,
      }),
      get: vi.fn().mockResolvedValue(archived),
    });
    render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "12121212-1212-4212-8212-121212121212",
          kind: "update",
          customerId: customer.customer_id,
          propertyId: "property-1",
          resultFingerprint: resultFingerprint ?? "",
          requestFingerprint: "a".repeat(64),
          expectedVersion: 1,
          updateSource: { memo: "Possibly committed" },
        }}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );

    expect(
      await screen.findByText(
        /original result was verified.*explicitly confirm/i,
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    expect(reconciled).toHaveBeenCalledOnce();
  });

  it("TEST-FE-102 blocks an altered create from reusing an absent command identity", async () => {
    const originalSource = { legal_name: "Original Customer" };
    const requestFingerprint =
      await customerCreateRequestFingerprint(originalSource);
    const resultFingerprint = await customerCreateResultFingerprint(
      "customer-original",
      originalSource,
    );
    expect(requestFingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
    });
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "88888888-8888-4888-8888-888888888888",
      kind: "create",
      customerId: "customer-original",
      propertyId: "property-1",
      resultFingerprint: resultFingerprint ?? "",
      requestFingerprint: requestFingerprint ?? "",
      createSource: originalSource,
    };
    const reconciled = vi.fn();
    const rendered = render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );
    reconciled.mockImplementation(() => {
      rendered.rerender(
        <CustomerManagement
          api={api}
          onReconciled={reconciled}
          reconciliationRequirement={null}
        />,
      );
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer was not created",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Altered Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    expect(
      await screen.findByText(
        /can only be retried with its original Customer values/,
      ),
    ).toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("TEST-FE-100 describes an absent update without claiming Customer creation failed", async () => {
    const resultFingerprint = await customerReconciliationResultFingerprint(
      "update",
      { ...customer, memo: "Attempted memo", version: 2 },
    );
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
    });
    render(
      <CustomerManagement
        api={api}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "command-nonce-absent-update",
          kind: "update",
          customerId: "customer-1",
          propertyId: "property-1",
          resultFingerprint: resultFingerprint ?? "",
          requestFingerprint: resultFingerprint ?? "",
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    const confirmation = await screen.findByRole("button", {
      name: "I verified the Customer update was not committed",
    });
    expect(
      screen.queryByRole("button", {
        name: "I verified the Customer was not created",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(confirmation);
    expect(
      await screen.findByText(/prior Customer update was not committed/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-104 blocks an absent update retry when only the reuse decision changes", async () => {
    const attempted = { ...customer, memo: "Attempted memo", version: 2 };
    const resultFingerprint = await customerReconciliationResultFingerprint(
      "update",
      attempted,
    );
    const requestFingerprint = await customerUpdateRequestFingerprint(
      customer,
      { memo: "Attempted memo" },
    );
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
    });
    render(
      <CustomerManagement
        api={api}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "command-nonce-update-reuse",
          kind: "update",
          customerId: "customer-1",
          propertyId: "property-1",
          resultFingerprint: resultFingerprint ?? "",
          requestFingerprint: requestFingerprint ?? "",
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer update was not committed",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByText("dara@example.com");
    fireEvent.change(screen.getByLabelText("Memo"), {
      target: { value: "Attempted memo" },
    });
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Confirm distinct after reviewing a possible match",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    expect(
      await screen.findByText(/original Customer values and reuse decision/),
    ).toBeInTheDocument();
    expect(api.update).not.toHaveBeenCalled();
  });

  it("TEST-FE-105 preserves a dirty create draft when another tab adds a command gate", async () => {
    const api = client();
    const rendered = render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Preserved draft" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.change(screen.getByLabelText("Email (optional)"), {
      target: { value: "preserved@example.com" },
    });
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Confirm a distinct person after reviewing a possible match",
      }),
    );

    const gate: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "command-nonce-other-tab",
      kind: "update",
      customerId: "customer-1",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
    };
    rendered.rerender(
      <CustomerManagement api={api} reconciliationRequirement={gate} />,
    );
    expect(
      screen.queryByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).not.toBeInTheDocument();
    rendered.rerender(
      <CustomerManagement api={api} reconciliationRequirement={null} />,
    );

    expect(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("Preserved draft");
    expect(screen.getByLabelText("Email (optional)")).toHaveValue(
      "preserved@example.com",
    );
    expect(
      screen.getByRole("checkbox", {
        name: "Confirm a distinct person after reviewing a possible match",
      }),
    ).toBeChecked();
  });

  it("TEST-FE-112 treats confirmation-only Customer edits as a local no-op", async () => {
    const api = client();
    render(<CustomerManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Dara Sok" }),
    );
    await screen.findByText("dara@example.com");
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Confirm distinct after reviewing a possible match",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "No approved Customer source field changed; no command was sent.",
    );
    expect(api.update).not.toHaveBeenCalled();
  });

  it("TEST-FE-106 keeps the durable command gate after an absent result is confirmed", async () => {
    const createSource = { legal_name: "Durable retry" };
    const requestFingerprint =
      await customerCreateRequestFingerprint(createSource);
    const resultFingerprint = await customerCreateResultFingerprint(
      "customer-durable-retry",
      createSource,
    );
    const reconciled = vi.fn();
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
    });
    render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "command-nonce-durable-retry",
          kind: "create",
          customerId: "customer-durable-retry",
          propertyId: "property-1",
          resultFingerprint: resultFingerprint ?? "",
          requestFingerprint: requestFingerprint ?? "",
          createSource,
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer was not created",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");

    expect(reconciled).not.toHaveBeenCalled();
    expect(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
    ).toHaveValue("Durable retry");
    expect(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-107 uses the server's Unicode boundary normalization for command fingerprints", async () => {
    expect(normalizeCustomerText("\u0085Dara Sok\u0085")).toBe("Dara Sok");
    expect(normalizeCustomerText("\ufeffDara Sok\ufeff")).toBe(
      "\ufeffDara Sok\ufeff",
    );
    expect(
      await customerCreateRequestFingerprint({
        legal_name: "\u0085Dara Sok\u0085",
        memo: "\u0085note\u0085",
      }),
    ).toBe(
      await customerCreateRequestFingerprint({
        legal_name: "Dara Sok",
        memo: "note",
      }),
    );
    expect(
      await customerCreateRequestFingerprint({
        legal_name: "Dara Sok",
        email_address: "user@EXAMPLE.COM",
      }),
    ).toBe(
      await customerCreateRequestFingerprint({
        legal_name: "Dara Sok",
        email_address: "user@example.com",
      }),
    );
  });

  it("TEST-FE-113 restores sealed exact update input after an absent command", async () => {
    const updateSource = {
      legal_name: customer.legal_name,
      phone_number: customer.phone_number,
      email_address: customer.email_address,
      contact_address: customer.contact_address,
      memo: "Durable restored update",
      confirmed_distinct: true,
    };
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "13131313-1313-4313-8313-131313131313",
      kind: "update",
      customerId: customer.customer_id,
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
      expectedVersion: 1,
      updateSource,
    };
    const api = client({
      commandStatus: vi
        .fn()
        .mockResolvedValue({ recorded: false, customer: null }),
    });
    render(
      <CustomerManagement api={api} reconciliationRequirement={requirement} />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer update was not committed",
      }),
    );

    expect(await screen.findByLabelText("Memo")).toHaveValue(
      "Durable restored update",
    );
    expect(
      screen.getByRole("checkbox", {
        name: "Confirm distinct after reviewing a possible match",
      }),
    ).toBeChecked();
  });

  it("TEST-FE-108 clears an absent stale-version gate for a fresh Customer decision", async () => {
    const current = { ...customer, memo: "Changed elsewhere", version: 2 };
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
      get: vi.fn().mockResolvedValue(current),
    });
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "99999999-9999-4999-8999-999999999999",
      kind: "update",
      customerId: customer.customer_id,
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
      expectedVersion: 1,
    };
    const reconciled = vi.fn();
    const rendered = render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );
    reconciled.mockImplementation(() => {
      rendered.rerender(
        <CustomerManagement
          api={api}
          onReconciled={reconciled}
          reconciliationRequirement={null}
        />,
      );
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer update was not committed",
      }),
    );

    expect(
      await screen.findByText(/original version is now stale/),
    ).toBeInTheDocument();
    expect(reconciled).toHaveBeenCalledWith(requirement);
    expect(screen.getAllByText("Changed elsewhere").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "Update Customer" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-132 reports that a stale-version gate remains active when durable clearance fails", async () => {
    const current = { ...customer, memo: "Changed elsewhere", version: 2 };
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "13213213-2132-4132-8132-132132132132",
      kind: "update",
      customerId: customer.customer_id,
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
      expectedVersion: 1,
    };
    const reconciled = vi.fn().mockResolvedValue(false);
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        customer: null,
      }),
      get: vi.fn().mockResolvedValue(current),
    });
    render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer update was not committed",
      }),
    );

    expect(
      await screen.findByText(/durable command gate could not be cleared/),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Customer commands remain blocked",
    );
    expect(reconciled).toHaveBeenCalledWith(requirement);
  });

  it("TEST-FE-084 requires the exact server-verifiable identity for creation reconciliation", async () => {
    const reconciled = vi.fn();
    const api = client({
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        customer: {
          ...customer,
          customer_id: "customer-command-1",
        },
      }),
    });
    const requestFingerprint = await customerCreateRequestFingerprint({
      ...customer,
      confirmed_distinct: true,
    });
    const resultFingerprint = await customerCreateResultFingerprint(
      "customer-command-1",
      customer,
    );
    expect(requestFingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(resultFingerprint).toMatch(/^[0-9a-f]{64}$/);
    render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "command-nonce-create",
          kind: "create",
          customerId: "customer-command-1",
          propertyId: "property-1",
          resultFingerprint: resultFingerprint ?? "",
          requestFingerprint: requestFingerprint ?? "",
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    );
    expect(api.commandStatus).toHaveBeenCalledWith(
      "property-1",
      "customer-command-1",
      "create",
      "command-nonce-create",
    );
    expect(reconciled).toHaveBeenCalledOnce();
  });

  it("TEST-FE-091 ignores proof returned for a superseded reconciliation command", async () => {
    let resolveFirst!: (value: {
      recorded: boolean;
      customer: CustomerDetail | null;
    }) => void;
    const firstProof = new Promise<{
      recorded: boolean;
      customer: CustomerDetail | null;
    }>((resolve) => {
      resolveFirst = resolve;
    });
    const api = client({
      commandStatus: vi
        .fn()
        .mockReturnValueOnce(firstProof)
        .mockResolvedValueOnce({ recorded: false, customer: null }),
    });
    const firstRequirement = {
      actorId: "test-actor",
      commandNonce: "command-nonce-first",
      kind: "create" as const,
      customerId: "customer-command-1",
      propertyId: "property-1",
      resultFingerprint: "b".repeat(64),
      requestFingerprint: "a".repeat(64),
    };
    const secondRequirement = {
      ...firstRequirement,
      commandNonce: "command-nonce-second",
      customerId: "customer-command-2",
    };
    const rendered = render(
      <CustomerManagement
        api={api}
        reconciliationRequirement={firstRequirement}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );

    rendered.rerender(
      <CustomerManagement
        api={api}
        reconciliationRequirement={secondRequirement}
      />,
    );
    resolveFirst({
      recorded: true,
      customer: { ...customer, customer_id: firstRequirement.customerId },
    });
    await waitFor(() => {
      expect(
        screen.queryByRole("button", {
          name: "I verified the prior Customer command result",
        }),
      ).not.toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    expect(
      await screen.findByRole("button", {
        name: "I verified the Customer was not created",
      }),
    ).toBeInTheDocument();
    expect(api.commandStatus).toHaveBeenLastCalledWith(
      "property-1",
      "customer-command-2",
      "create",
      "command-nonce-second",
    );
  });

  it("TEST-FE-090 rejects a mutation when another tab already reserved the actor gate", async () => {
    const api = client();
    render(
      <CustomerManagement api={api} onReconciliationRequired={() => false} />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Blocked duplicate" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Customer" }));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Another tab already has an unresolved Customer command",
      );
    });
    expect(api.create).not.toHaveBeenCalled();
  });

  it("TEST-FE-070 clears a create draft after confirmed navigation", async () => {
    const api = client();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await loadCustomers(api);
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "Discarded Customer" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    fireEvent.change(screen.getByLabelText("Search Customers"), {
      target: { value: "new scope" },
    });

    expect(confirm).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    expect(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
    ).toHaveValue("");
  });

  it("TEST-FE-133 purges loaded Customer state when command-status access is revoked", async () => {
    const api = client({
      commandStatus: vi.fn().mockRejectedValue(new CustomerUnavailableError()),
    });
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "revoked-command-status",
      kind: "update",
      customerId: customer.customer_id,
      propertyId: "property-1",
      resultFingerprint: "a".repeat(64),
      requestFingerprint: "b".repeat(64),
      expectedVersion: customer.version,
      updateSource: { legal_name: "Unsent privileged draft" },
    };
    const rendered = render(
      <CustomerManagement api={api} reconciliationRequirement={null} />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#edit-customer-legal-name",
      }),
      { target: { value: "Unsent privileged draft" } },
    );

    rendered.rerender(
      <CustomerManagement api={api} reconciliationRequirement={requirement} />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );

    await waitFor(() => {
      expect(screen.queryByText("dara@example.com")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Dara Sok")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "command identity is not currently available",
    );
  });

  it("TEST-FE-134 purges loaded Customer state when absent-proof reload access is revoked", async () => {
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockRejectedValueOnce(new CustomerUnavailableError()),
      commandStatus: vi
        .fn()
        .mockResolvedValue({ recorded: false, customer: null }),
    });
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "revoked-proof-reload",
      kind: "update",
      customerId: customer.customer_id,
      propertyId: "property-1",
      resultFingerprint: "c".repeat(64),
      requestFingerprint: "d".repeat(64),
      expectedVersion: customer.version,
      updateSource: { legal_name: "Sealed prior update" },
    };
    render(
      <CustomerManagement api={api} reconciliationRequirement={requirement} />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer update was not committed",
      }),
    );

    await waitFor(() => {
      expect(screen.queryByText("dara@example.com")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Dara Sok")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "current Customer version could not be verified",
    );
  });

  async function assertReadOnlyConflictReload(kind: "update" | "deactivate") {
    const readOnly = {
      ...customer,
      can_manage: false,
      can_deactivate: false,
    };
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValueOnce(readOnly),
      update: vi.fn().mockRejectedValue(new CustomerConflictError()),
      deactivate: vi.fn().mockRejectedValue(new CustomerConflictError()),
    });
    await loadCustomers(api);
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.change(
      screen.getByLabelText("Legal name", {
        selector: "#customer-legal-name",
      }),
      { target: { value: "Privileged create draft" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    if (kind === "update") {
      fireEvent.change(screen.getByLabelText("Memo"), {
        target: { value: "Privileged update draft" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Update Customer" }));
    } else {
      fireEvent.change(screen.getByLabelText("Reason"), {
        target: { value: "Privileged deactivation draft" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Deactivate Customer" }),
      );
    }

    await screen.findByText(/Customer management access changed/);
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByDisplayValue("Privileged create draft"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Preserved unsent Customer command"),
    ).not.toBeInTheDocument();
  }

  it("TEST-FE-136 purges privileged drafts when a successful update conflict reload is read-only", async () => {
    await assertReadOnlyConflictReload("update");
  });

  it("TEST-FE-138 purges privileged drafts when a successful deactivation conflict reload is read-only", async () => {
    await assertReadOnlyConflictReload("deactivate");
  });

  it("TEST-FE-137 keeps the command gate and purges drafts after a successful read-only reconciliation reload", async () => {
    const reconciled = vi.fn();
    const api = client({
      get: vi
        .fn()
        .mockResolvedValueOnce(customer)
        .mockResolvedValueOnce({
          ...customer,
          can_manage: false,
          can_deactivate: false,
        }),
      commandStatus: vi.fn().mockResolvedValue({
        recorded: false,
        expired: false,
        customer: null,
      }),
    });
    render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={{
          actorId: "test-actor",
          commandNonce: "read-only-reconciliation",
          kind: "update",
          customerId: customer.customer_id,
          propertyId: "property-1",
          resultFingerprint: "e".repeat(64),
          requestFingerprint: "f".repeat(64),
          expectedVersion: customer.version,
          updateSource: { memo: "Privileged sealed update" },
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.click(screen.getByRole("button", { name: "Open Dara Sok" }));
    await screen.findByText("dara@example.com");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "I verified the Customer update was not committed",
      }),
    );

    await screen.findByText(/Customer management access changed/);
    expect(reconciled).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-139 purges privileged drafts when a recorded-command reconciliation reload is read-only", async () => {
    const reconciled = vi.fn();
    const commandResult = {
      ...customer,
      memo: "Recorded command result",
      version: 2,
    };
    const resultFingerprint = await customerReconciliationResultFingerprint(
      "update",
      commandResult,
    );
    const api = client({
      get: vi.fn().mockResolvedValue({
        ...commandResult,
        can_manage: false,
        can_deactivate: false,
      }),
      commandStatus: vi.fn().mockResolvedValue({
        recorded: true,
        expired: false,
        customer: commandResult,
      }),
    });
    const requirement: CustomerReconciliationRequirement = {
      actorId: "test-actor",
      commandNonce: "read-only-recorded-reconciliation",
      kind: "update",
      customerId: customer.customer_id,
      propertyId: "property-1",
      resultFingerprint: resultFingerprint ?? "",
      requestFingerprint: "a".repeat(64),
      expectedVersion: customer.version,
      updateSource: { memo: "Recorded command result" },
    };
    const view = render(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
    await screen.findByText("Dara Sok");
    fireEvent.change(
      screen.getByLabelText("Legal name", { selector: "#customer-legal-name" }),
      { target: { value: "Privileged create draft" } },
    );
    fireEvent.change(
      screen.getByLabelText("ID number / Passport number", {
        selector: "#customer-id-number",
      }),
      { target: { value: "N0123456" } },
    );
    view.rerender(
      <CustomerManagement
        api={api}
        onReconciled={reconciled}
        reconciliationRequirement={requirement}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the prior Customer command status",
      }),
    );

    await screen.findByText(/Customer management access changed/);
    expect(reconciled).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", {
        name: "I verified the prior Customer command result",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create Customer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByDisplayValue("Privileged create draft"),
    ).not.toBeInTheDocument();
  });
});

it("TEST-FE-577 hands the selected Customer and current Property to the readonly ledger without invoking a Customer command", async () => {
  const customerId = "00000000-0000-4000-8000-000000000003",
    propertyId = "00000000-0000-4000-8000-000000000002";
  const api = client({
    list: vi.fn().mockResolvedValue({
      items: [
        {
          customer_id: customerId,
          legal_name: "Synthetic ledger Customer",
          active: true,
          relationship_indicators: [],
        },
      ],
      next_cursor: null,
      can_manage: false,
    }),
    get: vi.fn().mockResolvedValue({
      ...customer,
      customer_id: customerId,
      legal_name: "Synthetic ledger Customer",
      can_manage: false,
      can_deactivate: false,
    }),
  });
  const open = vi.fn();
  render(
    <CustomerManagement
      actorId="00000000-0000-4000-8000-000000000001"
      api={api}
      onOpenAccountLedger={open}
    />,
  );
  fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
    target: { value: propertyId },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load Customers" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Open Synthetic ledger Customer",
    }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Open account ledger" }),
  );
  expect(open).toHaveBeenCalledExactlyOnceWith({ customerId, propertyId });
  expect(api.create).not.toHaveBeenCalled();
  expect(api.update).not.toHaveBeenCalled();
  expect(api.deactivate).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Customer Property identifier"), {
    target: { value: "00000000-0000-4000-8000-000000000006" },
  });
  expect(
    screen.queryByRole("button", { name: "Open account ledger" }),
  ).not.toBeInTheDocument();
});
