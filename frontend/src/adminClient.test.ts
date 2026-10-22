import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AdministrationError,
  AdministrationUnavailableError,
  UserAccount,
  accessAdministrationApi,
} from "./adminClient";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const user = {
  user_id: "user-1",
  property_id: "property-1",
  username: "staff-one",
  display_name: "Staff One",
  audit_name: "Staff One",
  lifecycle_state: "active",
  mfa_policy_class: "optional",
  version: 1,
  account_class: "staff",
  settings_access: false,
} satisfies UserAccount;

function jsonResponse(data: unknown): Response {
  return new Response(
    JSON.stringify({
      data,
      page: { next_cursor: null, limit: 100 },
      meta: { request_id: "request-1" },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

describe("access administration client", () => {
  it("TEST-FE-ADMIN-001 loads only server-authorized property users, bundles, and capability catalog", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([user]))
      .mockResolvedValueOnce(
        jsonResponse([
          {
            capability_id: "access.admin",
            name: "Access administration",
            description: "Manage property access",
          },
        ]),
      )
      .mockResolvedValueOnce(
        jsonResponse([
          {
            role_bundle_id: "bundle-1",
            property_id: "property-1",
            name: "Configured bundle",
            capability_ids: ["access.admin"],
            version: 1,
          },
        ]),
      )
      .mockResolvedValueOnce(
        jsonResponse([
          {
            event_id: "event-1",
            property_id: "property-1",
            occurred_at: "2026-08-22T10:00:00Z",
            action: "role_bundle_assigned",
            actor_id: "owner-1",
            target_id: "user-1",
            outcome: "completed",
          },
        ]),
      );
    vi.stubGlobal("fetch", fetchImplementation);

    await expect(accessAdministrationApi.load("property-1")).resolves.toEqual({
      users: [user],
      capabilities: [
        {
          capability_id: "access.admin",
          name: "Access administration",
          description: "Manage property access",
        },
      ],
      roleBundles: [
        {
          role_bundle_id: "bundle-1",
          property_id: "property-1",
          name: "Configured bundle",
          capability_ids: ["access.admin"],
          version: 1,
        },
      ],
      authorizationHistory: [
        {
          event_id: "event-1",
          property_id: "property-1",
          occurred_at: "2026-08-22T10:00:00Z",
          action: "role_bundle_assigned",
          actor_id: "owner-1",
          target_id: "user-1",
          outcome: "completed",
        },
      ],
    });
    expect(fetchImplementation).toHaveBeenCalledWith(
      "/api/v1/properties/property-1/users?limit=100",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });

  it("TEST-FE-ADMIN-002 hides administration uniformly when the server denies capability", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response(null, { status: 403 })),
    );
    await expect(accessAdministrationApi.load("property-1")).rejects.toEqual(
      new AdministrationUnavailableError(),
    );
  });

  it("TEST-FE-ADMIN-003 binds disablement to CSRF and exact optimistic version", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        jsonResponse({ ...user, lifecycle_state: "disabled", version: 2 }),
      );
    vi.stubGlobal("fetch", fetchImplementation);
    await accessAdministrationApi.disableUser(user);
    const init: unknown = fetchImplementation.mock.calls[0]?.[1];
    if (typeof init !== "object" || init === null || !("headers" in init)) {
      throw new Error("request initialization is missing");
    }
    const headers = new Headers(init.headers as HeadersInit);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token");
    expect(headers.get("If-Match")).toBe('"1"');
    expect("body" in init ? init.body : undefined).toBe(
      JSON.stringify({ lifecycle_state: "disabled" }),
    );
  });

  it("TEST-FE-ADMIN-005 creates an account by its class and reads its class and Settings access", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(user))
      .mockResolvedValueOnce(jsonResponse({ ...user, account_class: "owner" }))
      .mockResolvedValueOnce(jsonResponse({ ...user, account_class: null }))
      .mockResolvedValueOnce(
        jsonResponse({ ...user, account_class: "Owner authority" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...user, settings_access: undefined }),
      );
    vi.stubGlobal("fetch", fetchImplementation);
    const newUser = {
      username: "staff-one",
      display_name: "Staff One",
      audit_name: "Staff One",
      account_class: "staff",
    } as const;

    await expect(
      accessAdministrationApi.createUser("property-1", newUser),
    ).resolves.toEqual(user);
    const init: unknown = fetchImplementation.mock.calls[0]?.[1];
    if (typeof init !== "object" || init === null || !("body" in init)) {
      throw new Error("request initialization is missing");
    }
    expect(init.body).toBe(JSON.stringify(newUser));
    await expect(
      accessAdministrationApi.createUser("property-1", newUser),
    ).resolves.toEqual({ ...user, account_class: "owner" });
    await expect(
      accessAdministrationApi.createUser("property-1", newUser),
    ).resolves.toEqual({ ...user, account_class: null });
    await expect(
      accessAdministrationApi.createUser("property-1", newUser),
    ).rejects.toEqual(new AdministrationError());
    await expect(
      accessAdministrationApi.createUser("property-1", newUser),
    ).rejects.toEqual(new AdministrationError());
  });

  it("TEST-FE-ADMIN-004 follows bounded cursors instead of silently omitting history", async () => {
    const page = (data: unknown[], nextCursor: string | null) =>
      new Response(
        JSON.stringify({
          data,
          page: { next_cursor: nextCursor, limit: 100 },
          meta: { request_id: "request" },
        }),
      );
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(page([], null))
      .mockResolvedValueOnce(page([], null))
      .mockResolvedValueOnce(page([], null))
      .mockResolvedValueOnce(
        page(
          [
            {
              event_id: "event-1",
              property_id: "property-1",
              occurred_at: "2026-08-22T10:00:00Z",
              action: "account_created",
              actor_id: "owner-1",
              target_id: "user-1",
              outcome: "completed",
            },
          ],
          "next-page",
        ),
      )
      .mockResolvedValueOnce(
        page(
          [
            {
              event_id: "event-2",
              property_id: "property-1",
              occurred_at: "2026-08-22T10:01:00Z",
              action: "role_bundle_assigned",
              actor_id: "owner-1",
              target_id: "user-1",
              outcome: "completed",
            },
          ],
          null,
        ),
      );
    vi.stubGlobal("fetch", fetchImplementation);

    const result = await accessAdministrationApi.load("property-1");

    expect(result.authorizationHistory).toHaveLength(2);
    expect(fetchImplementation).toHaveBeenLastCalledWith(
      "/api/v1/properties/property-1/authorization-history?limit=100&cursor=next-page",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });
});
