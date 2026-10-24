import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AUTHENTICATION_ERROR_MESSAGE,
  AuthenticationError,
  PasswordRuleError,
  SessionExpiredError,
  beginMfaEnrollment,
  changePassword,
  completeMfa,
  inspectSession,
  issueRecoveryCodes,
  logout,
  regenerateRecoveryCodes,
  signIn,
} from "./authClient";

afterEach(() => {
  vi.restoreAllMocks();
});

const authenticatedResponse = {
  data: {
    phase: "authenticated",
    session: {
      actor_id: "actor-1",
      authenticated_at: "2026-08-22T10:00:00Z",
      last_activity_at: "2026-08-22T10:00:00Z",
      idle_expires_at: "2026-08-22T10:30:00Z",
      absolute_expires_at: "2026-08-23T10:00:00Z",
      mfa_assurance: "none",
      reauthenticated_at: null,
    },
  },
  meta: { request_id: "request-1" },
};

describe("local authentication client", () => {
  it("TEST-FE-AUTH-001 sends the local credentials contract with browser cookies", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(authenticatedResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      signIn(
        { username: "local-user", password: "correct horse" },
        fetchImplementation,
      ),
    ).resolves.toEqual(authenticatedResponse.data);

    expect(fetchImplementation).toHaveBeenCalledWith("/api/v1/auth/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "local-user",
        password: "correct horse",
      }),
    });
  });

  it.each([401, 403, 429, 500])(
    "TEST-FE-AUTH-002 maps HTTP %s to the same enumeration-safe error",
    async (status) => {
      const fetchImplementation = vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response(null, { status }));

      await expect(
        signIn({ username: "unknown", password: "wrong" }, fetchImplementation),
      ).rejects.toEqual(new AuthenticationError());
      await expect(
        signIn({ username: "unknown", password: "wrong" }, fetchImplementation),
      ).rejects.toThrow(AUTHENTICATION_ERROR_MESSAGE);
    },
  );

  it("TEST-FE-AUTH-003 uses the generic error for network and malformed responses", async () => {
    const networkFailure = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new Error("private network detail"));
    const malformedResponse = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ data: { phase: "other" } })),
      );
    const missingMetadata = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: authenticatedResponse.data,
        }),
      ),
    );

    await expect(
      signIn({ username: "user", password: "password" }, networkFailure),
    ).rejects.toThrow(AUTHENTICATION_ERROR_MESSAGE);
    await expect(
      signIn({ username: "user", password: "password" }, malformedResponse),
    ).rejects.toThrow(AUTHENTICATION_ERROR_MESSAGE);
    await expect(
      signIn({ username: "user", password: "password" }, missingMetadata),
    ).rejects.toThrow(AUTHENTICATION_ERROR_MESSAGE);
  });

  it("TEST-FE-AUTH-004 accepts pre-authentication phases without exposing secrets", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { phase: "mfa_required", session: null },
          meta: { request_id: "request-2" },
        }),
      ),
    );

    await expect(
      signIn({ username: "user", password: "password" }, fetchImplementation),
    ).resolves.toEqual({ phase: "mfa_required", session: null });
  });

  it("TEST-FE-AUTH-005 sends MFA challenges with cookie credentials and the matching CSRF header", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(authenticatedResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await completeMfa(
      { method: "recovery_code", code: "single-use" },
      fetchImplementation,
    );
    expect(fetchImplementation).toHaveBeenCalledWith(
      "/api/v1/auth/mfa/challenge",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "csrf-token",
        },
        body: JSON.stringify({
          method: "recovery_code",
          code: "single-use",
        }),
      }),
    );
  });

  it("TEST-FE-AUTH-006 validates one-time enrollment material before exposing it", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const invalid = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { method: "totp", provisioning_uri: "https://not-secret-safe" },
          meta: { request_id: "request" },
        }),
      ),
    );
    await expect(beginMfaEnrollment(invalid)).rejects.toEqual(
      new AuthenticationError(),
    );
  });

  it("TEST-FE-AUTH-007 classifies an unauthorized session inspection as expiry", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 401 }));
    await expect(inspectSession(fetchImplementation)).rejects.toEqual(
      new SessionExpiredError(),
    );
  });

  it("TEST-FE-AUTH-008 clears local session state when logout reports an already-expired session", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 401 }));
    await expect(logout(fetchImplementation)).resolves.toBeUndefined();
  });

  it("TEST-FE-AUTH-009 accepts only bounded unique one-time recovery-code material", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const valid = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { set_id: "set-1", codes: ["one", "two"] },
          meta: { request_id: "request" },
        }),
      ),
    );
    await expect(issueRecoveryCodes(valid)).resolves.toEqual({
      set_id: "set-1",
      codes: ["one", "two"],
    });

    const duplicate = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { set_id: "set-1", codes: ["same", "same"] },
          meta: { request_id: "request" },
        }),
      ),
    );
    await expect(issueRecoveryCodes(duplicate)).rejects.toEqual(
      new AuthenticationError(),
    );
  });

  it("TEST-FE-AUTH-010 binds recovery-code replacement to the exact prior set and CSRF", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { set_id: "set-2", codes: ["replacement"] },
          meta: { request_id: "request" },
        }),
      ),
    );
    await regenerateRecoveryCodes("set-1", fetchImplementation);
    expect(fetchImplementation).toHaveBeenCalledWith(
      "/api/v1/auth/recovery-codes/regenerate",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "csrf-token",
        },
        body: JSON.stringify({ prior_set_id: "set-1" }),
      }),
    );
  });

  it("TEST-FE-AUTH-011 changes a one-time password and tells a rule refusal from others", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        json({
          data: { phase: "mfa_required", session: null },
          meta: { request_id: "request" },
        }),
      )
      .mockResolvedValueOnce(
        json(
          { error: { code: "PASSWORD_RULE", fields: ["new_password"] } },
          422,
        ),
      )
      .mockResolvedValueOnce(json({ error: { code: "VALIDATION_ERROR" } }, 422))
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(
        json({
          data: { phase: "password_change_required", session: null },
          meta: { request_id: "request" },
        }),
      );

    await expect(
      changePassword("a long new password of mine", fetchImplementation),
    ).resolves.toEqual({ phase: "mfa_required", session: null });
    expect(fetchImplementation).toHaveBeenCalledWith(
      "/api/v1/auth/password-change",
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "csrf-token",
        },
        body: JSON.stringify({ new_password: "a long new password of mine" }),
      },
    );
    await expect(
      changePassword("password1234567", fetchImplementation),
    ).rejects.toBeInstanceOf(PasswordRuleError);
    const other = changePassword("x", fetchImplementation);
    await expect(other).rejects.toBeInstanceOf(AuthenticationError);
    await expect(other).rejects.not.toBeInstanceOf(PasswordRuleError);
    await expect(
      changePassword("a long new password of mine", fetchImplementation),
    ).rejects.toBeInstanceOf(SessionExpiredError);
    // The phase is read like any sign-in answer; the server never answers this one (503).
    await expect(
      changePassword("a long new password of mine", fetchImplementation),
    ).resolves.toEqual({ phase: "password_change_required", session: null });
  });
});
