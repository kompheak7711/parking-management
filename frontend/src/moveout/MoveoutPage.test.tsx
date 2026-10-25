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
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceResource,
} from "../invoiceClient";
import {
  SettlementRequestError,
  type SettlementApi,
} from "../settlementClient";
import {
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
} from "../leaseClient";
import type { UnitResource } from "../unitClient";
import {
  UtilityClientError,
  type UtilityApi,
  type UtilityMeter,
  type UtilityReading,
} from "../utilityClient";
import { currentFinalInputs, finalInvoiceOf, metersOn } from "./finalReadings";
import {
  UtilityLeaseError,
  type EvidenceRecord,
  type UtilityLeaseApi,
} from "../utilityLeaseClient";
import {
  billedSources,
  cleaningInvoice,
  currentInspection,
  currentInspections,
} from "./charges";
import {
  MoveOutUnavailableError,
  type MoveOutApi,
  type MoveOutInspection,
  type MoveOutPage,
  type MoveOutRecord,
} from "./moveoutClient";
import { MoveoutPage } from "./MoveoutPage";

const TODAY = "2026-10-25";

function nth(items: HTMLElement[], index: number): HTMLElement {
  const item = items[index];
  if (item === undefined) throw new Error(`No item ${String(index)}`);
  return item;
}

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

function meter(type: "ELECTRICITY" | "WATER"): UtilityMeter {
  return {
    id: `meter-${type}`,
    property_id: "property-1",
    unit_id: "unit-U105",
    utility_type: type,
    serial_number: type === "ELECTRICITY" ? "E-501" : "W-501",
    measurement_unit_code: type === "ELECTRICITY" ? "KWH" : "M3",
    description: null,
    installed_date: "2024-01-01",
    failure_date: null,
    deactivated_date: null,
    current: true,
    version: 4,
    memo: null,
    replacement: {
      replaced_meter_id: null,
      replacement_meter_id: null,
      replacement_date: null,
    },
    readings_url: "",
  };
}

function reading(
  meterId: string,
  day: string,
  value: string,
  id = `reading-${meterId}-${day}`,
): UtilityReading {
  return {
    id,
    property_id: "property-1",
    meter_id: meterId,
    unit_id: "unit-U105",
    utility_type: meterId.endsWith("WATER") ? "WATER" : "ELECTRICITY",
    measurement_unit_code: meterId.endsWith("WATER") ? "M3" : "KWH",
    reading_date: day,
    original_value: value,
    effective_value: value,
    source: { kind: "MANUAL", evidence: "" },
    version: 1,
    corrections: [],
    validated: true,
    validated_at: `${day}T05:00:00Z`,
    validated_by: "actor-1",
  };
}

function finalInvoice(): InvoiceResource {
  const money = (cents: number) => ({
    currency: "USD" as const,
    minor_units: cents,
  });
  return {
    id: "invoice-final",
    property_id: "property-1",
    customer_id: "customer-U105",
    lease_id: "lease-U105",
    invoice_number: "INV-0042",
    category: "UTILITIES",
    status: "UNPAID",
    invoice_date: "2026-10-13",
    due_date: "2026-10-20",
    billing_period: null,
    version: 1,
    original_total: money(1830),
    adjusted_total: money(1830),
    active_application_total: money(0),
    outstanding_balance: money(1830),
    lines: [
      {
        id: "line-1",
        sequence: 1,
        description: "Electricity",
        category: "UTILITIES",
        original_amount: money(1830),
        adjusted_amount: money(1830),
        outstanding_balance: money(1830),
        source: {},
        calculation_evidence: {
          billing_kind: "FINAL",
          end_reading_id: "final-reading",
        },
        period: null,
      },
    ],
    adjustments: [],
    void_event: null,
    evidence: {},
  };
}

function chargeInvoice(
  source: string,
  category: "DAMAGE_CHARGES" | "MISCELLANEOUS_CHARGES",
  cents: number,
  status: InvoiceResource["status"],
  description = category === "DAMAGE_CHARGES"
    ? "Damage: Broken window"
    : "Unit cleaning charge",
): InvoiceResource {
  const money = (amount: number) => ({
    currency: "USD" as const,
    minor_units: amount,
  });
  return {
    ...finalInvoice(),
    id: `invoice-${source}`,
    invoice_number: status === "DRAFT" ? "" : `INV-${source}`,
    category,
    status,
    original_total: money(cents),
    adjusted_total: money(cents),
    outstanding_balance: money(cents),
    lines: [
      {
        id: `line-${source}`,
        sequence: 1,
        description,
        category,
        original_amount: money(cents),
        adjusted_amount: money(cents),
        outstanding_balance: money(cents),
        source: { type: "AUTHORIZED_NONRECURRING_OBLIGATION", id: source },
        calculation_evidence: {
          formula: "authorized_source_exact_amount",
          source_reference: `one-time-charge:${source}`,
        },
        period: null,
      },
    ],
  };
}

function inspectionOf(
  id: string,
  findings: [string, string, boolean][],
  overrides: Partial<MoveOutInspection> = {},
): MoveOutInspection {
  return {
    id,
    lease_id: "lease-U105",
    inspection_date: "2026-10-13",
    result_text: "Checked with the tenant",
    evidence_reference: "Move-out inspection recorded in the app",
    reason: "Move-out inspection after the hand-back",
    completed_at: "2026-10-13T04:00:00Z",
    supersedes_inspection_id: null,
    current_effect: "INSPECTION_ONLY",
    findings: findings.map(([findingId, description, pet], index) => ({
      id: findingId,
      ordinal: index + 1,
      description,
      pet_related: pet,
    })),
    ...overrides,
  };
}

function savedInspection(
  source: Parameters<MoveOutApi["inspect"]>[2],
): MoveOutInspection {
  return inspectionOf(
    source.inspection_id,
    source.findings.map((finding) => [
      finding.finding_id,
      finding.description,
      finding.pet_related,
    ]),
    {
      inspection_date: source.inspection_date,
      result_text: source.result_text,
      supersedes_inspection_id: source.supersedes_inspection_id,
    },
  );
}

const handedBackPage: MoveOutPage = {
  items: [
    {
      event_id: "move-out-1",
      lease_id: "lease-U105",
      termination_event_id: "termination",
      actual_move_out_date: "2026-10-12",
      unit_condition: "CLEANING",
      resulting_unit_status: "CLEANING",
      reason: "Unit handed back",
      evidence_reference: "Keys returned: all",
      supersedes_event_id: null,
      occurred_at: "2026-10-12T05:00:00Z",
      actor_id: "actor-1",
      event_status: "CURRENT",
      occupancies: [],
    },
  ],
  total: 1,
  open_occupancies: [],
};

