import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DepositResource } from "../depositClient";
import { InvoiceClientError } from "../invoiceClient";
import type { LeaseResource } from "../leaseClient";
import type { PaymentsApi } from "../payments/paymentsClient";
import {
  type SettlementApi,
  SettlementRequestError,
} from "../settlementClient";
import { ReceiveDepositDialog } from "./ReceiveDepositDialog";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const lease = {
  lease_id: "lease-1",
  unit_number: "U204",
  primary_tenant_id: "customer-dara",
  primary_tenant_name: "Sok Dara",
  monthly_rent_usd_cents: 50_000,
} as unknown as LeaseResource;

function apis() {
  const confirm = vi
    .fn<PaymentsApi["confirm"]>()
    .mockResolvedValue({ paymentId: "payment-9", receiptNumber: "RC0009" });
  const paymentsApi = {
    methods: vi.fn(() =>
      Promise.resolve([
        { id: "method-aba", code: "ABA", displayName: "ABA PAY" },
      ]),
    ),
    confirm,
  } as unknown as PaymentsApi;
  const createSecurityDeposit = vi
    .fn<SettlementApi["createSecurityDeposit"]>()
    .mockResolvedValue({});
  const receiveIntoDeposit = vi
    .fn<SettlementApi["receiveIntoDeposit"]>()
    .mockRejectedValueOnce(
      new SettlementRequestError(
        409,
        "deposit-receipt-payment-owed",
        "Pay the open Invoices first.",
      ),
    )
    .mockResolvedValue({});
  return {
    paymentsApi,
    confirm,
    settlementApi: { createSecurityDeposit, receiveIntoDeposit },
    createSecurityDeposit,
    receiveIntoDeposit,
  };
}

