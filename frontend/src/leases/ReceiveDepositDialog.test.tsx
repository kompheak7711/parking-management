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
import type { LeaseResource } from "../leaseClient";
import type { PaymentsApi } from "../payments/paymentsClient";
import {
  type SettlementApi,
  SettlementRequestError,
  SettlementUnavailableError,
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

const unknown =
  "We could not tell whether this was saved. “Try again” sends the very same request; it is never saved twice.";
const closeUnknown =
  "We could not tell whether the money was saved. If you close now, look in Payments before you receive it again, so it is not received twice.";

function apis() {
  // The money is never saved on its own (DL-112).
  const confirm = vi.fn();
  const paymentsApi = {
    methods: vi.fn(() =>
      Promise.resolve([
        { id: "method-aba", code: "ABA", displayName: "ABA PAY" },
      ]),
    ),
    confirm,
  } as unknown as PaymentsApi;
  const receive = vi
    .fn<SettlementApi["receiveSecurityDeposit"]>()
    .mockRejectedValueOnce(
      new SettlementRequestError(
        409,
        "deposit-receipt-payment-owed",
        "Pay the open Invoices first.",
      ),
    )
    .mockResolvedValue({ receiptNumber: "RC0009" });
  return {
    paymentsApi,
    settlementApi: { receiveSecurityDeposit: receive },
    receive,
    confirm,
  };
}

function open(
  all: ReturnType<typeof apis>,
  options: {
    security?: DepositResource | null;
    onClose?: () => void;
    onSaved?: (message: string) => void;
  } = {},
) {
  render(
    <ReceiveDepositDialog
      language="en"
      lease={lease}
      onClose={options.onClose ?? vi.fn()}
      onSaved={options.onSaved ?? vi.fn()}
      paymentsApi={all.paymentsApi}
      propertyId="property-1"
      security={options.security ?? null}
      settlementApi={all.settlementApi}
    />,
  );
  return screen.getByRole("dialog");
}

async function fill(dialog: HTMLElement) {
  fireEvent.change(await within(dialog).findByLabelText("How the money came"), {
    target: { value: "method-aba" },
  });
  fireEvent.change(within(dialog).getByLabelText("Bank or ABA reference"), {
    target: { value: "ABA 777" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save the deposit" }),
  );
}

describe("Receive Security Deposit (V1-060 B6; V1-061 one request)", () => {
  it("TEST-FE-1015 a walk-in Lease: one request saves the money, makes the Security Deposit and takes the receipt (DL-112); a refusal saved nothing, so Try again is a new request", async () => {
    const all = apis();
    const onSaved = vi.fn();
    const dialog = open(all, { onSaved });
    expect(within(dialog).getByLabelText("Full Security Deposit")).toHaveValue(
      "500.00",
    );
    fireEvent.change(within(dialog).getByLabelText("Received now"), {
      target: { value: "300" },
    });
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-aba" } },
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
    // Nothing was saved: the boxes stay open and no money notice shows.
    expect(within(dialog).queryByText(/The money is saved/)).toBeNull();
    expect(within(dialog).getByLabelText("Received now")).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        "Security Deposit of $300.00 received with Receipt RC0009.",
      );
    });
    expect(all.confirm).not.toHaveBeenCalled();
    expect(all.receive).toHaveBeenCalledTimes(2);
    const [propertyId, leaseId, body] = all.receive.mock.calls[1] ?? [];
    expect([propertyId, leaseId]).toEqual(["property-1", "lease-1"]);
    expect(body).toMatchObject({
      required_usd_cents: 50_000,
      payment: {
        evidence_reference: "ABA 123456",
        amount: { currency: "USD", minor_units: 30_000 },
      },
    });
    expect(body).not.toHaveProperty("payment.payer_customer_id");
  });

  it("TEST-FE-1016 a Security Deposit not fully received takes only the rest into that Deposit, and no new Deposit is made", async () => {
    const all = apis();
    all.receive.mockReset().mockResolvedValue({ receiptNumber: "RC0010" });
    const onSaved = vi.fn();
    const dialog = open(all, {
      onSaved,
      security: {
        deposit_id: "deposit-1",
        required_usd_cents: 50_000,
        outstanding_required_usd_cents: 40_000,
      } as unknown as DepositResource,
    });
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
    expect(all.receive).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Received now"), {
      target: { value: "400" },
    });
    await fill(dialog);
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        "Security Deposit of $400.00 received with Receipt RC0010.",
      );
    });
    expect(all.receive.mock.calls[0]?.[2]).toMatchObject({
      deposit_id: "deposit-1",
      required_usd_cents: null,
      payment: { amount: { minor_units: 40_000 } },
    });
  });

  it("TEST-FE-1078 a lost answer: Try again sends the very same request, its received time and the new Security Deposit's id included, with the same key", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T03:00:00.000Z"));
    const all = apis();
    all.receive
      .mockReset()
      .mockRejectedValueOnce(new SettlementUnavailableError())
      .mockRejectedValueOnce(
        new SettlementRequestError(500, null, "The server failed."),
      )
      .mockResolvedValue({ receiptNumber: "RC0009" });
    const onSaved = vi.fn();
    const dialog = open(all, { onSaved });
    await fill(dialog);
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    // Some seconds later the very same request goes again.
    vi.setSystemTime(new Date("2026-10-28T03:00:07.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(all.receive).toHaveBeenCalledTimes(2);
    });
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    expect(within(dialog).queryByText("The server failed.")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        "Security Deposit of $500.00 received with Receipt RC0009.",
      );
    });
    expect(all.receive.mock.calls[0]?.[2]).toMatchObject({
      payment: { received_at: "2026-10-28T03:00:00.000Z" },
    });
    for (const call of all.receive.mock.calls.slice(1)) {
      expect(call[2]).toEqual(all.receive.mock.calls[0]?.[2]);
      expect(call[3]).toBe(all.receive.mock.calls[0]?.[3]);
    }
  });
});

