import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LeaseApi } from "../leaseClient";
import {
  guestNoticesOf,
  ShortStaysError,
  type GuestNotice,
  type GuestNotices,
  type GuestNoticesApi,
} from "../shortstays/shortStaysClient";
import { LettersPage } from "./LettersPage";
import type { LettersApi } from "./lettersClient";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/letters/short-stays";
  document.cookie = "__Host-prm_csrf=token";
});

function notice(id: string, overrides: Partial<GuestNotice>): GuestNotice {
  return {
    notice_id: id,
    kind: "CHECK_OUT_REMINDER",
    notice_on: "2026-11-14",
    created_at: "2026-11-14T11:05:00Z",
    warning_number: null,
    reason: null,
    invoice_number: null,
    amount: null,
    time: null,
    booking_id: "b-501",
    booking_number: "ST260021",
    booking_status: "CHECKED_IN",
    check_out_on: "2026-11-15",
    unit_number: "U501",
    guest_name: "Meas Rina",
    automatic: true,
    given_by_name: null,
    telegram: "SENT",
    told_at: null,
    told_by_name: null,
    ...overrides,
  };
}

const PAGE: GuestNotices = {
  notices: [
    notice("n-1", {}),
    notice("n-2", {
      kind: "HOUSE_RULE_WARNING",
      warning_number: 1,
      reason: "Loud music after 22:00.",
      automatic: false,
      given_by_name: "Sok Dara",
    }),
    notice("n-3", {
      kind: "LATE_CHECK_OUT",
      time: "12:00",
      booking_id: "b-502",
      booking_number: "ST260022",
      unit_number: "U502",
      guest_name: "Chan Dara",
      telegram: "NO_TELEGRAM",
    }),
    notice("n-4", {
      kind: "UNPAID_CHARGE",
      invoice_number: "INV-2026-0101",
      amount: "$20.30",
      booking_id: "b-503",
      booking_number: "ST260023",
      unit_number: "U503",
      guest_name: "Keo Lina",
      telegram: "NO_TELEGRAM",
      told_at: "2026-11-14T03:00:00Z",
      told_by_name: "Sok Dara",
    }),
    notice("n-5", {
      kind: "HOUSE_RULE_WARNING",
      warning_number: 2,
      reason: "Smoking in the room.",
      automatic: false,
      given_by_name: "Sok Dara",
      booking_id: "b-490",
      booking_number: "ST260010",
      booking_status: "CHECKED_OUT",
      unit_number: "U409",
      guest_name: "Heng Sophea",
      telegram: "NOT_DELIVERED",
    }),
  ],
  stays: [
    {
      booking_id: "b-501",
      booking_number: "ST260021",
      unit_number: "U501",
      guest_name: "Meas Rina",
      check_out_on: "2026-11-15",
      warnings: 1,
      telegram: true,
    },
    {
      booking_id: "b-502",
      booking_number: "ST260022",
      unit_number: "U502",
      guest_name: "Chan Dara",
      check_out_on: "2026-11-14",
      warnings: 0,
      telegram: false,
    },
    {
      booking_id: "b-504",
      booking_number: "ST260024",
      unit_number: "U504",
      guest_name: "Sao Nita",
      check_out_on: "2026-11-18",
      warnings: 2,
      telegram: true,
    },
  ],
  rules: {
    days: 90,
    reminder_at: "18:00",
    late_after_minutes: 30,
    unpaid_at: "09:00",
  },
};

