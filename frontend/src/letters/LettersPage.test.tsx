import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LeaseApi, LeaseResource } from "../leaseClient";
import { todayInPhnomPenh } from "../shell/format";
import { addDays } from "../reservations/reservationsData";
import { LettersPage } from "./LettersPage";
import {
  LettersConflictError,
  LettersRequestError,
  LettersUnavailableError,
  type LeaseWarning,
  type LettersApi,
  type RentAlert,
  type RentLetterEvent,
} from "./lettersClient";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/letters";
  document.cookie = "__Host-prm_csrf=token";
});

const today = todayInPhnomPenh();

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
    start_date: addDays(today, -200),
    end_date: addDays(today, 165),
    monthly_rent_usd_cents: 50000,
    predecessor_lease_id: null,
    signed_at: "2026-03-01T03:00:00Z",
    terminated_at: null,
    actual_termination_date: null,
    version: 3,
    created_at: "2026-02-20T03:00:00Z",
    pet_deposit_required: false,
    pet_description: null,
    security_deposit_id: null,
    planned_occupant_customer_ids: [],
    planned_occupants: [],
    service_terms: [],
    signers: [],
    occupancies: [
      {
        occupancy_id: `occupancy-${unit}`,
        customer_id: `customer-${unit}`,
        customer_name: `Tenant ${unit}`,
        move_in_date: addDays(today, -199),
        move_out_date: null,
        version: 1,
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

const LEASES = [
  lease("U101"),
  lease("U102"),
  lease("U103"),
  lease("U104"),
  // Not moved in yet: it cannot be warned.
  lease("U105", { occupancies: [] }),
  lease("U106", { status: "DRAFTED" }),
];

const BUSINESS_DATE = "2026-11-25";

function alert(
  unit: string,
  due: string,
  caseId: string | null,
  flags: Partial<RentAlert["assessment"]>,
): RentAlert {
  return {
    rent_invoice_line_id: `line-${unit}`,
    invoice_id: `invoice-${unit}`,
    invoice_number: `INV26${unit}`,
    lease_id: `lease-${unit}`,
    customer_id: `customer-${unit}`,
    due_date: due,
    case_id: caseId,
    assessment: {
      business_date: BUSINESS_DATE,
      remaining_rent: { currency: "USD", minor_units: 50000 },
      ten_day_notice_eligible: false,
      twenty_day_warning_eligible: false,
      twenty_five_day_notice_eligible: false,
      thirty_day_default_eligible: false,
      ten_day_notice_recorded: false,
      warning_recorded: false,
      twenty_five_day_notice_recorded: false,
      serious_default_recorded: false,
      telegram_linked: false,
      // Due on the 5th: each step falls on day N of the month.
      step_days: {
        TEN_DAY_NOTICE: `${due.slice(0, 8)}10`,
        TWENTY_DAY_WARNING: `${due.slice(0, 8)}20`,
        TWENTY_FIVE_DAY_NOTICE: `${due.slice(0, 8)}25`,
        THIRTY_DAY_SERIOUS_DEFAULT: `${due.slice(0, 8)}30`,
      },
      ...flags,
    },
  };
}

const ALL_DUE = {
  ten_day_notice_eligible: true,
  twenty_day_warning_eligible: true,
  twenty_five_day_notice_eligible: true,
};
const ALL_GIVEN = {
  ten_day_notice_recorded: true,
  warning_recorded: true,
  twenty_five_day_notice_recorded: true,
};

// DL-237. None of these tenants has a Tenant-bot link, so people give the notices.
const ALERTS: RentAlert[] = [
  // November Rent, day 25: the three notices are due and none is given.
  alert("U101", "2026-11-05", null, ALL_DUE),
  // November Rent, the three notices given: wait for day 30.
  alert("U102", "2026-11-05", "case-U102", ALL_GIVEN),
  // October Rent, the notices and the termination letter given: the Lease may be ended.
  alert("U103", "2026-10-05", "case-U103", {
    ...ALL_GIVEN,
    serious_default_recorded: true,
  }),
  // October Rent, day 30 passed and no notice: the termination letter waits for them.
  alert("U104", "2026-10-05", null, ALL_DUE),
];

function letter(
  kind: RentLetterEvent["event_kind"],
  date: string,
  record: string,
  reference: string | null,
): RentLetterEvent {
  return {
    id: `event-${kind}-${date}`,
    event_kind: kind,
    event_date: date,
    notice_document_reference: reference,
    communication_record: record,
  };
}

const EVENTS: Record<string, RentLetterEvent[]> = {
  "case-U102": [
    letter(
      "TEN_DAY_NOTICE",
      "2026-11-10",
      "Sent by Telegram: by the Tenant bot, by itself",
      "TG-INV26U102-1",
    ),
    letter(
      "TWENTY_DAY_WARNING",
      "2026-11-20",
      "Handed to the tenant: signed our copy",
      "L-020",
    ),
    letter("TWENTY_FIVE_DAY_NOTICE", "2026-11-25", "Sent by email", "L-025"),
  ],
  "case-U103": [
    letter("TEN_DAY_NOTICE", "2026-10-10", "Handed to the tenant", "L-010"),
    letter(
      "TWENTY_DAY_WARNING",
      "2026-10-21",
      "Sent by Telegram: chat photo kept",
      "L-011",
    ),
    letter("TWENTY_FIVE_DAY_NOTICE", "2026-10-25", "Sent by WhatsApp", "L-012"),
    letter(
      "THIRTY_DAY_SERIOUS_DEFAULT",
      "2026-10-30",
      "Left at the Parking with a witness: Sok Dara",
      null,
    ),
  ],
};

function warning(
  unit: string,
  sequence: number,
  overrides: Partial<LeaseWarning> = {},
): LeaseWarning {
  return {
    id: `warning-${unit}-${String(sequence)}`,
    lease_id: `lease-${unit}`,
    warning_sequence: sequence,
    violation_date: "2026-09-10",
    warning_date: `2026-09-1${String(sequence)}`,
    violation_description: `Noise at night ${String(sequence)}`,
    lease_provision: "11.3",
    communication_record: "Handed to the tenant",
    ...overrides,
  };
}

function setup(
  capabilities: ReadonlySet<string> | null = null,
  tweak?: (api: Mocks) => void,
) {
  const api = {
    alerts: vi.fn<LettersApi["alerts"]>(() =>
      Promise.resolve({ items: ALERTS, business_date: BUSINESS_DATE }),
    ),
    events: vi.fn<LettersApi["events"]>((caseId) =>
      Promise.resolve(EVENTS[caseId] ?? []),
    ),
    openCase: vi.fn<LettersApi["openCase"]>(() =>
      Promise.resolve({ id: "case-new" }),
    ),
    recordLetter: vi.fn<LettersApi["recordLetter"]>((_case, source) =>
      Promise.resolve(
        letter(
          source.event_kind,
          BUSINESS_DATE,
          source.communication_record,
          null,
        ),
      ),
    ),
    warnings: vi.fn<LettersApi["warnings"]>((leaseId) =>
      Promise.resolve(
        leaseId === "lease-U101"
          ? [warning("U101", 2), warning("U101", 1)]
          : leaseId === "lease-U102"
            ? [
                warning("U102", 1),
                warning("U102", 2),
                warning("U102", 3, {
                  violation_description: "Smoking inside",
                  lease_provision: "12.1",
                  communication_record: "Sent by Telegram",
                }),
              ]
            : [],
      ),
    ),
    warningContext: vi.fn<LettersApi["warningContext"]>((leaseId) =>
      Promise.resolve({
        suggested_sequence: leaseId === "lease-U101" ? 3 : 1,
        business_date: today,
      }),
    ),
    recordWarning: vi.fn<LettersApi["recordWarning"]>((_lease, source) =>
      Promise.resolve(warning("U101", source.warning_sequence)),
    ),
    notices: vi.fn<LettersApi["notices"]>(() => Promise.resolve([])),
    recordNotice: vi.fn<LettersApi["recordNotice"]>((_property, leaseId) =>
      Promise.resolve({ id: "notice-new", lease_id: leaseId } as never),
    ),
  };
  tweak?.(api);
  const list = vi.fn<LeaseApi["list"]>(() =>
    Promise.resolve({ items: LEASES, next_cursor: null, can_create: false }),
  );
  render(
    <LettersPage
      active
      api={api}
      capabilities={capabilities}
      language="en"
      leaseApi={{ list }}
      propertyId="property-1"
    />,
  );
  return { api, list };
}

type Mocks = {
  [K in keyof LettersApi]: ReturnType<typeof vi.fn<LettersApi[K]>>;
};

function rowOf(unit: string): HTMLElement {
  const cell = screen
    .getAllByRole("row")
    .find((row) => within(row).queryByText(unit) !== null);
  if (cell === undefined) throw new Error(`no row for ${unit}`);
  return cell;
}

describe("Letters page (V1-058 R3)", () => {
  it("TEST-FE-862 Rent letters show each unpaid Rent month with its four steps, the counts and the next step", async () => {
    setup();
    await screen.findByText("Unpaid Rent after day 10");
    expect(screen.getByText(/as of 25\/11\/2026/)).toBeTruthy();
    // Cards: a person must give a notice (U101, U104), notices given and waiting (U102),
    // termination letter sent (U103).
    expect(
      screen.getByRole("button", { name: /^Letters to give: 2\./ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /^Notices given: 1\./ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /^Termination letter sent: 1\./ }),
    ).toBeTruthy();
    // Day 30 passed and the three notices are not all given.
    expect(screen.getByRole("alert").textContent).toContain("U104");

    const u101 = rowOf("U101");
    expect(within(u101).getByText("November 2026")).toBeTruthy();
    expect(within(u101).getByText(/INV26U101 · Day 25/)).toBeTruthy();
    expect(within(u101).getByText("$500.00 Rent owed")).toBeTruthy();
    expect(within(u101).getByText("Due Date 05/11/2026")).toBeTruthy();
    expect(
      ["Day 10", "Day 20", "Day 25", "Day 30"].every(
        (day) => within(u101).queryByText(day) !== null,
      ),
    ).toBe(true);
    expect(within(u101).getByText("Due since 10/11/2026")).toBeTruthy();
    expect(within(u101).getByText("Due since 20/11/2026")).toBeTruthy();
    expect(within(u101).getByText("Due since 25/11/2026")).toBeTruthy();
    expect(within(u101).getByText("On 30/11/2026")).toBeTruthy();
    expect(
      within(u101).getByRole("button", { name: /Record letter/ }),
    ).toBeTruthy();

    const u102 = rowOf("U102");
    expect(within(u102).getByText("Given 10/11/2026")).toBeTruthy();
    expect(u102.textContent).toContain("Sent by Telegram · TG-INV26U102-1");
    expect(within(u102).getByText("Given 20/11/2026")).toBeTruthy();
    expect(u102.textContent).toContain("Handed to the tenant · L-020");
    expect(within(u102).getByText("Wait for day 30 (30/11/2026)")).toBeTruthy();

    const u103 = rowOf("U103");
    expect(within(u103).getByText("October 2026")).toBeTruthy();
    expect(within(u103).getByText("Given 30/10/2026")).toBeTruthy();
    expect(
      within(u103).getByText("Left at the Parking with a witness"),
    ).toBeTruthy();
    const ending = within(u103).getByRole("link", { name: /End the Lease/ });
    expect(ending.textContent).toContain("MANAGER");
    expect(ending.getAttribute("href")).toBe("#/leases/terminate%3Alease-U103");

    // A card filters the table.
    fireEvent.click(
      screen.getByRole("button", { name: /^Termination letter sent/ }),
    );
    expect(screen.getByText("Showing: Termination letter sent")).toBeTruthy();
    expect(screen.queryByText("INV26U101 · Day 25")).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });

  it("TEST-FE-863 Record letter opens the case once, needs a letter number for each notice, and sends the very same request on Try again", async () => {
    const { api } = setup();
    await screen.findByText("Unpaid Rent after day 10");
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /Record letter/ }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Record a Rent letter · U101",
    });
    // The oldest notice not given is chosen. The termination letter is not in this dialog.
    expect(
      within(dialog).getByRole<HTMLInputElement>("radio", {
        name: /Notice 1 \(day 10\)/,
      }).checked,
    ).toBe(true);
    expect(within(dialog).getAllByRole("radio")).toHaveLength(3);
    fireEvent.click(
      within(dialog).getByRole("radio", { name: /Notice 2 \(day 20\)/ }),
    );
    expect(within(dialog).getByText(/Today, 25\/11\/2026/)).toBeTruthy();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record letter" }),
    );
    expect(within(dialog).getByText("Choose how it was given.")).toBeTruthy();
    expect(within(dialog).getByText("Write the details.")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Write the letter number. Each notice needs one.",
      ),
    ).toBeTruthy();
    expect(api.openCase).not.toHaveBeenCalled();

    // Owner 2026-10-25: on paper, or by email, Telegram or WhatsApp.
    expect(
      Array.from(
        within(dialog).getByLabelText<HTMLSelectElement>(/How it was given/)
          .options,
      ).map((option) => option.textContent),
    ).toEqual([
      "—",
      "Handed to the tenant",
      "Left at the Parking with a witness",
      "Sent by email",
      "Sent by Telegram",
      "Sent by WhatsApp",
      "Other",
    ]);
    fireEvent.change(within(dialog).getByLabelText(/How it was given/), {
      target: { value: "HAND" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Details/), {
      target: { value: " the tenant signed our copy " },
    });
    fireEvent.change(within(dialog).getByLabelText(/Letter number/), {
      target: { value: "L-021" },
    });
    api.recordLetter.mockRejectedValueOnce(new LettersUnavailableError());
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record letter" }),
    );
    await within(dialog).findByText(/No answer came back/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await screen.findByText("Notice 2 (day 20) recorded for U101.");

    expect(api.openCase).toHaveBeenCalledTimes(1);
    expect(api.openCase).toHaveBeenCalledWith(
      "lease-U101",
      { rent_invoice_line_id: "line-U101", reason: "Rent letter" },
      expect.any(String),
    );
    expect(api.recordLetter).toHaveBeenCalledTimes(2);
    const [first, second] = api.recordLetter.mock.calls;
    expect(first).toEqual(second);
    expect(first?.[0]).toBe("case-new");
    expect(first?.[1]).toEqual({
      event_kind: "TWENTY_DAY_WARNING",
      reason: "Day-20 warning letter given",
      communication_record: "Handed to the tenant: the tenant signed our copy",
      notice_document_reference: "L-021",
    });
    // The list is read again after the save.
    await waitFor(() => {
      expect(api.alerts).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-864 a notice goes on the open case, a given notice cannot be chosen again, and a change meanwhile reads the list again", async () => {
    const { api } = setup(null, (mocks) => {
      // U102 has its case and notice 1; notices 2 and 3 are due.
      mocks.alerts.mockResolvedValue({
        items: [
          alert("U102", "2026-11-05", "case-U102", {
            ...ALL_DUE,
            ten_day_notice_eligible: false,
            ten_day_notice_recorded: true,
          }),
        ],
        business_date: BUSINESS_DATE,
      });
    });
    await screen.findByText("Unpaid Rent after day 10");
    fireEvent.click(
      within(rowOf("U102")).getByRole("button", { name: /Record letter/ }),
    );
    const dialog = await screen.findByRole("dialog");
    const first = within(dialog).getByRole<HTMLInputElement>("radio", {
      name: /Notice 1 \(day 10\)/,
    });
    expect(first.disabled).toBe(true);
    expect(within(dialog).getByText(/already recorded/)).toBeTruthy();
    expect(
      within(dialog).getByRole<HTMLInputElement>("radio", {
        name: /Notice 2 \(day 20\)/,
      }).checked,
    ).toBe(true);
    fireEvent.click(
      within(dialog).getByRole("radio", { name: /Notice 3 \(day 25\)/ }),
    );
    fireEvent.change(within(dialog).getByLabelText(/How it was given/), {
      target: { value: "DOOR" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Details/), {
      target: { value: "Witness Sok Dara" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Letter number/), {
      target: { value: "L-025" },
    });
    api.recordLetter.mockRejectedValueOnce(new LettersConflictError());
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record letter" }),
    );
    await screen.findByText(/Somebody changed this meanwhile/);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.openCase).not.toHaveBeenCalled();
    expect(api.recordLetter).toHaveBeenCalledWith(
      "case-U102",
      {
        event_kind: "TWENTY_FIVE_DAY_NOTICE",
        reason: "Day-25 notice given",
        communication_record:
          "Left at the Unit with a witness: Witness Sok Dara",
        notice_document_reference: "L-025",
      },
      expect.any(String),
    );
  });

  it("TEST-FE-865 a person without the letter rights sees the letters but cannot record or give notice", async () => {
    setup(new Set(["rent_nonpayment.read", "leases.read"]));
    await screen.findByText("Unpaid Rent after day 10");
    expect(screen.queryByRole("button", { name: /Record letter/ })).toBeNull();
    expect(within(rowOf("U101")).getByText("Record letter")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /End the Lease/ })).toBeNull();
    expect(within(rowOf("U103")).getByText("Nothing to do now")).toBeTruthy();
    // The warnings tab has no Record warning without leases.warn.
    window.location.hash = "#/letters/warnings";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await screen.findByText("Noise at night 2");
    expect(screen.queryByRole("button", { name: /Record warning/ })).toBeNull();
    cleanup();

    // Only the warnings may be read: the page opens on them, without tabs.
    window.location.hash = "#/letters";
    const { api } = setup(new Set(["leases.read"]));
    await screen.findByText("Noise at night 2");
    expect(screen.queryByRole("link", { name: "Rent letters" })).toBeNull();
    expect(api.alerts).not.toHaveBeenCalled();
    cleanup();

    setup(new Set(["units.read"]));
    expect(
      await screen.findByText("You are not allowed to see this list."),
    ).toBeTruthy();
  });

  it("TEST-FE-2252 a tenant with Telegram gets the notices from the Tenant bot at 09:00, and a person may still record one by hand", async () => {
    const { api } = setup(null, (mocks) => {
      mocks.alerts.mockResolvedValue({
        items: [
          // Notice 1 went by itself; notice 2 and 3 are due today.
          alert("U101", "2026-11-05", "case-U102", {
            ...ALL_DUE,
            ten_day_notice_eligible: false,
            ten_day_notice_recorded: true,
            telegram_linked: true,
          }),
          // A Due Date on the 28th: no notice before the 29th.
          {
            ...alert("U104", "2026-11-28", null, { telegram_linked: true }),
            assessment: {
              ...alert("U104", "2026-11-28", null, {}).assessment,
              telegram_linked: true,
              step_days: {
                TEN_DAY_NOTICE: "2026-11-29",
                TWENTY_DAY_WARNING: "2026-11-29",
                TWENTY_FIVE_DAY_NOTICE: "2026-11-29",
                THIRTY_DAY_SERIOUS_DEFAULT: "2026-11-30",
              },
            },
          },
        ],
        business_date: BUSINESS_DATE,
      });
    });
    await screen.findByText("Unpaid Rent after day 10");
    // Nobody has to give a letter by hand.
    expect(
      screen.getByRole("button", { name: /^Letters to give: 0\./ }),
    ).toBeTruthy();
    const u101 = rowOf("U101");
    expect(u101.textContent).toContain("Sent by Telegram · TG-INV26U102-1");
    expect(
      within(u101).getByText("The Tenant bot sends notice 2 at 09:00."),
    ).toBeTruthy();
    expect(
      within(u101).queryByRole("button", { name: /^Record letter$/ }),
    ).toBeNull();
    const u104 = rowOf("U104");
    expect(within(u104).getAllByText("On 29/11/2026")).toHaveLength(3);
    expect(within(u104).getByText("Wait for day 10 (29/11/2026)")).toBeTruthy();

    // The bot could not send (for example the office computer was off): record it by hand.
    fireEvent.click(
      within(u101).getByRole("button", { name: "Record by hand" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Record a Rent letter · U101",
    });
    fireEvent.change(within(dialog).getByLabelText(/How it was given/), {
      target: { value: "HAND" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Details/), {
      target: { value: "signed our copy" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Letter number/), {
      target: { value: "L-020" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record letter" }),
    );
    await screen.findByText("Notice 2 (day 20) recorded for U101.");
    expect(api.recordLetter.mock.calls[0]?.[1].event_kind).toBe(
      "TWENTY_DAY_WARNING",
    );
  });

  it("TEST-FE-2253 on day 30 a Manager sends the termination letter: the day-30 step and the termination notice with its end date, the very same requests on Try again", async () => {
    const ready = (linked: boolean) => ({
      items: [
        alert("U102", "2026-10-05", "case-U102", {
          ...ALL_GIVEN,
          thirty_day_default_eligible: true,
          telegram_linked: linked,
        }),
      ],
      business_date: BUSINESS_DATE,
    });
    const { api } = setup(null, (mocks) => {
      mocks.alerts.mockResolvedValue(ready(true));
    });
    await screen.findByText("Unpaid Rent after day 10");
    expect(
      screen.getByRole("button", { name: /^Letters to give: 1\./ }),
    ).toBeTruthy();
    const open = within(rowOf("U102")).getByRole("button", {
      name: /Termination letter/,
    });
    expect(open.textContent).toContain("MANAGER");
    fireEvent.click(open);
    const dialog = await screen.findByRole("dialog", {
      name: "Termination letter · U102",
    });
    // Ready: the end date 30 days from today and the number. The termination letter is always
    // given on paper, also to a linked tenant: the paper letter is the official copy and the
    // Tenant bot sends a copy. So how the paper was given is never filled in by the app.
    const ends = addDays(today, 30);
    expect(
      within(dialog).getByText(
        /Print the letter and give it on paper\. The paper letter is the official copy\. The Tenant bot also sends a copy in Telegram/,
      ),
    ).toBeTruthy();
    expect(
      within(dialog).getByLabelText<HTMLSelectElement>(/How it was given/)
        .value,
    ).toBe("");
    expect(
      within(dialog).getByLabelText<HTMLInputElement>(/Letter number/).value,
    ).toBe("TL-INV26U102");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Send termination letter" }),
    );
    expect(within(dialog).getByText("Choose how it was given.")).toBeTruthy();
    expect(api.recordLetter).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/How it was given/), {
      target: { value: "HAND" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Details/), {
      target: { value: " the tenant signed our copy " },
    });
    api.recordNotice.mockRejectedValueOnce(new LettersUnavailableError());
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Send termination letter" }),
    );
    await within(dialog).findByText(/No answer came back/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await screen.findByText("Termination letter recorded for U102.");

    expect(api.openCase).not.toHaveBeenCalled();
    expect(api.recordLetter).toHaveBeenCalledTimes(2);
    expect(api.recordLetter.mock.calls[0]).toEqual(
      api.recordLetter.mock.calls[1],
    );
    expect(api.recordLetter.mock.calls[0]?.[0]).toBe("case-U102");
    expect(api.recordLetter.mock.calls[0]?.[1]).toEqual({
      event_kind: "THIRTY_DAY_SERIOUS_DEFAULT",
      reason: "Termination letter sent",
      communication_record: "Handed to the tenant: the tenant signed our copy",
      notice_document_reference: "TL-INV26U102",
    });
    expect(api.recordNotice).toHaveBeenCalledTimes(2);
    expect(api.recordNotice.mock.calls[0]).toEqual(
      api.recordNotice.mock.calls[1],
    );
    const [property, leaseId, notice] = api.recordNotice.mock.calls[0] ?? [];
    expect([property, leaseId]).toEqual(["property-1", "lease-U102"]);
    expect(notice).toMatchObject({
      expected_lease_version: 3,
      notice_date: today,
      intended_termination_date: ends,
      governing_lease_provision:
        "Signed Lease: Rent not paid after the notices of day 10, day 20 and day 25 (BR-LEASE-026)",
      approved_grounds:
        "Rent unpaid on day 30 after the three notices (DL-237)",
      evidence_reference: "TL-INV26U102",
      communication_record: "Handed to the tenant: the tenant signed our copy",
    });
    expect(notice?.notice_text).toContain("U102");
    cleanup();

    // No Telegram link: the paper letter, and how it was given must be written.
    window.location.hash = "#/letters";
    const paper = setup(null, (mocks) => {
      mocks.alerts.mockResolvedValue(ready(false));
    });
    await screen.findByText("Unpaid Rent after day 10");
    fireEvent.click(
      within(rowOf("U102")).getByRole("button", {
        name: /Termination letter/,
      }),
    );
    const second = await screen.findByRole("dialog");
    expect(
      within(second).getByText(/has no Telegram link\. Print the letter/),
    ).toBeTruthy();
    fireEvent.change(within(second).getByLabelText(/The Lease ends on/), {
      target: { value: addDays(today, -1) },
    });
    fireEvent.click(
      within(second).getByRole("button", { name: "Send termination letter" }),
    );
    expect(within(second).getByText("Choose how it was given.")).toBeTruthy();
    expect(within(second).getByText("Write the details.")).toBeTruthy();
    expect(
      within(second).getByText("The end date cannot be before today."),
    ).toBeTruthy();
    expect(paper.api.recordLetter).not.toHaveBeenCalled();
  });

  it("TEST-FE-2254 without the right to end a Lease the termination letter is shown as waiting for a Manager, and it waits for the three notices", async () => {
    setup(
      new Set([
        "rent_nonpayment.read",
        "rent_nonpayment.case_manage",
        "rent_nonpayment.event_post",
      ]),
      (mocks) => {
        mocks.alerts.mockResolvedValue({
          items: [
            alert("U102", "2026-10-05", "case-U102", {
              ...ALL_GIVEN,
              thirty_day_default_eligible: true,
            }),
            alert("U104", "2026-10-05", null, ALL_DUE),
          ],
          business_date: BUSINESS_DATE,
        });
      },
    );
    await screen.findByText("Unpaid Rent after day 10");
    const u102 = rowOf("U102");
    expect(
      within(u102).queryByRole("button", { name: /Termination letter/ }),
    ).toBeNull();
    expect(
      within(u102).getByText(
        "Termination letter ready: a Manager or the Owner sends it",
      ),
    ).toBeTruthy();
    // Day 30 passed with no notice: the notices come first, and staff may record them.
    expect(screen.getByRole("alert").textContent).toContain(
      "U104 · Day 30 has passed and the three notices are not all given.",
    );
    expect(
      within(rowOf("U104")).getByRole("button", { name: /Record letter/ }),
    ).toBeTruthy();
  });

  it("TEST-FE-866 Lease rule warnings list each warned Lease with n of 3, the last warning and its breach", async () => {
    window.location.hash = "#/letters/warnings";
    const { api } = setup();
    await screen.findByText("Smoking inside");
    expect(screen.getByText(/Three written warnings/)).toBeTruthy();
    const u101 = rowOf("Lease · U101");
    expect(within(u101).getByText("2 of 3")).toBeTruthy();
    expect(within(u101).getByText("12/09/2026")).toBeTruthy();
    expect(within(u101).getByText("Noise at night 2")).toBeTruthy();
    expect(
      within(u101).getByText("Lease article 11.3 · Handed to the tenant"),
    ).toBeTruthy();
    const u102 = rowOf("Lease · U102");
    expect(
      within(u102).getByText("3 of 3").closest(".ui-chip")?.className,
    ).toContain("err");
    expect(
      within(u102).getByText("Lease article 12.1 · Sent by Telegram"),
    ).toBeTruthy();
    // Leases without warnings are not listed; drafts are not read.
    expect(screen.queryByText("Lease · U103")).toBeNull();
    expect(api.warnings).not.toHaveBeenCalledWith("lease-U106");

    // A Lease whose warnings cannot be read is named, with Retry.
    cleanup();
    window.location.hash = "#/letters/warnings";
    const second = setup(null, (mocks) => {
      mocks.warnings.mockImplementation((leaseId) =>
        leaseId === "lease-U103"
          ? Promise.reject(new Error("down"))
          : Promise.resolve([]),
      );
    });
    expect(
      await screen.findByText(/The warnings of U103 could not be read/),
    ).toBeTruthy();
    second.api.warnings.mockResolvedValue([]);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(screen.queryByText(/The warnings of U103/)).toBeNull();
    });
    expect(screen.getByText("No Lease rule warnings recorded.")).toBeTruthy();
  });

  it("TEST-FE-867 Record warning offers moved-in Leases, numbers the warning from the server and checks the dates", async () => {
    window.location.hash = "#/letters/warnings";
    const { api } = setup();
    await screen.findByText("Smoking inside");
    fireEvent.click(
      within(rowOf("Lease · U101")).getByRole("button", {
        name: /Record warning/,
      }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Record a Lease rule warning",
    });
    const select =
      within(dialog).getByLabelText<HTMLSelectElement>(/^LeaseRequired$/);
    expect(select.value).toBe("lease-U101");
    const offered = Array.from(select.options).map((option) => option.value);
    expect(offered).toEqual([
      "lease-U101",
      "lease-U102",
      "lease-U103",
      "lease-U104",
    ]);
    await within(dialog).findByText(/Warning 3 of 3 for this Lease/);

    fireEvent.change(within(dialog).getByLabelText(/Date of the breach/), {
      target: { value: addDays(today, 1) },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record warning" }),
    );
    expect(
      within(dialog).getByText(
        "The breach comes first, then the warning; neither after today.",
      ),
    ).toBeTruthy();
    expect(within(dialog).getByText("Write what happened.")).toBeTruthy();
    expect(within(dialog).getByText(/Write the Lease article/)).toBeTruthy();
    expect(api.recordWarning).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText(/Date of the breach/), {
      target: { value: addDays(today, -2) },
    });
    fireEvent.change(within(dialog).getByLabelText(/What happened/), {
      target: { value: " Loud party after 22:00 " },
    });
    fireEvent.change(within(dialog).getByLabelText(/Lease article/), {
      target: { value: "11.3" },
    });
    fireEvent.change(within(dialog).getByLabelText(/How it was given/), {
      target: { value: "TG" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record warning" }),
    );
    await screen.findByText("Warning 3 recorded for U101.");
    expect(api.recordWarning).toHaveBeenCalledWith(
      "lease-U101",
      {
        warning_sequence: 3,
        violation_date: addDays(today, -2),
        warning_date: today,
        violation_description: "Loud party after 22:00",
        lease_provision: "11.3",
        communication_record: "Sent by Telegram",
        reason: "Lease rule warning given",
      },
      expect.any(String),
    );

    // Another Lease gets its own number from the server.
    const [again] = screen.getAllByRole("button", { name: /Record warning/ });
    if (again === undefined) throw new Error("no Record warning button");
    fireEvent.click(again);
    const next = await screen.findByRole("dialog");
    fireEvent.change(within(next).getByLabelText(/^LeaseRequired$/), {
      target: { value: "lease-U104" },
    });
    await within(next).findByText(/Warning 1 of 3 for this Lease/);
    expect(api.warningContext).toHaveBeenLastCalledWith("lease-U104");
  });

  it("TEST-FE-868 Cancel after the case was opened reads the list again, and Leases that cannot be warned get no Record warning button", async () => {
    const { api } = setup();
    await screen.findByText("Unpaid Rent after day 10");
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /Record letter/ }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Record a Rent letter · U101",
    });
    fireEvent.change(within(dialog).getByLabelText(/How it was given/), {
      target: { value: "HAND" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Details/), {
      target: { value: "signed our copy" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Letter number/), {
      target: { value: "L-021" },
    });
    api.recordLetter.mockRejectedValueOnce(new LettersRequestError());
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record letter" }),
    );
    await waitFor(() => {
      expect(api.recordLetter).toHaveBeenCalledTimes(1);
    });
    expect(api.openCase).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    // The opened case shows on the next read, so a new try never opens a second case.
    await waitFor(() => {
      expect(api.alerts).toHaveBeenCalledTimes(2);
    });

    cleanup();
    window.location.hash = "#/letters/warnings";
    setup(null, (mocks) => {
      mocks.warnings.mockImplementation((leaseId) =>
        Promise.resolve(
          leaseId === "lease-U105" || leaseId === "lease-U101"
            ? [warning(leaseId.slice(6), 1)]
            : [],
        ),
      );
    });
    await screen.findByText("Lease · U105");
    expect(
      within(rowOf("Lease · U101")).getByRole("button", {
        name: /Record warning/,
      }),
    ).toBeTruthy();
    expect(
      within(rowOf("Lease · U105")).queryByRole("button", {
        name: /Record warning/,
      }),
    ).toBeNull();
  });
});
