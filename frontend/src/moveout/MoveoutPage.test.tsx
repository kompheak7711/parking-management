import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DepositResource } from "../depositClient";
import {
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
} from "../leaseClient";
import type { UnitResource } from "../unitClient";
import {
  MoveOutUnavailableError,
  type MoveOutApi,
  type MoveOutPage,
  type MoveOutRecord,
} from "./moveoutClient";
import { MoveoutPage } from "./MoveoutPage";

const TODAY = "2026-10-25";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/moveout";
});

function lease(
  unit: string,
  overrides: Partial<LeaseResource> = {},
): LeaseResource {
  return {
    lease_id: `lease-${unit}`,
    property_id: "property-1",
    unit_id: `unit-${unit}`,
    unit_number: unit,
    primary_tenant_id: `customer-${unit}`,
    primary_tenant_name: `Tenant ${unit}`,
    status: "SIGNED",
    start_date: "2025-10-25",
    end_date: "2026-10-24",
    monthly_rent_usd_cents: 50000,
    predecessor_lease_id: null,
    signed_at: "2025-10-20T03:00:00Z",
    terminated_at: null,
    actual_termination_date: null,
    version: 3,
    created_at: "2025-10-19T03:00:00Z",
    pet_deposit_required: false,
    pet_description: null,
    security_deposit_id: `deposit-${unit}`,
    planned_occupant_customer_ids: [],
    service_terms: [],
    signers: [],
    occupancies: [
      {
        occupancy_id: `occupancy-${unit}`,
        customer_id: `customer-${unit}`,
        customer_name: `Tenant ${unit}`,
        move_in_date: "2025-10-25",
        move_out_date: null,
        version: 2,
      },
    ],
    timeline: [],
    timeline_next_cursor: null,
    can_edit: false,
    can_manage_signers: false,
    can_sign: false,
    can_terminate: true,
    can_move_in: false,
    can_renew: true,
    ...overrides,
  };
}

const ended = lease("U101");
const soon = lease("U102", { end_date: "2026-12-10" });
const far = lease("U103", { end_date: "2027-06-30" });
const terminated = lease("U104", {
  status: "TERMINATED",
  actual_termination_date: "2026-10-20",
  terminated_at: "2026-10-20T03:00:00Z",
  timeline: [
    {
      event_id: "termination-U104",
      event_kind: "lease.terminate",
      occurred_at: "2026-10-20T03:00:00Z",
      reason: "Left early at the Customer's request",
      actor_id: "actor-1",
      source_reference: "BR-LEASE-021",
      source_href: null,
    },
  ],
});
const out = lease("U105", {
  status: "TERMINATED",
  actual_termination_date: "2026-10-10",
  occupancies: [
    {
      occupancy_id: "occupancy-U105",
      customer_id: "customer-U105",
      customer_name: "Tenant U105",
      move_in_date: "2025-10-25",
      move_out_date: "2026-10-12",
      version: 3,
    },
  ],
});
const neverIn = lease("U106", {
  status: "TERMINATED",
  actual_termination_date: "2026-10-15",
  occupancies: [],
});

function deposit(leaseId: string, held: number): DepositResource {
  return {
    deposit_id: `deposit-${leaseId}`,
    property_id: "property-1",
    deposit_type: "SECURITY",
    customer_id: "customer",
    reservation_id: null,
    lease_id: leaseId,
    pet_approval_id: null,
    required_usd_cents: 50000,
    received_usd_cents: 50000,
    held_refundable_usd_cents: held,
    outstanding_required_usd_cents: 0,
    version: 1,
    reservation_version: null,
    pet_departure_id: null,
    pet_refund_review_id: null,
    refund_qualified: false,
    can_manage: false,
    can_reverse_receipt: false,
    can_qualify_pet_refund: false,
    new_receipt_creation_deferred: true,
    final_settlement_disposition_deferred: true,
  };
}

function record(overrides: Partial<MoveOutRecord> = {}): MoveOutRecord {
  return {
    event_id: "move-out-1",
    lease_id: "lease-U101",
    termination_event_id: "termination",
    actual_move_out_date: "2026-10-25",
    unit_condition: "CLEANING",
    resulting_unit_status: "CLEANING",
    reason: "Unit handed back",
    evidence_reference: "Keys returned: all",
    supersedes_event_id: null,
    occurred_at: "2026-10-25T05:00:00Z",
    actor_id: "actor-1",
    event_status: "CURRENT",
    occupancies: [],
    ...overrides,
  };
}

