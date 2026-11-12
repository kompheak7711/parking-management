// DL-225 (12 Nov 2026, migration 20270721_376): Reserve Unit stops on a Unit a short-stay
// guest has booked, as a Lease does (DL-223). The server answers 409 with the code
// RESERVATION_UNIT_BOOKED and its words; the dialog shows them, so staff reserve another Unit
// or move the guest first.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomerApi } from "../customerClient";
import type { PaymentsApi } from "../payments/paymentsClient";
import {
  ReservationConflictError,
  ReservationUnitBookedError,
  reservationApi,
  type ReservationApi,
  type ReservationResource,
  type ReservationWithPaymentSource,
} from "../reservationClient";
import { serverWords } from "../shell/serverText";
import type { UnitApi, UnitResource } from "../unitClient";
import { MakeReservationDialog } from "./MakeReservationDialog";

const WORDS =
  "A short-stay guest has booked this Unit. Nothing was saved and no money was taken. " +
  "Reserve another Unit, or move the guest to another Unit first (Short stays, Change Unit).";
const GENERAL =
  "The Reservation was not saved: the Unit or the Customer changed meanwhile (for example, someone else reserved this Unit first). Check them, then try again.";

function refusal(code: string, message: string): Response {
  return new Response(
    JSON.stringify({ error: { code, message, fields: [], rule_ids: [] } }),
    { status: 409, headers: { "Content-Type": "application/json" } },
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(document, "cookie", {
    configurable: true,
    value: "__Host-prm_csrf=reservation-token",
    writable: true,
  });
});

afterEach(() => {
  cleanup();
});

describe("Reserve Unit on a Unit a short-stay guest has booked (DL-225): the client", () => {
  const source = {
    unit_id: "unit-2",
  } as unknown as ReservationWithPaymentSource;

  it("TEST-FE-2103 Make Reservation with its money: the refusal carries its code and the server's words", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      refusal("RESERVATION_UNIT_BOOKED", WORDS),
    );
    const error: unknown = await reservationApi
      .createWithPayment("property-1", source, "key-1")
      .catch((thrown: unknown) => thrown);
    expect(error).toBeInstanceOf(ReservationUnitBookedError);
    // The screens that know only a conflict still say that nothing was saved.
    expect(error).toBeInstanceOf(ReservationConflictError);
    expect(error).toMatchObject({
      code: "RESERVATION_UNIT_BOOKED",
      message: WORDS,
    });
  });

  it("TEST-FE-2104 Make Reservation without money in the same step is refused the same way", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      refusal("RESERVATION_UNIT_BOOKED", WORDS),
    );
    await expect(
      reservationApi.create(
        "property-1",
        source as unknown as Parameters<ReservationApi["create"]>[1],
        "key-1",
      ),
    ).rejects.toBeInstanceOf(ReservationUnitBookedError);
  });

  it("TEST-FE-2105 any other conflict stays the general conflict, also when its answer cannot be read", async () => {
    for (const answer of [
      refusal("CONFLICT", "The request conflicts with the current state."),
      new Response("not json", { status: 409 }),
      new Response(null, { status: 409 }),
      new Response(null, { status: 412 }),
    ]) {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(answer);
      const error: unknown = await reservationApi
        .createWithPayment("property-1", source, "key-1")
        .catch((thrown: unknown) => thrown);
      expect(error).toBeInstanceOf(ReservationConflictError);
      expect(error).not.toBeInstanceOf(ReservationUnitBookedError);
      vi.restoreAllMocks();
    }
  });
});

describe("Reserve Unit on a Unit a short-stay guest has booked (DL-225): the dialog", () => {
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
    const paymentsApi = {
      methods: vi.fn(() =>
        Promise.resolve([
          { id: "method-cash", code: "CASH", displayName: "Cash" },
        ]),
      ),
      confirm: vi.fn(),
    } as unknown as PaymentsApi;
    return { unitApi, customerApi, paymentsApi };
  }

  it("TEST-FE-2106 shows the server's reason in place of the general words, keeps the boxes open, and saves once the guest has moved", async () => {
    const { unitApi, customerApi, paymentsApi } = apis();
    const saved = { reservation_id: "saved" } as unknown as ReservationResource;
    const create = vi
      .fn<ReservationApi["createWithPayment"]>()
      .mockRejectedValueOnce(new ReservationUnitBookedError(WORDS))
      .mockResolvedValue({ reservation: saved, receiptNumber: "RC0001" });
    const get = vi.fn<ReservationApi["get"]>();
    const onSaved = vi.fn();
    render(
      <MakeReservationDialog
        api={{ createWithPayment: create, get } as unknown as ReservationApi}
        customerApi={customerApi}
        language="en"
        mayOverride
        onClose={vi.fn()}
        onSaved={onSaved}
        paymentsApi={paymentsApi}
        propertyId="property-1"
        unitApi={unitApi}
        unitId="unit-2"
      />,
    );
    const dialog = await screen.findByRole("dialog");
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
    const save = within(dialog).getByRole("button", {
      name: "Save Reservation",
    });
    fireEvent.click(save);

    expect(await within(dialog).findByText(WORDS)).toBeInTheDocument();
    expect(within(dialog).queryByText(GENERAL)).toBeNull();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(WORDS);
    // Nothing was saved, so there is nothing to look for, and the Unit may be changed.
    expect(onSaved).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
    expect(within(dialog).getByLabelText("Unit")).toBeEnabled();
    expect(within(dialog).getByLabelText("Customer")).toBeEnabled();

    // After Change Unit moved the guest, the same Reservation is saved.
    fireEvent.click(save);
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(saved);
    });
    expect(within(dialog).queryByText(WORDS)).toBeNull();
  });

  it("TEST-FE-2107 the Khmer screen has Khmer words for this refusal, with the name of Change Unit", () => {
    const error = new ReservationUnitBookedError(WORDS);
    expect(serverWords("en", error)).toBe(WORDS);
    const khmer = serverWords("km", error);
    expect(khmer).not.toContain(WORDS);
    expect(khmer).toContain("ប្ដូរបន្ទប់");
    expect(khmer).toMatch(/[ក-៿]/);
  });
});
