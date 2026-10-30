import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  type ServiceSettingsApi,
  ServiceSettingsError,
} from "../settings/serviceSettingsClient";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CustomerApi,
  CustomerDetail,
  VehicleResource,
} from "../customerClient";
import type { DepositApi, DepositResource } from "../depositClient";
import {
  LeaseConflictError,
  LeaseRefusedError,
  LeaseRequestError,
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
} from "../leaseClient";
import type { PaymentsApi } from "../payments/paymentsClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import {
  type SettlementApi,
  SettlementRequestError,
  SettlementUnavailableError,
  type SigningPreview,
} from "../settlementClient";
import { dayText, todayInPhnomPenh } from "../shell/format";
import type { UnitApi, UnitResource } from "../unitClient";
import type { UtilityApi, UtilityMeter } from "../utilityClient";
import {
  LettersUnavailableError,
  type LeaseWarning,
  type LettersApi,
  type TerminationNotice,
} from "../letters/lettersClient";
import { formModeOf } from "./LeaseForm";
import { PEOPLE_MOVE_IN } from "./parking";
import { LeasesPage, type LeasesPageProps } from "./LeasesPage";
import { addDays, endingLimit, initialRent } from "./leasesData";

afterEach(() => {
  cleanup();
  window.location.hash = "";
  vi.useRealTimers();
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
    planned_occupants: [],
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

function meterOf(
  kind: "ELECTRICITY" | "WATER",
  installed = "2020-01-01",
): UtilityMeter {
  return {
    id: `meter-${kind}`,
    property_id: "property-1",
    unit_id: "unit-U402",
    utility_type: kind,
    serial_number: `S-${kind}`,
    measurement_unit_code: kind === "ELECTRICITY" ? "KWH" : "M3",
    description: null,
    installed_date: installed,
    failure_date: null,
    deactivated_date: null,
    current: true,
    version: 1,
    memo: null,
    replacement: {
      replaced_meter_id: null,
      replacement_meter_id: null,
      replacement_date: null,
    },
    readings_url: "",
  };
}

/** V1-060 B6 (DL-100) and B7 (DL-108): the calls of Sign Lease, which saves in one request. */
function signing(
  preview: Partial<NonNullable<SigningPreview["initial"]>> | null = {},
  planned: number | null = 50_000,
  held: SigningPreview["held_security_deposit"] = null,
) {
  const calls = {
    signingPreview: vi.fn<SettlementApi["signingPreview"]>().mockResolvedValue({
      initial:
        preview === null
          ? null
          : {
              period_start: "2026-12-10",
              period_end: "2026-12-31",
              // A Due Date far ahead, so it never passes while the tests run (the dialog
              // compares it with today).
              due_date: "2999-12-31",
              rent_usd_cents: 35_484,
              service_lines: [],
              total_usd_cents: 35_484,
              problem: null,
              invoice_id: null,
              ...preview,
            },
      planned_security_deposit_usd_cents: planned,
      held_security_deposit: held,
    }),
    planSecurityDeposit: vi
      .fn<SettlementApi["planSecurityDeposit"]>()
      .mockResolvedValue({}),
    signWithPayment: vi
      .fn<SettlementApi["signWithPayment"]>()
      .mockImplementation((_property, _lease, _version, body) =>
        Promise.resolve({
          lease_version: 7,
          receipt_number: "RC0042",
          invoice_number: "INV260001",
          total_usd_cents: body.payment.amount.minor_units,
        }),
      ),
    receiveSecurityDeposit: vi
      .fn<SettlementApi["receiveSecurityDeposit"]>()
      .mockResolvedValue({ receiptNumber: "RC0042" }),
  };
  // Sign Lease never saves the money on its own (DL-108).
  const confirm = vi
    .fn<PaymentsApi["confirm"]>()
    .mockResolvedValue({ paymentId: "payment-1", receiptNumber: "RC0042" });
  const payments = {
    methods: vi.fn(() =>
      Promise.resolve([
        { id: "method-cash", code: "CASH", displayName: "Cash" },
        { id: "method-bank", code: "BANK", displayName: "Bank transfer" },
      ]),
    ),
    confirm,
  } as unknown as PaymentsApi;
  return { ...calls, confirm, payments };
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
  servicesClient: Partial<Pick<ServiceSettingsApi, "read" | "addService">> = {},
  metersClient: Pick<UtilityApi, "loadMeters"> = {
    loadMeters: vi.fn<UtilityApi["loadMeters"]>().mockResolvedValue({
      items: [meterOf("ELECTRICITY"), meterOf("WATER")],
      nextCursor: null,
    }),
  },
  signingClients: ReturnType<typeof signing> = signing(),
  extra: Partial<LeasesPageProps> = {},
) {
  const services = {
    read: vi.fn<ServiceSettingsApi["read"]>().mockResolvedValue({
      services: [],
      service_types: [],
      today: "2026-10-25",
      can_manage: false,
    }),
    addService: vi.fn<ServiceSettingsApi["addService"]>().mockResolvedValue({}),
    ...servicesClient,
  };
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
      unitApi={
        {
          // V1-061: Edit draft reads the Unit's default Rent; none unless a test gives one.
          get: vi.fn<UnitApi["get"]>().mockRejectedValue(new Error("no")),
          ...unitClient,
        } as UnitApi
      }
      lettersApi={letters}
      servicesApi={services}
      metersApi={metersClient}
      settlementApi={signingClients}
      paymentsApi={signingClients.payments}
      {...extra}
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
      "Parking",
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
    // Parking Step 4: the Occupants card is the Vehicle card (people lists hidden, code kept).
    expect(screen.getByRole("region", { name: "Vehicle" })).toHaveTextContent(
      "No vehicle moved in yet.",
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
    // A walk-in draft: no Booking's deposit (DL-100 takes its Security Deposit at signing).
    security_deposit_id: null,
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

  it("TEST-FE-850 Sign Lease needs a tick for every Signer, says what signing does and sends the money, the Signers and the Lease version as one request (DL-100, DL-108)", async () => {
    window.location.hash = "#/leases/lease-sign";
    const recordSignature = vi.fn();
    const get = vi.fn().mockResolvedValue(signable);
    const money = signing();
    show(
      api({ get, recordSignature }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      money,
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog", { name: "Sign Lease · U301" });
    await checked(dialog);
    expect(dialog).toHaveTextContent("Initial Rent, 10/12/2026 to 31/12/2026");
    // The walk-in draft's own Security Deposit (DL-101); Edit draft changes it, not this dialog.
    expect(dialog).toHaveTextContent("Security Deposit$500.00");
    expect(within(dialog).queryByRole("textbox")).toBeNull();
    expect(dialog).toHaveTextContent("Total to receive$854.84");
    expect(dialog).toHaveTextContent("U301 becomes Occupied now");
    expect(dialog).toHaveTextContent(
      "saved together in one step, or nothing is saved",
    );
    // No active Reservation was found, so no line about it.
    expect(dialog).not.toHaveTextContent("Reservation of this Customer");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Tenant A/ }));
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-cash" } },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive $854.84 and sign" }),
    );
    expect(
      within(dialog).getByText(
        "Tick every Signer. The Lease is signed only when all have signed.",
      ),
    ).toBeInTheDocument();
    expect(money.signWithPayment).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: /Guarantor B/ }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive $854.84 and sign" }),
    );
    expect(
      await screen.findByText(
        "Lease signed. U301 is Occupied. $854.84 received with Receipt RC0042.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(money.signWithPayment).toHaveBeenCalledTimes(1);
    const [propertyId, leaseId, version, body, key] =
      money.signWithPayment.mock.calls[0] ?? [];
    expect([propertyId, leaseId, version]).toEqual([
      "property-1",
      "lease-sign",
      4,
    ]);
    expect(body).toEqual({
      signer_ids: ["signer-a", "signer-b"],
      reason: "Every Signer signed the paper Lease",
      payment: {
        payment_method_id: "method-cash",
        received_at: expect.any(String) as string,
        evidence_reference: "Cash received, Cash",
        payer_intent_memo: "Money received at signing the Lease of U301",
        amount: { currency: "USD", minor_units: 85_484 },
      },
    });
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    // Nothing is saved step by step any more.
    expect(money.confirm).not.toHaveBeenCalled();
    expect(recordSignature).not.toHaveBeenCalled();
    expect(money.receiveSecurityDeposit).not.toHaveBeenCalled();
    // The page reads the signed Lease again.
    await waitFor(() => {
      expect(get).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-851 after a lost answer Try again sends the very same request with the same key and nothing can be changed; a conflict reads the Lease again", async () => {
    // The clock moves between the presses: the time the money came stays the first one.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T03:00:00.000Z"));
    window.location.hash = "#/leases/lease-sign";
    const get = vi.fn().mockResolvedValue(signable);
    const money = signing();
    money.signWithPayment
      .mockRejectedValueOnce(new SettlementUnavailableError())
      .mockRejectedValueOnce(new SettlementRequestError(504, null, "Timeout"))
      .mockRejectedValueOnce(new SettlementRequestError(412, null, "Changed"));
    show(
      api({ get }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      money,
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog");
    await checked(dialog);
    for (const box of within(dialog).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-cash" } },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: /^Receive .* and sign$/ }),
    );
    expect(
      await within(dialog).findByText(
        /No answer came back, so it is not known whether the signing was saved/,
      ),
    ).toBeInTheDocument();
    // Only the same request may go again.
    expect(within(dialog).getByLabelText("How the money came")).toBeDisabled();
    for (const box of within(dialog).getAllByRole("checkbox"))
      expect(box).toBeDisabled();
    vi.setSystemTime(new Date("2026-10-28T03:00:07.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(money.signWithPayment).toHaveBeenCalledTimes(2);
    });
    expect(
      await within(dialog).findByText(/No answer came back/),
    ).toBeInTheDocument();
    vi.setSystemTime(new Date("2026-10-28T03:00:15.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText(/This Lease or its Parking changed meanwhile/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const calls = money.signWithPayment.mock.calls;
    expect(calls).toHaveLength(3);
    // The same key and the very same body, the time the money came included.
    expect(calls[1]).toEqual(calls[0]);
    expect(calls[2]).toEqual(calls[0]);
    expect(calls[0]?.[3].payment.received_at).toBe("2026-10-28T03:00:00.000Z");
    expect(get).toHaveBeenCalledTimes(2);
    expect(money.confirm).not.toHaveBeenCalled();
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

  it("TEST-FE-853 a draft whose Customer has an active Booking of the Parking takes only the rest of its deposit; a refusal saves nothing and shows why, and changed values are a new request", async () => {
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
        deposit_id: `deposit-${id}`,
        deposit_required_usd_cents: 50_000,
        deposit_received_usd_cents: 10_000,
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
    const money = signing({}, null);
    money.signWithPayment.mockRejectedValueOnce(
      new SettlementRequestError(
        409,
        "SIGNING_TOTAL_CHANGED",
        "The money due at signing changed meanwhile. Nothing was saved. Close and open Sign Lease again to see the new total.",
      ),
    );
    show(
      api({
        get: vi.fn().mockResolvedValue({
          ...signable,
          security_deposit_id: "deposit-reservation-301",
        }),
      }),
      deposits(),
      null,
      { list },
      undefined,
      {},
      {},
      {},
      undefined,
      money,
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog");
    await checked(dialog);
    expect(list.mock.calls).toEqual([
      ["property-1", "ACTIVE", undefined],
      ["property-1", "ACTIVE", "page-2"],
    ]);
    expect(dialog).toHaveTextContent(
      "An active Reservation of this Customer for this Parking is completed in the same step",
    );
    expect(dialog).toHaveTextContent(
      "Rest of the Security Deposit ($100.00 of $500.00 received with the Booking)$400.00",
    );
    for (const box of within(dialog).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-cash" } },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive $754.84 and sign" }),
    );
    expect(
      await within(dialog).findByText(
        "The money due at signing changed meanwhile. Nothing was saved. Close and open Sign Lease again to see the new total.",
      ),
    ).toBeInTheDocument();
    // Nothing was saved, so the values may change; changed values are a new request.
    fireEvent.change(within(dialog).getByLabelText("How the money came"), {
      target: { value: "method-bank" },
    });
    fireEvent.change(within(dialog).getByLabelText("Bank or ABA reference"), {
      target: { value: "ABA 7781" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText(
        "Lease signed. U301 is Occupied. $754.84 received with Receipt RC0042.",
      ),
    ).toBeInTheDocument();
    const calls = money.signWithPayment.mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0]?.[3].payment).toMatchObject({
      payment_method_id: "method-cash",
      amount: { currency: "USD", minor_units: 75_484 },
    });
    expect(calls[1]?.[3].payment).toMatchObject({
      payment_method_id: "method-bank",
      evidence_reference: "ABA 7781",
      amount: { currency: "USD", minor_units: 75_484 },
    });
    expect(calls[1]?.[4]).not.toBe(calls[0]?.[4]);
    expect(list).toHaveBeenCalledTimes(2);
    expect(money.receiveSecurityDeposit).not.toHaveBeenCalled();
  });

  it("TEST-FE-1111 Edit draft shows the Parking's default Rent and stops a lower Rent without a Manager; raising it is fine (V1-061, DL-110)", async () => {
    window.location.hash = "#/leases/lease-sign";
    const draft = {
      ...signable,
      end_date: "2027-12-31",
      monthly_rent_usd_cents: 50_000,
    };
    const update = vi
      .fn()
      .mockResolvedValue({ ...draft, monthly_rent_usd_cents: 55_000 });
    const get = vi.fn<UnitApi["get"]>().mockResolvedValue({
      unit_id: "unit-U301",
      default_monthly_rent_usd_cents: 50_000,
    } as UnitResource);
    show(
      api({ get: vi.fn().mockResolvedValue(draft), update }),
      deposits(),
      new Set(["leases.read", "leases.draft"]),
      undefined,
      undefined,
      { get },
    );

    fireEvent.click(await screen.findByRole("button", { name: "Edit draft" }));
    const dialog = screen.getByRole("dialog", { name: "Edit draft · U301" });
    expect(
      await within(dialog).findByText(
        "This Parking's default Rent is $500.00. A higher Rent is fine.",
      ),
    ).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("unit-U301");
    fireEvent.change(within(dialog).getByLabelText("Monthly Rent"), {
      target: { value: "450" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Why it changed/), {
      target: { value: "Asked for less" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent(
      "The Rent is below this Parking's default Rent of $500.00. Only a Manager or the Owner can agree a lower Rent.",
    );
    expect(update).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Monthly Rent"), {
      target: { value: "550" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(update).toHaveBeenCalledTimes(1);
    });
    expect(update.mock.calls[0]?.[1]).toMatchObject({
      monthly_rent_usd_cents: 55_000,
    });
  });

  it("TEST-FE-1017 a walk-in draft shows its planned Security Deposit, and Edit draft saves a new amount after the draft (DL-100)", async () => {
    window.location.hash = "#/leases/lease-sign";
    const update = vi.fn().mockResolvedValue(signable);
    const money = signing();
    show(
      api({ get: vi.fn().mockResolvedValue(signable), update }),
      deposits({
        leaseDeposits: vi.fn(() =>
          Promise.resolve({ items: [], can_manage: false }),
        ),
      } as unknown as Partial<DepositApi>),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      money,
    );
    expect(
      await screen.findByText("Security Deposit on this Lease: $500.00."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit draft" }));
    const dialog = screen.getByRole("dialog", { name: "Edit draft · U301" });
    const box = within(dialog).getByLabelText("Security Deposit (USD)");
    expect(box).toHaveValue("500.00");
    fireEvent.change(within(dialog).getByLabelText("End Date"), {
      target: { value: "2027-12-31" },
    });
    fireEvent.change(box, { target: { value: "0" } });
    fireEvent.change(within(dialog).getByLabelText(/Why it changed/), {
      target: { value: "Deposit agreed again" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent("Type the Security Deposit, more than 0.");
    expect(update).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "450" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The draft was saved.")).toBeInTheDocument();
    expect(money.planSecurityDeposit.mock.calls[0]?.[0]).toBe("lease-sign");
    expect(money.planSecurityDeposit.mock.calls[0]?.[1]).toMatchObject({
      required_usd_cents: 45_000,
      reason: "Deposit agreed again",
    });
    expect(update.mock.invocationCallOrder[0] ?? 0).toBeLessThan(
      money.planSecurityDeposit.mock.invocationCallOrder[0] ?? 0,
    );
  });

  it("TEST-FE-1082 Edit draft: when the dates and Rent save but the Security Deposit does not, it says so and Try again saves only the Security Deposit; a deposit that could not be read hides the box (B7)", async () => {
    window.location.hash = "#/leases/lease-sign";
    const noDeposits = () =>
      deposits({
        leaseDeposits: vi.fn(() =>
          Promise.resolve({ items: [], can_manage: false }),
        ),
      } as unknown as Partial<DepositApi>);
    const update = vi.fn().mockResolvedValue({ ...signable, version: 5 });
    const money = signing();
    money.planSecurityDeposit
      .mockReset()
      .mockRejectedValueOnce(
        new SettlementRequestError(
          409,
          null,
          "The Security Deposit save was refused.",
        ),
      )
      .mockResolvedValue({});
    show(
      api({ get: vi.fn().mockResolvedValue(signable), update }),
      noDeposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      money,
    );
    expect(
      await screen.findByText("Security Deposit on this Lease: $500.00."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit draft" }));
    const dialog = screen.getByRole("dialog", { name: "Edit draft · U301" });
    fireEvent.change(within(dialog).getByLabelText("End Date"), {
      target: { value: "2027-12-31" },
    });
    fireEvent.change(within(dialog).getByLabelText("Security Deposit (USD)"), {
      target: { value: "450" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Why it changed/), {
      target: { value: "Deposit agreed again" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "The dates and Rent are saved, but the Security Deposit is not. The Security Deposit save was refused. Try again saves only the Security Deposit.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("The draft was saved.")).toBeInTheDocument();
    expect(update).toHaveBeenCalledTimes(1);
    expect(money.planSecurityDeposit).toHaveBeenCalledTimes(2);
    expect(money.planSecurityDeposit.mock.calls[0]?.[1]).toMatchObject({
      required_usd_cents: 45_000,
      reason: "Deposit agreed again",
    });
    expect(money.planSecurityDeposit.mock.calls[1]?.[1]).toEqual(
      money.planSecurityDeposit.mock.calls[0]?.[1],
    );

    cleanup();
    window.location.hash = "#/leases/lease-sign";
    const unread = signing();
    unread.signingPreview
      .mockReset()
      .mockRejectedValue(new SettlementUnavailableError());
    const again = vi.fn().mockResolvedValue({ ...signable, version: 5 });
    show(
      api({ get: vi.fn().mockResolvedValue(signable), update: again }),
      noDeposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      unread,
    );
    const edit = await screen.findByRole("button", { name: "Edit draft" });
    await waitFor(() => {
      expect(unread.signingPreview).toHaveBeenCalled();
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    // Not known is never "none" on the page either.
    expect(
      await screen.findByText(
        "The Security Deposit could not be read just now. Reload the page to see it.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No Security Deposit is recorded for this Lease yet."),
    ).toBeNull();
    fireEvent.click(edit);
    const second = screen.getByRole("dialog", { name: "Edit draft · U301" });
    expect(
      within(second).queryByLabelText("Security Deposit (USD)"),
    ).toBeNull();
    fireEvent.change(within(second).getByLabelText("End Date"), {
      target: { value: "2027-12-31" },
    });
    fireEvent.change(within(second).getByLabelText(/Why it changed/), {
      target: { value: "New dates" },
    });
    fireEvent.click(within(second).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The draft was saved.")).toBeInTheDocument();
    expect(again).toHaveBeenCalledTimes(1);
    expect(unread.planSecurityDeposit).not.toHaveBeenCalled();
  });

  it("TEST-FE-1094 while the draft's Security Deposit is being read the page says so, never none; closing Sign Lease reads the Lease again, as it may be signed after a lost answer (B7)", async () => {
    window.location.hash = "#/leases/lease-sign";
    const reading = signing();
    reading.signingPreview
      .mockReset()
      .mockReturnValue(new Promise<never>(() => undefined));
    show(
      api({ get: vi.fn().mockResolvedValue(signable) }),
      deposits({
        leaseDeposits: vi.fn(() =>
          Promise.resolve({ items: [], can_manage: false }),
        ),
      } as unknown as Partial<DepositApi>),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      reading,
    );
    expect(
      await screen.findByText("Reading the Security Deposit…"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No Security Deposit is recorded for this Lease yet."),
    ).toBeNull();

    cleanup();
    window.location.hash = "#/leases/lease-sign";
    const get = vi.fn().mockResolvedValue(signable);
    show(
      api({ get }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      signing(),
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog");
    await checked(dialog);
    expect(get).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(get).toHaveBeenCalledTimes(2);
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("TEST-FE-1104 closing Receive Security Deposit reads the Lease again, as the money may be saved after a lost answer (B7)", async () => {
    window.location.hash = "#/leases/lease-U101";
    const get = vi.fn().mockResolvedValue(running);
    show(
      api({ get }),
      deposits({
        leaseDeposits: vi.fn(() =>
          Promise.resolve({
            items: [
              deposit("lease-U101", {
                received_usd_cents: 10000,
                outstanding_required_usd_cents: 40000,
              }),
            ],
            can_manage: false,
          }),
        ),
      } as unknown as Partial<DepositApi>),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Receive Security Deposit" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(get).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(get).toHaveBeenCalledTimes(2);
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("TEST-FE-1018 Sign Lease takes no money and signs nothing when the Initial Rent Invoice cannot be made or the person may not receive payments", async () => {
    window.location.hash = "#/leases/lease-sign";
    const recordSignature = vi.fn();
    const money = signing({ problem: "PARTIAL_SERVICE:Parking" });
    show(
      api({ get: vi.fn().mockResolvedValue(signable), recordSignature }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      money,
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog");
    expect(
      await within(dialog).findByText(
        "The Initial Rent Invoice cannot be made: Parking covers only part of a month or has no rate. Fix the Service first.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("How the money came")).toBeNull();
    for (const box of within(dialog).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.click(
      within(dialog).getByRole("button", { name: /^Receive .* and sign$/ }),
    );
    expect(money.signWithPayment).not.toHaveBeenCalled();
    expect(recordSignature).not.toHaveBeenCalled();
    cleanup();

    window.location.hash = "#/leases/lease-sign";
    show(
      api({ get: vi.fn().mockResolvedValue(signable), recordSignature }),
      deposits(),
      new Set(["leases.read", "leases.sign", "deposits.read"]),
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      signing(),
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    expect(
      await screen.findByText(
        "To sign, you need the rights to receive and allocate payments. Ask the Owner.",
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1019 Print draft shows the draft for the customer to check, with the money paid at signing, and prints only the sheet", async () => {
    window.location.hash = "#/leases/lease-sign";
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    show(
      api({ get: vi.fn().mockResolvedValue(signable) }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      signing({
        service_lines: [
          {
            name: "Parking",
            period_start: "2026-12-10",
            period_end: "2026-12-31",
            amount_usd_cents: 1_419,
          },
        ],
        total_usd_cents: 36_903,
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Print draft" }));
    const dialog = screen.getByRole("dialog", { name: "Print draft · U301" });
    const sheet = within(dialog).getByRole("article", {
      name: "Draft Lease sheet",
    });
    expect(
      await within(sheet).findByText("Total to receive"),
    ).toBeInTheDocument();
    expect(sheet).toHaveTextContent("ParkingU301");
    expect(sheet).toHaveTextContent("Other SignersGuarantor B");
    expect(sheet).toHaveTextContent("Monthly Rent$500.00");
    expect(sheet).toHaveTextContent("Parking, 10/12/2026 to 31/12/2026$14.19");
    expect(sheet).toHaveTextContent("Total to receive$869.03");
    expect(sheet).toHaveTextContent(
      "the Lease is signed only after the money below is received",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Print" }));
    expect(print).toHaveBeenCalledTimes(1);
    expect(document.body).toHaveClass("ui-printing");
    window.dispatchEvent(new Event("afterprint"));
    expect(document.body).not.toHaveClass("ui-printing");
    print.mockRestore();
  });

  // DL-101: the Reservation's Security Deposit of a draft from a Booking, as the preview shows it.
  const heldDeposit = {
    deposit_id: "deposit-reservation-301",
    required_usd_cents: 50_000,
    received_usd_cents: 10_000,
  };
  const activeBooking = {
    list: vi.fn<ReservationApi["list"]>().mockResolvedValue({
      items: [
        {
          reservation_id: "reservation-301",
          property_id: "property-1",
          unit_id: "unit-U301",
          customer_id: "customer-U301",
          status: "ACTIVE",
          deposit_id: "deposit-reservation-301",
          deposit_required_usd_cents: 50_000,
          deposit_received_usd_cents: 10_000,
        } as ReservationResource,
      ],
      next_cursor: null,
      can_create: false,
    }),
  };
  const bookingDraft = {
    ...signable,
    security_deposit_id: "deposit-reservation-301",
  };

  it("TEST-FE-1020 Sign Lease on a draft from a Booking asks for the rest of the draft's Security Deposit with the Initial Rent in one request; an amount below the money received signs nothing (DL-101, DL-108)", async () => {
    window.location.hash = "#/leases/lease-sign";
    const money = signing({}, 60_000, heldDeposit);
    show(
      api({ get: vi.fn().mockResolvedValue(bookingDraft) }),
      deposits(),
      null,
      activeBooking,
      undefined,
      {},
      {},
      {},
      undefined,
      money,
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog", { name: "Sign Lease · U301" });
    await checked(dialog);
    // The draft says $600.00; $100.00 came with the Booking, so $500.00 is left.
    expect(dialog).toHaveTextContent(
      "Rest of the Security Deposit ($100.00 of $600.00 received with the Booking)$500.00",
    );
    expect(dialog).toHaveTextContent("Total to receive$854.84");
    for (const box of within(dialog).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-cash" } },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Receive $854.84 and sign" }),
    );
    expect(
      await screen.findByText(
        "Lease signed. U301 is Occupied. $854.84 received with Receipt RC0042.",
      ),
    ).toBeInTheDocument();
    expect(money.signWithPayment).toHaveBeenCalledTimes(1);
    expect(money.signWithPayment.mock.calls[0]?.[3].payment.amount).toEqual({
      currency: "USD",
      minor_units: 85_484,
    });
    // The server applies the draft's amount and fills the Reservation's deposit itself.
    expect(money.receiveSecurityDeposit).not.toHaveBeenCalled();
    cleanup();

    window.location.hash = "#/leases/lease-sign";
    const low = signing({}, 5_000, heldDeposit);
    show(
      api({ get: vi.fn().mockResolvedValue(bookingDraft) }),
      deposits(),
      null,
      activeBooking,
      undefined,
      {},
      {},
      {},
      undefined,
      low,
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const refused = screen.getByRole("dialog");
    expect(
      await within(refused).findByText(
        "The Security Deposit on this draft is less than the $100.00 already received with the Reservation. Change it with Edit draft first.",
      ),
    ).toBeInTheDocument();
    expect(within(refused).queryByLabelText("How the money came")).toBeNull();
    for (const box of within(refused).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.click(
      within(refused).getByRole("button", { name: /^Receive .* and sign$/ }),
    );
    expect(low.signWithPayment).not.toHaveBeenCalled();
  });

  it("TEST-FE-1077 Sign Lease takes no money when a walk-in draft has no Security Deposit yet or the Initial Rent Due Date has passed (DL-101, DL-108)", async () => {
    window.location.hash = "#/leases/lease-sign";
    const missing = signing({}, null);
    show(
      api({ get: vi.fn().mockResolvedValue(signable) }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      missing,
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const dialog = screen.getByRole("dialog");
    expect(
      await within(dialog).findByText(
        "This draft has no Security Deposit yet. Add it with Edit draft first.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("How the money came")).toBeNull();
    for (const box of within(dialog).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.click(
      within(dialog).getByRole("button", { name: /^Receive .* and sign$/ }),
    );
    expect(missing.signWithPayment).not.toHaveBeenCalled();
    cleanup();

    window.location.hash = "#/leases/lease-sign";
    const late = signing({ due_date: "2026-01-15" });
    show(
      api({ get: vi.fn().mockResolvedValue(signable) }),
      deposits(),
      null,
      undefined,
      undefined,
      {},
      {},
      {},
      undefined,
      late,
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Sign Lease/ }));
    const passed = screen.getByRole("dialog");
    expect(
      await within(passed).findByText(
        "The Initial Rent Due Date (15/01/2026) has passed, so the Initial Rent Invoice cannot be made today. Ask the Owner or a Manager to set a new Due Date first.",
      ),
    ).toBeInTheDocument();
    expect(within(passed).queryByLabelText("How the money came")).toBeNull();
    for (const box of within(passed).getAllByRole("checkbox"))
      fireEvent.click(box);
    fireEvent.click(
      within(passed).getByRole("button", { name: /^Receive .* and sign$/ }),
    );
    expect(late.signWithPayment).not.toHaveBeenCalled();
  });

  it("TEST-FE-1021 a draft from a Booking shows its Security Deposit as a Lease term with the money received, prints it, and Edit draft never goes below the money received (DL-101)", async () => {
    window.location.hash = "#/leases/lease-sign";
    const update = vi.fn().mockResolvedValue(bookingDraft);
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const money = signing({}, 60_000, heldDeposit);
    show(
      api({ get: vi.fn().mockResolvedValue(bookingDraft), update }),
      // Before signing the Reservation's deposit is not yet the Lease's.
      deposits({
        leaseDeposits: vi.fn(() =>
          Promise.resolve({ items: [], can_manage: false }),
        ),
      } as unknown as Partial<DepositApi>),
      null,
      activeBooking,
      undefined,
      {},
      {},
      {},
      undefined,
      money,
    );
    expect(
      await screen.findByText("Security Deposit on this Lease: $600.00."),
    ).toBeInTheDocument();
    const card = screen.getByRole("region", { name: "Deposits" });
    expect(card).toHaveTextContent(
      "$100.00 received with the Reservation; $500.00 is paid when the Lease is signed.",
    );
    expect(card).not.toHaveTextContent("No Security Deposit is recorded");

    fireEvent.click(screen.getByRole("button", { name: "Print draft" }));
    const sheet = within(
      screen.getByRole("dialog", { name: "Print draft · U301" }),
    ).getByRole("article", { name: "Draft Lease sheet" });
    expect(
      await within(sheet).findByText("Total to receive"),
    ).toBeInTheDocument();
    expect(sheet).toHaveTextContent("Security Deposit$600.00");
    expect(sheet).toHaveTextContent(
      "Rest of the Security Deposit ($100.00 of $600.00 received with the Booking)$500.00",
    );
    expect(sheet).toHaveTextContent("Total to receive$854.84");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    print.mockRestore();

    fireEvent.click(screen.getByRole("button", { name: "Edit draft" }));
    const dialog = screen.getByRole("dialog", { name: "Edit draft · U301" });
    const box = within(dialog).getByLabelText("Security Deposit (USD)");
    expect(box).toHaveValue("600.00");
    fireEvent.change(within(dialog).getByLabelText("End Date"), {
      target: { value: "2027-12-31" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Why it changed/), {
      target: { value: "Deposit agreed again" },
    });
    fireEvent.change(box, { target: { value: "99.99" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent(
      "The Security Deposit cannot be less than the $100.00 already received.",
    );
    expect(update).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "650" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The draft was saved.")).toBeInTheDocument();
    expect(money.planSecurityDeposit.mock.calls[0]?.[0]).toBe("lease-sign");
    expect(money.planSecurityDeposit.mock.calls[0]?.[1]).toMatchObject({
      required_usd_cents: 65_000,
      reason: "Deposit agreed again",
    });
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
      target: { value: " Customer chose another Parking " },
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
      reason: "Customer chose another Parking",
    });
    expect(cancel.mock.calls[1]?.[1]).toEqual(cancel.mock.calls[0]?.[1]);
    expect(cancel.mock.calls[1]?.[2]).toBe(cancel.mock.calls[0]?.[2]);
  });

  it("TEST-FE-855 Record move-in offers the Signers and planned occupants, checks the date and keeps the Occupancy ids on Try again", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
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
    expect(within(dialog).getByLabelText("Move-in date")).toHaveValue(
      dayText(today),
    );
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
  it("TEST-FE-861 Record move-in can add an active Customer who is not named in the Lease", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
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

  it("TEST-FE-857 New Lease offers open Parking, fills a one-year End Date, previews the bill, asks before saving and keeps the Lease id on Try again", async () => {
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockImplementationOnce((_property, source) =>
        Promise.resolve(
          lease("U402", { lease_id: source.lease_id, status: "DRAFTED" }),
        ),
      );
    const money = signing();
    show(
      api({ create }),
      deposits(),
      null,
      undefined,
      people(),
      units,
      {},
      {},
      undefined,
      money,
    );

    fireEvent.click(await screen.findByRole("link", { name: "New Lease" }));
    const unitBox = await screen.findByLabelText("Parking");
    expect(
      within(unitBox)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Choose a Parking", "U401", "U402"]);
    pickIn("Parking", "unit-U402");
    pickIn("Primary Tenant", "customer-a");
    pickIn("Other Signers", "customer-b");
    // Parking Step 4: no "Other occupants" list on Parking (PEOPLE_MOVE_IN).
    fireEvent.change(screen.getByLabelText("Start Date"), {
      target: { value: "2026-12-22" },
    });
    expect(screen.getByLabelText("End Date")).toHaveValue(
      dayText("2027-12-31"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(screen.getByText("Enter the monthly Rent.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "310" },
    });
    const preview = screen.getByRole("region", { name: "What will be billed" });
    // 22 to 31 December is 10 of 31 days; day 21 or later adds January.
    expect(preview).toHaveTextContent(
      "Initial Rent $410.00, paid with the Security Deposit when the Lease is signed (its Invoice shows the Due Date 27/12/2026).",
    );
    expect(preview).toHaveTextContent("$310.00 × 10 ÷ 31 days = $100.00.");
    expect(preview).toHaveTextContent(
      "Security Deposit: $310.00, paid when the Lease is signed.",
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
      planned_occupant_customer_ids: ["customer-a"],
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
    // DL-100: the walk-in draft keeps its Security Deposit, one month's Rent unless typed.
    expect(money.planSecurityDeposit.mock.calls[0]?.[0]).toBe(sent?.lease_id);
    expect(money.planSecurityDeposit.mock.calls[0]?.[1]).toMatchObject({
      required_usd_cents: 31_000,
      reason: "Security Deposit on the New Lease form",
    });
  });

  it("TEST-FE-1083 New Lease: when the draft saves but no answer comes back for its Security Deposit, the dialog stays and Try again sends only the same Security Deposit, then opens the draft (B7)", async () => {
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockImplementation((_property, source) =>
        Promise.resolve(
          lease("U402", { lease_id: source.lease_id, status: "DRAFTED" }),
        ),
      );
    const money = signing();
    money.planSecurityDeposit
      .mockReset()
      .mockRejectedValueOnce(new SettlementUnavailableError())
      .mockResolvedValue({});
    window.location.hash = "#/leases/new";
    show(
      api({ create }),
      deposits(),
      null,
      undefined,
      people(),
      units,
      {},
      {},
      undefined,
      money,
    );
    await screen.findByLabelText("Parking");
    pickIn("Parking", "unit-U402");
    await waitFor(() => {
      expect(screen.getByLabelText("Parking")).toHaveValue("unit-U402");
    });
    pickIn("Primary Tenant", "customer-a");
    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "300" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    expect(
      await within(dialog).findByText(
        /^The draft is saved\. No answer came back for its Security Deposit/,
      ),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe("#/leases/new");
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(window.location.hash).toBe(
        `#/leases/${create.mock.calls[0]?.[1].lease_id ?? ""}`,
      );
    });
    expect(create).toHaveBeenCalledTimes(1);
    expect(money.planSecurityDeposit).toHaveBeenCalledTimes(2);
    expect(money.planSecurityDeposit.mock.calls[0]?.[1]).toMatchObject({
      required_usd_cents: 30_000,
    });
    expect(money.planSecurityDeposit.mock.calls[1]?.[1]).toEqual(
      money.planSecurityDeposit.mock.calls[0]?.[1],
    );
  });

  it("TEST-FE-1084 New Lease: a draft found after a lost answer also gets its Security Deposit; a refusal says why, and Close opens the draft (B7)", async () => {
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
    const money = signing();
    money.planSecurityDeposit
      .mockReset()
      .mockRejectedValue(
        new SettlementRequestError(
          422,
          null,
          "The Security Deposit must be more than 0.",
        ),
      );
    window.location.hash = "#/leases/new";
    show(
      api({ create, get }),
      deposits(),
      null,
      undefined,
      people(),
      units,
      {},
      {},
      undefined,
      money,
    );
    await screen.findByLabelText("Parking");
    pickIn("Parking", "unit-U402");
    await waitFor(() => {
      expect(screen.getByLabelText("Parking")).toHaveValue("unit-U402");
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
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    expect(
      await within(dialog).findByText(
        "The draft is saved, but its Security Deposit is not. The Security Deposit must be more than 0. Try again saves only the Security Deposit. Close opens the draft, where Edit draft can add it.",
      ),
    ).toBeInTheDocument();
    expect(money.planSecurityDeposit.mock.calls[0]?.[0]).toBe(savedId);
    expect(window.location.hash).toBe("#/leases/new");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(window.location.hash).toBe(`#/leases/${savedId}`);
    });
  });

  it("TEST-FE-1010 New Lease says when the chosen Parking has no electricity or water meter on the Start Date (nothing of that kind is billed); a meter put in later counts from its day; a failed meter read shows nothing", async () => {
    const loadMeters = vi.fn<UtilityApi["loadMeters"]>().mockResolvedValue({
      items: [meterOf("WATER", "2027-01-01")],
      nextCursor: null,
    });
    show(
      api(),
      deposits(),
      null,
      undefined,
      people(),
      units,
      {},
      {},
      { loadMeters },
    );
    fireEvent.click(await screen.findByRole("link", { name: "New Lease" }));
    await screen.findByLabelText("Parking");
    pickIn("Parking", "unit-U402");
    fireEvent.change(screen.getByLabelText("Start Date"), {
      target: { value: "2026-12-22" },
    });
    expect(
      await screen.findByText(
        "This Parking has no electricity or water meter, so no Utilities are billed. Add the meters in Utilities when they are put in.",
      ),
    ).toBeInTheDocument();
    expect(loadMeters).toHaveBeenLastCalledWith("unit-U402", undefined);
    // From 1 January the water meter is in: only electricity is missing.
    fireEvent.change(screen.getByLabelText("Start Date"), {
      target: { value: "2027-01-01" },
    });
    expect(
      await screen.findByText(
        "This Parking has no electricity meter, so no electricity is billed. Add the meter in Utilities when it is put in.",
      ),
    ).toBeInTheDocument();
    loadMeters.mockRejectedValue(new Error("not allowed"));
    fireEvent.change(screen.getByLabelText("Start Date"), {
      target: { value: "2027-01-02" },
    });
    await waitFor(() => {
      expect(screen.queryByText(/meter, so no/)).toBeNull();
    });
  });

  it("TEST-FE-1011 New Lease offers New Service only to a person with Settings access: it adds the Service with its own id, keeps that id after a lost answer and reads the Services again; an id saved before with other values closes the form and says so", async () => {
    const empty = {
      services: [],
      service_types: [],
      today: "2026-10-25",
      can_manage: true,
    };
    const read = vi.fn<ServiceSettingsApi["read"]>().mockResolvedValue(empty);
    const addService = vi
      .fn<ServiceSettingsApi["addService"]>()
      .mockRejectedValueOnce(new ServiceSettingsError("unknown"))
      .mockResolvedValueOnce({});
    show(
      api(),
      deposits(),
      null,
      undefined,
      people(),
      units,
      {},
      { read, addService },
    );
    fireEvent.click(await screen.findByRole("link", { name: "New Lease" }));
    fireEvent.click(await screen.findByRole("button", { name: "New Service" }));
    const dialog = screen.getByRole("dialog", { name: "Add a Service" });
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "Storage cage" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Monthly rate/), {
      target: { value: "15" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-01" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(/may be saved already/),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "Storage cage added. Tick it below if this Lease uses it.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    const [first, again] = addService.mock.calls;
    expect(first?.[1]).toEqual({
      service_id: again?.[1].service_id,
      name_en: "Storage cage",
      name_km: null,
      service_type_id: null,
      monthly_rate_usd_cents: 1500,
      starts_on: "2026-11-01",
    });
    expect(read.mock.calls.length).toBeGreaterThanOrEqual(3);

    // Other values saved before under this id: the form closes and says so, adding nothing.
    addService.mockRejectedValueOnce(new ServiceSettingsError("id_reused"));
    fireEvent.click(screen.getByRole("button", { name: "New Service" }));
    const second = screen.getByRole("dialog", { name: "Add a Service" });
    fireEvent.change(within(second).getByLabelText(/^Name in English/), {
      target: { value: "Cleaning" },
    });
    fireEvent.change(within(second).getByLabelText(/^Monthly rate/), {
      target: { value: "5" },
    });
    fireEvent.change(within(second).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-01" },
    });
    fireEvent.click(within(second).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        /This was already saved, with the values sent first/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(/Cleaning added/)).toBeNull();
    cleanup();

    // Without Settings access there is no button.
    window.location.hash = "#/leases";
    show(api(), deposits(), null, undefined, people(), units);
    fireEvent.click(await screen.findByRole("link", { name: "New Lease" }));
    await screen.findByText("No Services are set up in Settings yet.");
    expect(screen.queryByRole("button", { name: "New Service" })).toBeNull();
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
    await screen.findByLabelText("Parking");
    pickIn("Parking", "unit-U402");
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

  it("TEST-FE-1075 New Lease from a Parking page opens with that Parking chosen and still lets it change; a Parking a walk-in Lease may not use is not chosen", async () => {
    expect(formModeOf("unit:unit-U401")).toEqual({
      kind: "unit",
      unitId: "unit-U401",
    });
    expect(formModeOf("unit:")).toBeNull();
    expect(formModeOf("unit:a:b")).toBeNull();
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockImplementation((_property, source) =>
        Promise.resolve(
          lease("U401", { lease_id: source.lease_id, status: "DRAFTED" }),
        ),
      );
    window.location.hash = "#/leases/unit%3Aunit-U401";
    const view = show(
      api({ create }),
      deposits(),
      null,
      undefined,
      people(),
      units,
    );

    const unitBox = await screen.findByLabelText("Parking");
    expect(unitBox).toHaveValue("unit-U401");
    expect(
      within(unitBox)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Choose a Parking", "U401", "U402"]);
    pickIn("Primary Tenant", "customer-a");
    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "300" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.click(
      within(
        screen.getByRole("dialog", { name: "Save the draft · U401?" }),
      ).getByRole("button", { name: "Save draft" }),
    );
    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(1);
    });
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      unit_id: "unit-U401",
      primary_tenant_id: "customer-a",
      predecessor_lease_id: null,
      security_deposit_id: null,
    });
    view.unmount();

    // A Reserved Unit comes only with its Booking (DL-066), so nothing is chosen.
    window.location.hash = "#/leases/unit%3Aunit-U403";
    show(api(), deposits(), null, undefined, people(), units);
    expect(await screen.findByLabelText("Parking")).toHaveValue("");
  });

  it("TEST-FE-1109 New Lease starts at the Parking's default Rent, ticks and locks its required Services, and stops a lower Rent without a Manager; a Manager gives a reason (V1-061, DL-110)", async () => {
    const service = (id: string, name: string) => ({
      service_id: id,
      service_code: id,
      name_en: name,
      name_km: null,
      service_type_id: null,
      version: 1,
      rate_today_usd_cents: 1000,
      next_rate: null,
      rates: [{ monthly_rate_usd_cents: 1000, effective_date: "2026-01-01" }],
      approval_periods: [
        {
          approval_period_id: `ap-${id}`,
          effective_from: "2026-01-01",
          effective_through: null,
        },
      ],
      leases_using: 0,
    });
    const services = {
      read: vi.fn<ServiceSettingsApi["read"]>().mockResolvedValue({
        services: [
          service("svc-car", "Car park"),
          service("svc-wifi", "Wi-Fi"),
        ],
        service_types: [],
        today: "2026-10-29",
        can_manage: false,
      }),
    };
    const termsUnits: Partial<UnitApi> = {
      list: vi.fn<UnitApi["list"]>().mockResolvedValue({
        items: [
          {
            ...unit("U402", "VACANT"),
            default_monthly_rent_usd_cents: 45_000,
            required_service_ids: ["svc-car"],
          },
          unit("U401", "CLEANING"),
        ],
        next_cursor: null,
        can_manage: true,
      }),
    };
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockImplementation((_property, source) =>
        Promise.resolve(
          lease("U402", { lease_id: source.lease_id, status: "DRAFTED" }),
        ),
      );
    const save = async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      const confirm = await screen.findByRole("dialog", {
        name: "Save the draft · U402?",
      });
      fireEvent.click(
        within(confirm).getByRole("button", { name: "Save draft" }),
      );
    };
    window.location.hash = "#/leases/new";
    const view = show(
      api({ create }),
      deposits(),
      new Set(["leases.read", "leases.draft"]),
      undefined,
      people(),
      termsUnits,
      {},
      services,
    );

    await screen.findByLabelText("Parking");
    pickIn("Parking", "unit-U402");
    expect(screen.getByLabelText("Monthly Rent")).toHaveValue("450.00");
    expect(
      screen.getByText(
        "This Parking's default Rent is $450.00. A higher Rent is fine.",
      ),
    ).toBeInTheDocument();
    const car = await screen.findByRole("checkbox", { name: /Car park/ });
    expect(car).toBeChecked();
    expect(car).toBeDisabled();
    expect(car.closest("label")).toHaveTextContent("Required for this Parking");
    expect(screen.getByRole("checkbox", { name: /Wi-Fi/ })).toBeEnabled();
    pickIn("Primary Tenant", "customer-a");
    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "400" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText(
        "The Rent is below this Parking's default Rent of $450.00. Only a Manager or the Owner can agree a lower Rent.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "500" },
    });
    await save();
    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(1);
    });
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      unit_id: "unit-U402",
      monthly_rent_usd_cents: 50_000,
      reason: "Lease drafted from the New Lease form",
    });
    expect(
      create.mock.calls[0]?.[1].service_terms.map(
        (term) => term.property_service_id,
      ),
    ).toEqual(["svc-car"]);
    view.unmount();

    // A Manager may agree less, with a reason kept on the draft.
    window.location.hash = "#/leases/new";
    show(
      api({ create }),
      deposits(),
      new Set(["leases.read", "leases.draft", "rent.below_default"]),
      undefined,
      people(),
      termsUnits,
      {},
      services,
    );
    await screen.findByLabelText("Parking");
    pickIn("Parking", "unit-U402");
    pickIn("Primary Tenant", "customer-a");
    fireEvent.change(screen.getByLabelText("Monthly Rent"), {
      target: { value: "400" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText("Say why the Rent is lower."),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Why is the Rent below $450.00?"), {
      target: { value: "Long stay" },
    });
    await save();
    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(2);
    });
    expect(create.mock.calls[1]?.[1]).toMatchObject({
      monthly_rent_usd_cents: 40_000,
      reason:
        "Lease drafted from the New Lease form. Rent below the Parking default: Long stay",
    });
  });

  it("TEST-FE-858 a Lease from a Booking takes its Parking, Customer, Rent and Security Deposit", async () => {
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

    expect(await screen.findByLabelText("Parking")).toHaveValue("U403");
    expect(screen.getByLabelText("Primary Tenant")).toHaveValue("Bopha");
    expect(screen.getByLabelText("Monthly Rent")).toHaveValue("400.00");
    expect(
      screen.getByRole("region", { name: "What will be billed" }),
    ).toHaveTextContent(
      "Security Deposit: $80.00 received of $400.00 from the Booking; $320.00 is paid when the Lease is signed.",
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

  it("TEST-FE-1022 a Lease from a Booking records its Security Deposit, starting at the Reservation's amount; a change needs a reason and never goes below the money received (DL-101)", async () => {
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
    const money = signing();
    show(
      api({ create }),
      deposits(),
      null,
      { get },
      people(),
      units,
      {},
      {},
      undefined,
      money,
    );

    const box = await screen.findByLabelText("Security Deposit (USD)");
    expect(box).toHaveValue("400.00");
    expect(
      screen.getByText(
        "Starts at the Reservation's amount. It cannot be less than the $80.00 already received.",
      ),
    ).toBeInTheDocument();
    // Unchanged, it needs no reason.
    expect(
      screen.queryByLabelText("Why the Security Deposit changed"),
    ).toBeNull();
    fireEvent.change(box, { target: { value: "79.99" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      screen.getByText(
        "The Security Deposit cannot be less than the $80.00 already received.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Say why the Security Deposit changed."),
    ).toBeInTheDocument();
    fireEvent.change(box, { target: { value: "450" } });
    fireEvent.change(
      screen.getByLabelText("Why the Security Deposit changed"),
      {
        target: { value: " Rent went up " },
      },
    );
    expect(
      screen.getByRole("region", { name: "What will be billed" }),
    ).toHaveTextContent(
      "Security Deposit: $80.00 received of $450.00 from the Booking; $370.00 is paid when the Lease is signed.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Save draft",
      }),
    );
    await waitFor(() => {
      expect(money.planSecurityDeposit).toHaveBeenCalledTimes(1);
    });
    const sent = create.mock.calls[0]?.[1];
    expect(sent).toMatchObject({ security_deposit_id: "deposit-resv-1" });
    expect(money.planSecurityDeposit.mock.calls[0]?.[0]).toBe(sent?.lease_id);
    expect(money.planSecurityDeposit.mock.calls[0]?.[1]).toMatchObject({
      required_usd_cents: 45_000,
      reason: "Rent went up",
    });
  });

  it("TEST-FE-859 Renew starts the day after the old End Date with the same Parking, tenant and other Signers, linked to the old Lease", async () => {
    window.location.hash = "#/leases/lease-U101";
    const create = vi
      .fn<LeaseApi["create"]>()
      .mockImplementation((_property, source) =>
        Promise.resolve(lease("U101", { lease_id: source.lease_id })),
      );
    show(api({ create }), deposits(), null, undefined, people(), units);

    fireEvent.click(await screen.findByRole("link", { name: "Renew" }));
    expect(await screen.findByLabelText("Parking")).toHaveValue("U101");
    const next = addDays(running.end_date ?? today, 1);
    expect(screen.getByLabelText("Start Date")).toHaveValue(dayText(next));
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

    await screen.findByLabelText("Parking");
    pickIn("Parking", "unit-U402");
    await waitFor(() => {
      expect(screen.getByLabelText("Parking")).toHaveValue("unit-U402");
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
        "The Parking stays Occupied until the hand-back is recorded.",
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

  it("TEST-FE-1085 Terminate takes only a real day: a date typed in a wrong form is refused before anything is sent (B7)", async () => {
    window.location.hash = "#/leases/lease-U101";
    const terminate = vi.fn<LeaseApi["terminate"]>();
    show(api({ terminate }));
    const dialog = await openTerminate();
    fireEvent.click(
      within(dialog).getByRole("radio", { name: /Customer leaves early/ }),
    );
    // Typed in the year-first form with no real day ("2026-10-0").
    fireEvent.change(within(dialog).getByLabelText("Termination date"), {
      target: { value: `${today.slice(0, 8)}0` },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Evidence/), {
      target: { value: "Customer letter" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Moves to another city" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Terminate" }));
    expect(
      within(dialog).getByText(/Enter a date from .* up to today\./),
    ).toBeInTheDocument();
    expect(terminate).not.toHaveBeenCalled();
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

  // Parking Step 4: the people list is hidden (PEOPLE_MOVE_IN), the code kept.
  it("TEST-FE-1133 the New Lease form has no Other occupants list on Parking (people lists hidden, code kept)", async () => {
    show(
      api({}),
      deposits(),
      null,
      undefined,
      {
        get: vi.fn<CustomerApi["get"]>().mockRejectedValue(new Error("no")),
        list: vi.fn<CustomerApi["list"]>().mockResolvedValue({
          items: [],
          next_cursor: null,
          can_manage: false,
        }),
      },
      units,
      {},
      {},
      undefined,
      signing(),
    );
    fireEvent.click(await screen.findByRole("link", { name: "New Lease" }));
    await screen.findByLabelText("Parking");
    expect(screen.getByLabelText("Other Signers")).toBeInTheDocument();
    expect(screen.queryByLabelText("Other occupants")).toBeNull();
  });
});

describe("Add occupant (DL-102)", () => {
  function people(
    ...items: [string, string][]
  ): Pick<CustomerApi, "get" | "list"> {
    return {
      get: vi.fn<CustomerApi["get"]>().mockRejectedValue(new Error("no")),
      list: vi.fn<CustomerApi["list"]>().mockResolvedValue({
        items: items.map(([customer_id, legal_name]) => ({
          customer_id,
          legal_name,
          active: true,
          relationship_indicators: [],
        })),
        next_cursor: null,
        can_manage: false,
      }),
    };
  }

  it("TEST-FE-1118 a Lease with 20 people living there shows no Add occupant button and says why; 19 still shows it (V1-061 Fix 4)", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
    const crowd = (count: number) =>
      lease("U101", {
        occupancies: [
          ...lease("U101").occupancies,
          ...Array.from({ length: count - 1 }, (_, index) => ({
            occupancy_id: `occupancy-${String(index)}`,
            customer_id: `customer-${String(index)}`,
            customer_name: `Person ${String(index)}`,
            move_in_date: addDays(today, -100),
            move_out_date: null,
            version: 1,
          })),
        ],
      });
    window.location.hash = "#/leases/lease-U101";
    show(
      api({ get: vi.fn().mockResolvedValue(crowd(20)) }),
      deposits(),
      null,
      undefined,
      people(),
    );
    expect(
      await screen.findByText(
        "20 people are on this Lease, the most it takes. Move someone out first.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add occupant" })).toBeNull();

    cleanup();
    window.location.hash = "#/leases/lease-U101";
    show(
      api({ get: vi.fn().mockResolvedValue(crowd(19)) }),
      deposits(),
      null,
      undefined,
      people(),
    );
    expect(
      await screen.findByRole("button", { name: "Add occupant" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1025 after the move-in a friend gets their own move-in date: the date is checked, Try again sends the same Occupancy and key, and the page says who was added", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
    window.location.hash = "#/leases/lease-U101";
    const first = addDays(today, -199);
    const added = vi
      .fn<LeaseApi["addOccupant"]>()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockImplementationOnce((value) =>
        Promise.resolve({ ...value, version: value.version + 1 }),
      );
    show(
      api({
        get: vi.fn().mockResolvedValue(lease("U101")),
        addOccupant: added,
      }),
      deposits(),
      null,
      undefined,
      people(
        ["customer-U101", "Tenant U101"],
        ["customer-friend", "Chan Sopheap"],
      ),
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Add occupant" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Add occupant · U101",
    });
    const name = within(dialog).getByLabelText(/Name/);
    expect(
      await within(name).findByRole("option", { name: "Chan Sopheap" }),
    ).toBeInTheDocument();
    // The Primary Tenant already lives there.
    expect(
      within(name).queryByRole("option", { name: "Tenant U101" }),
    ).toBeNull();
    expect(within(dialog).getByLabelText(/Move-in date/)).toHaveValue(
      dayText(today),
    );
    expect(dialog).toHaveTextContent(
      `The day the person actually moved in, between ${dayText(first)} and ${dayText(today)}.`,
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent("Choose the person.");
    fireEvent.change(name, { target: { value: "customer-friend" } });
    fireEvent.change(within(dialog).getByLabelText(/Move-in date/), {
      target: { value: addDays(first, -1) },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent(
      `Enter a date between ${dayText(first)} and ${dayText(today)}.`,
    );
    expect(added).not.toHaveBeenCalled();

    const day = addDays(today, -2);
    fireEvent.change(within(dialog).getByLabelText(/Move-in date/), {
      target: { value: day },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Try again" }),
    );
    expect(
      await screen.findByText("Chan Sopheap added as an occupant of U101."),
    ).toBeInTheDocument();
    const sent = added.mock.calls[0]?.[1];
    expect(sent).toMatchObject({
      customer_id: "customer-friend",
      move_in_date: day,
      reason: `Chan Sopheap moved in on ${dayText(day)}`,
    });
    expect(sent?.occupancy_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(added.mock.calls[1]?.[1]).toEqual(sent);
    expect(added.mock.calls[1]?.[2]).toBe(added.mock.calls[0]?.[2]);
    expect(added.mock.calls[1]?.[0].version).toBe(3);
  });

  it("TEST-FE-1026 before the move-in the person is planned with no date, and the Occupants box lists who moves in with the Lease", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
    window.location.hash = "#/leases/lease-U302";
    const planned = lease("U302", {
      start_date: addDays(today, 10),
      end_date: addDays(today, 375),
      occupancies: [],
      planned_occupant_customer_ids: ["customer-U302"],
      planned_occupants: [
        { customer_id: "customer-U302", customer_name: "Tenant U302" },
      ],
    });
    let current = planned;
    const added = vi
      .fn<LeaseApi["addOccupant"]>()
      .mockImplementation((value, source) => {
        current = {
          ...value,
          version: value.version + 1,
          planned_occupant_customer_ids: [
            ...value.planned_occupant_customer_ids,
            source.customer_id,
          ],
          planned_occupants: [
            ...value.planned_occupants,
            { customer_id: source.customer_id, customer_name: "Sok Lina" },
          ],
        };
        return Promise.resolve(current);
      });
    show(
      api({
        get: vi.fn(() => Promise.resolve(current)),
        addOccupant: added,
      }),
      deposits(),
      null,
      undefined,
      people(["customer-U302", "Tenant U302"], ["customer-lina", "Sok Lina"]),
    );

    const box = (
      await screen.findByRole("heading", { name: "Occupants" })
    ).closest("section");
    if (box === null) throw new Error("no Occupants box");
    expect(box).toHaveTextContent(
      "Tenant U302Primary TenantMoves in with the Lease; the real date is recorded at move-in.",
    );
    fireEvent.click(within(box).getByRole("button", { name: "Add occupant" }));
    const dialog = screen.getByRole("dialog", {
      name: "Add occupant · U302",
    });
    expect(dialog).toHaveTextContent(
      "Nobody has moved in yet, so this person is listed now and gets the real date when the move-in is recorded.",
    );
    expect(within(dialog).queryByLabelText(/Move-in date/)).toBeNull();
    const name = within(dialog).getByLabelText(/Name/);
    await within(name).findByRole("option", { name: "Sok Lina" });
    expect(
      within(name).queryByRole("option", { name: "Tenant U302" }),
    ).toBeNull();
    fireEvent.change(name, { target: { value: "customer-lina" } });
    fireEvent.change(within(dialog).getByLabelText("Note (optional)"), {
      target: { value: "Her sister" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Sok Lina added as an occupant of U302."),
    ).toBeInTheDocument();
    expect(added.mock.calls[0]?.[1]).toMatchObject({
      customer_id: "customer-lina",
      occupancy_id: null,
      move_in_date: null,
      reason: "Her sister",
    });
    expect(box).toHaveTextContent(
      "Sok LinaOccupantMoves in with the Lease; the real date is recorded at move-in.",
    );
  });

  it("TEST-FE-1027 Add occupant shows on a draft and a running Lease to someone who records move-ins, and not on a renewal before its move-in, an ended or terminated Lease, after everyone moved out, or without the permissions", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
    const cases: [
      Partial<LeaseResource>,
      ReadonlySet<string> | null,
      boolean,
    ][] = [
      [{ status: "DRAFTED", signed_at: null, occupancies: [] }, null, true],
      [{}, null, true],
      [{}, new Set(["reservations.complete", "customers.read"]), true],
      [{ predecessor_lease_id: "lease-before", occupancies: [] }, null, false],
      [{ end_date: addDays(today, -1) }, null, false],
      [
        {
          status: "TERMINATED",
          actual_termination_date: addDays(today, -3),
        },
        null,
        false,
      ],
      [
        {
          occupancies: lease("U101").occupancies.map((occupancy) => ({
            ...occupancy,
            move_out_date: addDays(today, -1),
          })),
        },
        null,
        false,
      ],
      [{}, new Set(["customers.read"]), false],
      [{}, new Set(["reservations.complete"]), false],
    ];
    for (const [extra, capabilities, shown] of cases) {
      cleanup();
      window.location.hash = "#/leases/lease-U101";
      show(
        api({ get: vi.fn().mockResolvedValue(lease("U101", extra)) }),
        deposits(),
        capabilities,
      );
      await screen.findByRole("heading", { name: /Lease · U101/ });
      expect(
        screen.queryByRole("button", { name: "Add occupant" }) !== null,
      ).toBe(shown);
    }
  });

  it("TEST-FE-1112 Move out one occupant: a person who signs nothing moves out with only the day, and the History says Occupant moved out (V1-061, DL-111)", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
    window.location.hash = "#/leases/lease-U101";
    const people = lease("U101", {
      occupancies: [
        ...lease("U101").occupancies,
        {
          occupancy_id: "occupancy-friend",
          customer_id: "customer-friend",
          customer_name: "Chan Sopheap",
          move_in_date: addDays(today, -100),
          move_out_date: null,
          version: 1,
        },
      ],
      timeline: [
        {
          event_id: "event-out",
          event_kind: "lease.occupant_moved_out",
          occurred_at: "2026-10-28T03:00:00Z",
          reason: "Dara moved out on 28/10/2026",
          actor_id: "actor-1",
          source_reference: null,
          source_href: null,
        },
      ],
    });
    const moveOutOccupant = vi
      .fn<LeaseApi["moveOutOccupant"]>()
      .mockResolvedValue(people);
    show(api({ get: vi.fn().mockResolvedValue(people), moveOutOccupant }));

    expect(await screen.findByText("Occupant moved out")).toBeInTheDocument();
    // The Primary Tenant has no button and says why.
    expect(screen.getAllByRole("button", { name: "Move out" })).toHaveLength(1);
    expect(
      screen.getByText("Primary Tenant: moves out only with the Lease."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Move out" }));
    const dialog = screen.getByRole("dialog", {
      name: "Move out · Chan Sopheap",
    });
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Move out" }));

    await waitFor(() => {
      expect(moveOutOccupant).toHaveBeenCalledTimes(1);
    });
    expect(moveOutOccupant).toHaveBeenCalledWith(
      expect.objectContaining({ lease_id: "lease-U101" }),
      "occupancy-friend",
      expect.objectContaining({
        move_out_date: today,
        agreed_signer_customer_ids: [],
      }),
      expect.anything(),
    );
    expect(moveOutOccupant.mock.calls.at(0)?.[2].reason).toMatch(
      /^Chan Sopheap moved out on /,
    );
    expect(
      await screen.findByText("Chan Sopheap has moved out."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1113 Move out a Joint Signer: every other Signer must be ticked as agreeing; the only Signer living there and a reader without the move-in right get no button (V1-061, DL-111)", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
    window.location.hash = "#/leases/lease-U101";
    const guarantor = {
      occupancy_id: "occupancy-guarantor",
      customer_id: "customer-guarantor",
      customer_name: "Guarantor",
      move_in_date: addDays(today, -199),
      move_out_date: null,
      version: 1,
    };
    const joint = lease("U101", {
      signers: running.signers,
      occupancies: [...lease("U101").occupancies, guarantor],
    });
    const moveOutOccupant = vi
      .fn<LeaseApi["moveOutOccupant"]>()
      .mockResolvedValue(joint);
    show(api({ get: vi.fn().mockResolvedValue(joint), moveOutOccupant }));

    fireEvent.click(await screen.findByRole("button", { name: "Move out" }));
    const dialog = screen.getByRole("dialog", { name: "Move out · Guarantor" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move out" }));
    expect(
      within(dialog).getByText(
        "Tick each Signer once they have agreed. Every other Signer must agree.",
      ),
    ).toBeInTheDocument();
    expect(moveOutOccupant).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: /Tenant U101 agrees/ }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Move out" }));
    await waitFor(() => {
      expect(moveOutOccupant).toHaveBeenCalledTimes(1);
    });
    expect(moveOutOccupant).toHaveBeenCalledWith(
      expect.anything(),
      "occupancy-guarantor",
      expect.objectContaining({
        agreed_signer_customer_ids: ["customer-U101"],
      }),
      expect.anything(),
    );

    // When the Guarantor lives there alone after the Primary Tenant left, they are the only
    // Signer living there and wait for Terminate.
    cleanup();
    window.location.hash = "#/leases/lease-U101";
    const alone = lease("U101", {
      signers: running.signers,
      occupancies: [
        ...lease("U101").occupancies.map((occupancy) => ({
          ...occupancy,
          move_out_date: addDays(today, -1),
        })),
        guarantor,
      ],
    });
    show(api({ get: vi.fn().mockResolvedValue(alone) }));
    expect(
      await screen.findByText(
        "The only Signer living there: moves out only when the Lease ends (Terminate).",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move out" })).toBeNull();

    cleanup();
    window.location.hash = "#/leases/lease-U101";
    show(
      api({ get: vi.fn().mockResolvedValue(joint) }),
      deposits(),
      new Set(["customers.read"]),
    );
    await screen.findByRole("heading", { name: /Lease · U101/ });
    expect(screen.queryByRole("button", { name: "Move out" })).toBeNull();
  });

  it("TEST-FE-1028 Record move-in names the planned people from the Lease without reading each Customer", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
    window.location.hash = "#/leases/lease-move";
    const ready = lease("U302", {
      lease_id: "lease-move",
      start_date: addDays(today, -3),
      end_date: addDays(today, 360),
      signed_at: `${addDays(today, -5)}T03:00:00Z`,
      occupancies: [],
      can_move_in: true,
      planned_occupant_customer_ids: ["customer-U302", "customer-kid"],
      planned_occupants: [
        { customer_id: "customer-U302", customer_name: "Tenant U302" },
        { customer_id: "customer-kid", customer_name: "Kid K" },
      ],
    });
    const get = vi.fn<CustomerApi["get"]>().mockRejectedValue(new Error("no"));
    show(
      api({ get: vi.fn().mockResolvedValue(ready) }),
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
    expect(
      within(dialog).getByRole("checkbox", { name: /Kid K/ }),
    ).toBeChecked();
    expect(get).not.toHaveBeenCalledWith("customer-kid");
  });

  it("TEST-FE-1029 New Customer opens the Add Customer form in place of the dialog and Cancel comes back; a failed Customer read and a refused save say so; the History says Occupant added", async ({
    skip,
  }) => {
    // Parking Step 4: people lists are hidden on Parking (PEOPLE_MOVE_IN); the code stays.
    skip(!PEOPLE_MOVE_IN);
    window.location.hash = "#/leases/lease-U101";
    const added = vi
      .fn<LeaseApi["addOccupant"]>()
      .mockRejectedValue(new LeaseRequestError());
    const withHistory = lease("U101", {
      timeline: [
        {
          event_id: "event-occupant",
          event_kind: "lease.occupant_added",
          occurred_at: "2026-10-28T03:00:00Z",
          reason: "Chan Sopheap moved in on 28/10/2026",
          actor_id: "actor-1",
          source_reference: null,
          source_href: null,
        },
      ],
    });
    show(
      api({ get: vi.fn().mockResolvedValue(withHistory), addOccupant: added }),
      deposits(),
      null,
      undefined,
      people(["customer-friend", "Chan Sopheap"]),
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      {
        customerCreateApi: {} as CustomerApi,
        customerGate: {
          actorId: "actor-1",
          open: true,
          reserve: vi.fn().mockResolvedValue(true),
          release: vi.fn().mockResolvedValue(true),
          setBusy: vi.fn(),
        },
      },
    );

    expect(
      await screen.findByText("Chan Sopheap moved in on 28/10/2026"),
    ).toBeInTheDocument();
    expect(screen.getByText("Occupant added")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add occupant" }));
    fireEvent.click(screen.getByRole("button", { name: "New Customer" }));
    expect(
      screen.getByRole("dialog", { name: "Add Customer" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: "Add occupant · U101" }),
    ).toBeNull();
    const [cancel] = within(
      screen.getByRole("dialog", { name: "Add Customer" }),
    ).getAllByRole("button", { name: "Cancel" });
    if (cancel === undefined) throw new Error("no Cancel button");
    fireEvent.click(cancel);
    const dialog = screen.getByRole("dialog", { name: "Add occupant · U101" });
    const name = within(dialog).getByLabelText(/Name/);
    await within(name).findByRole("option", { name: "Chan Sopheap" });
    fireEvent.change(name, { target: { value: "customer-friend" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "The server refused this. Nothing was saved. Check the details, or ask the Owner.",
      ),
    ).toBeInTheDocument();

    cleanup();
    window.location.hash = "#/leases/lease-U101";
    show(
      api({ get: vi.fn().mockResolvedValue(lease("U101")) }),
      deposits(),
      null,
      undefined,
      {
        get: vi.fn<CustomerApi["get"]>().mockRejectedValue(new Error("no")),
        list: vi.fn<CustomerApi["list"]>().mockRejectedValue(new Error("down")),
      },
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Add occupant" }),
    );
    expect(
      await screen.findByText(
        "The Customers could not be read just now. Close and try again.",
      ),
    ).toBeInTheDocument();
  });
});

// Parking Step 4 (owner 2026-10-30): the vehicle takes the Occupancy slot of a Lease.
describe("Vehicle (Parking Step 4)", () => {
  function vehicle(
    id: string,
    plate: string,
    type: VehicleResource["vehicle_type"],
    owner: string,
    ownerName: string,
  ): VehicleResource {
    return {
      vehicle_id: id,
      customer_id: owner,
      customer_name: ownerName,
      vehicle_type: type,
      plate_text: plate,
      version: 1,
    };
  }
  const garage = (id: string) =>
    id === "customer-U101" || id === "customer-U302"
      ? [
          vehicle(
            "vehicle-car",
            "1AB-1234",
            "CAR",
            id,
            `Tenant ${id.slice(9)}`,
          ),
          vehicle(
            "vehicle-second",
            "1AB-0001",
            "CAR",
            id,
            `Tenant ${id.slice(9)}`,
          ),
        ]
      : id === "customer-guarantor"
        ? [vehicle("vehicle-moto", "2CD-5678", "MOTORBIKE", id, "Guarantor")]
        : [];
  const people = () => ({
    get: vi.fn<CustomerApi["get"]>((id) =>
      Promise.resolve({
        customer_id: id,
        legal_name: "Someone",
      } as CustomerDetail),
    ),
    listVehicles: vi.fn<CustomerApi["listVehicles"]>((id) =>
      Promise.resolve(garage(id)),
    ),
  });
  const parked = (overrides: Partial<LeaseResource> = {}) =>
    lease("U101", {
      occupancies: [
        {
          occupancy_id: "occupancy-old",
          customer_id: "customer-U101",
          customer_name: "Tenant U101",
          move_in_date: addDays(today, -199),
          move_out_date: addDays(today, -10),
          version: 2,
          vehicle_id: "vehicle-car",
          vehicle_type: "CAR",
          plate_text: "1AB-1234",
        },
        {
          occupancy_id: "occupancy-now",
          customer_id: "customer-guarantor",
          customer_name: "Guarantor",
          move_in_date: addDays(today, -10),
          move_out_date: null,
          version: 1,
          vehicle_id: "vehicle-moto",
          vehicle_type: "MOTORBIKE",
          plate_text: "2CD-5678",
        },
      ],
      timeline: [
        {
          event_id: "event-in",
          event_kind: "lease.move_in",
          occurred_at: "2026-04-01T03:00:00Z",
          reason: "Vehicle moved in",
          actor_id: "actor-1",
          source_reference: null,
          source_href: null,
        },
        {
          event_id: "event-change",
          event_kind: "lease.vehicle_changed",
          occurred_at: "2026-10-20T03:00:00Z",
          reason: "1AB-1234 → 2CD-5678: Sold the old car",
          actor_id: "actor-1",
          source_reference: null,
          source_href: null,
        },
      ],
      ...overrides,
    });

  it("TEST-FE-1130 the Lease page shows the vehicle moved in, the earlier vehicles with their move-out day, Change vehicle, and no people buttons", async () => {
    window.location.hash = "#/leases/lease-U101";
    show(api({ get: vi.fn().mockResolvedValue(parked()) }));
    const card = await screen.findByRole("region", { name: "Vehicle" });
    expect(within(card).getByText("2CD-5678")).toBeInTheDocument();
    expect(within(card).getByText("Motorbike")).toBeInTheDocument();
    expect(
      within(card).getByRole("link", { name: "Guarantor" }),
    ).toBeInTheDocument();
    expect(card).toHaveTextContent(`Moved in ${dayText(addDays(today, -10))}`);
    expect(within(card).getByText("1AB-1234")).toBeInTheDocument();
    expect(card).toHaveTextContent(`moved out ${dayText(addDays(today, -10))}`);
    expect(
      within(card).getByRole("button", { name: "Change vehicle" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move out" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add occupant" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Occupants" })).toBeNull();
    // The History names the event and shows the reason it was recorded with.
    expect(screen.getAllByText("Vehicle moved in").length).toBeGreaterThan(0);
    expect(screen.getByText("Vehicle changed")).toBeInTheDocument();
    expect(
      screen.getByText("1AB-1234 → 2CD-5678: Sold the old car"),
    ).toBeInTheDocument();

    cleanup();
    window.location.hash = "#/leases/lease-U101";
    show(
      api({ get: vi.fn().mockResolvedValue(parked()) }),
      deposits(),
      new Set(["leases.read", "customers.read"]),
    );
    const reading = await screen.findByRole("region", { name: "Vehicle" });
    expect(
      within(reading).queryByRole("button", { name: "Change vehicle" }),
    ).toBeNull();

    cleanup();
    window.location.hash = "#/leases/lease-U101";
    show(
      api({
        get: vi
          .fn()
          .mockResolvedValue(parked({ occupancies: [], timeline: [] })),
      }),
    );
    const empty = await screen.findByRole("region", { name: "Vehicle" });
    expect(
      within(empty).getByText("No vehicle moved in yet."),
    ).toBeInTheDocument();
    expect(
      within(empty).queryByRole("button", { name: "Change vehicle" }),
    ).toBeNull();
  });

  it("TEST-FE-1131 Record move-in picks one vehicle of the Signers, checks the date, keeps the ids on Try again, and points to the Customer page when there is none", async () => {
    window.location.hash = "#/leases/lease-move";
    const start = addDays(today, -3);
    const ready = lease("U302", {
      lease_id: "lease-move",
      start_date: start,
      end_date: addDays(today, 360),
      signed_at: `${addDays(today, -5)}T03:00:00Z`,
      occupancies: [],
      can_move_in: true,
      signers: [
        ...lease("U302").signers,
        {
          signer_id: "signer-g",
          customer_id: "customer-guarantor",
          customer_name: "Guarantor",
          is_primary_tenant: false,
          signed_at: "2026-03-01T03:00:00Z",
          added_at: "2026-02-20T03:00:00Z",
        },
      ],
    });
    const recordVehicleMoveIn = vi
      .fn<LeaseApi["recordVehicleMoveIn"]>()
      .mockRejectedValueOnce(new LeaseUnavailableError())
      .mockImplementationOnce((value) => Promise.resolve(value));
    const customers = people();
    show(
      api({ get: vi.fn().mockResolvedValue(ready), recordVehicleMoveIn }),
      deposits(),
      null,
      undefined,
      customers,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Record move-in" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Record move-in · U302",
    });
    expect(
      await within(dialog).findByRole("radio", {
        name: "1AB-1234 · Car · Tenant U302",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("radio", {
        name: "2CD-5678 · Motorbike · Guarantor",
      }),
    ).toBeInTheDocument();
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    expect(customers.listVehicles).toHaveBeenCalledWith("customer-guarantor");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record move-in" }),
    );
    expect(within(dialog).getByText("Choose the vehicle.")).toBeInTheDocument();
    expect(recordVehicleMoveIn).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("radio", {
        name: "1AB-1234 · Car · Tenant U302",
      }),
    );
    fireEvent.change(within(dialog).getByLabelText("Move-in date"), {
      target: { value: addDays(start, -1) },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record move-in" }),
    );
    expect(dialog).toHaveTextContent(
      `Choose a date from ${dayText(start)} to ${dayText(today)}.`,
    );
    fireEvent.change(within(dialog).getByLabelText("Move-in date"), {
      target: { value: start },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record move-in" }),
    );
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Try again" }),
    );
    expect(await screen.findByText("Vehicle moved in.")).toBeInTheDocument();
    const first = recordVehicleMoveIn.mock.calls[0]?.[1];
    expect(first).toMatchObject({
      actual_move_in_date: start,
      vehicle_id: "vehicle-car",
      reason: "Vehicle moved in",
    });
    expect(first?.occupancy_id).toEqual(expect.any(String));
    expect(recordVehicleMoveIn.mock.calls[1]?.[1]).toEqual(first);
    expect(recordVehicleMoveIn.mock.calls[1]?.[2]).toBe(
      recordVehicleMoveIn.mock.calls[0]?.[2],
    );

    cleanup();
    window.location.hash = "#/leases/lease-move";
    show(
      api({ get: vi.fn().mockResolvedValue(ready), recordVehicleMoveIn }),
      deposits(),
      null,
      undefined,
      {
        ...people(),
        listVehicles: vi
          .fn<CustomerApi["listVehicles"]>()
          .mockResolvedValue([]),
      },
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Record move-in" }),
    );
    const none = screen.getByRole("dialog", { name: "Record move-in · U302" });
    expect(
      await within(none).findByText(
        "No vehicle yet. Add one on the Customer page first.",
      ),
    ).toBeInTheDocument();
    expect(
      within(none).getByRole("link", { name: "Tenant U302" }),
    ).toHaveAttribute("href", "#/customers/customer-U302");
    expect(within(none).queryByRole("radio")).toBeNull();
  });

  it("TEST-FE-1132 Change vehicle offers the Signers' other vehicles, needs a reason, sends the vehicle and the day, and shows the server's words when refused", async () => {
    window.location.hash = "#/leases/lease-U101";
    const current = parked({
      signers: [
        ...lease("U101").signers,
        {
          signer_id: "signer-g",
          customer_id: "customer-guarantor",
          customer_name: "Guarantor",
          is_primary_tenant: false,
          signed_at: "2026-03-01T03:00:00Z",
          added_at: "2026-02-20T03:00:00Z",
        },
      ],
    });
    const changeVehicle = vi
      .fn<LeaseApi["changeVehicle"]>()
      .mockRejectedValueOnce(
        new LeaseRefusedError(
          "VEHICLE_TYPE",
          "This vehicle type cannot park in this Parking Type. Car: Covered or Uncovered. Motorbike: Motorbike. Tuk-tuk and food cart: Tuk-Tuk/Food Cart.",
        ),
      )
      .mockImplementationOnce((value) =>
        Promise.resolve({ ...value, version: value.version + 1 }),
      );
    show(
      api({ get: vi.fn().mockResolvedValue(current), changeVehicle }),
      deposits(),
      null,
      undefined,
      people(),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Change vehicle" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Change vehicle · U101",
    });
    expect(
      await within(dialog).findByRole("radio", {
        name: "1AB-1234 · Car · Tenant U101",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("radio", {
        name: "1AB-0001 · Car · Tenant U101",
      }),
    ).toBeInTheDocument();
    // The vehicle moved in now is not offered.
    expect(
      within(dialog).queryByRole("radio", { name: /2CD-5678/ }),
    ).toBeNull();
    expect(within(dialog).getByLabelText("Change date")).toHaveValue(
      dayText(today),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Change vehicle" }),
    );
    expect(within(dialog).getByText("Choose the vehicle.")).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("radio", {
        name: "1AB-1234 · Car · Tenant U101",
      }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Change vehicle" }),
    );
    expect(
      within(dialog).getByText("Give the reason for the change."),
    ).toBeInTheDocument();
    expect(changeVehicle).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Reason"), {
      target: { value: " Sold the motorbike " },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Change vehicle" }),
    );
    expect(
      await within(dialog).findByText(
        /This vehicle type cannot park in this Parking Type/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Change vehicle" }),
    );
    expect(await screen.findByText("Vehicle changed.")).toBeInTheDocument();
    expect(changeVehicle).toHaveBeenCalledTimes(2);
    expect(changeVehicle.mock.calls[1]?.[1]).toMatchObject({
      change_date: today,
      vehicle_id: "vehicle-car",
      reason: "Sold the motorbike",
    });
    expect(changeVehicle.mock.calls[1]?.[1].occupancy_id).toEqual(
      expect.any(String),
    );
    expect(changeVehicle.mock.calls[1]?.[0].version).toBe(3);
  });

  it("TEST-FE-1138 Change vehicle opens on the End Date when that day is already past", async () => {
    window.location.hash = "#/leases/lease-U101";
    const overdue = parked({
      end_date: addDays(today, -2),
      occupancies: parked().occupancies.map((row) =>
        row.move_out_date === null
          ? { ...row, move_in_date: addDays(today, -30) }
          : row,
      ),
    });
    show(
      api({ get: vi.fn().mockResolvedValue(overdue) }),
      deposits(),
      null,
      undefined,
      people(),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Change vehicle" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Change vehicle · U101",
    });
    expect(within(dialog).getByLabelText("Change date")).toHaveValue(
      dayText(addDays(today, -2)),
    );
  });
});
