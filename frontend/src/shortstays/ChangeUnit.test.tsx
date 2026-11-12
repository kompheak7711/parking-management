// DL-224 (owner's rules of 12 Nov 2026): Change Unit for a short-stay booking that is not checked
// in yet, and the Owner's or Manager's special discount after a move. The guest keeps the agreed
// price. The bookings here are read through the client's own parser, as the server sends them.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BookingDetail } from "./BookingDetail";
import {
  type Booking,
  bookingOf,
  type MoveUnit,
  type ShortStaysApi,
  shortStaysApi,
  ShortStaysError,
} from "./shortStaysClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const BOOKED = {
  kind: "BOOKED",
  occurred_at: "2026-11-11T02:00:00Z",
  note: null,
};
const MOVED = {
  kind: "UNIT_CHANGED",
  occurred_at: "2026-11-12T03:00:00Z",
  note: "A Lease takes the Unit the guest booked",
  details: {
    from_unit_id: "u-301",
    from_unit_number: "U301",
    from_unit_type: "STUDIO",
    to_unit_id: "u-505",
    to_unit_number: "U505",
    to_unit_type: "TWO_BEDROOM",
  },
};
const DISCOUNTED = {
  kind: "MOVE_DISCOUNT",
  occurred_at: "2026-11-12T03:10:00Z",
  note: "A smaller Unit than the guest booked",
  details: { amount_usd_cents: 1000, credit_usd_cents: 1000 },
};

/** The owner's case: a paid stay in U301 from 13 to 15 Nov 2026, as the server sends it. */
const RAW = {
  booking_id: "b-1",
  booking_number: "ST260007",
  unit_id: "u-301",
  unit_number: "U301",
  unit_type: "STUDIO",
  customer_id: "c-1",
  guest_name: "Lim Dara",
  guest_phone: "010 333 444",
  guest_count: 2,
  check_in_on: "2026-11-13",
  check_out_on: "2026-11-15",
  nights: 2,
  source: "WALK_IN",
  site_name: null,
  site_reference: null,
  note: null,
  status: "BOOKED",
  total_usd_cents: 5800,
  version: 4,
  created_at: "2026-11-11T02:00:00Z",
  lines: [
    {
      position: 1,
      kind: "NIGHTS",
      quantity: 2,
      unit_price_usd_cents: 2900,
      discount_basis_points: 0,
      amount_usd_cents: 5800,
    },
  ],
  history: [BOOKED],
  unit_status: "VACANT",
  guest_has_id: true,
  payment: "PAID",
  invoice: {
    invoice_id: "i-1",
    invoice_number: "INV-000123",
    status: "ISSUED",
    total_usd_cents: 5800,
    due_usd_cents: 0,
  },
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
  free_cancel_until: "2026-11-11",
  cancel_reason: null,
  paid_usd_cents: 5800,
  cancellation: null,
  credit: null,
  refund: null,
  lease_off_usd_cents: 5000,
  lease_offer: null,
  lease_drafts: [],
  returning_guest: false,
  problem_guest: false,
  review_asked_at: null,
};

function stay(extra: Record<string, unknown> = {}): Booking {
  return bookingOf({ ...RAW, ...extra });
}

const UNITS: MoveUnit[] = [
  {
    unit_id: "u-302",
    unit_number: "U302",
    floor: "3",
    unit_type: "STUDIO",
    same_type: true,
    monthly_rent_usd_cents: 29900,
  },
  {
    unit_id: "u-505",
    unit_number: "U505",
    floor: "5",
    unit_type: "TWO_BEDROOM",
    same_type: false,
    monthly_rent_usd_cents: 49900,
  },
];

const notUsed = () => Promise.reject(new Error("not used"));

