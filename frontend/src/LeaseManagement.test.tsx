import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PET_DEPOSIT } from "./leases/parking";

import { LeaseManagement } from "./LeaseManagement";
import { LeaseApi, LeaseResource, leaseApi } from "./leaseClient";

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
  planned_occupants: [],
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
    renew: vi.fn().mockResolvedValue({
      ...drafted,
      lease_id: "lease-2",
      predecessor_lease_id: drafted.lease_id,
    }),
    terminate: vi.fn().mockResolvedValue({ ...drafted, status: "TERMINATED" }),
    cancel: vi.fn().mockResolvedValue({ ...drafted, status: "CANCELLED" }),
    recordMoveIn: vi.fn().mockResolvedValue(drafted),
    addOccupant: vi.fn().mockResolvedValue(drafted),
    moveOutOccupant: vi.fn().mockResolvedValue(drafted),
    resolveNeverMovedIn: vi.fn(
      (
        _property: string,
        terminationEvent: string,
        source: { resolution_id: string; unit_status: "VACANT" | "CLEANING" },
      ) =>
        Promise.resolve({
          resolution_id: source.resolution_id,
          termination_event_id: terminationEvent,
          lease_id: "lease-1",
          path: "NEVER_MOVED_IN" as const,
          cause: "CUSTOMER_UNPAID_INITIAL_OBLIGATION",
          resulting_unit_status: source.unit_status,
          deposit_disposition_id: "disposition-1",
          invoice_void_event_id: "void-1",
          adjustment_ids: [],
          credit_usd_cents: 0,
        }),
    ),
    creditMovedInInitialRent: vi.fn(
      (
        _property: string,
        terminationEvent: string,
        source: { resolution_id: string },
      ) =>
        Promise.resolve({
          resolution_id: source.resolution_id,
          termination_event_id: terminationEvent,
          lease_id: "lease-1",
          path: "MOVED_IN" as const,
          cause: "CUSTOMER_UNPAID_INITIAL_OBLIGATION",
          resulting_unit_status: null,
          deposit_disposition_id: null,
          invoice_void_event_id: null,
          adjustment_ids: ["adjustment-1"],
          credit_usd_cents: 12345,
        }),
    ),
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
    recordVehicleMoveIn: vi.fn().mockResolvedValue(drafted),
    changeVehicle: vi.fn().mockResolvedValue(drafted),
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

  it("TEST-FE-189 keeps Signers separate and sends signing to Sign Lease with its money", async () => {
    const api = client();
    await loadAndOpen(api);
    expect(
      screen.getByText(/Occupancy alone grants no signing responsibility/),
    ).toBeInTheDocument();
    // V1-061: the folded form no longer signs without money; Sign Lease does it in one step.
    expect(
      screen.queryByRole("button", { name: "Review and sign Lease" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Sign this Lease with Sign Lease on the Lease page/),
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

  it("TEST-FE-674 sends no device time with a Signer signature", async () => {
    const api = client();
    await loadAndOpen(api);
    fireEvent.change(screen.getByLabelText("Signature evidence reason"), {
      target: { value: "Signer identity and consent verified" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record attributed signature" }),
    );

    await waitFor(() => {
      expect(api.recordSignature).toHaveBeenCalledTimes(1);
    });
    const source = vi.mocked(api.recordSignature).mock.calls[0]?.[2];
    expect(Object.keys(source ?? {}).sort()).toEqual(["event_id", "reason"]);
    expect(typeof source?.event_id).toBe("string");
    expect(source?.reason).toBe("Signer identity and consent verified");
  });

  it("TEST-FE-675 the Lease client has no plain signing call", () => {
    // V1-061: POST /leases/{id}/sign signed with no money; only Sign Lease with payment signs.
    expect("sign" in leaseApi).toBe(false);
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
    fireEvent.change(screen.getByLabelText("Parking version"), {
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
    const units = screen.getAllByLabelText("Parking identifier");
    const createUnit = units.at(-1);
    if (createUnit === undefined)
      throw new Error("Create Lease Parking input is absent");
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
    // Parking Step 5: no pet terms on Parking (PET_DEPOSIT); the code stays.
    if (PET_DEPOSIT) {
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
    }
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
    if (PET_DEPOSIT) {
      expect(submitted?.pet_term).toMatchObject({
        deposit_required_by_signed_terms: true,
        pet_description: "One approved indoor cat",
      });
    } else {
      expect(submitted?.pet_term).toBeNull();
    }
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
    const units = screen.getAllByLabelText("Parking identifier");
    const createUnit = units.at(-1);
    if (createUnit === undefined)
      throw new Error("Create Lease Parking input is absent");
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

  describe("V1-055 unpaid Initial obligation termination", () => {
    const signed = {
      ...drafted,
      status: "SIGNED" as const,
      version: 3,
      can_terminate: true,
    };
    const terminated = {
      ...drafted,
      status: "TERMINATED" as const,
      version: 4,
      timeline: [
        {
          event_id: "termination-event-1",
          event_kind: "lease.terminate",
          occurred_at: "2026-09-10T02:00:00Z",
          reason: "Customer did not pay",
          actor_id: "actor-1",
          source_reference: "BR-LEASE-005",
          source_href: "/api/v1/leases/lease-1#timeline-termination-event-1",
        },
      ],
    };
    function fillTermination(notice: "none" | "applies" = "none") {
      fireEvent.change(
        screen.getByLabelText("Unpaid Initial: actual termination date"),
        { target: { value: "2026-09-10" } },
      );
      fireEvent.change(
        screen.getByLabelText(
          "Signed Lease clause that allows this termination",
        ),
        { target: { value: "Clause 7.3" } },
      );
      fireEvent.change(screen.getByLabelText("Approved grounds"), {
        target: { value: "Initial Rent unpaid" },
      });
      fireEvent.change(
        screen.getByLabelText("Management authorization reference"),
        { target: { value: "AUTH-1" } },
      );
      fireEvent.change(screen.getByLabelText("Evidence reference"), {
        target: { value: "LEDGER-1" },
      });
      fireEvent.change(screen.getByLabelText("Termination notice"), {
        target: { value: notice },
      });
      if (notice === "applies") {
        fireEvent.change(
          screen.getByLabelText("Termination notice identifier"),
          {
            target: { value: "notice-1" },
          },
        );
        fireEvent.change(screen.getByLabelText("Notice period end date"), {
          target: { value: "2026-09-09" },
        });
      } else {
        fireEvent.change(
          screen.getByLabelText("Reason no notice period applies"),
          { target: { value: "Clause allows immediate termination" } },
        );
      }
      fireEvent.change(
        screen.getByLabelText("Unpaid Initial: termination reason"),
        { target: { value: "Customer did not pay" } },
      );
    }
    it("TEST-FE-651 terminates with the explicit unpaid Initial context and replays the same identities after a failure", async () => {
      const terminate = vi
        .fn()
        .mockRejectedValueOnce(new Error("network"))
        .mockResolvedValue(terminated);
      const api = client({
        get: vi.fn().mockResolvedValue(signed),
        terminate,
      });
      vi.spyOn(window, "confirm").mockReturnValue(true);
      await loadAndOpen(api);
      fillTermination();
      const submit = () => {
        fireEvent.click(
          screen.getByRole("button", {
            name: "Terminate for unpaid Initial obligation",
          }),
        );
      };
      submit();
      await waitFor(() => {
        expect(terminate).toHaveBeenCalledTimes(1);
      });
      await screen.findByText(/was not completed/);
      submit();
      await waitFor(() => {
        expect(terminate).toHaveBeenCalledTimes(2);
      });
      expect(terminate.mock.calls[1]).toEqual(terminate.mock.calls[0]);
      const [, source, key] = terminate.mock.calls[0] as [
        unknown,
        Record<string, unknown>,
        string,
      ];
      expect(key).toMatch(/^[0-9a-f-]{36}$/);
      expect(source).toMatchObject({
        actual_termination_date: "2026-09-10",
        governing_event_reference: "BR-LEASE-005",
        reason: "Customer did not pay",
        context: {
          basis: "UNPAID_INITIAL_OBLIGATION",
          signed_lease_provision: "Clause 7.3",
          approved_grounds: "Initial Rent unpaid",
          management_authorization_reference: "AUTH-1",
          evidence_reference: "LEDGER-1",
          notice_required: false,
          notice_exception_reason: "Clause allows immediate termination",
        },
      });
      expect(source.context).not.toHaveProperty("notice_id");
      await screen.findByRole("region", {
        name: "Unpaid Initial obligation follow-up",
      });
    });
    it("TEST-FE-678 sends no device time with the authorized termination", async () => {
      const api = client({ get: vi.fn().mockResolvedValue(signed) });
      vi.spyOn(window, "confirm").mockReturnValue(true);
      await loadAndOpen(api);
      fireEvent.change(screen.getByLabelText("Actual termination date"), {
        target: { value: "2026-09-10" },
      });
      fireEvent.change(screen.getByLabelText("Governing event reference"), {
        target: { value: "approved-termination-1" },
      });
      fireEvent.change(screen.getByLabelText("Termination reason"), {
        target: { value: "Authorized termination boundary" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Apply authorized termination" }),
      );
      await waitFor(() => {
        expect(api.terminate).toHaveBeenCalledTimes(1);
      });
      const source = vi.mocked(api.terminate).mock.calls[0]?.[1];
      expect(Object.keys(source ?? {}).sort()).toEqual([
        "actual_termination_date",
        "event_id",
        "governing_event_reference",
        "reason",
      ]);
    });
    it("TEST-FE-679 sends no device time with the unpaid Initial termination, also on its retry", async () => {
      const terminate = vi
        .fn()
        .mockRejectedValueOnce(new Error("network"))
        .mockResolvedValue(terminated);
      const api = client({
        get: vi.fn().mockResolvedValue(signed),
        terminate,
      });
      vi.spyOn(window, "confirm").mockReturnValue(true);
      await loadAndOpen(api);
      fillTermination();
      const submit = () => {
        fireEvent.click(
          screen.getByRole("button", {
            name: "Terminate for unpaid Initial obligation",
          }),
        );
      };
      submit();
      await waitFor(() => {
        expect(terminate).toHaveBeenCalledTimes(1);
      });
      await screen.findByText(/was not completed/);
      submit();
      await waitFor(() => {
        expect(terminate).toHaveBeenCalledTimes(2);
      });
      for (const call of terminate.mock.calls) {
        const source = (call as [unknown, Record<string, unknown>])[1];
        expect(Object.keys(source).sort()).toEqual([
          "actual_termination_date",
          "context",
          "event_id",
          "governing_event_reference",
          "reason",
        ]);
      }
    });
    it("TEST-FE-652 sends the notice identity and period end when a notice applies", async () => {
      const api = client({ get: vi.fn().mockResolvedValue(signed) });
      vi.spyOn(window, "confirm").mockReturnValue(true);
      await loadAndOpen(api);
      fillTermination("applies");
      fireEvent.click(
        screen.getByRole("button", {
          name: "Terminate for unpaid Initial obligation",
        }),
      );
      await waitFor(() => {
        expect(api.terminate).toHaveBeenCalledTimes(1);
      });
      const source = vi.mocked(api.terminate).mock.calls[0]?.[1];
      expect(source?.context).toMatchObject({
        notice_required: true,
        notice_id: "notice-1",
        notice_period_ends_on: "2026-09-09",
      });
      expect(source?.context).not.toHaveProperty("notice_exception_reason");
    });
    it("TEST-FE-653 keeps the termination and the follow-up hidden unless the Lease state and capability allow them", async () => {
      await loadAndOpen(client());
      expect(
        screen.queryByRole("button", {
          name: "Terminate for unpaid Initial obligation",
        }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("region", {
          name: "Unpaid Initial obligation follow-up",
        }),
      ).not.toBeInTheDocument();
    });
    it("TEST-FE-654 resolves never moved in with the timeline event, requires the CLEANING reason and replays after a failure", async () => {
      const resolveNeverMovedIn = vi
        .fn()
        .mockRejectedValueOnce(new Error("network"));
      const base = client({ get: vi.fn().mockResolvedValue(terminated) });
      resolveNeverMovedIn.mockImplementation(base.resolveNeverMovedIn);
      const api = { ...base, resolveNeverMovedIn };
      vi.spyOn(window, "confirm").mockReturnValue(true);
      await loadAndOpen(api);
      const region = await screen.findByRole("region", {
        name: "Unpaid Initial obligation follow-up",
      });
      expect(
        within(region).getByLabelText("Termination event identifier"),
      ).toHaveValue("termination-event-1");
      fireEvent.change(within(region).getByLabelText("Parking after release"), {
        target: { value: "CLEANING" },
      });
      fireEvent.change(
        within(region).getByLabelText("Never moved in: resolution reason"),
        { target: { value: "Never moved in and did not pay" } },
      );
      const submit = () => {
        fireEvent.click(
          within(region).getByRole("button", {
            name: "Resolve never moved in",
          }),
        );
      };
      submit();
      expect(resolveNeverMovedIn).not.toHaveBeenCalled();
      fireEvent.change(
        within(region).getByLabelText(
          "Parking status reason (required for CLEANING)",
        ),
        { target: { value: "Needs cleaning" } },
      );
      submit();
      await waitFor(() => {
        expect(resolveNeverMovedIn).toHaveBeenCalledTimes(1);
      });
      await screen.findByText(/was not completed/);
      submit();
      await waitFor(() => {
        expect(resolveNeverMovedIn).toHaveBeenCalledTimes(2);
      });
      expect(resolveNeverMovedIn.mock.calls[1]).toEqual(
        resolveNeverMovedIn.mock.calls[0],
      );
      expect(resolveNeverMovedIn.mock.calls[0]?.slice(0, 3)).toEqual([
        "property-1",
        "termination-event-1",
        expect.objectContaining({
          unit_status: "CLEANING",
          unit_status_reason: "Needs cleaning",
          reason: "Never moved in and did not pay",
        }),
      ]);
      const recorded = await screen.findByRole("article", {
        name: "Recorded unpaid Initial follow-up",
      });
      expect(recorded).toHaveTextContent("Parking CLEANING");
      expect(recorded).toHaveTextContent("Security Deposit forfeited");
    });
    it("TEST-FE-655 credits the Rent after the termination date for a Customer who moved in", async () => {
      const api = client({ get: vi.fn().mockResolvedValue(terminated) });
      vi.spyOn(window, "confirm").mockReturnValue(true);
      await loadAndOpen(api);
      fireEvent.change(screen.getByLabelText("Moved in: credit reason"), {
        target: { value: "Rent after termination" },
      });
      fireEvent.click(
        screen.getByRole("button", {
          name: "Credit Initial Rent after termination",
        }),
      );
      await waitFor(() => {
        expect(api.creditMovedInInitialRent).toHaveBeenCalledTimes(1);
      });
      expect(api.creditMovedInInitialRent).toHaveBeenCalledWith(
        "property-1",
        "termination-event-1",
        expect.objectContaining({ reason: "Rent after termination" }),
        expect.any(String),
      );
      const recorded = await screen.findByRole("article", {
        name: "Recorded unpaid Initial follow-up",
      });
      expect(recorded).toHaveTextContent("Moved in: credit $123.45");
    });
    it("TEST-FE-656 does nothing when the confirmation is declined", async () => {
      const api = client({ get: vi.fn().mockResolvedValue(terminated) });
      vi.spyOn(window, "confirm").mockReturnValue(false);
      await loadAndOpen(api);
      fireEvent.change(screen.getByLabelText("Moved in: credit reason"), {
        target: { value: "Rent after termination" },
      });
      fireEvent.click(
        screen.getByRole("button", {
          name: "Credit Initial Rent after termination",
        }),
      );
      expect(api.creditMovedInInitialRent).not.toHaveBeenCalled();
    });
    it("TEST-FE-671 says the Security Deposit stays held before resolving never moved in", async () => {
      const api = client({ get: vi.fn().mockResolvedValue(terminated) });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      await loadAndOpen(api);
      const region = await screen.findByRole("region", {
        name: "Unpaid Initial obligation follow-up",
      });
      expect(region).toHaveTextContent(
        "The Security Deposit stays held until a forfeiture draft under BR-LEASE-005 is confirmed by a financial.approve holder.",
      );
      expect(region).not.toHaveTextContent("Forfeits the Security Deposit");
      fireEvent.change(
        within(region).getByLabelText("Never moved in: resolution reason"),
        { target: { value: "Never moved in and did not pay" } },
      );
      fireEvent.click(
        within(region).getByRole("button", { name: "Resolve never moved in" }),
      );
      expect(confirm).toHaveBeenCalledTimes(1);
      const message = String(confirm.mock.calls[0]?.[0]);
      expect(message).toContain(
        "The Security Deposit stays held until a forfeiture draft is confirmed.",
      );
      expect(message).not.toContain("Forfeit the Security Deposit");
      expect(api.resolveNeverMovedIn).not.toHaveBeenCalled();
    });
  });

  it("TEST-FE-660 labels the unpaid Initial follow-up events in the permanent timeline with their source", async () => {
    const api = client({
      get: vi.fn().mockResolvedValue({
        ...drafted,
        status: "TERMINATED",
        timeline: [
          {
            event_id: "resolution-1",
            event_kind: "lease.unpaid_initial_never_moved_in",
            occurred_at: "2026-09-10T03:00:00Z",
            reason: "Customer never moved in",
            actor_id: "actor-1",
            source_reference: "termination-event-1",
            source_href: "/api/v1/leases/lease-1#timeline-resolution-1",
          },
          {
            event_id: "resolution-2",
            event_kind: "lease.unpaid_initial_moved_in_credit",
            occurred_at: "2026-09-10T04:00:00Z",
            reason: "Rent after termination",
            actor_id: "actor-1",
            source_reference: "termination-event-1",
            source_href: "/api/v1/leases/lease-1#timeline-resolution-2",
          },
        ],
      }),
    });
    await loadAndOpen(api);
    expect(
      screen.getByText(/Unpaid Initial obligation resolved: never moved in/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Unpaid Initial obligation resolved: Rent credited after termination/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "termination-event-1" }),
    ).toHaveLength(2);
  });

  it("TEST-FE-670 labels the Initial Rent Due Date override and Rent-nonpayment events the server returns", async () => {
    const api = client({
      get: vi.fn().mockResolvedValue({
        ...drafted,
        status: "SIGNED",
        timeline: [
          {
            event_id: "override-1",
            event_kind: "lease.initial_rent_due_date_override",
            occurred_at: "2026-09-10T03:00:00Z",
            reason: "Customer payroll",
            actor_id: "actor-1",
            source_reference: "2026-09-20",
            source_href: "/api/v1/leases/lease-1#timeline-override-1",
          },
          {
            event_id: "warning-1",
            event_kind: "lease.rent_nonpayment_twenty_day_warning",
            occurred_at: "2026-09-10T04:00:00Z",
            reason: "Authorized documented action",
            actor_id: "actor-1",
            source_reference: "case-1",
            source_href: "/api/v1/leases/lease-1#timeline-warning-1",
          },
        ],
      }),
    });
    await loadAndOpen(api);
    expect(screen.getByText(/Initial Rent Due Date set/)).toBeInTheDocument();
    expect(
      screen.getByText(/Rent nonpayment: 20-day warning recorded/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1149 Parking Step 5: the old Lease screen's draft form has no pet terms", async ({
    skip,
  }) => {
    skip(PET_DEPOSIT);
    render(<LeaseManagement api={client()} />);
    fireEvent.change(screen.getByLabelText("Lease Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Leases" }));
    await screen.findByRole("heading", { name: "Create Lease draft" });
    expect(screen.queryByLabelText("Approved pet terms apply")).toBeNull();
    expect(screen.queryByText("Approved pet terms")).toBeNull();
  });

  it("TEST-FE-1153 Parking Step 5: the old Lease screen's move-in checklist does not mention a Pet Deposit", async ({
    skip,
  }) => {
    skip(PET_DEPOSIT);
    const signed = {
      ...drafted,
      status: "SIGNED" as const,
      version: 2,
      can_edit: false,
      can_manage_signers: false,
      can_sign: false,
      can_move_in: true,
      can_terminate: true,
      can_renew: true,
    };
    await loadAndOpen(client({ get: vi.fn().mockResolvedValue(signed) }));
    expect(
      screen.getByText(
        "Required Security Deposit balances will be server-validated.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Pet Deposit/)).toBeNull();
  });
});
