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
  SettlementUnavailableError,
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
import { readPreview, settlementOf as settlementOfLease } from "./settlement";

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

function settlementOf(
  leaseId: string,
  change: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id: `fs-${leaseId}`,
    property_id: "property-1",
    lease_id: leaseId,
    started_at: "2026-10-20T03:00:00Z",
    closed: false,
    closed_at: null,
    closing_balance_due_usd_cents: null,
    pending_draft: false,
    ...change,
  };
}

function previewOf(
  settlementId: string,
  change: Record<string, unknown> = {},
): Record<string, unknown> {
  const leaseId = settlementId.replace(/^fs-/, "");
  return {
    settlement: settlementOf(leaseId),
    lease: { lease_id: leaseId },
    customers: [
      {
        customer_id: "customer-1",
        primary_tenant: true,
        invoice_lines: [
          {
            invoice_id: "inv-rent",
            invoice_line_id: "line-rent",
            customer_id: "customer-1",
            category: "RENT",
            description: "Rent October 2026",
            due_date: "2026-10-05",
            outstanding_usd_cents: 30000,
            pet_damage: false,
          },
        ],
        late_payment_charges: [
          {
            late_payment_charge_id: "late-1",
            source_invoice_id: "inv-rent",
            customer_id: "customer-1",
            remaining_usd_cents: 1500,
          },
        ],
        open_total_usd_cents: 31500,
        credits: [
          { customer_credit_id: "credit-1", available_usd_cents: 2000 },
        ],
        credit_available_usd_cents: 2000,
        credit_may_use_usd_cents: 2000,
      },
    ],
    deposits: [
      {
        deposit_id: "dep-sec",
        deposit_type: "SECURITY",
        customer_id: "customer-1",
        held_usd_cents: 50000,
        path: "DL_032",
        ground: null,
        forfeiture: "NONE",
      },
    ],
    steps: [
      { step: 1, kind: "OBLIGATIONS_FINAL", open_total_usd_cents: 31500 },
      {
        step: 3,
        kind: "PET_DEPOSIT_PET_DAMAGE",
        pet_damage_open_usd_cents: 0,
        deposits: [],
      },
      {
        step: 5,
        kind: "PET_DEPOSIT_REMAINDER",
        chosen_by: "CUSTOMER_OR_STAFF_WITH_REASON",
        deposits: [],
      },
    ],
    open_total_usd_cents: 31500,
    blocking_issues: [],
    information: [],
    ready: true,
    previewed_at: "2026-10-25T03:00:00Z",
    ...change,
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
    settlements?: SettlementApi["settlements"];
    startSettlement?: SettlementApi["startSettlement"];
    settlementPreview?: SettlementApi["settlementPreview"];
    settlementDraft?: SettlementApi["settlementDraft"];
    refundMethods?: SettlementApi["refundMethods"];
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
    settlements: vi.fn<SettlementApi["settlements"]>(
      options.settlements ?? (() => Promise.resolve([])),
    ),
    startSettlement: vi.fn<SettlementApi["startSettlement"]>(
      options.startSettlement ??
        ((_property, lease) =>
          Promise.resolve(settlementOf(lease, { created: true }))),
    ),
    settlementPreview: vi.fn<SettlementApi["settlementPreview"]>(
      options.settlementPreview ??
        ((_property, id) => Promise.resolve(previewOf(id))),
    ),
    refundMethods: vi.fn<SettlementApi["refundMethods"]>(
      options.refundMethods ??
        (() =>
          Promise.resolve([
            {
              id: "m-aba",
              code: "ABA",
              display_name: "ABA transfer",
              active: true,
            },
            { id: "m-cash", code: "CASH", display_name: "Cash", active: true },
            { id: "m-wing", code: "WING", display_name: "Wing", active: false },
          ])),
    ),
    settlementDraft: vi.fn<SettlementApi["settlementDraft"]>(
      options.settlementDraft ??
        ((property, settlement, form) =>
          Promise.resolve({
            draft_id: "draft-1",
            property_id: property,
            kind: "FINAL_SETTLEMENT",
            prepare_capability: "final_settlements.prepare",
            payload: { final_settlement_id: settlement, steps: form.steps },
            reason: form.reason,
            prepared_at: "2026-10-25T03:00:00Z",
            prepared_by: "actor-1",
            state: "PENDING",
            decision: null,
          })),
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

  it("TEST-FE-985 the list reads the Final Settlements without starting one: a draft waiting for a Manager comes first and a closed one last, each with its card; without the Settlement rights the list keeps the earlier steps", async () => {
    const closedLease = lease("U107", {
      status: "TERMINATED",
      actual_termination_date: "2026-09-30",
      occupancies: [],
    });
    const { settlementApi } = setup([out, neverIn, closedLease], {
      settlements: () =>
        Promise.resolve([
          settlementOf("lease-U106", { pending_draft: true }),
          settlementOf("lease-U107", {
            closed: true,
            closed_at: "2026-10-01T03:00:00Z",
          }),
        ]),
    });
    await screen.findByRole("table");
    await waitFor(() => {
      expect(rows().map((row) => row[0])).toEqual(["U106", "U105", "U107"]);
    });
    expect(settlementApi.settlements).toHaveBeenCalledWith("property-1");
    expect(settlementApi.startSettlement).not.toHaveBeenCalled();
    expect(rows()[0]?.[4]).toBe("Waiting for a ManagerA Manager confirms it");
    expect(rows()[2]?.[4]).toBe("ClosedNothing left to do");
    fireEvent.click(
      screen.getByRole("button", { name: /Waiting for a Manager/ }),
    );
    expect(rows().map((row) => row[0])).toEqual(["U106"]);
    fireEvent.click(screen.getByRole("button", { name: /^Closed/ }));
    expect(rows().map((row) => row[0])).toEqual(["U107"]);
    cleanup();

    // A Settlement read that fails keeps the list.
    setup([out, neverIn], {
      settlements: () => Promise.reject(new SettlementUnavailableError()),
    });
    await screen.findByRole("table");
    await waitFor(() => {
      expect(rows().map((row) => row[0])).toEqual(["U105", "U106"]);
    });
    expect(
      await screen.findByText(
        "The Final Settlements could not be read, so Waiting for a Manager and Closed are not shown.",
      ),
    ).toBeTruthy();
    cleanup();

    const staff = setup([out, neverIn], {
      capabilities: new Set(["leases.read", "deposits.read"]),
    });
    await screen.findByRole("table");
    expect(staff.settlementApi.settlements).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: /Waiting for a Manager/ }),
    ).toBeNull();
    expect(rows().map((row) => row[0])).toEqual(["U105", "U106"]);
  });

  it("TEST-FE-986 a terminated Lease nobody moved into: Start Final Settlement opens it with a key, then the statement shows the open Invoices and charges, the Customer's own Credit, the Security Deposit and that it is ready", async () => {
    window.location.hash = "#/moveout/lease-U106";
    let started = false;
    const { settlementApi } = setup([neverIn], {
      settlements: () =>
        Promise.resolve(started ? [settlementOf("lease-U106")] : []),
      startSettlement: (_property, leaseId) => {
        started = true;
        return Promise.resolve(settlementOf(leaseId, { created: true }));
      },
    });
    expect(
      await screen.findByText(
        "Prepare the statement. Staff prepare the draft; a Manager confirms and closes it.",
      ),
    ).toBeTruthy();
    expect(settlementApi.settlements).toHaveBeenCalledWith(
      "property-1",
      "lease-U106",
    );
    expect(settlementApi.settlementPreview).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Start Final Settlement" }),
    );
    expect(await screen.findByText("Final Settlement started.")).toBeTruthy();
    const [property, leaseId, key] =
      settlementApi.startSettlement.mock.calls[0] ?? [];
    expect([property, leaseId]).toEqual(["property-1", "lease-U106"]);
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByText("Statement")).toBeTruthy();
    expect(settlementApi.settlementPreview).toHaveBeenCalledWith(
      "property-1",
      "fs-lease-U106",
    );
    expect(screen.getByText("Started on 20/10/2026 10:00.")).toBeTruthy();
    expect(screen.getByText("$315.00")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Rent October 2026" }),
    ).toBeTruthy();
    expect(screen.getByText("Due 05/10/2026")).toBeTruthy();
    expect(screen.getByText("Late-payment charge")).toBeTruthy();
    expect(screen.getByText("Up to $20.00")).toBeTruthy();
    // The statement and the Deposits card.
    expect(screen.getAllByText("$500.00 held")).toHaveLength(2);
    expect(
      screen.getByText("Pays all Lease debt, oldest Due Date first."),
    ).toBeTruthy();
    expect(screen.getByText("Ready: the draft can be prepared.")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Start Final Settlement" }),
    ).toBeNull();
  });

  it("TEST-FE-987 the step waits until the Unit is handed back; a person who may only approve sees it but cannot start it; a person with neither right is told so; a refused start says why and no answer offers Try again with the same key", async () => {
    window.location.hash = "#/moveout/lease-U104";
    const still = setup([terminated]);
    expect(
      await screen.findByText(
        "After the Lease ends and the Unit is handed back.",
      ),
    ).toBeTruthy();
    expect(still.settlementApi.settlements).toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Start Final Settlement" }),
    ).toBeNull();
    cleanup();

    window.location.hash = "#/moveout/lease-U106";
    setup([neverIn], {
      capabilities: new Set(["leases.read", "financial.approve"]),
    });
    expect(
      await screen.findByText(
        "A person with the Final Settlement right starts it.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Start Final Settlement" }),
    ).toBeNull();
    cleanup();

    window.location.hash = "#/moveout/lease-U106";
    const none = setup([neverIn], {
      capabilities: new Set(["leases.read"]),
    });
    expect(
      await screen.findByText("You may not see the Final Settlement."),
    ).toBeTruthy();
    expect(none.settlementApi.settlements).not.toHaveBeenCalled();
    cleanup();

    window.location.hash = "#/moveout/lease-U106";
    let calls = 0;
    const { settlementApi } = setup([neverIn], {
      startSettlement: () => {
        calls += 1;
        return Promise.reject(
          calls === 1
            ? new SettlementUnavailableError()
            : new SettlementRequestError(
                409,
                "FINAL_SETTLEMENT_LEASE_NOT_TERMINATED",
                "The Lease is not terminated",
              ),
        );
      },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Start Final Settlement" }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText(
        "The Final Settlement could not be started. Read the page again: the Lease may not be terminated yet.",
      ),
    ).toBeTruthy();
    const keys = settlementApi.startSettlement.mock.calls.map(
      (call) => call[2],
    );
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("TEST-FE-988 an open Settlement names what blocks it in plain words, once each; a kept Security Deposit shows as kept, never as a payment; a draft waiting for a Manager is named with a link for a person who may approve", async () => {
    window.location.hash = "#/moveout/lease-U106";
    setup([neverIn], {
      settlements: () =>
        Promise.resolve([settlementOf("lease-U106", { pending_draft: true })]),
      settlementPreview: (_property, id) =>
        Promise.resolve(
          previewOf(id, {
            ready: false,
            blocking_issues: [
              {
                code: "FINAL_UTILITY_NOT_ISSUED",
                reason: "MOVE_OUT_NOT_RECORDED",
              },
              { code: "INVOICE_DRAFT_NOT_ISSUED", invoice_id: "inv-1" },
              { code: "INVOICE_DRAFT_NOT_ISSUED", invoice_id: "inv-2" },
              { code: "PENDING_DRAFT" },
              { code: "SOMETHING_NEW" },
            ],
            deposits: [
              {
                deposit_id: "dep-sec",
                deposit_type: "SECURITY",
                customer_id: "customer-1",
                held_usd_cents: 50000,
                path: "KEPT",
              },
              {
                deposit_id: "dep-pet",
                deposit_type: "PET",
                customer_id: "customer-1",
                held_usd_cents: 20000,
                path: "DL_032",
              },
            ],
            information: [
              {
                code: "VOIDED_CHARGE_NOT_BILLED_AGAIN",
                amount_usd_cents: 2500,
              },
            ],
          }),
        ),
    });
    expect(await screen.findByText("Not ready yet. First:")).toBeTruthy();
    const blocked = screen.getByText("Not ready yet. First:").parentElement;
    if (blocked === null) throw new Error("no notice");
    expect(
      within(blocked)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Issue the final Utility Invoice (step 3).",
      "Issue or remove the draft Invoices of the Lease.",
      "Wait for the draft that waits for a Manager.",
      "Something else blocks it. Read the page again later.",
    ]);
    expect(screen.getByText("Security Deposit kept")).toBeTruthy();
    expect(
      screen.getByText("Kept for the termination. Not used for the charges."),
    ).toBeTruthy();
    expect(screen.getByText("Pet Deposit for pet damage")).toBeTruthy();
    expect(
      screen.getByText(
        "When the Customer asks for it, or Staff with a reason, after the Security Deposit is used up.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("A voided charge is not billed again: $25.00."),
    ).toBeTruthy();
    expect(screen.getByText("A draft waits for a Manager.")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open Waiting for approval" })
        .getAttribute("href"),
    ).toBe("#/approvals");
    cleanup();

    // Review round 1: the preview does not count this Settlement's own waiting draft, so it may
    // say ready; the page then does not offer to prepare another.
    window.location.hash = "#/moveout/lease-U106";
    setup([neverIn], {
      settlements: () =>
        Promise.resolve([settlementOf("lease-U106", { pending_draft: true })]),
    });
    expect(
      await screen.findByText("A draft waits for a Manager."),
    ).toBeTruthy();
    expect(await screen.findByText("Statement")).toBeTruthy();
    expect(screen.queryByText("Ready: the draft can be prepared.")).toBeNull();
  });

  it("TEST-FE-989 a closed Settlement shows when it closed and what stays owed, reads no preview and marks the step done; an unreadable preview says so", async () => {
    window.location.hash = "#/moveout/lease-U106";
    const { settlementApi } = setup([neverIn], {
      settlements: () =>
        Promise.resolve([
          settlementOf("lease-U106", {
            closed: true,
            closed_at: "2026-10-22T04:00:00Z",
            closing_balance_due_usd_cents: 4200,
          }),
        ]),
    });
    expect(await screen.findByText("Closed on 22/10/2026 11:00.")).toBeTruthy();
    expect(
      screen.getByText(
        "$42.00 stays owed on the Customer Ledger. No write-off in V1.",
      ),
    ).toBeTruthy();
    expect(settlementApi.settlementPreview).not.toHaveBeenCalled();
    const step = screen.getByRole("heading", { name: "5. Final Settlement" })
      .parentElement?.parentElement;
    if (step === null || step === undefined) throw new Error("no step");
    expect(within(step).getByText("Done")).toBeTruthy();
    cleanup();

    window.location.hash = "#/moveout/lease-U106";
    setup([neverIn], {
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
      settlementPreview: () => Promise.resolve({ settlement: {} }),
    });
    expect(
      await screen.findByText(
        "The statement could not be read. Read the page again.",
      ),
    ).toBeTruthy();
  });

  it("TEST-FE-990 the Settlement and its preview are read field by field: an unknown Deposit path or a broken amount is unreadable; the newest Settlement of the Lease is the one shown", () => {
    const good = previewOf("fs-lease-U106");
    expect(readPreview(good).open_total_usd_cents).toBe(31500);
    expect(readPreview(good).pet_remainder_chosen_by).toBe(
      "CUSTOMER_OR_STAFF_WITH_REASON",
    );
    expect(() =>
      readPreview({
        ...good,
        deposits: [
          {
            deposit_id: "d",
            deposit_type: "SECURITY",
            customer_id: null,
            held_usd_cents: 1,
            path: "SOMEWHERE",
          },
        ],
      }),
    ).toThrow();
    expect(() => readPreview({ ...good, open_total_usd_cents: 1.5 })).toThrow();
    // Review round 1: a missing step or an unknown chooser is unreadable, never a guess.
    expect(() => readPreview({ ...good, steps: [] })).toThrow();
    const steps = (good.steps as Record<string, unknown>[]).map((item) =>
      item.kind === "PET_DEPOSIT_REMAINDER"
        ? { ...item, chosen_by: "ANYONE" }
        : item,
    );
    expect(() => readPreview({ ...good, steps })).toThrow();
    // The list always says whether a draft waits.
    expect(() =>
      settlementOfLease(
        [{ ...settlementOf("lease-U106"), pending_draft: undefined }],
        "lease-U106",
      ),
    ).toThrow();
    expect(
      settlementOfLease(
        [
          settlementOf("lease-U106", { id: "old" }),
          settlementOf("lease-U106", {
            id: "new",
            started_at: "2026-10-22T03:00:00Z",
          }),
          settlementOf("lease-U105", { id: "other" }),
        ],
        "lease-U106",
      )?.id,
    ).toBe("new");
    expect(settlementOfLease([], "lease-U106")).toBeNull();
  });

  it("TEST-FE-993 Prepare draft proposes the DL-032 steps (own Credit first, then the Security Deposit oldest first) and refunds the rest to the Primary Tenant with the chosen method; a bank transfer needs its reference; the draft is recorded with a key", async () => {
    window.location.hash = "#/moveout/lease-U106";
    let drafted = false;
    const { settlementApi } = setup([neverIn], {
      settlements: () =>
        Promise.resolve([
          settlementOf("lease-U106", { pending_draft: drafted }),
        ]),
      settlementDraft: (property, settlement, form) => {
        drafted = true;
        return Promise.resolve({
          draft_id: "draft-1",
          property_id: property,
          kind: "FINAL_SETTLEMENT",
          prepare_capability: "final_settlements.prepare",
          payload: { final_settlement_id: settlement, steps: form.steps },
          reason: form.reason,
          prepared_at: "2026-10-25T03:00:00Z",
          prepared_by: "actor-1",
          state: "PENDING",
          decision: null,
        });
      },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Prepare draft" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("− $20.00")).toBeTruthy();
    expect(within(dialog).getByText("− $295.00")).toBeTruthy();
    expect(within(dialog).getByText("$205.00")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "The refund goes to the Primary Tenant, Tenant U106.",
      ),
    ).toBeTruthy();
    await within(dialog).findByLabelText("Refund by");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    expect(
      await within(dialog).findByText(
        "Fill in every box marked Required. A bank transfer needs its reference.",
      ),
    ).toBeTruthy();
    expect(settlementApi.settlementDraft).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/Transfer reference/), {
      target: { value: "ABA-123" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText(
        "Draft Final Settlement saved. A Manager confirms it in Waiting for approval.",
      ),
    ).toBeTruthy();
    const [property, settlementId, form, key] =
      settlementApi.settlementDraft.mock.calls[0] ?? [];
    expect([property, settlementId]).toEqual(["property-1", "fs-lease-U106"]);
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(form).toEqual({
      steps: [
        {
          kind: "CUSTOMER_CREDIT",
          customer_credit_id: "credit-1",
          target_kind: "INVOICE_LINE",
          target_id: "line-rent",
          amount_usd_cents: 2000,
          customer_designation: null,
        },
        {
          kind: "SECURITY_DEPOSIT",
          deposit_id: "dep-sec",
          target_kind: "INVOICE_LINE",
          target_id: "line-rent",
          amount_usd_cents: 28000,
        },
        {
          kind: "SECURITY_DEPOSIT",
          deposit_id: "dep-sec",
          target_kind: "LATE_PAYMENT_CHARGE",
          target_id: "late-1",
          amount_usd_cents: 1500,
        },
        {
          kind: "DEPOSIT_REFUNDS",
          deposit_id: "dep-sec",
          amount_usd_cents: 20500,
          refund_method_id: "m-aba",
          reference_note: "ABA-123",
          recipient_customer_id: "customer-U106",
          signer_agreement: null,
        },
      ],
      reason: "Final Settlement prepared from the move-out",
      pet_remainder: null,
    });
    // The draft now waits: no second one is offered.
    expect(
      await screen.findByText("A draft waits for a Manager."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Prepare draft" })).toBeNull();
  });

  it("TEST-FE-994 the rest of the Pet Deposit: on a normal end it pays the debt left after the Security Deposit with the Customer's choice or a staff reason; at an early termination only the Customer may choose it, otherwise it is refunded", async () => {
    const petCase = (chosenBy: string) => (_property: string, id: string) =>
      Promise.resolve(
        previewOf(id, {
          customers: [
            {
              customer_id: "customer-U106",
              primary_tenant: true,
              invoice_lines: [
                {
                  invoice_id: "inv-dmg",
                  invoice_line_id: "line-dog",
                  customer_id: "customer-U106",
                  category: "DAMAGE_CHARGES",
                  description: "Damage: chewed door",
                  due_date: "2026-10-20",
                  outstanding_usd_cents: 5000,
                  pet_damage: true,
                },
                {
                  invoice_id: "inv-dmg",
                  invoice_line_id: "line-window",
                  customer_id: "customer-U106",
                  category: "DAMAGE_CHARGES",
                  description: "Damage: window",
                  due_date: "2026-10-20",
                  outstanding_usd_cents: 60000,
                  pet_damage: false,
                },
              ],
              late_payment_charges: [],
              open_total_usd_cents: 65000,
              credits: [],
              credit_available_usd_cents: 0,
              credit_may_use_usd_cents: 0,
            },
          ],
          deposits: [
            {
              deposit_id: "dep-pet",
              deposit_type: "PET",
              customer_id: "customer-U106",
              held_usd_cents: 20000,
              path: "DL_032",
            },
            {
              deposit_id: "dep-sec",
              deposit_type: "SECURITY",
              customer_id: "customer-U106",
              held_usd_cents: 50000,
              path: "DL_032",
            },
          ],
          steps: [
            {
              step: 3,
              kind: "PET_DEPOSIT_PET_DAMAGE",
              pet_damage_open_usd_cents: 5000,
              deposits: [],
            },
            {
              step: 5,
              kind: "PET_DEPOSIT_REMAINDER",
              chosen_by: chosenBy,
              deposits: [],
            },
          ],
          open_total_usd_cents: 65000,
        }),
      );
    window.location.hash = "#/moveout/lease-U106";
    const normal = setup([neverIn], {
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
      settlementPreview: petCase("CUSTOMER_OR_STAFF_WITH_REASON"),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Prepare draft" }),
    );
    let dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText(/will not pay/));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    expect(
      await within(dialog).findByText(/Fill in every box marked Required/),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/Staff reason/), {
      target: { value: "The Customer left no money for the window" },
    });
    // 5,000 of the Pet Deposit is left to refund; ABA (the first method) needs a reference.
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    expect(normal.settlementApi.settlementDraft).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/Transfer reference/), {
      target: { value: "ABA 778899" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    await waitFor(() => {
      expect(normal.settlementApi.settlementDraft).toHaveBeenCalled();
    });
    const first = normal.settlementApi.settlementDraft.mock.calls[0]?.[2];
    expect(
      first?.steps.map((step) => [step.kind, step.amount_usd_cents]),
    ).toEqual([
      ["PET_DEPOSIT_PET_DAMAGE", 5000],
      ["SECURITY_DEPOSIT", 50000],
      ["PET_DEPOSIT_REMAINDER", 10000],
      ["DEPOSIT_REFUNDS", 5000],
    ]);
    expect(first?.steps[3]).toMatchObject({
      refund_method_id: "m-aba",
      reference_note: "ABA 778899",
    });
    expect(first?.pet_remainder).toEqual({
      basis: "STAFF_REASON",
      staff_reason: "The Customer left no money for the window",
      customer_choice: null,
    });
    cleanup();

    window.location.hash = "#/moveout/lease-U106";
    const early = setup([neverIn], {
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
      settlementPreview: petCase("CUSTOMER_ONLY"),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Prepare draft" }),
    );
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText(/will not pay/)).toBeNull();
    await within(dialog).findByLabelText("Refund by");
    fireEvent.change(within(dialog).getByLabelText("Refund by"), {
      target: { value: "m-cash" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    await waitFor(() => {
      expect(early.settlementApi.settlementDraft).toHaveBeenCalled();
    });
    const second = early.settlementApi.settlementDraft.mock.calls[0]?.[2];
    expect(
      second?.steps.map((step) => [step.kind, step.amount_usd_cents]),
    ).toEqual([
      ["PET_DEPOSIT_PET_DAMAGE", 5000],
      ["SECURITY_DEPOSIT", 50000],
      ["DEPOSIT_REFUNDS", 15000],
    ]);
    expect(second?.steps[2]).toMatchObject({
      refund_method_id: "m-cash",
      reference_note: "Paid in cash",
    });
    expect(second?.pet_remainder).toBeNull();
  });

  it("TEST-FE-995 no answer to the draft: Try again sends the same draft with the same key; a refused draft shows the server's words; a draft that already waits closes the dialog and says so; without the right, or while something blocks it, no Prepare draft", async () => {
    window.location.hash = "#/moveout/lease-U106";
    let calls = 0;
    const { settlementApi } = setup([neverIn], {
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
      settlementDraft: () => {
        calls += 1;
        return Promise.reject(
          calls === 1
            ? new SettlementUnavailableError()
            : calls === 2
              ? new SettlementRequestError(
                  422,
                  "FINAL_SETTLEMENT_CREDIT_FIRST",
                  "Each Customer's Credit must pay that Customer's open debt first.",
                )
              : new SettlementRequestError(
                  409,
                  "FINAL_SETTLEMENT_DRAFT_WAITING",
                  "A Final Settlement draft is already waiting",
                ),
        );
      },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Prepare draft" }),
    );
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByLabelText("Refund by");
    fireEvent.change(within(dialog).getByLabelText("Refund by"), {
      target: { value: "m-cash" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Try again" }),
    );
    expect(
      await within(dialog).findByText(
        "Each Customer's Credit must pay that Customer's open debt first.",
      ),
    ).toBeTruthy();
    const keys = settlementApi.settlementDraft.mock.calls.map(
      (call) => call[3],
    );
    expect(keys[0]).toBe(keys[1]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText(
        "A draft of this Final Settlement already waits for a Manager.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    cleanup();

    window.location.hash = "#/moveout/lease-U106";
    setup([neverIn], {
      capabilities: new Set(["leases.read", "financial.approve"]),
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
    });
    expect(await screen.findByText("Statement")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Prepare draft" })).toBeNull();
    cleanup();

    window.location.hash = "#/moveout/lease-U106";
    setup([neverIn], {
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
      settlementPreview: (_property, id) =>
        Promise.resolve(
          previewOf(id, {
            ready: false,
            blocking_issues: [{ code: "CLEANING_CHARGE_MISSING" }],
          }),
        ),
    });
    expect(
      await screen.findByText("Record the cleaning charge (step 4)."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Prepare draft" })).toBeNull();
    cleanup();

    // A refund with no refund method turned on: the dialog says so and records nothing.
    window.location.hash = "#/moveout/lease-U106";
    const none = setup([neverIn], {
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
      refundMethods: () =>
        Promise.resolve([
          { id: "m-wing", code: "WING", display_name: "Wing", active: false },
        ]),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Prepare draft" }),
    );
    const empty = await screen.findByRole("dialog");
    expect(
      await within(empty).findByText(/No refund method is turned on/),
    ).toBeTruthy();
    fireEvent.click(within(empty).getByRole("button", { name: "Save draft" }));
    expect(none.settlementApi.settlementDraft).not.toHaveBeenCalled();
    cleanup();

    // The refund methods could not be read: the dialog says so and records nothing.
    window.location.hash = "#/moveout/lease-U106";
    const failed = setup([neverIn], {
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
      refundMethods: () => Promise.reject(new Error("down")),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Prepare draft" }),
    );
    const unread = await screen.findByRole("dialog");
    expect(
      await within(unread).findByText(/refund methods could not be read/),
    ).toBeTruthy();
    fireEvent.click(within(unread).getByRole("button", { name: "Save draft" }));
    expect(failed.settlementApi.settlementDraft).not.toHaveBeenCalled();
    cleanup();

    // More than 200 steps cannot be saved at once: the dialog says so before staff fill it in.
    window.location.hash = "#/moveout/lease-U106";
    const long = setup([neverIn], {
      settlements: () => Promise.resolve([settlementOf("lease-U106")]),
      settlementPreview: (_property, id) =>
        Promise.resolve(
          previewOf(id, {
            customers: [
              {
                customer_id: "customer-U106",
                primary_tenant: true,
                invoice_lines: Array.from({ length: 201 }, (_, index) => ({
                  invoice_id: `inv-${String(index)}`,
                  invoice_line_id: `line-${String(index)}`,
                  customer_id: "customer-U106",
                  category: "UTILITIES",
                  description: "Water",
                  due_date: "2026-10-05",
                  outstanding_usd_cents: 100,
                  pet_damage: false,
                })),
                late_payment_charges: [],
                open_total_usd_cents: 20100,
                credits: [],
                credit_available_usd_cents: 0,
                credit_may_use_usd_cents: 0,
              },
            ],
            open_total_usd_cents: 20100,
          }),
        ),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Prepare draft" }),
    );
    const tooLong = await screen.findByRole("dialog");
    expect(
      within(tooLong).getAllByText(/too many lines to save at once/).length,
    ).toBeGreaterThan(0);
    fireEvent.click(
      within(tooLong).getByRole("button", { name: "Save draft" }),
    );
    expect(long.settlementApi.settlementDraft).not.toHaveBeenCalled();
  });
});
