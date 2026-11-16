import {
  act,
  cleanup,
  waitFor,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  HealthNotAllowedError,
  type HealthStatus,
  HealthUnavailableError,
} from "./healthClient";
import type { AccessAdministrationSnapshot } from "../adminClient";
import { rolesApiOf } from "../test/rolesFixtures";
import { SettingsPage, type SettingsPageProps } from "./SettingsPage";

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "#/");
});

const HEALTHY: HealthStatus = {
  build_version: "1.0.0-rc1",
  environment: "production",
  generated_at: "2026-11-03T03:30:00Z",
  database: "ok",
  backup: {
    last_attempt_at: "2026-11-02T19:00:00Z",
    last_outcome: "succeeded",
    last_success_at: "2026-11-02T19:00:00Z",
  },
  offhost_daily: { last_success_at: "2026-11-02T20:00:00Z" },
  offhost_weekly: null,
  restore_test: {
    last_outcome: "failed",
    last_attempt_at: "2026-11-01T21:00:00Z",
    last_success_at: null,
  },
  migration: { revision: "20270222_210" },
  last_check_at: "2026-11-03T03:25:00Z",
  schema_revision: "20270222_210",
  scheduled_jobs: {
    billing_last_success_at: "2026-10-24T23:00:00Z",
    reservation_expiration_last_success_at: "2026-11-02T17:05:00Z",
  },
  telegram: {
    configured: true,
    last_delivery_outcome: "sent",
    last_attempt_at: "2026-11-01T21:01:00Z",
  },
  warnings: [],
};

/** Is this earlier form on the tab shown now (it sits folded under "Earlier forms")? */
const onShownTab = (text: string) =>
  screen.getByText(text).closest("[hidden]") === null;

