import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LeaseManagement } from "./LeaseManagement";
import { LeaseApi, LeaseResource } from "./leaseClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const drafted: LeaseResource = {
  lease_id: "lease-1",
  property_id: "property-1",
  unit_id: "unit-1",
  unit_number: "101",
  primary_tenant_id: "customer-1",
  primary_tenant_name: "Primary Tenant",
  status: "DRAFTED",
  start_date: "2026-09-01",
  end_date: "2027-08-31",
  monthly_rent_usd_cents: 80000,
  predecessor_lease_id: null,
  signed_at: null,
  terminated_at: null,
  actual_termination_date: null,
  version: 1,
  created_at: "2026-08-26T01:00:00Z",
  pet_deposit_required: false,
  pet_description: null,
  security_deposit_id: "deposit-1",
  planned_occupant_customer_ids: ["customer-1"],
  service_terms: [],
  signers: [
    {
      signer_id: "signer-1",
      customer_id: "customer-1",
      customer_name: "Primary Tenant",
      is_primary_tenant: true,
      signed_at: null,
      added_at: "2026-08-26T01:00:00Z",
    },
  ],
  occupancies: [],
  timeline: [],
  timeline_next_cursor: null,
  can_edit: true,
  can_manage_signers: true,
  can_sign: true,
  can_terminate: false,
  can_move_in: false,
  can_renew: false,
};

function client(overrides: Partial<LeaseApi> = {}): LeaseApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: [drafted],
      next_cursor: null,
      can_create: true,
    }),
    get: vi.fn().mockResolvedValue(drafted),
    timeline: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    create: vi.fn().mockResolvedValue(drafted),
    update: vi.fn().mockResolvedValue({ ...drafted, version: 2 }),
    addSigner: vi.fn().mockResolvedValue(drafted),
    recordSignature: vi.fn().mockResolvedValue({
      ...drafted,
      version: 2,
      signers: [{ ...drafted.signers[0], signed_at: "2026-08-26T02:00:00Z" }],
    }),
    sign: vi.fn().mockResolvedValue({
      ...drafted,
      status: "SIGNED",
      version: 2,
      signed_at: "2026-08-26T02:00:00Z",
      can_edit: false,
      can_manage_signers: false,
      can_sign: false,
      can_move_in: true,
      can_terminate: true,
      can_renew: true,
    }),
    renew: vi.fn().mockResolvedValue({
      ...drafted,
      lease_id: "lease-2",
      predecessor_lease_id: drafted.lease_id,
    }),
    terminate: vi.fn().mockResolvedValue({ ...drafted, status: "TERMINATED" }),
    completeMoveIn: vi.fn().mockResolvedValue({
      event_id: "move-in-1",
      property_id: "property-1",
      reservation_id: "reservation-1",
      reservation_version: 2,
      lease_id: "lease-1",
      lease_version: 3,
      unit_id: "unit-1",
      unit_version: 4,
      deposit_id: "deposit-1",
      deposit_version: 2,
      actual_move_in_date: "2026-09-01",
      occupancy_ids: ["occupancy-1"],
    }),
    ...overrides,
  };
}

async function loadAndOpen(api: LeaseApi) {
  render(<LeaseManagement api={api} />);
  fireEvent.change(screen.getByLabelText("Lease Property identifier"), {
    target: { value: "property-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load Leases" }));
  fireEvent.click(await screen.findByRole("button", { name: "View Lease" }));
  await screen.findByRole("heading", { name: "Lease detail" });
}

