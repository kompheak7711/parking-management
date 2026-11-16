import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ContactOfficePage,
  FaqPageView,
  LinkedTenantsPage,
  NoticesPageView,
  TelegramHealthPage,
  VisitRequestsPageView,
} from "./TelegramPages";
import {
  type ContactPage,
  type FaqPage,
  type HealthPage,
  type InvoicesPage,
  type LinksPage,
  type NoticesPage,
  type ReceiptsPage,
  type WarningsPage,
  type TelegramApi,
  TelegramError,
  type VisitRequest,
  type VisitRequestDetail,
  type VisitRequestsPage,
  contactPageOf,
  noticesPageOf,
  receiptsPageOf,
  warningsPageOf,
  faqPageOf,
  healthPageOf,
  linksPageOf,
  visitRequestDetailOf,
  visitRequestsPageOf,
} from "./telegramClient";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const LINKS: LinksPage = {
  linked: [
    {
      id: "link-1",
      telegram_user_id: 920001,
      phone: "+85512300400",
      name: "Sao Rina",
      unit_number: "601",
      lease_end_date: "2027-06-30",
      booking_number: null,
      stay_end_date: null,
      linked_at: "2026-11-03T02:40:00Z",
    },
  ],
  tries: [
    {
      telegram_user_id: 920002,
      phone: "+85599000111",
      typed_name: "Somebody",
      typed_unit: "601",
      tries: 2,
      tries_left: 3,
      blocked_until: null,
      last_at: "2026-11-04T01:00:00Z",
    },
    {
      telegram_user_id: 920005,
      phone: "+85599000222",
      typed_name: "Other",
      typed_unit: "102",
      tries: 5,
      tries_left: 0,
      blocked_until: "2026-11-05T01:00:00Z",
      last_at: "2026-11-04T01:00:00Z",
    },
  ],
  ended: [
    {
      id: "link-0",
      telegram_user_id: 920009,
      name: "Keo Vannak",
      unit_number: "101",
      linked_at: "2026-09-01T02:00:00Z",
      ended_at: "2026-10-31T17:00:00Z",
      reason: "LEASE_ENDED",
      note: null,
    },
  ],
  rules: { tries: 5, block_hours: 24, keep_days: 90 },
};

const HEALTH: HealthPage = {
  last_pull_at: "2026-11-04T03:00:00Z",
  last_pull_outcome: "OK",
  last_pull_error: null,
  outbox_waiting: 1,
  outbox_failing_12h: 0,
  relay_dropped: 0,
  bots: [
    {
      code: "CUSTOMER",
      name: "Customer bot",
      last_in: null,
      last_out: null,
      failing: false,
    },
    {
      code: "TENANT",
      name: "Tenant bot",
      last_in: "2026-11-04T02:59:00Z",
      last_out: "2026-11-04T02:58:00Z",
      failing: true,
    },
    {
      code: "STAFF",
      name: "Staff bot",
      last_in: null,
      last_out: null,
      failing: false,
    },
  ],
  outbox: [
    {
      id: "msg-wait",
      bot: "TENANT",
      text_code: "tenant.menu",
      created_at: "2026-11-04T02:00:00Z",
      tries: 1,
      last_error: "telegram_too_many",
      last_try_at: "2026-11-04T02:01:00Z",
      status: "WAITING",
      retried: false,
      to: { name: "Sao Rina", unit_number: "601" },
    },
    {
      id: "msg-old",
      bot: "TENANT",
      text_code: "tenant.report_received",
      created_at: "2026-10-27T02:00:00Z",
      tries: 3,
      last_error: "telegram_blocked_by_person",
      last_try_at: "2026-11-03T02:00:00Z",
      status: "GAVE_UP",
      retried: false,
      to: { name: "Keo Vannak", unit_number: "101" },
    },
  ],
  pulls: [
    {
      started_at: "2026-11-04T03:00:00Z",
      outcome: "OK",
      error_code: null,
      items_saved: 4,
    },
    {
      started_at: "2026-11-04T02:59:00Z",
      outcome: "FAILED",
      error_code: "relay_unreachable",
      items_saved: 0,
    },
  ],
};

const CONTACT: ContactPage = {
  waiting: [
    {
      id: "c-1",
      bot: "TENANT",
      name: "Lim Dara",
      unit_number: "801",
      phone: "+85512800100",
      message: "The light in my bathroom is weak.",
      received_at: "2026-11-05T01:00:00Z",
      answer: null,
    },
  ],
  answered: [
    {
      id: "c-0",
      bot: "CUSTOMER",
      name: "Sok",
      unit_number: null,
      phone: null,
      message: "Do you have a studio?",
      received_at: "2026-11-04T01:00:00Z",
      answer: {
        how: "PHONE",
        text: "Called; visit on Friday.",
        at: "2026-11-04T02:00:00Z",
        by: "Mony",
      },
    },
  ],
};

const FAQ: FaqPage = {
  owner: false,
  can_edit: true,
  questions: [
    {
      id: "q-1",
      number: 1,
      current: {
        version_id: "v-1",
        version_number: 1,
        approved_by: "Kompheak",
        approved_at: "2026-11-05T01:00:00Z",
        for_bots: "BOTH",
        question_en: "What are your office hours?",
        answer_en: "Monday to Saturday, 07:00 to 17:00.",
        question_km: "ការិយាល័យបើកម៉ោងប៉ុន្មាន?",
        answer_km: "ពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។",
      },
      pending: {
        version_id: "v-2",
        proposed_by: "Mony",
        proposed_at: "2026-11-05T02:00:00Z",
        for_bots: "TENANT",
        question_en: "What are your office hours?",
        answer_en: "Monday to Saturday, 07:00 to 17:00. Closed on Sunday.",
        question_km: "ការិយាល័យបើកម៉ោងប៉ុន្មាន?",
        answer_km: "ពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍។",
      },
    },
  ],
};

const SOKHA = {
  id: "vr-1",
  number: "VR260001",
  received_at: "2026-11-05T03:05:00Z",
  name: "Sokha Chan",
  phone: "+85512800200",
  contact_by: "EMAIL",
  email: "sokha@example.com",
  language: "en",
  unit_type: "TWO_BEDROOM",
  unit_type_en: "2 bedrooms",
  unit_type_km: "បន្ទប់គេង ២",
  visit_on: "2026-11-09",
  visit_part: "AFTERNOON",
  move_in_month: "2026-12",
  note: "A high floor, please.",
};

const WORK = {
  staff_id: null,
  staff: null,
  mine: false,
  waiting_minutes: 70,
  late: false,
  no_answer_days: 0,
  calls: 0,
  visit_local: null,
  visit_staff: null,
  reason: null,
  close_note: null,
  to_send: [],
  reservation_id: null,
  blocked: false,
  removed: false,
};

const PAGE_FACTS = {
  today: "2026-11-05",
  address: "Near Camko Roundabout",
  workers: [
    { id: "staff-1", name: "Dara" },
    { id: "boss-1", name: "Sophea" },
  ],
  me: "staff-1",
  can_work: true,
  can_manage: false,
  month: null,
};

const FIRST: VisitRequest = {
  ...SOKHA,
  ...WORK,
  status: "NEW",
  joined: [
    {
      ...SOKHA,
      id: "vr-2",
      number: "VR260002",
      contact_by: "WHATSAPP",
      email: null,
      unit_type: "STUDIO",
      unit_type_en: "Studio",
      unit_type_km: "ស្ទូឌីយោ",
      visit_on: null,
      visit_part: null,
      move_in_month: null,
      note: null,
    },
  ],
};

const VISITS: VisitRequestsPage = { ...PAGE_FACTS, requests: [FIRST] };