describe("Receive Security Deposit (V1-060 B7; V1-061 one request)", () => {
  it("TEST-FE-1091 after a lost answer nothing that makes up the request can change until the server says; not allowed is still not known; Close asks once more; a refusal of the very same request opens the boxes, and a change is a new request", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T03:00:00.000Z"));
    const all = apis();
    all.receive
      .mockReset()
      .mockRejectedValueOnce(new SettlementUnavailableError())
      .mockRejectedValueOnce(
        new SettlementRequestError(403, null, "Not allowed."),
      )
      .mockRejectedValueOnce(
        new SettlementRequestError(
          422,
          null,
          "This was not saved. Check the Lease and try again.",
        ),
      )
      .mockResolvedValue({ receiptNumber: "RC0009" });
    const onClose = vi.fn();
    const onSaved = vi.fn();
    const dialog = open(all, { onClose, onSaved });
    await fill(dialog);
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
      expect(all.receive).toHaveBeenCalledTimes(2);
    });
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    for (const box of boxes()) expect(box).toBeDisabled();
    expect(all.receive.mock.calls[1]?.[2]).toEqual(
      all.receive.mock.calls[0]?.[2],
    );
    expect(all.receive.mock.calls[1]?.[3]).toBe(all.receive.mock.calls[0]?.[3]);
    // Close asks once more.
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(within(dialog).getByText(closeUnknown)).toBeInTheDocument();
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
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        "Security Deposit of $200.00 received with Receipt RC0009.",
      );
    });
    expect(all.receive).toHaveBeenCalledTimes(4);
    expect(all.receive.mock.calls[3]?.[2]).toMatchObject({
      payment: { amount: { currency: "USD", minor_units: 20_000 } },
    });
    expect(all.receive.mock.calls[3]?.[3]).not.toBe(
      all.receive.mock.calls[0]?.[3],
    );
  });
});

describe("Receive Security Deposit (V1-060 B7, third review)", () => {
  it("TEST-FE-1096 after a lost answer a Try again that never leaves the browser is still not known and nothing can change; Escape only asks, also held or pressed again; the next Try again sends the very same request", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T03:00:00.000Z"));
    const all = apis();
    all.receive
      .mockReset()
      .mockRejectedValueOnce(new SettlementUnavailableError())
      .mockRejectedValueOnce(new Error("The sign-in cookie is gone."))
      .mockResolvedValue({ receiptNumber: "RC0009" });
    const onClose = vi.fn();
    const onSaved = vi.fn();
    const dialog = open(all, { onClose, onSaved });
    await fill(dialog);
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    // Signed out meanwhile: nothing reaches the server, so nothing says it was not saved.
    vi.setSystemTime(new Date("2026-10-28T03:00:05.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(all.receive).toHaveBeenCalledTimes(2);
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
    expect(within(dialog).getByText(closeUnknown)).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape", repeat: true });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    // Signed in again: the very same request, its time and key included.
    vi.setSystemTime(new Date("2026-10-28T03:00:09.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        "Security Deposit of $500.00 received with Receipt RC0009.",
      );
    });
    expect(all.receive).toHaveBeenCalledTimes(3);
    for (const call of all.receive.mock.calls.slice(1)) {
      expect(call[2]).toEqual(all.receive.mock.calls[0]?.[2]);
      expect(call[3]).toBe(all.receive.mock.calls[0]?.[3]);
    }
    expect(onClose).not.toHaveBeenCalled();
  });

  it("TEST-FE-1097 a refusal with no lost answer before it says so at once and leaves the boxes open; Close then closes without asking (DL-112)", async () => {
    const all = apis();
    all.receive
      .mockReset()
      .mockRejectedValueOnce(
        new SettlementRequestError(
          403,
          null,
          "You may not make Security Deposits.",
        ),
      );
    const onClose = vi.fn();
    const dialog = open(all, { onClose });
    await fill(dialog);
    expect(
      await within(dialog).findByText("You may not make Security Deposits."),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(unknown)).toBeNull();
    expect(within(dialog).getByLabelText("Received now")).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