function setup(
  capabilities: ReadonlySet<string> | null,
  tweak?: (api: GuestMocks) => void,
) {
  const guestApi = {
    notices: vi.fn<GuestNoticesApi["notices"]>(() => Promise.resolve(PAGE)),
    warn: vi.fn<GuestNoticesApi["warn"]>(() =>
      Promise.resolve({
        notice_id: "n-new",
        warning_number: 1,
        telegram_messages: 0,
      }),
    ),
    told: vi.fn<GuestNoticesApi["told"]>(() =>
      Promise.resolve({
        ...PAGE,
        notices: PAGE.notices.map((item) =>
          item.notice_id === "n-3"
            ? {
                ...item,
                told_at: "2026-11-14T05:00:00Z",
                told_by_name: "Sok Dara",
              }
            : item,
        ),
      }),
    ),
  };
  tweak?.(guestApi);
  const list = vi.fn<LeaseApi["list"]>(() =>
    Promise.resolve({ items: [], next_cursor: null, can_create: false }),
  );
  const alerts = vi.fn<LettersApi["alerts"]>(() =>
    Promise.resolve({ items: [], business_date: "2026-11-14" }),
  );
  render(
    <LettersPage
      active
      api={{ alerts } as unknown as LettersApi}
      capabilities={capabilities}
      guestApi={guestApi}
      language="en"
      leaseApi={{ list }}
      propertyId="property-1"
    />,
  );
  return { guestApi, list, alerts };
}

type GuestMocks = {
  [K in keyof GuestNoticesApi]: ReturnType<typeof vi.fn<GuestNoticesApi[K]>>;
};

function rowOf(text: string): HTMLElement {
  const row = screen
    .getAllByRole("row")
    .find((item) => within(item).queryByText(text) !== null);
  if (row === undefined) throw new Error(`no row for ${text}`);
  return row;
}

