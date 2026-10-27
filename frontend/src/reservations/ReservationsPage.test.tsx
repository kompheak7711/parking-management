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
  ReservationConflictError,
  ReservationUnavailableError,
  type ReservationApi,
  type ReservationResource,
} from "../reservationClient";
import { dayText, todayInPhnomPenh } from "../shell/format";
import { ReservationsPage } from "./ReservationsPage";
import { addDays } from "./reservationsData";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/reservations";
});

const today = todayInPhnomPenh();

function reservation(
  id: string,
  overrides: Partial<ReservationResource> = {},
): ReservationResource {
  return {
    reservation_id: id,
    property_id: "property-1",
    unit_id: `unit-${id}`,
    unit_number: id,
    customer_id: `customer-${id}`,
    customer_name: `Customer ${id}`,
    reservation_date: addDays(today, -10),
    original_expiration_date: addDays(today, 11),
    effective_expiration_date: addDays(today, 11),
    agreed_monthly_rent_usd_cents: 50000,
    status: "ACTIVE",
    version: 2,
    deposit_id: `deposit-${id}`,
    deposit_required_usd_cents: 10000,
    deposit_received_usd_cents: 10000,
    deposit_outcome_state: "PENDING_V1_031",
    cancellation_reason_code: null,
    cancellation_responsibility: null,
    resulting_lease_id: null,
    extension_notice: null,
    can_extend: true,
    can_cancel: true,
    receipts: [
      {
        receipt_id: `receipt-${id}`,
        payment_id: `payment-${id}`,
        amount_usd_cents: 10000,
        occurred_at: "2026-10-15T03:00:00Z",
        actor_id: "actor-1",
      },
    ],
    lifecycle_events: [],
    deposit_outcomes: [],
    extension_days_remaining: 11,
    ...overrides,
  };
}

const extended = reservation("U101", {
  effective_expiration_date: addDays(today, 5),
  original_expiration_date: addDays(today, -2),
  can_extend: false,
  extension_notice: {
    notice_id: "notice-1",
    previous_expiration_date: addDays(today, -2),
    new_expiration_date: addDays(today, 5),
    approved_at: "2026-10-20T03:00:00Z",
    reason_memo: "Waiting for the guarantor",
  },
});
const fresh = reservation("U102");
const completed = reservation("U201", {
  status: "COMPLETED",
  resulting_lease_id: "lease-1",
  can_extend: false,
  can_cancel: false,
});
const withdrawn = reservation("U202", {
  status: "CANCELLED",
  cancellation_reason_code: "CUSTOMER_NO_LONGER_WANTS_UNIT",
  cancellation_responsibility: "CUSTOMER",
  deposit_outcome_state: "AWAITING_DECISION",
  can_extend: false,
  can_cancel: false,
  lifecycle_events: [
    {
      event_id: "event-1",
      event_kind: "CANCELLATION",
      reason_code: "CUSTOMER_NO_LONGER_WANTS_UNIT",
      responsibility: "CUSTOMER",
      reason_memo: "Found a house",
      coordination_reference: null,
      authorization_reference: "auth-1",
      occurred_at: "2026-10-21T04:00:00Z",
      business_date: "2026-10-21",
      actor_id: "actor-1",
    },
  ],
});
const expired = reservation("U203", {
  status: "CANCELLED",
  cancellation_reason_code: "RESERVATION_EXPIRED",
  cancellation_responsibility: "CUSTOMER",
  deposit_outcome_state: "NON_REFUNDABLE_DISPOSITION",
  can_extend: false,
  can_cancel: false,
});
const all = [extended, fresh, completed, withdrawn, expired];

function api(overrides: Partial<ReservationApi> = {}): ReservationApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: all,
      next_cursor: null,
      can_create: true,
    }),
    get: vi.fn((id: string) =>
      Promise.resolve(
        all.find((entry) => entry.reservation_id === id) ?? fresh,
      ),
    ),
    create: vi.fn(),
    extend: vi.fn(),
    cancel: vi.fn(),
    ...overrides,
  };
}

function show(client: ReservationApi) {
  return render(
    <ReservationsPage
      active
      api={client}
      capabilities={null}
      language="en"
      propertyId="property-1"
    />,
  );
}

function rowOf(unit: string): HTMLElement {
  const row = screen.getByRole("link", { name: unit }).closest("tr");
  if (row === null) throw new Error(`no row for ${unit}`);
  return row;
}

