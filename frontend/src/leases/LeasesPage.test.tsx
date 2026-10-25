import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DepositApi, DepositResource } from "../depositClient";
import {
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
} from "../leaseClient";
import { dayText, todayInPhnomPenh } from "../shell/format";
import { LeasesPage } from "./LeasesPage";
import { addDays, endingLimit, initialRent } from "./leasesData";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/leases";
});

const today = todayInPhnomPenh();

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
    start_date: addDays(today, -200),
    end_date: addDays(today, 165),
    monthly_rent_usd_cents: 50000,
    predecessor_lease_id: null,
    signed_at: "2026-03-01T03:00:00Z",
    terminated_at: null,
    actual_termination_date: null,
    version: 3,
    created_at: "2026-02-20T03:00:00Z",
    pet_deposit_required: false,
    pet_description: null,
    security_deposit_id: `deposit-${unit}`,
    planned_occupant_customer_ids: [],
    service_terms: [],
    signers: [
      {
        signer_id: `signer-${unit}`,
        customer_id: `customer-${unit}`,
        customer_name: `Tenant ${unit}`,
        is_primary_tenant: true,
        signed_at: "2026-03-01T03:00:00Z",
        added_at: "2026-02-20T03:00:00Z",
      },
    ],
    occupancies: [
      {
        occupancy_id: `occupancy-${unit}`,
        customer_id: `customer-${unit}`,
        customer_name: `Tenant ${unit}`,
        move_in_date: addDays(today, -199),
        move_out_date: null,
        version: 1,
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

const running = lease("U101", {
  signers: [
    ...lease("U101").signers,
    {
      signer_id: "signer-2",
      customer_id: "customer-guarantor",
      customer_name: "Guarantor",
      is_primary_tenant: false,
      signed_at: "2026-03-01T03:00:00Z",
      added_at: "2026-02-20T03:00:00Z",
    },
  ],
});
const ending = lease("U102", { end_date: addDays(today, 20) });
const renewedEnding = lease("U103", { end_date: addDays(today, 15) });
const renewal = lease("U103", {
  lease_id: "lease-U103-renewal",
  status: "DRAFTED",
  predecessor_lease_id: "lease-U103",
  start_date: addDays(today, 16),
  end_date: addDays(today, 380),
  signed_at: null,
  occupancies: [],
});
const draft = lease("U201", {
  status: "DRAFTED",
  start_date: "2026-12-10",
  end_date: "2027-12-09",
  signed_at: null,
  signers: lease("U201").signers.map((signer) => ({
    ...signer,
    signed_at: null,
  })),
  occupancies: [],
  planned_occupant_customer_ids: ["customer-child"],
});
const terminated = lease("U202", {
  status: "TERMINATED",
  start_date: "2025-06-01",
  end_date: "2026-05-31",
  actual_termination_date: "2026-02-28",
  terminated_at: "2026-02-10T04:00:00Z",
  occupancies: [
    {
      occupancy_id: "occupancy-old",
      customer_id: "customer-U202",
      customer_name: "Tenant U202",
      move_in_date: "2025-06-01",
      move_out_date: "2026-02-28",
      version: 2,
    },
  ],
});
const cancelled = lease("U203", { status: "CANCELLED", signed_at: null });
const all = [
  running,
  ending,
  renewedEnding,
  renewal,
  draft,
  terminated,
  cancelled,
];

function deposit(
  leaseId: string,
  overrides: Partial<DepositResource> = {},
): DepositResource {
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
    held_refundable_usd_cents: 50000,
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
    ...overrides,
  };
}

function api(overrides: Partial<LeaseApi> = {}): LeaseApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: all,
      next_cursor: null,
      can_create: true,
    }),
    get: vi.fn((id: string) =>
      Promise.resolve(all.find((entry) => entry.lease_id === id) ?? running),
    ),
    timeline: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    ...overrides,
  } as unknown as LeaseApi;
}

function deposits(overrides: Partial<DepositApi> = {}): DepositApi {
  return {
    leaseDeposits: vi.fn((id: string) =>
      Promise.resolve({
        items:
          id === "lease-U201"
            ? [
                deposit(id, {
                  received_usd_cents: 10000,
                  outstanding_required_usd_cents: 40000,
                }),
              ]
            : [deposit(id)],
        can_manage: false,
      }),
    ),
    ...overrides,
  } as unknown as DepositApi;
}

