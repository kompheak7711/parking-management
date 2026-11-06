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
import { invoiceType, ivt } from "../invoices/text";
import { lineWords } from "../payments/ReceiptDocument";
import { pyt } from "../payments/text";
import { bookingRefusal } from "./NewBooking";
import { ShortStaysPage } from "./ShortStaysPage";
import {
  type Booking,
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
    decide: vi.fn(() => Promise.resolve(BOOKING)),
    cleaning: vi.fn((_: string, day: string) =>
      Promise.resolve({ day, today: "2026-11-04", tasks: [] }),
    ),
    finishTask: vi.fn(() =>
      Promise.resolve({ day: "2026-11-04", today: "2026-11-04", tasks: [] }),
    ),
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
  it("TEST-FE-1600 shows one row per Unit and one square per night, each with a word", async () => {
    const { api } = show();
    const table = await screen.findByRole("table");
    expect(api.calendar).toHaveBeenCalledWith("p-1", "2026-11-04", 14);
    const u501 = within(table).getByRole("row", { name: /U501/ });
    // The first night shows the guest, the next nights the status; each opens the booking.
    expect(
      within(u501).getByRole("link", { name: /Lim Dara/ }),
    ).toHaveAttribute("href", "#/shortstays/st%3Ab-1");
    // Not paid yet: the next nights say so.
    expect(
      within(u501).getAllByRole("link", { name: /Not paid/ }),
    ).toHaveLength(2);
    // Today is free: the square opens New booking for that Unit and night.
    expect(
      within(u501).getByRole("link", {
        name: "New booking: U501, night of 04/11/2026",
      }),
    ).toHaveAttribute("href", "#/shortstays/new%3Au-501%3A2026-11-04");
    const u503 = within(table).getByRole("row", { name: /U503/ });
    expect(within(u503).getByText("1 bedroom")).toBeInTheDocument();
    expect(within(u503).getAllByText("Lease")).toHaveLength(8);
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
    fireEvent.click(await screen.findByRole("button", { name: "Bookings" }));
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
      await screen.findAllByText("Type the guest's full name."),
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
    expect(screen.getByText("Never type the card number.")).toBeInTheDocument();
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

  it("TEST-FE-1609 records the room check with damage and lets only the Manager decide", async () => {
    const out: Booking = {
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
    };
    const waiting: Booking = {
      ...out,
      room_check: {
        ...(out.room_check ?? { task_id: "", task_on: "" }),
        status: "DONE",
        done_at: "2026-11-04T04:00:00Z",
        note: null,
      },
      damages: [
        {
          damage_id: "g-1",
          description: "Broken lamp",
          amount_usd_cents: 8000,
          status: "WAITING",
          decided_at: null,
          decision_note: null,
          from_deposit_usd_cents: 0,
          invoice_id: null,
          invoice_number: null,
        },
      ],
    };
    const step = vi.fn(() => Promise.resolve(waiting));
    show({
      api: fakeApi({ get: vi.fn(() => Promise.resolve(out)), step }),
      capabilities: new Set([...DESK, "short_stays.housekeeping"]),
    });
    go("#/shortstays/st:b-1");
    fireEvent.click(await screen.findByLabelText("Damage found"));
    fireEvent.change(screen.getByLabelText(/What is damaged/), {
      target: { value: "Broken lamp" },
    });
    fireEvent.change(screen.getByLabelText(/Cost to fix/), {
      target: { value: "80,5" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Room check done/ }));
    expect(
      screen.getByText("Type the cost in dollars, for example 80 or 80.50."),
    ).toBeInTheDocument();
    expect(step).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Cost to fix/), {
      target: { value: "80" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Room check done/ }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "room-check", {
      damage: "Broken lamp",
      damage_usd_cents: 8000,
    });
    expect(
      await screen.findByText("Waits for the Manager"),
    ).toBeInTheDocument();
    // Without the approve right there is nothing to press; the deposit waits.
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Return the deposit/ }),
    ).toBeNull();
  });

  it("TEST-FE-1610 approves damage from the deposit, then keeps it", async () => {
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
    const checked: Booking = {
      ...TODAY_STAY,
      status: "CHECKED_OUT",
      payment: "PAID",
      invoice: INVOICE,
      deposit: DEPOSIT,
      room_check: {
        task_id: "t-1",
        task_on: "2026-11-04",
        status: "DONE",
        note: null,
        done_at: "2026-11-04T04:00:00Z",
      },
      damages: [damage],
    };
    const approved: Booking = {
      ...checked,
      damages: [
        {
          ...damage,
          status: "APPROVED",
          decision_note: "Photo on file",
          from_deposit_usd_cents: 5000,
          invoice_id: "i-2",
          invoice_number: "INV-000124",
        },
      ],
    };
    const decide = vi.fn(() => Promise.resolve(approved));
    const step = vi.fn(() =>
      Promise.resolve({
        ...approved,
        deposit: { ...DEPOSIT, status: "KEPT" as const, kept_usd_cents: 5000 },
      }),
    );
    show({
      api: fakeApi({
        get: vi.fn(() => Promise.resolve(checked)),
        decide,
        step,
      }),
      capabilities: new Set([...DESK, "short_stays.approve"]),
    });
    go("#/shortstays/st:b-1");
    // A refusal needs a reason.
    fireEvent.click(await screen.findByRole("button", { name: "Refuse" }));
    expect(screen.getByText("A refusal says why.")).toBeInTheDocument();
    expect(decide).not.toHaveBeenCalled();
    fireEvent.change(screen.getByPlaceholderText("Reason"), {
      target: { value: "Photo on file" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(decide).toHaveBeenCalledWith("p-1", "g-1", {
      approve: true,
      note: "Photo on file",
    });
    expect(
      await screen.findByText(/\$50\.00 from the deposit/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Invoice INV-000124 for the rest" }),
    ).toHaveAttribute("href", "#/invoices/inv%3Ai-2");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Keep $50.00 for damage, return $0.00",
      }),
    );
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "deposit/end", null);
    expect(await screen.findByText(/Kept \$50\.00/)).toBeInTheDocument();
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
        },
      ],
    };
    const cleaning = vi.fn(() => Promise.resolve(day));
    const finishTask = vi.fn(() => Promise.resolve(day));
    show({
      api: fakeApi({ cleaning, finishTask }),
      capabilities: new Set([...DESK, "short_stays.housekeeping"]),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Cleaning" }));
    expect(await screen.findByText("Daily clean")).toBeInTheDocument();
    expect(cleaning).toHaveBeenCalledWith("p-1", "2026-11-04");
    expect(screen.getByText("2 to do")).toBeInTheDocument();
    expect(screen.getByText("Due 03/11/2026")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Do the room check" }),
    ).toHaveAttribute("href", "#/shortstays/st%3Ab-9");
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(
      await screen.findByText("A skipped clean says why."),
    ).toBeInTheDocument();
    expect(finishTask).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Why it is skipped/), {
      target: { value: "Do not disturb" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
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
      screen.getByText("Type an amount up to $60.90."),
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
    fireEvent.click(await screen.findByRole("button", { name: "Bookings" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "Bookings" }));
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
    const clash = within(u501).getAllByRole("cell")[3];
    expect(clash).toHaveClass("ss-clash");
    expect(clash).toHaveAttribute(
      "title",
      "Agoda also has these nights: check both bookings.",
    );
    // Then Agoda's own nights, closed for every other booking.
    expect(within(u501).getAllByText("Agoda")).toHaveLength(2);
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
    show({
      api: fakeApi({ siteCalendars, saveSiteCalendar }),
      capabilities: new Set([...DESK, "short_stays.approve"]),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Booking sites" }),
    );
    expect(
      await screen.findByText("The site answered 404"),
    ).toBeInTheDocument();
    expect(screen.getByText("Could not read")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add link" }));
    expect(
      screen.getByText(
        "Pick the room and the site, and paste a link that starts with https://",
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
    fireEvent.click(screen.getByRole("button", { name: "Add link" }));
    expect(saveSiteCalendar).toHaveBeenCalledWith("p-1", {
      unit_id: "u-503",
      site_name: "Airbnb",
      import_url: "https://airbnb.example/cal.ics",
      active: true,
    });
    await waitFor(() => {
      expect(siteCalendars).toHaveBeenCalledTimes(2);
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
    expect(screen.queryByRole("button", { name: "Booking sites" })).toBeNull();
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
      await screen.findByText("1 stays done · 2 nights · $52.00 spent"),
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
      screen.getByText("Type an amount less than the stay and a reason."),
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

  it("TEST-FE-1625 makes a quote with today's price and a message for the guest", async () => {
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
      check_out_on: "2026-11-09",
      nights: 3,
      total_usd_cents: 5460,
      lines: LINES,
      made_on: "2026-11-04",
      check_in_time: 840,
      check_out_time: 720,
      deposit_usd_cents: 5000,
      month_only_usd_cents: 40500,
      monthly_rent_usd_cents: 26900,
    };
    const quote = vi.fn(() => Promise.resolve(made));
    const quotes = vi.fn(() => Promise.resolve([] as StayQuote[]));
    quotes.mockResolvedValueOnce([]).mockResolvedValue([made]);
    show({ api: fakeApi({ quote, quotes }) });
    fireEvent.click(await screen.findByRole("button", { name: "Quotes" }));
    expect(await screen.findByText("No quotes yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Make the quote" }));
    expect(
      screen.getByText(
        "Pick the room, type the guest's name, 1 to 10 guests and the nights.",
      ),
    ).toBeInTheDocument();
    fireEvent.change(byId("sq-unit"), { target: { value: "u-503" } });
    fireEvent.change(byId("sq-in"), { target: { value: "06/11/2026" } });
    fireEvent.change(byId("sq-nights"), { target: { value: "3" } });
    fireEvent.change(byId("sq-guests"), { target: { value: "2" } });
    fireEvent.change(byId("sq-name"), { target: { value: " Sok Chenda " } });
    fireEvent.change(byId("sq-contact"), { target: { value: "@chenda" } });
    fireEvent.click(screen.getByRole("button", { name: "Make the quote" }));
    expect(quote).toHaveBeenCalledWith("p-1", {
      unit_id: "u-503",
      guest_name: "Sok Chenda",
      guest_contact: "@chenda",
      guest_count: 2,
      check_in_on: "2026-11-06",
      check_out_on: "2026-11-09",
    });
    expect(
      await screen.findByText(
        "Quote SQ260001 made. Copy the message for the guest.",
      ),
    ).toBeInTheDocument();
    const message = screen.getByDisplayValue(
      /^CHETANA Residence: quote SQ260001/,
    );
    expect((message as HTMLTextAreaElement).value).toContain(
      "06/11/2026 to 09/11/2026, 3 nights\nTotal $54.60\nCheck-in from 14:00, check-out by 12:00.",
    );
    expect((message as HTMLTextAreaElement).value).toContain(
      "Staying longer? 1 month only: $405.00. A Lease of 6 or 12 months: $269.00 a month.",
    );
    expect(screen.getByRole("link", { name: "Book this" })).toHaveAttribute(
      "href",
      "#/shortstays/new%3Au-503%3A2026-11-06",
    );
    expect(await screen.findByText("SQ260001")).toBeInTheDocument();
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
    show();
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Weekly report" })).toBeNull();
    cleanup();
    show({ api, capabilities: new Set([...DESK, "short_stays.approve"]) });
    fireEvent.click(
      await screen.findByRole("button", { name: "Weekly report" }),
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
    expect(
      screen.getByRole("button", { name: "ប្រតិទិន" }),
    ).toBeInTheDocument();
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
    ).toBe("Miscellaneous");
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
    expect(card.getByText("Type the reference.")).toBeInTheDocument();
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
      screen.getByRole("link", { name: "Open Waiting for approval" }),
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
});
