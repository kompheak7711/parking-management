import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type CustomerApi,
  type CustomerDetail,
  CustomerConflictError,
} from "../customerClient";
import type { InvoiceResource } from "../invoiceClient";
import { type InvoicesData, payerIds } from "../invoices/invoicesData";
import type { ProblemType } from "../problems/problemsClient";
import { invoiceType, ivt } from "../invoices/text";
import { lineWords } from "../payments/ReceiptDocument";
import { pyt } from "../payments/text";
import { bookingRefusal } from "./NewBooking";
import { ShortStaysPage } from "./ShortStaysPage";
import { nextStep } from "./TodayPanel";
import { SiteCalendars } from "./SiteCalendars";
import { WeekReport as WeekReportView } from "./WeekReport";
import {
  type Booking,
  type CleaningDay,
  type CleaningTask,
  type GuestHistory,
  type NewBooking,
  type PriceLine,
  type ShortStaysApi,
  ShortStaysError,
  type StayCalendar,
  type StayPrice,
  type StayQuote,
  type WeekReport,
} from "./shortStaysClient";

const NOW = new Date("2026-11-04T03:00:00Z"); // 10:00 in Phnom Penh

beforeEach(() => {
  window.location.hash = "#/shortstays";
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

function calendar(from: string, days: number): StayCalendar {
  return {
    from,
    days,
    today: "2026-11-04",
    units: [
      {
        unit_id: "u-501",
        unit_number: "U501",
        unit_type: "STUDIO",
        status: "VACANT",
        for_rent: true,
        monthly_rent_usd_cents: 29900,
        bookings: [
          {
            booking_id: "b-1",
            booking_number: "ST260001",
            guest_name: "Lim Dara",
            status: "BOOKED",
            source: "WALK_IN",
            check_in_on: "2026-11-05",
            check_out_on: "2026-11-08",
            paid: false,
          },
        ],
        leases: [],
        reserved: false,
        site_holds: [],
      },
      {
        unit_id: "u-503",
        unit_number: "U503",
        unit_type: "ONE_BEDROOM",
        status: "VACANT",
        for_rent: true,
        monthly_rent_usd_cents: 26900,
        bookings: [],
        leases: [
          { lease_id: "l-1", start_date: "2026-11-10", end_date: "2027-05-09" },
        ],
        reserved: false,
        site_holds: [],
      },
    ],
  };
}

const LINE: PriceLine = {
  position: 1,
  kind: "NIGHTS",
  quantity: 3,
  unit_price_usd_cents: 2600,
  discount_basis_points: 3000,
  amount_usd_cents: 5460,
};
const LINES = [LINE];

function price0(extra: Partial<StayPrice> = {}): StayPrice {
  return {
    unit_id: "u-503",
    unit_number: "U503",
    unit_type: "ONE_BEDROOM",
    check_in_on: "2026-11-06",
    check_out_on: "2026-11-07",
    nights: 1,
    night_usd_cents: 2600,
    week_usd_cents: 12500,
    total_usd_cents: 2600,
    charged_as_whole_weeks: false,
    lines: [
      {
        ...LINE,
        quantity: 1,
        discount_basis_points: 0,
        amount_usd_cents: 2600,
      },
    ],
    month_only_usd_cents: 40500,
    suggest_month: false,
    blockers: [],
    site_holds: [],
    ...extra,
  };
}

const BOOKING: Booking = {
  booking_id: "b-1",
  booking_number: "ST260001",
  unit_id: "u-501",
  unit_number: "U501",
  unit_type: "STUDIO",
  customer_id: "c-1",
  guest_name: "Lim Dara",
  guest_phone: "010 333 444",
  guest_count: 2,
  check_in_on: "2026-11-05",
  check_out_on: "2026-11-08",
  nights: 3,
  source: "WALK_IN",
  site_name: null,
  site_reference: null,
  note: "Late arrival",
  status: "BOOKED",
  total_usd_cents: 6090,
  version: 1,
  created_at: "2026-11-04T02:00:00Z",
  lines: [{ ...LINE, unit_price_usd_cents: 2900, amount_usd_cents: 6090 }],
  history: [
    { kind: "BOOKED", occurred_at: "2026-11-04T02:00:00Z", note: null },
  ],
  unit_status: "VACANT",
  guest_has_id: true,
  payment: "NOT_BILLED",
  invoice: null,
  deposit: null,
  room_check: null,
  damages: [],
  problems: [],
  damage_decision: null,
  damage_due: false,
  extra_invoices: [],
  early_check_in: false,
  late_check_out: false,
  fee_usd_cents: 500,
  check_in_time: 840,
  check_out_time: 720,
  late_check_out_until: 1080,
  cleans: [],
  free_cancel_until: "2026-11-03",
  cancel_reason: null,
  paid_usd_cents: 0,
  cancellation: null,
  credit: null,
  lease_off_usd_cents: 5000,
  lease_offer: null,
  lease_drafts: [],
  returning_guest: false,
  problem_guest: false,
  review_asked_at: null,
};

/** Booking b-1 checks in today (04/11) for 3 nights. */
const TODAY_STAY: Booking = {
  ...BOOKING,
  check_in_on: "2026-11-04",
  check_out_on: "2026-11-07",
};

const INVOICE = {
  invoice_id: "i-1",
  invoice_number: "INV-000123",
  status: "ISSUED",
  total_usd_cents: 6090,
  due_usd_cents: 6090,
};

const DEPOSIT: NonNullable<Booking["deposit"]> = {
  deposit_id: "d-1",
  kind: "CASH",
  amount_usd_cents: 5000,
  hold_reference: null,
  card_last4: null,
  status: "HELD",
  kept_usd_cents: 0,
  taken_at: "2026-11-04T03:00:00Z",
  ended_at: null,
};

function guestHistory(extra: Partial<GuestHistory> = {}): GuestHistory {
  return {
    customer_id: "c-1",
    legal_name: "Lim Dara",
    phone_number: "010 333 444",
    stays: [],
    stays_done: 0,
    nights_done: 0,
    spent_usd_cents: 0,
    returning: false,
    problem_guest: false,
    notes: [],
    thank_you_usd_cents: 300,
    ...extra,
  };
}

function weekReport(extra: Partial<WeekReport> = {}): WeekReport {
  return {
    from: "2026-11-02",
    to: "2026-11-08",
    so_far: true,
    base_occupancy_points: 4000,
    change_over_usd_cents: 500,
    linen_usd_cents: 200,
    units: [
      {
        unit_id: "u-501",
        unit_number: "U501",
        nights: 3,
        income_usd_cents: 6090,
        site_fees_usd_cents: 0,
        cleaning_usd_cents: 700,
        net_usd_cents: 5390,
      },
      {
        unit_id: "u-503",
        unit_number: "U503",
        nights: 0,
        income_usd_cents: 0,
        site_fees_usd_cents: 0,
        cleaning_usd_cents: 0,
        net_usd_cents: 0,
      },
    ],
    totals: {
      units: 2,
      unit_nights: 14,
      nights: 3,
      income_usd_cents: 6090,
      site_fees_usd_cents: 0,
      cleaning_usd_cents: 700,
      net_usd_cents: 5390,
      occupancy_points: 2142,
    },
    leases: [],
    damages: [],
    complaints: [],
    sources: [{ source: "WALK_IN", site_name: null, stays: 1 }],
    cancellations: { count: 0, kept_usd_cents: 0 },
    ...extra,
  };
}

/** DL-222: the problem types a room check offers; a water leak is always urgent. */
const PROBLEM_TYPES: ProblemType[] = [
  {
    id: "pt-1",
    code: "FURNITURE",
    name_en: "Furniture",
    name_kh: "គ្រឿងសង្ហារិម",
    icon: "sofa",
    always_urgent: false,
  },
  {
    id: "pt-2",
    code: "WATER_LEAK",
    name_en: "Water leak",
    name_kh: null,
    icon: "water",
    always_urgent: true,
  },
];

/** DL-222: checked out, the deposit held, the room check still to do. */
function checkedOut(extra: Partial<Booking> = {}): Booking {
  return {
    ...TODAY_STAY,
    status: "CHECKED_OUT",
    payment: "PAID",
    invoice: INVOICE,
    deposit: DEPOSIT,
    room_check: {
      task_id: "t-1",
      task_on: "2026-11-04",
      status: "TO_DO",
      note: null,
      done_at: null,
    },
    ...extra,
  };
}

const ROOM_DONE: Booking["room_check"] = {
  task_id: "t-1",
  task_on: "2026-11-04",
  status: "DONE",
  note: null,
  done_at: "2026-11-04T04:00:00Z",
};

const PROBLEM: Booking["problems"][number] = {
  report_id: "r-1",
  report_number: "UP260007",
  description: "Lamp broken",
  type_name_en: "Furniture",
  type_name_kh: "គ្រឿងសង្ហារិម",
  urgent: true,
  status: "RECEIVED",
};

function fakeApi(overrides: Partial<ShortStaysApi> = {}): ShortStaysApi {
  return {
    calendar: vi.fn((_: string, from: string, days: number) =>
      Promise.resolve(calendar(from, days)),
    ),
    price: vi.fn(() => Promise.resolve(price0())),
    list: vi.fn(() => Promise.resolve([BOOKING])),
    get: vi.fn(() => Promise.resolve(BOOKING)),
    book: vi.fn((_: string, body: NewBooking) =>
      Promise.resolve({
        ...BOOKING,
        booking_id: "b-2",
        booking_number: "ST260002",
        unit_id: body.unit_id,
      }),
    ),
    step: vi.fn(() => Promise.resolve(BOOKING)),
    moveUnits: vi.fn(() => Promise.resolve([])),
    decide: vi.fn(() => Promise.resolve(BOOKING)),
    cleaning: vi.fn((_: string, day: string) =>
      Promise.resolve({ day, today: "2026-11-04", tasks: [], cleaners: [] }),
    ),
    finishTask: vi.fn(() =>
      Promise.resolve({
        day: "2026-11-04",
        today: "2026-11-04",
        tasks: [],
        cleaners: [],
      }),
    ),
    assignTask: vi.fn(() => Promise.reject(new Error("not used"))),
    siteCalendars: vi.fn(() => Promise.resolve([])),
    saveSiteCalendar: vi.fn(() => Promise.reject(new Error("not used"))),
    guest: vi.fn((_: string, customerId: string) =>
      Promise.resolve(guestHistory({ customer_id: customerId })),
    ),
    addGuestNote: vi.fn(() => Promise.reject(new Error("not used"))),
    quotes: vi.fn(() => Promise.resolve([])),
    quote: vi.fn(() => Promise.reject(new Error("not used"))),
    weekReport: vi.fn((_: string, from: string) =>
      Promise.resolve(weekReport({ from })),
    ),
    complaint: vi.fn(() => Promise.resolve()),
    creditsDue: vi.fn(() => Promise.resolve([])),
    damageDue: vi.fn(() => Promise.resolve([])),
    problemTypes: vi.fn(() => Promise.resolve(PROBLEM_TYPES)),
    refundMethods: vi.fn(() => Promise.resolve([])),
    refund: vi.fn(() => Promise.reject(new Error("not used"))),
    ...overrides,
  };
}

function customer(extra: Partial<CustomerDetail> = {}): CustomerDetail {
  return {
    customer_id: "c-new",
    legal_name: "Meas Rina",
    phone_number: "012 555 666",
    email_address: null,
    contact_address: null,
    memo: null,
    id_document_number: "N123456",
    date_of_birth: null,
    gender: null,
    nationality: null,
    version: 1,
    active: true,
    deactivated_at: null,
    deactivation_reason: null,
    relationships: {
      reservations: [],
      primary_tenant_leases: [],
      signer_leases: [],
      occupancies: [],
      invoices: [],
      payments: [],
      customer_credit: [],
      refunds: [],
    },
    audit_history: [],
    audit_history_next_cursor: null,
    can_manage: true,
    can_deactivate: false,
    can_view_audit: false,
    audit_history_available: false,
    ...extra,
  };
}

function fakeCustomers(overrides: Partial<CustomerApi> = {}): CustomerApi {
  return {
    list: vi.fn(() =>
      Promise.resolve({
        items: [
          {
            customer_id: "c-1",
            legal_name: "Lim Dara",
            phone_number: "010 333 444",
            active: true,
            relationship_indicators: [],
          },
        ],
        next_cursor: null,
        can_manage: true,
      }),
    ),
    create: vi.fn(() => Promise.resolve(customer())),
    ...overrides,
  } as unknown as CustomerApi;
}

function byId(id: string): HTMLElement {
  const found = document.getElementById(id);
  if (found === null) throw new Error(`No element #${id}`);
  return found;
}

const DESK = new Set(["short_stays.read", "short_stays.desk"]);

function show(
  props: {
    api?: ShortStaysApi;
    customerApi?: CustomerApi;
    capabilities?: ReadonlySet<string> | null;
    language?: "en" | "km";
  } = {},
) {
  const api = props.api ?? fakeApi();
  const customerApi = props.customerApi ?? fakeCustomers();
  render(
    <ShortStaysPage
      active
      api={api}
      capabilities={
        props.capabilities === undefined ? DESK : props.capabilities
      }
      customerApi={customerApi}
      language={props.language ?? "en"}
      now={NOW}
      propertyId="p-1"
    />,
  );
  return { api, customerApi };
}

function go(hash: string) {
  window.location.hash = hash;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

describe("Daily and weekly rent: Short stays", () => {
  it("TEST-FE-1600 shows one row per Unit and one bar per stay, each with a word", async () => {
    const { api } = show();
    const table = await screen.findByRole("table");
    expect(api.calendar).toHaveBeenCalledWith("p-1", "2026-11-04", 14);
    const u501 = within(table).getByRole("row", { name: /U501/ });
    // Leasing batch (owner 13/11/2026): the stay is one bar with the guest's name; not paid yet
    // is said too (an orange dot on the screen). It opens the booking.
    const bar = within(u501).getByRole("link", { name: /Lim Dara/ });
    expect(bar).toHaveAttribute("href", "#/shortstays/st%3Ab-1");
    expect(bar).toHaveAccessibleName("Lim Dara, not paid · ST260001");
    expect(bar.closest("td")).toHaveAttribute("colspan", "3");
    // Today is free: the square opens New booking for that Unit and night.
    expect(
      within(u501).getByRole("link", {
        name: "New booking: U501, night of 04/11/2026",
      }),
    ).toHaveAttribute("href", "#/shortstays/new%3Au-501%3A2026-11-04");
    // The Units sit under their Unit type, whose row counts the free rooms each night.
    expect(
      within(table).getByRole("rowheader", { name: "1 bedroom" }),
    ).toBeInTheDocument();
    const u503 = within(table).getByRole("row", { name: /U503/ });
    expect(within(u503).getAllByText("Lease")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /Later/ }));
    await waitFor(() => {
      expect(api.calendar).toHaveBeenLastCalledWith("p-1", "2026-11-11", 14);
    });
    expect(
      await screen.findByText("11/11/2026 to 24/11/2026"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => {
      expect(api.calendar).toHaveBeenLastCalledWith("p-1", "2026-11-04", 14);
    });
  });

  it("TEST-FE-1601 lists bookings and opens one with its price lines and history", async () => {
    const { api } = show();
    fireEvent.click(await screen.findByRole("link", { name: "Bookings" }));
    const row = await screen.findByRole("row", { name: /ST260001/ });
    expect(within(row).getByText("$60.90")).toBeInTheDocument();
    expect(within(row).getByText("3 nights")).toBeInTheDocument();
    expect(within(row).getByText("Walk-in")).toBeInTheDocument();
    expect(screen.getByText("1 booking")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("link", { name: "ST260001" }));
    expect(
      await screen.findByRole("heading", { name: "ST260001" }),
    ).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("p-1", "b-1");
    expect(screen.getByText("3 × night $29.00")).toBeInTheDocument();
    expect(screen.getByText("(30% off)")).toBeInTheDocument();
    expect(screen.getByText("Late arrival")).toBeInTheDocument();
    expect(screen.getByText("05/11/2026 to 08/11/2026")).toBeInTheDocument();
  });

  it("TEST-FE-1602 books a free night for a guest who is a Customer, at the server's price", async () => {
    go("#/shortstays/new:u-503:2026-11-06");
    const api = fakeApi({
      price: vi.fn(() =>
        Promise.resolve(
          price0({
            nights: 3,
            check_out_on: "2026-11-09",
            lines: LINES,
            total_usd_cents: 5460,
          }),
        ),
      ),
    });
    const { customerApi } = show({ api });
    const nights = await screen.findByLabelText(/^Nights/);
    fireEvent.change(nights, { target: { value: "3" } });
    await waitFor(() => {
      expect(api.price).toHaveBeenLastCalledWith(
        "p-1",
        "u-503",
        "2026-11-06",
        "2026-11-09",
      );
    });
    expect(await screen.findByText("3 × night $26.00")).toBeInTheDocument();
    expect(screen.getAllByText("$54.60")).toHaveLength(2);
    expect(screen.getByLabelText(/^Unit/)).toHaveValue("u-503");
    // Typing the phone shows the matching Customers (owner test 06/11/2026).
    fireEvent.change(screen.getByLabelText(/^Phone/), {
      target: { value: "010" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Choose" }));
    expect(customerApi.list).toHaveBeenCalledWith("p-1", {
      query: "010",
      active: true,
    });
    fireEvent.change(screen.getByLabelText(/^Note/), {
      target: { value: " Late arrival " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Book" }));
    expect(
      await screen.findByText("Booking ST260002 made."),
    ).toBeInTheDocument();
    expect(api.book).toHaveBeenCalledWith("p-1", {
      unit_id: "u-503",
      customer_id: "c-1",
      guest_count: 1,
      check_in_on: "2026-11-06",
      check_out_on: "2026-11-09",
      source: "WALK_IN",
      note: "Late arrival",
    });
    expect(window.location.hash).toBe("#/shortstays/st%3Ab-2");
  });

  it("TEST-FE-1603 says what is missing, why a Unit cannot be booked, and offers the monthly Lease", async () => {
    go("#/shortstays/new:u-501:2026-11-06");
    const api = fakeApi({
      price: vi.fn(() =>
        Promise.resolve(
          price0({
            unit_id: "u-501",
            unit_number: "U501",
            suggest_month: true,
            blockers: ["BOOKED"],
          }),
        ),
      ),
    });
    show({ api, capabilities: DESK });
    expect(
      await screen.findByText("Another guest has booked one of these nights."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "This stay costs more than the 1-month-only rent of $405.00. Offer the monthly Lease.",
      ),
    ).toBeInTheDocument();
    // U501 is booked on the 6th, so it is marked not free; U503 is free.
    expect(
      screen.getByRole("option", { name: "U501 · Studio · not free" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "U503 · 1 bedroom" }),
    ).not.toBeDisabled();
    // Without customers.manage the desk cannot add a guest here.
    expect(
      screen.getByText(/Your account may not add Customers/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Booked by/), {
      target: { value: "BOOKING_SITE" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Book" }));
    const summary = await screen.findByRole("alert");
    expect(
      within(summary).getByText("3 things need fixing:"),
    ).toBeInTheDocument();
    expect(
      within(summary).getByText("Choose the guest or add a new one."),
    ).toBeInTheDocument();
    expect(
      within(summary).getByText("Name the booking site."),
    ).toBeInTheDocument();
    expect(
      within(summary).getByText("These nights cannot be booked in this Unit."),
    ).toBeInTheDocument();
    expect(api.book).not.toHaveBeenCalled();
  });

  it("TEST-FE-1604 adds a new guest as a Customer once, even when the booking is tried again", async () => {
    go("#/shortstays/new:u-503:2026-11-06");
    const book = vi
      .fn<ShortStaysApi["book"]>()
      .mockRejectedValueOnce(
        new ShortStaysError(
          409,
          "The Unit is already booked on one of these nights",
        ),
      )
      .mockResolvedValueOnce({
        ...BOOKING,
        booking_id: "b-3",
        booking_number: "ST260003",
      });
    const api = fakeApi({ book });
    const create = vi
      .fn<CustomerApi["create"]>()
      .mockRejectedValueOnce(
        new CustomerConflictError([
          {
            customer_id: "c-9",
            legal_name: "Meas Rina",
            active: true,
            relationship_indicators: [],
          },
        ]),
      )
      .mockResolvedValue(customer());
    const { customerApi } = show({
      api,
      customerApi: fakeCustomers({ create }),
      capabilities: new Set([...DESK, "customers.manage"]),
    });
    await screen.findByLabelText(/^Full name/);
    fireEvent.click(screen.getByRole("button", { name: "Book" }));
    expect(
      await screen.findAllByText("Enter the guest's full name."),
    ).toHaveLength(2);
    fireEvent.change(screen.getByLabelText(/^Full name/), {
      target: { value: "Meas Rina" },
    });
    fireEvent.change(screen.getByLabelText(/^ID or passport number/), {
      target: { value: "N123456" },
    });
    fireEvent.change(screen.getByLabelText(/^Phone/), {
      target: { value: "012 555 666" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Book" }));
    // The same name is already a Customer: the desk says it is another person.
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Another person: add the new guest",
      }),
    );
    expect(
      await screen.findByText(/Someone has just booked one of these nights/),
    ).toBeInTheDocument();
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[1]?.[2]).toEqual({
      legal_name: "Meas Rina",
      id_document_number: "N123456",
      phone_number: "012 555 666",
      confirmed_distinct: true,
    });
    // The guest is now a Customer; the next try books without adding them again.
    expect(screen.getByText("Meas Rina")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Book" }));
    expect(
      await screen.findByText("Booking ST260003 made."),
    ).toBeInTheDocument();
    expect(customerApi.create).toHaveBeenCalledTimes(2);
    expect(book.mock.calls[1]?.[1].customer_id).toBe("c-new");
  });

  it("TEST-FE-1606 makes the Invoice, then sends the desk to Receive payment", async () => {
    const step = vi.fn(() =>
      Promise.resolve({
        ...TODAY_STAY,
        payment: "UNPAID" as const,
        invoice: INVOICE,
        version: 2,
      }),
    );
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(TODAY_STAY)), step }),
      capabilities: new Set([...DESK, "payments.record"]),
    });
    go("#/shortstays/st:b-1");
    expect(await screen.findByText("Not billed yet")).toBeInTheDocument();
    // A walk-in cannot be marked paid on a booking site.
    expect(
      screen.queryByRole("button", { name: "Paid on the booking site" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Make the Invoice" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "bill", { version: 1 });
    expect(
      await screen.findByRole("link", { name: "Open Invoice INV-000123" }),
    ).toHaveAttribute("href", "#/invoices/inv%3Ai-1");
    expect(
      screen.getByRole("link", { name: /Receive payment/ }),
    ).toHaveAttribute("href", "#/payments/receive%3Ac-1");
    expect(screen.getByText("Not paid")).toBeInTheDocument();
  });

  it("TEST-FE-1607 takes a card hold without the card number, then checks in when all is ready", async () => {
    let now: Booking = { ...TODAY_STAY, payment: "PAID", invoice: INVOICE };
    const step = vi.fn(
      (_: string, __: string, which: string, body: unknown) => {
        if (which === "deposit")
          now = {
            ...now,
            deposit: {
              ...DEPOSIT,
              kind: "CARD_HOLD",
              hold_reference: "HOLD-7781",
              card_last4: "1234",
            },
          };
        if (which === "check-in") {
          expect(body).toEqual({
            version: 1,
            id_copy_made: true,
            house_rules_signed: true,
          });
          now = { ...now, status: "CHECKED_IN", version: 2 };
        }
        return Promise.resolve(now);
      },
    );
    show({ api: fakeApi({ get: vi.fn(() => Promise.resolve(now)), step }) });
    go("#/shortstays/st:b-1");
    const checkIn = within(
      await screen.findByRole("region", { name: "Check-in" }),
    );
    const button = checkIn.getByRole("button", { name: "Check in" });
    expect(button).toBeDisabled();
    expect(checkIn.getByText("The deposit is taken").closest("li")).toHaveClass(
      "ss-todo",
    );
    fireEvent.click(screen.getByLabelText("Card hold"));
    const take = screen.getByRole("button", { name: "Take the deposit" });
    expect(take).toBeDisabled();
    expect(
      screen.getByText("Never enter the card number."),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Hold reference/), {
      target: { value: " HOLD-7781 " },
    });
    fireEvent.change(screen.getByLabelText(/last 4 digits/), {
      target: { value: "1234" },
    });
    fireEvent.click(take);
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "deposit", {
      kind: "CARD_HOLD",
      hold_reference: "HOLD-7781",
      card_last4: "1234",
    });
    expect(await screen.findByText(/•••• 1234/)).toBeInTheDocument();
    const ready = within(screen.getByRole("region", { name: "Check-in" }));
    expect(ready.getByText("The deposit is taken").closest("li")).toHaveClass(
      "ss-ok",
    );
    fireEvent.click(
      ready.getByLabelText("I made a copy of the ID or passport"),
    );
    expect(ready.getByRole("button", { name: "Check in" })).toBeDisabled();
    fireEvent.click(ready.getByLabelText("The guest signed the house rules"));
    fireEvent.click(ready.getByRole("button", { name: "Check in" }));
    expect(await screen.findByText("Checked in")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Check-in" })).toBeNull();
    expect(
      screen.getByRole("button", { name: /Check out/ }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1608 shows a stale screen as it is now and says why", async () => {
    const get = vi.fn(() =>
      Promise.resolve({
        ...TODAY_STAY,
        payment: "UNPAID" as const,
        invoice: INVOICE,
      }),
    );
    show({
      api: fakeApi({
        get: vi.fn().mockResolvedValueOnce(TODAY_STAY).mockImplementation(get),
        step: vi.fn(() => Promise.reject(new ShortStaysError(412))),
      }),
    });
    go("#/shortstays/st:b-1");
    fireEvent.click(
      await screen.findByRole("button", { name: "Make the Invoice" }),
    );
    expect(
      await screen.findByText(
        "This booking changed meanwhile. It is shown as it is now.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("Not paid")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Make the Invoice" }),
    ).toBeNull();
  });

  it("TEST-FE-1609 the room check reports problems as Problem reports, with no cost", async () => {
    const out = checkedOut();
    const reported = checkedOut({
      room_check: ROOM_DONE,
      problems: [PROBLEM],
      damage_due: true,
    });
    const step = vi.fn(() => Promise.resolve(reported));
    const problemTypes = vi.fn(() => Promise.resolve(PROBLEM_TYPES));
    show({
      api: fakeApi({
        get: vi.fn(() => Promise.resolve(out)),
        step,
        problemTypes,
      }),
      capabilities: new Set([
        ...DESK,
        "short_stays.housekeeping",
        "problem_reports.read",
        "problem_reports.add",
      ]),
    });
    go("#/shortstays/st:b-1");
    fireEvent.click(
      await screen.findByRole("button", { name: "Report a problem" }),
    );
    expect(problemTypes).toHaveBeenCalledWith("p-1");
    // The room check never asks for money.
    expect(screen.queryByLabelText(/Cost/)).toBeNull();
    expect(screen.queryByLabelText(/Amount/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Room check done/ }));
    expect(screen.getByText("Pick the type of problem.")).toBeInTheDocument();
    expect(screen.getByText("Say what is wrong.")).toBeInTheDocument();
    expect(step).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Type 1/), {
      target: { value: "pt-1" },
    });
    fireEvent.change(screen.getByLabelText(/What is wrong 1/), {
      target: { value: " Lamp broken " },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Urgent" }));
    // A second problem of a type that is always urgent, then removed again.
    fireEvent.click(screen.getByRole("button", { name: "Report a problem" }));
    fireEvent.change(screen.getByLabelText(/Type 2/), {
      target: { value: "pt-2" },
    });
    const urgent = screen.getAllByRole("checkbox", { name: "Urgent" });
    expect(urgent[1]).toBeChecked();
    expect(urgent[1]).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Remove 2" }));
    expect(screen.queryByLabelText(/Type 2/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Room check done/ }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "room-check", {
      problems: [
        { problem_type_id: "pt-1", description: "Lamp broken", urgent: true },
      ],
    });
    // The problem shows on the booking and opens its Problem report.
    expect(
      await screen.findByRole("link", { name: "UP260007" }),
    ).toHaveAttribute("href", "#/problems/pr%3Ar-1");
    // Without the right to bill damage: no decision form, and the deposit waits.
    expect(
      screen.getByText(
        "The damage charge is not decided yet. A person who bills damage decides it.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save the decision" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Return the deposit/ }),
    ).toBeNull();
  });

  it("TEST-FE-1610 charges the guest without an approval: from the deposit, then keeps it", async () => {
    const reported = checkedOut({
      room_check: ROOM_DONE,
      problems: [PROBLEM],
      damage_due: true,
    });
    const charged: Booking = {
      ...reported,
      damage_due: false,
      damage_decision: {
        outcome: "CHARGE",
        damage_id: "g-1",
        note: null,
        decided_at: "2026-11-04T05:00:00Z",
      },
      damages: [
        {
          damage_id: "g-1",
          description: "Broken lamp",
          amount_usd_cents: 8000,
          status: "APPROVED",
          decided_at: "2026-11-04T05:00:00Z",
          decision_note: null,
          from_deposit_usd_cents: 5000,
          invoice_id: "i-2",
          invoice_number: "INV-000124",
        },
      ],
    };
    const step = vi
      .fn()
      .mockResolvedValueOnce(charged)
      .mockResolvedValueOnce({
        ...charged,
        deposit: { ...DEPOSIT, status: "KEPT" as const, kept_usd_cents: 5000 },
      });
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(reported)), step }),
      capabilities: new Set([...DESK, "damage_charges.bill"]),
    });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByText(
        "Decide the damage charge. The deposit waits until then.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The deposit ends after check-out and the room check, once the damage charge is decided.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Return the deposit/ }),
    ).toBeNull();
    // Charge the guest is chosen first; what for starts from the problems, and it needs both.
    const what = screen.getByLabelText(/What the guest pays for/);
    expect(what).toHaveValue("Lamp broken");
    fireEvent.change(what, { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: "Save the decision" }));
    expect(
      screen.getByText("Say what the guest pays for."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Enter the cost in dollars, for example 80 or 80.50."),
    ).toBeInTheDocument();
    expect(step).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/What the guest pays for/), {
      target: { value: "Broken lamp" },
    });
    fireEvent.change(screen.getByLabelText(/Amount/), {
      target: { value: "80" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save the decision" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "damage", {
      charge: true,
      description: "Broken lamp",
      amount_usd_cents: 8000,
    });
    expect(
      await screen.findByText(/\$50\.00 from the deposit/),
    ).toBeInTheDocument();
    expect(screen.getByText("Charged")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Invoice INV-000124 for the rest" }),
    ).toHaveAttribute("href", "#/invoices/inv%3Ai-2");
    expect(
      screen.queryByRole("button", { name: "Save the decision" }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Keep $50.00 for damage, return $0.00",
      }),
    );
    expect(step).toHaveBeenLastCalledWith("p-1", "b-1", "deposit/end", null);
    expect(await screen.findByText(/Kept \$50\.00/)).toBeInTheDocument();
  });

  it("TEST-FE-2050 a room check without the right to add a Problem report reports nothing", async () => {
    const problemTypes = vi.fn(() => Promise.resolve(PROBLEM_TYPES));
    const step = vi.fn(() =>
      Promise.resolve(checkedOut({ room_check: ROOM_DONE })),
    );
    show({
      api: fakeApi({
        get: vi.fn(() => Promise.resolve(checkedOut())),
        step,
        problemTypes,
      }),
      capabilities: new Set([...DESK, "short_stays.housekeeping"]),
    });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByText(
        "To report a problem, your account needs the right to add a Problem report.",
      ),
    ).toBeInTheDocument();
    expect(problemTypes).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Report a problem" }),
    ).toBeNull();
    fireEvent.change(screen.getByLabelText("Note"), {
      target: { value: "All fine" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Room check done/ }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "room-check", {
      note: "All fine",
    });
  });

  it("TEST-FE-2051 No charge returns the whole deposit", async () => {
    const reported = checkedOut({
      room_check: ROOM_DONE,
      problems: [{ ...PROBLEM, urgent: false }],
      damage_due: true,
    });
    const decided: Booking = {
      ...reported,
      damage_due: false,
      damage_decision: {
        outcome: "NO_CHARGE",
        damage_id: null,
        note: "Normal wear",
        decided_at: "2026-11-04T05:00:00Z",
      },
    };
    const step = vi.fn(() => Promise.resolve(decided));
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(reported)), step }),
      capabilities: new Set([...DESK, "damage_charges.bill"]),
      language: "km",
    });
    go("#/shortstays/st:b-1");
    // The problem's type shows in Khmer.
    expect(await screen.findByText(/គ្រឿងសង្ហារិម/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "មិនគិតថ្លៃ" }));
    expect(screen.queryByLabelText(/ចំនួនទឹកប្រាក់/)).toBeNull();
    fireEvent.change(screen.getByLabelText(/កំណត់ចំណាំ \(បើចង់\)/), {
      target: { value: " Normal wear " },
    });
    fireEvent.click(screen.getByRole("button", { name: "រក្សាទុកការសម្រេច" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "damage", {
      charge: false,
      note: "Normal wear",
    });
    expect(await screen.findByText("មិនគិតថ្លៃការខូចខាត។")).toBeInTheDocument();
    expect(screen.getByText("Normal wear")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "ប្រគល់ប្រាក់កក់វិញ" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2052 a damage charge waiting from before is decided by the person who bills damage", async () => {
    const damage = {
      damage_id: "g-1",
      description: "Broken lamp",
      amount_usd_cents: 8000,
      status: "WAITING" as const,
      decided_at: null,
      decision_note: null,
      from_deposit_usd_cents: 0,
      invoice_id: null,
      invoice_number: null,
    };
    const waiting = checkedOut({ room_check: ROOM_DONE, damages: [damage] });
    const decide = vi.fn(() => Promise.resolve(waiting));
    // The old approve right alone no longer decides it.
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(waiting)), decide }),
      capabilities: new Set([...DESK, "short_stays.approve"]),
    });
    go("#/shortstays/st:b-1");
    expect(await screen.findByText("Waits for a decision")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "No charge" })).toBeNull();
    cleanup();
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(waiting)), decide }),
      capabilities: new Set([...DESK, "damage_charges.bill"]),
    });
    go("#/shortstays/st:b-1");
    fireEvent.click(await screen.findByRole("button", { name: "No charge" }));
    expect(screen.getByText("No charge says why.")).toBeInTheDocument();
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Charge the guest" }));
    expect(decide).toHaveBeenCalledWith("p-1", "g-1", { approve: true });
  });

  it("TEST-FE-2053 the Bookings list shows stays waiting for a damage decision to the person who bills damage", async () => {
    const damageDue = vi.fn(() =>
      Promise.resolve([
        {
          booking_id: "b-1",
          booking_number: "ST260001",
          guest_name: "Lim Dara",
          unit_number: "U501",
          problem_count: 2,
        },
      ]),
    );
    show({ api: fakeApi({ damageDue }) });
    fireEvent.click(await screen.findByRole("link", { name: "Bookings" }));
    await screen.findByRole("table");
    expect(damageDue).not.toHaveBeenCalled();
    cleanup();
    show({
      api: fakeApi({ damageDue }),
      capabilities: new Set([...DESK, "damage_charges.bill"]),
    });
    fireEvent.click(await screen.findByRole("link", { name: "Bookings" }));
    const title =
      "1 stay(s) wait for a damage decision. Open each booking and choose Charge the guest or No charge.";
    const due = await screen.findByRole("region", { name: title });
    expect(damageDue).toHaveBeenCalledWith("p-1");
    expect(within(due).getByRole("link", { name: "ST260001" })).toHaveAttribute(
      "href",
      "#/shortstays/st%3Ab-1",
    );
    expect(
      within(due).getByText(/Lim Dara, U501: problems 2/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1611 adds a late check-out and shows its own Invoice once the stay is billed", async () => {
    const billed: Booking = {
      ...TODAY_STAY,
      payment: "PAID",
      invoice: INVOICE,
    };
    const step = vi.fn(() =>
      Promise.resolve({
        ...billed,
        payment: "UNPAID" as const,
        late_check_out: true,
        version: 2,
        extra_invoices: [
          {
            invoice_id: "i-3",
            invoice_number: "INV-000125",
            status: "UNPAID",
            kind: "LATE_CHECK_OUT" as const,
            total_usd_cents: 500,
          },
        ],
      }),
    );
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(billed)), step }),
    });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByText("Check-in from 14:00, check-out by 12:00"),
    ).toBeInTheDocument();
    expect(screen.getByText("$5.00 each for this stay.")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Add late check-out (until 18:00)" }),
    );
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "fee", {
      version: 1,
      kind: "LATE_CHECK_OUT",
    });
    expect(
      await screen.findByRole("link", {
        name: "Late check-out: Invoice INV-000125",
      }),
    ).toHaveAttribute("href", "#/invoices/inv%3Ai-3");
    expect(
      screen.getByText("Late check-out added (until 18:00)"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Add late check-out/ }),
    ).toBeNull();
    // Still one early check-in to offer before the guest is in.
    expect(
      screen.getByRole("button", { name: "Add early check-in" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1612 prices an extension before the desk extends the stay", async () => {
    const price = vi.fn(() =>
      Promise.resolve({ ...price0(), total_usd_cents: 12180 }),
    );
    const step = vi.fn(() =>
      Promise.resolve({
        ...TODAY_STAY,
        check_out_on: "2026-11-10",
        nights: 6,
        total_usd_cents: 12180,
        version: 2,
      }),
    );
    show({
      api: fakeApi({
        get: vi.fn(() => Promise.resolve(TODAY_STAY)),
        price,
        step,
      }),
    });
    go("#/shortstays/st:b-1");
    const card = within(
      await screen.findByRole("region", { name: "Extend the stay" }),
    );
    // The first day offered is the day after the check-out day.
    await waitFor(() => {
      expect(price).toHaveBeenCalledWith(
        "p-1",
        "u-501",
        "2026-11-04",
        "2026-11-08",
      );
    });
    fireEvent.change(card.getByLabelText("New check-out day"), {
      target: { value: "2026-11-10" },
    });
    await waitFor(() => {
      expect(price).toHaveBeenLastCalledWith(
        "p-1",
        "u-501",
        "2026-11-04",
        "2026-11-10",
      );
    });
    expect(
      await card.findByText("New total $121.80: $60.90 more."),
    ).toBeInTheDocument();
    fireEvent.click(card.getByRole("button", { name: /Extend/ }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "extend", {
      version: 1,
      check_out_on: "2026-11-10",
    });
    expect(await screen.findByText("6 nights")).toBeInTheDocument();
  });

  it("TEST-FE-1613 lists the day's cleans and skips one only with a reason", async () => {
    const day = {
      day: "2026-11-04",
      today: "2026-11-04",
      tasks: [
        {
          task_id: "t-1",
          kind: "DAILY_CLEAN" as const,
          task_on: "2026-11-04",
          status: "TO_DO" as const,
          note: null,
          done_at: null,
          unit_id: "u-501",
          unit_number: "U501",
          booking_id: "b-1",
          booking_number: "ST260001",
          guest_name: "Lim Dara",
          late: false,
          assigned_to: null,
          assigned_name: null,
          done_by_name: null,
        },
        {
          task_id: "t-2",
          kind: "ROOM_CHECK" as const,
          task_on: "2026-11-03",
          status: "TO_DO" as const,
          note: null,
          done_at: null,
          unit_id: "u-503",
          unit_number: "U503",
          booking_id: "b-9",
          booking_number: "ST260009",
          guest_name: "Meas Rina",
          late: true,
          assigned_to: null,
          assigned_name: null,
          done_by_name: null,
        },
      ],
      cleaners: [],
    };
    const cleaning = vi.fn(() => Promise.resolve(day));
    const finishTask = vi.fn(() => Promise.resolve(day));
    show({
      api: fakeApi({ cleaning, finishTask }),
      capabilities: new Set([...DESK, "short_stays.housekeeping"]),
    });
    fireEvent.click(await screen.findByRole("link", { name: "Housekeeping" }));
    expect(await screen.findByText("Daily clean")).toBeInTheDocument();
    expect(cleaning).toHaveBeenCalledWith("p-1", "2026-11-04");
    expect(screen.getByText("2 to do")).toBeInTheDocument();
    expect(screen.getByText("Due 03/11/2026")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Do the room check" }),
    ).toHaveAttribute("href", "#/shortstays/st%3Ab-9");
    fireEvent.click(screen.getByRole("button", { name: "Not cleaned today" }));
    fireEvent.click(screen.getByRole("button", { name: "Not cleaned today" }));
    expect(
      await screen.findByText("Say why the room is not cleaned today."),
    ).toBeInTheDocument();
    expect(finishTask).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Why it is not cleaned/), {
      target: { value: "Do not disturb" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Not cleaned today" }));
    await waitFor(() => {
      expect(finishTask).toHaveBeenCalledWith("p-1", "t-1", {
        skip: true,
        note: "Do not disturb",
      });
    });
    fireEvent.click(screen.getByRole("button", { name: /Next day/ }));
    await waitFor(() => {
      expect(cleaning).toHaveBeenLastCalledWith("p-1", "2026-11-05");
    });
  });

  it("TEST-FE-1614 cancels with a reason and says the money comes back as credit", async () => {
    const early: Booking = {
      ...BOOKING,
      check_in_on: "2026-11-10",
      check_out_on: "2026-11-12",
      free_cancel_until: "2026-11-08",
      payment: "PAID",
      invoice: INVOICE,
    };
    const step = vi.fn(() =>
      Promise.resolve({
        ...early,
        status: "CANCELLED" as const,
        cancel_reason: "Flight changed",
        version: 2,
        cancellation: {
          kind: "CANCELLED" as const,
          free: true,
          paid_usd_cents: 6090,
          back_usd_cents: 6090,
          kept_usd_cents: 0,
        },
      }),
    );
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(early)), step }),
      capabilities: new Set([...DESK, "customers.read"]),
    });
    go("#/shortstays/st:b-1");
    const card = within(await screen.findByRole("region", { name: "Cancel" }));
    expect(
      card.getByText(
        "Free cancel until 08/11/2026 at 23:59: the money paid comes back.",
      ),
    ).toBeInTheDocument();
    // Not the check-in day yet: no "did not come".
    expect(
      card.queryByRole("button", { name: "The guest did not come" }),
    ).toBeNull();
    fireEvent.click(card.getByRole("button", { name: "Cancel the booking" }));
    expect(card.getByText("Say why.")).toBeInTheDocument();
    expect(step).not.toHaveBeenCalled();
    fireEvent.change(card.getByLabelText(/Why/), {
      target: { value: "Flight changed" },
    });
    fireEvent.click(card.getByRole("button", { name: "Cancel the booking" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "cancel", {
      version: 1,
      reason: "Flight changed",
    });
    expect(
      await screen.findByText(
        "$60.90 is now the guest's Credit. Give it back with Refund below.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Cancel" })).toBeNull();
    expect(
      screen.getByRole("link", { name: "Open the guest's credit" }),
    ).toHaveAttribute("href", "#/customers/c-1");
  });

  it("TEST-FE-1615 gives credit after a late cancel, up to the money kept", async () => {
    const late: Booking = {
      ...BOOKING,
      status: "NO_SHOW",
      cancel_reason: "Did not come",
      payment: "PAID",
      invoice: INVOICE,
      cancellation: {
        kind: "NO_SHOW",
        free: false,
        paid_usd_cents: 6090,
        back_usd_cents: 0,
        kept_usd_cents: 6090,
      },
    };
    const step = vi.fn(() =>
      Promise.resolve({
        ...late,
        credit: {
          amount_usd_cents: 2000,
          use_by: "2027-05-04",
          note: "Sick",
          left_usd_cents: 2000,
          ended: null,
        },
      }),
    );
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(late)), step }),
      capabilities: new Set([...DESK, "short_stays.credit"]),
    });
    go("#/shortstays/st:b-1");
    expect(await screen.findByText("$60.90 is kept.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Credit \(US\$\)/), {
      target: { value: "70" },
    });
    fireEvent.change(screen.getByLabelText(/^Why/), {
      target: { value: "Sick" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Give credit" }));
    expect(
      screen.getByText("Enter an amount up to $60.90."),
    ).toBeInTheDocument();
    expect(step).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Credit \(US\$\)/), {
      target: { value: "20" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Give credit" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "credit", {
      amount_usd_cents: 2000,
      note: "Sick",
    });
    expect(
      await screen.findByText("$20.00 credit, to use by 04/05/2027."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Give credit" })).toBeNull();
  });

  it("TEST-FE-1628 ends a late-cancel credit after its use-by day", async () => {
    const late: Booking = {
      ...BOOKING,
      status: "NO_SHOW",
      cancel_reason: "Did not come",
      payment: "PAID",
      invoice: INVOICE,
      cancellation: {
        kind: "NO_SHOW",
        free: false,
        paid_usd_cents: 6090,
        back_usd_cents: 0,
        kept_usd_cents: 6090,
      },
      credit: {
        amount_usd_cents: 2000,
        use_by: "2026-10-31",
        note: "Sick",
        left_usd_cents: 1500,
        ended: null,
      },
    };
    const step = vi.fn(() =>
      Promise.resolve({
        ...late,
        credit: {
          ...late.credit,
          left_usd_cents: 0,
          ended: {
            left_usd_cents: 1500,
            invoice_id: "i-9",
            invoice_number: "INV-260009",
            at: "2026-11-04T03:00:00Z",
          },
        },
      } as Booking),
    );
    const creditsDue = vi.fn(() =>
      Promise.resolve([
        {
          booking_id: "b-1",
          booking_number: "ST260001",
          guest_name: "Meas Rina",
          use_by: "2026-10-31",
          left_usd_cents: 1500,
        },
      ]),
    );
    // Without the credit right: no list of credits and no End credit.
    show({ api: fakeApi({ creditsDue }) });
    fireEvent.click(await screen.findByRole("link", { name: "Bookings" }));
    await screen.findByRole("table");
    expect(creditsDue).not.toHaveBeenCalled();
    cleanup();
    show({
      api: fakeApi({
        creditsDue,
        get: vi.fn(() => Promise.resolve(late)),
        step,
      }),
      capabilities: new Set([...DESK, "short_stays.credit"]),
    });
    fireEvent.click(await screen.findByRole("link", { name: "Bookings" }));
    expect(
      await screen.findByText(
        "1 guest credit(s) passed the use-by day. Open each booking and end the credit.",
      ),
    ).toBeInTheDocument();
    const due = screen.getByRole("region", {
      name: "1 guest credit(s) passed the use-by day. Open each booking and end the credit.",
    });
    expect(within(due).getByRole("link", { name: "ST260001" })).toHaveAttribute(
      "href",
      "#/shortstays/st%3Ab-1",
    );
    go("#/shortstays/st:b-1");
    expect(await screen.findByText("$15.00 left to use.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "End credit" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "credit/end", null);
    expect(
      await screen.findByText(
        "Credit ended: $15.00 became income (Invoice INV-260009).",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End credit" })).toBeNull();
  });

  it("TEST-FE-1616 links the guest's Lease draft for $50 off the first month", async () => {
    const inside: Booking = {
      ...BOOKING,
      status: "CHECKED_IN",
      payment: "PAID",
      invoice: INVOICE,
      lease_drafts: [
        {
          lease_id: "l-9",
          unit_number: "U503",
          start_date: "2026-12-01",
          monthly_rent_usd_cents: 40500,
        },
      ],
    };
    const step = vi.fn(() =>
      Promise.resolve({
        ...inside,
        lease_drafts: [],
        lease_offer: {
          lease_id: "l-9",
          off_usd_cents: 5000,
          lease_status: "DRAFTED",
          start_date: "2026-12-01",
          unit_number: "U503",
        },
      }),
    );
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(inside)), step }),
    });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByRole("heading", { name: "Change to a Lease" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New Lease" })).toHaveAttribute(
      "href",
      "#/leases/new",
    );
    expect(screen.getByLabelText("Lease draft")).toHaveValue("l-9");
    fireEvent.click(screen.getByRole("button", { name: "Link the Lease" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "lease", {
      lease_id: "l-9",
    });
    expect(
      await screen.findByText(
        "Linked to the Lease for U503: $50.00 off the first month.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open the Lease" }),
    ).toHaveAttribute("href", "#/leases/l-9");
  });

  it("TEST-FE-1618 shows a booking site's nights, and a clash with our own booking", async () => {
    const held = (from: string, days: number): StayCalendar => {
      const found = calendar(from, days);
      return {
        ...found,
        units: found.units.map((unit) =>
          unit.unit_id !== "u-501"
            ? unit
            : {
                ...unit,
                site_holds: [
                  {
                    hold_id: "h-1",
                    site_name: "Agoda",
                    start_on: "2026-11-07",
                    end_on: "2026-11-10",
                    clash: true,
                  },
                ],
              },
        ),
      };
    };
    show({
      api: fakeApi({
        calendar: vi.fn((_: string, from: string, days: number) =>
          Promise.resolve(held(from, days)),
        ),
      }),
    });
    const table = await screen.findByRole("table");
    const u501 = within(table).getByRole("row", { name: /U501/ });
    // 07/11 is our guest's last night and Agoda's first: a clash.
    const clash = within(u501).getAllByRole("cell")[2];
    expect(clash).toHaveClass("ss-clash");
    expect(clash).toHaveAttribute(
      "title",
      "Agoda also has these nights: check both bookings.",
    );
    // Then Agoda's own nights, one bar closed for every other booking.
    expect(within(u501).getAllByText("Agoda")).toHaveLength(1);
  });

  it("TEST-FE-1619 sets up a booking site's calendar link and turns it off", async () => {
    const link = {
      calendar_id: "c-1",
      unit_id: "u-501",
      unit_number: "U501",
      site_name: "Agoda",
      import_url: "https://agoda.example/ical/1",
      active: true,
      last_read_at: "2026-11-04T03:00:00Z",
      last_read_ok: false,
      last_error: "The site answered 404",
      version: 2,
      holds: 0,
    };
    const siteCalendars = vi.fn(() => Promise.resolve([link]));
    const saveSiteCalendar = vi.fn(() => Promise.resolve(link));
    // Owner 13/11/2026 evening: the links are a Settings tab now (SettingsPage).
    render(
      <SiteCalendars
        api={fakeApi({ siteCalendars, saveSiteCalendar })}
        language="en"
        propertyId="p-1"
        today="2026-11-04"
      />,
    );
    expect(
      await screen.findByText("The site answered 404"),
    ).toBeInTheDocument();
    expect(screen.getByText("Could not read")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add link" }));
    expect(
      screen.getByText(
        "Choose the room and the site, and paste a link that starts with https://.",
      ),
    ).toBeInTheDocument();
    expect(saveSiteCalendar).not.toHaveBeenCalled();
    fireEvent.change(byId("sc-unit"), {
      target: { value: "u-503" },
    });
    fireEvent.change(byId("sc-site"), {
      target: { value: "Airbnb" },
    });
    fireEvent.change(byId("sc-url"), {
      target: { value: " https://airbnb.example/cal.ics " },
    });
    const reads = siteCalendars.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Add link" }));
    expect(saveSiteCalendar).toHaveBeenCalledWith("p-1", {
      unit_id: "u-503",
      site_name: "Airbnb",
      import_url: "https://airbnb.example/cal.ics",
      active: true,
    });
    await waitFor(() => {
      expect(siteCalendars).toHaveBeenCalledTimes(reads + 1);
    });
    fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(saveSiteCalendar).toHaveBeenLastCalledWith("p-1", {
      calendar_id: "c-1",
      version: 2,
      site_name: "Agoda",
      import_url: "https://agoda.example/ical/1",
      active: false,
    });
  });

  it("TEST-FE-1620 hides Booking sites without the approve right", async () => {
    show();
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Online/ })).toBeNull();
  });

  it("TEST-FE-1621 warns that a booking site holds the nights, except for that site's own guest", async () => {
    go("#/shortstays/new:u-503:2026-11-06");
    const hold = {
      hold_id: "h-1",
      site_name: "Agoda",
      start_on: "2026-11-06",
      end_on: "2026-11-08",
      clash: false,
    };
    show({
      api: fakeApi({
        price: vi.fn(() => Promise.resolve(price0({ site_holds: [hold] }))),
      }),
    });
    const warning =
      "Booked on Agoda, 06/11/2026 to 08/11/2026. Only a booking from Agoda may take these nights.";
    expect(await screen.findByText(warning)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Booked by/), {
      target: { value: "BOOKING_SITE" },
    });
    fireEvent.change(byId("sb-site"), {
      target: { value: "Agoda" },
    });
    await waitFor(() => {
      expect(screen.queryByText(warning)).toBeNull();
    });
  });

  it("TEST-FE-1622 shows the guest's history and notes, and adds a problem-guest note", async () => {
    const history = guestHistory({
      stays: [
        {
          booking_id: "b-0",
          booking_number: "ST250009",
          unit_number: "U503",
          check_in_on: "2025-12-01",
          check_out_on: "2025-12-03",
          status: "CHECKED_OUT",
          source: "WALK_IN",
          site_name: null,
          total_usd_cents: 5200,
        },
      ],
      stays_done: 1,
      nights_done: 2,
      spent_usd_cents: 5200,
      returning: true,
    });
    const addGuestNote = vi.fn(() =>
      Promise.resolve({
        ...history,
        problem_guest: true,
        notes: [
          {
            note: "Loud music at night",
            problem_guest: true,
            created_at: "2026-11-04T04:00:00Z",
            booking_number: "ST260001",
          },
        ],
      }),
    );
    show({
      api: fakeApi({
        get: vi.fn(() =>
          Promise.resolve({ ...BOOKING, returning_guest: true }),
        ),
        guest: vi.fn(() => Promise.resolve(history)),
        addGuestNote,
      }),
    });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByText("1 stay done · 2 nights · $52.00 spent"),
    ).toBeInTheDocument();
    expect(screen.getByText("Returning guest")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ST250009" })).toHaveAttribute(
      "href",
      "#/shortstays/st%3Ab-0",
    );
    expect(screen.getByText("No notes yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(screen.getByText("Write the note first.")).toBeInTheDocument();
    expect(addGuestNote).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("New note"), {
      target: { value: " Loud music at night " },
    });
    fireEvent.click(screen.getByLabelText(/^Problem guest/));
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(addGuestNote).toHaveBeenCalledWith("p-1", BOOKING.customer_id, {
      note: "Loud music at night",
      problem_guest: true,
      booking_id: "b-1",
    });
    expect(await screen.findByText("Loud music at night")).toBeInTheDocument();
    expect(screen.getAllByText("Problem guest").length).toBeGreaterThan(0);
  });

  it("TEST-FE-1623 lets only the Owner or Manager give an extra discount with a reason", async () => {
    const step = vi.fn(() => Promise.resolve(BOOKING));
    show({ api: fakeApi({ step }) });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByRole("heading", { name: "Payment" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Extra discount" }),
    ).toBeNull();
    cleanup();
    show({
      api: fakeApi({ step }),
      capabilities: new Set([...DESK, "short_stays.approve"]),
    });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByRole("heading", { name: "Extra discount" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Give the discount" }));
    expect(
      screen.getByText("Enter an amount less than the stay and a reason."),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Discount ($)"), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: " Stayed last year " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Give the discount" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "discount", {
      version: BOOKING.version,
      amount_usd_cents: 1000,
      reason: "Stayed last year",
    });
  });

  it("TEST-FE-1624 asks for a review once after the check-out", async () => {
    const out: Booking = {
      ...BOOKING,
      status: "CHECKED_OUT",
      payment: "PAID",
      invoice: INVOICE,
      source: "BOOKING_SITE",
      site_name: "Agoda",
    };
    const step = vi.fn(() =>
      Promise.resolve({ ...out, review_asked_at: "2026-11-04T05:00:00Z" }),
    );
    show({ api: fakeApi({ get: vi.fn(() => Promise.resolve(out)), step }) });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByRole("heading", { name: "Ask for a review" }),
    ).toBeInTheDocument();
    expect(
      screen.getByDisplayValue(
        "Thank you for staying with CHETANA Residence, Lim! If you liked your stay, please leave us a short review on Google Maps: https://search.google.com/local/writereview?placeid=ChIJH87t_fRTCTER6g_sn780yZI",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark as asked" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "review", null);
    expect(await screen.findByText(/^Review asked for on/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark as asked" })).toBeNull();
  });

  it("TEST-FE-2177 has no Quotes tab; New booking copies the price message for the guest and still keeps it as a quote", async () => {
    // Leasing batch (owner 13/11/2026): the Quotes tab is gone.
    show({ capabilities: new Set([...DESK, "short_stays.approve"]) });
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Quotes" })).toBeNull();
    cleanup();
    const made: StayQuote = {
      quote_id: "q-1",
      quote_number: "SQ260001",
      unit_id: "u-503",
      unit_number: "U503",
      unit_type: "ONE_BEDROOM",
      guest_name: "Sok Chenda",
      guest_contact: "@chenda",
      guest_count: 2,
      check_in_on: "2026-11-06",
      check_out_on: "2026-11-07",
      nights: 1,
      total_usd_cents: 2600,
      lines: LINES,
      made_on: "2026-11-04",
      check_in_time: 840,
      check_out_time: 720,
      deposit_usd_cents: 5000,
      month_only_usd_cents: 40500,
      monthly_rent_usd_cents: 26900,
    };
    const quote = vi.fn(() => Promise.resolve(made));
    go("#/shortstays/new:u-503:2026-11-06");
    show({ api: fakeApi({ quote }) });
    await screen.findByText("1 × night $26.00");
    const copy = screen.getByRole("button", { name: "Copy price message" });
    // Without a guest name there is no message yet.
    fireEvent.click(copy);
    expect(
      screen.getByText("Type the guest's name first."),
    ).toBeInTheDocument();
    expect(quote).not.toHaveBeenCalled();
    fireEvent.change(byId("sb-name"), { target: { value: " Sok Chenda " } });
    fireEvent.change(screen.getByLabelText(/^Phone/), {
      target: { value: "@chenda" },
    });
    fireEvent.change(byId("sb-guests"), { target: { value: "2" } });
    fireEvent.click(copy);
    expect(quote).toHaveBeenCalledWith("p-1", {
      unit_id: "u-503",
      guest_name: "Sok Chenda",
      guest_contact: "@chenda",
      guest_count: 2,
      check_in_on: "2026-11-06",
      check_out_on: "2026-11-07",
    });
    const message = await screen.findByDisplayValue(
      /^CHETANA Residence: quote SQ260001/,
    );
    expect((message as HTMLTextAreaElement).value).toContain(
      "06/11/2026 to 07/11/2026, 1 night\nTotal $26.00\nCheck-in from 14:00, check-out by 12:00.",
    );
    expect((message as HTMLTextAreaElement).value).toContain(
      "Staying longer? 1 month only: $405.00. A Lease of 6 or 12 months: $269.00 a month.",
    );
    // A change of guests makes the message out of date, so it goes.
    fireEvent.change(byId("sb-guests"), { target: { value: "3" } });
    expect(
      screen.queryByDisplayValue(/^CHETANA Residence: quote SQ260001/),
    ).toBeNull();
  });

  it("TEST-FE-1626 tells the desk about a returning guest's thank-you and a problem guest", async () => {
    go("#/shortstays/new:u-503:2026-11-06");
    const guest = vi.fn(() =>
      Promise.resolve(
        guestHistory({
          returning: true,
          problem_guest: true,
          notes: [
            {
              note: "Left without paying for drinks",
              problem_guest: true,
              created_at: "2026-10-01T04:00:00Z",
              booking_number: "ST250009",
            },
          ],
        }),
      ),
    );
    show({ api: fakeApi({ guest }) });
    await screen.findByText("1 × night $26.00");
    // Typing the phone shows the matching Customers (owner test 06/11/2026).
    fireEvent.change(screen.getByLabelText(/^Phone/), {
      target: { value: "010" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Choose" }));
    expect(
      await screen.findByText(
        "Returning guest: $3.00 thank-you comes off a direct booking.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Problem guest. Read the notes before you book: Left without paying for drinks",
      ),
    ).toBeInTheDocument();
    expect(guest).toHaveBeenCalledWith("p-1", "c-1");
  });

  it("TEST-FE-1627 shows the weekly report to the Manager and records a tenant's complaint", async () => {
    const complaint = vi.fn(() => Promise.resolve());
    const api = fakeApi({ complaint });
    // Owner 13/11/2026 evening: the report is in Reports now (ReportsPage), not a tab here.
    show({ capabilities: new Set([...DESK, "short_stays.approve"]) });
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Weekly report" })).toBeNull();
    cleanup();
    render(
      <WeekReportView
        api={api}
        language="en"
        may={() => true}
        propertyId="p-1"
        today="2026-11-04"
      />,
    );
    // Today is Wednesday 04/11: the week from Monday 02/11, no next week yet.
    expect(api.weekReport).toHaveBeenCalledWith("p-1", "2026-11-02");
    expect(
      await screen.findByText("21.4%", { selector: "b" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("3 of 14 unit-nights paid · before the test 40.0%"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("$53.90").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Next week" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Week before" }));
    expect(api.weekReport).toHaveBeenLastCalledWith("p-1", "2026-10-26");
    await screen.findByText("21.4%", { selector: "b" });
    fireEvent.click(screen.getByRole("button", { name: "Save complaint" }));
    expect(screen.getByText("Write what happened first.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("What happened"), {
      target: { value: " Noise after midnight " },
    });
    fireEvent.change(screen.getByLabelText("Tenant's Unit"), {
      target: { value: "u-501" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save complaint" }));
    expect(complaint).toHaveBeenCalledWith("p-1", {
      what: "Noise after midnight",
      unit_id: "u-501",
    });
  });

  it("TEST-FE-1605 speaks Khmer and hides New booking without the front-desk right", async () => {
    show({ capabilities: new Set(["short_stays.read"]), language: "km" });
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ប្រតិទិន" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /ការកក់ថ្មី/ })).toBeNull();
    expect(screen.getAllByText("ទំនេរ").length).toBeGreaterThan(0);
  });

  it("TEST-FE-1629 shows the real reason when a booking is refused", () => {
    const refused = (detail: string) =>
      bookingRefusal("en", new ShortStaysError(409, detail));
    expect(
      refused("The Unit is already booked on one of these nights"),
    ).toMatch(/Someone has just booked/);
    expect(
      refused("The Unit cannot be booked for these nights: LEASE"),
    ).toMatch(/cannot be booked in this Unit/);
    expect(
      refused("The Unit has no monthly Rent to price a short stay from"),
    ).toMatch(/no monthly Rent/);
    expect(refused("The nights are booked on Agoda")).toBe(
      "This booking was not made: The nights are booked on Agoda",
    );
  });

  it("TEST-FE-1630 keeps a Unit without a monthly Rent out of a new booking", async () => {
    go("#/shortstays/new:u-503:2026-11-06");
    const api = fakeApi({
      calendar: vi.fn((_: string, from: string, days: number) => {
        const found = calendar(from, days);
        return Promise.resolve({
          ...found,
          units: found.units.map((unit) =>
            unit.unit_id === "u-501"
              ? { ...unit, monthly_rent_usd_cents: null }
              : unit,
          ),
        });
      }),
    });
    show({ api });
    const option = await screen.findByRole("option", {
      name: "U501 · Studio · no monthly Rent yet",
    });
    expect(option).toBeDisabled();
  });

  it("TEST-FE-1631 lists a guest who owes a stay Invoice in Receive payment", () => {
    const owed = (customer: string, status: string, cents: number) =>
      ({
        customer_id: customer,
        status,
        outstanding_balance: { minor_units: String(cents) },
      }) as unknown as InvoiceResource;
    const data = {
      invoices: [
        owed("guest", "UNPAID", 6090),
        owed("paid-guest", "PAID", 0),
        owed("draft-guest", "DRAFT", 6090),
      ],
      customerLeases: new Map([["tenant", "lease-1"]]),
    } as unknown as InvoicesData;
    expect(payerIds(data).sort()).toEqual(["guest", "tenant"]);
  });

  it("TEST-FE-1850 names a stay Invoice Short stay, not Miscellaneous", () => {
    const stay = {
      category: "MISCELLANEOUS_CHARGES" as const,
      short_stay: "SHORT_STAY" as const,
    };
    expect(ivt("en", invoiceType(stay))).toBe("Short stay");
    expect(ivt("km", invoiceType(stay))).toBe("ការស្នាក់នៅខ្លី");
    expect(
      ivt(
        "en",
        invoiceType({ category: "MISCELLANEOUS_CHARGES", short_stay: null }),
      ),
    ).toBe("Other charges");
    expect(pyt("en", "SHORT_STAY_DAMAGE")).toBe("Short-stay damage");
    expect(
      lineWords({
        kind: "INVOICE",
        invoiceId: "i-1",
        invoiceNumber: "INV260011",
        category: "SHORT_STAY",
        dueDate: null,
        depositType: null,
        amount: 6090,
      }),
    ).toEqual(["ថ្លៃស្នាក់នៅ", "Short stay", "INV260011"]);
  });

  it("TEST-FE-1852 gives the money back after a free cancel with the Refund button", async () => {
    const cancelled: Booking = {
      ...BOOKING,
      status: "CANCELLED",
      cancel_reason: "Flight changed",
      payment: "PAID",
      invoice: INVOICE,
      cancellation: {
        kind: "CANCELLED",
        free: true,
        paid_usd_cents: 4640,
        back_usd_cents: 4640,
        kept_usd_cents: 0,
      },
      refund: {
        credits: [{ credit_id: "cr-1", left_usd_cents: 4640 }],
        left_usd_cents: 4640,
        waiting_usd_cents: 0,
        refunded_usd_cents: 0,
      },
    };
    const waiting: Booking = {
      ...cancelled,
      refund: {
        credits: [{ credit_id: "cr-1", left_usd_cents: 4640 }],
        left_usd_cents: 4640,
        waiting_usd_cents: 4640,
        refunded_usd_cents: 0,
      },
    };
    const get = vi
      .fn()
      .mockResolvedValueOnce(cancelled)
      .mockResolvedValue(waiting);
    const refund = vi.fn(() => Promise.resolve());
    show({
      api: fakeApi({
        get,
        refund,
        refundMethods: vi.fn(() =>
          Promise.resolve([
            { id: "m-cash", name: "Cash" },
            { id: "m-aba", name: "ABA bank" },
          ]),
        ),
      }),
      capabilities: new Set([...DESK, "refunds.create", "financial.approve"]),
    });
    go("#/shortstays/st:b-1");
    const card = within(
      await screen.findByRole("region", { name: "Give the money back" }),
    );
    const button = card.getByRole("button", { name: "Refund $46.40" });
    await waitFor(() => {
      expect(card.getByLabelText(/How it goes back/)).toHaveValue("m-cash");
    });
    fireEvent.change(card.getByLabelText(/How it goes back/), {
      target: { value: "m-aba" },
    });
    fireEvent.click(button);
    expect(card.getByText("Enter the reference.")).toBeInTheDocument();
    expect(refund).not.toHaveBeenCalled();
    fireEvent.change(card.getByLabelText(/Reference/), {
      target: { value: "ABA 778899" },
    });
    fireEvent.click(button);
    await waitFor(() => {
      expect(refund).toHaveBeenCalledWith(
        "p-1",
        {
          credit_id: "cr-1",
          amount_usd_cents: 4640,
          reason: "Free cancel ST260001: the money paid goes back",
          refund_method_id: "m-aba",
          reference_note: "ABA 778899",
        },
        expect.any(String),
      );
    });
    expect(
      await screen.findByText(/Refund of \$46\.40 waits for approval\./),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open Approvals" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Refund \$/ })).toBeNull();
  });

  it("TEST-FE-1853 tells a desk without the Refund right to ask a Manager", async () => {
    const cancelled: Booking = {
      ...BOOKING,
      status: "CANCELLED",
      refund: {
        credits: [{ credit_id: "cr-1", left_usd_cents: 4640 }],
        left_usd_cents: 4640,
        waiting_usd_cents: 0,
        refunded_usd_cents: 0,
      },
    };
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(cancelled)) }),
      capabilities: DESK,
    });
    go("#/shortstays/st:b-1");
    expect(
      await screen.findByText(
        "Your account may not make a Refund. Ask a Manager.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Refund \$/ })).toBeNull();
  });

  it("TEST-FE-1851 shows matching Customers while the guest's name is typed", async () => {
    go("#/shortstays/new:u-503:2026-11-06");
    const { customerApi } = show({
      capabilities: new Set([...DESK, "customers.manage"]),
    });
    expect(screen.queryByLabelText("Find a guest by name or phone")).toBeNull();
    fireEvent.change(await screen.findByLabelText(/^Full name/), {
      target: { value: "Lim" },
    });
    expect(
      await screen.findByText(
        "Already a Customer? Choose them instead of adding again:",
      ),
    ).toBeInTheDocument();
    expect(customerApi.list).toHaveBeenLastCalledWith("p-1", {
      query: "Lim",
      active: true,
    });
    fireEvent.click(screen.getByRole("button", { name: "Choose" }));
    expect(
      await screen.findByRole("button", { name: "Change guest" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/^ID or passport number/)).toBeNull();
  });

  it('TEST-FE-1946 (owner 12/11/2026: "check all card is link to correct place") the Bookings list has a status row with a count each; "?show=booked" and "?show=checked_in" open the list on that status, and a status chosen by hand is kept in the address', async () => {
    const stay = (id: string, number: string, status: Booking["status"]) => ({
      ...BOOKING,
      booking_id: id,
      booking_number: number,
      status,
    });
    const api = fakeApi({
      list: vi.fn(() =>
        Promise.resolve([
          stay("b-1", "ST260001", "BOOKED"),
          stay("b-2", "ST260002", "BOOKED"),
          stay("b-3", "ST260003", "CHECKED_IN"),
          stay("b-4", "ST260004", "CANCELLED"),
        ]),
      ),
    });
    const numbers = () =>
      screen
        .getAllByRole("row")
        .slice(1)
        .map((row) => within(row).getAllByRole("link")[0]?.textContent);

    // Home's "Short stays checked in" card.
    window.location.hash = "#/shortstays?show=checked_in";
    show({ api });
    const row = await screen.findByRole("group", { name: "Status" });
    expect(
      screen
        .getByRole("link", { name: "Bookings" })
        .getAttribute("aria-current"),
    ).toBe("page");
    // Booked and Checked in always show; another status shows only when a booking has it.
    expect(
      within(row)
        .getAllByRole("button")
        .map((button) => [
          button.textContent,
          button.getAttribute("aria-pressed"),
        ]),
    ).toEqual([
      ["All 4", "false"],
      ["Booked 2", "false"],
      ["Checked in 1", "true"],
      ["Cancelled 1", "false"],
    ]);
    expect(numbers()).toEqual(["ST260003"]);
    expect(screen.getByText("1 booking")).toBeInTheDocument();

    // Home's "Short stay bookings" card, opened while the page is on screen.
    go("#/shortstays?show=booked");
    await waitFor(() => {
      expect(numbers()).toEqual(["ST260001", "ST260002"]);
    });
    expect(screen.getByText("2 bookings")).toBeInTheDocument();

    // By hand: the address follows, and All gives the plain address again.
    fireEvent.click(within(row).getByRole("button", { name: "Cancelled 1" }));
    expect(numbers()).toEqual(["ST260004"]);
    // Leasing batch: the address keeps the Bookings tab, so the menu's sub-item stays marked.
    expect(window.location.hash).toBe("#/shortstays?show=cancelled&tab=list");
    fireEvent.click(within(row).getByRole("button", { name: "All 4" }));
    expect(numbers()).toHaveLength(4);
    expect(window.location.hash).toBe("#/shortstays?tab=list");
    cleanup();

    // A status no booking has says so, and the row still offers the others.
    window.location.hash = "#/shortstays?show=checked_in";
    show({
      api: fakeApi({
        list: vi.fn(() => Promise.resolve([stay("b-1", "ST260001", "BOOKED")])),
      }),
    });
    expect(
      await screen.findByText("No bookings with this status."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Booked 1" }),
    ).toBeInTheDocument();
  });

  // Leasing batch (owner 13/11/2026, design "Short-stay calendar samples", FINAL).
  describe("Calendar as a booking chart", () => {
    /** b-1 arrives today in U501; b-3 leaves today from U503. */
    function deskDay(from: string, days: number): StayCalendar {
      const found = calendar(from, days);
      const [u501, u503] = found.units;
      if (u501 === undefined || u503 === undefined) throw new Error("fixture");
      return {
        ...found,
        units: [
          {
            ...u501,
            bookings: [
              {
                booking_id: "b-1",
                booking_number: "ST260001",
                guest_name: "Lim Dara",
                status: "BOOKED",
                source: "WALK_IN",
                check_in_on: "2026-11-04",
                check_out_on: "2026-11-07",
                paid: true,
              },
            ],
          },
          {
            ...u503,
            bookings: [
              {
                booking_id: "b-3",
                booking_number: "ST260003",
                guest_name: "Sok Chea",
                status: "CHECKED_IN",
                source: "WALK_IN",
                check_in_on: "2026-11-01",
                check_out_on: "2026-11-04",
                paid: true,
              },
            ],
          },
        ],
      };
    }
    const LEAVING: Booking = {
      ...BOOKING,
      booking_id: "b-3",
      booking_number: "ST260003",
      guest_name: "Sok Chea",
      unit_id: "u-503",
      unit_number: "U503",
      status: "CHECKED_IN",
      check_in_on: "2026-11-01",
      check_out_on: "2026-11-04",
      version: 4,
    };
    const READY: Booking = {
      ...TODAY_STAY,
      payment: "PAID",
      deposit: DEPOSIT,
      guest_has_id: true,
      unit_status: "VACANT",
    };
    function deskApi(arriving: Booking): ShortStaysApi {
      return fakeApi({
        calendar: vi.fn((_: string, from: string, days: number) =>
          Promise.resolve(deskDay(from, days)),
        ),
        get: vi.fn((_: string, id: string) =>
          Promise.resolve(id === "b-3" ? LEAVING : arriving),
        ),
      });
    }

    it("TEST-FE-2178 shows a week, 2 weeks or a month; Earlier and Later move a week, or a month on Month", async () => {
      const { api } = show();
      await screen.findByRole("table");
      const views = screen.getByRole("group", { name: "How many days" });
      expect(
        within(views).getByRole("button", { name: "2 weeks" }),
      ).toHaveAttribute("aria-pressed", "true");
      fireEvent.click(within(views).getByRole("button", { name: "Week" }));
      expect(
        await screen.findByText("04/11/2026 to 10/11/2026"),
      ).toBeInTheDocument();
      expect(api.calendar).toHaveBeenCalledWith("p-1", "2026-11-04", 7);
      fireEvent.click(
        within(screen.getByRole("group", { name: "How many days" })).getByRole(
          "button",
          { name: "Month" },
        ),
      );
      expect(
        await screen.findByText("04/11/2026 to 03/12/2026"),
      ).toBeInTheDocument();
      expect(api.calendar).toHaveBeenCalledWith("p-1", "2026-11-04", 30);
      fireEvent.click(screen.getByRole("button", { name: /Later/ }));
      expect(
        await screen.findByText("04/12/2026 to 02/01/2027"),
      ).toBeInTheDocument();
      expect(api.calendar).toHaveBeenCalledWith("p-1", "2026-12-04", 30);
    });

    it("TEST-FE-2179 counts the free rooms of each Unit type each night and shows the room's own state under its number", async () => {
      show({
        api: fakeApi({
          calendar: vi.fn((_: string, from: string, days: number) => {
            const found = calendar(from, days);
            return Promise.resolve({
              ...found,
              units: found.units.map((unit) =>
                unit.unit_id === "u-501"
                  ? { ...unit, status: "CLEANING" }
                  : unit,
              ),
            });
          }),
        }),
      });
      const table = await screen.findByRole("table");
      const studios = within(table).getByRole("row", { name: /^Studio/ });
      const nights = within(studios).getAllByRole("cell");
      // 04/11 U501 is free; 05/11 to 07/11 Lim Dara has it.
      expect(nights[0]).toHaveTextContent("1 free");
      expect(nights[1]).toHaveTextContent("Full");
      expect(nights[1]).toHaveClass("full");
      const u501 = within(table).getByRole("row", { name: /U501/ });
      expect(
        within(u501).getByRole("rowheader", { name: "U501Needs cleaning" }),
      ).toBeInTheDocument();
      const u503 = within(table).getByRole("row", { name: /U503/ });
      expect(within(u503).getByText("Ready")).toBeInTheDocument();
    });

    it("TEST-FE-2180 shows the quick numbers: full tonight, arriving, leaving, not paid; booking sites only to the Owner and the Manager", async () => {
      show();
      const full = (await screen.findByText("Tonight")).closest("div");
      // Owner 14/11/2026: "Tonight" shows the Units taken (0), with "2 free" under it.
      expect(full?.querySelector("b")).toHaveTextContent(/^0$/);
      expect(full).toHaveTextContent("2 free");
      // Owner 13/11/2026 evening: Not paid yet opens the Not paid panel from the right.
      const unpaid = screen.getByRole("button", { name: /Not paid yet/ });
      expect(unpaid).toHaveTextContent("1");
      expect(unpaid).toHaveClass("warn");
      fireEvent.click(unpaid);
      const panel = screen.getByRole("dialog", { name: "Not paid" });
      expect(
        within(panel).getByRole("link", {
          name: /Lim Dara · U501 · arrives 05\/11\/2026/,
        }),
      ).toHaveAttribute("href", "#/shortstays/st%3Ab-1");
      fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("link", { name: /Online/ }),
      ).not.toBeInTheDocument();
      cleanup();
      window.location.hash = "#/shortstays";
      show({
        api: fakeApi({
          siteCalendars: vi.fn(() =>
            Promise.resolve([
              {
                calendar_id: "c-1",
                unit_id: "u-501",
                unit_number: "U501",
                site_name: "Agoda",
                import_url: "https://agoda.example/ical/1",
                active: true,
                last_read_at: "2026-11-04T03:00:00Z",
                last_read_ok: false,
                last_error: "The site answered 404",
                version: 2,
                holds: 0,
              },
            ]),
          ),
        }),
        capabilities: new Set([...DESK, "short_stays.approve"]),
      });
      const sites = await screen.findByRole("link", { name: /Online/ });
      expect(sites).toHaveTextContent("Agoda (U501): could not read");
      // Owner 14/11/2026: the last read time, short, at the top right.
      expect(sites.querySelector("b")).toHaveTextContent("04/11 10:00");
      expect(sites).toHaveClass("warn");
      expect(sites).toHaveAttribute("href", "#/settings/sites");
    });

    it("TEST-FE-2181 shows the step still missing before a check-in, in the desk's order", () => {
      expect(nextStep({ ...READY, payment: "NOT_BILLED" })).toBe("pay");
      expect(nextStep({ ...READY, payment: "PAID_ON_SITE" })).toBe("in");
      expect(nextStep({ ...READY, deposit: null })).toBe("deposit");
      expect(
        nextStep({ ...READY, deposit: { ...DEPOSIT, status: "RETURNED" } }),
      ).toBe("deposit");
      expect(nextStep({ ...READY, guest_has_id: false })).toBe("id");
      expect(nextStep({ ...READY, unit_status: "CLEANING" })).toBe("room");
      expect(nextStep(READY)).toBe("in");
    });

    it("TEST-FE-2182 a guest who has not paid gets Pay, which opens the booking; a room not ready opens Housekeeping", async () => {
      show({ api: deskApi({ ...READY, payment: "NOT_BILLED" }) });
      fireEvent.click(
        await screen.findByRole("button", { name: /Arriving today/ }),
      );
      const today = screen.getByRole("dialog", {
        name: "Today · 04/11/2026",
      });
      expect(
        await within(today).findByRole("link", { name: "Pay" }),
      ).toHaveAttribute("href", "#/shortstays/st%3Ab-1");
      expect(within(today).getByText("Not paid")).toHaveClass("ss-warn");
      expect(
        within(today).queryByRole("button", { name: "Check in" }),
      ).not.toBeInTheDocument();
      cleanup();
      window.location.hash = "#/shortstays";
      show({ api: deskApi({ ...READY, unit_status: "CLEANING" }) });
      fireEvent.click(
        await screen.findByRole("button", { name: /Arriving today/ }),
      );
      expect(
        await screen.findByRole("link", { name: "Room not ready" }),
      ).toHaveAttribute("href", "#/shortstays?tab=clean");
    });

    it("TEST-FE-2183 checks a ready guest in from the Today panel after both ticks, and the Calendar reads again", async () => {
      const api = deskApi(READY);
      show({ api });
      fireEvent.click(
        await screen.findByRole("button", { name: /Arriving today/ }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Check in" }));
      const dialog = await screen.findByRole("dialog", {
        name: "Check in Lim Dara",
      });
      const calls = vi.mocked(api.calendar).mock.calls.length;
      fireEvent.click(within(dialog).getByRole("button", { name: "Check in" }));
      expect(
        await within(dialog).findByText(
          "Tick both boxes: ID copy made and house rules signed.",
        ),
      ).toBeInTheDocument();
      expect(api.step).not.toHaveBeenCalled();
      for (const box of within(dialog).getAllByRole("checkbox"))
        fireEvent.click(box);
      fireEvent.click(within(dialog).getByRole("button", { name: "Check in" }));
      await waitFor(() => {
        expect(api.step).toHaveBeenCalledWith("p-1", "b-1", "check-in", {
          version: 1,
          id_copy_made: true,
          house_rules_signed: true,
        });
      });
      expect(
        await screen.findByText("Lim Dara is checked in."),
      ).toBeInTheDocument();
      await waitFor(() => {
        expect(vi.mocked(api.calendar).mock.calls.length).toBeGreaterThan(
          calls,
        );
      });
    });

    it("TEST-FE-2184 checks a leaving guest out from the Today panel", async () => {
      const api = deskApi(READY);
      show({ api });
      fireEvent.click(
        await screen.findByRole("button", { name: /Leaving today/ }),
      );
      const today = screen.getByRole("dialog", { name: /Today/ });
      expect(await within(today).findByText("Sok Chea")).toBeInTheDocument();
      fireEvent.click(within(today).getByRole("button", { name: "Check out" }));
      const dialog = await screen.findByRole("dialog", {
        name: "Check out Sok Chea",
      });
      fireEvent.click(
        within(dialog).getByRole("button", { name: "Check out" }),
      );
      await waitFor(() => {
        expect(api.step).toHaveBeenCalledWith("p-1", "b-3", "check-out", {
          version: 4,
        });
      });
      expect(
        await screen.findByText("Sok Chea is checked out."),
      ).toBeInTheDocument();
    });

    it("TEST-FE-2185 shows no Check in or Check out button to a person without the desk right", async () => {
      show({
        api: deskApi(READY),
        capabilities: new Set(["short_stays.read"]),
      });
      fireEvent.click(
        await screen.findByRole("button", { name: /Leaving today/ }),
      );
      const today = screen.getByRole("dialog", { name: /Today/ });
      expect(await within(today).findByText("Sok Chea")).toBeInTheDocument();
      expect(
        within(today).queryByRole("button", { name: /Check/ }),
      ).not.toBeInTheDocument();
      // A free night does not open New booking either.
      const table = await screen.findByRole("table");
      expect(
        within(table).queryByRole("link", { name: /New booking/ }),
      ).not.toBeInTheDocument();
    });
  });

  describe("Bookings and Housekeeping (owner 13/11/2026)", () => {
    const stay = (
      id: string,
      number: string,
      guest: string,
      unit: string,
      status: Booking["status"],
    ): Booking => ({
      ...BOOKING,
      booking_id: id,
      booking_number: number,
      guest_name: guest,
      unit_number: unit,
      status,
    });

    it("TEST-FE-2200 the Bookings search finds a guest, booking number or Unit, and the status counts follow it", async () => {
      const api = fakeApi({
        list: vi.fn(() =>
          Promise.resolve([
            stay("b-1", "ST260001", "Sok Dara", "U101", "BOOKED"),
            stay("b-2", "ST260002", "Kim Lina", "U102", "CHECKED_IN"),
            stay("b-3", "ST260003", "Sok Vanna", "U305", "CHECKED_IN"),
          ]),
        ),
      });
      show({ api });
      fireEvent.click(await screen.findByRole("link", { name: "Bookings" }));
      const box = await screen.findByRole("searchbox", {
        name: "Search guest, phone, booking or Unit",
      });
      const numbers = () =>
        screen
          .getAllByRole("row")
          .slice(1)
          .map((row) => within(row).getAllByRole("link")[0]?.textContent);
      expect(numbers()).toEqual(["ST260001", "ST260002", "ST260003"]);
      fireEvent.change(box, { target: { value: "sok" } });
      expect(numbers()).toEqual(["ST260001", "ST260003"]);
      const status = screen.getByRole("group", { name: "Status" });
      expect(
        within(status).getByRole("button", { name: /All/ }),
      ).toHaveTextContent("2");
      fireEvent.change(box, { target: { value: "u305" } });
      expect(numbers()).toEqual(["ST260003"]);
      fireEvent.change(box, { target: { value: "260002" } });
      expect(numbers()).toEqual(["ST260002"]);
    });

    it("TEST-FE-2201 Housekeeping lists a late task first in red, folds done and skipped tasks, and shows no booking number or guest name", async () => {
      const task = (
        id: string,
        unit: string,
        status: "TO_DO" | "DONE" | "SKIPPED",
        late: boolean,
      ) => ({
        task_id: id,
        kind: "DAILY_CLEAN" as const,
        task_on: late ? "2026-11-03" : "2026-11-04",
        status,
        note: null,
        done_at: null,
        unit_id: `u-${unit}`,
        unit_number: unit,
        booking_id: `b-${id}`,
        booking_number: `ST26000${id}`,
        guest_name: "Lim Dara",
        late,
        assigned_to: null,
        assigned_name: null,
        done_by_name: null,
      });
      const day = {
        day: "2026-11-04",
        today: "2026-11-04",
        tasks: [
          task("1", "U501", "TO_DO", false),
          task("2", "U502", "DONE", false),
          task("3", "U503", "TO_DO", true),
        ],
        cleaners: [],
      };
      show({
        api: fakeApi({ cleaning: vi.fn(() => Promise.resolve(day)) }),
        capabilities: new Set([...DESK, "short_stays.housekeeping"]),
      });
      fireEvent.click(
        await screen.findByRole("link", { name: "Housekeeping" }),
      );
      const list = await screen.findByRole("list", { name: "Housekeeping" });
      const rows = within(list).getAllByRole("listitem");
      expect(rows.map((row) => row.textContent)).toEqual([
        expect.stringContaining("U503"),
        expect.stringContaining("U501"),
      ]);
      const [first] = rows;
      if (!first) throw new Error("no Housekeeping rows");
      expect(first).toHaveClass("late");
      expect(within(first).getByText("Late")).toBeInTheDocument();
      // Owner 14/11/2026 01:39: a task shows no booking number or guest name.
      expect(within(first).queryByRole("link")).toBeNull();
      expect(within(list).queryByText(/ST26000|Lim Dara/)).toBeNull();
      expect(screen.getByText("Finished (1)")).toBeInTheDocument();
      const done = screen.getByRole("list", { name: "Finished" });
      expect(done.closest("details")).not.toHaveAttribute("open");
      expect(within(done).getByText("U502")).toBeInTheDocument();
    });

    it("TEST-FE-2203 the Calendar leaves out a Unit leased for every day shown and a Unit not for rent; a Unit whose tenant moves out within the days shown stays", async () => {
      const base = calendar("2026-11-04", 14);
      const [free, laterLease] = base.units;
      if (free === undefined || laterLease === undefined)
        throw new Error("No sample Units");
      const unit = (
        number: string,
        extra: Partial<(typeof base.units)[number]>,
      ) => ({
        ...free,
        unit_id: `u-${number}`,
        unit_number: number,
        bookings: [],
        ...extra,
      });
      const units = [
        free,
        laterLease,
        unit("U601", {
          leases: [
            {
              lease_id: "l-6",
              start_date: "2026-06-01",
              end_date: "2027-05-31",
            },
          ],
        }),
        unit("U602", {
          leases: [
            {
              lease_id: "l-7",
              start_date: "2026-06-01",
              end_date: "2026-11-09",
            },
          ],
        }),
        unit("U603", { for_rent: false }),
      ];
      show({
        api: fakeApi({
          calendar: vi.fn((_: string, from: string, days: number) =>
            Promise.resolve({ ...calendar(from, days), units }),
          ),
        }),
      });
      const table = await screen.findByRole("table");
      expect(
        within(table).getByRole("row", { name: /U501/ }),
      ).toBeInTheDocument();
      expect(
        within(table).getByRole("row", { name: /U503/ }),
      ).toBeInTheDocument();
      expect(
        within(table).getByRole("row", { name: /U602/ }),
      ).toBeInTheDocument();
      expect(within(table).queryByRole("row", { name: /U601/ })).toBeNull();
      expect(within(table).queryByRole("row", { name: /U603/ })).toBeNull();
    });

    it("TEST-FE-2204 (DL-236) the front desk gives a task to a cleaner from the staff list, marks who has no Telegram, has no My tasks, and a finished task names who did it", async () => {
      const task = (
        id: string,
        unit: string,
        extra: Partial<CleaningTask> = {},
      ): CleaningTask => ({
        task_id: id,
        kind: "DAILY_CLEAN",
        task_on: "2026-11-04",
        status: "TO_DO",
        note: null,
        done_at: null,
        unit_id: `u-${unit}`,
        unit_number: unit,
        booking_id: `b-${id}`,
        booking_number: `ST26000${id}`,
        guest_name: "Lim Dara",
        late: false,
        assigned_to: null,
        assigned_name: null,
        done_by_name: null,
        ...extra,
      });
      const cleaners = [
        {
          employee_id: "e-1",
          name: "Chan Thida",
          name_km: "ចាន់ ធីតា",
          telegram: true,
        },
        {
          employee_id: "e-2",
          name: "Sok Mony",
          name_km: "សុខ មុនី",
          telegram: false,
        },
      ];
      const day = (tasks: CleaningTask[]): CleaningDay => ({
        day: "2026-11-04",
        today: "2026-11-04",
        tasks,
        cleaners,
      });
      const first = day([
        task("1", "U501"),
        task("2", "U502", {
          assigned_to: "e-2",
          assigned_name: "Sok Mony",
        }),
        task("3", "U503", {
          status: "DONE",
          done_at: "2026-11-04T02:00:00Z",
          done_by_name: "Chan Thida",
        }),
      ]);
      const given = day([
        task("1", "U501", { assigned_to: "e-1", assigned_name: "Chan Thida" }),
        ...first.tasks.slice(1),
      ]);
      const assignTask = vi.fn(() => Promise.resolve(given));
      show({
        api: fakeApi({
          cleaning: vi.fn(() => Promise.resolve(first)),
          assignTask,
        }),
        capabilities: new Set([...DESK, "short_stays.housekeeping"]),
      });
      fireEvent.click(
        await screen.findByRole("link", { name: "Housekeeping" }),
      );
      const list = await screen.findByRole("list", { name: "Housekeeping" });
      const u501 = within(list).getAllByRole("listitem")[0];
      if (u501 === undefined) throw new Error("No row");
      const box = within(u501).getByRole("combobox", { name: /Assign to/ });
      expect(
        within(box)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Nobody yet", "Chan Thida", "Sok Mony (no Telegram)"]);
      fireEvent.change(box, { target: { value: "e-1" } });
      await waitFor(() => {
        expect(assignTask).toHaveBeenCalledWith("p-1", "1", "e-1");
      });
      await waitFor(() => {
        expect(
          screen.getAllByRole("combobox", { name: /Assign to/ })[0],
        ).toHaveValue("e-1");
      });
      expect(screen.getByText("Done by Chan Thida")).toBeInTheDocument();
      // Owner card 14/11/2026: cleaners use the Staff bot, so there is no "My tasks".
      expect(screen.queryByRole("button", { name: "My tasks" })).toBeNull();
    });

    it("TEST-FE-2205 (DL-236) a housekeeper without the desk right sees who a task is given to, with no box", async () => {
      const day: CleaningDay = {
        day: "2026-11-04",
        today: "2026-11-04",
        cleaners: [
          {
            employee_id: "e-1",
            name: "Chan Thida",
            name_km: "ចាន់ ធីតា",
            telegram: true,
          },
        ],
        tasks: [
          {
            task_id: "1",
            kind: "DAILY_CLEAN",
            task_on: "2026-11-04",
            status: "TO_DO",
            note: null,
            done_at: null,
            unit_id: "u-501",
            unit_number: "U501",
            booking_id: "b-1",
            booking_number: "ST260001",
            guest_name: "Lim Dara",
            late: false,
            assigned_to: "e-1",
            assigned_name: "Chan Thida",
            done_by_name: null,
          },
        ],
      };
      show({
        api: fakeApi({ cleaning: vi.fn(() => Promise.resolve(day)) }),
        capabilities: new Set(["short_stays.read", "short_stays.housekeeping"]),
      });
      fireEvent.click(
        await screen.findByRole("link", { name: "Housekeeping" }),
      );
      expect(
        await screen.findByText("Given to Chan Thida"),
      ).toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: /Assign to/ })).toBeNull();
    });

    it("TEST-FE-2202 the Short stays tabs are the page head's links, as on Invoices, with the open one marked", async () => {
      window.location.hash = "#/shortstays?tab=list";
      show({ api: fakeApi({ list: vi.fn(() => Promise.resolve([])) }) });
      const tabs = screen.getByRole("navigation", { name: "Views" });
      const links = within(tabs).getAllByRole("link");
      expect(links.map((link) => link.textContent)).toEqual([
        "Calendar",
        "Bookings",
        "Housekeeping",
      ]);
      expect(links.map((link) => link.getAttribute("href"))).toEqual([
        "#/shortstays?tab=cal",
        "#/shortstays?tab=list",
        "#/shortstays?tab=clean",
      ]);
      expect(links[1]).toHaveAttribute("aria-current", "page");
      expect(links[0]).not.toHaveAttribute("aria-current");
      expect(screen.queryByRole("tab")).toBeNull();
      expect(await screen.findByText("No bookings yet.")).toBeInTheDocument();
    });
  });
});