function show(
  client: LeaseApi,
  depositClient: DepositApi = deposits(),
  capabilities: ReadonlySet<string> | null = null,
) {
  return render(
    <LeasesPage
      active
      api={client}
      capabilities={capabilities}
      depositApi={depositClient}
      language="en"
      propertyId="property-1"
    />,
  );
}

function rowOf(unit: string): HTMLElement {
  const row = screen.getAllByRole("link", { name: unit })[0]?.closest("tr");
  if (row === null || row === undefined) throw new Error(`no row for ${unit}`);
  return row;
}

describe("Leases list", () => {
  it("TEST-FE-843 shows each Lease with its tenant, dates, Rent, Security Deposit and status", async () => {
    show(api());

    expect(await screen.findByText("Tenant U101")).toBeInTheDocument();
    expect(
      within(screen.getByRole("table"))
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual([
      "Unit",
      "Primary Tenant",
      "Period",
      "Monthly Rent",
      "Deposit",
      "Status",
    ]);
    expect(rowOf("U101")).toHaveTextContent("Tenant U101+1 Signer");
    expect(rowOf("U101")).toHaveTextContent("$500.00");
    await waitFor(() => {
      expect(rowOf("U201")).toHaveTextContent("$100.00of $500.00Draft");
    });
    expect(rowOf("U101")).toHaveTextContent("Lease active");
    expect(rowOf("U102")).toHaveTextContent("Ending soon");
    // A Lease that a later Lease renews is not "ending soon".
    expect(rowOf("U202")).toHaveTextContent(
      "01/06/2025 – 31/05/2026Terminated as of 28/02/2026",
    );
    expect(rowOf("U202")).toHaveTextContent("—Terminated");
    expect(rowOf("U203")).toHaveTextContent("Cancelled");
    expect(screen.getByText("7 Leases")).toBeInTheDocument();
  });

  it("TEST-FE-844 filters by count card, does not count a renewed Lease as ending, and opens a Lease at its own address", async () => {
    show(api());
    await screen.findByText("Tenant U101");

    expect(
      screen.getByRole("button", { name: /^Current: 3\./ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: `Ending soon: 1. End Date before ${dayText(endingLimit(today))}`,
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Drafts: 2\./ }));
    expect(screen.getByText("2 Leases")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Ended: 2\./ }));
    expect(rowOf("U202")).toBeInTheDocument();
    expect(screen.queryByText("Tenant U101")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "U202" }));
    expect(window.location.hash).toBe("#/leases/lease-U202");
  });
});