describe("Receive Security Deposit (V1-060 B6)", () => {
  it("TEST-FE-1015 a walk-in Lease: saves the money, makes the Security Deposit, takes the receipt, shows a refusal and finishes on Try again without paying twice", async () => {
    const all = apis();
    const onSaved = vi.fn();
    render(
      <ReceiveDepositDialog
        language="en"
        lease={lease}
        onClose={vi.fn()}
        onSaved={onSaved}
        paymentsApi={all.paymentsApi}
        propertyId="property-1"
        security={null}
        settlementApi={all.settlementApi}
      />,
    );
    const dialog = screen.getByRole("dialog", {
      name: "Receive Security Deposit · U204",
    });
    expect(within(dialog).getByLabelText("Full Security Deposit")).toHaveValue(
      "500.00",
    );
    fireEvent.change(within(dialog).getByLabelText("Received now"), {
      target: { value: "300" },
    });
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      {
        target: { value: "method-aba" },
      },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the deposit" }),
    );
    expect(
      within(dialog).getByText("Type the bank reference for this method."),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Bank or ABA reference"), {
      target: { value: "ABA 123456" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the deposit" }),
    );
    expect(
      await within(dialog).findByText("Pay the open Invoices first."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/The money is saved with Receipt RC0009/),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        "Security Deposit of $300.00 received with Receipt RC0009.",
      );
    });
    expect(all.confirm).toHaveBeenCalledTimes(1);
    expect(all.confirm.mock.calls[0]?.[1]).toMatchObject({
      payer_customer_id: "customer-dara",
      evidence_reference: "ABA 123456",
      amount: { currency: "USD", minor_units: 30_000 },
    });
    expect(all.createSecurityDeposit).toHaveBeenCalledTimes(1);
    const created = all.createSecurityDeposit.mock.calls[0]?.[1];
    expect(created).toMatchObject({ required_usd_cents: 50_000 });
    expect(all.receiveIntoDeposit).toHaveBeenCalledTimes(2);
    expect(all.receiveIntoDeposit.mock.calls[1]?.[0]).toBe(created?.deposit_id);
    expect(all.receiveIntoDeposit.mock.calls[1]?.[1]).toMatchObject({
      payment_id: "payment-9",
      amount_usd_cents: 30_000,
    });
    expect(all.receiveIntoDeposit.mock.calls[1]?.[2]).toBe(
      all.receiveIntoDeposit.mock.calls[0]?.[2],
    );
  });

  it("TEST-FE-1016 a Security Deposit not fully received takes only the rest, and no new Deposit is made", () => {
    const all = apis();
    render(
      <ReceiveDepositDialog
        language="en"
        lease={lease}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        paymentsApi={all.paymentsApi}
        propertyId="property-1"
        security={
          {
            deposit_id: "deposit-1",
            required_usd_cents: 50_000,
            outstanding_required_usd_cents: 40_000,
          } as unknown as DepositResource
        }
        settlementApi={all.settlementApi}
      />,
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("$400.00 still to receive")).toBeTruthy();
    expect(within(dialog).getByLabelText("Received now")).toHaveValue("400.00");
    fireEvent.change(within(dialog).getByLabelText("Received now"), {
      target: { value: "400.01" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the deposit" }),
    );
    expect(
      within(dialog).getByText(
        "Type the money received, more than 0 and not more than what is still to receive.",
      ),
    ).toBeInTheDocument();
    expect(all.confirm).not.toHaveBeenCalled();
    expect(all.createSecurityDeposit).not.toHaveBeenCalled();
  });
  it("TEST-FE-1078 a lost answer: Try again sends the very same Payment, its time included, with the same key; a server failure says it is not known whether it was saved", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T03:00:00.000Z"));
    const all = apis();
    all.confirm
      .mockReset()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockResolvedValue({ paymentId: "payment-9", receiptNumber: "RC0009" });
    all.receiveIntoDeposit
      .mockReset()
      .mockRejectedValueOnce(
        new SettlementRequestError(500, null, "The server failed."),
      )
      .mockResolvedValue({});
    const onSaved = vi.fn();
    render(
      <ReceiveDepositDialog
        language="en"
        lease={lease}
        onClose={vi.fn()}
        onSaved={onSaved}
        paymentsApi={all.paymentsApi}
        propertyId="property-1"
        security={null}
        settlementApi={all.settlementApi}
      />,
    );
    const dialog = screen.getByRole("dialog");
    const unknown =
      "We could not tell whether this was saved. “Try again” sends the very same request; it is never saved twice.";
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-aba" } },
    );
    fireEvent.change(within(dialog).getByLabelText("Bank or ABA reference"), {
      target: { value: "ABA 777" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the deposit" }),
    );
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    // Some seconds later the very same Payment goes again.
    vi.setSystemTime(new Date("2026-10-28T03:00:07.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await within(dialog).findByRole("button", { name: "Try again" });
    expect(
      within(dialog).getByText(/The money is saved with Receipt RC0009/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(unknown)).toBeInTheDocument();
    expect(within(dialog).queryByText("The server failed.")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        "Security Deposit of $500.00 received with Receipt RC0009.",
      );
    });
    expect(all.confirm).toHaveBeenCalledTimes(2);
    expect(all.confirm.mock.calls[0]?.[1]).toMatchObject({
      received_at: "2026-10-28T03:00:00.000Z",
    });
    expect(all.confirm.mock.calls[1]?.[1]).toEqual(
      all.confirm.mock.calls[0]?.[1],
    );
    expect(all.confirm.mock.calls[1]?.[2]).toBe(all.confirm.mock.calls[0]?.[2]);
    expect(all.createSecurityDeposit).toHaveBeenCalledTimes(1);
    expect(all.receiveIntoDeposit).toHaveBeenCalledTimes(2);
    expect(all.receiveIntoDeposit.mock.calls[1]?.[1]).toEqual(
      all.receiveIntoDeposit.mock.calls[0]?.[1],
    );
    expect(all.receiveIntoDeposit.mock.calls[1]?.[2]).toBe(
      all.receiveIntoDeposit.mock.calls[0]?.[2],
    );
  });
});

describe("Receive Security Deposit (V1-060 B7)", () => {
  it("TEST-FE-1091 after a lost answer nothing that makes up the Payment can change until the server says; not allowed is still not known; Close asks once more while the money may be saved; the money saved but the rest refused says so", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T03:00:00.000Z"));
    const all = apis();
    all.confirm
      .mockReset()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockRejectedValueOnce(new InvoiceClientError(403, "FORBIDDEN", false))
      .mockRejectedValueOnce(
        new InvoiceClientError(422, "VALIDATION_FAILED", false),
      )
      .mockResolvedValue({ paymentId: "payment-9", receiptNumber: "RC0009" });
    const onClose = vi.fn();
    render(
      <ReceiveDepositDialog
        language="en"
        lease={lease}
        onClose={onClose}
        onSaved={vi.fn()}
        paymentsApi={all.paymentsApi}
        propertyId="property-1"
        security={null}
        settlementApi={all.settlementApi}
      />,
    );
    const dialog = screen.getByRole("dialog");
    const unknown =
      "We could not tell whether this was saved. “Try again” sends the very same request; it is never saved twice.";
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-aba" } },
    );
    fireEvent.change(within(dialog).getByLabelText("Bank or ABA reference"), {
      target: { value: "ABA 777" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the deposit" }),
    );
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    const boxes = () => [
      within(dialog).getByLabelText("Full Security Deposit"),
      within(dialog).getByLabelText("Received now"),
      within(dialog).getByLabelText("How the money came"),
      within(dialog).getByLabelText("Bank or ABA reference"),
    ];
    for (const box of boxes()) expect(box).toBeDisabled();
    // "Not allowed" comes before the server looks up the request: still not known.
    vi.setSystemTime(new Date("2026-10-28T03:00:07.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(all.confirm).toHaveBeenCalledTimes(2);
    });
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    for (const box of boxes()) expect(box).toBeDisabled();
    expect(all.confirm.mock.calls[1]?.[1]).toEqual(
      all.confirm.mock.calls[0]?.[1],
    );
    expect(all.confirm.mock.calls[1]?.[2]).toBe(all.confirm.mock.calls[0]?.[2]);
    // Close asks once more; Escape is the same press.
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(
      within(dialog).getByText(
        "We could not tell whether the money was saved. If you close now, look in Payments before you receive it again, so it is not received twice.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Close anyway" }),
    ).toBeInTheDocument();
    // A refusal of the very same request says it was not saved: the boxes open again.
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await within(dialog).findByText(
        "This was not saved. Check the Lease and try again.",
      ),
    ).toBeInTheDocument();
    for (const box of boxes()) expect(box).toBeEnabled();
    expect(
      within(dialog).getByRole("button", { name: "Close" }),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Received now"), {
      target: { value: "200" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await within(dialog).findByText("Pay the open Invoices first."),
    ).toBeInTheDocument();
    expect(all.confirm).toHaveBeenCalledTimes(4);
    expect(all.confirm.mock.calls[3]?.[1]).toMatchObject({
      amount: { currency: "USD", minor_units: 20_000 },
    });
    expect(all.confirm.mock.calls[3]?.[2]).not.toBe(
      all.confirm.mock.calls[0]?.[2],
    );
    expect(
      within(dialog).getByText(
        "The money is saved with Receipt RC0009, but the rest was not saved (the reason is below). The money pays nothing yet, so do not receive it again. If the reason cannot be fixed here, close this and ask the Owner or a Manager to finish it.",
      ),
    ).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(
      within(dialog).getByText(
        "The money is saved with Receipt RC0009, but the rest is not confirmed. If you close now, do not receive the money again; ask the Owner or a Manager to check and finish it.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Close anyway" }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("Receive Security Deposit (V1-060 B7, third review)", () => {
  const unknown =
    "We could not tell whether this was saved. “Try again” sends the very same request; it is never saved twice.";

  it("TEST-FE-1096 after a lost answer a Try again that never leaves the browser is still not known and nothing can change; Escape only asks, also held or pressed again; the next Try again sends the very same Payment", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T03:00:00.000Z"));
    const all = apis();
    all.confirm
      .mockReset()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockRejectedValueOnce(
        new InvoiceClientError(null, "CSRF_UNAVAILABLE", false),
      )
      .mockResolvedValue({ paymentId: "payment-9", receiptNumber: "RC0009" });
    all.receiveIntoDeposit.mockReset().mockResolvedValue({});
    const onClose = vi.fn();
    const onSaved = vi.fn();
    render(
      <ReceiveDepositDialog
        language="en"
        lease={lease}
        onClose={onClose}
        onSaved={onSaved}
        paymentsApi={all.paymentsApi}
        propertyId="property-1"
        security={null}
        settlementApi={all.settlementApi}
      />,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-aba" } },
    );
    fireEvent.change(within(dialog).getByLabelText("Bank or ABA reference"), {
      target: { value: "ABA 777" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the deposit" }),
    );
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    // Signed out meanwhile: nothing reaches the server, so nothing says the money was not saved.
    vi.setSystemTime(new Date("2026-10-28T03:00:05.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(all.confirm).toHaveBeenCalledTimes(2);
    });
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    expect(
      within(dialog).queryByText(
        "This was not saved. Check the Lease and try again.",
      ),
    ).toBeNull();
    expect(within(dialog).getByLabelText("Received now")).toBeDisabled();
    expect(
      within(dialog).getByLabelText("Bank or ABA reference"),
    ).toBeDisabled();
    // Escape only asks: a held key or a second press does not close.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      within(dialog).getByText(
        "We could not tell whether the money was saved. If you close now, look in Payments before you receive it again, so it is not received twice.",
      ),
    ).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape", repeat: true });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    // Signed in again: the very same Payment, its time and key included, then the rest.
    vi.setSystemTime(new Date("2026-10-28T03:00:09.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        "Security Deposit of $500.00 received with Receipt RC0009.",
      );
    });
    expect(all.confirm).toHaveBeenCalledTimes(3);
    for (const call of all.confirm.mock.calls.slice(1)) {
      expect(call[1]).toEqual(all.confirm.mock.calls[0]?.[1]);
      expect(call[2]).toBe(all.confirm.mock.calls[0]?.[2]);
    }
    expect(onClose).not.toHaveBeenCalled();
  });

  it("TEST-FE-1097 a lost answer on the Security Deposit step: not allowed on Try again is still not known, the same request goes again, and the next answer finishes it", async () => {
    const all = apis();
    all.createSecurityDeposit
      .mockReset()
      .mockRejectedValueOnce(
        new SettlementRequestError(503, null, "The server failed."),
      )
      .mockRejectedValueOnce(
        new SettlementRequestError(
          403,
          null,
          "You may not make Security Deposits.",
        ),
      )
      .mockResolvedValue({});
    all.receiveIntoDeposit.mockReset().mockResolvedValue({});
    const onSaved = vi.fn();
    render(
      <ReceiveDepositDialog
        language="en"
        lease={lease}
        onClose={vi.fn()}
        onSaved={onSaved}
        paymentsApi={all.paymentsApi}
        propertyId="property-1"
        security={null}
        settlementApi={all.settlementApi}
      />,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-aba" } },
    );
    fireEvent.change(within(dialog).getByLabelText("Bank or ABA reference"), {
      target: { value: "ABA 777" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the deposit" }),
    );
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    expect(
      within(dialog).getByText(/The money is saved with Receipt RC0009/),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(all.createSecurityDeposit).toHaveBeenCalledTimes(2);
    });
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    expect(
      within(dialog).queryByText("You may not make Security Deposits."),
    ).toBeNull();
    expect(all.createSecurityDeposit.mock.calls[1]?.[1]).toEqual(
      all.createSecurityDeposit.mock.calls[0]?.[1],
    );
    expect(all.createSecurityDeposit.mock.calls[1]?.[2]).toBe(
      all.createSecurityDeposit.mock.calls[0]?.[2],
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
    expect(all.confirm).toHaveBeenCalledTimes(1);
    expect(all.receiveIntoDeposit).toHaveBeenCalledTimes(1);
  });
});
