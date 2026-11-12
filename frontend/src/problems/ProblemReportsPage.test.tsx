import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProblemReportsPage } from "./ProblemReportsPage";
import {
  type FindingSource,
  type ProblemChoices,
  type ProblemMonth,
  type ProblemReport,
  ProblemsError,
  type ProblemsApi,
  type ProblemType,
} from "./problemsClient";

const NOW = new Date("2026-11-04T03:00:00Z"); // 10:00 in Phnom Penh

beforeEach(() => {
  window.location.hash = "#/problems";
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

const WATER: ProblemType = {
  id: "t-water",
  code: "WATER",
  name_en: "Water",
  name_kh: "ទឹក",
  icon: "drop",
  always_urgent: false,
};
const SAFETY: ProblemType = {
  id: "t-safety",
  code: "SAFETY",
  name_en: "Safety (fire, gas, smoke)",
  name_kh: null,
  icon: "flame",
  always_urgent: true,
};
const LIFT = { id: "pl-lift", code: "LIFT", name_en: "Lift", name_kh: null };

function report(extra: Partial<ProblemReport>): ProblemReport {
  return {
    report_id: "r-1",
    report_number: "UP260001",
    kind: "UNIT",
    status: "RECEIVED",
    state: "RECEIVED",
    late: null,
    repeat: null,
    unit_id: "u-101",
    unit_number: "U101",
    lease_id: "l-1",
    customer_id: "c-1",
    customer_name: "Sok Dara",
    customer_phone: "+855 12 000 001",
    place: { item_id: "i-bath", number: 1, name_en: "Bathroom", name_kh: null },
    problem_place: null,
    floor: null,
    problem_type: WATER,
    description: "The tap leaks",
    urgent: false,
    always_urgent: false,
    may_enter: false,
    best_time: "AM",
    source: "PHONE",
    reported_by: null,
    repair_job: false,
    contacted_at: null,
    contacted_how: null,
    technician: null,
    visit_on: null,
    visit_at: null,
    cause: null,
    cause_note: null,
    fixed_at_check: false,
    pays: null,
    tenant_amount_usd_cents: null,
    tenant_reason: null,
    decided_on: null,
    tenant_answer: null,
    tenant_answer_how: null,
    tenant_answer_on: null,
    tenant_said: null,
    tenant_can_answer: true,
    damage: null,
    done_at: null,
    finding: null,
    stay: null,
    cost: null,
    closes_on: null,
    closed_at: null,
    close_note: null,
    joined_to: null,
    join: null,
    joined: [],
    created_at: "2026-11-04T02:00:00Z",
    created_by_name: "Staff One",
    version: 1,
    history: [
      {
        step: "RECEIVED",
        note: null,
        details: { source: "PHONE" },
        at: "2026-11-04T02:00:00Z",
        by_name: "Staff One",
      },
    ],
    ...extra,
  };
}

const UP1 = report({});
const UP2 = report({
  report_id: "r-2",
  report_number: "UP260002",
  urgent: true,
  late: "URGENT",
  repeat: [
    {
      report_id: "r-0",
      report_number: "UP250009",
      created_at: "2026-09-01T00:00:00Z",
    },
  ],
  created_at: "2026-11-03T01:00:00Z",
});
const BP1 = report({
  report_id: "b-1",
  report_number: "BP260001",
  kind: "BUILDING",
  unit_id: null,
  unit_number: null,
  lease_id: null,
  customer_id: null,
  customer_name: null,
  customer_phone: null,
  place: null,
  problem_place: LIFT,
  floor: "3",
  description: "The lift stops",
  created_at: "2026-11-02T01:00:00Z",
});
const BP2 = report({
  report_id: "b-2",
  report_number: "BP260002",
  kind: "BUILDING",
  status: "JOINED",
  state: "JOINED",
  unit_id: null,
  unit_number: null,
  customer_id: null,
  customer_name: null,
  place: null,
  problem_place: LIFT,
  description: "Lift is stuck again",
  joined_to: { report_id: "b-1", report_number: "BP260001", state: "RECEIVED" },
  join: {
    reason: "Same lift",
    joined_at: "2026-11-03T02:00:00Z",
    joined_by_name: "Manager One",
    previous_status: "RECEIVED",
  },
});
const DONE = report({
  report_id: "r-3",
  report_number: "UP260003",
  status: "CLOSED",
  state: "CLOSED",
  description: "Old leak",
});

const CHOICES: ProblemChoices = {
  types: [WATER, SAFETY],
  places: [LIFT],
  units: [
    {
      unit_id: "u-101",
      unit_number: "U101",
      floor: "1",
      customer_name: "Sok Dara",
      places: [
        {
          item_id: "i-bath",
          number: 1,
          name_en: "Bathroom",
          name_kh: null,
          count: 1,
        },
      ],
    },
    {
      unit_id: "u-102",
      unit_number: "U102",
      floor: "1",
      customer_name: null,
      places: [],
    },
  ],
  rules: {
    repeat_count: 3,
    repeat_days: 90,
    urgent_hours: 1,
    plan_workdays: 1,
    auto_close_days: 3,
  },
  today: "2026-11-04",
};

function element(found: HTMLElement | null): HTMLElement {
  if (found === null) throw new Error("not found");
  return found;
}

function row(rows: HTMLElement[], index: number): HTMLElement {
  return element(rows[index] ?? null);
}

const STAFF = new Set(["problem_reports.read", "problem_reports.add"]);
const MANAGER = new Set([
  "problem_reports.read",
  "problem_reports.add",
  "problem_reports.plan",
  "problem_reports.join",
]);

const FINDING: FindingSource = {
  finding_id: "f-1",
  inspection_id: "i-1",
  lease_id: "lease-1",
  inspection_date: "2026-11-03",
  ordinal: 2,
  description: "Bedroom door handle broken",
  pet_related: false,
  unit_id: "u-101",
  unit_number: "U101",
  replaced: false,
  report: null,
};

function apiOf(overrides: Partial<ProblemsApi> = {}): ProblemsApi {
  return {
    list: vi.fn(() => Promise.resolve([UP1, UP2, BP1, BP2, DONE])),
    get: vi.fn((_: string, id: string) =>
      Promise.resolve(
        [UP1, UP2, BP1, BP2, DONE].find((one) => one.report_id === id) ?? UP1,
      ),
    ),
    choices: vi.fn(() => Promise.resolve(CHOICES)),
    add: vi.fn(() =>
      Promise.resolve(report({ report_id: "r-9", report_number: "UP260009" })),
    ),
    step: vi.fn((_: string, one: ProblemReport) => Promise.resolve(one)),
    answer: vi.fn((_: string, one: ProblemReport) => Promise.resolve(one)),
    cost: vi.fn((_: string, one: ProblemReport) => Promise.resolve(one)),
    checkCost: vi.fn((_: string, one: ProblemReport) => Promise.resolve(one)),
    summary: vi.fn(() =>
      Promise.resolve({ open: 0, urgent: 0, late: 0, costs_to_check: [] }),
    ),
    month: vi.fn(() => Promise.reject(new ProblemsError(403))),
    finding: vi.fn(() => Promise.resolve(FINDING)),
    ...overrides,
  };
}

function show(api: ProblemsApi, capabilities: ReadonlySet<string>) {
  render(
    <ProblemReportsPage
      active
      api={api}
      capabilities={capabilities}
      language="en"
      now={NOW}
      propertyId="property-1"
    />,
  );
}

describe("Building › Problem reports (V1.1 part 7, DL-124)", () => {
  it("TEST-FE-1220 The list shows Open, Urgent, Late and Done with counts, oldest first, the Urgent, Repeat and joined marks, a joined report in a grey row under its main report, the filters, and New Problem report only to a person who may add one", async () => {
    show(apiOf(), new Set(["problem_reports.read"]));
    const table = await screen.findByRole("table");
    expect(
      screen.queryByRole("link", { name: "New Problem report" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Open 3" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Urgent 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Late 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Done 1" })).toBeTruthy();
    const rows = within(table).getAllByRole("row").slice(1);
    // Oldest first; the joined report follows its main report.
    expect(
      rows.map((row) => within(row).getAllByRole("link")[0]?.textContent),
    ).toEqual(["BP260001", "BP260002", "UP260002", "UP260001"]);
    expect(within(row(rows, 0)).getByText("+1 joined")).toBeTruthy();
    expect(within(row(rows, 1)).getByText("Joined to BP260001")).toBeTruthy();
    expect(within(row(rows, 2)).getByText("Urgent")).toBeTruthy();
    expect(within(row(rows, 2)).getByText("Repeat")).toBeTruthy();
    expect(
      within(row(rows, 2)).getByText("Late: the tenant is not contacted yet"),
    ).toBeTruthy();
    expect(within(row(rows, 0)).getByText("Lift · floor 3")).toBeTruthy();
    expect(within(row(rows, 3)).getByText("U101 · Bathroom 1")).toBeTruthy();
    expect(screen.getByText("3 reports")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Kind"), {
      target: { value: "BUILDING" },
    });
    expect(screen.getByText("1 report")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    fireEvent.click(screen.getByRole("button", { name: "Done 1" }));
    expect(screen.getByText("UP260003")).toBeTruthy();
    expect(screen.queryByText("UP260001")).toBeNull();
    cleanup();

    show(apiOf(), STAFF);
    expect(
      (
        await screen.findByRole("link", { name: "New Problem report" })
      ).getAttribute("href"),
    ).toBe("#/problems/new");
  });

  it("TEST-FE-1221 New Problem report checks the form, Safety is always urgent, the Building kind asks for the shared place and floor, and Same problem saves it joined to an open report here", async () => {
    window.location.hash = "#/problems/new";
    const api = apiOf();
    show(api, STAFF);
    // The list is read first so the form can offer "Open reports here".
    await waitFor(() => {
      expect(api.list).toHaveBeenCalled();
    });
    fireEvent.click(await screen.findByRole("button", { name: "Save report" }));
    expect(screen.getByText("Choose the Unit.")).toBeTruthy();
    expect(screen.getByText("Choose the type.")).toBeTruthy();
    expect(screen.getByText("Please write this.")).toBeTruthy();
    expect(api.add).not.toHaveBeenCalled();

    fireEvent.change(element(document.getElementById("np-unit")), {
      target: { value: "u-101" },
    });
    expect(screen.getByText("Open reports here (2)")).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Safety/));
    expect(screen.getByText(/Safety is always urgent/)).toBeTruthy();
    const urgentYes = document.getElementById(
      "np-urgent-y",
    ) as HTMLInputElement;
    expect(urgentYes.checked && urgentYes.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/^What is wrong/), {
      target: { value: "  Smoke from the plug  " },
    });
    fireEvent.change(screen.getByLabelText("Place in the Unit (if known)"), {
      target: { value: "i-bath|1" },
    });
    fireEvent.click(screen.getByLabelText("Walk-in"));
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    await waitFor(() => {
      expect(api.add).toHaveBeenCalledWith("property-1", {
        kind: "UNIT",
        source: "WALKIN",
        problem_type_id: "t-safety",
        description: "Smoke from the plug",
        urgent: true,
        unit_id: "u-101",
        may_enter: false,
        best_time: "ANY",
        place_item_id: "i-bath",
        place_number: 1,
      });
    });
    await waitFor(() => {
      expect(window.location.hash).toBe("#/problems/pr%3Ar-9");
    });
    expect(
      await screen.findByText("UP260009 added. Status: Received."),
    ).toBeTruthy();
    cleanup();

    window.location.hash = "#/problems/new";
    const api2 = apiOf();
    show(api2, STAFF);
    await waitFor(() => {
      expect(api2.list).toHaveBeenCalled();
    });
    fireEvent.click(await screen.findByLabelText(/^Building problem/));
    expect(document.getElementById("np-unit")).toBeNull();
    fireEvent.change(screen.getByLabelText(/^Where in the building/), {
      target: { value: "pl-lift" },
    });
    fireEvent.change(screen.getByLabelText("Floor (if known)"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByLabelText("Water"));
    fireEvent.click(screen.getByLabelText("No"));
    fireEvent.change(screen.getByLabelText(/^What is wrong/), {
      target: { value: "The lift stops" },
    });
    const here = element(
      screen.getByText("Open reports here (1)").closest("section"),
    );
    fireEvent.click(within(here).getByRole("button", { name: "Same problem" }));
    await waitFor(() => {
      expect(api2.add).toHaveBeenCalledWith(
        "property-1",
        expect.objectContaining({
          kind: "BUILDING",
          problem_place_id: "pl-lift",
          floor: "3",
          urgent: false,
          same_as: "b-1",
        }),
      );
    });
  });

  it("TEST-FE-1222 A report's Next step fits its status: an urgent report is first marked Contacted, then the check visit is planned with a typed technician, a day and a time every 30 minutes; Staff see a lock line", async () => {
    window.location.hash = "#/problems/pr:r-2";
    const planned = report({
      ...UP2,
      status: "PLANNED",
      state: "PLANNED",
      contacted_at: "2026-11-04T02:30:00Z",
      technician: "Chan Rith",
      visit_on: "2026-11-05",
      visit_at: "09:30",
      version: 3,
    });
    const step = vi
      .fn()
      .mockResolvedValueOnce(
        report({ ...UP2, contacted_at: "2026-11-04T02:30:00Z", version: 2 }),
      )
      .mockResolvedValueOnce(planned);
    const api = apiOf({ step });
    show(api, MANAGER);
    expect(
      await screen.findByText("Urgent: contact the tenant within 1 h."),
    ).toBeTruthy();
    expect(screen.getByText(/Repeat problem/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "UP250009" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Contacted" }));
    let dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Choose one.")).toBeTruthy();
    fireEvent.click(within(dialog).getByLabelText("Phone call"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(step).toHaveBeenCalledWith(
        "property-1",
        expect.objectContaining({ report_id: "r-2" }),
        { step: "CONTACTED", how: "PHONE" },
      );
    });
    expect(await screen.findByText("UP260002: saved.")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Plan the check visit" }),
    );
    dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Type the technician's name."),
    ).toBeTruthy();
    expect(
      within(dialog).getByText("Pick a time later than now."),
    ).toBeTruthy();
    const times = within(dialog).getByLabelText(/^Time/);
    const options = Array.from(times.querySelectorAll("option")).map(
      (one) => one.value,
    );
    expect(options[1]).toBe("07:00");
    expect(options[options.length - 1]).toBe("16:30");
    expect(options).toHaveLength(21);
    fireEvent.change(within(dialog).getByLabelText(/^Technician/), {
      target: { value: " Chan Rith " },
    });
    fireEvent.change(times, { target: { value: "14:30" } });
    expect(
      within(dialog).getByText(/Tenant's best time: Morning/),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(step).toHaveBeenLastCalledWith(
        "property-1",
        expect.objectContaining({ version: 2 }),
        {
          step: "PLAN",
          technician: "Chan Rith",
          visit_on: "2026-11-04",
          visit_at: "14:30",
        },
      );
    });
    expect(
      await screen.findByText(/Chan Rith comes 05\/11\/2026 09:30/),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Write the check report" }),
    ).toBeTruthy();
    cleanup();

    window.location.hash = "#/problems/pr:r-1";
    show(apiOf(), STAFF);
    expect(
      await screen.findByText(/Only a Manager or the Owner plans repairs/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Plan the check visit" }),
    ).toBeNull();
  });

  it("TEST-FE-1223 Tenant pays needs the amount and the reason; the tenant's answer Agreed makes the Damage Invoice draft and the page links to it; Refused needs what the tenant said and what happens next", async () => {
    window.location.hash = "#/problems/pr:r-1";
    const checked = report({
      status: "CHECKED",
      state: "CHECKED",
      cause: "DAMAGE",
      version: 4,
    });
    const waiting = report({
      status: "WAITING_TENANT",
      state: "WAITING_TENANT",
      cause: "DAMAGE",
      pays: "TENANT",
      tenant_amount_usd_cents: 2500,
      tenant_reason: "Broken by a guest",
      decided_on: "2026-11-04",
      version: 5,
    });
    const agreed = report({
      ...waiting,
      status: "REPAIR_PLANNED",
      state: "REPAIR_PLANNED",
      tenant_answer: "AGREED",
      tenant_answer_how: "PHONE",
      tenant_answer_on: "2026-11-04",
      damage: {
        charge_id: "ch-1",
        invoice_id: "inv-7",
        invoice_number: "D7",
        invoice_status: "DRAFT",
        amount_usd_cents: 2500,
      },
      version: 6,
    });
    const step = vi.fn(() => Promise.resolve(waiting));
    const answer = vi.fn(() => Promise.resolve(agreed));
    const api = apiOf({
      get: vi.fn(() => Promise.resolve(checked)),
      step,
      answer,
    });
    show(api, MANAGER);
    fireEvent.click(
      await screen.findByRole("button", { name: "Decide who pays" }),
    );
    let dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText("Tenant pays"));
    fireEvent.change(within(dialog).getByLabelText(/^Amount the tenant pays/), {
      target: { value: "abc" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Type the amount.")).toBeTruthy();
    expect(within(dialog).getByText("Please write this.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Amount the tenant pays/), {
      target: { value: "25" },
    });
    fireEvent.change(
      within(dialog).getByLabelText(/^Reason \(the tenant sees it\)/),
      {
        target: { value: "Broken by a guest" },
      },
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(step).toHaveBeenCalledWith("property-1", checked, {
        step: "DECIDE",
        pays: "TENANT",
        amount_usd_cents: 2500,
        reason: "Broken by a guest",
      });
    });
    expect(
      await screen.findByText(
        "The Damage Invoice draft is made when the tenant agrees.",
      ),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Tenant's answer" }));
    dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText("Refused"));
    fireEvent.click(within(dialog).getByLabelText("Phone call"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getAllByText(/Please write this|Choose one/),
    ).toHaveLength(2);
    expect(answer).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByLabelText("Agreed"));
    expect(
      within(dialog).getByText(
        "Saving makes the Damage Invoice draft for $25.00 at once.",
      ),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(answer).toHaveBeenCalledWith("property-1", waiting, {
        answer: "AGREED",
        how: "PHONE",
        answered_on: "2026-11-04",
        said: null,
        after_refusal: null,
      });
    });
    expect(
      await screen.findByText(
        "UP260001: the tenant agreed. Damage Invoice draft D7 is made.",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open Damage Invoice D7" })
        .getAttribute("href"),
    ).toBe("#/invoices/inv%3Ainv-7");
  });

  it("TEST-FE-1224 Join to a report offers only open reports of the same kind and place and needs a reason; a joined report follows its main report and Undo join needs a reason; a report changed meanwhile is read again", async () => {
    window.location.hash = "#/problems/pr:r-1";
    const step = vi.fn(() => Promise.reject(new ProblemsError(412)));
    const api = apiOf({ step });
    show(api, MANAGER);
    fireEvent.click(
      await screen.findByRole("button", { name: "Join to a report" }),
    );
    const dialog = screen.getByRole("dialog");
    const main = within(dialog).getByLabelText(/^Main report/);
    await waitFor(() => {
      expect(main.querySelectorAll("option")).toHaveLength(2);
    });
    expect(within(main).getByText(/UP260002/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Choose one.")).toBeTruthy();
    fireEvent.change(main, { target: { value: "r-2" } });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Same tap" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(step).toHaveBeenCalledWith("property-1", UP1, {
        step: "JOIN",
        main_id: "r-2",
        reason: "Same tap",
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(api.get).toHaveBeenCalledTimes(2);
    cleanup();

    window.location.hash = "#/problems/pr:b-2";
    const unjoin = vi.fn(() => Promise.resolve(BP2));
    show(apiOf({ step: unjoin }), MANAGER);
    expect(
      await screen.findByText(/This report follows BP260001/),
    ).toBeTruthy();
    expect(screen.getByText("Same lift")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Undo join" }));
    const undo = screen.getByRole("dialog");
    fireEvent.click(within(undo).getByRole("button", { name: "Save" }));
    expect(within(undo).getByText("Please write this.")).toBeTruthy();
    fireEvent.change(within(undo).getByLabelText(/^Reason/), {
      target: { value: "Different lift" },
    });
    fireEvent.click(within(undo).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(unjoin).toHaveBeenCalledWith("property-1", BP2, {
        step: "UNJOIN",
        note: "Different lift",
      });
    });
    cleanup();

    show(apiOf(), STAFF);
    expect(
      await screen.findByText(/Only a Manager or the Owner can join reports/),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Undo join" })).toBeNull();
  });

  it("TEST-FE-1291 Repair cost: from Repair planned on, staff type parts and outside workers in dollars or riel (or No cost); the box waits for a Manager; a person without Check repair costs gets no check button", async () => {
    window.location.hash = "#/problems/pr:r-1";
    const done = report({
      status: "DONE",
      state: "DONE",
      pays: "OWNER",
      done_at: "2026-11-04T02:30:00Z",
      version: 7,
    });
    const typed = report({
      ...done,
      version: 8,
      cost: {
        set_no: 1,
        no_cost: false,
        note: null,
        entered_at: "2026-11-04T02:40:00Z",
        entered_by_name: "Staff One",
        lines: [
          {
            kind: "PARTS",
            description: "New tap",
            currency: "USD",
            amount_minor: 1250,
          },
          {
            kind: "OUTSIDE_WORKER",
            description: "Plumber",
            currency: "KHR",
            amount_minor: 40000,
          },
        ],
        totals: [
          { currency: "USD", amount_minor: 1250 },
          { currency: "KHR", amount_minor: 40000 },
        ],
        check: null,
        expense_requests: [],
        can_enter: true,
      },
    });
    const cost = vi.fn(() => Promise.resolve(typed));
    show(apiOf({ get: vi.fn(() => Promise.resolve(done)), cost }), STAFF);
    fireEvent.click(
      await screen.findByRole("button", { name: "Type the cost" }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Choose one.")).toBeTruthy();
    expect(within(dialog).getByText("Type dollars, like 12.50.")).toBeTruthy();
    expect(cost).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Kind"), {
      target: { value: "PARTS" },
    });
    fireEvent.change(within(dialog).getByLabelText("What"), {
      target: { value: " New tap " },
    });
    fireEvent.change(within(dialog).getByLabelText("Amount"), {
      target: { value: "12.50" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add a line" }));
    const second = within(dialog).getByRole("group", { name: "Line 2" });
    fireEvent.change(within(second).getByLabelText("Kind"), {
      target: { value: "OUTSIDE_WORKER" },
    });
    fireEvent.change(within(second).getByLabelText("What"), {
      target: { value: "Plumber" },
    });
    fireEvent.change(within(second).getByLabelText("Currency"), {
      target: { value: "KHR" },
    });
    fireEvent.change(within(second).getByLabelText("Amount"), {
      target: { value: "40.5" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Type whole riel, like 40000."),
    ).toBeTruthy();
    fireEvent.change(within(second).getByLabelText("Amount"), {
      target: { value: "40,000" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(cost).toHaveBeenCalledWith("property-1", done, {
        no_cost: false,
        lines: [
          {
            kind: "PARTS",
            description: "New tap",
            currency: "USD",
            amount_minor: 1250,
          },
          {
            kind: "OUTSIDE_WORKER",
            description: "Plumber",
            currency: "KHR",
            amount_minor: 40000,
          },
        ],
      });
    });
    const box = element(
      (await screen.findByRole("heading", { name: "Repair cost" })).closest(
        "section",
      ),
    );
    // Each line, then the total of each currency.
    expect(within(box).getAllByText("$12.50")).toHaveLength(2);
    expect(within(box).getAllByText("40,000 ៛")).toHaveLength(2);
    expect(
      within(box).getByText("Waiting for a Manager to check the cost."),
    ).toBeTruthy();
    expect(
      within(box).queryByRole("button", {
        name: "Checked, make Expense report",
      }),
    ).toBeNull();
  });

  it("TEST-FE-1292 Repair cost check: a Manager with Check repair costs confirms the receipt, how it was paid and the day; the box then shows the Expense reports with links and their status", async () => {
    window.location.hash = "#/problems/pr:r-1";
    const waiting = report({
      status: "DONE",
      state: "DONE",
      pays: "TENANT",
      done_at: "2026-11-04T02:30:00Z",
      version: 8,
      cost: {
        set_no: 1,
        no_cost: false,
        note: null,
        entered_at: "2026-11-04T02:40:00Z",
        entered_by_name: "Staff One",
        lines: [
          {
            kind: "OUTSIDE_WORKER",
            description: "Plumber",
            currency: "KHR",
            amount_minor: 40000,
          },
        ],
        totals: [{ currency: "KHR", amount_minor: 40000 }],
        check: null,
        expense_requests: [],
        can_enter: true,
      },
    });
    const checked = report({
      ...waiting,
      version: 9,
      cost: {
        ...(waiting.cost ?? ({} as never)),
        check: {
          checked_at: "2026-11-04T03:00:00Z",
          checked_by_name: "Manager One",
          spent_on: "2026-11-04",
          paid_how: "OWN_MONEY",
        },
        expense_requests: [
          {
            request_number: "ER26000003",
            status: "WAITING",
            currency: "KHR",
            amount_cents: 980,
            original_amount_minor: 40000,
          },
        ],
        can_enter: false,
      },
    });
    const checkCost = vi.fn(() => Promise.resolve(checked));
    show(
      apiOf({ get: vi.fn(() => Promise.resolve(waiting)), checkCost }),
      new Set([...MANAGER, "problem_reports.costs"]),
    );
    expect(
      await screen.findByText(
        "For comparison only; it does not change the Damage Invoice draft.",
      ),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Checked, make Expense report" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(/Riel turns into dollars at today's riel rate/),
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Checked, make Expense report",
      }),
    );
    expect(within(dialog).getByText("Check the receipt first.")).toBeTruthy();
    expect(checkCost).not.toHaveBeenCalled();
    fireEvent.click(
      within(dialog).getByLabelText("Staff's own money (paid back later)"),
    );
    fireEvent.click(
      within(dialog).getByLabelText(
        "I have seen the receipt and it matches these lines.",
      ),
    );
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Checked, make Expense report",
      }),
    );
    await waitFor(() => {
      expect(checkCost).toHaveBeenCalledWith("property-1", waiting, {
        receipt_seen: true,
        spent_on: "2026-11-04",
        paid_how: "OWN_MONEY",
      });
    });
    expect(
      await screen.findByText(
        "UP260001: cost checked. Expense report ER26000003 made.",
      ),
    ).toBeTruthy();
    const link = screen.getByRole("link", { name: "ER26000003" });
    expect(link.getAttribute("href")).toContain("ER26000003");
    expect(screen.getByText(/Waiting for approval/)).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Type the cost again" }),
    ).toBeNull();
  });

  it("TEST-FE-1293 Monthly report: a person who may plan repairs opens it from the list; it shows one month's counts, who pays, repeats, late reports and the repair cost by Unit and by type with dollars and riel apart; another month is read again; Staff get no button", async () => {
    const DAY: ProblemMonth = {
      month: "2026-11-01",
      received: 5,
      joined: 1,
      unit_problems: 3,
      building_problems: 2,
      urgent: 2,
      urgent_on_time: 1,
      normal: 3,
      normal_on_time: 3,
      done: 2,
      average_days_to_fix: 1.5,
      still_open: 3,
      not_accepted: 0,
      opened_again: 1,
      owner_pays: 2,
      tenant_pays: 1,
      damage_usd_cents: 2500,
      by_type: [
        {
          code: "WATER",
          name_en: "Water",
          name_kh: null,
          icon: "drop",
          reports: 3,
        },
      ],
      by_place: [
        {
          kind: "UNIT",
          unit_number: "U101",
          place_code: null,
          place_en: null,
          place_kh: null,
          reports: 3,
        },
        {
          kind: "BUILDING",
          unit_number: null,
          place_code: "LOBBY",
          place_en: "Lobby",
          place_kh: null,
          reports: 2,
        },
      ],
      repeats: [
        {
          code: "WATER",
          name_en: "Water",
          name_kh: null,
          icon: "drop",
          unit_number: "U101",
          reports: 2,
          found: [
            { report_id: "r-1", report_number: "UP260001" },
            { report_id: "r-2", report_number: "UP260002" },
          ],
        },
      ],
      late_now: [
        { report_id: "r-3", report_number: "BP260003", late: "URGENT" },
      ],
      cost_by_unit: [
        {
          unit_number: "U101",
          reports: 1,
          parts_usd_cents: 1400,
          outside_usd_cents: 0,
          parts_khr: 0,
          outside_khr: 40000,
        },
        {
          unit_number: null,
          reports: 1,
          parts_usd_cents: 0,
          outside_usd_cents: 0,
          parts_khr: 0,
          outside_khr: 0,
        },
      ],
      cost_by_type: [],
    };
    const month = vi.fn(() => Promise.resolve(DAY));
    window.location.hash = "#/problems";
    show(apiOf(), STAFF);
    await screen.findByText("UP260001");
    expect(screen.queryByRole("link", { name: "Monthly report" })).toBeNull();
    cleanup();

    show(apiOf({ month }), MANAGER);
    await screen.findByText("UP260001");
    expect(
      screen.getByRole("link", { name: "Monthly report" }).getAttribute("href"),
    ).toBe("#/problems/month");
    cleanup();

    window.location.hash = "#/problems/month";
    show(apiOf({ month }), MANAGER);
    expect(await screen.findByText("Reports received")).toBeTruthy();
    expect(month).toHaveBeenCalledWith("property-1", "2026-11");
    expect(
      screen.getByText("3 Unit · 2 Building · 1 joined, not counted again"),
    ).toBeTruthy();
    expect(screen.getByText("1.5 days to fix on average")).toBeTruthy();
    expect(screen.getByText("1 opened again · 0 not accepted")).toBeTruthy();
    expect(screen.getByText("1 / 2")).toBeTruthy();
    expect(screen.getByText("Normal planned on time: 3 / 3")).toBeTruthy();
    expect(
      screen.getByText("Owner pays 2 · Tenant pays 1 · Damage charges $25.00"),
    ).toBeTruthy();
    const byUnit = screen.getByRole("region", { name: "Repair cost by Unit" });
    const u101 = within(byUnit).getByRole("row", { name: /U101/ });
    expect(within(u101).getByText("$14.00 + 40,000 ៛")).toBeTruthy();
    expect(within(u101).getByText("40,000 ៛")).toBeTruthy();
    expect(
      within(byUnit).getByRole("row", { name: /Building \(shared places\)/ }),
    ).toBeTruthy();
    expect(
      within(
        screen.getByRole("region", { name: "Repair cost by type" }),
      ).getByText("No repair done this month."),
    ).toBeTruthy();
    const repeats = screen.getByRole("region", {
      name: "Same problem again in one Unit",
    });
    expect(
      within(repeats)
        .getByRole("link", { name: "UP260002" })
        .getAttribute("href"),
    ).toBe("#/problems/pr%3Ar-2");
    expect(
      within(
        screen.getByRole("region", { name: "Reports by place" }),
      ).getByText(/Lobby/),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "Late now" })).getByText(
        /Late: the tenant is not contacted yet/,
      ),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Month"), {
      target: { value: "2026-10" },
    });
    await waitFor(() => {
      expect(month).toHaveBeenLastCalledWith("property-1", "2026-10");
    });
    expect(screen.getAllByRole("option")).toHaveLength(12);
  });

  it("TEST-FE-1295 Make a Problem report from a move-out inspection finding: the form says where it comes from, keeps the Unit, copies the text and saves with the source Inspection and the finding; a finding with a report links to it; the report page links back to the move-out", async () => {
    window.location.hash = "#/problems/finding:f-1";
    const add = vi.fn(() =>
      Promise.resolve(report({ report_id: "r-9", report_number: "UP260009" })),
    );
    const finding = vi.fn(() => Promise.resolve(FINDING));
    show(apiOf({ add, finding }), STAFF);
    expect(
      await screen.findByText(
        "From the move-out inspection of 03/11/2026, finding 2. The Unit and the text come from the finding; you may change the text.",
      ),
    ).toBeTruthy();
    expect(finding).toHaveBeenCalledWith("property-1", "f-1");
    const unit = element(
      document.getElementById("np-unit"),
    ) as HTMLSelectElement;
    expect(unit.value).toBe("u-101");
    expect(unit.disabled).toBe(true);
    expect(screen.queryByLabelText("Walk-in")).toBeNull();
    expect(
      screen.getByLabelText<HTMLTextAreaElement>(/^What is wrong/).value,
    ).toBe("Bedroom door handle broken");
    fireEvent.click(screen.getByLabelText(/Water/));
    const urgent = document.querySelectorAll<HTMLInputElement>(
      'input[name="np-urgent"]',
    );
    fireEvent.click(element(urgent[1] ?? null));
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    await waitFor(() => {
      expect(add).toHaveBeenCalledWith("property-1", {
        kind: "UNIT",
        source: "INSPECTION",
        problem_type_id: "t-water",
        description: "Bedroom door handle broken",
        urgent: false,
        unit_id: "u-101",
        may_enter: false,
        best_time: "ANY",
        finding_id: "f-1",
      });
    });
    cleanup();

    window.location.hash = "#/problems/finding:f-1";
    show(
      apiOf({
        finding: vi.fn(() =>
          Promise.resolve({
            ...FINDING,
            report: { report_id: "r-7", report_number: "UP260007" },
          }),
        ),
      }),
      STAFF,
    );
    expect(
      await screen.findByText("This finding already has a Problem report:"),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "UP260007" }).getAttribute("href"),
    ).toBe("#/problems/pr%3Ar-7");
    expect(screen.queryByRole("button", { name: "Save report" })).toBeNull();
    cleanup();

    window.location.hash = "#/problems/pr:r-1";
    show(
      apiOf({
        get: vi.fn(() =>
          Promise.resolve(
            report({
              source: "INSPECTION",
              finding: {
                finding_id: "f-1",
                inspection_id: "i-1",
                lease_id: "lease-1",
                inspection_date: "2026-11-03",
                ordinal: 2,
                description: "Bedroom door handle broken",
              },
            }),
          ),
        ),
      }),
      STAFF,
    );
    expect(
      await screen.findByText(
        /From the move-out inspection of 03\/11\/2026: Bedroom door handle broken/,
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open the move-out" })
        .getAttribute("href"),
    ).toBe("#/moveout/lease-1");
  });

  it("TEST-FE-2055 a problem from a short-stay room check links back to the stay", async () => {
    window.location.hash = "#/problems/pr:r-1";
    show(
      apiOf({
        get: vi.fn(() =>
          Promise.resolve(
            report({
              source: "ROOM_CHECK",
              stay: {
                booking_id: "b-1",
                booking_number: "ST260001",
                guest_name: "Lim Dara",
                check_in_on: "2026-11-04",
                check_out_on: "2026-11-07",
              },
            }),
          ),
        ),
      }),
      STAFF,
    );
    expect(
      await screen.findByText(
        /From the room check after short stay ST260001 \(Lim Dara, 04\/11\/2026 to 07\/11\/2026\)\./,
      ),
    ).toBeTruthy();
    expect(screen.getAllByText(/Short-stay room check/).length).toBeGreaterThan(
      0,
    );
    expect(
      screen.getByRole("link", { name: "Open the stay" }).getAttribute("href"),
    ).toBe("#/shortstays/st%3Ab-1");
  });
});