function fakeApi(overrides: Partial<ShortStaysApi>): ShortStaysApi {
  const api: Partial<ShortStaysApi> = {
    get: vi.fn(() => Promise.resolve(stay())),
    step: vi.fn(notUsed),
    moveUnits: vi.fn(() => Promise.resolve(UNITS)),
    price: vi.fn(notUsed),
    guest: vi.fn(notUsed),
    refundMethods: vi.fn(() => Promise.resolve([])),
    ...overrides,
  };
  return api as ShortStaysApi;
}

const DESK = ["short_stays.read", "short_stays.desk"];
const MANAGER = [...DESK, "short_stays.approve"];

function show(
  api: ShortStaysApi,
  rights: string[] = DESK,
  language: "en" | "km" = "en",
) {
  render(
    <BookingDetail
      api={api}
      bookingId="b-1"
      flash={null}
      language={language}
      may={(right) => rights.includes(right)}
      onFlashShown={() => undefined}
      propertyId="p-1"
      today="2026-11-12"
    />,
  );
  return api;
}

async function card(name = "Change Unit") {
  return within(await screen.findByRole("region", { name }));
}

describe("Short stays: Change Unit before check-in (DL-224)", () => {
  it("TEST-FE-2110 the client reads the Units a stay can move to and sends the move and the special discount", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=token-1",
      writable: true,
    });
    const answer = (data: unknown) =>
      new Response(JSON.stringify({ data }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        answer({ booking_id: "b-1", unit_id: "u-301", units: UNITS }),
      )
      .mockResolvedValueOnce(answer({ ...RAW, history: [BOOKED, MOVED] }))
      .mockResolvedValueOnce(answer(RAW))
      .mockResolvedValueOnce(answer({ units: [{ unit_id: "u-302" }] }));

    await expect(shortStaysApi.moveUnits("p-1", "b-1")).resolves.toEqual(UNITS);
    const moved = await shortStaysApi.step("p-1", "b-1", "unit", {
      version: 4,
      unit_id: "u-505",
      reason: "A Lease takes the Unit the guest booked",
    });
    // The History keeps the old and the new Unit of a move.
    expect(moved.history[1]).toEqual(MOVED);
    expect(moved.history[0]?.details ?? null).toBeNull();
    await shortStaysApi.step("p-1", "b-1", "move-discount", {
      version: 5,
      amount_usd_cents: 1000,
      reason: "A smaller Unit than the guest booked",
    });
    // A Unit the server did not describe in full is refused, not shown half empty.
    await expect(shortStaysApi.moveUnits("p-1", "b-1")).rejects.toBeInstanceOf(
      ShortStaysError,
    );

    const calls = fetcher.mock.calls.map(([path, init]) => [
      path,
      init?.method ?? "GET",
    ]);
    const base = "/api/v1/properties/p-1/short-stays/bookings/b-1";
    expect(calls).toEqual([
      [`${base}/units`, "GET"],
      [`${base}/unit`, "POST"],
      [`${base}/move-discount`, "POST"],
      [`${base}/units`, "GET"],
    ]);
    expect(fetcher.mock.calls[1]?.[1]?.body).toBe(
      JSON.stringify({
        version: 4,
        unit_id: "u-505",
        reason: "A Lease takes the Unit the guest booked",
      }),
    );
  });

  it("TEST-FE-2111 the front desk moves a booked guest to a free Unit, the same type first, with a reason", async () => {
    const moved = stay({
      unit_id: "u-505",
      unit_number: "U505",
      unit_type: "TWO_BEDROOM",
      version: 5,
      history: [BOOKED, MOVED],
    });
    const step = vi.fn(() => Promise.resolve(moved));
    const api = show(fakeApi({ step }));
    const change = await card();
    // The list is read only when the form is opened.
    expect(api.moveUnits).not.toHaveBeenCalled();
    expect(
      change.getByText(/The guest keeps the agreed price of \$58\.00/),
    ).toBeInTheDocument();
    fireEvent.click(change.getByRole("button", { name: "Change Unit" }));
    const select = await change.findByLabelText(/Move to/);
    expect(api.moveUnits).toHaveBeenCalledWith("p-1", "b-1");
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Choose…", "U302 · Studio", "U505 · 2 bedrooms"]);
    expect(
      within(select).getByRole("group", { name: "Same type" }),
    ).toContainElement(within(select).getByRole("option", { name: /U302/ }));
    expect(
      within(select).getByRole("group", { name: "Other types" }),
    ).toContainElement(within(select).getByRole("option", { name: /U505/ }));

    fireEvent.change(select, { target: { value: "u-505" } });
    // Another type: the price stays, and the screen says who may give a discount.
    expect(change.getByText(/This Unit is another type/)).toBeInTheDocument();
    fireEvent.change(change.getByLabelText(/Reason/), {
      target: { value: "  A Lease takes the Unit the guest booked " },
    });
    fireEvent.click(change.getByRole("button", { name: "Move the guest" }));
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "unit", {
      version: 4,
      unit_id: "u-505",
      reason: "A Lease takes the Unit the guest booked",
    });

    // The page shows the new Unit; the History names the two Units and the reason.
    expect(
      await screen.findByText(
        "Moved from U301 to U505. The guest keeps the agreed price.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Lim Dara · U505/)).toBeInTheDocument();
    const history = within(screen.getByRole("region", { name: "History" }));
    expect(history.getByText("Moved to another Unit")).toBeInTheDocument();
    expect(history.getByText("U301 to U505")).toBeInTheDocument();
    expect(
      history.getByText("A Lease takes the Unit the guest booked"),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2112 a move needs a Unit and a reason before anything is sent", async () => {
    const step = vi.fn(notUsed);
    show(fakeApi({ step }));
    const change = await card();
    fireEvent.click(change.getByRole("button", { name: "Change Unit" }));
    const select = await change.findByLabelText(/Move to/);
    fireEvent.click(change.getByRole("button", { name: "Move the guest" }));
    expect(
      change.getByText("Choose a Unit and write the reason."),
    ).toBeInTheDocument();
    expect(select).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(select, { target: { value: "u-302" } });
    fireEvent.change(change.getByLabelText(/Reason/), {
      target: { value: "   " },
    });
    fireEvent.click(change.getByRole("button", { name: "Move the guest" }));
    expect(change.getByLabelText(/Reason/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(step).not.toHaveBeenCalled();
    // The same type: nothing about a discount.
    expect(
      change.queryByText(/This Unit is another type/),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-2113 Change Unit shows only to the front desk and only before check-in", async () => {
    show(fakeApi({}), ["short_stays.read"]);
    await screen.findByRole("region", { name: "History" });
    expect(
      screen.queryByRole("region", { name: "Change Unit" }),
    ).not.toBeInTheDocument();
    cleanup();

    show(
      fakeApi({
        get: vi.fn(() =>
          Promise.resolve(
            stay({ status: "CHECKED_IN", unit_status: "OCCUPIED" }),
          ),
        ),
      }),
    );
    await screen.findByRole("region", { name: "History" });
    expect(
      screen.queryByRole("region", { name: "Change Unit" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-2114 says when no other Unit is free, and reads the list again after a failure", async () => {
    const moveUnits = vi
      .fn<ShortStaysApi["moveUnits"]>()
      .mockRejectedValueOnce(new ShortStaysError(500))
      .mockResolvedValueOnce([]);
    show(fakeApi({ moveUnits }));
    const change = await card();
    fireEvent.click(change.getByRole("button", { name: "Change Unit" }));
    expect(
      await change.findByText("The free Units could not be read just now."),
    ).toBeInTheDocument();
    fireEvent.click(change.getByRole("button", { name: "Try again" }));
    expect(
      await change.findByText("No other Unit is free on these nights."),
    ).toBeInTheDocument();
    expect(moveUnits).toHaveBeenCalledTimes(2);
    expect(
      change.queryByRole("button", { name: "Move the guest" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-2115 a Unit taken in the meantime is refused and the list of free Units is read again", async () => {
    const moveUnits = vi
      .fn<ShortStaysApi["moveUnits"]>()
      .mockResolvedValueOnce(UNITS)
      .mockResolvedValue(UNITS.slice(1));
    const step = vi.fn(() => Promise.reject(new ShortStaysError(409)));
    show(fakeApi({ moveUnits, step }));
    const change = await card();
    fireEvent.click(change.getByRole("button", { name: "Change Unit" }));
    fireEvent.change(await change.findByLabelText(/Move to/), {
      target: { value: "u-302" },
    });
    fireEvent.change(change.getByLabelText(/Reason/), {
      target: { value: "The air conditioner is broken" },
    });
    fireEvent.click(change.getByRole("button", { name: "Move the guest" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await waitFor(() => {
      expect(moveUnits).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(
        within(change.getByLabelText(/Move to/)).queryByRole("option", {
          name: /U302/,
        }),
      ).not.toBeInTheDocument();
    });
    // The Unit that is gone is no longer chosen; the reason typed is kept.
    expect(change.getByLabelText(/Move to/)).toHaveValue("");
    expect(change.getByLabelText(/Reason/)).toHaveValue(
      "The air conditioner is broken",
    );
  });

  it("TEST-FE-2116 a moved stay is not extended: the page says to make a new booking for the extra nights", async () => {
    show(fakeApi({}));
    await card();
    expect(
      screen.getByRole("region", { name: "Extend the stay" }),
    ).toBeInTheDocument();
    cleanup();

    show(
      fakeApi({
        get: vi.fn(() =>
          Promise.resolve(
            stay({
              status: "CHECKED_IN",
              unit_id: "u-505",
              unit_number: "U505",
              unit_type: "TWO_BEDROOM",
              history: [BOOKED, MOVED],
            }),
          ),
        ),
      }),
    );
    const change = await card();
    expect(
      change.getByText(
        "A moved stay is not extended. Make a new booking for the extra nights.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Extend the stay" }),
    ).not.toBeInTheDocument();
    // After check-in the guest does not move again.
    expect(
      change.queryByRole("button", { name: "Change Unit" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-2117 an Owner or Manager gives the special discount after a move, once", async () => {
    const moved = stay({
      unit_id: "u-505",
      unit_number: "U505",
      unit_type: "TWO_BEDROOM",
      version: 5,
      history: [BOOKED, MOVED],
    });
    const given = stay({
      unit_id: "u-505",
      unit_number: "U505",
      unit_type: "TWO_BEDROOM",
      version: 6,
      total_usd_cents: 4800,
      paid_usd_cents: 4800,
      lines: [
        ...RAW.lines,
        {
          position: 2,
          kind: "EXTRA_DISCOUNT",
          quantity: 1,
          unit_price_usd_cents: 1000,
          discount_basis_points: 0,
          amount_usd_cents: -1000,
        },
      ],
      history: [BOOKED, MOVED, DISCOUNTED],
      refund: {
        credits: [{ credit_id: "cr-1", left_usd_cents: 1000 }],
        left_usd_cents: 1000,
        waiting_usd_cents: 0,
        refunded_usd_cents: 0,
      },
    });
    const step = vi.fn(() => Promise.resolve(given));
    show(fakeApi({ get: vi.fn(() => Promise.resolve(moved)), step }), MANAGER);
    const special = await card("Special discount after the move");
    fireEvent.click(
      special.getByRole("button", { name: "Give the special discount" }),
    );
    expect(
      special.getByText("Type an amount less than the stay and a reason."),
    ).toBeInTheDocument();
    fireEvent.change(special.getByLabelText(/Discount/), {
      target: { value: "10" },
    });
    fireEvent.change(special.getByLabelText(/Reason/), {
      target: { value: "A smaller Unit than the guest booked" },
    });
    fireEvent.click(
      special.getByRole("button", { name: "Give the special discount" }),
    );
    expect(step).toHaveBeenCalledWith("p-1", "b-1", "move-discount", {
      version: 5,
      amount_usd_cents: 1000,
      reason: "A smaller Unit than the guest booked",
    });

    // Given: the form is gone, the amount and the reason stay, and the Credit is named.
    expect(
      await screen.findByText(
        "$10.00 off: A smaller Unit than the guest booked",
      ),
    ).toBeInTheDocument();
    const after = await card("Special discount after the move");
    expect(
      after.getByText("$10.00 is now the guest's Credit."),
    ).toBeInTheDocument();
    expect(
      after.queryByRole("button", { name: "Give the special discount" }),
    ).not.toBeInTheDocument();
    // The ordinary Extra discount card does not claim this discount as its own.
    expect(
      screen.queryByRole("region", { name: "Extra discount" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Give the money back" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2118 the special discount form shows only after a move, to an Owner or Manager, and not for a stay paid on the booking site", async () => {
    const moved = { history: [BOOKED, MOVED], version: 5 };
    const cases: [Record<string, unknown>, string[]][] = [
      [{}, MANAGER],
      [moved, DESK],
      [{ ...moved, payment: "PAID_ON_SITE", invoice: null }, MANAGER],
      [{ ...moved, status: "CHECKED_IN" }, MANAGER],
    ];
    for (const [extra, rights] of cases) {
      show(fakeApi({ get: vi.fn(() => Promise.resolve(stay(extra))) }), rights);
      await screen.findByRole("region", { name: "History" });
      expect(
        screen.queryByRole("region", {
          name: "Special discount after the move",
        }),
      ).not.toBeInTheDocument();
      cleanup();
    }
  });

  it("TEST-FE-2119 Change Unit speaks Khmer, and a Refund of the discount Credit names the special discount", async () => {
    const refund = vi.fn<ShortStaysApi["refund"]>(() => Promise.resolve());
    const paid = stay({
      version: 6,
      history: [BOOKED, MOVED, DISCOUNTED],
      refund: {
        credits: [{ credit_id: "cr-1", left_usd_cents: 1000 }],
        left_usd_cents: 1000,
        waiting_usd_cents: 0,
        refunded_usd_cents: 0,
      },
    });
    show(
      fakeApi({
        get: vi.fn(() => Promise.resolve(paid)),
        refund,
        refundMethods: vi.fn(() =>
          Promise.resolve([{ id: "m-cash", name: "Cash" }]),
        ),
      }),
      [...MANAGER, "refunds.create"],
    );
    const back = within(
      await screen.findByRole("region", { name: "Give the money back" }),
    );
    await waitFor(() => {
      expect(back.getByLabelText(/How it goes back/)).toHaveValue("m-cash");
    });
    fireEvent.change(back.getByLabelText(/Reference/), {
      target: { value: "Cash at the desk" },
    });
    fireEvent.click(back.getByRole("button", { name: "Refund $10.00" }));
    await waitFor(() => {
      expect(refund).toHaveBeenCalledTimes(1);
    });
    expect(refund.mock.calls[0]?.[1]).toMatchObject({
      credit_id: "cr-1",
      amount_usd_cents: 1000,
      reason:
        "Special discount ST260007: the money paid above the new price goes back",
    });
    cleanup();

    show(fakeApi({}), DESK, "km");
    const change = await card("ប្ដូរបន្ទប់");
    fireEvent.click(change.getByRole("button", { name: "ប្ដូរបន្ទប់" }));
    expect(await change.findByLabelText(/ផ្លាស់ទៅ/)).toBeInTheDocument();
    expect(
      change.getByRole("button", { name: "ផ្លាស់ភ្ញៀវ" }),
    ).toBeInTheDocument();
  });
});