const INVOICES: InvoicesPage = {
  invoices: [
    {
      id: "inv-1",
      number: "INV-2026-0042",
      unit_number: "601",
      customer: "Sao Rina",
      status: "UNPAID",
      issued_at: "2026-11-24T02:00:00Z",
      due_date: "2026-12-05",
      to_pay_usd_cents: 35450,
      sent: [
        {
          telegram_user_id: 9001,
          queued_at: "2026-11-24T02:00:00Z",
          state: "SENT",
          sent_at: "2026-11-24T02:00:10Z",
        },
      ],
      reminded_at: "2026-12-02T01:00:00Z",
    },
    {
      id: "inv-2",
      number: "INV-2026-0043",
      unit_number: "602",
      customer: "Kim Dara",
      status: "UNPAID",
      issued_at: "2026-11-24T02:00:00Z",
      due_date: "2026-12-05",
      to_pay_usd_cents: 40000,
      sent: [],
      reminded_at: null,
    },
  ],
  rules: { remind_days: 3, days: 45 },
};

const RECEIPTS: ReceiptsPage = {
  receipts: [
    {
      id: "rec-1",
      number: "R2611-0007",
      customer: "Sao Rina",
      status: "RECEIVED",
      issued_at: "2026-11-11T03:00:00Z",
      amount_usd_cents: 90000,
      sent: [
        {
          telegram_user_id: 9001,
          queued_at: "2026-11-11T03:01:00Z",
          state: "SENT",
          sent_at: "2026-11-11T03:01:05Z",
        },
      ],
    },
    {
      id: "rec-2",
      number: "R2611-0008",
      customer: "Kim Dara",
      status: "RECEIVED",
      issued_at: "2026-11-11T03:10:00Z",
      amount_usd_cents: 5000,
      sent: [],
    },
    {
      id: "rec-3",
      number: "R2611-0009",
      customer: "Lim Bora",
      status: "REVERSED",
      issued_at: "2026-11-11T03:20:00Z",
      amount_usd_cents: 7000,
      sent: [],
    },
  ],
  rules: { days: 45 },
};

const NOTICES: NoticesPage = {
  notices: [
    {
      id: "nt-1",
      text_en: "No water 9-11 tomorrow.",
      text_km: "គ្មានទឹកថ្ងៃស្អែក។",
      audience: "FLOORS",
      floors: ["3"],
      units: [],
      sent_by: "Dara Manager",
      created_at: "2026-11-11T03:00:00Z",
      people: 4,
      sent: 3,
      failed: 1,
    },
  ],
  floors: ["3", "5"],
  units: [
    { id: "u-301", unit_number: "U301", floor: "3" },
    { id: "u-501", unit_number: "U501", floor: "5" },
  ],
  rules: { days: 90, max: 1500 },
};

const WARNINGS: WarningsPage = {
  warnings: [
    {
      id: "warn-1",
      kind: "RENT_20",
      unit_number: "U512",
      customer: "Heng Dara",
      recorded_at: "2026-11-11T05:00:00Z",
      sent: [
        {
          telegram_user_id: 9001,
          queued_at: "2026-11-11T05:01:00Z",
          state: "SENT",
          sent_at: "2026-11-11T05:01:05Z",
        },
      ],
    },
    {
      id: "warn-2",
      kind: "LEASE_WARNING",
      unit_number: "U301",
      customer: "Sok Vanna",
      recorded_at: "2026-11-10T09:00:00Z",
      sent: [],
    },
  ],
  rules: { days: 90 },
};

function fakeApi(extra: Partial<TelegramApi> = {}): TelegramApi {
  return {
    contact: vi.fn(() => Promise.resolve(CONTACT)),
    answer: vi.fn(() =>
      Promise.resolve({
        waiting: [],
        answered: [...CONTACT.waiting, ...CONTACT.answered],
      }),
    ),
    faq: vi.fn(() => Promise.resolve(FAQ)),
    saveFaq: vi.fn(() =>
      Promise.resolve({ number: 2, approved: false, page: FAQ }),
    ),
    loadFaqStarter: vi.fn(() => Promise.resolve(FAQ)),
    approveFaq: vi.fn(() =>
      Promise.resolve({
        ...FAQ,
        owner: true,
        questions: FAQ.questions.map((question) => ({
          ...question,
          pending: null,
        })),
      }),
    ),
    visitRequests: vi.fn(() => Promise.resolve(VISITS)),
    visitRequest: vi.fn(() => Promise.resolve({ ...FIRST, history: [] })),
    visitStep: vi.fn(() =>
      Promise.resolve({
        request: { ...FIRST, history: [] },
        page: VISITS,
      }),
    ),
    links: vi.fn(() => Promise.resolve(LINKS)),
    removeLink: vi.fn(() => Promise.resolve({ ...LINKS, linked: [] })),
    health: vi.fn(() => Promise.resolve(HEALTH)),
    invoices: vi.fn(() => Promise.resolve(INVOICES)),
    receipts: vi.fn(() => Promise.resolve(RECEIPTS)),
    warnings: vi.fn(() => Promise.resolve(WARNINGS)),
    notices: vi.fn(() => Promise.resolve(NOTICES)),
    sendNotice: vi.fn(() => Promise.resolve({ queued: 2, page: NOTICES })),
    retry: vi.fn(() =>
      Promise.resolve({
        ...HEALTH,
        outbox: HEALTH.outbox.map((message) =>
          message.id === "msg-old" ? { ...message, retried: true } : message,
        ),
      }),
    ),
    ...extra,
  };
}

const MANAGER = new Set(["telegram.read", "telegram.operate"]);
const READER = new Set(["telegram.read"]);

/** UI v81: Spam and Block both ask "Reason"; pick the field by its id. */
function fieldById(fields: HTMLElement[], id: string): HTMLElement {
  const field = fields.find((entry) => entry.id === id);
  if (field === undefined) throw new Error(`no field ${id}`);
  return field;
}