describe("Short-stay guest notices (DL-238)", () => {
  it("TEST-FE-2260 the Short-stay tab lists each notice with how the guest got it, and the cards show only their notices", async () => {
    const { list } = setup(null);
    await screen.findByText("Check-out reminder");
    expect(
      screen
        .getByRole("link", { name: "Short-stay guest notices" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Rent arrears notices" }),
    ).toBeTruthy();
    // The Lease letters are not read for this tab.
    expect(list).not.toHaveBeenCalled();
    expect(
      screen.getByText(/check-out reminder at 18:00 the evening before/),
    ).toBeTruthy();
    const reminder = rowOf("Check-out reminder");
    expect(within(reminder).getByText("Check-out 15/11/2026")).toBeTruthy();
    expect(within(reminder).getByText("Sent by the app")).toBeTruthy();
    expect(within(reminder).getByText("Sent by Telegram")).toBeTruthy();
    expect(
      within(reminder).getByRole("link", { name: "U501" }).getAttribute("href"),
    ).toBe("#/shortstays/st%3Ab-501");
    const warning = rowOf("House-rule warning 1");
    expect(within(warning).getByText("Loud music after 22:00.")).toBeTruthy();
    expect(within(warning).getByText("By Sok Dara")).toBeTruthy();
    expect(
      within(rowOf("Late check-out notice")).getByText("Time to leave 12:00"),
    ).toBeTruthy();
    expect(
      within(rowOf("Late check-out notice")).getByText(
        "No Telegram: tell in person",
      ),
    ).toBeTruthy();
    expect(
      within(rowOf("Unpaid charge")).getByText("INV-2026-0101: $20.30 to pay"),
    ).toBeTruthy();
    expect(
      within(rowOf("Unpaid charge")).getByText(
        "Told by Sok Dara on 14/11/2026",
      ),
    ).toBeTruthy();
    expect(
      within(rowOf("Final house-rule warning")).getByText(
        "Not delivered: tell in person",
      ),
    ).toBeTruthy();
    // Two notices still to tell in person (the late notice and the undelivered warning).
    const tell = screen.getByRole("button", { name: /To tell in person/ });
    expect(tell.textContent).toContain("2");
    fireEvent.click(tell);
    expect(screen.queryByText("Check-out reminder")).toBeNull();
    expect(screen.getByText("Late check-out notice")).toBeTruthy();
    expect(screen.getByText("Final house-rule warning")).toBeTruthy();
    fireEvent.click(tell);
    expect(screen.getByText("Check-out reminder")).toBeTruthy();
    // Guests with a warning: the warnings of guests checked in now.
    fireEvent.click(
      screen.getByRole("button", { name: /Guests with a warning/ }),
    );
    expect(screen.getByText("House-rule warning 1")).toBeTruthy();
    expect(screen.queryByText("Final house-rule warning")).toBeNull();
    expect(screen.queryByText("Unpaid charge")).toBeNull();
  });

  it("TEST-FE-2261 Give a warning lists the guests checked in, needs what happened, and says when the guest has no Telegram", async () => {
    const { guestApi } = setup(null);
    fireEvent.click(
      await screen.findByRole("button", { name: "Give a warning" }),
    );
    const dialog = await screen.findByRole("dialog");
    const guest = within(dialog).getByLabelText(/Guest/);
    const options = within(guest).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "U501 · Meas Rina",
      "U502 · Chan Dara",
      "U504 · Sao Nita (final warning given)",
    ]);
    expect((options[2] as HTMLOptionElement).disabled).toBe(true);
    // U501 already has warning 1: this one is the final warning.
    expect(within(dialog).getByText(/This is the final warning/)).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Give a warning" }),
    );
    expect(
      await within(dialog).findByText("Write what happened."),
    ).toBeTruthy();
    expect(guestApi.warn).not.toHaveBeenCalled();
    fireEvent.change(guest, { target: { value: "b-502" } });
    expect(within(dialog).getByText(/This is warning 1/)).toBeTruthy();
    expect(within(dialog).getByText(/has no Telegram/)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/What happened/), {
      target: { value: "  Party in the room.  " },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Give a warning" }),
    );
    await waitFor(() => {
      expect(guestApi.warn).toHaveBeenCalledWith(
        "property-1",
        "b-502",
        "Party in the room.",
      );
    });
    expect(
      await screen.findByText(
        "Warning 1 given to U502 · Chan Dara. No Telegram: tell the guest in person.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(guestApi.notices).toHaveBeenCalledTimes(2);
  });

  it("TEST-FE-2262 a notice the guest did not get is marked told in person once, and only with the front-desk right", async () => {
    const { guestApi } = setup(null);
    await screen.findByText("Late check-out notice");
    // The reminder went by Telegram and the unpaid charge was told: no button on them.
    expect(
      within(rowOf("Check-out reminder")).queryByRole("button"),
    ).toBeNull();
    expect(within(rowOf("Unpaid charge")).queryByRole("button")).toBeNull();
    fireEvent.click(
      within(rowOf("Late check-out notice")).getByRole("button", {
        name: "Told in person",
      }),
    );
    await waitFor(() => {
      expect(guestApi.told).toHaveBeenCalledWith("property-1", "n-3");
    });
    expect(
      await screen.findByText("Marked as told in person: U502 · Chan Dara."),
    ).toBeTruthy();
    expect(
      within(rowOf("Late check-out notice")).getByText(
        "Told by Sok Dara on 14/11/2026",
      ),
    ).toBeTruthy();
    cleanup();

    // short_stays.read only: the list, without Give a warning or Told in person.
    setup(new Set(["short_stays.read"]));
    await screen.findByText("Late check-out notice");
    expect(screen.queryByRole("button", { name: "Give a warning" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Told in person" })).toBeNull();
    // With that right only, the page opens on this tab and shows no tab row.
    expect(
      screen.queryByRole("link", { name: "Rent arrears notices" }),
    ).toBeNull();
  });

  it("TEST-FE-2263 a page that cannot be read says so, and an answer of the wrong shape is refused", async () => {
    window.location.hash = "#/letters";
    const { alerts } = setup(
      new Set(["short_stays.read", "short_stays.desk"]),
      (api) => {
        api.notices.mockRejectedValueOnce(new ShortStaysError(503));
      },
    );
    expect(
      await screen.findByText(/could not be loaded|not load/i),
    ).toBeTruthy();
    expect(alerts).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Check-out reminder")).toBeTruthy();
    expect(() =>
      guestNoticesOf({
        ...PAGE,
        notices: [{ ...PAGE.notices[0], kind: "OTHER" }],
      }),
    ).toThrow(ShortStaysError);
    expect(() =>
      guestNoticesOf({
        ...PAGE,
        stays: [{ ...PAGE.stays[0], telegram: "yes" }],
      }),
    ).toThrow(ShortStaysError);
    expect(guestNoticesOf(JSON.parse(JSON.stringify(PAGE)))).toEqual(PAGE);
  });
});
