import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CustomerApi } from "../customerClient";
import { InvoiceClientError } from "../invoiceClient";
import type { PaymentsApi } from "../payments/paymentsClient";
import {
  ReservationConflictError,
  type ReservationApi,
  type ReservationResource,
} from "../reservationClient";
import { DateInput, isDay, parseDay } from "../shell/DateInput";
import { dayText, todayInPhnomPenh } from "../shell/format";
import type { UnitApi, UnitResource } from "../unitClient";
import {
  MakeReservationDialog,
  suggestedDeposit,
} from "./MakeReservationDialog";
import { addDays } from "./reservationsData";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const today = todayInPhnomPenh();

function apis() {
  const unitApi = {
    list: vi.fn(() =>
      Promise.resolve({
        items: [
          {
            unit_id: "unit-2",
            unit_number: "U102",
            status: "VACANT",
          } as unknown as UnitResource,
        ],
        next_cursor: null,
      }),
    ),
  } as unknown as Pick<UnitApi, "list">;
  const customerApi = {
    list: vi.fn(() =>
      Promise.resolve({
        items: [
          {
            customer_id: "customer-dara",
            legal_name: "Sok Dara",
            phone_number: null,
            active: true,
            relationship_indicators: [],
          },
        ],
        next_cursor: null,
      }),
    ),
  } as unknown as CustomerApi;
  const confirm = vi
    .fn<PaymentsApi["confirm"]>()
    .mockResolvedValue({ paymentId: "payment-1", receiptNumber: "RC0001" });
  const paymentsApi = {
    methods: vi.fn(() =>
      Promise.resolve([
        { id: "method-cash", code: "CASH", displayName: "Cash" },
      ]),
    ),
    confirm,
  } as unknown as PaymentsApi;
  const create = vi
    .fn<ReservationApi["create"]>()
    .mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValue({
      reservation_id: "saved",
    } as unknown as ReservationResource);
  const api = { create } as unknown as ReservationApi;
  return { unitApi, customerApi, paymentsApi, confirm, api, create };
}

describe("Date box (V1-060 B6)", () => {
  it("TEST-FE-1012 reads dd/mm/yyyy and yyyy-mm-dd, adds the slashes while typing and sends yyyy-mm-dd", () => {
    expect(parseDay("15/03/1986")).toBe("1986-03-15");
    expect(parseDay("5.3.1986")).toBe("1986-03-05");
    expect(parseDay("1986-03-15")).toBe("1986-03-15");
    expect(parseDay("31/02/2026")).toBe("");
    expect(parseDay("15/03")).toBe("");
    const onChange = vi.fn();
    render(
      <>
        <label htmlFor="born">Date of birth</label>
        <DateInput id="born" onChange={onChange} value="" />
      </>,
    );
    const box = screen.getByLabelText("Date of birth");
    fireEvent.change(box, { target: { value: "15031986" } });
    expect(box).toHaveValue("15/03/1986");
    expect(onChange).toHaveBeenLastCalledWith("1986-03-15");
    fireEvent.change(box, { target: { value: "15/13/1986" } });
    expect(onChange).toHaveBeenLastCalledWith("15/13/1986");
    // The calendar picks a day far back with its month and year lists.
    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    fireEvent.change(screen.getByLabelText("Year"), {
      target: { value: "1990" },
    });
    fireEvent.change(screen.getByLabelText("Month"), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "02/01/1990" }));
    expect(onChange).toHaveBeenLastCalledWith("1990-01-02");
    expect(box).toHaveValue("02/01/1990");
    expect(screen.queryByLabelText("Year")).toBeNull();
  });
});