describe("Reservations list", () => {
  it("TEST-FE-837 shows each Reservation with its dates, days left, deposit, status and result", async () => {
    show(api());

    expect(
      await screen.findByText(/^5 Reservations · a Unit held/),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("table"))
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual([
      "Unit",
      "Customer",
      "Reserved on",
      "Expires",
      "Deposit received",
      "Status",
    ]);
    expect(rowOf("U101")).toHaveTextContent(
      `${dayText(addDays(today, 5))}extended once · 5 days left`,
    );
    expect(rowOf("U101")).toHaveTextContent("$100.00of $100.00");
    expect(rowOf("U102")).toHaveTextContent(
      "11 days left$100.00of $100.00Active",
    );
    expect(rowOf("U201")).toHaveTextContent("CompletedLease signed");
    expect(rowOf("U202")).toHaveTextContent(
      "CancelledCustomer no longer wants the Unit",
    );
    expect(rowOf("U203")).toHaveTextContent("CancelledExpired");
    for (const label of [
      "Active: 2.",
      "Ending within 7 days: 1.",
      "Completed: 1.",
      "Cancelled: 2.",
    ])
      expect(
        screen.getByRole("button", { name: new RegExp(`^${label}`) }),
      ).toBeInTheDocument();
  });

  it("TEST-FE-838 filters by count card and opens a Reservation at its own address", async () => {
    show(api());
    await screen.findByText("5 Reservations");

    fireEvent.click(
      screen.getByRole("button", { name: /^Ending within 7 days: 1\./ }),
    );
    expect(screen.getByText("1 Reservation")).toBeInTheDocument();
    expect(rowOf("U101")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getByText("5 Reservations")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "U102" }));
    expect(window.location.hash).toBe("#/reservations/U102");
    expect(
      await screen.findByRole("heading", { name: "Reservation · U102" }),
    ).toBeInTheDocument();
  });
});

