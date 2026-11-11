import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TelegramQrCard } from "./TelegramQrCard";
import {
  type LinkCodeMade,
  type LinkPeople,
  type LinkQrApi,
  TelegramError,
  linkCodeOf,
  linkPeopleOf,
  linkQrApi,
  linksPageOf,
} from "./telegramClient";

const PROPERTY = "p-1";
const CODE = "0123456789abcdef0123456789abcdef01234567";
const SVG = '<svg xmlns="http://www.w3.org/2000/svg"><path fill="#000"/></svg>';
const PEOPLE: LinkPeople = {
  people: [
    { customer_id: "c-1", name: "Sao Rina", unit_number: "U302" },
    { customer_id: "c-2", name: "Chan Dara", unit_number: "U302" },
  ],
  bot_ready: true,
  hours: 24,
};
const MADE: LinkCodeMade = {
  url: `https://t.me/ChetanaSupportBot?start=${CODE}`,
  name: "Sao Rina",
  unit_number: "U302",
  expires_at: "2026-11-12T03:00:00Z",
  qr_svg: SVG,
};

function fakeApi(over: Partial<LinkQrApi> = {}): LinkQrApi {
  return {
    people: vi.fn(() => Promise.resolve(PEOPLE)),
    make: vi.fn(() => Promise.resolve(MADE)),
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Telegram QR (DL-214)", () => {
  it("TEST-FE-1951 on a Lease, staff open the QR, pick a person and the QR is shown once, then closed", async () => {
    const api = fakeApi();
    render(
      <TelegramQrCard
        api={api}
        language="en"
        propertyId={PROPERTY}
        stay={{ lease_id: "l-1" }}
      />,
    );
    expect(screen.getByText(/tenant scans it/)).toBeInTheDocument();
    expect(api.people).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Show Telegram QR" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "QR for Chan Dara" }),
    );
    expect(api.people).toHaveBeenCalledWith(PROPERTY, { lease_id: "l-1" });
    const picture = await screen.findByRole("img", {
      name: "Telegram QR code",
    });
    expect(api.make).toHaveBeenCalledWith(PROPERTY, { lease_id: "l-1" }, "c-2");
    expect(picture.getAttribute("src")).toBe(
      `data:image/svg+xml;charset=utf-8,${encodeURIComponent(SVG)}`,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Ask Sao Rina (U302) to scan this with the phone camera",
    );
    expect(screen.getByText(/shown only once/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show Telegram QR" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1952 on a Booking the guest words show, and a bot not ready, nobody, or a refusal says so", async () => {
    const notReady = fakeApi({
      people: vi.fn(() => Promise.resolve({ ...PEOPLE, bot_ready: false })),
    });
    render(
      <TelegramQrCard
        api={notReady}
        language="en"
        propertyId={PROPERTY}
        stay={{ booking_id: "b-1" }}
      />,
    );
    expect(screen.getByText(/link ends at check-out/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show Telegram QR" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "The Telegram QR is not ready yet.",
    );
    expect(notReady.people).toHaveBeenCalledWith(PROPERTY, {
      booking_id: "b-1",
    });
    cleanup();

    const nobody = fakeApi({
      people: vi.fn(() => Promise.resolve({ ...PEOPLE, people: [] })),
    });
    render(
      <TelegramQrCard
        api={nobody}
        language="km"
        propertyId={PROPERTY}
        stay={{ booking_id: "b-1" }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "បង្ហាញ QR តេឡេក្រាម" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "គ្មាននរណាម្នាក់",
    );
    cleanup();

    for (const [status, words] of [
      [409, "The Telegram bot is not ready yet."],
      [422, "This person is not on a live Lease or stay now."],
      [403, "You do not have the right to do this."],
    ] as const) {
      const refused = fakeApi({
        make: vi.fn(() => Promise.reject(new TelegramError(status))),
      });
      render(
        <TelegramQrCard
          api={refused}
          language="en"
          propertyId={PROPERTY}
          stay={{ booking_id: "b-1" }}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Show Telegram QR" }));
      fireEvent.click(
        await screen.findByRole("button", { name: "QR for Sao Rina" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(words);
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
      cleanup();
    }
  });

  it("TEST-FE-1953 the client reads the people and makes a code with the CSRF token, and refuses a bad answer", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=token-1",
      writable: true,
    });
    const calls: [string, RequestInit | undefined][] = [];
    const answers = [
      { data: PEOPLE },
      { data: { ...MADE, bot: "ChetanaSupportBot" } },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        calls.push([path, init]);
        const body = answers.shift();
        return Promise.resolve(
          new Response(JSON.stringify(body), { status: 200 }),
        );
      }),
    );
    expect(await linkQrApi.people(PROPERTY, { booking_id: "b 1" })).toEqual(
      PEOPLE,
    );
    expect(calls[0]?.[0]).toBe(
      "/api/v1/properties/p-1/telegram/link-people?booking_id=b%201",
    );
    expect(await linkQrApi.make(PROPERTY, { lease_id: "l-1" }, "c-1")).toEqual(
      MADE,
    );
    const [path, init] = calls[1] ?? ["", undefined];
    expect(path).toBe("/api/v1/properties/p-1/telegram/link-codes");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("token-1");
    expect(JSON.parse(init?.body as string)).toEqual({
      lease_id: "l-1",
      customer_id: "c-1",
    });
    expect(() => linkCodeOf({ ...MADE, qr_svg: "<img>" })).toThrow(
      TelegramError,
    );
    expect(() => linkPeopleOf({ people: [], hours: 24 })).toThrow(
      TelegramError,
    );
    // A guest linked by QR shows the stay on Linked tenants.
    const guest = linksPageOf({
      linked: [
        {
          id: "link-2",
          telegram_user_id: 7710002,
          phone: null,
          name: "Chan Dara",
          unit_number: "U508",
          lease_end_date: null,
          booking_number: "ST269901",
          stay_end_date: "2026-11-14",
          linked_at: "2026-11-11T03:00:00Z",
        },
      ],
      tries: [],
      ended: [],
      rules: { tries: 5, block_hours: 24, keep_days: 30 },
    });
    expect(guest.linked[0]?.booking_number).toBe("ST269901");
    expect(guest.linked[0]?.stay_end_date).toBe("2026-11-14");
  });
});