describe("Office › Telegram", () => {
  it("TEST-FE-1500 Linked tenants lists the links in force, the link tries that did not match with tries left or blocked until, and the ended links with why", async () => {
    const api = fakeApi();
    render(
      <LinkedTenantsPage
        active
        api={api}
        capabilities={MANAGER}
        language="en"
        propertyId="prop-1"
      />,
    );
    const linked = await screen.findByRole("region", { name: "Linked now" });
    const row = within(linked).getByRole("row", { name: /Sao Rina/ });
    expect(row.textContent).toContain("+85512300400");
    expect(row.textContent).toContain("601");
    expect(row.textContent).toContain("30/06/2027");
    expect(
      screen.getByText("Failed link attempts: 2 Telegram accounts."),
    ).toBeTruthy();
    const tries = screen.getByRole("region", {
      name: "Failed link attempts",
    });
    expect(within(tries).getByText("3 attempts left")).toBeTruthy();
    expect(within(tries).getByText(/^Blocked until 05\/11\/2026/)).toBeTruthy();
    expect(tries.textContent).toContain(
      "5 failed attempts, linking is blocked for 24 hours",
    );
    const ended = screen.getByRole("region", { name: "Ended links" });
    expect(within(ended).getByText("The Lease ended")).toBeTruthy();
    expect(within(ended).getByText("The last 90 days.")).toBeTruthy();
    expect(api.links).toHaveBeenCalledWith("prop-1");
  });

  it("TEST-FE-2232 Invoices on Telegram shows the 5 newest of a long list and a Show all button (Administration review fix 7)", async () => {
    const api = fakeApi();
    const unsent = INVOICES.invoices[1];
    if (unsent === undefined) throw new Error("the fixture has two Invoices");
    const many = Array.from({ length: 8 }, (_, index) => ({
      ...unsent,
      id: `inv-${String(index)}`,
      number: `INV-2026-01${String(index).padStart(2, "0")}`,
    }));
    api.invoices = vi.fn(() =>
      Promise.resolve({ ...INVOICES, invoices: many }),
    );
    render(
      <LinkedTenantsPage
        active
        api={api}
        capabilities={READER}
        language="en"
        propertyId="prop-1"
      />,
    );
    const invoices = await screen.findByRole("region", {
      name: "Invoices on Telegram",
    });
    await within(invoices).findByRole("row", { name: /INV-2026-0100/ });
    // The heading row and the 5 newest.
    expect(within(invoices).getAllByRole("row")).toHaveLength(6);
    expect(
      within(invoices).getByText("The 5 newest of 8."),
    ).toBeInTheDocument();
    // The count of Invoices that need a paper copy still counts every one.
    expect(
      within(invoices).getByText(/did not reach anyone on Telegram: 8\./),
    ).toBeInTheDocument();
    fireEvent.click(
      within(invoices).getByRole("button", { name: "Show all 8" }),
    );
    expect(within(invoices).getAllByRole("row")).toHaveLength(9);
    fireEvent.click(
      within(invoices).getByRole("button", { name: "Show fewer" }),
    );
    expect(within(invoices).getAllByRole("row")).toHaveLength(6);
  });

  it("TEST-FE-1950 Invoices on Telegram shows who got each issued Invoice and its reminder, and which tenants need a paper copy", async () => {
    const api = fakeApi();
    render(
      <LinkedTenantsPage
        active
        api={api}
        capabilities={READER}
        language="en"
        propertyId="prop-1"
      />,
    );
    const invoices = await screen.findByRole("region", {
      name: "Invoices on Telegram",
    });
    const sent = await within(invoices).findByRole("row", {
      name: /INV-2026-0042/,
    });
    expect(sent.textContent).toContain("Sent to 1");
    expect(sent.textContent).toContain("05/12/2026");
    expect(sent.textContent).toContain("$354.50");
    const paper = within(invoices).getByRole("row", { name: /INV-2026-0043/ });
    expect(paper.textContent).toContain("Give a paper copy");
    expect(paper.textContent).toContain("Not yet");
    expect(
      within(invoices).getByText(
        "Invoices that did not reach anyone on Telegram: 1. Give these tenants a paper copy.",
      ),
    ).toBeTruthy();
    expect(invoices.textContent).toContain(
      "A reminder goes 3 days before the due date",
    );
    expect(api.invoices).toHaveBeenCalledWith("prop-1");
  });

  it("TEST-FE-1954 Receipts on Telegram shows who got each Receipt, a Receipt that reached nobody, and a reversed one", async () => {
    const api = fakeApi();
    render(
      <LinkedTenantsPage
        active
        api={api}
        capabilities={READER}
        language="en"
        propertyId="prop-1"
      />,
    );
    const receipts = await screen.findByRole("region", {
      name: "Receipts on Telegram",
    });
    const sent = await within(receipts).findByRole("row", {
      name: /R2611-0007/,
    });
    expect(sent.textContent).toContain("Sent to 1");
    expect(sent.textContent).toContain("$900.00");
    const paper = within(receipts).getByRole("row", { name: /R2611-0008/ });
    expect(paper.textContent).toContain("Give a paper copy");
    const reversed = within(receipts).getByRole("row", { name: /R2611-0009/ });
    expect(reversed.textContent).toContain("Reversed");
    expect(
      within(receipts).getByText(
        "Receipts that did not reach anyone on Telegram: 1. Give these people a paper copy if they need one.",
      ),
    ).toBeTruthy();
    expect(receipts.textContent).toContain("Receipts of the last 45 days.");
    expect(api.receipts).toHaveBeenCalledWith("prop-1");
    expect(receiptsPageOf(JSON.parse(JSON.stringify(RECEIPTS)))).toEqual(
      RECEIPTS,
    );
    expect(() => receiptsPageOf({ receipts: [], rules: {} })).toThrow(
      TelegramError,
    );
  });

  it("TEST-FE-1955 Notices: a Manager writes a notice, chooses floors, confirms and sends it; the list shows who got each one", async () => {
    const api = fakeApi();
    render(
      <NoticesPageView
        active
        api={api}
        capabilities={MANAGER}
        language="en"
        propertyId="prop-1"
      />,
    );
    const list = await screen.findByRole("region", { name: "Sent notices" });
    const row = within(list).getByRole("row", { name: /No water 9-11/ });
    expect(row.textContent).toContain("Floor 3");
    expect(row.textContent).toContain("3 of 4");
    expect(row.textContent).toContain("1 not delivered");
    expect(row.textContent).toContain("Dara Manager");
    const send = screen.getByRole("button", { name: "Send notice" });
    fireEvent.click(send);
    expect(
      screen.getByText("Write the notice in English or Khmer."),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("In English"), {
      target: { value: "  Lift work on Monday. " },
    });
    fireEvent.click(screen.getByRole("radio", { name: "Some floors" }));
    fireEvent.click(screen.getByRole("button", { name: "Send notice" }));
    expect(screen.getByText("Choose at least one floor or Unit.")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "Floor 5" }));
    fireEvent.click(screen.getByRole("button", { name: "Send notice" }));
    expect(api.sendNotice).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, send it" }));
    expect(
      await screen.findByText("The notice is on its way to 2 people."),
    ).toBeTruthy();
    expect(api.sendNotice).toHaveBeenCalledWith("prop-1", {
      text_en: "Lift work on Monday.",
      text_km: "",
      audience: "FLOORS",
      floors: ["5"],
      unit_ids: [],
    });
    expect(screen.getByLabelText("In English")).toHaveValue("");
  });

  it("TEST-FE-1956 Notices: a reader sees the list but no form; a refused notice says so and keeps the words; a wrong page answer is refused", async () => {
    render(
      <NoticesPageView
        active
        api={fakeApi()}
        capabilities={READER}
        language="km"
        propertyId="prop-1"
      />,
    );
    expect(await screen.findByText(/គ្មានទឹកថ្ងៃស្អែក/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /ផ្ញើ/ })).toBeNull();
    cleanup();

    const refused = fakeApi({
      sendNotice: vi.fn(() => Promise.reject(new TelegramError(422))),
    });
    render(
      <NoticesPageView
        active
        api={refused}
        capabilities={MANAGER}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.change(await screen.findByLabelText("In Khmer"), {
      target: { value: "សួស្តី" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send notice" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, send it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The notice was not sent. Check the words and who it is for.",
    );
    expect(screen.getByLabelText("In Khmer")).toHaveValue("សួស្តី");

    expect(noticesPageOf(JSON.parse(JSON.stringify(NOTICES)))).toEqual(NOTICES);
    expect(() => noticesPageOf({ ...NOTICES, rules: {} })).toThrow(
      TelegramError,
    );
  });

  it("TEST-FE-1957 Warnings on Telegram shows who got each late Rent letter and Lease warning, and which tenants need the letter by hand", async () => {
    const api = fakeApi();
    render(
      <LinkedTenantsPage
        active
        api={api}
        capabilities={READER}
        language="en"
        propertyId="prop-1"
      />,
    );
    const warnings = await screen.findByRole("region", {
      name: "Warnings on Telegram",
    });
    const rent = await within(warnings).findByRole("row", { name: /U512/ });
    expect(rent.textContent).toContain("Rent not paid: notice 2 (day 20)");
    expect(rent.textContent).toContain("Sent to 1");
    const lease = within(warnings).getByRole("row", { name: /U301/ });
    expect(lease.textContent).toContain("Lease warning");
    expect(lease.textContent).toContain("Give the letter");
    expect(
      within(warnings).getByText(
        "Warnings that did not reach anyone on Telegram: 1. Make sure these tenants got the paper letter.",
      ),
    ).toBeTruthy();
    expect(warnings.textContent).toContain("Warnings of the last 90 days.");
    expect(api.warnings).toHaveBeenCalledWith("prop-1");
    expect(warningsPageOf(JSON.parse(JSON.stringify(WARNINGS)))).toEqual(
      WARNINGS,
    );
    expect(() => warningsPageOf({ warnings: [], rules: {} })).toThrow(
      TelegramError,
    );
  });

  it("TEST-FE-1501 Remove link needs a reason, sends it and shows the list the server answers; an ended link reads the list again; a person without telegram.operate gets no button", async () => {
    const api = fakeApi();
    render(
      <LinkedTenantsPage
        active
        api={api}
        capabilities={MANAGER}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Remove link" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain(
      "Remove the Telegram link of Sao Rina (601, +85512300400)?",
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Remove link" }),
    );
    expect(within(dialog).getByText("Type a reason.")).toBeTruthy();
    expect(api.removeLink).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/Reason/), {
      target: { value: "  Lost phone " },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Remove link" }),
    );
    await screen.findByText("Link of Sao Rina removed.");
    expect(api.removeLink).toHaveBeenCalledWith(
      "prop-1",
      "link-1",
      "Lost phone",
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("No tenant is linked yet.")).toBeTruthy();
    cleanup();

    const late = fakeApi({
      removeLink: vi.fn(() => Promise.reject(new TelegramError(409))),
    });
    render(
      <LinkedTenantsPage
        active
        api={late}
        capabilities={MANAGER}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Remove link" }));
    fireEvent.change(screen.getByLabelText(/Reason/), {
      target: { value: "Wrong person" },
    });
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Remove link",
      }),
    );
    await screen.findByText(
      "This link has already ended. The list has been refreshed.",
    );
    await waitFor(() => {
      expect(late.links).toHaveBeenCalledTimes(2);
    });
    cleanup();

    render(
      <LinkedTenantsPage
        active
        api={fakeApi()}
        capabilities={READER}
        language="en"
        propertyId="prop-1"
      />,
    );
    await screen.findByRole("region", { name: "Linked now" });
    expect(screen.queryByRole("button", { name: "Remove link" })).toBeNull();
  });

  it("TEST-FE-1502 Telegram health shows the last relay pull, the waiting count, each bot's state and last message in and out, the messages not sent with their last error, and the last pulls; no bot key is shown", async () => {
    render(
      <TelegramHealthPage
        active
        api={fakeApi()}
        capabilities={MANAGER}
        language="en"
        propertyId="prop-1"
      />,
    );
    const bots = await screen.findByRole("region", { name: "Bots" });
    const tenant = within(bots).getByRole("row", { name: /Tenant bot/ });
    expect(within(tenant).getByText("Problem")).toBeTruthy();
    expect(within(bots).getAllByText("Working")).toHaveLength(2);
    expect(within(bots).getAllByText("Never").length).toBeGreaterThan(0);
    expect(screen.getByText("4 received")).toBeTruthy();
    const cards = screen.getAllByRole("listitem");
    expect(cards.map((card) => card.textContent)).toEqual([
      expect.stringContaining("Last message check") as string,
      "Waiting to send1The app retries automatically",
      "Failed to send0Failing for 12 hours or more",
      "Not received within 7 days0These messages are deleted and lost. This should be 0.",
    ]);
    const outbox = screen.getByRole("region", {
      name: "Messages not sent yet",
    });
    const waiting = within(outbox).getByRole("row", { name: /Sao Rina, 601/ });
    expect(waiting.textContent).toContain(
      "Telegram asked the app to slow down",
    );
    expect(waiting.textContent).toContain("Retrying");
    const old = within(outbox).getByRole("row", { name: /Keo Vannak, 101/ });
    expect(old.textContent).toContain("The person blocked the bot");
    expect(old.textContent).toContain("Stopped after 7 days");
    const pulls = screen.getByRole("region", { name: "Recent message checks" });
    expect(
      within(pulls).getByText(
        "The message server did not respond. The app tried again a minute later.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(/Bot access keys are never shown here/),
    ).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/\d{6,}:[A-Za-z0-9_-]{20,}/);
  });

  it("TEST-FE-1503 Retry shows only on a message the app gave up on, to a person with telegram.operate; it sends once and shows Sent again; a second Retry the server refuses reads the page again", async () => {
    const api = fakeApi();
    render(
      <TelegramHealthPage
        active
        api={api}
        capabilities={MANAGER}
        language="en"
        propertyId="prop-1"
      />,
    );
    const outbox = await screen.findByRole("region", {
      name: "Messages not sent yet",
    });
    expect(
      within(outbox).getAllByRole("button", { name: "Retry" }),
    ).toHaveLength(1);
    fireEvent.click(within(outbox).getByRole("button", { name: "Retry" }));
    await screen.findByText(
      "Keo Vannak, 101: the message waits to be sent again. It goes out within a minute.",
    );
    expect(api.retry).toHaveBeenCalledWith("prop-1", "msg-old");
    expect(within(outbox).getByText("Sent again")).toBeTruthy();
    expect(within(outbox).queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();

    const refused = fakeApi({
      retry: vi.fn(() => Promise.reject(new TelegramError(409))),
    });
    render(
      <TelegramHealthPage
        active
        api={refused}
        capabilities={MANAGER}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await screen.findByText(/This message was already resent /);
    await waitFor(() => {
      expect(refused.health).toHaveBeenCalledTimes(2);
    });
    cleanup();

    render(
      <TelegramHealthPage
        active
        api={fakeApi()}
        capabilities={READER}
        language="en"
        propertyId="prop-1"
      />,
    );
    await screen.findByRole("region", { name: "Messages not sent yet" });
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("TEST-FE-1504 the client reads the pages, sends Remove link and Retry with the browser token, and refuses an answer of the wrong shape", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=tg-token",
      writable: true,
    });
    const calls: [string, RequestInit | undefined][] = [];
    const answer = (data: unknown) =>
      Promise.resolve(
        new Response(JSON.stringify({ data, meta: {} }), { status: 200 }),
      );
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        calls.push([path, init]);
        if (path.endsWith("/retry"))
          return answer({ message_id: "new", health: HEALTH });
        if (path.endsWith("/health")) return answer(HEALTH);
        return answer(LINKS);
      }),
    );
    const { telegramApi } = await import("./telegramClient");
    expect(await telegramApi.links("p 1")).toEqual(LINKS);
    expect(await telegramApi.removeLink("p 1", "link-1", "Lost")).toEqual(
      LINKS,
    );
    expect(await telegramApi.health("p 1")).toEqual(HEALTH);
    expect(await telegramApi.retry("p 1", "msg-old")).toEqual(HEALTH);
    expect(calls.map(([path]) => path)).toEqual([
      "/api/v1/properties/p%201/telegram/links",
      "/api/v1/properties/p%201/telegram/links/link-1/remove",
      "/api/v1/properties/p%201/telegram/health",
      "/api/v1/properties/p%201/telegram/outbox/msg-old/retry",
    ]);
    const remove = calls[1]?.[1];
    expect(remove?.method).toBe("POST");
    expect(remove?.body).toBe(JSON.stringify({ reason: "Lost" }));
    expect((remove?.headers as Record<string, string>)["X-CSRF-Token"]).toBe(
      "tg-token",
    );
    expect(() => linksPageOf({ linked: "no" })).toThrow(TelegramError);
    expect(() => healthPageOf({ bots: [] })).toThrow(TelegramError);
    expect(linksPageOf(LINKS)).toEqual(LINKS);
  });

  it("TEST-FE-1505 the pages show in Khmer and say to choose a Property first when none is chosen", async () => {
    render(
      <LinkedTenantsPage
        active
        api={fakeApi()}
        capabilities={MANAGER}
        language="km"
        propertyId="prop-1"
      />,
    );
    expect(
      await screen.findByRole("region", { name: "កំពុងភ្ជាប់" }),
    ).toBeTruthy();
    cleanup();
    const api = fakeApi();
    render(
      <TelegramHealthPage
        active
        api={api}
        capabilities={MANAGER}
        language="en"
        propertyId=""
      />,
    );
    expect(screen.getByText("Choose a Property first.")).toBeTruthy();
    expect(api.health).not.toHaveBeenCalled();
  });

  it("TEST-FE-1506 Contact office lists the waiting messages oldest first with who, Unit and phone, and the answered ones with who answered and how; Reply needs words and sends them; a message someone already answered reads the list again", async () => {
    const api = fakeApi();
    render(
      <ContactOfficePage
        active
        api={api}
        capabilities={new Set(["telegram.contact"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    expect(
      await screen.findByText("The light in my bathroom is weak."),
    ).toBeTruthy();
    expect(screen.getByText("Lim Dara")).toBeTruthy();
    expect(screen.getByText("+85512800100")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Answered \d/ }));
    expect(screen.getByText(/Phoned by Mony/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reply" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Waiting \d/ }));
    fireEvent.click(screen.getByRole("button", { name: "Reply" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Sent by the Tenant bot.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(
      within(dialog).getByText("Type a message or note first."),
    ).toBeTruthy();
    expect(api.answer).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/Your reply/), {
      target: { value: "  We will call you at 10:00. " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await screen.findByText("Reply sent to Lim Dara.");
    expect(api.answer).toHaveBeenCalledWith(
      "prop-1",
      "c-1",
      "TELEGRAM",
      "We will call you at 10:00.",
    );
    expect(screen.getByText("No message is waiting.")).toBeTruthy();
    cleanup();

    const late = fakeApi({
      answer: vi.fn(() => Promise.reject(new TelegramError(409))),
    });
    render(
      <ContactOfficePage
        active
        api={late}
        capabilities={new Set(["telegram.contact"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Answered by phone" }),
    );
    const phoned = screen.getByRole("dialog");
    expect(phoned.textContent).toContain("Nothing is sent.");
    fireEvent.change(
      within(phoned).getByLabelText(/What you said on the phone/),
      { target: { value: "Called." } },
    );
    fireEvent.click(within(phoned).getByRole("button", { name: "Save" }));
    await screen.findByText(
      "This message has already been answered. The list has been refreshed.",
    );
    await waitFor(() => {
      expect(late.contact).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-1507 FAQ shows each question in both languages, who sees it, the approved version and the version waiting for the Owner; a Manager's save is sent to the Owner and needs all four texts", async () => {
    const api = fakeApi();
    render(
      <FaqPageView
        active
        api={api}
        capabilities={new Set(["telegram.faq", "telegram.contact"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    expect(await screen.findByText("ការិយាល័យបើកម៉ោងប៉ុន្មាន?")).toBeTruthy();
    expect(screen.getByText("Customers and tenants")).toBeTruthy();
    expect(screen.getByText("Version 1")).toBeTruthy();
    expect(
      screen.getByText("New version from Mony waits for the Owner"),
    ).toBeTruthy();
    // Only the Owner approves.
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "See the new version" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByDisplayValue(
        "Monday to Saturday, 07:00 to 17:00. Closed on Sunday.",
      ).id,
    ).toBe("tg-faq-answer_en");
    expect(dialog.textContent).toContain(
      "The bots keep the old version until the Owner approves this one.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "New question" }));
    const fresh = screen.getByRole("dialog");
    fireEvent.change(within(fresh).getByLabelText(/Question in English/), {
      target: { value: " How do I pay? " },
    });
    fireEvent.click(
      within(fresh).getByRole("button", { name: "Send for approval" }),
    );
    expect(
      within(fresh).getAllByText("Type a message or note first."),
    ).toHaveLength(3);
    expect(api.saveFaq).not.toHaveBeenCalled();
    fireEvent.change(within(fresh).getByLabelText(/Who sees it/), {
      target: { value: "TENANT" },
    });
    fireEvent.change(within(fresh).getByLabelText(/Answer in English/), {
      target: { value: "Cash, ABA or KHQR." },
    });
    fireEvent.change(within(fresh).getByLabelText(/Question in Khmer/), {
      target: { value: "តើបង់ដោយរបៀបណា?" },
    });
    fireEvent.change(within(fresh).getByLabelText(/Answer in Khmer/), {
      target: { value: "សាច់ប្រាក់ ABA ឬ KHQR។" },
    });
    fireEvent.click(
      within(fresh).getByRole("button", { name: "Send for approval" }),
    );
    await screen.findByText("Question 2: sent to the Owner to approve.");
    expect(api.saveFaq).toHaveBeenCalledWith("prop-1", null, {
      for_bots: "TENANT",
      question_en: "How do I pay?",
      answer_en: "Cash, ABA or KHQR.",
      question_km: "តើបង់ដោយរបៀបណា?",
      answer_km: "សាច់ប្រាក់ ABA ឬ KHQR។",
    });
  });

  it("TEST-FE-1520 an empty FAQ offers the Owner and the Manager the 15 starter questions, which load waiting for the Owner; Staff do not see the button", async () => {
    const api = fakeApi({
      faq: vi.fn(() => Promise.resolve({ ...FAQ, questions: [] })),
    });
    render(
      <FaqPageView
        active
        api={api}
        capabilities={new Set(["telegram.faq"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Load the 15 starter questions",
      }),
    );
    await screen.findByText(
      "15 questions loaded. Each waits for the Owner to approve it.",
    );
    expect(api.loadFaqStarter).toHaveBeenCalledWith("prop-1");
    expect(
      screen.queryByRole("button", { name: "Load the 15 starter questions" }),
    ).toBeNull();
    cleanup();

    const staff = fakeApi({
      faq: vi.fn(() =>
        Promise.resolve({ ...FAQ, questions: [], can_edit: false }),
      ),
    });
    render(
      <FaqPageView
        active
        api={staff}
        capabilities={new Set(["telegram.contact"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    await screen.findByText(/No questions yet/);
    expect(
      screen.queryByRole("button", { name: "Load the 15 starter questions" }),
    ).toBeNull();
  });

  it("TEST-FE-1508 the Owner approves the version waiting and saves at once; Staff with only telegram.contact read the FAQ and change nothing", async () => {
    const api = fakeApi({
      faq: vi.fn(() => Promise.resolve({ ...FAQ, owner: true })),
    });
    render(
      <FaqPageView
        active
        api={api}
        capabilities={new Set(["telegram.faq"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await screen.findByText("Question 1: the bots use the new version.");
    expect(api.approveFaq).toHaveBeenCalledWith("prop-1", "v-2");
    expect(screen.queryByText(/waits for the Owner/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Save and use",
      }),
    ).toBeTruthy();
    cleanup();

    const staff = fakeApi({
      faq: vi.fn(() => Promise.resolve({ ...FAQ, can_edit: false })),
    });
    render(
      <FaqPageView
        active
        api={staff}
        capabilities={new Set(["telegram.contact"])}
        language="km"
        propertyId="prop-1"
      />,
    );
    expect(
      await screen.findByText(
        /មានតែម្ចាស់ និងអ្នកគ្រប់គ្រងទេដែលកែសំណួរញឹកញាប់។/,
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "សំណួរថ្មី" })).toBeNull();
    expect(screen.queryByRole("button", { name: "កែ" })).toBeNull();
  });

  it("TEST-FE-1509 the client reads Contact office and the FAQ, sends an answer, a FAQ version and an approval with the browser token, and refuses an answer of the wrong shape", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=tg-token",
      writable: true,
    });
    const calls: [string, RequestInit | undefined][] = [];
    const answer = (data: unknown) =>
      Promise.resolve(
        new Response(JSON.stringify({ data, meta: {} }), { status: 200 }),
      );
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        calls.push([path, init]);
        if (path.endsWith("/approve"))
          return answer({ approved: { number: 1 }, faq: FAQ });
        if (path.endsWith("/faq") && init?.method === "POST")
          return answer({ saved: { number: 2, approved: true }, faq: FAQ });
        if (path.endsWith("/faq")) return answer(FAQ);
        return answer(CONTACT);
      }),
    );
    const { telegramApi } = await import("./telegramClient");
    expect(await telegramApi.contact("p1")).toEqual(CONTACT);
    expect(await telegramApi.answer("p1", "c-1", "PHONE", "Called.")).toEqual(
      CONTACT,
    );
    expect(await telegramApi.faq("p1")).toEqual(FAQ);
    const words = {
      for_bots: "BOTH" as const,
      question_en: "Q",
      answer_en: "A",
      question_km: "ស",
      answer_km: "ច",
    };
    expect(await telegramApi.saveFaq("p1", "q-1", words)).toEqual({
      number: 2,
      approved: true,
      page: FAQ,
    });
    expect(await telegramApi.approveFaq("p1", "v-2")).toEqual(FAQ);
    expect(calls.map(([path]) => path)).toEqual([
      "/api/v1/properties/p1/telegram/contact",
      "/api/v1/properties/p1/telegram/contact/c-1/answer",
      "/api/v1/properties/p1/telegram/faq",
      "/api/v1/properties/p1/telegram/faq",
      "/api/v1/properties/p1/telegram/faq/versions/v-2/approve",
    ]);
    expect(calls[1]?.[1]?.body).toBe(
      JSON.stringify({ how: "PHONE", answer: "Called." }),
    );
    expect(calls[3]?.[1]?.body).toBe(
      JSON.stringify({ question_id: "q-1", ...words }),
    );
    expect(
      (calls[4]?.[1]?.headers as Record<string, string>)["X-CSRF-Token"],
    ).toBe("tg-token");
    expect(() => contactPageOf({ waiting: [] })).toThrow(TelegramError);
    expect(() =>
      faqPageOf({
        questions: [{ ...FAQ.questions[0], current: { for_bots: "ALL" } }],
      }),
    ).toThrow(TelegramError);
  });

  it("TEST-FE-1510 Visit requests lists the Customer bot's requests oldest first with the customer, phone, how to contact, what they want, the day they prefer and the note; a later ask of the same person shows under it as Joined", async () => {
    const api = fakeApi();
    render(
      <VisitRequestsPageView
        active
        api={api}
        capabilities={new Set(["visit_requests.read"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    expect(await screen.findByText("VR260001")).toBeTruthy();
    expect(screen.getByText("1 request")).toBeTruthy();
    expect(screen.getAllByText("Sokha Chan")).toHaveLength(2);
    expect(screen.getByText("sokha@example.com")).toBeTruthy();
    expect(screen.getByText("2 bedrooms")).toBeTruthy();
    expect(screen.getByText("move in 12/2026")).toBeTruthy();
    expect(screen.getByText("09/11/2026, Afternoon")).toBeTruthy();
    expect(screen.getByText("A high floor, please.")).toBeTruthy();
    expect(screen.getByText("New")).toBeTruthy();
    // The second ask joins the first and keeps its place.
    expect(screen.getByText("merged with VR260001")).toBeTruthy();
    expect(screen.getByText("Merged")).toBeTruthy();
    expect(screen.getByText("WhatsApp")).toBeTruthy();
    expect(screen.getByText("move in Later")).toBeTruthy();
    expect(screen.getByText("No day yet")).toBeTruthy();
    expect(api.visitRequests).toHaveBeenCalledWith("prop-1");
    cleanup();

    const empty = fakeApi({
      visitRequests: vi.fn(() =>
        Promise.resolve({ ...PAGE_FACTS, requests: [] }),
      ),
    });
    render(
      <VisitRequestsPageView
        active
        api={empty}
        capabilities={new Set(["visit_requests.read"])}
        language="km"
        propertyId="prop-1"
      />,
    );
    expect(
      await screen.findByText("គ្មានសំណើមកមើលបន្ទប់នៅទីនេះទេ។"),
    ).toBeTruthy();
  });

  it("TEST-FE-1511 the client reads Visit requests from the Bookings address and refuses a list of the wrong shape", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) => {
        calls.push(path);
        return Promise.resolve(
          new Response(JSON.stringify({ data: VISITS, meta: {} }), {
            status: 200,
          }),
        );
      }),
    );
    const { telegramApi } = await import("./telegramClient");
    expect(await telegramApi.visitRequests("p 1")).toEqual(VISITS);
    expect(calls).toEqual(["/api/v1/properties/p%201/visit-requests"]);
    expect(() => visitRequestsPageOf({ requests: [] })).toThrow(TelegramError);
    expect(() =>
      visitRequestsPageOf({
        today: "2026-11-05",
        requests: [{ ...VISITS.requests[0], joined: null }],
      }),
    ).toThrow(TelegramError);
  });
  it("TEST-FE-1512 Visit requests shows the Waiting, Late, Visits booked and Mine cards, and Send by hand today gives the words in the customer's language to copy and Mark sent", async () => {
    const booked: VisitRequest = {
      ...FIRST,
      ...WORK,
      id: "vr-3",
      number: "VR260003",
      name: "Rithy",
      language: "km",
      contact_by: "WHATSAPP",
      email: null,
      status: "VISIT_BOOKED",
      staff_id: "staff-1",
      staff: "Dara",
      mine: true,
      visit_local: "2026-11-07T09:00",
      visit_staff: "Dara",
      to_send: ["CONFIRMATION"],
      joined: [],
    };
    const late: VisitRequest = {
      ...FIRST,
      id: "vr-4",
      number: "VR260004",
      waiting_minutes: 185,
      late: true,
      joined: [],
    };
    const page: VisitRequestsPage = {
      ...PAGE_FACTS,
      requests: [late, booked],
    };
    const sent = { ...page, requests: [late, { ...booked, to_send: [] }] };
    const visitStep = vi.fn(() =>
      Promise.resolve({ request: { ...booked, history: [] }, page: sent }),
    );
    const api = fakeApi({
      visitRequests: vi.fn(() => Promise.resolve(page)),
      visitStep,
    });
    render(
      <VisitRequestsPageView
        active
        api={api}
        capabilities={new Set(["visit_requests.read"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    expect(
      await screen.findByRole("button", { name: /^Response overdue: 1\./ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /^Awaiting first contact: 1\./ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /^Viewings booked: 1\./ }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Mine: 1\./ })).toBeTruthy();
    expect(screen.getByText("3 h 5 min")).toBeTruthy();
    expect(screen.getAllByText("Overdue").length).toBeGreaterThan(0);
    // The words go in the customer's language (Khmer here), with the day and the address.
    const box = screen.getByRole("region", { name: "Send manually today" });
    expect(within(box).getByText("Viewing confirmation")).toBeTruthy();
    expect(
      within(box).getByText(/ថ្ងៃ៖ ថ្ងៃសៅរ៍ 07\/11\/2026 ម៉ោង 09:00/),
    ).toBeTruthy();
    expect(within(box).getByText(/Near Camko Roundabout/)).toBeTruthy();
    fireEvent.click(within(box).getByRole("button", { name: "Mark as sent" }));
    await waitFor(() => {
      expect(
        screen.queryByRole("region", { name: "Send manually today" }),
      ).toBeNull();
    });
    expect(visitStep).toHaveBeenCalledWith("prop-1", "vr-3", "sent", {
      what: "CONFIRMATION",
    });
    // A card shows only its requests.
    fireEvent.click(
      screen.getByRole("button", { name: /^Response overdue: 1\./ }),
    );
    expect(screen.getByText("Showing: Response overdue")).toBeTruthy();
    expect(screen.queryByText("VR260003")).toBeNull();
  });

  it('TEST-FE-2125 (owner 12/11/2026: "check all card is link to correct place") "#/visitreqs?show=waiting" opens Viewing requests on the Awaiting first contact card; a card chosen by hand is kept in the address', async () => {
    const waiting: VisitRequest = {
      ...FIRST,
      id: "vr-4",
      number: "VR260004",
      joined: [],
    };
    const booked: VisitRequest = {
      ...FIRST,
      ...WORK,
      id: "vr-3",
      number: "VR260003",
      status: "VISIT_BOOKED",
      staff_id: "staff-1",
      staff: "Dara",
      visit_local: "2026-11-07T09:00",
      visit_staff: "Dara",
      to_send: [],
      joined: [],
    };
    const api = fakeApi({
      visitRequests: vi.fn(() =>
        Promise.resolve({ ...PAGE_FACTS, requests: [waiting, booked] }),
      ),
    });
    window.location.hash = "#/visitreqs?show=waiting";
    render(
      <VisitRequestsPageView
        active
        api={api}
        capabilities={new Set(["visit_requests.read"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    expect(
      await screen.findByRole("button", {
        name: /^Awaiting first contact: 1\./,
        pressed: true,
      }),
    ).toBeTruthy();
    expect(screen.getByText("Showing: Awaiting first contact")).toBeTruthy();
    expect(screen.getByText("VR260004")).toBeTruthy();
    expect(screen.queryByText("VR260003")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: /^Viewings booked: 1\./ }),
    );
    expect(window.location.hash).toBe("#/visitreqs?show=booked");
    expect(screen.getByText("VR260003")).toBeTruthy();
    expect(screen.queryByText("VR260004")).toBeNull();
    window.location.hash = "";
  });

  it("TEST-FE-1513 a Visit request opens with Take; the person who has it records calls, books a visit Monday to Saturday and closes it; a Manager gives it and marks Spam with a note; the history is shown", async () => {
    const fresh: VisitRequestDetail = {
      ...FIRST,
      contact_by: "TELEGRAM",
      email: null,
      history: [],
    };
    const mine: VisitRequestDetail = {
      ...fresh,
      status: "CONTACTED",
      staff_id: "staff-1",
      staff: "Dara",
      mine: true,
      calls: 1,
      history: [
        {
          at: "2026-11-05T03:10:00Z",
          kind: "TAKEN",
          by: "Dara",
          staff: "Dara",
          answered: null,
          visit_at: null,
          reason: null,
          what: null,
          note: null,
          sent_by_bot: false,
        },
        {
          at: "2026-11-05T03:20:00Z",
          kind: "CALL",
          by: "Dara",
          staff: null,
          answered: true,
          visit_at: null,
          reason: null,
          what: null,
          note: "Wants Monday",
          sent_by_bot: false,
        },
      ],
    };
    const visitStep = vi.fn(() =>
      Promise.resolve({ request: mine, page: VISITS }),
    );
    const api = fakeApi({
      visitRequest: vi.fn(() => Promise.resolve(fresh)),
      visitStep,
    });
    render(
      <VisitRequestsPageView
        active
        api={api}
        capabilities={new Set(["visit_requests.read"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open VR260001" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByText("Record a call")).toBeNull();
    expect(within(dialog).queryByText("Manager")).toBeNull();
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "Assign to me" }),
    );
    expect(await within(dialog).findByText("Saved.")).toBeTruthy();
    expect(visitStep).toHaveBeenLastCalledWith("prop-1", "vr-1", "take", {});
    expect(within(dialog).getByText("Assigned to Dara")).toBeTruthy();
    expect(
      within(dialog).getByText(/Call: answered · Wants Monday/),
    ).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "No answer" }));
    expect(visitStep).toHaveBeenLastCalledWith("prop-1", "vr-1", "call", {
      answered: false,
    });
    expect(await within(dialog).findByText("Saved.")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "The customer gets the confirmation on Telegram, and a reminder at 08:00 the day before.",
        { exact: false },
      ),
    ).toBeTruthy();
    // A Sunday is refused here; the server checks the day and time again.
    fireEvent.change(within(dialog).getByLabelText("Day"), {
      target: { value: "2026-11-08" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Book viewing" }),
    );
    expect(
      within(dialog).getByText("Choose today or a later day, except Sunday."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Day"), {
      target: { value: "2026-11-09" },
    });
    fireEvent.change(within(dialog).getByLabelText("Time"), {
      target: { value: "14:30" },
    });
    fireEvent.change(within(dialog).getByLabelText("Shown by"), {
      target: { value: "boss-1" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Book viewing" }),
    );
    await waitFor(() => {
      expect(visitStep).toHaveBeenLastCalledWith("prop-1", "vr-1", "book", {
        visit_at: "2026-11-09T14:30",
        staff_id: "boss-1",
      });
    });
    // Other needs a note.
    fireEvent.change(within(dialog).getByLabelText("Reason"), {
      target: { value: "OTHER" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Close request" }),
    );
    expect(within(dialog).getByText("Write a note.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Reason"), {
      target: { value: "PRICE" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Close request" }),
    );
    await waitFor(() => {
      expect(visitStep).toHaveBeenLastCalledWith("prop-1", "vr-1", "close", {
        reason: "PRICE",
      });
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Customer cancelled" }),
    );
    await waitFor(() => {
      expect(visitStep).toHaveBeenLastCalledWith("prop-1", "vr-1", "close", {
        reason: "CANCELLED",
      });
    });
    cleanup();

    // A Manager: Give to and Mark Spam (with a note); someone else's request is read only for Staff.
    const bossPage = { ...VISITS, can_manage: true, me: "boss-1" };
    const bossStep = vi.fn(() =>
      Promise.resolve({ request: { ...mine, mine: false }, page: bossPage }),
    );
    const manager = fakeApi({
      visitRequests: vi.fn(() => Promise.resolve(bossPage)),
      visitRequest: vi.fn(() => Promise.resolve({ ...mine, mine: false })),
      visitStep: bossStep,
    });
    render(
      <VisitRequestsPageView
        active
        api={manager}
        capabilities={new Set(["visit_requests.read"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open VR260001" }),
    );
    const boss = await screen.findByRole("dialog");
    expect(await within(boss).findByText("Manager")).toBeTruthy();
    fireEvent.change(within(boss).getByLabelText("Assign to"), {
      target: { value: "boss-1" },
    });
    fireEvent.click(within(boss).getByRole("button", { name: "Assign to" }));
    await waitFor(() => {
      expect(bossStep).toHaveBeenLastCalledWith("prop-1", "vr-1", "give", {
        staff_id: "boss-1",
      });
    });
    fireEvent.click(within(boss).getByRole("button", { name: "Mark as spam" }));
    expect(within(boss).getByText("Write a note.")).toBeTruthy();
    fireEvent.change(
      fieldById(within(boss).getAllByLabelText("Reason"), "vr-spam"),
      {
        target: { value: " Advert " },
      },
    );
    fireEvent.click(within(boss).getByRole("button", { name: "Mark as spam" }));
    await waitFor(() => {
      expect(bossStep).toHaveBeenLastCalledWith("prop-1", "vr-1", "spam", {
        note: "Advert",
      });
    });
    cleanup();

    const other = fakeApi({
      visitRequest: vi.fn(() => Promise.resolve({ ...mine, mine: false })),
    });
    render(
      <VisitRequestsPageView
        active
        api={other}
        capabilities={new Set(["visit_requests.read"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open VR260001" }),
    );
    expect(
      await screen.findByText(
        "This request is assigned to Dara. Only Dara or a Manager can update it.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Answered" })).toBeNull();
  });

  it("TEST-FE-1514 the client reads one Visit request and sends each step to its address with the CSRF token", async () => {
    const detail = { ...VISITS.requests[0], history: [] };
    const calls: [string, RequestInit | undefined][] = [];
    document.cookie = "__Host-prm_csrf=tg-token";
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        calls.push([path, init]);
        const data =
          init?.method === "POST" ? { request: detail, page: VISITS } : detail;
        return Promise.resolve(
          new Response(JSON.stringify({ data, meta: {} }), { status: 200 }),
        );
      }),
    );
    const { telegramApi } = await import("./telegramClient");
    expect(await telegramApi.visitRequest("p 1", "vr 1")).toEqual(detail);
    const done = await telegramApi.visitStep("p 1", "vr 1", "no-show", {
      note: "Did not come",
    });
    expect(done.page).toEqual(VISITS);
    expect(calls.map(([path]) => path)).toEqual([
      "/api/v1/properties/p%201/visit-requests/vr%201",
      "/api/v1/properties/p%201/visit-requests/vr%201/no-show",
    ]);
    expect(calls[1]?.[1]?.body).toBe(JSON.stringify({ note: "Did not come" }));
    expect(
      (calls[1]?.[1]?.headers as Record<string, string>)["X-CSRF-Token"],
    ).toBe("tg-token");
    expect(() =>
      visitRequestDetailOf({ ...detail, history: [{ kind: "TAKEN" }] }),
    ).toThrow(TelegramError);
    expect(() => visitRequestsPageOf({ ...VISITS, can_work: "yes" })).toThrow(
      TelegramError,
    );
  });
  it("TEST-FE-2206 Viewing requests: This month is number cards, the counts are lists inside the card, and the request list has six columns", async () => {
    const page: VisitRequestsPage = {
      ...VISITS,
      can_manage: true,
      month: {
        month: "2026-11",
        new: 3,
        joined: 1,
        steps: { VISIT_BOOKED: 1 },
        reasons: [],
        sources: [{ code: "TELEGRAM", count: 3 }],
      },
    };
    render(
      <VisitRequestsPageView
        active
        api={fakeApi({ visitRequests: vi.fn(() => Promise.resolve(page)) })}
        capabilities={null}
        language="en"
        propertyId="prop-1"
      />,
    );
    const month = await screen.findByRole("region", { name: /This month/ });
    const cards = within(month)
      .getAllByRole("listitem")
      .map((card) => card.textContent);
    expect(cards.slice(0, 8)).toEqual([
      "New requests3",
      "Asked again1",
      "Viewings booked1",
      "Viewings done0",
      "No-show0",
      "Reserved0",
      "Closed0",
      "Spam0",
    ]);
    expect(cards[8]).toBe("Telegram bot3");
    expect(within(month).queryByRole("table")).toBeNull();
    const list = screen.getByRole("table");
    expect(
      within(list)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Request", "Waited", "Customer", "Wants", "Status", "Staff"]);
  });
  it("TEST-FE-1516 a Visit request opens Make Reservation, shows the Reservation it became, a Manager blocks the Telegram account with a note, a removed request says so, and Managers see this month", async () => {
    const contacted: VisitRequestDetail = {
      ...FIRST,
      status: "CONTACTED",
      staff_id: "staff-1",
      staff: "Dara",
      mine: true,
      history: [],
    };
    const managerPage: VisitRequestsPage = {
      ...VISITS,
      can_manage: true,
      month: {
        month: "2026-11",
        new: 7,
        joined: 2,
        steps: { VISIT_BOOKED: 3, VISITED: 2, RESERVED: 1, CLOSED: 2 },
        reasons: [
          { code: "PRICE", count: 2 },
          { code: "CANCELLED", count: 1 },
        ],
        sources: [{ code: "TELEGRAM", count: 7 }],
      },
    };
    const visitStep = vi.fn(() =>
      Promise.resolve({
        request: { ...contacted, blocked: true },
        page: managerPage,
      }),
    );
    const api = fakeApi({
      visitRequests: vi.fn(() => Promise.resolve(managerPage)),
      visitRequest: vi.fn(() => Promise.resolve(contacted)),
      visitStep,
    });
    render(
      <VisitRequestsPageView
        active
        api={api}
        capabilities={null}
        language="en"
        propertyId="prop-1"
      />,
    );
    const month = await screen.findByRole("region", { name: /This month/ });
    expect(within(month).getByText("11/2026")).toBeTruthy();
    expect(within(month).getByText("Price too high")).toBeTruthy();
    expect(within(month).getByText("Customer cancelled")).toBeTruthy();
    expect(within(month).getByText("Telegram bot")).toBeTruthy();
    expect(within(month).getAllByText("7")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Open VR260001" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      await within(dialog).findByRole("button", {
        name: "Block Telegram account",
      }),
    );
    expect(within(dialog).getByText("Write a note.")).toBeTruthy();
    // UI v81: Spam and Block both ask "Reason".
    const reasons = within(dialog).getAllByLabelText("Reason");
    fireEvent.change(fieldById(reasons, "vr-block"), {
      target: { value: "Adverts" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Block Telegram account" }),
    );
    expect(
      await within(dialog).findByText(
        "This Telegram account is blocked. It cannot send requests or messages.",
      ),
    ).toBeTruthy();
    expect(visitStep).toHaveBeenCalledWith("prop-1", "vr-1", "block", {
      note: "Adverts",
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Unblock Telegram account" }),
    );
    await waitFor(() => {
      expect(visitStep).toHaveBeenLastCalledWith(
        "prop-1",
        "vr-1",
        "unblock",
        {},
      );
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "New Reservation" }),
    );
    expect(decodeURIComponent(window.location.hash)).toBe(
      "#/reservations/visit:vr-1",
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    cleanup();
    window.location.hash = "";

    const reserved = fakeApi({
      visitRequest: vi.fn(() =>
        Promise.resolve({
          ...contacted,
          status: "RESERVED",
          reservation_id: "res-9",
          removed: true,
          name: "",
          phone: "",
        }),
      ),
    });
    render(
      <VisitRequestsPageView
        active
        api={reserved}
        capabilities={new Set(["visit_requests.read"])}
        language="en"
        propertyId="prop-1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open VR260001" }),
    );
    const done = await screen.findByRole("dialog");
    expect(await within(done).findByText("Reserved")).toBeTruthy();
    expect(
      within(done).getByRole("link", { name: "Open the Reservation" }),
    ).toHaveAttribute("href", "#/reservations/res-9");
    expect(
      within(done).getByText(
        "The name, phone and email were removed after 12 months with no activity.",
      ),
    ).toBeTruthy();
    expect(
      within(done).queryByRole("button", { name: "New Reservation" }),
    ).toBeNull();
    expect(within(done).queryByText("Record a call")).toBeNull();
  });
});
