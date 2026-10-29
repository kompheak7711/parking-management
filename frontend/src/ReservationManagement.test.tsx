import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReservationManagement } from "./ReservationManagement";
import { ReservationApi, ReservationResource } from "./reservationClient";

afterEach(() => {
  cleanup();
});

const active: ReservationResource = {
  reservation_id: "reservation-1",
  property_id: "property-1",
  unit_id: "unit-1",
  unit_number: "101",
  customer_id: "customer-1",
  customer_name: "Customer One",
  reservation_date: "2026-08-26",
  original_expiration_date: "2026-09-05",
  effective_expiration_date: "2026-09-05",
  agreed_monthly_rent_usd_cents: 50000,
  status: "ACTIVE",
  version: 1,
  deposit_id: "deposit-1",
  deposit_required_usd_cents: 50000,
  deposit_received_usd_cents: 10000,
  deposit_outcome_state: "PENDING_V1_031",
  cancellation_reason_code: null,
  cancellation_responsibility: null,
  resulting_lease_id: null,
  extension_notice: null,
  can_extend: true,
  can_cancel: true,
  receipts: [],
  lifecycle_events: [],
  deposit_outcomes: [],
  extension_days_remaining: 10,
};

function api(overrides: Partial<ReservationApi> = {}): ReservationApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: [active],
      next_cursor: null,
      can_create: true,
    }),
    get: vi.fn().mockResolvedValue(active),
    create: vi.fn().mockResolvedValue(active),
    extend: vi.fn().mockResolvedValue({
      ...active,
      version: 2,
      effective_expiration_date: "2026-09-12",
      extension_notice: {
        notice_id: "notice-1",
        previous_expiration_date: "2026-09-05",
        new_expiration_date: "2026-09-12",
        approved_at: "2026-09-01T00:00:00Z",
        reason_memo: "Approved",
      },
      can_extend: false,
    }),
    cancel: vi.fn().mockResolvedValue({
      ...active,
      version: 2,
      status: "CANCELLED",
      deposit_outcome_state: "NON_REFUNDABLE_DISPOSITION",
      can_extend: false,
      can_cancel: false,
    }),
    ...overrides,
  };
}

describe("Reservation staff workflow", () => {
  it("TEST-FE-182 shows only canonical statuses, Deposit progress, and permitted actions", async () => {
    const client = api();
    render(<ReservationManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Reservations" }));

    expect(await screen.findByText("Customer One")).toBeInTheDocument();
    expect(screen.getByText("$100.00 / $500.00")).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "EXPIRED" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Create Reservation" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-183 exposes original expiration and one accessible Extension Notice action", async () => {
    const client = api();
    render(<ReservationManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Reservations" }));
    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    await screen.findByRole("heading", { name: "Reservation detail" });
    fireEvent.change(
      screen.getByLabelText("New Expiration Date (maximum 14 added days)"),
      {
        target: { value: "2026-09-12" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Record Extension Notice" }),
    );

    await waitFor(() => {
      expect(client.extend).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByText(/Original date remains preserved/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-680 sends no device time with the Extension Notice", async () => {
    const client = api();
    render(<ReservationManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Reservations" }));
    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    await screen.findByRole("heading", { name: "Reservation detail" });
    fireEvent.change(
      screen.getByLabelText("New Expiration Date (maximum 14 added days)"),
      {
        target: { value: "2026-09-12" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Record Extension Notice" }),
    );

    await waitFor(() => {
      expect(client.extend).toHaveBeenCalledTimes(1);
    });
    const source = vi.mocked(client.extend).mock.calls[0]?.[1];
    expect(Object.keys(source ?? {}).sort()).toEqual([
      "new_expiration_date",
      "notice_id",
      "reason_memo",
    ]);
  });

  it("TEST-FE-681 sends no device time with the Reservation create", async () => {
    const client = api();
    render(<ReservationManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Reservations" }));
    await screen.findByRole("heading", { name: "Create Reservation" });
    const fields: [string, string][] = [
      ["Available Parking identifier", "unit-1"],
      ["Customer identifier", "customer-1"],
      ["Reservation Date", "2026-08-26"],
      ["Expiration Date (maximum initial period: 21 days)", "2026-09-05"],
      ["Agreed monthly Rent (USD)", "500.00"],
      ["Accepted initial Security Deposit (USD)", "100.00"],
      ["Full required Security Deposit (USD)", "500.00"],
      ["Deposit Payment source identifier", "payment-1"],
      ["Acceptance reason", "Accepted normal suggestion"],
    ];
    for (const [label, value] of fields) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(
      screen.getByRole("button", { name: "Create ACTIVE Reservation" }),
    );

    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    const source = vi.mocked(client.create).mock.calls[0]?.[1];
    expect(Object.keys(source ?? {}).sort()).toEqual([
      "acceptance_id",
      "acceptance_reason",
      "accepted_initial_deposit_usd_cents",
      "agreed_monthly_rent_usd_cents",
      "customer_id",
      "deposit_id",
      "expiration_date",
      "payment_id",
      "receipt_id",
      "required_security_deposit_usd_cents",
      "reservation_date",
      "reservation_id",
      "unit_id",
    ]);
    expect(source?.accepted_initial_deposit_usd_cents).toBe(10000);
  });

  it("TEST-FE-184 previews classified Deposit consequences and confirms cancellation", async () => {
    const client = api();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ReservationManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Reservations" }));
    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    await screen.findByRole("heading", { name: "Cancel Reservation" });
    fireEvent.change(screen.getByLabelText("Approved reason code"), {
      target: { value: "CUSTOMER_WITHDREW" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review and confirm cancellation" }),
    );

    await waitFor(() => {
      expect(client.cancel).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("reservation-status")).toHaveTextContent(
      "forfeiture draft is confirmed by an approver",
    );
  });

  it("TEST-FE-212 reuses exact cancellation identities after an ambiguous failure", async () => {
    const client = api();
    vi.mocked(client.cancel)
      .mockRejectedValueOnce(new Error("ambiguous"))
      .mockResolvedValueOnce({
        ...active,
        version: 2,
        status: "CANCELLED",
        deposit_outcome_state: "NON_REFUNDABLE_DISPOSITION",
        can_extend: false,
        can_cancel: false,
      });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ReservationManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Reservations" }));
    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    await screen.findByRole("heading", { name: "Cancel Reservation" });
    fireEvent.change(screen.getByLabelText("Approved reason code"), {
      target: { value: "CUSTOMER_WITHDREW" },
    });
    const submit = screen.getByRole("button", {
      name: "Review and confirm cancellation",
    });
    fireEvent.click(submit);
    await screen.findByText(
      "The Reservation request was not completed. Review the fields and retry.",
    );
    const firstCall = vi.mocked(client.cancel).mock.calls[0];
    fireEvent.click(submit);
    await waitFor(() => {
      expect(client.cancel).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(client.cancel).mock.calls[1]).toEqual(firstCall);
  });
});