describe("Date box (V1-060 B7)", () => {
  it("TEST-FE-1089 typing digits one by one adds both slashes, slashes typed elsewhere stay, only a whole day counts, and the calendar gives the focus back to its button when it closes", () => {
    expect(isDay("2026-10-28")).toBe(true);
    expect(isDay("")).toBe(false);
    expect(isDay("2026-02-31")).toBe(false);
    expect(isDay("28/10/2026")).toBe(false);
    const onChange = vi.fn();
    render(
      <>
        <label htmlFor="day">Day</label>
        <DateInput id="day" onChange={onChange} value="" />
      </>,
    );
    const box = screen.getByLabelText<HTMLInputElement>("Day");
    for (const key of "15031986")
      fireEvent.change(box, { target: { value: box.value + key } });
    expect(box).toHaveValue("15/03/1986");
    expect(onChange).toHaveBeenLastCalledWith("1986-03-15");
    fireEvent.change(box, { target: { value: "5/3/1986" } });
    expect(box).toHaveValue("5/3/1986");
    expect(onChange).toHaveBeenLastCalledWith("1986-03-05");

    const button = screen.getByRole("button", { name: "Calendar" });
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Close calendar" }));
    expect(button).toHaveFocus();
    box.focus();
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole("button", { name: "Today" }), {
      key: "Escape",
    });
    expect(button).toHaveFocus();
    box.focus();
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
    expect(button).toHaveFocus();
  });
});