function openTab(tab: string) {
  act(() => {
    window.history.replaceState(null, "", `#/settings/${tab}`);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

const setupApi = {
  list: vi.fn(() =>
    Promise.resolve({ items: [], next_cursor: null, can_manage: true }),
  ),
  setupLists: vi.fn(() =>
    Promise.resolve({
      lists: {
        FLOOR: [],
        UNIT_TYPE: [],
        VIEW: [],
        KITCHEN: [],
        ROOM_FEATURE: [],
        FEATURE_TYPE: [],
        UNIT_FEATURE: [],
        ITEM_TYPE: [],
      },
      can_manage: true,
    }),
  ),
  createSetupItem: vi.fn(),
  updateSetupItem: vi.fn(),
  removeSetupItem: vi.fn(),
};

const usersApi = {
  load: vi.fn(
    (): Promise<AccessAdministrationSnapshot> =>
      Promise.resolve({
        users: [],
        capabilities: [],
        roleBundles: [],
        authorizationHistory: [],
      }),
  ),
  createUser: vi.fn(),
  disableUser: vi.fn(),
  revokeSessions: vi.fn(),
  administrativelyRecoverUser: vi.fn(),
};

const businessApi = {
  property: {
    load: vi.fn(() =>
      Promise.resolve({
        property_id: "property-1",
        name: "CHETANA Parking",
        address_text: null,
        description: null,
        business_name: null,
        timezone_name: "Asia/Phnom_Penh" as const,
        payment_methods: [],
        version: 1,
      }),
    ),
    updateSource: vi.fn(),
    updatePaymentMethods: vi.fn(),
  },
  settings: {
    rules: vi.fn(() => Promise.resolve({ rules: [], today: "2026-11-03" })),
    setRule: vi.fn(),
    addRule: vi.fn(),
    numbers: vi.fn(() => Promise.resolve([])),
    setLetters: vi.fn(),
    invoiceTypes: vi.fn(() => Promise.resolve([])),
    setLatePayment: vi.fn(),
  },
  dueDays: {
    get: vi.fn(() =>
      Promise.resolve({
        property_id: "property-1",
        one_time_charge_due_days: 7,
        version: 1,
      }),
    ),
    set: vi.fn(),
  },
  units: setupApi,
  rates: { load: vi.fn(() => Promise.reject(new Error("no rates"))) },
};

const ratesApi = {
  load: vi.fn(() => Promise.reject(new Error("no rates"))),
  loadConfiguredServices: vi.fn(),
  loadServiceRates: vi.fn(),
  loadUtilityRates: vi.fn(),
  createServiceRate: vi.fn(),
  createUtilityRate: vi.fn(),
};

function show(
  status: () => Promise<HealthStatus>,
  {
    capabilities = null as ReadonlySet<string> | null,
    language = "en" as "en" | "km",
    propertyId = "property-1",
    mode = "settings" as "settings" | "access",
    testApp = false,
    stayApi = undefined as SettingsPageProps["stayApi"],
  } = {},
) {
  const api = { status: vi.fn(status) };
  render(
    <SettingsPage
      active
      capabilities={capabilities}
      earlier={{
        business: <p>Old business form</p>,
        users: <p>Old account form</p>,
      }}
      healthApi={api}
      language={language}
      myUserId="owner-1"
      propertyId={propertyId}
      reauthenticate={vi.fn()}
      unitApi={setupApi}
      usersApi={usersApi}
      rolesApi={rolesApiOf()}
      businessApi={businessApi}
      ratesApi={ratesApi}
      mode={mode}
      testApp={testApp}
      {...(stayApi === undefined ? {} : { stayApi })}
    />,
  );
  return api;
}

describe("Settings", () => {
  it("TEST-FE-1116 with no Property open, the Business, Rates, Parking and Users tabs say how to open one instead of reading forever, and the earlier form to open it stays (V1-061 Fix 4)", async () => {
    window.location.hash = "#/settings/business";
    businessApi.property.load.mockClear();
    show(() => new Promise<HealthStatus>(() => undefined), { propertyId: "" });
    const note =
      "No Property is open yet. On the Business tab, open “Earlier forms (English)”, enter the Property identifier and press “Load business configuration”. Then every tab fills in.";
    expect(await screen.findByText(note)).toBeInTheDocument();
    expect(screen.queryByText("Reading the business settings…")).toBeNull();
    expect(screen.getByText("Old business form")).toBeInTheDocument();
    expect(businessApi.property.load).not.toHaveBeenCalled();
    for (const tab of ["rates", "units", "users"]) {
      act(() => {
        window.location.hash = `#/settings/${tab}`;
        window.dispatchEvent(new HashChangeEvent("hashchange"));
      });
      expect(await screen.findByText(note)).toBeInTheDocument();
    }
  });

  it("TEST-FE-937 shows only the tabs the person may use; a Manager without Settings access lands on System health, which lists the health records", async () => {
    const api = show(() => Promise.resolve(HEALTHY), {
      capabilities: new Set(["operations.status.read"]),
    });
    expect(screen.queryByRole("navigation")).toBeNull();
    const card = await screen.findByRole("region", { name: "System health" });
    expect(api.status).toHaveBeenCalledTimes(1);
    expect(within(card).getByText("Healthy")).toBeTruthy();
    const pairs = Array.from(card.querySelectorAll("dt")).map(
      (term) =>
        `${term.textContent}: ${term.nextElementSibling?.textContent ?? ""}`,
    );
    expect(pairs).toEqual([
      "App version: 1.0.0-rc1",
      "Database: PostgreSQL · Healthy",
      "Migration: 20270222_210",
      "Last backup: 03/11/2026 02:00 · OK",
      "Copy to another place: Daily 03/11/2026 03:00 · OK · Weekly Not yet",
      "Last restore test: Failed 02/11/2026 04:00",
      "Last billing run: 25/10/2026 06:00",
      "Last reservation expiry check: 03/11/2026 00:05",
      "Telegram alerts: On · last sent 02/11/2026 04:01",
      "Last health check: 03/11/2026 10:25",
    ]);
    expect(onShownTab("Old business form")).toBe(false);
    cleanup();

    show(() => Promise.resolve(HEALTHY), {
      capabilities: new Set(["settings.manage", "identity.manage_access"]),
    });
    const tabs = within(
      screen.getByRole("navigation", { name: "Settings tabs" }),
    )
      .getAllByRole("link")
      .map((link) => [link.textContent, link.getAttribute("href")]);
    // UI v81: Business first (round 4: "Business" again, so it does not clash with its General
    // sub-tab); Rates split in two; Users and access is its own menu item.
    expect(tabs).toEqual([
      ["Business", "#/settings/business"],
      ["Utility rates", "#/settings/rates"],
      ["Monthly services", "#/settings/services"],
      ["Unit setup", "#/settings/units"],
    ]);
    // The first tab opens; a tab not rebuilt yet keeps its earlier forms, folded.
    expect(onShownTab("Old business form")).toBe(true);
    expect(onShownTab("Old account form")).toBe(false);
    openTab("services");
    expect(
      screen
        .getByRole("link", { name: "Monthly services" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(onShownTab("Old business form")).toBe(false);
    // A tab the person may not use opens the first one instead.
    openTab("health");
    expect(onShownTab("Old business form")).toBe(true);
  });

  it("TEST-FE-938 a warning or a database that does not answer says Needs attention with the server's notes; a failed read offers Retry and shows no old state; no right says so", async () => {
    let answer: () => Promise<HealthStatus> = () =>
      Promise.resolve({
        ...HEALTHY,
        database: "unavailable",
        warnings: [
          {
            code: "database_unavailable",
            message: "The database is not answering.",
            critical: true,
          },
          {
            code: "backup_stale",
            message: "The last good backup is more than a day old.",
            critical: false,
          },
        ],
      });
    const api = show(() => answer());
    openTab("health");
    const card = await screen.findByRole("region", { name: "System health" });
    expect(within(card).getByText("Needs attention")).toBeTruthy();
    expect(card.textContent).toContain("PostgreSQL · Not answering");
    const notes = screen.getByRole("region", { name: "What needs attention" });
    expect(notes.textContent).toContain("The database is not answering.");
    expect(notes.textContent).toContain(
      "The last good backup is more than a day old.",
    );

    answer = () => Promise.reject(new HealthUnavailableError());
    cleanup();
    show(() => answer());
    openTab("health");
    expect(
      await screen.findByText(
        "System health could not be loaded. The app may still be working; try again.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("Needs attention")).toBeNull();
    answer = () => Promise.resolve(HEALTHY);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Healthy")).toBeTruthy();
    expect(api.status).toHaveBeenCalled();
    cleanup();

    show(() => Promise.reject(new HealthNotAllowedError()));
    openTab("health");
    expect(
      await screen.findByText("Your account cannot open this tab."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("TEST-FE-1934 (owner 12/11/2026) on a test app, health records that are not set up are normal: System health says Test computer with a calm note and no Needs attention; the real install, and any other note, still need attention; the Settings wrapper spaces its parts", async () => {
    const notSetUp = {
      code: "operations_status_not_set_up",
      message: "The health records are not set up on this computer yet.",
      critical: false,
    };
    const calm =
      "This is a test computer. Backups and health checks are set up when the app is installed on the real computer, so they show “Not yet” here. Nothing needs fixing.";
    // The local server calls itself "production" too; the screens' own label decides.
    show(() => Promise.resolve({ ...HEALTHY, warnings: [notSetUp] }), {
      testApp: true,
    });
    openTab("health");
    let card = await screen.findByRole("region", { name: "System health" });
    expect(within(card).getByText("Test computer")).toBeTruthy();
    expect(screen.getByText(calm).closest('[role="note"]')).toHaveClass(
      "ui-notice",
      "info",
    );
    expect(screen.queryByText("Needs attention")).toBeNull();
    expect(screen.queryByText("Healthy")).toBeNull();
    expect(
      screen.queryByRole("region", { name: "What needs attention" }),
    ).toBeNull();
    expect(screen.queryByText(notSetUp.message)).toBeNull();
    // The cards and notes of Settings sit in one wrapper that keeps the space between them.
    expect(card.parentElement).toHaveClass("ui-settings");
    cleanup();

    // The real install: the same note needs attention, as before.
    show(() => Promise.resolve({ ...HEALTHY, warnings: [notSetUp] }));
    openTab("health");
    card = await screen.findByRole("region", { name: "System health" });
    expect(within(card).getByText("Needs attention")).toBeTruthy();
    expect(
      screen.getByRole("region", { name: "What needs attention" }).textContent,
    ).toContain(notSetUp.message);
    expect(screen.queryByText(calm)).toBeNull();
    expect(screen.queryByText("Test computer")).toBeNull();
    cleanup();

    // A test app with another note: that note still needs attention; the calm note stays too.
    show(
      () =>
        Promise.resolve({
          ...HEALTHY,
          warnings: [
            notSetUp,
            {
              code: "backup_stale",
              message: "The last good backup is more than a day old.",
              critical: false,
            },
          ],
        }),
      { testApp: true },
    );
    openTab("health");
    card = await screen.findByRole("region", { name: "System health" });
    expect(within(card).getByText("Needs attention")).toBeTruthy();
    const notes = screen.getByRole("region", { name: "What needs attention" });
    expect(notes.textContent).toContain(
      "The last good backup is more than a day old.",
    );
    expect(notes.textContent).not.toContain(notSetUp.message);
    expect(screen.getByText(calm)).toBeTruthy();
    cleanup();

    // A healthy test app is simply Healthy.
    show(() => Promise.resolve(HEALTHY), { testApp: true });
    openTab("health");
    card = await screen.findByRole("region", { name: "System health" });
    expect(within(card).getByText("Healthy")).toBeTruthy();
    expect(screen.queryByText(calm)).toBeNull();
  });

  it("TEST-FE-939 Khmer words come from the mock-up, and the server's English notes are marked as English", async () => {
    show(
      () =>
        Promise.resolve({
          ...HEALTHY,
          warnings: [
            {
              code: "backup_stale",
              message: "The last good backup is more than a day old.",
              critical: false,
            },
          ],
        }),
      { language: "km" },
    );
    openTab("health");
    expect(
      await screen.findByText("ត្រូវការការយកចិត្តទុកដាក់", {
        selector: ".ui-chead *",
      }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "សុខភាពប្រព័ន្ធ" })).toBeTruthy();
    expect(
      screen
        .getByText("The last good backup is more than a day old.")
        .getAttribute("lang"),
    ).toBe("en");
    expect(
      screen.getByText("កំណត់ចំណាំទាំងនេះមកពីម៉ាស៊ីនមេជាភាសាអង់គ្លេស។"),
    ).toBeTruthy();
  });

  it("TEST-FE-1906 Users and access is its own page with Users, Roles, Sign-in and security and History; the earlier account forms show only under History (Administration review fix 10)", async () => {
    window.location.hash = "#/access";
    show(() => Promise.resolve(HEALTHY), {
      capabilities: new Set(["identity.manage_access"]),
      mode: "access",
    });
    const tabs = within(
      screen.getByRole("tablist", { name: "Users and access sections" }),
    )
      .getAllByRole("tab")
      .map((tab) => tab.textContent);
    expect(tabs).toEqual(["Users", "Roles", "Sign-in and security", "History"]);
    // On Users the earlier account forms are hidden; the Settings ones too.
    expect(
      screen.getByText("Old account form").closest("[hidden]"),
    ).not.toBeNull();
    expect(
      screen.getByText("Old business form").closest("[hidden]"),
    ).not.toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(window.location.hash).toBe("#/access?tab=history");
    expect(screen.getByText("Old account form").closest("[hidden]")).toBeNull();
    expect(
      await screen.findByText("No access change yet."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2230 Users and access › History lists the access changes, newest first, with names and plain words (Administration review fix 10)", async () => {
    window.location.hash = "#/access?tab=history";
    usersApi.load.mockImplementationOnce(() =>
      Promise.resolve({
        users: [
          {
            user_id: "u-owner",
            display_name: "Owner",
          } as never,
          { user_id: "u-dara", display_name: "Sok Dara" } as never,
        ],
        capabilities: [],
        roleBundles: [],
        authorizationHistory: [
          {
            event_id: "e1",
            property_id: "p",
            occurred_at: "2026-11-13T01:00:00Z",
            action: "identity.account.created",
            actor_id: "u-owner",
            target_id: "u-dara",
            outcome: "completed",
          },
          {
            event_id: "e2",
            property_id: "p",
            occurred_at: "2026-11-13T02:00:00Z",
            action: "identity.account.locked_out",
            actor_id: "u-owner",
            target_id: "u-dara",
            outcome: "rejected",
          },
        ],
      }),
    );
    show(() => Promise.resolve(HEALTHY), {
      capabilities: new Set(["identity.manage_access"]),
      mode: "access",
    });
    const added = await screen.findByText("User added");
    const rows = screen.getAllByRole("row").slice(1);
    // Newest first: the unknown action reads in plain words, and a refused one says so.
    expect(rows[0]).toHaveTextContent("Account locked out");
    expect(rows[0]).toHaveTextContent("Refused");
    expect(rows[1]).toContainElement(added);
    expect(rows[1]).toHaveTextContent("Sok Dara");
    expect(rows[1]).toHaveTextContent("13/11/2026");
  });

  it("TEST-FE-2231 Users and access follows the address, so the side menu's Roles opens Roles on the open page (Administration review fix 5)", () => {
    window.location.hash = "#/access";
    show(() => Promise.resolve(HEALTHY), {
      capabilities: new Set(["identity.manage_access"]),
      mode: "access",
    });
    expect(screen.getByRole("tab", { name: "Users" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    act(() => {
      window.location.hash = "#/access?tab=roles";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByRole("tab", { name: "Roles" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("TEST-FE-2187 Booking sites is a Settings tab for the Owner and the Manager (owner 13/11/2026: moved from Short stays)", async () => {
    window.location.hash = "#/settings/sites";
    const siteCalendars = vi.fn(() => new Promise<never>(() => undefined));
    const calendar = vi.fn(() => new Promise<never>(() => undefined));
    show(() => new Promise<HealthStatus>(() => undefined), {
      stayApi: {
        siteCalendars,
        calendar,
      } as unknown as SettingsPageProps["stayApi"],
    });
    expect(screen.getByRole("link", { name: "Booking sites" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await waitFor(() => {
      expect(siteCalendars).toHaveBeenCalledWith("property-1");
    });
    cleanup();
    window.location.hash = "#/settings/business";
    show(() => new Promise<HealthStatus>(() => undefined), {
      capabilities: new Set(["settings.manage"]),
    });
    expect(screen.queryByRole("link", { name: "Booking sites" })).toBeNull();
  });
});