describe("Reservation page", () => {
  it("TEST-FE-839 shows the facts, the Extension card, the Security Deposit and what happens to it", async () => {
    window.location.hash = "#/reservations/U101";
    show(api());

    expect(
      await screen.findByRole("heading", { name: "Reservation · U101" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "5 days left. Sign the Lease or extend the Reservation before it expires.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Extend/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "It cannot be extended again: a Reservation is extended once only.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Extension" })).toHaveTextContent(
      "Waiting for the guarantor",
    );
    const deposit = screen.getByRole("region", { name: "Security Deposit" });
    expect(deposit).toHaveTextContent(
      "Suggested$100.0020% of the agreed Rent, not a minimum",
    );
    expect(deposit).toHaveTextContent("Accepted$100.00same as the suggestion");
    expect(deposit).toHaveTextContent(
      "This money is already the Security Deposit and continues into the Lease.",
    );
    expect(screen.getByRole("link", { name: "Customer U101" })).toHaveAttribute(
      "href",
      "#/customers/customer-U101",
    );
    cleanup();

    window.location.hash = "#/reservations/U202";
    show(api());
    const card = await screen.findByRole("region", { name: "Cancellation" });
    expect(card).toHaveTextContent("Customer no longer wants the Unit");
    expect(card).toHaveTextContent("Found a house");
    expect(
      screen.getByText(
        "Under the rules the Security Deposit is kept. Nothing has moved yet: someone records the decision as a draft, and it takes effect when the Owner or a Manager confirms it.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel Reservation" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-840 Extend offers at most 14 more days and Try again sends the very same request", async () => {
    window.location.hash = "#/reservations/U102";
    const latest = addDays(fresh.effective_expiration_date, 14);
    const extend = vi
      .fn()
      .mockRejectedValueOnce(new ReservationUnavailableError())
      .mockResolvedValueOnce({
        ...fresh,
        effective_expiration_date: latest,
        version: 3,
      });
    show(api({ extend }));

    fireEvent.click(await screen.findByRole("button", { name: /^Extend/ }));
    const dialog = screen.getByRole("dialog", { name: "Extend · U102" });
    const box = within(dialog).getByLabelText("New expiration date");
    expect(box).toHaveValue(dayText(dayText(latest)));
    fireEvent.change(box, { target: { value: addDays(latest, 1) } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Extend" }));
    expect(within(dialog).getByText(/^Pick a date after/)).toBeInTheDocument();
    expect(extend).not.toHaveBeenCalled();

    fireEvent.change(box, { target: { value: latest } });
    fireEvent.change(within(dialog).getByLabelText("Memo (optional)"), {
      target: { value: " Visa delay " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Extend" }));
    expect(
      await within(dialog).findByText(
        /We could not tell whether this was saved/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText(
        `The Reservation now expires on ${dayText(latest)}.`,
      ),
    ).toBeInTheDocument();
    expect(extend).toHaveBeenCalledTimes(2);
    const [first, second] = extend.mock.calls as [
      [ReservationResource, Record<string, unknown>, string],
      [ReservationResource, Record<string, unknown>, string],
    ];
    expect(first[1]).toMatchObject({
      new_expiration_date: latest,
      reason_memo: "Visa delay",
    });
    expect(second[1]).toEqual(first[1]);
    expect(second[2]).toBe(first[2]);
  });

  it("TEST-FE-841 Cancel asks why, needs a memo and what was offered for a Property reason, and reloads after someone else's change", async () => {
    window.location.hash = "#/reservations/U102";
    const cancel = vi
      .fn()
      .mockResolvedValueOnce({
        ...fresh,
        status: "CANCELLED",
        cancellation_responsibility: "PROPERTY",
        deposit_outcome_state: "AWAITING_DECISION",
        can_cancel: false,
        can_extend: false,
      })
      .mockRejectedValueOnce(new ReservationConflictError());
    const client = api({ cancel });
    show(client);

    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel Reservation" }),
    );
    let dialog = screen.getByRole("dialog", {
      name: "Cancel Reservation · U102",
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Cancel Reservation" }),
    );
    expect(within(dialog).getByText("Choose why.")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter a memo.")).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("radio", { name: /^The Property cannot/ }),
    );
    fireEvent.change(within(dialog).getByLabelText(/^Memo/), {
      target: { value: "Water leak in U102" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Cancel Reservation" }),
    );
    expect(
      within(dialog).getByText("Say what was offered to the Customer."),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^What was offered/), {
      target: { value: "Offered U305; declined" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Cancel Reservation" }),
    );
    expect(
      await screen.findByText("The Reservation was cancelled."),
    ).toBeInTheDocument();
    expect(cancel.mock.calls[0]?.[1]).toMatchObject({
      reason_code: "PROPERTY_CANNOT_PROVIDE_UNIT",
      responsibility: "PROPERTY",
      property_could_provide_unit: false,
      reason_memo: "Water leak in U102",
      coordination_reference: "Offered U305; declined",
    });
    cleanup();

    window.location.hash = "#/reservations/U102";
    const get = vi.fn().mockResolvedValue(fresh);
    show(api({ cancel, get }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel Reservation" }),
    );
    dialog = screen.getByRole("dialog", { name: "Cancel Reservation · U102" });
    fireEvent.click(
      within(dialog).getByRole("radio", { name: /^The Customer no longer/ }),
    );
    fireEvent.change(within(dialog).getByLabelText(/^Memo/), {
      target: { value: "Changed plans" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Cancel Reservation" }),
    );
    expect(
      await screen.findByText(/Someone else changed this Reservation first/),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(get).toHaveBeenCalledTimes(2);
    });
    expect(cancel.mock.calls[1]?.[1]).toMatchObject({
      reason_code: "CUSTOMER_NO_LONGER_WANTS_UNIT",
      responsibility: "CUSTOMER",
      property_could_provide_unit: true,
      coordination_reference: null,
    });
  });
});

describe("Reservation page when it cannot be read", () => {
  it("TEST-FE-842 offers Retry when there is no answer, and never shows a Reservation of another Property", async () => {
    window.location.hash = "#/reservations/U102";
    const get = vi
      .fn()
      .mockRejectedValueOnce(new ReservationUnavailableError())
      .mockResolvedValueOnce(fresh);
    show(api({ get }));

    expect(
      await screen.findByText(/could not be read just now/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/was not found/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("heading", { name: "Reservation · U102" }),
    ).toBeInTheDocument();
    cleanup();

    show(
      api({
        get: vi.fn().mockResolvedValue({ ...fresh, property_id: "property-2" }),
      }),
    );
    expect(await screen.findByText(/was not found/)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Reservation · U102" }),
    ).not.toBeInTheDocument();
  });
});
