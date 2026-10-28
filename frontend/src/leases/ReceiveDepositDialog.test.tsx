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
