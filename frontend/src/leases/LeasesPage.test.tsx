import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ServiceSettingsApi } from "../settings/serviceSettingsClient";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomerApi, CustomerDetail } from "../customerClient";
import type { DepositApi, DepositResource } from "../depositClient";
import {
  LeaseConflictError,
  LeaseRequestError,
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
} from "../leaseClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import { dayText, todayInPhnomPenh } from "../shell/format";
import type { UnitApi, UnitResource } from "../unitClient";
import {
  LettersUnavailableError,
  type LeaseWarning,
  type LettersApi,
  type TerminationNotice,
} from "../letters/lettersClient";
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
  reservationClient: Partial<ReservationApi> = {
    list: vi.fn<ReservationApi["list"]>().mockResolvedValue({
      items: [],
      next_cursor: null,
      can_create: false,
    }),
  },
  customerClient: Partial<CustomerApi> = {
    get: vi.fn<CustomerApi["get"]>().mockRejectedValue(new Error("no")),
  },
  unitClient: Partial<UnitApi> = {},
  lettersClient: Partial<LettersApi> = {},
  servicesClient: Pick<ServiceSettingsApi, "read"> = {
    read: vi.fn<ServiceSettingsApi["read"]>().mockResolvedValue({
      services: [],
      service_types: [],
      today: "2026-10-25",
      can_manage: false,
    }),
  },
) {
  const letters = {
    warnings: vi.fn<LettersApi["warnings"]>().mockResolvedValue([]),
    notices: vi.fn<LettersApi["notices"]>().mockResolvedValue([]),
    recordNotice: vi.fn<LettersApi["recordNotice"]>(),
    ...lettersClient,
  };
  return render(
    <LeasesPage
      active
      api={client}
      capabilities={capabilities}
      depositApi={depositClient}
      language="en"
      propertyId="property-1"
      customerApi={customerClient as CustomerApi}
      reservationApi={reservationClient as ReservationApi}
      unitApi={unitClient as UnitApi}
      lettersApi={letters}
      servicesApi={servicesClient}
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

describe("Lease actions", () => {
  const signable = lease("U301", {
    lease_id: "lease-sign",
    status: "DRAFTED",
    start_date: "2026-12-10",
    end_date: "2027-12-09",
    signed_at: null,
    can_sign: true,
    can_edit: true,
    occupancies: [],
    version: 4,
    signers: [
      {
        signer_id: "signer-a",
        customer_id: "customer-a",
        customer_name: "Tenant A",
        is_primary_tenant: true,
        signed_at: null,
        added_at: "2026-10-20T03:00:00Z",
      },
      {
        signer_id: "signer-b",
        customer_id: "customer-b",
        customer_name: "Guarantor B",
        is_primary_tenant: false,
        signed_at: null,
        added_at: "2026-10-20T03:00:00Z",
      },
    ],
  });
  // The dialog first looks for the Customer's active Reservation.
  const checked = async (dialog: HTMLElement) => {
    await waitFor(() => {
      expect(dialog).not.toHaveTextContent("Checking for a Reservation");
    });
  };
  const signedBy = (value: LeaseResource, signerId: string): LeaseResource => ({
    ...value,
    version: value.version + 1,
    signers: value.signers.map((signer) =>
      signer.signer_id === signerId
        ? { ...signer, signed_at: "2026-10-25T03:00:00Z" }
        : signer,
    ),
  });

  it("TEST-FE-850 Sign Lease needs a tick for every Signer, records each signature and then signs", async () => {
    window.location.hash = "#/leases/lease-sign";
    const recordSignature = vi.fn((value: LeaseResource, signerId: string) =>
      Promise.resolve(signedBy(value, signerId)),
    );
    const sign = vi.fn<LeaseApi["sign"]>((value) =>
      Promise.resolve({
        ...value,
        status: "SIGNED" as const,
        version: value.version + 1,
      }),
    );
    show(
      api({
        get: vi.fn().mockResolvedValue(signable),
        recordSignature,
        sign,
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog", { name: "Sign Lease · U301" });
    await checked(dialog);
    expect(dialog).toHaveTextContent(
      "Initial Rent of $354.84 becomes due 15/12/2026; billing makes its Invoice.",
    );
    // No active Reservation was found, so neither the line nor the field.
    expect(dialog).not.toHaveTextContent("Reservation of this Customer");
    // The Security Deposit is received in full, so no line about the rest.
    expect(dialog).not.toHaveTextContent("still due");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Tenant A/ }));
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record signing" }),
    );
    expect(
      within(dialog).getByText(
        "Tick every Signer. The Lease is signed only when all have signed.",
      ),
    ).toBeInTheDocument();
    expect(recordSignature).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: /Guarantor B/ }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record signing" }),
    );
    expect(
      await screen.findByText("Lease signed. U301 is Occupied."),
    ).toBeInTheDocument();
    expect(
      recordSignature.mock.calls.map((call) => [call[0].version, call[1]]),
    ).toEqual([
      [4, "signer-a"],
      [5, "signer-b"],
    ]);
    expect(sign.mock.calls[0]?.[0].version).toBe(6);
    expect(sign.mock.calls[0]?.[1]).toEqual({
      event_id: expect.any(String) as string,
      reason: "Every Signer signed the paper Lease",
    });
  });

  it("TEST-FE-851 after an unknown result Try again carries on with the same requests, and a conflict reads the Lease again", async () => {
    window.location.hash = "#/leases/lease-sign";
    const recordSignature = vi
      .fn<LeaseApi["recordSignature"]>()
      .mockImplementationOnce((value: LeaseResource, signerId: string) =>
        Promise.resolve(signedBy(value, signerId)),
      )
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockImplementationOnce((value: LeaseResource, signerId: string) =>
        Promise.resolve(signedBy(value, signerId)),
      );
    const sign = vi.fn().mockRejectedValue(new LeaseConflictError());
    const get = vi.fn().mockResolvedValue(signable);
    show(api({ get, recordSignature, sign }));

    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog");
    await checked(dialog);
    for (const box of within(dialog).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record signing" }),
    );
    expect(
      await within(dialog).findByText(
        /We could not tell whether this was saved/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(sign).toHaveBeenCalledTimes(1);
    });
    // The first signature is not sent again; the second is resent with the same key.
    expect(recordSignature.mock.calls.map((call) => call[1])).toEqual([
      "signer-a",
      "signer-b",
      "signer-b",
    ]);
    expect(recordSignature.mock.calls[2]?.[3]).toBe(
      recordSignature.mock.calls[1]?.[3],
    );
    expect(
      await screen.findByText(/This Lease or its Unit changed meanwhile/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("TEST-FE-852 Edit draft checks the dates, Rent and reason, sends whole cents, and keeps the request on Try again", async () => {
    window.location.hash = "#/leases/lease-sign";
    const update = vi
      .fn()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockRejectedValueOnce(new LeaseRequestError())
      .mockResolvedValueOnce({ ...signable, monthly_rent_usd_cents: 52050 });
    show(api({ get: vi.fn().mockResolvedValue(signable), update }));

    fireEvent.click(await screen.findByRole("button", { name: "Edit draft" }));
    const dialog = screen.getByRole("dialog", { name: "Edit draft · U301" });
    fireEvent.change(within(dialog).getByLabelText("End Date"), {
      target: { value: "2026-12-01" },
    });
    fireEvent.change(within(dialog).getByLabelText("Monthly Rent"), {
      target: { value: "520.5" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent(
      "The End Date must be after the Start Date and the last day of a month.",
    );
    expect(dialog).toHaveTextContent("Say why it changed.");
    expect(update).not.toHaveBeenCalled();

    // Not the last day of a month.
    fireEvent.change(within(dialog).getByLabelText("End Date"), {
      target: { value: "2027-12-09" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent("the last day of a month");
    fireEvent.change(within(dialog).getByLabelText("End Date"), {
      target: { value: "2027-12-31" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Why it changed/), {
      target: { value: "Rent agreed again" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Try again" }),
    );
    expect(
      await within(dialog).findByText(/The server refused this/),
    ).toBeInTheDocument();
    expect(update.mock.calls[0]?.[1]).toMatchObject({
      start_date: "2026-12-10",
      end_date: "2027-12-31",
      monthly_rent_usd_cents: 52050,
      reason: "Rent agreed again",
    });
    expect(update.mock.calls[1]?.[2]).toBe(update.mock.calls[0]?.[2]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The draft was saved.")).toBeInTheDocument();
  });

  it("TEST-FE-853 signing names the Customer's active Reservation, and a refusal after a signature keeps it shown", async () => {
    window.location.hash = "#/leases/lease-sign";
    const reservation = (
      id: string,
      overrides: Partial<ReservationResource>,
    ): ReservationResource =>
      ({
        reservation_id: id,
        property_id: "property-1",
        unit_id: "unit-U301",
        customer_id: "customer-U301",
        status: "ACTIVE",
        ...overrides,
      }) as ReservationResource;
    const list = vi
      .fn<ReservationApi["list"]>()
      .mockResolvedValueOnce({
        items: [reservation("other-customer", { customer_id: "customer-x" })],
        next_cursor: "page-2",
        can_create: false,
      })
      .mockResolvedValueOnce({
        items: [reservation("reservation-301", {})],
        next_cursor: null,
        can_create: false,
      });
    const recordSignature = vi.fn((value: LeaseResource, signerId: string) =>
      Promise.resolve(signedBy(value, signerId)),
    );
    const sign = vi
      .fn<LeaseApi["sign"]>()
      .mockRejectedValueOnce(new LeaseRequestError())
      .mockImplementationOnce((value) =>
        Promise.resolve({ ...value, status: "SIGNED" as const }),
      );
    show(
      api({ get: vi.fn().mockResolvedValue(signable), recordSignature, sign }),
      deposits(),
      null,
      { list },
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog");
    await checked(dialog);
    expect(list.mock.calls).toEqual([
      ["property-1", "ACTIVE", undefined],
      ["property-1", "ACTIVE", "page-2"],
    ]);
    expect(dialog).toHaveTextContent(
      "An active Reservation of this Customer for this Unit is completed in the same step",
    );
    for (const box of within(dialog).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record signing" }),
    );
    expect(
      await within(dialog).findByText(/The server refused the signing/),
    ).toBeInTheDocument();
    expect(sign.mock.calls[0]?.[1]).toMatchObject({
      reservation_id: "reservation-301",
    });
    // Both signatures were recorded; the page behind the dialog shows them.
    expect(screen.getByRole("region", { name: "Signers" })).toHaveTextContent(
      /Guarantor BSigned/,
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record signing" }),
    );
    expect(
      await screen.findByText("Lease signed. U301 is Occupied."),
    ).toBeInTheDocument();
    expect(recordSignature).toHaveBeenCalledTimes(2);
    expect(sign.mock.calls[1]?.[1]).toEqual(sign.mock.calls[0]?.[1]);
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("TEST-FE-854 Cancel draft needs a memo and keeps the request on Try again", async () => {
    window.location.hash = "#/leases/lease-sign";
    const cancel = vi
      .fn<LeaseApi["cancel"]>()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockImplementationOnce((value) =>
        Promise.resolve({ ...value, status: "CANCELLED" as const }),
      );
    show(api({ get: vi.fn().mockResolvedValue(signable), cancel }));

    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel draft" }),
    );
    const dialog = screen.getByRole("dialog", { name: "Cancel draft · U301" });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Cancel the draft" }),
    );
    expect(dialog).toHaveTextContent("Write why it is cancelled.");
    expect(cancel).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/Memo/), {
      target: { value: " Customer chose another Unit " },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Cancel the draft" }),
    );
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Try again" }),
    );
    expect(
      await screen.findByText("The draft was cancelled."),
    ).toBeInTheDocument();
    expect(cancel.mock.calls[0]?.[1]).toMatchObject({
      reason: "Customer chose another Unit",
    });
    expect(cancel.mock.calls[1]?.[1]).toEqual(cancel.mock.calls[0]?.[1]);
    expect(cancel.mock.calls[1]?.[2]).toBe(cancel.mock.calls[0]?.[2]);
  });

  it("TEST-FE-855 Record move-in offers the Signers and planned occupants, checks the date and keeps the Occupancy ids on Try again", async () => {
    window.location.hash = "#/leases/lease-move";
    const start = addDays(today, -3);
    const ready = lease("U302", {
      lease_id: "lease-move",
      start_date: start,
      end_date: addDays(today, 360),
      signed_at: `${addDays(today, -5)}T03:00:00Z`,
      occupancies: [],
      can_move_in: true,
      planned_occupant_customer_ids: ["customer-U302", "customer-kid"],
    });
    const get = vi.fn<CustomerApi["get"]>((id) =>
      Promise.resolve({
        customer_id: id,
        legal_name: "Child C",
      } as CustomerDetail),
    );
    const recordMoveIn = vi
      .fn<LeaseApi["recordMoveIn"]>()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockImplementationOnce((value) => Promise.resolve(value));
    show(
      api({ get: vi.fn().mockResolvedValue(ready), recordMoveIn }),
      deposits(),
      null,
      undefined,
      { get },
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Record move-in" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Record move-in · U302",
    });
    expect(within(dialog).getByLabelText("Move-in date")).toHaveValue(today);
    expect(
      await within(dialog).findByRole("checkbox", { name: /Child C/ }),
    ).toBeChecked();
    expect(
      within(dialog).getByRole("checkbox", { name: /Tenant U302/ }),
    ).toBeChecked();
    expect(get).toHaveBeenCalledWith("customer-kid");

    fireEvent.change(within(dialog).getByLabelText("Move-in date"), {
      target: { value: addDays(start, -1) },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record move-in" }),
    );
    expect(dialog).toHaveTextContent(
      `Choose a date from ${dayText(start)} to ${dayText(today)}.`,
    );
    expect(recordMoveIn).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Move-in date"), {
      target: { value: start },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record move-in" }),
    );
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Try again" }),
    );
    expect(await screen.findByText("Move-in recorded.")).toBeInTheDocument();
    const first = recordMoveIn.mock.calls[0]?.[1];
    expect(first).toMatchObject({
      actual_move_in_date: start,
      reason: "Move-in recorded",
    });
    expect(first?.occupants.map((item) => item.customer_id)).toEqual([
      "customer-U302",
      "customer-kid",
    ]);
    expect(recordMoveIn.mock.calls[1]?.[1]).toEqual(first);
    expect(recordMoveIn.mock.calls[1]?.[2]).toBe(
      recordMoveIn.mock.calls[0]?.[2],
    );
    // Try again sends the same Lease version as the first try.
    expect(recordMoveIn.mock.calls[1]?.[0].version).toBe(
      recordMoveIn.mock.calls[0]?.[0].version,
    );
  });

  it("TEST-FE-856 Record move-in is not offered before the Start Date or on a renewal", async () => {
    const ready = {
      start_date: addDays(today, -3),
      signed_at: `${addDays(today, -5)}T03:00:00Z`,
      occupancies: [],
      can_move_in: true,
    };
    for (const extra of [
      { start_date: addDays(today, 2) },
      { predecessor_lease_id: "lease-before" },
      {},
    ]) {
      cleanup();
      window.location.hash = "#/leases/lease-move";
      const value = lease("U302", {
        lease_id: "lease-move",
        ...ready,
        ...extra,
      });
      show(api({ get: vi.fn().mockResolvedValue(value) }));
      await screen.findByRole("heading", { name: /Lease · U302/ });
      expect(
        screen.queryByRole("button", { name: "Record move-in" }) !== null,
      ).toBe(Object.keys(extra).length === 0);
    }
  });
});

describe("Move-in with someone else", () => {
  it("TEST-FE-861 Record move-in can add an active Customer who is not named in the Lease", async () => {
    window.location.hash = "#/leases/lease-move";
    const ready = lease("U302", {
      lease_id: "lease-move",
      start_date: addDays(today, -3),
      end_date: addDays(today, 360),
      signed_at: `${addDays(today, -5)}T03:00:00Z`,
      occupancies: [],
      can_move_in: true,
    });
    const recordMoveIn = vi
      .fn<LeaseApi["recordMoveIn"]>()
      .mockImplementation((value) => Promise.resolve(value));
    const customers: Partial<CustomerApi> = {
      get: vi.fn<CustomerApi["get"]>().mockRejectedValue(new Error("no")),
      list: vi.fn<CustomerApi["list"]>().mockResolvedValue({
        items: [
          {
            customer_id: "customer-U302",
            legal_name: "Tenant U302",
            active: true,
            relationship_indicators: [],
          },
          {
            customer_id: "customer-sister",
            legal_name: "Sister S",
            active: true,
            relationship_indicators: [],
          },
        ],
        next_cursor: null,
        can_manage: true,
      }),
    };
    show(
      api({ get: vi.fn().mockResolvedValue(ready), recordMoveIn }),
      deposits(),
      null,
      undefined,
      customers,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Record move-in" }),
    );
    const dialog = screen.getByRole("dialog");
    const add = await within(dialog).findByLabelText(
      "Someone else moves in too",
    );
    // The Primary Tenant is already listed, so only the other Customer is offered.
    expect(
      within(add)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Add a Customer…", "Sister S"]);
    fireEvent.change(add, { target: { value: "customer-sister" } });
    // Choosing alone adds nobody; the Add button does.
    expect(
      within(dialog).queryByRole("checkbox", { name: "Sister S" }),
    ).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(
      within(dialog).getByRole("checkbox", { name: "Sister S" }),
    ).toBeChecked();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record move-in" }),
    );
    await waitFor(() => {
      expect(recordMoveIn).toHaveBeenCalledTimes(1);
    });
    expect(
      recordMoveIn.mock.calls[0]?.[1].occupants.map((item) => item.customer_id),
    ).toEqual(["customer-U302", "customer-sister"]);
  });
});

describe("New Lease and Renew", () => {
  const unit = (number: string, status: UnitResource["status"]) =>
    ({
      unit_id: `unit-${number}`,
      unit_number: number,
      status,
    }) as UnitResource;
  const units: Partial<UnitApi> = {
    list: vi.fn<UnitApi["list"]>().mockResolvedValue({
      items: [
        unit("U402", "VACANT"),
        unit("U401", "CLEANING"),
        unit("U101", "OCCUPIED"),
        unit("U403", "RESERVED"),
      ],
      next_cursor: null,
      can_manage: true,
    }),
  };
  const people = (): Partial<CustomerApi> => ({
    list: vi.fn<CustomerApi["list"]>().mockResolvedValue({
      items: [
        {
          customer_id: "customer-b",
          legal_name: "Bopha",
          active: true,
          relationship_indicators: [],
        },
        {
          customer_id: "customer-a",
          legal_name: "Arun",
          phone_number: "012 345 678",
          active: true,
          relationship_indicators: [],
        },
        {
          customer_id: "customer-c",
          legal_name: "Chenda",
          active: true,
          relationship_indicators: [],
        },
      ],
      next_cursor: null,
      can_manage: true,
    }),
  });
  const pickIn = (label: string, value: string) => {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  };

  it("TEST-FE-857 New Lease offers open Units, fills a one-year End Date, previews the bill, asks before saving and keeps the Lease id on Try again", async () => {
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockImplementationOnce((_property, source) =>
        Promise.resolve(
          lease("U402", { lease_id: source.lease_id, status: "DRAFTED" }),
        ),
      );
    show(api({ create }), deposits(), null, undefined, people(), units);

    fireEvent.click(await screen.findByRole("link", { name: "New Lease" }));
    const unitBox = await screen.findByLabelText("Unit");
    expect(
      within(unitBox)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Choose a Unit", "U401", "U402"]);
    pickIn("Unit", "unit-U402");
    pickIn("Primary Tenant", "customer-a");
    pickIn("Other Signers", "customer-b");
    pickIn("Other occupants", "customer-c");
    fireEvent.change(screen.getByLabelText("Start Date"), {
      target: { value: "2026-12-22" },
    });
    expect(screen.getByLabelText("End Date")).toHaveValue("2027-12-31");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(screen.getByText("Enter the monthly Rent.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "310" },
    });
    const preview = screen.getByRole("region", { name: "What will be billed" });
    // 22 to 31 December is 10 of 31 days; day 21 or later adds January.
    expect(preview).toHaveTextContent(
      "Initial Rent $410.00, due 27/12/2026, with the rest of the Security Deposit.",
    );
    expect(preview).toHaveTextContent("$310.00 × 10 ÷ 31 days = $100.00.");
    expect(preview).toHaveTextContent(
      "Security Deposit: one month's Rent ($310.00), entered after signing.",
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "A pet is approved" }),
    );
    fireEvent.change(screen.getByLabelText("Which pet"), {
      target: { value: "One small cat" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    const dialog = screen.getByRole("dialog", {
      name: "Save the draft · U402?",
    });
    expect(create).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Try again" }),
    );
    await waitFor(() => {
      expect(window.location.hash).toBe(
        `#/leases/${create.mock.calls[0]?.[1].lease_id ?? ""}`,
      );
    });
    const sent = create.mock.calls[0]?.[1];
    expect(sent).toMatchObject({
      unit_id: "unit-U402",
      primary_tenant_id: "customer-a",
      start_date: "2026-12-22",
      end_date: "2027-12-31",
      monthly_rent_usd_cents: 31000,
      predecessor_lease_id: null,
      planned_occupant_customer_ids: ["customer-a", "customer-c"],
      security_deposit_id: null,
      service_terms: [],
      pet_term: {
        deposit_required_by_signed_terms: true,
        pet_description: "One small cat",
      },
    });
    expect(sent?.additional_signers.map((item) => item.customer_id)).toEqual([
      "customer-b",
    ]);
    expect(create.mock.calls[1]?.[1]).toEqual(sent);
    expect(create.mock.calls[1]?.[2]).toBe(create.mock.calls[0]?.[2]);
  });

  it("TEST-FE-1004 New Lease picks Services by type: None first for an Only one type, Trash Collection by default, tick boxes for One or more, a later Service greyed; they are saved as terms from the Start Date; a failed read waits with Retry", async () => {
    const period = (id: string, from: string) => [
      { approval_period_id: id, effective_from: from, effective_through: null },
    ];
    const settings = {
      services: [
        {
          service_id: "svc-trash",
          service_code: "TRASH_COLLECTION",
          name_en: "Trash Collection",
          name_km: null,
          service_type_id: "type-trash",
          version: 1,
          rate_today_usd_cents: 300,
          next_rate: {
            monthly_rate_usd_cents: 350,
            effective_date: "2027-01-01",
          },
          rates: [
            { monthly_rate_usd_cents: 300, effective_date: "2026-01-01" },
            { monthly_rate_usd_cents: 350, effective_date: "2027-01-01" },
          ],
          approval_periods: period("ap-trash", "2026-01-01"),
          leases_using: 0,
        },
        {
          service_id: "svc-trash-big",
          service_code: "SVC_B",
          name_en: "Trash, large bin",
          name_km: null,
          service_type_id: "type-trash",
          version: 1,
          rate_today_usd_cents: 600,
          next_rate: null,
          rates: [
            { monthly_rate_usd_cents: 600, effective_date: "2026-01-01" },
          ],
          approval_periods: period("ap-big", "2026-01-01"),
          leases_using: 0,
        },
        {
          service_id: "svc-car",
          service_code: "SVC_C",
          name_en: "Car park",
          name_km: null,
          service_type_id: "type-park",
          version: 1,
          rate_today_usd_cents: 2000,
          next_rate: null,
          rates: [
            { monthly_rate_usd_cents: 2000, effective_date: "2026-01-01" },
          ],
          approval_periods: period("ap-car", "2026-01-01"),
          leases_using: 0,
        },
        {
          service_id: "svc-bike",
          service_code: "SVC_D",
          name_en: "Bike park",
          name_km: null,
          service_type_id: "type-park",
          version: 1,
          rate_today_usd_cents: null,
          next_rate: {
            monthly_rate_usd_cents: 500,
            effective_date: "2027-03-01",
          },
          rates: [
            { monthly_rate_usd_cents: 500, effective_date: "2027-03-01" },
          ],
          approval_periods: period("ap-bike", "2027-03-01"),
          leases_using: 0,
        },
      ],
      service_types: [
        {
          service_type_id: "type-trash",
          name_en: "Trash",
          name_km: null,
          one_per_lease: true,
          removed: false,
          version: 1,
          services: 2,
        },
        {
          service_type_id: "type-park",
          name_en: "Parking",
          name_km: null,
          one_per_lease: false,
          removed: false,
          version: 1,
          services: 2,
        },
      ],
      today: "2026-10-25",
      can_manage: false,
    };
    let fail = true;
    const read = vi.fn<ServiceSettingsApi["read"]>(() =>
      fail ? Promise.reject(new Error("down")) : Promise.resolve(settings),
    );
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockImplementation((_property, source) =>
        Promise.resolve(
          lease("U402", { lease_id: source.lease_id, status: "DRAFTED" }),
        ),
      );
    show(
      api({ create }),
      deposits(),
      null,
      undefined,
      people(),
      units,
      {},
      { read },
    );
    fireEvent.click(await screen.findByRole("link", { name: "New Lease" }));
    await screen.findByLabelText("Unit");
    pickIn("Unit", "unit-U402");
    pickIn("Primary Tenant", "customer-a");
    fireEvent.change(screen.getByLabelText("Start Date"), {
      target: { value: "2027-01-10" },
    });
    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "310" },
    });
    // The Services could not be read: the draft waits, Retry reads them again.
    expect(
      await screen.findByText(/The Services could not be read just now/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      screen.getByText("The Services are not read yet. Press Retry above."),
    ).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    const trash = await screen.findByRole("group", { name: /^Trash/ });
    expect(
      within(trash)
        .getAllByRole("radio")
        .map((radio) => radio.closest("label")?.textContent),
    ).toEqual([
      "None",
      "Trash Collection$3.50 a month",
      "Trash, large bin$6.00 a month",
    ]);
    // Trash Collection is chosen by default; its rate on the Start Date is the January one.
    expect(
      within(trash).getByRole("radio", { name: /^Trash Collection/ }),
    ).toBeChecked();
    const parking = screen.getByRole("group", { name: /^Parking/ });
    expect(within(parking).getAllByRole("checkbox")).toHaveLength(2);
    const bike = within(parking).getByRole("checkbox", { name: /^Bike park/ });
    expect(bike).toBeDisabled();
    expect(bike.closest("label")).toHaveTextContent("Starts 01/03/2027");
    fireEvent.click(
      within(parking).getByRole("checkbox", { name: /^Car park/ }),
    );
    // Choosing the large bin leaves out Trash Collection.
    fireEvent.click(
      within(trash).getByRole("radio", { name: /^Trash, large/ }),
    );
    expect(
      within(trash).getByRole("radio", { name: /^Trash Collection/ }),
    ).not.toBeChecked();
    const preview = screen.getByRole("region", { name: "What will be billed" });
    expect(preview).toHaveTextContent(
      "Trash, large bin: $6.00 a month from the Start Date",
    );
    expect(preview).toHaveTextContent("Car park: $20.00 a month");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    const dialog = screen.getByRole("dialog", {
      name: "Save the draft · U402?",
    });
    expect(dialog).toHaveTextContent("Services: Trash, large bin, Car park.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    await waitFor(() => {
      expect(create).toHaveBeenCalled();
    });
    expect(create.mock.calls[0]?.[1].service_terms).toEqual([
      {
        term_id: expect.any(String) as string,
        property_service_id: "svc-trash-big",
        applicable_from: "2027-01-10",
        applicable_through: null,
        service_approval_period_id: "ap-big",
        terms_reference: "Chosen on the New Lease form",
      },
      {
        term_id: expect.any(String) as string,
        property_service_id: "svc-car",
        applicable_from: "2027-01-10",
        applicable_through: null,
        service_approval_period_id: "ap-car",
        terms_reference: "Chosen on the New Lease form",
      },
    ]);
  });

  it("TEST-FE-858 a Lease from a Booking takes its Unit, Customer, Rent and Security Deposit", async () => {
    window.location.hash = "#/leases/new%3Aresv-1";
    const get = vi.fn<ReservationApi["get"]>().mockResolvedValue({
      reservation_id: "resv-1",
      status: "ACTIVE",
      unit_id: "unit-U403",
      unit_number: "U403",
      customer_id: "customer-b",
      customer_name: "Bopha",
      agreed_monthly_rent_usd_cents: 40000,
      deposit_id: "deposit-resv-1",
      deposit_required_usd_cents: 40000,
      deposit_received_usd_cents: 8000,
    } as ReservationResource);
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockImplementation((_property, source) =>
        Promise.resolve(lease("U403", { lease_id: source.lease_id })),
      );
    show(api({ create }), deposits(), null, { get }, people(), units);

    expect(await screen.findByLabelText("Unit")).toHaveValue("U403");
    expect(screen.getByLabelText("Primary Tenant")).toHaveValue("Bopha");
    expect(screen.getByLabelText("Monthly Rent")).toHaveValue("400.00");
    expect(
      screen.getByRole("region", { name: "What will be billed" }),
    ).toHaveTextContent(
      "Security Deposit: $80.00 received of $400.00 from the Booking; $320.00 still due by",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Save draft",
      }),
    );
    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(1);
    });
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      unit_id: "unit-U403",
      primary_tenant_id: "customer-b",
      monthly_rent_usd_cents: 40000,
      security_deposit_id: "deposit-resv-1",
      reason: "Lease drafted from the Booking",
    });
  });

  it("TEST-FE-859 Renew starts the day after the old End Date with the same Unit, tenant and other Signers, linked to the old Lease", async () => {
    window.location.hash = "#/leases/lease-U101";
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockImplementation((_property, source) =>
        Promise.resolve(lease("U101", { lease_id: source.lease_id })),
      );
    show(api({ create }), deposits(), null, undefined, people(), units);

    fireEvent.click(await screen.findByRole("link", { name: "Renew" }));
    expect(await screen.findByLabelText("Unit")).toHaveValue("U101");
    const next = addDays(running.end_date ?? today, 1);
    expect(screen.getByLabelText("Start Date")).toHaveValue(next);
    expect(screen.getByText("Guarantor")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "What will be billed" }),
    ).toHaveTextContent(
      "Security Deposit: the old Lease's deposit does not move by itself.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Save draft",
      }),
    );
    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(1);
    });
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      unit_id: "unit-U101",
      primary_tenant_id: "customer-U101",
      start_date: next,
      predecessor_lease_id: "lease-U101",
      monthly_rent_usd_cents: 50000,
    });
    expect(
      create.mock.calls[0]?.[1].additional_signers.map(
        (item) => item.customer_id,
      ),
    ).toEqual(["customer-guarantor"]);
  });

  it("TEST-FE-860 a refused save after a lost answer opens the draft that was saved, and a Booking that is no longer active makes no Lease", async () => {
    let savedId = "";
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockImplementationOnce((_property, source) => {
        savedId = source.lease_id;
        return Promise.reject(new LeaseUnavailableError());
      })
      .mockRejectedValueOnce(new LeaseConflictError());
    const get = vi.fn((id: string) =>
      id === savedId
        ? Promise.resolve(lease("U402", { lease_id: id, status: "DRAFTED" }))
        : Promise.reject(new LeaseRequestError()),
    );
    window.location.hash = "#/leases/new";
    show(api({ create, get }), deposits(), null, undefined, people(), units);

    await screen.findByLabelText("Unit");
    pickIn("Unit", "unit-U402");
    await waitFor(() => {
      expect(screen.getByLabelText("Unit")).toHaveValue("unit-U402");
    });
    pickIn("Primary Tenant", "customer-a");
    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "300" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Save draft",
      }),
    );
    await within(screen.getByRole("dialog")).findByRole("button", {
      name: "Try again",
    });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "320" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Save draft",
      }),
    );
    await waitFor(() => {
      expect(window.location.hash).toBe(`#/leases/${savedId}`);
    });
    expect(create.mock.calls[1]?.[1].lease_id).toBe(savedId);

    cleanup();
    window.location.hash = "#/leases/new%3Aresv-old";
    const reservations = {
      get: vi.fn<ReservationApi["get"]>().mockResolvedValue({
        reservation_id: "resv-old",
        status: "EXPIRED",
        customer_name: "Bopha",
      } as unknown as ReservationResource),
    };
    show(api({ create }), deposits(), null, reservations, people(), units);
    expect(
      await screen.findByText(/The Booking of Bopha is no longer active/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save draft" })).toBeNull();
  });

  function lw(sequence: number): LeaseWarning {
    return {
      id: `warning-${String(sequence)}`,
      lease_id: "lease-U101",
      warning_sequence: sequence,
      violation_date: addDays(today, -40 + sequence),
      warning_date: addDays(today, -39 + sequence),
      violation_description: `Noise at night ${String(sequence)}`,
      lease_provision: "11.3",
      communication_record: "Handed to the tenant",
    };
  }

  function notice(id: string, ends: string): TerminationNotice {
    return {
      id,
      lease_id: "lease-U101",
      notice_date: addDays(ends, -30),
      intended_termination_date: ends,
      notice_text: "The Lease ends.",
      governing_lease_provision: "Signed Lease: Rent provision",
      occurred_at: "2026-10-01T03:00:00Z",
      context: {
        approved_grounds:
          "Rent unpaid after the day-30 default notice (DL-073)",
        notice_period_terms: "30 days",
        evidence_reference: `TN-${id}`,
        communication_record: "Handed to the tenant: signed",
      },
      current_effect: "NOTICE_ONLY",
    };
  }

  async function openTerminate() {
    fireEvent.click(await screen.findByRole("button", { name: /^Terminate/ }));
    return screen.findByRole("dialog", {
      name: "Terminate the Lease · U101",
    });
  }

  it("TEST-FE-869 Terminate for early leaving sends the signed-Lease evidence, says the Security Deposit is kept and needs every field", async () => {
    window.location.hash = "#/leases/lease-U101";
    const terminate = vi
      .fn<LeaseApi["terminate"]>()
      .mockImplementation((value, source) =>
        Promise.resolve({
          ...value,
          status: "TERMINATED",
          actual_termination_date: source.actual_termination_date,
        }),
      );
    show(api({ terminate }));
    const button = await screen.findByRole("button", { name: /^Terminate/ });
    expect(within(button).getByText("Manager")).toBeInTheDocument();
    const dialog = await openTerminate();
    fireEvent.click(within(dialog).getByRole("button", { name: "Terminate" }));
    expect(within(dialog).getByText("Choose the ground.")).toBeInTheDocument();
    expect(within(dialog).getByText("Write the evidence.")).toBeInTheDocument();
    expect(within(dialog).getByText("Write the reason.")).toBeInTheDocument();
    expect(terminate).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("radio", { name: /Customer leaves early/ }),
    );
    expect(
      within(dialog).getByText(
        "The Security Deposit is kept in full and is not used for what the Customer owes.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "The Unit stays Occupied until the hand-back is recorded.",
      ),
    ).toBeInTheDocument();
    // A day after today cannot be recorded.
    fireEvent.change(within(dialog).getByLabelText("Termination date"), {
      target: { value: addDays(today, 1) },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Evidence/), {
      target: { value: " Customer letter 24/10 " },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Moves to another city" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Terminate" }));
    expect(
      within(dialog).getByText(/Enter a date from .* up to today\./),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Termination date"), {
      target: { value: today },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Terminate" }));
    expect(
      await screen.findByText(
        `Lease of U101 terminated as of ${dayText(today)}.`,
      ),
    ).toBeInTheDocument();
    expect(terminate).toHaveBeenCalledTimes(1);
    const [, source, key] = terminate.mock.calls[0] ?? [];
    expect(key).toEqual(expect.any(String));
    expect(source).toEqual({
      event_id: expect.any(String) as string,
      actual_termination_date: today,
      governing_event_reference: "BR-LEASE-021",
      reason: "Moves to another city",
      context: {
        basis: "VOLUNTARY_EARLY",
        signed_lease_provision:
          "Signed Lease: early leaving at the Customer's request (BR-LEASE-021)",
        approved_grounds:
          "The Customer leaves before the End Date at the Customer's request",
        management_authorization_reference:
          "Approved in the app by the signed-in Owner or Manager (leases.terminate)",
        evidence_reference: "Customer letter 24/10",
        notice_required: false,
        notice_exception_reason:
          "No landlord notice: the Customer asked to leave early",
      },
    });
  });

  it("TEST-FE-870 a violation termination needs 3 ticked warnings, and the pet tick keeps both Deposits", async () => {
    window.location.hash = "#/leases/lease-U101";
    const terminate = vi
      .fn<LeaseApi["terminate"]>()
      .mockImplementation((value) => Promise.resolve(value));
    const withPet = { ...running, pet_deposit_required: true };
    show(
      api({ get: vi.fn().mockResolvedValue(withPet), terminate }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {
        warnings: vi
          .fn<LettersApi["warnings"]>()
          .mockResolvedValue([lw(1), lw(2), lw(3)]),
      },
    );
    const dialog = await openTerminate();
    fireEvent.click(
      within(dialog).getByRole("radio", { name: /Lease violation/ }),
    );
    const boxes = await within(dialog).findAllByRole("checkbox", {
      name: /^Warning/,
    });
    const [first, second, third] = boxes;
    if (!first || !second || !third) throw new Error("three warnings");
    fireEvent.click(first);
    fireEvent.click(third);
    fireEvent.change(within(dialog).getByLabelText(/^Evidence/), {
      target: { value: "Warning letters W-1 to W-3" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Dog kept against the rules" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Terminate" }));
    expect(
      within(dialog).getByText("Tick at least 3 written warnings."),
    ).toBeInTheDocument();
    fireEvent.click(second);
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: /Pet-rule violation/ }),
    );
    expect(
      within(dialog).getByText(
        "The Pet Deposit is kept too (pet-rule termination).",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "The Security Deposit is kept in full and is not used for what the Customer owes.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Terminate" }));
    await waitFor(() => {
      expect(terminate).toHaveBeenCalledTimes(1);
    });
    const source = terminate.mock.calls[0]?.[1];
    expect(source?.governing_event_reference).toBe("BR-DEP-022");
    expect(source?.context).toMatchObject({
      basis: "CUSTOMER_VIOLATION",
      approved_grounds: "Pet-rule violation after three written warnings",
      notice_required: false,
      warning_ids: ["warning-1", "warning-2", "warning-3"],
    });
  });

  it("TEST-FE-871 from Letters the Rent ground records the termination notice first, keeps what was typed, and refuses a termination before the notice period ends", async () => {
    window.location.hash = "#/leases/terminate:lease-U101";
    const terminate = vi
      .fn<LeaseApi["terminate"]>()
      .mockImplementation((value) => Promise.resolve(value));
    const fresh = notice("notice-new", addDays(today, 30));
    const notices = vi.fn<LettersApi["notices"]>().mockResolvedValue([]);
    const recordNotice = vi
      .fn<LettersApi["recordNotice"]>()
      .mockImplementation(() => {
        notices.mockResolvedValue([fresh]);
        return Promise.resolve(fresh);
      });
    show(
      api({ terminate }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {
        notices,
        recordNotice,
      },
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Terminate the Lease · U101",
    });
    expect(
      within(dialog).getByRole<HTMLInputElement>("radio", {
        name: /Rent unpaid after the day-30 notice/,
      }).checked,
    ).toBe(true);
    expect(
      await within(dialog).findByText(/No termination notice yet/),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Evidence/), {
      target: { value: "TN-7" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: /Record termination notice/ }),
    );
    const record = await screen.findByRole("dialog", {
      name: "Termination notice · U101",
    });
    fireEvent.change(within(record).getByLabelText(/Letter number/), {
      target: { value: "TN-7" },
    });
    fireEvent.change(within(record).getByLabelText(/How it was given/), {
      target: { value: "HAND" },
    });
    fireEvent.change(within(record).getByLabelText(/^Details/), {
      target: { value: "signed our copy" },
    });
    fireEvent.click(
      within(record).getByRole("button", { name: "Record termination notice" }),
    );
    expect(
      await screen.findByText("Termination notice recorded for U101."),
    ).toBeInTheDocument();
    expect(recordNotice).toHaveBeenCalledWith(
      "property-1",
      "lease-U101",
      {
        notice_id: expect.any(String) as string,
        expected_lease_version: running.version,
        notice_date: today,
        intended_termination_date: addDays(today, 30),
        notice_text: `The Lease of U101 ends on ${dayText(addDays(today, 30))} because the Rent is still unpaid after the day-20 warning letter and the day-30 default notice.`,
        governing_lease_provision:
          "Signed Lease: Rent not paid after the day-20 warning letter and the day-30 default notice (BR-LEASE-028)",
        approved_grounds:
          "Rent unpaid after the day-30 default notice (DL-073)",
        notice_period_terms: "The Lease ends on the date written in the notice",
        evidence_reference: "TN-7",
        communication_record: "Handed to the tenant: signed our copy",
        authorization_reference:
          "Approved in the app by the signed-in Owner or Manager (leases.terminate)",
        reason: "Termination notice given",
      },
      expect.any(String),
    );
    // Back on Terminate with the new notice chosen; its period has not ended yet.
    const again = await screen.findByRole("dialog", {
      name: "Terminate the Lease · U101",
    });
    expect(
      await within(again).findByText(/The notice period ends on/),
    ).toBeInTheDocument();
    expect(
      within(again).getByRole<HTMLInputElement>("radio", { name: /^Given/ })
        .checked,
    ).toBe(true);
    // What was typed before the notice is still there.
    expect(
      within(again).getByLabelText<HTMLInputElement>(/^Evidence/).value,
    ).toBe("TN-7");
    fireEvent.change(within(again).getByLabelText(/^Reason/), {
      target: { value: "Rent unpaid" },
    });
    fireEvent.click(within(again).getByRole("button", { name: "Terminate" }));
    expect(
      within(again).getByText(/Enter a date from .* up to today\./),
    ).toBeInTheDocument();
    expect(terminate).not.toHaveBeenCalled();
  });

  it("TEST-FE-872 a Rent termination names the chosen current notice whose period is over, and nobody without the right sees Terminate", async () => {
    window.location.hash = "#/leases/lease-U101";
    const terminate = vi
      .fn<LeaseApi["terminate"]>()
      .mockImplementation((value) => Promise.resolve(value));
    const over = notice("notice-over", addDays(today, -1));
    show(
      api({ terminate }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {
        notices: vi.fn<LettersApi["notices"]>().mockResolvedValue([
          {
            ...notice("notice-old", addDays(today, -5)),
            current_effect: "SUPERSEDED",
          },
          over,
          // Recorded last, so chosen first; its period is not over yet.
          {
            ...notice("notice-late", addDays(today, 3)),
            occurred_at: "2026-10-02T03:00:00Z",
          },
        ]),
      },
    );
    const dialog = await openTerminate();
    fireEvent.click(
      within(dialog).getByRole("radio", { name: /Rent unpaid after/ }),
    );
    // A superseded notice is not offered.
    const choices = await within(dialog).findAllByRole("radio", {
      name: /^Given/,
    });
    expect(choices).toHaveLength(2);
    expect(
      choices.map((choice) => (choice as HTMLInputElement).checked),
    ).toEqual([false, true]);
    fireEvent.click(
      within(dialog).getByRole("radio", { name: /TN-notice-over/ }),
    );
    fireEvent.change(within(dialog).getByLabelText(/^Evidence/), {
      target: { value: "TN-over" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Rent unpaid" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Terminate" }));
    await waitFor(() => {
      expect(terminate).toHaveBeenCalledTimes(1);
    });
    const source = terminate.mock.calls[0]?.[1];
    expect(source?.governing_event_reference).toBe("BR-LEASE-028");
    expect(source?.context).toEqual({
      basis: "SIGNED_LEASE_OTHER",
      signed_lease_provision: "Signed Lease: Rent provision",
      approved_grounds: "Rent unpaid after the day-30 default notice (DL-073)",
      management_authorization_reference:
        "Approved in the app by the signed-in Owner or Manager (leases.terminate)",
      evidence_reference: "TN-over",
      notice_required: true,
      notice_id: "notice-over",
      notice_period_ends_on: addDays(today, -1),
    });

    cleanup();
    window.location.hash = "#/leases/lease-U101";
    show(api(), deposits(), new Set(["leases.read", "deposits.read"]));
    await screen.findByRole("heading", { name: "Lease · U101" });
    expect(screen.queryByRole("button", { name: /^Terminate/ })).toBeNull();
    cleanup();
    window.location.hash = "#/leases/lease-U202";
    show(api());
    await screen.findByRole("heading", { name: "Lease · U202" });
    expect(screen.queryByRole("button", { name: /^Terminate/ })).toBeNull();
  });

  it("TEST-FE-873 Try again sends the very same termination and notice, a change gets new ones, and the Initial-unpaid ground waits 5 days", async () => {
    window.location.hash = "#/leases/terminate:lease-U101";
    const terminate = vi
      .fn<LeaseApi["terminate"]>()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockImplementation((value) => Promise.resolve(value));
    const over = notice("notice-over", addDays(today, -1));
    const recordNotice = vi
      .fn<LettersApi["recordNotice"]>()
      .mockRejectedValueOnce(new LettersUnavailableError())
      .mockRejectedValueOnce(new LettersUnavailableError())
      .mockResolvedValue(over);
    const fresh = { ...running, start_date: addDays(today, -3) };
    show(
      api({ get: vi.fn().mockResolvedValue(fresh), terminate }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {
        notices: vi.fn<LettersApi["notices"]>().mockResolvedValue([over]),
        recordNotice,
      },
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Terminate the Lease · U101",
    });
    // Start Date 3 days ago: the 5 days to pay are not over.
    expect(
      within(dialog).getByRole<HTMLInputElement>("radio", {
        name: /Initial Rent not paid/,
      }).disabled,
    ).toBe(true);
    expect(within(dialog).getByText(/^Possible from/)).toBeInTheDocument();

    // The notice: an unknown result, Try again, then a changed value.
    fireEvent.click(
      await within(dialog).findByRole("button", {
        name: /Record termination notice/,
      }),
    );
    const record = await screen.findByRole("dialog", {
      name: "Termination notice · U101",
    });
    fireEvent.change(within(record).getByLabelText(/Letter number/), {
      target: { value: "TN-8" },
    });
    fireEvent.change(within(record).getByLabelText(/How it was given/), {
      target: { value: "TG" },
    });
    fireEvent.change(within(record).getByLabelText(/^Details/), {
      target: { value: "chat photo kept" },
    });
    fireEvent.click(
      within(record).getByRole("button", { name: "Record termination notice" }),
    );
    fireEvent.click(
      await within(record).findByRole("button", { name: "Try again" }),
    );
    await waitFor(() => {
      expect(recordNotice).toHaveBeenCalledTimes(2);
    });
    const [n1, n2] = recordNotice.mock.calls;
    expect(n2).toEqual(n1);
    fireEvent.change(within(record).getByLabelText(/Letter number/), {
      target: { value: "TN-9" },
    });
    // The letter text follows the Lease end date until somebody writes it.
    fireEvent.change(within(record).getByLabelText("Lease ends on"), {
      target: { value: addDays(today, 40) },
    });
    expect(
      within(record).getByLabelText<HTMLTextAreaElement>(/What the letter says/)
        .value,
    ).toContain(dayText(addDays(today, 40)));
    await waitFor(() => {
      expect(
        within(record).getByRole("button", { name: "Try again" }),
      ).toBeEnabled();
    });
    fireEvent.click(within(record).getByRole("button", { name: "Try again" }));
    await screen.findByText("Termination notice recorded for U101.");
    const n3 = recordNotice.mock.calls[2];
    expect(n3?.[2].notice_id).not.toBe(n1?.[2].notice_id);
    expect(n3?.[3]).not.toBe(n1?.[3]);
    expect(n3?.[2].intended_termination_date).toBe(addDays(today, 40));

    // The termination: an unknown result, Try again, then a changed reason.
    const again = await screen.findByRole("dialog", {
      name: "Terminate the Lease · U101",
    });
    await within(again).findAllByRole("radio", { name: /^Given/ });
    fireEvent.change(within(again).getByLabelText(/^Evidence/), {
      target: { value: "TN-over" },
    });
    fireEvent.change(within(again).getByLabelText(/^Reason/), {
      target: { value: "Rent unpaid" },
    });
    fireEvent.click(within(again).getByRole("button", { name: "Terminate" }));
    fireEvent.click(
      await within(again).findByRole("button", { name: "Try again" }),
    );
    await waitFor(() => {
      expect(terminate).toHaveBeenCalledTimes(2);
    });
    const [t1, t2] = terminate.mock.calls;
    expect(t2?.[1]).toEqual(t1?.[1]);
    expect(t2?.[2]).toBe(t1?.[2]);
    await within(again).findByRole("button", { name: "Try again" });
    fireEvent.change(within(again).getByLabelText(/^Reason/), {
      target: { value: "Rent unpaid for two months" },
    });
    fireEvent.click(within(again).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(terminate).toHaveBeenCalledTimes(3);
    });
    const t3 = terminate.mock.calls[2];
    expect(t3?.[1].event_id).not.toBe(t1?.[1].event_id);
    expect(t3?.[2]).not.toBe(t1?.[2]);
    // Once done, a reload shows the Lease, not the dialog again.
    await waitFor(() => {
      expect(window.location.hash).toBe("#/leases/lease-U101");
    });
  });
});