describe("Make Reservation (V1-060 B6)", () => {
  it("TEST-FE-1013 saves the deposit as a Payment first, then the Reservation with that Payment; Try again never pays twice", async () => {
    const { unitApi, customerApi, paymentsApi, confirm, api, create } = apis();
    const onSaved = vi.fn();
    render(
      <MakeReservationDialog
        api={api}
        customerApi={customerApi}
        language="en"
        mayOverride
        onClose={vi.fn()}
        onSaved={onSaved}
        paymentsApi={paymentsApi}
        propertyId="property-1"
        unitApi={unitApi}
      />,
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Make Reservation",
    });
    await within(dialog).findByLabelText("Unit");
    expect(within(dialog).getByLabelText("Reservation Date")).toHaveValue(
      dayText(today),
    );
    expect(within(dialog).getByLabelText("Expires on")).toHaveValue(
      dayText(addDays(today, 21)),
    );
    fireEvent.change(within(dialog).getByLabelText("Unit"), {
      target: { value: "unit-2" },
    });
    fireEvent.change(within(dialog).getByLabelText("Customer"), {
      target: { value: "customer-dara" },
    });
    fireEvent.change(
      within(dialog).getByLabelText("Agreed monthly Rent (USD)"),
      {
        target: { value: "500" },
      },
    );
    expect(within(dialog).getByLabelText("Received now (USD)")).toHaveValue(
      "100.00",
    );
    expect(
      within(dialog).getByLabelText("Full Security Deposit (USD)"),
    ).toHaveValue("500.00");
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      {
        target: { value: "method-cash" },
      },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Try again" }),
    );
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0]?.[1]).toMatchObject({
      payer_customer_id: "customer-dara",
      payment_method_id: "method-cash",
      evidence_reference: "Cash received, Cash",
      payer_intent_memo:
        "Security Deposit received with the Reservation of U102",
      amount: { currency: "USD", minor_units: 10_000 },
    });
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      unit_id: "unit-2",
      customer_id: "customer-dara",
      reservation_date: today,
      expiration_date: addDays(today, 21),
      agreed_monthly_rent_usd_cents: 50_000,
      accepted_initial_deposit_usd_cents: 10_000,
      required_security_deposit_usd_cents: 50_000,
      payment_id: "payment-1",
    });
    expect(create.mock.calls[1]?.[1]).toEqual(create.mock.calls[0]?.[1]);
    expect(create.mock.calls[1]?.[2]).toBe(create.mock.calls[0]?.[2]);
  });

  it("TEST-FE-1014 suggests 20% of the Rent, asks why only when less is received (DL-099)", async () => {
    expect(suggestedDeposit(45_000)).toBe(9_000);
    expect(suggestedDeposit(45_003)).toBe(9_001);
    const { unitApi, customerApi, paymentsApi, confirm, api } = apis();
    render(
      <MakeReservationDialog
        api={api}
        customerApi={customerApi}
        language="en"
        mayOverride
        onClose={vi.fn()}
        onSaved={vi.fn()}
        paymentsApi={paymentsApi}
        propertyId="property-1"
        unitApi={unitApi}
        unitId="unit-2"
      />,
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Make Reservation",
    });
    expect(await within(dialog).findByLabelText("Unit")).toHaveValue("unit-2");
    fireEvent.change(
      within(dialog).getByLabelText("Agreed monthly Rent (USD)"),
      {
        target: { value: "450" },
      },
    );
    fireEvent.change(within(dialog).getByLabelText("Received now (USD)"), {
      target: { value: "50" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(
      within(dialog).getByText(
        "Say why the amount is less than the suggestion.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Choose a Customer.")).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Received now (USD)"), {
      target: { value: "200" },
    });
    expect(
      within(dialog).queryByLabelText(/Why less than the suggestion/),
    ).toBeNull();
  });
  it("TEST-FE-1079 less than the suggestion without the Owner or a Manager stops before any money; a lost Payment answer goes again the very same; the Rent and the amount stay fixed with the money; a conflict says the Reservation was not saved", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-28T03:00:00.000Z"));
    const { unitApi, customerApi, paymentsApi, confirm, api, create } = apis();
    confirm
      .mockReset()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockResolvedValue({ paymentId: "payment-1", receiptNumber: "RC0001" });
    create
      .mockReset()
      .mockRejectedValueOnce(new ReservationConflictError())
      .mockResolvedValue({
        reservation_id: "saved",
      } as unknown as ReservationResource);
    const onSaved = vi.fn();
    render(
      <MakeReservationDialog
        api={api}
        customerApi={customerApi}
        language="en"
        mayOverride={false}
        onClose={vi.fn()}
        onSaved={onSaved}
        paymentsApi={paymentsApi}
        propertyId="property-1"
        unitApi={unitApi}
        unitId="unit-2"
      />,
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Make Reservation",
    });
    await within(dialog).findByLabelText("Unit");
    fireEvent.change(within(dialog).getByLabelText("Customer"), {
      target: { value: "customer-dara" },
    });
    fireEvent.change(
      within(dialog).getByLabelText("Agreed monthly Rent (USD)"),
      { target: { value: "500" } },
    );
    fireEvent.change(
      await within(dialog).findByLabelText("How the money came"),
      { target: { value: "method-cash" } },
    );
    fireEvent.change(within(dialog).getByLabelText("Received now (USD)"), {
      target: { value: "50" },
    });
    fireEvent.change(
      within(dialog).getByLabelText(/Why less than the suggestion/),
      { target: { value: "Family of the Owner" } },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(
      within(dialog).getByText(
        "Less than the suggested $100.00 needs the Owner or a Manager. Ask one of them, or receive at least $100.00.",
      ),
    ).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Received now (USD)"), {
      target: { value: "100" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(
      await within(dialog).findByText(
        "We could not tell whether this was saved. “Try again” sends the very same request; it is never saved twice.",
      ),
    ).toBeInTheDocument();
    // Some seconds later the very same Payment goes again; then the Reservation meets a conflict.
    vi.setSystemTime(new Date("2026-10-28T03:00:07.000Z"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await within(dialog).findByText(
        /The Reservation was not saved: the Unit or the Customer changed meanwhile/,
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/The money is saved with Receipt RC0001/),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText("Agreed monthly Rent (USD)"),
    ).toBeDisabled();
    expect(within(dialog).getByLabelText("Received now (USD)")).toBeDisabled();
    expect(within(dialog).getByLabelText("Received now (USD)")).toHaveValue(
      "100",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(confirm.mock.calls[0]?.[1]).toMatchObject({
      received_at: "2026-10-28T03:00:00.000Z",
      amount: { currency: "USD", minor_units: 10_000 },
    });
    expect(confirm.mock.calls[1]?.[1]).toEqual(confirm.mock.calls[0]?.[1]);
    expect(confirm.mock.calls[1]?.[2]).toBe(confirm.mock.calls[0]?.[2]);
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      agreed_monthly_rent_usd_cents: 50_000,
      accepted_initial_deposit_usd_cents: 10_000,
      payment_id: "payment-1",
    });
    expect(create.mock.calls[1]?.[1]).toEqual(create.mock.calls[0]?.[1]);
    expect(create.mock.calls[1]?.[2]).toBe(create.mock.calls[0]?.[2]);
  });
});
