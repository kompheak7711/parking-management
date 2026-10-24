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

function jsonResponse(
  data: unknown,
  extra: Record<string, unknown> = {},
): Response {
  return new Response(
    JSON.stringify({
      data,
      page: { next_cursor: null, limit: 100 },
      meta: { request_id: "request-1" },
      ...extra,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

// Login sub-slice L4: the one-time password the server makes for a new or reset account.
const oneTimePassword = {
  value: "k7m2-x9qp-4hrt-w3nd",
  expires_at: "2026-08-23T10:10:00Z",
};
const withPassword = { one_time_password: oneTimePassword };

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
      .mockResolvedValueOnce(jsonResponse(user, withPassword))
      .mockResolvedValueOnce(
        jsonResponse({ ...user, account_class: "owner" }, withPassword),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...user, account_class: null }, withPassword),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { ...user, account_class: "Owner authority" },
          withPassword,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...user, settings_access: undefined }, withPassword),
      )
      .mockResolvedValueOnce(jsonResponse(user))
      .mockResolvedValueOnce(
        jsonResponse(user, { one_time_password: { value: "" } }),
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
    ).resolves.toEqual({ account: user, one_time_password: oneTimePassword });
    const init: unknown = fetchImplementation.mock.calls[0]?.[1];
    if (typeof init !== "object" || init === null || !("body" in init)) {
      throw new Error("request initialization is missing");
    }
    expect(init.body).toBe(JSON.stringify(newUser));
    await expect(
      accessAdministrationApi.createUser("property-1", newUser),
    ).resolves.toEqual({
      account: { ...user, account_class: "owner" },
      one_time_password: oneTimePassword,
    });
    await expect(
      accessAdministrationApi.createUser("property-1", newUser),
    ).resolves.toEqual({
      account: { ...user, account_class: null },
      one_time_password: oneTimePassword,
    });
    // Two wrong accounts, then a new account without its one-time password or with an empty one.
    for (let attempt = 0; attempt < 4; attempt += 1) {
      await expect(
        accessAdministrationApi.createUser("property-1", newUser),
      ).rejects.toEqual(new AdministrationError());
    }
  });

  it("TEST-FE-ADMIN-006 resets an account without a typed password and reads its one-time password", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const result = {
      user_id: "user-1",
      password_changed: true,
      mfa_reset: false,
      sessions_revoked: 1,
    };
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({ ...result, one_time_password: oneTimePassword }),
      )
      .mockResolvedValueOnce(jsonResponse(result));
    vi.stubGlobal("fetch", fetchImplementation);
    const request = { reset_mfa: false, reason: "Forgot the password" };

    await expect(
      accessAdministrationApi.administrativelyRecoverUser("user-1", request),
    ).resolves.toEqual({ ...result, one_time_password: oneTimePassword });
    const init: unknown = fetchImplementation.mock.calls[0]?.[1];
    if (typeof init !== "object" || init === null || !("body" in init)) {
      throw new Error("request initialization is missing");
    }
    expect(init.body).toBe(JSON.stringify(request));
    await expect(
      accessAdministrationApi.administrativelyRecoverUser("user-1", request),
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