function inputsPage(eventId: string | null): EvidenceRecord {
  return {
    items:
      eventId === null
        ? []
        : [
            {
              event_id: eventId,
              move_out_event_id: "move-out-1",
              actual_move_out_date: "2026-10-12",
              occurred_at: "2026-10-12T06:00:00Z",
              event_status: "CURRENT",
              physical_event_status: "CURRENT",
              unresolved_item_count: 0,
              items: [
                {
                  meter_id: "meter-ELECTRICITY",
                  utility_type: "ELECTRICITY",
                  resolution: "READING",
                  reading: {
                    reading_id: "final-reading",
                    reading_value: "4190",
                  },
                },
              ],
            },
          ],
    total: eventId === null ? 0 : 1,
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
    finalInputs?: () => Promise<EvidenceRecord>;
    invoices?: () => Promise<InvoiceResource[]>;
    readings?: Record<string, UtilityReading[]>;
    recordInputs?: UtilityLeaseApi["recordFinalInputs"];
    createInvoice?: UtilityLeaseApi["createFinalInvoice"];
    inspections?: MoveOutInspection[];
    inspect?: MoveOutApi["inspect"];
    recordCharge?: InvoiceApi["recordOneTimeCharge"];
    createDraft?: InvoiceApi["create"];
    cleaningRate?: SettlementApi["cleaningRate"];
    chargeCleaning?: SettlementApi["chargeCleaning"];
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
    inspections: vi.fn<MoveOutApi["inspections"]>(() =>
      Promise.resolve({
        items: options.inspections ?? [],
        total: options.inspections?.length ?? 0,
      }),
    ),
    inspect: vi.fn<MoveOutApi["inspect"]>(
      options.inspect ??
        ((_property, _lease, source) =>
          Promise.resolve(savedInspection(source))),
    ),
  };
  const utilityApi = {
    loadMeters: vi.fn<UtilityApi["loadMeters"]>(() =>
      Promise.resolve({
        items: [meter("ELECTRICITY"), meter("WATER")],
        nextCursor: null,
      }),
    ),
    loadReadings: vi.fn<UtilityApi["loadReadings"]>((meterId) =>
      Promise.resolve({
        items: options.readings?.[meterId] ?? [
          reading(
            meterId,
            "2026-09-24",
            meterId.endsWith("WATER") ? "310" : "4120",
          ),
        ],
        nextCursor: null,
      }),
    ),
    recordReading: vi.fn<UtilityApi["recordReading"]>((meterId, input) =>
      Promise.resolve(
        reading(
          meterId,
          input.reading_date,
          input.reading_value,
          `saved-${meterId}`,
        ),
      ),
    ),
  };
  const utilityLeaseApi = {
    readFinalInputs: vi.fn<UtilityLeaseApi["readFinalInputs"]>(
      options.finalInputs ?? (() => Promise.resolve(inputsPage(null))),
    ),
    recordFinalInputs: vi.fn<UtilityLeaseApi["recordFinalInputs"]>(
      options.recordInputs ??
        ((_property, _lease, input) =>
          Promise.resolve({ event_id: input.event_id })),
    ),
    createFinalInvoice: vi.fn<UtilityLeaseApi["createFinalInvoice"]>(
      options.createInvoice ??
        ((_property, _lease, input) =>
          Promise.resolve({
            invoice_id: input.invoice_id,
            invoice: { invoice_number: "INV-0042" },
          })),
    ),
  };
  const invoiceApi = {
    list: vi.fn<InvoiceApi["list"]>((_property, filters) =>
      (options.invoices ?? (() => Promise.resolve([])))().then((items) => ({
        items: items.filter(
          (item) =>
            filters?.category === undefined ||
            item.category === filters.category,
        ),
        next_cursor: null,
        capabilities: [],
      })),
    ),
    recordOneTimeCharge: vi.fn<InvoiceApi["recordOneTimeCharge"]>(
      options.recordCharge ??
        ((_property, input) =>
          Promise.resolve({
            obligation_id: input.charge_id,
            ...input,
            evidence: {},
          })),
    ),
    create: vi.fn<InvoiceApi["create"]>(
      options.createDraft ??
        ((_property, obligation) =>
          Promise.resolve(
            chargeInvoice(obligation, "DAMAGE_CHARGES", 2500, "DRAFT"),
          )),
    ),
  };
  const settlementApi = {
    cleaningRate: vi.fn<SettlementApi["cleaningRate"]>(
      options.cleaningRate ??
        (() =>
          Promise.resolve({ rate: { id: "rate-1", rate_usd_cents: 3500 } })),
    ),
    chargeCleaning: vi.fn<SettlementApi["chargeCleaning"]>(
      options.chargeCleaning ??
        ((_property, _lease, form) =>
          Promise.resolve({ obligation_id: form.charge_id })),
    ),
  };
  render(
    <MoveoutPage
      active
      capabilities={options.capabilities ?? null}
      depositApi={depositApi}
      invoiceApi={invoiceApi}
      language="en"
      leaseApi={leaseApi}
      moveOutApi={moveOutApi}
      propertyId="property-1"
      settlementApi={settlementApi}
      today={TODAY}
      unitApi={unitApi}
      utilityApi={utilityApi}
      utilityLeaseApi={utilityLeaseApi}
    />,
  );
  return {
    leaseApi,
    depositApi,
    unitApi,
    moveOutApi,
    utilityApi,
    utilityLeaseApi,
    invoiceApi,
    settlementApi,
  };
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

  it("TEST-FE-967 after the hand-back, Record final readings shows each meter with its last reading, refuses a lower or broken reading and marks only that box, then saves both readings on the hand-back day, the final inputs that name them and the final Utility Invoice", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const { utilityApi, utilityLeaseApi, invoiceApi } = setup([out], {
      page: handedBackPage,
    });
    const button = await screen.findByRole("button", {
      name: "Record final readings",
    });
    expect(
      screen.getByText(/Read both meters on the hand-back day/),
    ).toBeTruthy();
    // No final inputs yet: the Invoices are not read.
    expect(
      invoiceApi.list.mock.calls.some(
        (call) => call[1]?.category === "UTILITIES",
      ),
    ).toBe(false);
    fireEvent.click(button);
    const dialog = screen.getByRole("dialog");
    const electricity = await within(dialog).findByLabelText(/Electricity/);
    expect(
      within(dialog).getByText("Last reading 4,120 kWh on 24/09/2026"),
    ).toBeTruthy();
    expect(
      within(dialog).getByText("Last reading 310 m³ on 24/09/2026"),
    ).toBeTruthy();
    fireEvent.change(electricity, { target: { value: "4100" } });
    fireEvent.change(within(dialog).getByLabelText(/Water/), {
      target: { value: "318" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Save and issue the Invoice",
      }),
    );
    expect(
      within(dialog).getByText(
        "Each new reading must be a whole number not lower than the last reading.",
      ),
    ).toBeTruthy();
    expect(utilityApi.recordReading).not.toHaveBeenCalled();
    expect(electricity.getAttribute("aria-invalid")).toBe("true");
    expect(
      within(dialog).getByLabelText(/Water/).getAttribute("aria-invalid"),
    ).toBe("false");
    fireEvent.change(electricity, { target: { value: "41a5" } });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Save and issue the Invoice",
      }),
    );
    expect(electricity.getAttribute("aria-invalid")).toBe("true");
    expect(utilityApi.recordReading).not.toHaveBeenCalled();
    fireEvent.change(electricity, { target: { value: "4,185" } });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Save and issue the Invoice",
      }),
    );
    await screen.findByText("Final Utility Invoice INV-0042 issued.");
    expect(
      utilityApi.recordReading.mock.calls.map((call) => call.slice(0, 2)),
    ).toEqual([
      [
        "meter-ELECTRICITY",
        {
          expected_meter_version: 4,
          reading_date: "2026-10-12",
          reading_value: "4185",
          source_kind: "MANUAL",
          source_evidence:
            "Final reading at the hand-back, recorded in the app",
        },
      ],
      [
        "meter-WATER",
        expect.objectContaining({
          reading_date: "2026-10-12",
          reading_value: "318",
        }),
      ],
    ]);
    const [property, leaseId, inputs] =
      utilityLeaseApi.recordFinalInputs.mock.calls[0] ?? [];
    expect([property, leaseId]).toEqual(["property-1", "lease-U105"]);
    expect(inputs).toMatchObject({
      move_out_event_id: "move-out-1",
      items: [
        {
          meter_id: "meter-ELECTRICITY",
          resolution: "READING",
          reading_id: "saved-meter-ELECTRICITY",
        },
        {
          meter_id: "meter-WATER",
          resolution: "READING",
          reading_id: "saved-meter-WATER",
        },
      ],
    });
    expect(utilityLeaseApi.createFinalInvoice.mock.calls[0]?.[2]).toMatchObject(
      {
        final_input_event_id: inputs?.event_id,
      },
    );
  });

  it("TEST-FE-968 a reading already taken on the hand-back day is used as it is; without the right to issue Invoices only the readings are saved and the step says a Manager issues the Invoice", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const { utilityApi, utilityLeaseApi } = setup([out], {
      page: handedBackPage,
      capabilities: new Set([
        "leases.read",
        "leases.move_out",
        "utility_readings.record",
        "utility.read",
        "invoices.read",
      ]),
      readings: {
        "meter-ELECTRICITY": [
          reading("meter-ELECTRICITY", "2026-10-12", "4190", "taken"),
          reading("meter-ELECTRICITY", "2026-09-24", "4120"),
        ],
      },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record final readings" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      await within(dialog).findByText("4,190 kWh, read on 12/10/2026"),
    ).toBeTruthy();
    expect(
      within(dialog).queryByRole("textbox", { name: /Electricity/ }),
    ).toBeNull();
    fireEvent.change(within(dialog).getByLabelText(/Water/), {
      target: { value: "320" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the readings" }),
    );
    await screen.findByText("Final readings saved.");
    expect(utilityApi.recordReading).toHaveBeenCalledTimes(1);
    expect(utilityLeaseApi.recordFinalInputs.mock.calls[0]?.[2].items).toEqual([
      {
        meter_id: "meter-ELECTRICITY",
        resolution: "READING",
        reading_id: "taken",
      },
      {
        meter_id: "meter-WATER",
        resolution: "READING",
        reading_id: "saved-meter-WATER",
      },
    ]);
    expect(utilityLeaseApi.createFinalInvoice).not.toHaveBeenCalled();
  });

  it("TEST-FE-969 readings saved without an Invoice: Issue the final Utility Invoice sends only the Invoice for those inputs and shows why it was refused; a page whose final Invoice exists shows the step done with the Invoice number, total and link", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const { utilityApi, utilityLeaseApi } = setup([out], {
      page: handedBackPage,
      finalInputs: () => Promise.resolve(inputsPage("inputs-1")),
      readings: {
        "meter-ELECTRICITY": [
          reading("meter-ELECTRICITY", "2026-10-12", "4190"),
        ],
        "meter-WATER": [reading("meter-WATER", "2026-10-12", "320")],
      },
      createInvoice: () =>
        Promise.reject(
          new UtilityLeaseError(422, "UTILITY_EARLIER_READING_NOT_FINALIZED"),
        ),
    });
    expect(
      await screen.findByText(
        "Readings saved for 12/10/2026. The final Utility Invoice is not issued yet.",
      ),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Issue the final Utility Invoice" }),
    );
    const dialog = screen.getByRole("dialog");
    // Only the Invoice is left: the meters are not read again.
    expect(
      within(dialog).getByText(/The final readings of 12\/10\/2026 are saved/),
    ).toBeTruthy();
    expect(utilityApi.loadMeters).not.toHaveBeenCalled();
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Issue the final Utility Invoice",
      }),
    );
    expect(
      await within(dialog).findByText(
        "An earlier month is not billed yet. Bill it in Utilities first, then try again.",
      ),
    ).toBeTruthy();
    expect(utilityApi.recordReading).not.toHaveBeenCalled();
    expect(utilityLeaseApi.recordFinalInputs).not.toHaveBeenCalled();
    expect(utilityLeaseApi.createFinalInvoice.mock.calls[0]?.[2]).toMatchObject(
      {
        final_input_event_id: "inputs-1",
      },
    );
    cleanup();

    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      finalInputs: () => Promise.resolve(inputsPage("inputs-1")),
      invoices: () => Promise.resolve([finalInvoice()]),
    });
    expect(
      await screen.findByText(
        /Read on 12\/10\/2026\. Final Utility Invoice INV-0042 · \$18\.30\./,
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open Invoice" }).getAttribute("href"),
    ).toBe("#/invoices/inv%3Ainvoice-final");
    expect(
      screen.queryByRole("button", {
        name: /final Utility Invoice|final readings/,
      }),
    ).toBeNull();
    expect(screen.getByText("Final readings; INV-0042 issued.")).toBeTruthy();
  });

  it("TEST-FE-970 no answer to the final inputs: Try again records no reading twice and sends the same inputs with the same key", async () => {
    window.location.hash = "#/moveout/lease-U105";
    let fail = true;
    const { utilityApi, utilityLeaseApi } = setup([out], {
      page: handedBackPage,
      recordInputs: (_property, _lease, input) =>
        fail
          ? Promise.reject(new UtilityLeaseError(null, "NETWORK"))
          : Promise.resolve({ event_id: input.event_id }),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record final readings" }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(await within(dialog).findByLabelText(/Electricity/), {
      target: { value: "4185" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Water/), {
      target: { value: "318" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Save and issue the Invoice",
      }),
    );
    await within(dialog).findByText(/No answer came back/);
    fail = false;
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await screen.findByText("Final Utility Invoice INV-0042 issued.");
    expect(utilityApi.recordReading).toHaveBeenCalledTimes(2);
    const [first, second] = utilityLeaseApi.recordFinalInputs.mock.calls;
    expect(second?.[2]).toEqual(first?.[2]);
    expect(second?.[3]).toBe(first?.[3]);
  });

  it("TEST-FE-971 no answer to a reading: Try again sends that reading with the same key and saves no other twice; no answer to the Invoice: Try again sends the same Invoice id and key; a refused reading says not saved", async () => {
    window.location.hash = "#/moveout/lease-U105";
    let readingFails = true;
    let invoiceFails = true;
    const { utilityApi, utilityLeaseApi } = setup([out], {
      page: handedBackPage,
      createInvoice: (_property, _lease, input) =>
        invoiceFails
          ? Promise.reject(new UtilityLeaseError(null, "NETWORK"))
          : Promise.resolve({
              invoice_id: input.invoice_id,
              invoice: { invoice_number: "INV-0043" },
            }),
    });
    utilityApi.recordReading.mockImplementation((meterId, input) =>
      meterId === "meter-WATER" && readingFails
        ? Promise.reject(new UtilityClientError())
        : Promise.resolve(
            reading(
              meterId,
              input.reading_date,
              input.reading_value,
              `saved-${meterId}`,
            ),
          ),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Record final readings" }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(await within(dialog).findByLabelText(/Electricity/), {
      target: { value: "4185" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Water/), {
      target: { value: "318" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Save and issue the Invoice",
      }),
    );
    await within(dialog).findByText(/No answer came back/);
    readingFails = false;
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await within(dialog).findByText(/No answer came back/);
    const calls = utilityApi.recordReading.mock.calls;
    expect(calls.map((call) => call[0])).toEqual([
      "meter-ELECTRICITY",
      "meter-WATER",
      "meter-WATER",
    ]);
    expect(calls[2]?.[1]).toEqual(calls[1]?.[1]);
    expect(calls[2]?.[2]).toBe(calls[1]?.[2]);
    expect(utilityLeaseApi.recordFinalInputs).toHaveBeenCalledTimes(1);
    invoiceFails = false;
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await screen.findByText("Final Utility Invoice INV-0043 issued.");
    const [first, second] = utilityLeaseApi.createFinalInvoice.mock.calls;
    expect(second?.[2]).toEqual(first?.[2]);
    expect(second?.[3]).toBe(first?.[3]);
    expect(utilityLeaseApi.recordFinalInputs).toHaveBeenCalledTimes(1);
    cleanup();

    window.location.hash = "#/moveout/lease-U105";
    const refused = setup([out], { page: handedBackPage });
    refused.utilityApi.recordReading.mockRejectedValue(
      new UtilityClientError(undefined, [], "request-1", 422),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Record final readings" }),
    );
    const again = screen.getByRole("dialog");
    fireEvent.change(await within(again).findByLabelText(/Electricity/), {
      target: { value: "4185" },
    });
    fireEvent.change(within(again).getByLabelText(/Water/), {
      target: { value: "318" },
    });
    fireEvent.click(
      within(again).getByRole("button", { name: "Save and issue the Invoice" }),
    );
    expect(await within(again).findByText(/not saved/i)).toBeTruthy();
    expect(
      within(again).queryByRole("button", { name: "Try again" }),
    ).toBeNull();
  });

  it("TEST-FE-972 only the meters in use on the hand-back day are read; after a corrected hand-back the new final inputs replace the earlier ones; a changed record closes the dialog, warns and reads the page again", async () => {
    const day = "2026-10-12";
    const later = {
      ...meter("WATER"),
      id: "later",
      installed_date: "2026-10-13",
    };
    const gone = {
      ...meter("WATER"),
      id: "gone",
      deactivated_date: "2026-10-11",
    };
    const lastDay = {
      ...meter("WATER"),
      id: "last-day",
      deactivated_date: day,
    };
    expect(
      metersOn([later, gone, lastDay, meter("ELECTRICITY")], day).map(
        (item) => item.id,
      ),
    ).toEqual(["meter-ELECTRICITY", "last-day"]);

    window.location.hash = "#/moveout/lease-U105";
    const earlier = inputsPage("inputs-old");
    const items = earlier.items as EvidenceRecord[];
    items[0] = { ...items[0], move_out_event_id: "move-out-0" };
    let conflict = true;
    const { utilityLeaseApi, leaseApi } = setup([out], {
      page: handedBackPage,
      finalInputs: () => Promise.resolve(earlier),
      recordInputs: (_property, _lease, input) =>
        conflict
          ? Promise.reject(new UtilityLeaseError(409, "CONFLICT"))
          : Promise.resolve({ event_id: input.event_id }),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record final readings" }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(await within(dialog).findByLabelText(/Electricity/), {
      target: { value: "4185" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Water/), {
      target: { value: "318" },
    });
    const reads = leaseApi.get.mock.calls.length;
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Save and issue the Invoice",
      }),
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(utilityLeaseApi.recordFinalInputs.mock.calls[0]?.[2]).toMatchObject({
      move_out_event_id: "move-out-1",
      supersedes_event_id: "inputs-old",
    });
    expect(screen.getByRole("alert").textContent).toMatch(/changed/i);
    await waitFor(() => {
      expect(leaseApi.get.mock.calls.length).toBeGreaterThan(reads);
    });
    conflict = false;
  });

  it("TEST-FE-973 the final Invoice is the one whose line ends at a reading of the current final inputs, never an earlier final Invoice; a same-day reading not checked yet is shown and stops the save", async () => {
    const inputs = currentFinalInputs(inputsPage("inputs-1"), "move-out-1");
    expect(inputs?.items[0]?.reading_id).toBe("final-reading");
    if (inputs === null) return;
    const earlier = {
      ...finalInvoice(),
      id: "invoice-old",
      invoice_date: "2026-10-12",
      lines: finalInvoice().lines.map((line) => ({
        ...line,
        calculation_evidence: {
          billing_kind: "FINAL",
          end_reading_id: "old-reading",
        },
      })),
    };
    expect(finalInvoiceOf([earlier], inputs)).toBeNull();
    expect(finalInvoiceOf([earlier, finalInvoice()], inputs)?.id).toBe(
      "invoice-final",
    );
    expect(
      finalInvoiceOf([{ ...finalInvoice(), status: "VOID" }], inputs),
    ).toBeNull();

    window.location.hash = "#/moveout/lease-U105";
    const unchecked = {
      ...reading("meter-WATER", "2026-10-12", "320", "unchecked"),
      validated: false as const,
      validated_at: null,
      validated_by: null,
    };
    const { utilityApi, utilityLeaseApi } = setup([out], {
      page: handedBackPage,
      readings: {
        "meter-WATER": [unchecked, reading("meter-WATER", "2026-09-24", "310")],
      },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record final readings" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      await within(dialog).findByText(
        "320 m³, read on 12/10/2026, not checked yet",
      ),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/Electricity/), {
      target: { value: "4185" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Save and issue the Invoice",
      }),
    );
    expect(
      within(dialog).getByText(
        /A reading of the hand-back day is not checked yet/,
      ),
    ).toBeTruthy();
    expect(utilityApi.recordReading).not.toHaveBeenCalled();
    expect(utilityLeaseApi.recordFinalInputs).not.toHaveBeenCalled();
  });

  const step4 = async () => {
    const heading = await screen.findByRole("heading", {
      name: "4. Inspection and charges",
    });
    const item = heading.closest("li");
    if (item === null) throw new Error("no step 4");
    return item;
  };

  it("TEST-FE-974 after the hand-back, Record inspection saves the findings with the pet mark, then a Damage charge and its Draft Invoice for each finding with an amount, the finding's id being the charge's id", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const { moveOutApi, invoiceApi } = setup([out], { page: handedBackPage });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record inspection" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("No damage found.")).toBeTruthy();
    const date = within(dialog).getByLabelText(/Inspection date/);
    expect((date as HTMLInputElement).value).toBe(TODAY);
    expect(date.getAttribute("min")).toBe("2026-10-12");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Add finding" }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Add finding" }),
    );
    const described = within(dialog).getAllByLabelText(/What is damaged/);
    fireEvent.change(nth(described, 0), {
      target: { value: "Broken  window   in the bedroom " },
    });
    fireEvent.change(nth(described, 1), {
      target: { value: "Scratched door" },
    });
    fireEvent.click(
      nth(within(dialog).getAllByLabelText(/Caused by the pet/), 1),
    );
    fireEvent.change(nth(within(dialog).getAllByLabelText(/^Charge/), 0), {
      target: { value: "25" },
    });
    fireEvent.change(
      nth(within(dialog).getAllByLabelText(/Evidence \(photo names/), 0),
      { target: { value: "Photos 1-3" } },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save and make the charges" }),
    );
    await screen.findByText("Saved. Draft Invoices made: $25.00.");
    const [sent] = moveOutApi.inspect.mock.calls;
    expect(sent?.[0]).toBe("property-1");
    expect(sent?.[1]).toBe("lease-U105");
    const source = sent?.[2];
    expect(source).toMatchObject({
      expected_lease_version: 3,
      inspection_date: TODAY,
      result_text: "2 damage finding(s).",
      reason: "Move-out inspection after the hand-back",
      supersedes_inspection_id: null,
    });
    expect(
      source?.findings.map((finding) => [
        finding.description,
        finding.pet_related,
      ]),
    ).toEqual([
      ["Broken window in the bedroom", false],
      ["Scratched door", true],
    ]);
    expect(invoiceApi.recordOneTimeCharge).toHaveBeenCalledTimes(1);
    const [charge] = invoiceApi.recordOneTimeCharge.mock.calls;
    const finding = source?.findings[0]?.finding_id;
    expect(charge?.[1]).toEqual({
      charge_id: finding,
      category: "DAMAGE_CHARGES",
      customer_id: "customer-U105",
      lease_id: "lease-U105",
      inspection_damage_finding_id: finding,
      description: "Damage: Broken window in the bedroom",
      amount: { currency: "USD", minor_units: 2500 },
      reason: `Damage found at the move-out inspection on ${TODAY}`,
      evidence_reference: "Photos 1-3",
    });
    expect(invoiceApi.create.mock.calls[0]?.[1]).toBe(finding);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(moveOutApi.inspections.mock.calls.length).toBeGreaterThan(1);
    cleanup();

    // A charge whose Draft is refused as already made: saved, with a warning to check.
    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      createDraft: () =>
        Promise.reject(new InvoiceClientError(409, "CONFLICT", false)),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record inspection" }),
    );
    const again = screen.getByRole("dialog");
    fireEvent.click(within(again).getByRole("button", { name: "Add finding" }));
    fireEvent.change(within(again).getByLabelText(/What is damaged/), {
      target: { value: "Broken window" },
    });
    fireEvent.change(within(again).getByLabelText(/^Charge/), {
      target: { value: "25" },
    });
    fireEvent.change(within(again).getByLabelText(/Evidence \(photo/), {
      target: { value: "Photo 1" },
    });
    fireEvent.click(
      within(again).getByRole("button", { name: "Save and make the charges" }),
    );
    await screen.findByText(
      "Saved, but a charge got no new Draft, or its Draft bills an amount recorded before. Check the Drafts on the Invoices page.",
    );
  });

  it("TEST-FE-975 the inspection dialog refuses a day before the hand-back, an empty finding, and an amount without evidence, marking the box; without the right to make Damage charges it asks for no amounts", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const { moveOutApi } = setup([out], { page: handedBackPage });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record inspection" }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Inspection date/), {
      target: { value: "2026-10-11" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the inspection" }),
    );
    expect(
      within(dialog).getByText("Choose a day from the hand-back day to today."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/Inspection date/), {
      target: { value: "2026-10-12" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Add finding" }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the inspection" }),
    );
    expect(
      within(dialog).getByText("Describe each finding, or remove it."),
    ).toBeTruthy();
    expect(
      within(dialog)
        .getByLabelText(/What is damaged/)
        .getAttribute("aria-invalid"),
    ).toBe("true");
    fireEvent.change(within(dialog).getByLabelText(/What is damaged/), {
      target: { value: "Broken window" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Charge/), {
      target: { value: "25" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save and make the charges" }),
    );
    expect(
      within(dialog).getByText(
        "Give a description, an amount above zero and the evidence.",
      ),
    ).toBeTruthy();
    expect(
      within(dialog)
        .getByLabelText(/Evidence \(photo names/)
        .getAttribute("aria-invalid"),
    ).toBe("true");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Remove finding 1" }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the inspection" }),
    );
    await screen.findByText("Inspection saved.");
    expect(moveOutApi.inspect.mock.calls[0]?.[2]).toMatchObject({
      inspection_date: "2026-10-12",
      result_text: "No damage found.",
      findings: [],
    });
    cleanup();

    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      capabilities: new Set([
        "leases.read",
        "leases.inspect",
        "invoices.read",
        "deposits.read",
      ]),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record inspection" }),
    );
    const plain = screen.getByRole("dialog");
    fireEvent.click(within(plain).getByRole("button", { name: "Add finding" }));
    expect(within(plain).queryByLabelText(/^Charge/)).toBeNull();
    expect(
      within(plain).getByText(
        "A finding alone charges nothing. A person allowed to make Damage charges adds the amounts.",
      ),
    ).toBeTruthy();
  });

  it("TEST-FE-976 a recorded inspection shows each finding with its charge: a Draft with its link, an issued Invoice by number, a Charge button for the rest; the cleaning charge; charges from a replaced inspection; with a charge the inspection is no longer corrected", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const old = inspectionOf(
      "inspection-old",
      [["finding-old", "Old stain", false]],
      {
        current_effect: "SUPERSEDED",
      },
    );
    const current = inspectionOf(
      "inspection-new",
      [
        ["finding-1", "Broken window", false],
        ["finding-2", "Chewed door", true],
        ["finding-3", "Loose tile", false],
      ],
      {
        supersedes_inspection_id: "inspection-old",
        reason: "Missed a room",
        completed_at: "2026-10-14T04:00:00Z",
      },
    );
    setup([out], {
      page: handedBackPage,
      inspections: [old, current],
      invoices: () =>
        Promise.resolve([
          chargeInvoice("finding-1", "DAMAGE_CHARGES", 2500, "DRAFT"),
          chargeInvoice(
            "finding-2",
            "DAMAGE_CHARGES",
            4000,
            "UNPAID",
            "Damage: Chewed door",
          ),
          chargeInvoice(
            "finding-old",
            "DAMAGE_CHARGES",
            1000,
            "UNPAID",
            "Damage: Old stain",
          ),
          chargeInvoice(
            "finding-3",
            "DAMAGE_CHARGES",
            900,
            "VOID",
            "Damage: Loose tile",
          ),
          chargeInvoice("lease-U105", "MISCELLANEOUS_CHARGES", 3500, "UNPAID"),
        ]),
    });
    const step = await step4();
    await within(step).findByText("Inspected on 13/10/2026.");
    const items = within(step)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(items).toEqual([
      "Broken window$25.00 Draft Open",
      "Chewed doorpet damage$40.00 INV-finding-2",
      "Loose tile$9.00 Void INV-finding-3",
      "Unit cleaning charge$35.00 INV-lease-U105",
      "Damage: Old stain$10.00 INV-finding-old",
    ]);
    expect(
      within(step).getByRole("link", { name: "Open" }).getAttribute("href"),
    ).toBe("#/invoices/inv%3Ainvoice-finding-1");
    expect(
      within(step).getByText("Charges from an earlier inspection"),
    ).toBeTruthy();
    expect(
      within(step).getByText(
        "A Draft is not owed yet. A Manager issues it on the Invoices page, due in 7 days.",
      ),
    ).toBeTruthy();
    expect(
      within(step).getByText(
        "A finding is charged, so this inspection is kept as it is. New damage found later is a correction after closure.",
      ),
    ).toBeTruthy();
    expect(
      within(step).queryByRole("button", { name: "Correct inspection" }),
    ).toBeNull();
    expect(
      within(step).queryByRole("button", { name: "Add cleaning charge" }),
    ).toBeNull();
    expect(within(step).getByText("Now")).toBeTruthy();
    expect(
      screen.getByText("Inspection corrected: 3 finding(s)."),
    ).toBeTruthy();
    expect(screen.getByText("Missed a room")).toBeTruthy();
    expect(screen.getByText("Move-out inspection: 1 finding(s).")).toBeTruthy();
  });

  it("TEST-FE-977 Charge on a finding records its Damage charge and Draft; a charge recorded before (answered 409) still gets its Draft and a warning when that Draft bills another amount; a Draft already made says so; no answer offers Try again with the same key", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const current = inspectionOf("inspection-1", [
      ["finding-1", "Broken window", false],
    ]);
    let attempt = 0;
    const { invoiceApi } = setup([out], {
      page: handedBackPage,
      inspections: [current],
      recordCharge: () => {
        attempt += 1;
        return attempt === 1
          ? Promise.reject(new InvoiceClientError(null, "NETWORK", true))
          : Promise.reject(new InvoiceClientError(409, "CONFLICT", false));
      },
    });
    const step = await step4();
    fireEvent.click(
      await within(step).findByRole("button", { name: "Charge" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Broken window")).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Make the charge" }),
    );
    expect(
      within(dialog).getByText(
        "Give a description, an amount above zero and the evidence.",
      ),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Charge/), {
      target: { value: "25.50" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Evidence/), {
      target: { value: "Photo 4" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Make the charge" }),
    );
    await within(dialog).findByText(/No answer came back/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await screen.findByText(
      "This finding was charged before at another amount. Its Draft Invoice bills $25.00: correct it on the Invoices page if needed.",
    );
    expect(screen.queryByText("Draft Invoice made for $25.00.")).toBeNull();
    const [first, second] = invoiceApi.recordOneTimeCharge.mock.calls;
    expect(second?.[1]).toEqual(first?.[1]);
    expect(second?.[2]).toBe(first?.[2]);
    expect(first?.[1]).toMatchObject({
      charge_id: "finding-1",
      inspection_damage_finding_id: "finding-1",
      amount: { currency: "USD", minor_units: 2550 },
      reason: "Damage found at the move-out inspection on 2026-10-13",
      evidence_reference: "Photo 4",
    });
    expect(invoiceApi.create.mock.calls.map((call) => call[1])).toEqual([
      "finding-1",
    ]);
    cleanup();

    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      inspections: [current],
      createDraft: () =>
        Promise.reject(new InvoiceClientError(409, "CONFLICT", false)),
    });
    fireEvent.click(
      await within(await step4()).findByRole("button", { name: "Charge" }),
    );
    const again = screen.getByRole("dialog");
    fireEvent.change(within(again).getByLabelText(/^Charge/), {
      target: { value: "25" },
    });
    fireEvent.change(within(again).getByLabelText(/Evidence/), {
      target: { value: "Photo 4" },
    });
    fireEvent.click(
      within(again).getByRole("button", { name: "Make the charge" }),
    );
    await screen.findByText(
      "No new Draft was made: the charge may already have its Invoice. The page was read again; check the Invoices page.",
    );
    cleanup();

    // Recorded before at the same amount: the Draft is made and nothing is wrong.
    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      inspections: [current],
      recordCharge: () =>
        Promise.reject(new InvoiceClientError(409, "CONFLICT", false)),
    });
    fireEvent.click(
      await within(await step4()).findByRole("button", { name: "Charge" }),
    );
    const same = screen.getByRole("dialog");
    fireEvent.change(within(same).getByLabelText(/^Charge/), {
      target: { value: "25" },
    });
    fireEvent.change(within(same).getByLabelText(/Evidence/), {
      target: { value: "Photo 4" },
    });
    fireEvent.click(
      within(same).getByRole("button", { name: "Make the charge" }),
    );
    await screen.findByText("Draft Invoice made for $25.00.");
  });

  it("TEST-FE-978 Add cleaning charge records the Unit's rate with the Lease's id and makes its Draft, also when that id was recorded before; a refusal names why, a server failure offers Try again; no rate, a zero rate or a hidden rate say so", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const current = inspectionOf("inspection-1", []);
    const { settlementApi, invoiceApi } = setup([out], {
      page: handedBackPage,
      inspections: [current],
      createDraft: (_property, obligation) =>
        Promise.resolve(
          chargeInvoice(obligation, "MISCELLANEOUS_CHARGES", 3500, "DRAFT"),
        ),
    });
    const step = await step4();
    await within(step).findByText("This Unit's cleaning rate: $35.00.");
    expect(settlementApi.cleaningRate).toHaveBeenCalledWith(
      "property-1",
      "unit-U105",
    );
    fireEvent.click(
      within(step).getByRole("button", { name: "Add cleaning charge" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(
        "Add the cleaning charge of $35.00 for U105? It makes a Draft Invoice for Tenant U105.",
      ),
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Add cleaning charge" }),
    );
    await screen.findByText("Draft Invoice made for $35.00.");
    expect(settlementApi.chargeCleaning).toHaveBeenCalledWith(
      "property-1",
      "lease-U105",
      { charge_id: "lease-U105", expected_rate_id: "rate-1" },
    );
    expect(invoiceApi.create.mock.calls[0]?.[1]).toBe("lease-U105");
    cleanup();

    window.location.hash = "#/moveout/lease-U105";
    const refused = setup([out], {
      page: handedBackPage,
      inspections: [current],
      chargeCleaning: () =>
        Promise.reject(
          new SettlementRequestError(
            409,
            "CLEANING_RATE_CHANGED",
            "The cleaning rate changed.",
          ),
        ),
    });
    fireEvent.click(
      await within(await step4()).findByRole("button", {
        name: "Add cleaning charge",
      }),
    );
    const box = screen.getByRole("dialog");
    fireEvent.click(
      within(box).getByRole("button", { name: "Add cleaning charge" }),
    );
    await within(box).findByText(
      "The cleaning rate changed meanwhile. Close, check the new rate and add it again.",
    );
    expect(refused.invoiceApi.create).not.toHaveBeenCalled();
    cleanup();

    // Recorded before under the Lease's id by another person: its Draft is still made.
    window.location.hash = "#/moveout/lease-U105";
    const before = setup([out], {
      page: handedBackPage,
      inspections: [current],
      chargeCleaning: () =>
        Promise.reject(
          new SettlementRequestError(409, "IDEMPOTENCY_KEY_REUSED", "Reused."),
        ),
      createDraft: (_property, obligation) =>
        Promise.resolve(
          chargeInvoice(obligation, "MISCELLANEOUS_CHARGES", 3500, "DRAFT"),
        ),
    });
    fireEvent.click(
      await within(await step4()).findByRole("button", {
        name: "Add cleaning charge",
      }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Add cleaning charge",
      }),
    );
    await screen.findByText("Draft Invoice made for $35.00.");
    expect(before.invoiceApi.create.mock.calls[0]?.[1]).toBe("lease-U105");
    cleanup();

    // A server failure may have saved it: not "not saved".
    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      inspections: [current],
      chargeCleaning: () =>
        Promise.reject(new SettlementRequestError(500, null, "Failed.")),
    });
    fireEvent.click(
      await within(await step4()).findByRole("button", {
        name: "Add cleaning charge",
      }),
    );
    const failed = screen.getByRole("dialog");
    fireEvent.click(
      within(failed).getByRole("button", { name: "Add cleaning charge" }),
    );
    await within(failed).findByText(/No answer came back/);
    expect(
      within(failed).getByRole("button", { name: "Try again" }),
    ).toBeTruthy();
    cleanup();

    for (const [rate, words] of [
      [
        { rate: null },
        "This Unit has no cleaning rate yet. Set it in Settings, then add the charge.",
      ],
      [
        { rate: { id: "rate-0", rate_usd_cents: 0 } },
        "This Unit's cleaning rate is zero: no cleaning charge.",
      ],
    ] as const) {
      window.location.hash = "#/moveout/lease-U105";
      setup([out], {
        page: handedBackPage,
        inspections: [current],
        cleaningRate: () => Promise.resolve(rate),
      });
      const shown = await step4();
      await within(shown).findByText(words);
      expect(
        within(shown).queryByRole("button", { name: "Add cleaning charge" }),
      ).toBeNull();
      cleanup();
    }

    window.location.hash = "#/moveout/lease-U105";
    const hidden = setup([out], {
      page: handedBackPage,
      inspections: [current],
      capabilities: new Set(["leases.read", "invoices.read"]),
    });
    await within(await step4()).findByText(
      "Your account cannot see the cleaning rate.",
    );
    expect(hidden.settlementApi.cleaningRate).not.toHaveBeenCalled();
  });

  it("TEST-FE-979 Correct inspection, offered while no finding is charged, fills the form with the findings, asks why, and sends a new inspection that replaces the old one with new finding ids; a zero cleaning rate and no Drafts mark the step done", async () => {
    window.location.hash = "#/moveout/lease-U105";
    const current = inspectionOf("inspection-1", [
      ["finding-1", "Broken window", false],
      ["finding-2", "Chewed door", true],
    ]);
    const { moveOutApi } = setup([out], {
      page: handedBackPage,
      inspections: [current],
      cleaningRate: () =>
        Promise.resolve({ rate: { id: "rate-0", rate_usd_cents: 0 } }),
    });
    const step = await step4();
    await within(step).findByText("Inspected on 13/10/2026.");
    expect(within(step).getByText("Done")).toBeTruthy();
    fireEvent.click(
      within(step).getByRole("button", { name: "Correct inspection" }),
    );
    const dialog = screen.getByRole("dialog");
    const described = within(dialog).getAllByLabelText(/What is damaged/);
    expect(described.map((item) => (item as HTMLInputElement).value)).toEqual([
      "Broken window",
      "Chewed door",
    ]);
    const pets = within(dialog).getAllByLabelText(/Caused by the pet/);
    expect(pets.map((item) => (item as HTMLInputElement).checked)).toEqual([
      false,
      true,
    ]);
    expect(
      within(dialog).getByLabelText<HTMLTextAreaElement>("Notes").value,
    ).toBe("Checked with the tenant");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Remove finding 1" }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save the inspection" }),
    );
    expect(
      within(dialog).getByText("Say why the inspection is corrected."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/Why it is corrected/), {
      target: { value: "The window was broken before the Lease" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /Save/ }));
    await screen.findByText("Inspection saved.");
    const source = moveOutApi.inspect.mock.calls[0]?.[2];
    expect(source).toMatchObject({
      supersedes_inspection_id: "inspection-1",
      reason: "The window was broken before the Lease",
      result_text: "Checked with the tenant",
    });
    expect(source?.findings).toHaveLength(1);
    expect(source?.findings[0]).toMatchObject({
      description: "Chewed door",
      pet_related: true,
    });
    expect(["finding-1", "finding-2"]).not.toContain(
      source?.findings[0]?.finding_id,
    );
  });

  it("TEST-FE-980 without leases.inspect, Damage-charge or Invoice rights the step offers no buttons and says why; without invoices.read the charges are not shown; two inspections in force are named", async () => {
    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      capabilities: new Set(["leases.read", "deposits.read"]),
    });
    const step = await step4();
    await within(step).findByText("Your account cannot record the inspection.");
    expect(
      within(step).getByText(
        "Your account cannot see Invoices, so the charges are not shown.",
      ),
    ).toBeTruthy();
    expect(within(step).queryByRole("button")).toBeNull();
    cleanup();

    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      inspections: [
        inspectionOf("inspection-1", [["finding-1", "Broken window", false]]),
      ],
      capabilities: new Set(["leases.read", "invoices.read"]),
    });
    const shown = await step4();
    await within(shown).findByText("no charge");
    expect(within(shown).queryByRole("button")).toBeNull();
    cleanup();

    window.location.hash = "#/moveout/lease-U105";
    setup([out], {
      page: handedBackPage,
      inspections: [
        inspectionOf("inspection-0", []),
        inspectionOf("inspection-1", [["finding-1", "Broken window", false]]),
      ],
    });
    await within(await step4()).findByText(
      "More than one inspection is in force for this move-out; the newest is shown. Check the History and the Invoices page.",
    );
  });

  it("TEST-FE-981 no answer to the inspection: the form is held and Try again sends the same inspection with the same key; a charge that fails after the inspection is saved says so and Try again sends only the charge", async () => {
    window.location.hash = "#/moveout/lease-U105";
    let inspectFails = true;
    let chargeFails = true;
    const { moveOutApi, invoiceApi } = setup([out], {
      page: handedBackPage,
      inspect: (_property, _lease, source) =>
        inspectFails
          ? Promise.reject(new MoveOutUnavailableError())
          : Promise.resolve(savedInspection(source)),
      recordCharge: (_property, input) =>
        chargeFails
          ? Promise.reject(new InvoiceClientError(null, "NETWORK", true))
          : Promise.resolve({
              obligation_id: input.charge_id,
              ...input,
              evidence: {},
            }),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Record inspection" }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Add finding" }),
    );
    fireEvent.change(within(dialog).getByLabelText(/What is damaged/), {
      target: { value: "Broken window" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Charge/), {
      target: { value: "25" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Evidence \(photo/), {
      target: { value: "Photo 1" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save and make the charges" }),
    );
    await within(dialog).findByText(/No answer came back/);
    expect(
      within(dialog).getByLabelText<HTMLInputElement>(/What is damaged/)
        .disabled,
    ).toBe(true);
    expect(
      within(dialog).queryByRole("button", { name: "Add finding" }),
    ).toBeNull();
    inspectFails = false;
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await within(dialog).findByText(
      "The inspection is saved, but a charge was not made. Press Try again; nothing is saved twice.",
    );
    const [first, second] = moveOutApi.inspect.mock.calls;
    expect(second?.[2]).toEqual(first?.[2]);
    expect(second?.[3]).toBe(first?.[3]);
    chargeFails = false;
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await screen.findByText("Saved. Draft Invoices made: $25.00.");
    expect(moveOutApi.inspect).toHaveBeenCalledTimes(2);
    const charges = invoiceApi.recordOneTimeCharge.mock.calls;
    expect(charges).toHaveLength(2);
    expect(charges[1]?.[2]).toBe(charges[0]?.[2]);
  });

  it("TEST-FE-982 the step reads the inspections still in force and the Invoice billing each charge source, a VOID one only when no other bills it, and finds the cleaning charge by its source or its fixed text", () => {
    const first = inspectionOf("a", []);
    const second = inspectionOf("b", [], { supersedes_inspection_id: "a" });
    expect(currentInspection([first, second])?.id).toBe("b");
    expect(
      currentInspection([{ ...first, current_effect: "SUPERSEDED" }]),
    ).toBeNull();
    expect(currentInspection([])).toBeNull();
    const draft = chargeInvoice("f1", "DAMAGE_CHARGES", 100, "DRAFT");
    const voided = chargeInvoice("f2", "DAMAGE_CHARGES", 100, "VOID");
    const billed = billedSources([draft, voided, finalInvoice()]);
    expect([...billed.keys()]).toEqual(["f1", "f2"]);
    expect(
      billedSources([
        chargeInvoice("f1", "DAMAGE_CHARGES", 100, "VOID"),
        draft,
      ]).get("f1")?.status,
    ).toBe("DRAFT");
    expect(currentInspections([first, inspectionOf("c", [])])).toHaveLength(2);
    expect(
      cleaningInvoice(
        [chargeInvoice("other-id", "MISCELLANEOUS_CHARGES", 3500, "UNPAID")],
        "lease-U105",
      )?.id,
    ).toBe("invoice-other-id");
    expect(
      cleaningInvoice(
        [
          chargeInvoice(
            "x",
            "MISCELLANEOUS_CHARGES",
            100,
            "UNPAID",
            "Late key",
          ),
        ],
        "lease-U105",
      ),
    ).toBeNull();
    expect(
      cleaningInvoice(
        [
          chargeInvoice("lease-U105", "MISCELLANEOUS_CHARGES", 100, "VOID"),
          chargeInvoice("other", "MISCELLANEOUS_CHARGES", 3500, "UNPAID"),
        ],
        "lease-U105",
      )?.status,
    ).toBe("UNPAID");
  });
});
