import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AUTHENTICATION_ERROR_MESSAGE,
  AuthenticationError,
  PasswordRuleError,
  RateLimitedError,
  ServiceUnavailableError,
  SessionExpiredError,
  beginMfaEnrollment,
  changePassword,
  completeMfa,
  inspectSession,
  issueRecoveryCodes,
  liveRecoveryCodeSet,
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
      ).rejects.toBeInstanceOf(AuthenticationError);
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
  it("TEST-FE-AUTH-012 tells a wait with its seconds and an unreachable server from a refusal", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const waiting = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(null, { status: 429, headers: { "Retry-After": "290" } }),
      );
    const waitingWithoutSeconds = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 429 }));
    const unreachable = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new Error("private network detail"));
    const failing = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 503 }));
    const refused = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 401 }));

    const wait = await signIn(
      { username: "user", password: "password" },
      waiting,
    ).catch((error: unknown) => error);
    expect(wait).toBeInstanceOf(RateLimitedError);
    expect((wait as RateLimitedError).retryAfterSeconds).toBe(290);
    const codeWait = await completeMfa(
      { method: "totp", code: "123456" },
      waitingWithoutSeconds,
    ).catch((error: unknown) => error);
    expect(codeWait).toBeInstanceOf(RateLimitedError);
    expect((codeWait as RateLimitedError).retryAfterSeconds).toBe(60);
    await expect(
      signIn({ username: "user", password: "password" }, unreachable),
    ).rejects.toBeInstanceOf(ServiceUnavailableError);
    await expect(
      signIn({ username: "user", password: "password" }, failing),
    ).rejects.toBeInstanceOf(ServiceUnavailableError);
    const wrong = await signIn(
      { username: "user", password: "password" },
      refused,
    ).catch((error: unknown) => error);
    expect(wrong).toBeInstanceOf(AuthenticationError);
    expect(wrong).not.toBeInstanceOf(RateLimitedError);
    expect(wrong).not.toBeInstanceOf(ServiceUnavailableError);
  });

  it("TEST-FE-AUTH-013 accepts a set-up picture only when it starts as an SVG, and the display name", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "__Host-prm_csrf=csrf-token",
    );
    const material = {
      method: "totp",
      provisioning_uri: "otpauth://totp/CHETANA:sokha?secret=JBSWY3DPEHPK3PXP",
      qr_code_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
    };
    const enrollment = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ data: material, meta: { request_id: "request" } }),
        ),
      );
    await expect(beginMfaEnrollment(enrollment)).resolves.toEqual(material);
    const noPicture = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { ...material, qr_code_svg: "<script></script>" },
          meta: { request_id: "request" },
        }),
      ),
    );
    await expect(beginMfaEnrollment(noPicture)).rejects.toBeInstanceOf(
      AuthenticationError,
    );

    const named = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: {
            ...authenticatedResponse.data.session,
            display_name: "Sokha Chan",
          },
          meta: { request_id: "request" },
        }),
      ),
    );
    await expect(inspectSession(named)).resolves.toMatchObject({
      display_name: "Sokha Chan",
    });
    const badName = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { ...authenticatedResponse.data.session, display_name: 7 },
          meta: { request_id: "request" },
        }),
      ),
    );
    await expect(inspectSession(badName)).rejects.toBeInstanceOf(
      AuthenticationError,
    );
  });

  it("TEST-FE-AUTH-014 reads the live recovery-code set or none, refusing any other shape", async () => {
    const summary = {
      set_id: "11111111-1111-4111-8111-111111111111",
      created_at: "2026-10-24T09:00:00Z",
      made_by: "issued",
      usable_count: 9,
    };
    const answer = (data: unknown) =>
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          new Response(JSON.stringify({ data, meta: { request_id: "r" } })),
        );
    const live = answer(summary);
    await expect(liveRecoveryCodeSet(live)).resolves.toEqual(summary);
    expect(live).toHaveBeenCalledWith("/api/v1/auth/recovery-codes", {
      method: "GET",
      credentials: "include",
    });
    await expect(liveRecoveryCodeSet(answer(null))).resolves.toBeNull();
    for (const bad of [
      { ...summary, made_by: "guessed" },
      { ...summary, usable_count: 1.5 },
      { ...summary, created_at: "not a time" },
      { ...summary, codes: undefined, set_id: 7 },
    ]) {
      await expect(liveRecoveryCodeSet(answer(bad))).rejects.toBeInstanceOf(
        AuthenticationError,
      );
    }
  });
});