describe("Lease staff workflow", () => {
  it("TEST-FE-188 exposes accessible bounded filters and future-successor distinction", async () => {
    const api = client({
      list: vi.fn().mockResolvedValue({
        items: [{ ...drafted, predecessor_lease_id: "lease-prior" }],
        next_cursor: null,
        can_create: true,
      }),
    });
    render(<LeaseManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Lease Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.change(screen.getByLabelText("Period view"), {
      target: { value: "future" },
    });
    fireEvent.change(
      screen.getByLabelText("Property business date for period view"),
      {
        target: { value: "2026-08-26" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Load Leases" }));

    expect(
      await screen.findByRole("cell", { name: "Primary Tenant" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Successor")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith(
      "property-1",
      expect.objectContaining({ period: "future", as_of: "2026-08-26" }),
    );
  });

  it("TEST-FE-189 keeps Signers separate and signs only after explicit confirmation", async () => {
    const api = client();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await loadAndOpen(api);
    expect(
      screen.getByText(/Occupancy alone grants no signing responsibility/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Signing reason and evidence"), {
      target: { value: "All terms and Signers verified" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review and sign Lease" }),
    );

    await waitFor(() => {
      expect(api.sign).toHaveBeenCalledTimes(1);
    });
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText(/explicit audited command/),
    ).toBeInTheDocument();
  });

  it("requires attributed signature evidence before recording a Signer signature", async () => {
    const api = client();
    await loadAndOpen(api);
    const recordButton = screen.getByRole("button", {
      name: "Record attributed signature",
    });
    expect(recordButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Signature evidence reason"), {
      target: { value: "Signer identity and consent verified" },
    });
    expect(recordButton).toBeEnabled();
    fireEvent.click(recordButton);
    await waitFor(() => {
      expect(api.recordSignature).toHaveBeenCalledTimes(1);
    });
    expect(api.recordSignature).toHaveBeenCalledWith(
      drafted,
      "signer-1",
      expect.objectContaining({
        reason: "Signer identity and consent verified",
      }),
      expect.any(String),
    );
  });

  it("TEST-FE-190 conditionally displays Pet Deposit and completes move-in atomically", async () => {
    const signed = {
      ...drafted,
      status: "SIGNED" as const,
      version: 2,
      pet_deposit_required: true,
      pet_description: "approved indoor cat",
      can_edit: false,
      can_manage_signers: false,
      can_sign: false,
      can_move_in: true,
      can_terminate: true,
      can_renew: true,
    };
    const api = client({ get: vi.fn().mockResolvedValue(signed) });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await loadAndOpen(api);
    expect(screen.getByText(/approved indoor cat/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reservation identifier"), {
      target: { value: "reservation-1" },
    });
    fireEvent.change(screen.getByLabelText("Reservation version"), {
      target: { value: "1" },
    });
    fireEvent.change(screen.getByLabelText("Unit version"), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByLabelText("Actual Move-in Date"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Occupant Customer identifiers (one per line, maximum 20)",
      ),
      {
        target: { value: "customer-1\ncustomer-2" },
      },
    );
    fireEvent.change(screen.getByLabelText("Move-in evidence reason"), {
      target: { value: "All prerequisites verified" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Complete move-in atomically" }),
    );

    await waitFor(() => {
      expect(api.completeMoveIn).toHaveBeenCalledTimes(1);
    });
    expect(api.completeMoveIn).toHaveBeenCalledWith(
      "reservation-1",
      1,
      expect.objectContaining({
        occupants: [
          expect.objectContaining({ customer_id: "customer-1" }),
          expect.objectContaining({ customer_id: "customer-2" }),
        ],
      }),
      expect.any(String),
    );
    expect(
      await screen.findByText(/Deposit deposit-1 remain linked/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-191 captures approved terms, Signers, and planned Occupants in one draft", async () => {
    const api = client();
    render(<LeaseManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Lease Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Leases" }));
    await screen.findByRole("heading", { name: "Create Lease draft" });
    const units = screen.getAllByLabelText("Unit identifier");
    const createUnit = units.at(-1);
    if (createUnit === undefined)
      throw new Error("Create Lease Unit input is absent");
    fireEvent.change(createUnit, { target: { value: "unit-1" } });
    fireEvent.change(
      screen.getByLabelText("Primary Tenant Customer identifier"),
      { target: { value: "customer-1" } },
    );
    fireEvent.change(
      screen.getByLabelText(
        "Additional Signer Customer identifiers (one per line)",
      ),
      { target: { value: "customer-2" } },
    );
    fireEvent.change(
      screen.getByLabelText(
        "Planned Occupant Customer identifiers (one per line)",
      ),
      { target: { value: "customer-1\ncustomer-3" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Add approved Service term" }),
    );
    fireEvent.change(
      screen.getByLabelText("Configured Property Service identifier"),
      { target: { value: "service-1" } },
    );
    fireEvent.change(screen.getByLabelText("Applicable From"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(
      screen.getByLabelText("Owner-approved Service period identifier"),
      { target: { value: "approval-1" } },
    );
    fireEvent.change(screen.getByLabelText("Approved terms reference"), {
      target: { value: "owner-approved-parking" },
    });
    fireEvent.click(screen.getByLabelText("Approved pet terms apply"));
    fireEvent.change(screen.getByLabelText("Pet approval date"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(screen.getByLabelText("Pet description"), {
      target: { value: "One approved indoor cat" },
    });
    fireEvent.click(
      screen.getByLabelText("Signed terms require a distinct Pet Deposit"),
    );
    fireEvent.change(
      screen.getByLabelText("Approved Security Deposit source identifier"),
      { target: { value: "deposit-1" } },
    );
    fireEvent.change(screen.getByLabelText("Contract Start Date"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(screen.getByLabelText("Contract End Date"), {
      target: { value: "2027-08-31" },
    });
    fireEvent.change(screen.getByLabelText("Monthly Rent (USD)"), {
      target: { value: "800" },
    });
    fireEvent.change(screen.getByLabelText("Approved source reason"), {
      target: { value: "All distinct sources reviewed" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create DRAFTED Lease" }),
    );
    await waitFor(() => {
      expect(api.create).toHaveBeenCalledTimes(1);
    });
    const submitted = vi.mocked(api.create).mock.calls[0]?.[1];
    expect(submitted?.additional_signers[0]?.customer_id).toBe("customer-2");
    expect(submitted?.planned_occupant_customer_ids).toEqual([
      "customer-1",
      "customer-3",
    ]);
    expect(submitted?.service_terms[0]).toMatchObject({
      property_service_id: "service-1",
      service_approval_period_id: "approval-1",
    });
    expect(submitted?.pet_term).toMatchObject({
      deposit_required_by_signed_terms: true,
      pet_description: "One approved indoor cat",
    });
    expect(submitted?.security_deposit_id).toBe("deposit-1");
  });

  it("TEST-FE-193 preserves complex draft evidence when creation fails", async () => {
    const api = client({
      create: vi.fn().mockRejectedValue(new Error("conflict")),
    });
    render(<LeaseManagement api={api} />);
    fireEvent.change(screen.getByLabelText("Lease Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Leases" }));
    await screen.findByRole("heading", { name: "Create Lease draft" });
    const units = screen.getAllByLabelText("Unit identifier");
    const createUnit = units.at(-1);
    if (createUnit === undefined)
      throw new Error("Create Lease Unit input is absent");
    fireEvent.change(createUnit, { target: { value: "unit-preserved" } });
    fireEvent.change(
      screen.getByLabelText("Primary Tenant Customer identifier"),
      {
        target: { value: "customer-preserved" },
      },
    );
    fireEvent.change(screen.getByLabelText("Approved source reason"), {
      target: { value: "Preserve this evidence" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create DRAFTED Lease" }),
    );
    await screen.findByText(/The Lease request was not completed/);
    expect(createUnit).toHaveValue("unit-preserved");
    expect(
      screen.getByLabelText("Primary Tenant Customer identifier"),
    ).toHaveValue("customer-preserved");
    expect(screen.getByLabelText("Approved source reason")).toHaveValue(
      "Preserve this evidence",
    );
  });

  it("TEST-FE-194 shows renewal only when the server grants the eligible capability", async () => {
    const api = client();
    await loadAndOpen(api);
    expect(
      screen.queryByRole("button", { name: "Create successor Lease draft" }),
    ).not.toBeInTheDocument();

    cleanup();
    const eligible = {
      ...drafted,
      status: "SIGNED" as const,
      can_edit: false,
      can_manage_signers: false,
      can_sign: false,
      can_renew: true,
    };
    await loadAndOpen(client({ get: vi.fn().mockResolvedValue(eligible) }));
    expect(
      screen.getByRole("button", { name: "Create successor Lease draft" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-192 renders permanent timeline sources as distinct links", async () => {
    const api = client({
      get: vi.fn().mockResolvedValue({
        ...drafted,
        timeline_next_cursor: "cursor-1",
        timeline: [
          {
            event_id: "event-1",
            event_kind: "lease.draft",
            occurred_at: "2026-08-26T02:00:00Z",
            reason: "Lease drafted",
            actor_id: "actor-1",
            source_reference: "event-1",
            source_href: "/api/v1/leases/lease-1#timeline-event-1",
          },
        ],
      }),
      timeline: vi.fn().mockResolvedValue({
        items: [
          {
            event_id: "event-2",
            event_kind: "lease.renewal_successor",
            occurred_at: "2026-08-26T03:00:00Z",
            reason: "Successor Lease drafted",
            actor_id: "actor-1",
            source_reference: "lease-2",
            source_href: "/api/v1/leases/lease-2",
          },
        ],
        next_cursor: null,
      }),
    });
    await loadAndOpen(api);
    expect(screen.getByRole("link", { name: "event-1" })).toHaveAttribute(
      "href",
      "/api/v1/leases/lease-1#timeline-event-1",
    );
    expect(document.getElementById("timeline-event-1")).not.toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Load more timeline events" }),
    );
    expect(
      await screen.findByRole("link", { name: "lease-2" }),
    ).toHaveAttribute("href", "/api/v1/leases/lease-2");
    expect(document.getElementById("timeline-event-2")).not.toBeNull();
    expect(api.timeline).toHaveBeenCalledWith("lease-1", "cursor-1");
  });
});