describe("Lease page", () => {
  it("TEST-FE-845 shows the facts, Signers, Occupants, Initial Rent worked out by the rules and the deposits", async () => {
    window.location.hash = "#/leases/lease-U201";
    show(api());

    expect(
      await screen.findByRole("heading", { name: "Lease · U201" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Draft. Signers can still be changed. Nothing is billed until the Lease is signed.",
      ),
    ).toBeInTheDocument();
    const signers = screen.getByRole("region", { name: "Signers" });
    expect(signers).toHaveTextContent("Tenant U201Primary TenantTo sign");
    expect(screen.getByRole("region", { name: "Occupants" })).toHaveTextContent(
      "1 planned to live there; moves in with the Lease.",
    );
    // Start on the 10th of a 31-day month: $500.00 × 22 ÷ 31 = $354.84, due 5 days later.
    const rent = screen.getByRole("region", { name: "Rent and services" });
    expect(rent).toHaveTextContent("$500.00 × 22 ÷ 31 days = $354.84.");
    expect(rent).toHaveTextContent("Initial Rent $354.84, due 15/12/2026.");
    const money = await screen.findByText(
      "$400.00 due by 15/12/2026, with the Initial Rent.",
    );
    expect(money).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Deposits" })).toHaveTextContent(
      "No pet approved, so no Pet Deposit.",
    );
  });

  it("TEST-FE-846 works out the Initial Rent: day 21 or later adds the whole next month, rounding half up", () => {
    expect(initialRent("2026-11-01", 50000)).toMatchObject({
      days: 30,
      firstPart: 50000,
      nextMonth: 0,
      due: "2026-11-06",
    });
    expect(initialRent("2026-11-21", 50000)).toMatchObject({
      days: 10,
      firstPart: 16667,
      nextMonth: 50000,
      total: 66667,
    });
    // 1 cent × 15 ÷ 30 = 0.5 cent, rounded half up to 1 cent.
    expect(initialRent("2026-11-16", 1).firstPart).toBe(1);
    expect(initialRent("2027-02-28", 28000)).toMatchObject({
      days: 1,
      daysInMonth: 28,
      firstPart: 1000,
      nextMonth: 28000,
    });
  });

  it("TEST-FE-847 shows the termination, the move-out and the whole History, newest first", async () => {
    window.location.hash = "#/leases/lease-U202";
    const timeline = vi.fn().mockResolvedValue({
      items: [
        {
          event_id: "event-3",
          event_kind: "lease.terminate",
          occurred_at: "2026-02-10T04:00:00Z",
          reason: "Customer leaves early",
          actor_id: "actor-1",
          source_reference: null,
          source_href: null,
        },
      ],
      next_cursor: null,
    });
    const client = api({
      get: vi.fn().mockResolvedValue({
        ...terminated,
        timeline: [
          {
            event_id: "event-1",
            event_kind: "lease.draft",
            occurred_at: "2025-05-20T04:00:00Z",
            reason: "New Lease",
            actor_id: "actor-1",
            source_reference: null,
            source_href: null,
          },
          {
            event_id: "event-2",
            event_kind: "lease.sign",
            occurred_at: "2025-05-25T04:00:00Z",
            reason: "Signed",
            actor_id: "actor-1",
            source_reference: null,
            source_href: null,
          },
        ],
        timeline_next_cursor: "cursor-2",
      }),
      timeline,
    });
    show(client);

    const termination = await screen.findByRole("region", {
      name: "Termination",
    });
    expect(termination).toHaveTextContent("Termination date28/02/2026");
    expect(termination).toHaveTextContent("Moved out on28/02/2026");
    const history = screen.getByRole("region", { name: "History" });
    await waitFor(() => {
      expect(within(history).getAllByRole("listitem")).toHaveLength(3);
    });
    expect(timeline).toHaveBeenCalledWith("lease-U202", "cursor-2");
    const items = within(history).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Lease terminatedCustomer leaves early");
    expect(items[2]).toHaveTextContent("Draft made");
  });

  it("TEST-FE-848 offers Retry when there is no answer, never shows another Property's Lease, and hides deposits without access", async () => {
    window.location.hash = "#/leases/lease-U101";
    const get = vi
      .fn()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockResolvedValueOnce(running);
    const depositClient = deposits();
    show(api({ get }), depositClient, new Set(["leases.read"]));

    expect(
      await screen.findByText(/could not be read just now/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("heading", { name: "Lease · U101" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Your account cannot see the deposits."),
    ).toBeInTheDocument();
    expect(depositClient.leaseDeposits).not.toHaveBeenCalled();
    cleanup();

    show(
      api({
        get: vi.fn().mockResolvedValue({ ...running, property_id: "other" }),
      }),
    );
    expect(await screen.findByText(/was not found/)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Lease · U101" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-849 does not count a cancelled renewal draft, and leaves the Initial Rent Due Date to the Invoice after an approved change", async () => {
    window.location.hash = "#/leases/lease-U102";
    const event = (id: string, kind: string, reference: string | null) => ({
      event_id: id,
      event_kind: kind,
      occurred_at: "2026-10-01T04:00:00Z",
      reason: "",
      actor_id: "actor-1",
      source_reference: reference,
      source_href: null,
    });
    const get = vi.fn((id: string) =>
      Promise.resolve(
        id === "lease-U102"
          ? {
              ...ending,
              timeline: [
                event("e1", "lease.renewal_successor", "lease-cancelled"),
                event("e2", "lease.initial_rent_due_date_override", null),
              ],
            }
          : { ...renewal, lease_id: id, status: "CANCELLED" as const },
      ),
    );
    show(api({ get }));

    expect(
      await screen.findByRole("heading", { name: "Lease · U102" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(get).toHaveBeenCalledWith("lease-cancelled");
    });
    expect(screen.getByText(/^This Lease ends on/)).toHaveTextContent(
      `This Lease ends on ${dayText(ending.end_date)} (20 days left).`,
    );
    expect(
      screen.queryByText("A renewal Lease follows this one."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Rent and services" }),
    ).toHaveTextContent(
      "Its Due Date was changed with approval; the Invoice shows it.",
    );
  });
});
