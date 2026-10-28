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
      twenty_day_warning_eligible: false,
      thirty_day_default_eligible: false,
      warning_recorded: false,
      serious_default_recorded: false,
      ...flags,
    },
  };
}

const ALERTS: RentAlert[] = [
  // November Rent, day 25: the day-20 letter is due.
  alert("U101", "2026-11-05", null, { twenty_day_warning_eligible: true }),
  // November Rent, day-20 letter given: wait for day 30.
  alert("U102", "2026-11-05", "case-U102", { warning_recorded: true }),
  // October Rent, both letters given: a Termination notice may follow.
  alert("U103", "2026-10-05", "case-U103", {
    warning_recorded: true,
    serious_default_recorded: true,
  }),
  // October Rent, both days passed and no letter.
  alert("U104", "2026-10-05", null, {
    twenty_day_warning_eligible: true,
    thirty_day_default_eligible: true,
  }),
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
      "TWENTY_DAY_WARNING",
      "2026-11-20",
      "Handed to the tenant: signed our copy",
      "L-020",
    ),
  ],
  "case-U103": [
    letter(
      "TWENTY_DAY_WARNING",
      "2026-10-21",
      "Sent by Telegram: chat photo kept",
      "L-011",
    ),
    letter(
      "THIRTY_DAY_SERIOUS_DEFAULT",
      "2026-10-30",
      "Left at the Unit with a witness: Sok Dara",
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
    recordNotice: vi.fn<LettersApi["recordNotice"]>(() =>
      Promise.reject(new Error("not used")),
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
  it("TEST-FE-862 Rent letters show each unpaid Rent month with its letters, the counts and the next step", async () => {
    setup();
    await screen.findByText("Unpaid Rent after day 20");
    expect(screen.getByText(/as of 25\/11\/2026/)).toBeTruthy();
    // Cards: due (U101 day 20, U104 day 20), day-20 given and waiting (U102), day-30 given (U103).
    expect(
      screen.getByRole("button", { name: /^Letters due: 2\./ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /^Day-20 letter given: 1\./ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /^Day-30 letter given: 1\./ }),
    ).toBeTruthy();
    // Both days passed with no letter.
    expect(screen.getByRole("alert").textContent).toContain("U104");

    const u101 = rowOf("U101");
    expect(within(u101).getByText("November 2026")).toBeTruthy();
    expect(within(u101).getByText(/INV26U101 · Day 25/)).toBeTruthy();
    expect(within(u101).getByText("$500.00 Rent owed")).toBeTruthy();
    expect(within(u101).getByText("Due Date 05/11/2026")).toBeTruthy();
    expect(within(u101).getByText("Due since 20/11/2026")).toBeTruthy();
    expect(within(u101).getByText("On 30/11/2026")).toBeTruthy();
    expect(
      within(u101).getByRole("button", { name: /Record letter/ }),
    ).toBeTruthy();

    const u102 = rowOf("U102");
    expect(within(u102).getByText("Given 20/11/2026")).toBeTruthy();
    expect(u102.textContent).toContain("Handed to the tenant · L-020");
    expect(within(u102).getByText("Wait for day 30 (30/11/2026)")).toBeTruthy();

    const u103 = rowOf("U103");
    expect(within(u103).getByText("October 2026")).toBeTruthy();
    expect(within(u103).getByText("Given 30/10/2026")).toBeTruthy();
    expect(
      within(u103).getByText("Left at the Unit with a witness"),
    ).toBeTruthy();
    const notice = within(u103).getByRole("link", {
      name: /Termination notice/,
    });
    expect(notice.textContent).toContain("MANAGER");
    expect(notice.getAttribute("href")).toBe("#/leases/terminate%3Alease-U103");

    // A card filters the table.
    fireEvent.click(
      screen.getByRole("button", { name: /^Day-30 letter given/ }),
    );
    expect(screen.getByText("Showing: Day-30 letter given")).toBeTruthy();
    expect(screen.queryByText("INV26U101 · Day 25")).toBeNull();
    // Only cases with a case read their letters.
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });

  it("TEST-FE-863 Record letter opens the case once, needs a letter number for day 20, and sends the very same request on Try again", async () => {
    const { api } = setup();
    await screen.findByText("Unpaid Rent after day 20");
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /Record letter/ }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Record a Rent letter · U101",
    });
    // Day 20 is chosen; day 30 is not due yet.
    const day20 = within(dialog).getByRole<HTMLInputElement>("radio", {
      name: /Day-20 warning letter/,
    });
    expect(day20.checked).toBe(true);
    expect(
      within(dialog).getByRole<HTMLInputElement>("radio", {
        name: /Day-30 default notice/,
      }).disabled,
    ).toBe(true);
    expect(within(dialog).getByText(/Today, 25\/11\/2026/)).toBeTruthy();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record letter" }),
    );
    expect(within(dialog).getByText("Choose how it was given.")).toBeTruthy();
    expect(within(dialog).getByText("Write the details.")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Write the letter number. The day-20 letter needs one.",
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
      "Left at the Unit with a witness",
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
    await screen.findByText("Day-20 warning letter recorded for U101.");

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

  it("TEST-FE-864 the day-30 letter goes on the open case without a number, and a change meanwhile reads the list again", async () => {
    const { api } = setup();
    await screen.findByText("Unpaid Rent after day 20");
    // U104: both letters due; day 20 comes first.
    fireEvent.click(
      within(rowOf("U104")).getByRole("button", { name: /Record letter/ }),
    );
    let dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole<HTMLInputElement>("radio", {
        name: /Day-20 warning letter/,
      }).checked,
    ).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    // U102 has its case and its day-20 letter; on day 30 only the day-30 letter is left.
    api.alerts.mockResolvedValue({
      items: [
        alert("U102", "2026-11-05", "case-U102", {
          warning_recorded: true,
          thirty_day_default_eligible: true,
        }),
      ],
      business_date: "2026-11-30",
    });
    // Going to the other tab and back reads the list again.
    window.location.hash = "#/letters/warnings";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await screen.findByText("Smoking inside");
    window.location.hash = "#/letters";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await screen.findByText(/as of 30\/11\/2026/);
    fireEvent.click(
      within(rowOf("U102")).getByRole("button", { name: /Record letter/ }),
    );
    dialog = await screen.findByRole("dialog");
    const day20 = within(dialog).getByRole<HTMLInputElement>("radio", {
      name: /Day-20 warning letter/,
    });
    expect(day20.disabled).toBe(true);
    expect(within(dialog).getByText(/already recorded/)).toBeTruthy();
    expect(within(dialog).getByText("Optional")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/How it was given/), {
      target: { value: "DOOR" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Details/), {
      target: { value: "Witness Sok Dara" },
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
        event_kind: "THIRTY_DAY_SERIOUS_DEFAULT",
        reason: "Day-30 default notice given",
        communication_record:
          "Left at the Unit with a witness: Witness Sok Dara",
      },
      expect.any(String),
    );
  });

  it("TEST-FE-865 a person without the letter rights sees the letters but cannot record or give notice", async () => {
    setup(new Set(["rent_nonpayment.read", "leases.read"]));
    await screen.findByText("Unpaid Rent after day 20");
    expect(screen.queryByRole("button", { name: /Record letter/ })).toBeNull();
    expect(within(rowOf("U101")).getByText("Record letter")).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: /Termination notice/ }),
    ).toBeNull();
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
    await screen.findByText("Unpaid Rent after day 20");
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
