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
  ReservationRequestError,
  ReservationUnavailableError,
  type ReservationApi,
  type ReservationResource,
} from "../reservationClient";
import { DateInput, isDay, parseDay } from "../shell/DateInput";
import { dayText, todayInPhnomPenh } from "../shell/format";
import { Dialog } from "../shell/ui";
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

  it("TEST-FE-1090 an edit inside a typed date stays as typed and is refused, a deleted slash is not put back, a year before 1900 is no day, and Escape on the calendar button closes only the calendar", () => {
    expect(parseDay("01/01/0000")).toBe("");
    expect(parseDay("15/03/1899")).toBe("");
    expect(parseDay("15/03/1900")).toBe("1900-03-15");
    const onChange = vi.fn();
    const onClose = vi.fn();
    render(
      <Dialog closeLabel="Close" onClose={onClose} title="Dates">
        <label htmlFor="born">Born</label>
        <DateInput id="born" onChange={onChange} value="" />
      </Dialog>,
    );
    const box = screen.getByLabelText<HTMLInputElement>("Born");
    fireEvent.change(box, { target: { value: "15031986" } });
    expect(box).toHaveValue("15/03/1986");
    // A "9" typed after "19" (to make 1996) leaves 9 digits: the box keeps them, so the form
    // refuses the day instead of the box turning it into 15/03/1998.
    fireEvent.change(box, {
      target: { value: "15/03/19986", selectionStart: 9, selectionEnd: 9 },
    });
    expect(box).toHaveValue("15/03/19986");
    expect(onChange).toHaveBeenLastCalledWith("15/03/19986");
    // A digit added at the end of a whole date is not swallowed either.
    fireEvent.change(box, { target: { value: "15/03/1986" } });
    fireEvent.change(box, { target: { value: "15/03/19861" } });
    expect(box).toHaveValue("15/03/19861");
    // Backspace on the second slash: it stays deleted.
    fireEvent.change(box, { target: { value: "15/03/1986" } });
    fireEvent.change(box, {
      target: { value: "15/031986", selectionStart: 5, selectionEnd: 5 },
    });
    expect(box).toHaveValue("15/031986");
    // Typing at the end still adds the slashes.
    fireEvent.change(box, { target: { value: "" } });
    for (const key of "0103")
      fireEvent.change(box, { target: { value: box.value + key } });
    expect(box).toHaveValue("01/03");

    const button = screen.getByRole("button", { name: "Calendar" });
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Today" })).toBeInTheDocument();
    fireEvent.keyDown(button, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    // With the calendar shut, Escape is the dialog's Cancel again.
    fireEvent.keyDown(button, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
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

describe("Make Reservation (V1-060 B7)", () => {
  /** Opens the dialog for Unit U102 and fills a Reservation of $500.00 a month, $100.00 now. */
  async function filled(
    api: ReservationApi,
    paymentsApi: PaymentsApi,
    unitApi: Pick<UnitApi, "list">,
    customerApi: CustomerApi,
    onSaved: (saved: ReservationResource) => void,
    onClose: () => void,
  ) {
    render(
      <MakeReservationDialog
        api={api}
        customerApi={customerApi}
        language="en"
        mayOverride
        onClose={onClose}
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
    return dialog;
  }
  const unknown =
    "We could not tell whether this was saved. “Try again” sends the very same request; it is never saved twice.";
  const boxes = (dialog: HTMLElement) =>
    [
      "Unit",
      "Customer",
      "Reservation Date",
      "Expires on",
      "Agreed monthly Rent (USD)",
      "Full Security Deposit (USD)",
      "Received now (USD)",
      "How the money came",
    ].map((label) => within(dialog).getByLabelText(label));

  it("TEST-FE-1092 a Unit from the address that is not free is not kept; less than the suggestion waits while the rights are not known; after a lost answer every box stays fixed; a refusal after a lost Reservation answer finds that Reservation saved", async () => {
    const { unitApi, customerApi, paymentsApi, confirm } = apis();
    confirm
      .mockReset()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockResolvedValue({ paymentId: "payment-1", receiptNumber: "RC0001" });
    const found = { reservation_id: "found" } as unknown as ReservationResource;
    const create = vi
      .fn<ReservationApi["create"]>()
      .mockRejectedValueOnce(new ReservationUnavailableError())
      .mockRejectedValueOnce(new ReservationConflictError());
    const get = vi.fn<ReservationApi["get"]>().mockResolvedValue(found);
    const api = { create, get } as unknown as ReservationApi;
    // A Unit that is not free now: the address named it, the box starts empty.
    const first = render(
      <MakeReservationDialog
        api={api}
        customerApi={customerApi}
        language="en"
        mayOverride={null}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        paymentsApi={paymentsApi}
        propertyId="property-1"
        unitApi={unitApi}
        unitId="unit-9"
      />,
    );
    const away = await screen.findByRole("dialog", {
      name: "Make Reservation",
    });
    expect(await within(away).findByLabelText("Unit")).toHaveValue("");
    fireEvent.change(within(away).getByLabelText("Unit"), {
      target: { value: "unit-2" },
    });
    fireEvent.change(within(away).getByLabelText("Customer"), {
      target: { value: "customer-dara" },
    });
    fireEvent.change(within(away).getByLabelText("Agreed monthly Rent (USD)"), {
      target: { value: "500" },
    });
    fireEvent.change(await within(away).findByLabelText("How the money came"), {
      target: { value: "method-cash" },
    });
    fireEvent.change(within(away).getByLabelText("Received now (USD)"), {
      target: { value: "50" },
    });
    fireEvent.change(
      within(away).getByLabelText(/Why less than the suggestion/),
      { target: { value: "Family of the Owner" } },
    );
    fireEvent.click(
      within(away).getByRole("button", { name: "Save Reservation" }),
    );
    expect(
      within(away).getByText(
        "Your rights could not be read just now, so less than the suggested $100.00 cannot be checked before the money is taken. Reload the page, or receive at least $100.00.",
      ),
    ).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    first.unmount();

    const onSaved = vi.fn();
    const dialog = await filled(
      api,
      paymentsApi,
      unitApi,
      customerApi,
      onSaved,
      vi.fn(),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    for (const box of boxes(dialog)) expect(box).toBeDisabled();
    // The money is saved now; the Reservation's answer is lost: still every box fixed.
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(1);
    });
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    for (const box of boxes(dialog)) expect(box).toBeDisabled();
    // The very same request meets the Reservation it saved: the Unit is no longer free.
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(found);
    });
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(confirm.mock.calls[1]?.[2]).toBe(confirm.mock.calls[0]?.[2]);
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[1]?.[1]).toEqual(create.mock.calls[0]?.[1]);
    expect(create.mock.calls[1]?.[2]).toBe(create.mock.calls[0]?.[2]);
    expect(get).toHaveBeenCalledWith(create.mock.calls[0]?.[1].reservation_id);
  });

  it("TEST-FE-1093 a refusal after a lost Reservation answer stays not known until the lookup says there is none; then the money saved but the Reservation refused says so, and Close asks once more", async () => {
    const { unitApi, customerApi, paymentsApi, confirm } = apis();
    const create = vi
      .fn<ReservationApi["create"]>()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValue(new ReservationConflictError());
    const get = vi
      .fn<ReservationApi["get"]>()
      .mockRejectedValueOnce(new ReservationUnavailableError())
      .mockRejectedValue(new ReservationRequestError(404));
    const api = { create, get } as unknown as ReservationApi;
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const dialog = await filled(
      api,
      paymentsApi,
      unitApi,
      customerApi,
      onSaved,
      onClose,
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    // The lookup cannot be read: still not known.
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(get).toHaveBeenCalledTimes(1);
    });
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    for (const box of boxes(dialog)) expect(box).toBeDisabled();
    // The server says there is no such Reservation: the conflict stands.
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await within(dialog).findByText(
        /The Reservation was not saved: the Unit or the Customer changed meanwhile/,
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "The money is saved with Receipt RC0001, but the rest was not saved (the reason is below). The money pays nothing yet, so do not receive it again. If the reason cannot be fixed here, close this and ask the Owner or a Manager to finish it.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Reservation Date")).toBeEnabled();
    expect(within(dialog).getByLabelText("Received now (USD)")).toBeDisabled();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(create).toHaveBeenCalledTimes(3);
    expect(onSaved).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(
      within(dialog).getByText(
        "The money is saved with Receipt RC0001, but the rest is not confirmed. If you close now, do not receive the money again; ask the Owner or a Manager to check and finish it.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Close anyway" }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-1098 after a lost Payment answer, a Try again that never leaves the browser, not allowed or not found stays not known with every box fixed; the server's own refusal of the same request opens them", async () => {
    const { unitApi, customerApi, paymentsApi, confirm } = apis();
    confirm
      .mockReset()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockRejectedValueOnce(
        new InvoiceClientError(null, "CSRF_UNAVAILABLE", false),
      )
      .mockRejectedValueOnce(new InvoiceClientError(403, "FORBIDDEN", false))
      .mockRejectedValueOnce(new InvoiceClientError(404, "NOT_FOUND", false))
      .mockRejectedValueOnce(
        new InvoiceClientError(422, "VALIDATION_FAILED", false),
      );
    const api = { create: vi.fn(), get: vi.fn() } as unknown as ReservationApi;
    const dialog = await filled(
      api,
      paymentsApi,
      unitApi,
      customerApi,
      vi.fn(),
      vi.fn(),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    for (let press = 2; press <= 4; press += 1) {
      fireEvent.click(
        within(dialog).getByRole("button", { name: "Try again" }),
      );
      await waitFor(() => {
        expect(confirm).toHaveBeenCalledTimes(press);
      });
      expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
      for (const box of boxes(dialog)) expect(box).toBeDisabled();
      expect(confirm.mock.calls[press - 1]?.[1]).toEqual(
        confirm.mock.calls[0]?.[1],
      );
      expect(confirm.mock.calls[press - 1]?.[2]).toBe(
        confirm.mock.calls[0]?.[2],
      );
    }
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await within(dialog).findByText(
        "It was not saved. Check the details and try again.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Received now (USD)")).toBeEnabled();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("TEST-FE-1099 after a lost Reservation answer, a Try again that never leaves the browser, not allowed or not found stays not known without a lookup; the server's own refusal is looked up first", async () => {
    const { unitApi, customerApi, paymentsApi, confirm } = apis();
    const create = vi
      .fn<ReservationApi["create"]>()
      .mockRejectedValueOnce(new ReservationUnavailableError())
      .mockRejectedValueOnce(new ReservationRequestError())
      .mockRejectedValueOnce(new ReservationRequestError(403))
      .mockRejectedValueOnce(new ReservationRequestError(404))
      .mockRejectedValueOnce(new ReservationRequestError(422));
    const get = vi
      .fn<ReservationApi["get"]>()
      .mockRejectedValue(new ReservationRequestError(404));
    const api = { create, get } as unknown as ReservationApi;
    const dialog = await filled(
      api,
      paymentsApi,
      unitApi,
      customerApi,
      vi.fn(),
      vi.fn(),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
    for (let press = 2; press <= 4; press += 1) {
      fireEvent.click(
        within(dialog).getByRole("button", { name: "Try again" }),
      );
      await waitFor(() => {
        expect(create).toHaveBeenCalledTimes(press);
      });
      expect(await within(dialog).findByText(unknown)).toBeInTheDocument();
      for (const box of boxes(dialog)) expect(box).toBeDisabled();
      expect(create.mock.calls[press - 1]?.[2]).toBe(create.mock.calls[0]?.[2]);
    }
    expect(get).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await within(dialog).findByText(
        "It was not saved. Check the details and try again.",
      ),
    ).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(1);
    expect(
      within(dialog).getByText(/The money is saved with Receipt RC0001/),
    ).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-1100 a Unit from the address that is not vacant never reaches the money step", async () => {
    const { unitApi, customerApi, paymentsApi, confirm } = apis();
    render(
      <MakeReservationDialog
        api={{ create: vi.fn(), get: vi.fn() } as unknown as ReservationApi}
        customerApi={customerApi}
        language="en"
        mayOverride
        onClose={vi.fn()}
        onSaved={vi.fn()}
        paymentsApi={paymentsApi}
        propertyId="property-1"
        unitApi={unitApi}
        unitId="unit-9"
      />,
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Make Reservation",
    });
    await within(dialog).findByRole("option", { name: /U102/ });
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
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(within(dialog).getByText("Choose a Unit.")).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("TEST-FE-1101 the money saved but the Reservation refused as changed does not ask to change the Unit or the Customer, which are fixed with the money", async () => {
    const { unitApi, customerApi, paymentsApi } = apis();
    const create = vi
      .fn<ReservationApi["create"]>()
      .mockRejectedValue(new ReservationConflictError());
    const api = { create, get: vi.fn() } as unknown as ReservationApi;
    const dialog = await filled(
      api,
      paymentsApi,
      unitApi,
      customerApi,
      vi.fn(),
      vi.fn(),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Reservation" }),
    );
    expect(
      await within(dialog).findByText(
        "The Reservation was not saved: the Unit or the Customer changed meanwhile (for example, someone else reserved this Unit first).",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/Check them, then try again/)).toBeNull();
    expect(
      within(dialog).getByText(/The money is saved with Receipt RC0001/),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Unit")).toBeDisabled();
    expect(within(dialog).getByLabelText("Customer")).toBeDisabled();
  });
});

describe("Date box (V1-060 B7, third review)", () => {
  it("TEST-FE-1103 a whole day pasted as digits over a selected day gets its slashes", () => {
    const onChange = vi.fn();
    render(
      <>
        <label htmlFor="d">Day</label>
        <DateInput id="d" onChange={onChange} value="2026-10-28" />
      </>,
    );
    const box = screen.getByLabelText<HTMLInputElement>("Day");
    expect(box).toHaveValue("28/10/2026");
    // Everything selected, then "15031986" pasted: the caret ends after the new text.
    fireEvent.change(box, { target: { value: "15031986" } });
    expect(box).toHaveValue("15/03/1986");
    expect(onChange).toHaveBeenLastCalledWith("1986-03-15");
  });
});
