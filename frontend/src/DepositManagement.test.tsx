import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DepositManagement } from "./DepositManagement";
import {
  DepositApi,
  DepositRequestError,
  DepositResource,
} from "./depositClient";

afterEach(cleanup);

const deposit: DepositResource = {
  deposit_id: "deposit-1",
  property_id: "property-1",
  deposit_type: "PET",
  customer_id: "customer-1",
  reservation_id: null,
  lease_id: "lease-1",
  pet_approval_id: "approval-1",
  required_usd_cents: 20000,
  received_usd_cents: 20000,
  held_refundable_usd_cents: 20000,
  outstanding_required_usd_cents: 0,
  version: 1,
  reservation_version: null,
  pet_departure_id: null,
  pet_refund_review_id: null,
  refund_qualified: false,
  can_manage: true,
  can_reverse_receipt: true,
  can_qualify_pet_refund: true,
  new_receipt_creation_deferred: true,
  final_settlement_disposition_deferred: true,
};

function api(): DepositApi {
  return {
    reservationDeposits: vi
      .fn()
      .mockResolvedValue({ items: [deposit], can_manage: true }),
    leaseDeposits: vi
      .fn()
      .mockResolvedValue({ items: [deposit], can_manage: true }),
    get: vi.fn().mockResolvedValue(deposit),
    ledger: vi.fn().mockResolvedValue({
      items: [
        {
          event_id: "receipt-1",
          event_kind: "RECEIPT",
          occurred_at: "2026-08-26T00:00:00Z",
          amount_usd_cents: 20000,
          source_id: "payment-1",
          reason: null,
          evidence_reference: null,
          actor_id: "actor-1",
          authorization_reference: null,
          currency: "USD",
          amount_minor: 20000,
          reference_number: null,
          governing_source_kind: null,
          governing_source_id: null,
          source_lifecycle_event_id: null,
          effective_date: null,
          can_reverse: true,
        },
      ],
      next_cursor: null,
    }),
    createPetDeposit: vi.fn().mockResolvedValue(deposit),
    reverseReceipt: vi.fn().mockResolvedValue({
      ...deposit,
      received_usd_cents: 0,
      held_refundable_usd_cents: 0,
    }),
    reverseDisposition: vi.fn().mockResolvedValue(deposit),
    recordDeparture: vi.fn().mockResolvedValue({
      ...deposit,
      pet_departure_id: "departure-1",
    }),
    departures: vi.fn().mockResolvedValue([]),
    qualifyReview: vi.fn().mockResolvedValue({
      ...deposit,
      pet_departure_id: "departure-1",
      pet_refund_review_id: "review-1",
      refund_qualified: true,
    }),
    review: vi.fn().mockResolvedValue({
      review_id: "review-1",
      departure_id: "departure-1",
      deposit_id: "deposit-1",
      obligations_reviewed_usd_cents: 0,
      review_findings: "No remaining pet obligations",
      resolution_reference: "inspection-2026-08-26",
      reason: "Authorized active-Lease exception review",
      reviewed_at: "2026-08-26T01:00:00Z",
      reviewed_by: "actor-1",
      authorization_reference: "deposits.refund.qualify",
      refundable_usd_cents: 20000,
      current_refundable_usd_cents: 20000,
    }),
  };
}

