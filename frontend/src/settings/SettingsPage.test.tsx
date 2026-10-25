import {
  act,
  cleanup,
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
import { SettingsPage } from "./SettingsPage";

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
      },
      can_manage: true,
    }),
  ),
  createSetupItem: vi.fn(),
  updateSetupItem: vi.fn(),
  removeSetupItem: vi.fn(),
};

const usersApi = {
  load: vi.fn(() =>
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
  giveSettingsAccess: vi.fn(),
  removeSettingsAccess: vi.fn(),
};

function show(
  status: () => Promise<HealthStatus>,
  {
    capabilities = null as ReadonlySet<string> | null,
    language = "en" as "en" | "km",
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
      propertyId="property-1"
      reauthenticate={vi.fn()}
      unitApi={setupApi}
      usersApi={usersApi}
    />,
  );
  return api;
}

describe("Settings", () => {
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
    expect(tabs).toEqual([
      ["Business", "#/settings/business"],
      ["Rates and services", "#/settings/rates"],
      ["Unit setup", "#/settings/units"],
      ["Users and sign-in", "#/settings/users"],
    ]);
    // The first tab opens; a tab not rebuilt yet keeps its earlier forms, folded.
    expect(onShownTab("Old business form")).toBe(true);
    expect(onShownTab("Old account form")).toBe(false);
    openTab("users");
    expect(onShownTab("Old account form")).toBe(true);
    expect(onShownTab("Old business form")).toBe(false);
    expect(
      screen
        .getByRole("link", { name: "Users and sign-in" })
        .getAttribute("aria-current"),
    ).toBe("page");
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
        "System health could not be read just now. The app may still be working; try again.",
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
});