function setup(
  leases: LeaseResource[],
  options: {
    capabilities?: ReadonlySet<string> | null;
    page?: MoveOutPage;
    record?: MoveOutApi["record"];
    terminate?: LeaseApi["terminate"];
    unitGet?: () => Promise<UnitResource>;
  } = {},
) {
  const byId = new Map(leases.map((item) => [item.lease_id, item]));
  const leaseApi = {
    list: vi.fn<LeaseApi["list"]>(() =>
      Promise.resolve({ items: leases, next_cursor: null, can_create: true }),
    ),
    get: vi.fn<LeaseApi["get"]>((id) => {
      const found = byId.get(id);
      return found === undefined
        ? Promise.reject(new Error("missing"))
        : Promise.resolve(found);
    }),
    timeline: vi.fn<LeaseApi["timeline"]>(() =>
      Promise.resolve({ items: [], next_cursor: null }),
    ),
    terminate: vi.fn<LeaseApi["terminate"]>(
      options.terminate ??
        ((item, source) =>
          Promise.resolve({
            ...item,
            status: "TERMINATED",
            version: item.version + 1,
            actual_termination_date: source.actual_termination_date,
          })),
    ),
  };
  const depositApi = {
    leaseDeposits: vi.fn((id: string) =>
      Promise.resolve({
        items: [deposit(id, id === "lease-U101" ? 45000 : 50000)],
        can_manage: false,
      }),
    ),
  };
  const unitApi = {
    get: vi.fn(
      options.unitGet ??
        (() => Promise.resolve({ version: 7 } as UnitResource)),
    ),
  };
  const moveOutApi = {
    read: vi.fn<MoveOutApi["read"]>((_property, id) =>
      Promise.resolve(
        options.page ?? {
          items: [],
          total: 0,
          open_occupancies: (byId.get(id)?.occupancies ?? [])
            .filter((occupancy) => occupancy.move_out_date === null)
            .map((occupancy) => ({
              occupancy_id: occupancy.occupancy_id,
              customer_id: occupancy.customer_id,
              move_in_date: occupancy.move_in_date,
              version: occupancy.version,
            })),
        },
      ),
    ),
    record: vi.fn<MoveOutApi["record"]>(
      options.record ?? (() => Promise.resolve(record())),
    ),
  };
  render(
    <MoveoutPage
      active
      capabilities={options.capabilities ?? null}
      depositApi={depositApi}
      language="en"
      leaseApi={leaseApi}
      moveOutApi={moveOutApi}
      propertyId="property-1"
      today={TODAY}
      unitApi={unitApi}
    />,
  );
  return { leaseApi, depositApi, unitApi, moveOutApi };
}

const rows = () =>
  within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );

describe("Move-out", () => {
  it("TEST-FE-962 lists Leases ending within 60 days or terminated and still in as Leaving soon, the handed-back ones first, with the Deposits held; the cards filter the list", async () => {
    setup([ended, soon, far, terminated, out, neverIn]);
    await screen.findByRole("table");
    await waitFor(() => {
      expect(rows()[0]?.[5]).toBe("$500.00");
    });
    expect(rows()).toEqual([
      [
        "U105",
        "Tenant U105",
        "10/10/2026End Date was 24/10/2026",
        "12/10/2026",
        "Handed backRecord final readings",
        "$500.00",
      ],
      [
        "U106",
        "Tenant U106",
        "15/10/2026End Date was 24/10/2026",
        "Not needed",
        "Never moved inPrepare the Final Settlement",
        "$500.00",
      ],
      [
        "U104",
        "Tenant U104",
        "20/10/2026End Date was 24/10/2026",
        "—",
        "Still in the Unit5 days agoRecord the hand-back",
        "$500.00",
      ],
      [
        "U101",
        "Tenant U101",
        "24/10/2026",
        "—",
        "Leaving soon1 day agoRecord the hand-back",
        "$450.00",
      ],
      [
        "U102",
        "Tenant U102",
        "10/12/2026",
        "—",
        "Leaving soonin 46 daysRecord the hand-back",
        "$500.00",
      ],
    ]);
    fireEvent.click(screen.getByRole("button", { name: /Handed back/ }));
    expect(rows().map((row) => row[0])).toEqual(["U105", "U106"]);
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(rows()).toHaveLength(5);
    expect(
      screen.getByRole("link", { name: "U101" }).getAttribute("href"),
    ).toBe("#/moveout/lease-U101");
  });

  it("TEST-FE-963 a Lease past its End Date: Record hand-back ends it on the End Date as signed, then records the move-out with the new Lease version, the Unit version and every open Occupancy; Try again after no answer sends the same request", async () => {
    window.location.hash = "#/moveout/lease-U101";
    let fail = true;
    const { leaseApi, moveOutApi } = setup([ended], {
      record: () =>
        fail
          ? Promise.reject(new MoveOutUnavailableError())
          : Promise.resolve(record()),
    });
    await screen.findByRole("heading", { name: "Move-out · U101" });
    expect(screen.getByText(/Lease End Date 24\/10\/2026/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Record hand-back" }));
    const dialog = screen.getByRole("dialog");
    // Before the End Date is refused: leaving early is Terminate.
    fireEvent.change(within(dialog).getByLabelText(/Hand-back date/), {
      target: { value: "2026-10-23" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record hand-back" }),
    );
    expect(
      within(dialog).getByText("Enter a date from 24/10/2026 to today."),
    ).toBeTruthy();
    expect(leaseApi.terminate).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/Hand-back date/), {
      target: { value: "2026-10-25" },
    });
    expect(
      within(dialog).getByText(
        /Handed back on 25\/10\/2026, on or after the 5th: Rent for October 2026 is due in full/,
      ),
    ).toBeTruthy();
    expect(
      within(dialog).getByText(/This also ends the Lease on its End Date/),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByLabelText("All keys returned"));
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record hand-back" }),
    );
    await within(dialog).findByText(/No answer came back/);
    expect(leaseApi.terminate).toHaveBeenCalledTimes(1);
    const [terminatedLease, source, endKey] =
      leaseApi.terminate.mock.calls[0] ?? [];
    expect(terminatedLease?.version).toBe(3);
    expect(source).toMatchObject({
      actual_termination_date: "2026-10-24",
      governing_event_reference: "BR-LEASE-023",
      context: {
        basis: "SIGNED_LEASE_OTHER",
        notice_required: false,
        evidence_reference:
          "Hand-back recorded in the app on or after the End Date",
      },
    });
    expect(typeof endKey).toBe("string");
    const [property, leaseId, sent, key] =
      moveOutApi.record.mock.calls[0] ?? [];
    expect([property, leaseId]).toEqual(["property-1", "lease-U101"]);
    expect(sent).toMatchObject({
      termination_event_id: source?.event_id,
      expected_lease_version: 4,
      expected_unit_version: 7,
      actual_move_out_date: "2026-10-25",
      unit_condition: "CLEANING",
      occupancies: [{ occupancy_id: "occupancy-U101", expected_version: 2 }],
      evidence_reference: "Keys returned: not all",
      reason: "Unit handed back",
      supersedes_event_id: null,
    });
    fail = false;
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await screen.findByText("Hand-back recorded. U101 is now Cleaning.");
    // The Lease was ended once; the move-out went again with the same identity.
    expect(leaseApi.terminate).toHaveBeenCalledTimes(1);
    expect(moveOutApi.record.mock.calls[1]?.[2]).toEqual(sent);
    expect(moveOutApi.record.mock.calls[1]?.[3]).toBe(key);
  });

  it("TEST-FE-964 a terminated Lease names its termination and ends nothing again; a Lease handed back shows the day and the Rent rule; never moved in skips the hand-back; without leases.terminate a running Lease says a Manager records it", async () => {
    window.location.hash = "#/moveout/lease-U104";
    const { leaseApi, moveOutApi } = setup([terminated]);
    await screen.findByRole("heading", { name: "Move-out · U104" });
    const steps = within(
      screen.getByRole("region", { name: "Move-out steps" }),
    );
    expect(steps.getByText("Terminated as of 20/10/2026.")).toBeTruthy();
    expect(
      screen.getByText("Reason: Left early at the Customer's request"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Record hand-back" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Hand-back date/), {
      target: { value: "2026-10-03" },
    });
    expect(within(dialog).getByText(/before the 5th/)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/The Unit after/), {
      target: { value: "UNDER_MAINTENANCE" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record hand-back" }),
    );
    await waitFor(() => {
      expect(moveOutApi.record).toHaveBeenCalledTimes(1);
    });
    expect(leaseApi.terminate).not.toHaveBeenCalled();
    expect(moveOutApi.record.mock.calls[0]?.[2]).toMatchObject({
      termination_event_id: "termination-U104",
      expected_lease_version: 3,
      actual_move_out_date: "2026-10-03",
      unit_condition: "UNDER_MAINTENANCE",
    });
    cleanup();

    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: {
        items: [record({ actual_move_out_date: "2026-10-12" })],
        total: 1,
        open_occupancies: [],
      },
    });
    expect(
      await screen.findByText(
        "Handed back on 12/10/2026. Unit set to Cleaning.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(/Rent for October 2026 is due in full/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Record hand-back" }),
    ).toBeNull();
    cleanup();

    window.location.hash = "#/moveout/lease-U106";
    setup([neverIn]);
    expect(
      await screen.findAllByText("Never moved in: nothing to hand back."),
    ).toHaveLength(3);
    cleanup();

    window.location.hash = "#/moveout/lease-U101";
    setup([ended], {
      capabilities: new Set(["leases.read", "leases.move_out"]),
    });
    expect(
      await screen.findByText(
        "A Manager records this hand-back, because it also ends the Lease at its End Date.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Record hand-back" }),
    ).toBeNull();
    expect(screen.getByText("Your account cannot see Deposits.")).toBeTruthy();
  });

  it("TEST-FE-966 ending the Lease answers nothing: Try again ends it with the same request; a Unit read failure after that is not called a refusal; closing reads the page again; a Lease with a signed renewal shows no hand-back", async () => {
    window.location.hash = "#/moveout/lease-U101";
    let calls = 0;
    const { leaseApi, unitApi } = setup([ended], {
      terminate: (item, source) => {
        calls += 1;
        return calls === 1
          ? Promise.reject(new LeaseUnavailableError())
          : Promise.resolve({
              ...item,
              status: "TERMINATED",
              version: 4,
              actual_termination_date: source.actual_termination_date,
            });
      },
      unitGet: () => Promise.reject(new Error("unit service down")),
    });
    await screen.findByRole("heading", { name: "Move-out · U101" });
    fireEvent.click(screen.getByRole("button", { name: "Record hand-back" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record hand-back" }),
    );
    await within(dialog).findByText(/No answer came back/);
    // A changed tick does not change the request that ends the Lease.
    fireEvent.click(within(dialog).getByLabelText("All keys returned"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(unitApi.get).toHaveBeenCalledTimes(1);
    });
    await within(dialog).findByText(/No answer came back/);
    const [first, second] = leaseApi.terminate.mock.calls;
    expect(second?.[1]).toEqual(first?.[1]);
    expect(second?.[2]).toBe(first?.[2]);
    const reads = leaseApi.get.mock.calls.length;
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(leaseApi.get.mock.calls.length).toBeGreaterThan(reads);
    });
    cleanup();

    window.location.hash = "#/moveout/lease-U101";
    const renewal = lease("U101", {
      lease_id: "lease-U101-next",
      predecessor_lease_id: "lease-U101",
      start_date: "2026-10-25",
      end_date: "2027-10-24",
    });
    setup([
      lease("U101", {
        timeline: [
          {
            event_id: "renewal",
            event_kind: "lease.renewal_successor",
            occurred_at: "2026-09-01T03:00:00Z",
            reason: "Successor Lease drafted",
            actor_id: "actor-1",
            source_reference: "lease-U101-next",
            source_href: null,
          },
        ],
      }),
      renewal,
    ]);
    expect(
      await screen.findByText(
        "A signed renewal continues this Lease, so the tenants stay: there is no move-out.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Record hand-back" }),
    ).toBeNull();
  });
});