describe("DepositManagement", () => {
  it("TEST-FE-198 shows separate liabilities, source history, and explicit deferrals", async () => {
    const client = api();
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation or Lease identifier"), {
      target: { value: "lease-1" },
    });
    fireEvent.change(screen.getByLabelText("Source type"), {
      target: { value: "lease" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Deposits" }));
    expect(await screen.findByText("PET")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open history" }));
    expect(await screen.findByText(/RECEIPT — \$200.00/)).toBeInTheDocument();
    expect(client.get).toHaveBeenCalledWith("deposit-1");
    expect(
      screen.getByText(
        /source payment-1.*actor actor-1.*original USD 20000 minor units/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Receipt creation waits for authoritative Payment persistence/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Final Settlement disposition is deferred/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-209 refreshes the Deposit before combining it with current history", async () => {
    const client = api();
    const refreshed = {
      ...deposit,
      held_refundable_usd_cents: 10000,
      reservation_version: 3,
    };
    vi.mocked(client.get).mockResolvedValue(refreshed);
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation or Lease identifier"), {
      target: { value: "lease-1" },
    });
    fireEvent.change(screen.getByLabelText("Source type"), {
      target: { value: "lease" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Deposits" }));
    await screen.findByText("PET");
    fireEvent.click(screen.getByRole("button", { name: "Open history" }));
    expect(
      await screen.findByText(/refundable held balance \$100.00/),
    ).toBeInTheDocument();
    expect(client.ledger).toHaveBeenCalledWith("deposit-1");
  });

  it("TEST-FE-199 records departure separately before qualifying a Refund review", async () => {
    const client = api();
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Deposit identifier"), {
      target: { value: "deposit-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load one Deposit" }));
    await screen.findByText("PET Deposit");
    fireEvent.change(screen.getByLabelText("Permanent departure date"), {
      target: { value: "2026-08-26" },
    });
    const departureForm = screen
      .getByRole("heading", { name: "Record permanent pet departure" })
      .closest("form");
    if (departureForm === null) throw new Error("Departure form is missing");
    fireEvent.change(within(departureForm).getByLabelText("Reason"), {
      target: { value: "Pet permanently left" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record departure only" }),
    );
    await waitFor(() => {
      expect(client.recordDeparture).toHaveBeenCalled();
    });
    expect(
      await screen.findByText(/no Refund is authorized yet/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-200 hides management controls without the exact server capability", async () => {
    const client = api();
    vi.mocked(client.leaseDeposits).mockResolvedValue({
      items: [{ ...deposit, can_manage: false }],
      can_manage: false,
    });
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation or Lease identifier"), {
      target: { value: "lease-1" },
    });
    fireEvent.change(screen.getByLabelText("Source type"), {
      target: { value: "lease" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Deposits" }));
    await screen.findByText("PET");
    expect(
      screen.queryByRole("button", { name: "Create Pet Deposit liability" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-201 requires confirmation and renders the authoritative review", async () => {
    const client = api();
    vi.mocked(client.get).mockResolvedValue({
      ...deposit,
      pet_departure_id: "departure-1",
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Deposit identifier"), {
      target: { value: "deposit-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load one Deposit" }));
    await screen.findByText("PET Deposit");
    fireEvent.change(screen.getByLabelText("Pet obligations reviewed (USD)"), {
      target: { value: "0.00" },
    });
    fireEvent.change(screen.getByLabelText("Resolved findings"), {
      target: { value: "No remaining pet obligations" },
    });
    fireEvent.change(screen.getByLabelText("Resolution reference"), {
      target: { value: "inspection-2026-08-26" },
    });
    fireEvent.change(screen.getByLabelText("Authorization reason"), {
      target: { value: "Authorized active-Lease exception review" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record qualifying review" }),
    );
    expect(
      await screen.findByText("Authoritative Refund review"),
    ).toBeInTheDocument();
    expect(client.review).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText(
        /qualified refundable balance \$200\.00; current held refundable balance \$200\.00/,
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-202 rejects imprecise money without submitting", async () => {
    const client = api();
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation or Lease identifier"), {
      target: { value: "lease-1" },
    });
    fireEvent.change(screen.getByLabelText("Source type"), {
      target: { value: "lease" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Deposits" }));
    await screen.findByText("PET");
    const form = screen
      .getByRole("heading", {
        name: "Approved conditional Pet Deposit liability",
      })
      .closest("form");
    if (form === null) throw new Error("Pet Deposit form is missing");
    fireEvent.change(within(form).getByLabelText("Signed Lease identifier"), {
      target: { value: "lease-1" },
    });
    fireEvent.change(within(form).getByLabelText("Approved pet identifier"), {
      target: { value: "approval-1" },
    });
    fireEvent.change(within(form).getByLabelText("Required amount (USD)"), {
      target: { value: "0.001" },
    });
    fireEvent.change(within(form).getByLabelText("Effective date"), {
      target: { value: "2026-08-26" },
    });
    fireEvent.change(within(form).getByLabelText("Reason"), {
      target: { value: "Approved terms" },
    });
    fireEvent.submit(form);
    expect(await screen.findByText(/exact USD amount/)).toBeInTheDocument();
    expect(client.createPetDeposit).not.toHaveBeenCalled();
  });

  it("TEST-FE-210 reuses one command identity after an ambiguous client failure", async () => {
    const client = api();
    vi.mocked(client.leaseDeposits).mockResolvedValue({
      items: [],
      can_manage: true,
    });
    vi.mocked(client.createPetDeposit)
      .mockRejectedValueOnce(new DepositRequestError())
      .mockResolvedValueOnce(deposit);
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Reservation or Lease identifier"), {
      target: { value: "lease-1" },
    });
    fireEvent.change(screen.getByLabelText("Source type"), {
      target: { value: "lease" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Deposits" }));
    const form = (
      await screen.findByRole("heading", {
        name: "Approved conditional Pet Deposit liability",
      })
    ).closest("form");
    if (form === null) throw new Error("Pet Deposit form is missing");
    fireEvent.change(within(form).getByLabelText("Signed Lease identifier"), {
      target: { value: "lease-1" },
    });
    fireEvent.change(within(form).getByLabelText("Approved pet identifier"), {
      target: { value: "approval-1" },
    });
    fireEvent.change(within(form).getByLabelText("Required amount (USD)"), {
      target: { value: "200.00" },
    });
    fireEvent.change(within(form).getByLabelText("Effective date"), {
      target: { value: "2026-08-26" },
    });
    fireEvent.change(within(form).getByLabelText("Reason"), {
      target: { value: "Approved terms" },
    });
    fireEvent.submit(form);
    await screen.findByText("The Deposit request was not completed.");
    const firstCall = vi.mocked(client.createPetDeposit).mock.calls[0];
    fireEvent.submit(form);
    await waitFor(() => {
      expect(client.createPetDeposit).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(client.createPetDeposit).mock.calls[1]).toEqual(firstCall);
  });

  it("TEST-FE-203 coordinates Reservation disposition reversal and replacement", async () => {
    const client = api();
    const reservationDeposit: DepositResource = {
      ...deposit,
      deposit_type: "SECURITY",
      reservation_id: "reservation-1",
      lease_id: null,
      pet_approval_id: null,
      reservation_version: 7,
      can_qualify_pet_refund: false,
    };
    vi.mocked(client.get).mockResolvedValue(reservationDeposit);
    vi.mocked(client.reverseDisposition).mockResolvedValue(reservationDeposit);
    vi.mocked(client.ledger).mockResolvedValue({
      items: [
        {
          event_id: "disposition-1",
          event_kind: "DISPOSITION",
          occurred_at: "2026-08-26T00:00:00Z",
          amount_usd_cents: 20000,
          source_id: "reservation-1",
          reason: "Customer cancellation",
          evidence_reference: null,
          actor_id: "actor-1",
          authorization_reference: "reservation_deposits.dispose",
          currency: "USD",
          amount_minor: 20000,
          reference_number: null,
          governing_source_kind: "RESERVATION",
          governing_source_id: "reservation-1",
          source_lifecycle_event_id: "lifecycle-1",
          effective_date: "2026-08-25",
          can_reverse: true,
        },
      ],
      next_cursor: null,
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Deposit identifier"), {
      target: { value: "deposit-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load one Deposit" }));
    await screen.findByText("SECURITY Deposit");
    expect(screen.getByText(/effective 2026-08-25/)).toBeInTheDocument();
    const correctionForm = screen
      .getByRole("heading", { name: "Record linked correction" })
      .closest("form");
    if (correctionForm === null) throw new Error("Correction form is missing");
    expect(
      within(correctionForm).getByRole("option", {
        name: /DISPOSITION — disposition-1 — \$200\.00/,
      }),
    ).toBeInTheDocument();
    fireEvent.change(within(correctionForm).getByLabelText("Reason"), {
      target: { value: "Corrected cancellation evidence" },
    });
    fireEvent.submit(correctionForm);
    expect(
      await screen.findByText(/Enter the verified evidence reference/),
    ).toBeInTheDocument();
    expect(client.reverseDisposition).not.toHaveBeenCalled();
    fireEvent.change(
      within(correctionForm).getByLabelText(
        "Verified evidence reference (required for dispositions)",
      ),
      { target: { value: "case-2026-038" } },
    );
    fireEvent.submit(correctionForm);
    await waitFor(() => {
      expect(client.reverseDisposition).toHaveBeenCalledTimes(1);
    });
    const call = vi.mocked(client.reverseDisposition).mock.calls[0];
    if (call === undefined) throw new Error("Correction call is missing");
    expect(call[0]).toBe("disposition-1");
    expect(call[1]).toMatchObject({
      reason: "Corrected cancellation evidence",
      evidence_reference: "case-2026-038",
      expected_reservation_version: 7,
    });
    expect(typeof call[1].replacement_disposition_id).toBe("string");
    expect(typeof call[2]).toBe("string");
    expect(confirm).toHaveBeenCalledWith(
      expect.stringMatching(
        /Authoritative amount: \$200\.00\. Source: reservation-1.*changes the held Deposit balance/,
      ),
    );
    expect(
      screen.getByText(
        /reopen history to view the original and correction together/,
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-205 restores persisted departure and review state on reload", async () => {
    const client = api();
    const persisted = {
      ...deposit,
      pet_departure_id: "departure-1",
      pet_refund_review_id: "review-1",
      refund_qualified: true,
    };
    vi.mocked(client.get).mockResolvedValue(persisted);
    vi.mocked(client.departures).mockResolvedValue([
      {
        departure_id: "departure-1",
        deposit_id: "deposit-1",
        lease_id: "lease-1",
        pet_approval_id: "approval-1",
        permanently_left_date: "2026-08-26",
        reason: "Pet permanently left",
        occurred_at: "2026-08-26T00:30:00Z",
        actor_id: "actor-1",
        refund_review_id: "review-1",
      },
    ]);
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Deposit identifier"), {
      target: { value: "deposit-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load one Deposit" }));

    expect(
      await screen.findByText("Authoritative Refund review"),
    ).toBeInTheDocument();
    expect(client.departures).toHaveBeenCalledWith("lease-1");
    expect(client.review).toHaveBeenCalledWith("review-1");
    expect(
      screen.queryByRole("heading", { name: "Record permanent pet departure" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        name: "Qualify active-Lease Pet Deposit Refund",
      }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-206 clears stale ledger controls while a different Deposit loads", async () => {
    const client = api();
    let resolveSecond: ((value: DepositResource) => void) | undefined;
    vi.mocked(client.get)
      .mockResolvedValueOnce(deposit)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecond = resolve;
          }),
      );
    render(<DepositManagement api={client} />);
    const input = screen.getByLabelText("Deposit identifier");
    fireEvent.change(input, { target: { value: "deposit-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Load one Deposit" }));
    expect(
      await screen.findByRole("option", { name: /RECEIPT/ }),
    ).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "deposit-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Load one Deposit" }));
    expect(
      screen.queryByRole("option", { name: /RECEIPT/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("PET Deposit")).not.toBeInTheDocument();

    resolveSecond?.({ ...deposit, deposit_id: "deposit-2" });
    expect(await screen.findByText("PET Deposit")).toBeInTheDocument();
  });

  it("TEST-FE-207 shapes a continued Security Deposit correction from the event source", async () => {
    const client = api();
    const continued = {
      ...deposit,
      deposit_type: "SECURITY" as const,
      reservation_id: "reservation-1",
      lease_id: "lease-1",
      reservation_version: 7,
    };
    vi.mocked(client.get).mockResolvedValue(continued);
    vi.mocked(client.ledger).mockResolvedValue({
      items: [
        {
          event_id: "lease-disposition-1",
          event_kind: "DISPOSITION",
          occurred_at: "2026-08-26T00:00:00Z",
          amount_usd_cents: 5000,
          source_id: "lease-1",
          reason: "Authorized Lease outcome",
          evidence_reference: null,
          actor_id: "actor-1",
          authorization_reference: "deposits.dispose",
          currency: "USD",
          amount_minor: 5000,
          reference_number: null,
          governing_source_kind: "LEASE",
          governing_source_id: "lease-1",
          source_lifecycle_event_id: null,
          effective_date: "2026-08-25",
          can_reverse: true,
        },
      ],
      next_cursor: null,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DepositManagement api={client} />);
    fireEvent.change(screen.getByLabelText("Deposit identifier"), {
      target: { value: "deposit-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load one Deposit" }));
    const form = (
      await screen.findByRole("heading", {
        name: "Record linked correction",
      })
    ).closest("form");
    if (form === null) throw new Error("Correction form is missing");
    fireEvent.change(within(form).getByLabelText("Reason"), {
      target: { value: "Correct Lease evidence" },
    });
    fireEvent.change(
      within(form).getByLabelText(
        "Verified evidence reference (required for dispositions)",
      ),
      {
        target: { value: "case-lease-1" },
      },
    );
    fireEvent.submit(form);
    await waitFor(() => {
      expect(client.reverseDisposition).toHaveBeenCalledTimes(1);
    });
    expect(
      vi.mocked(client.reverseDisposition).mock.calls[0]?.[1],
    ).toMatchObject({
      replacement_disposition_id: null,
      expected_reservation_version: null,
    });
  });
});
