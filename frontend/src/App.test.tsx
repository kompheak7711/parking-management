import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { AccessAdministrationApi, UserAccount } from "./adminClient";
import {
  AUTHENTICATION_ERROR_MESSAGE,
  AuthenticationApi,
  SessionData,
} from "./authClient";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const session: SessionData = {
  actor_id: "actor-1",
  authenticated_at: "2026-08-22T10:00:00Z",
  last_activity_at: "2026-08-22T10:00:00Z",
  idle_expires_at: "2026-08-22T10:30:00Z",
  absolute_expires_at: "2026-08-23T10:00:00Z",
  mfa_assurance: "totp",
  reauthenticated_at: "2026-08-22T10:05:00Z",
};

function mockAuthenticationApi(
  overrides: Partial<AuthenticationApi> = {},
): AuthenticationApi {
  return {
    signIn: vi.fn().mockResolvedValue({ phase: "authenticated", session }),
    completeMfa: vi.fn().mockResolvedValue({ phase: "authenticated", session }),
    beginMfaEnrollment: vi.fn().mockResolvedValue({
      method: "totp",
      provisioning_uri: "otpauth://totp/PropertyRental:test?secret=protected",
    }),
    confirmMfaEnrollment: vi
      .fn()
      .mockResolvedValue({ phase: "authenticated", session }),
    inspectSession: vi.fn().mockResolvedValue(session),
    reauthenticate: vi.fn().mockResolvedValue(session),
    issueRecoveryCodes: vi.fn().mockResolvedValue({
      set_id: "set-1",
      codes: ["code-one", "code-two"],
    }),
    regenerateRecoveryCodes: vi.fn().mockResolvedValue({
      set_id: "set-2",
      codes: ["replacement-one", "replacement-two"],
    }),
    logout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("local sign-in", () => {
  it("TEST-FE-001 renders an accessible local username and password form", () => {
    render(<App environment="development" buildId="test-build" />);

    expect(
      screen.getByRole("heading", { name: "Property Rental Management" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAccessibleName("Sign in");
    expect(screen.getByLabelText("Username")).toHaveAttribute(
      "autocomplete",
      "username",
    );
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute(
      "type",
      "submit",
    );
  });

  it("TEST-FE-002 shows safe support metadata outside production", () => {
    render(<App environment="development" buildId="test-build" />);

    expect(screen.getByText("development")).toBeInTheDocument();
    expect(screen.getByText("Build test-build")).toBeInTheDocument();
  });

  it("TEST-FE-003 does not show the environment indicator in production", () => {
    render(<App environment="production" buildId="release-1" />);

    expect(screen.queryByText("production")).not.toBeInTheDocument();
    expect(screen.getByText("Build release-1")).toBeInTheDocument();
  });

  it("TEST-FE-004 submits the labeled controls through the semantic form", async () => {
    const authenticate = vi.fn().mockResolvedValue({
      phase: "authenticated",
      session: null,
    });
    render(
      <App
        environment="development"
        buildId="test-build"
        authenticate={authenticate}
      />,
    );

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "local-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "local-password" },
    });
    const form = screen
      .getByRole("button", { name: "Sign in" })
      .closest("form");
    expect(form).not.toBeNull();
    if (form === null) {
      throw new Error("sign-in form is missing");
    }
    fireEvent.submit(form);

    await waitFor(() => {
      expect(authenticate).toHaveBeenCalledWith({
        username: "local-user",
        password: "local-password",
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your sign-in was accepted.",
    );
  });

  it("TEST-FE-005 announces one generic, associated authentication failure", async () => {
    const authenticate = vi
      .fn()
      .mockRejectedValue(new Error("account disabled"));
    render(
      <App
        environment="development"
        buildId="test-build"
        authenticate={authenticate}
      />,
    );

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "possible-owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(AUTHENTICATION_ERROR_MESSAGE);
    expect(alert).not.toHaveTextContent("disabled");
    expect(screen.getByLabelText("Username")).toHaveAccessibleDescription(
      AUTHENTICATION_ERROR_MESSAGE,
    );
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      AUTHENTICATION_ERROR_MESSAGE,
    );
    expect(screen.getByLabelText("Username")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("TEST-FE-006 exposes no first-Owner, external-provider, SMS, or security-question flow", () => {
    render(<App environment="development" buildId="test-build" />);

    expect(screen.queryByText(/create first owner/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/google|microsoft|auth0/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/sms|security question/i),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Need help signing in? Contact your administrator."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-007 keeps native controls focusable in a logical keyboard order", () => {
    render(<App environment="development" buildId="test-build" />);

    const username = screen.getByLabelText("Username");
    const password = screen.getByLabelText("Password");
    const submit = screen.getByRole("button", { name: "Sign in" });
    const form = submit.closest("form");

    expect(form).not.toBeNull();
    expect(form?.querySelectorAll("input, button")).toEqual(
      expect.objectContaining({
        0: username,
        1: password,
        2: submit,
        length: 3,
      }),
    );

    for (const control of [username, password, submit]) {
      control.focus();
      expect(control).toHaveFocus();
    }
  });

  it("TEST-FE-008 allows retry after a generic failure without clearing credentials", async () => {
    const authenticate = vi
      .fn()
      .mockRejectedValueOnce(new Error("unknown account"))
      .mockResolvedValueOnce({ phase: "authenticated", session: null });
    render(
      <App
        environment="development"
        buildId="test-build"
        authenticate={authenticate}
      />,
    );

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "local-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "local-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      AUTHENTICATION_ERROR_MESSAGE,
    );
    expect(screen.getByLabelText("Username")).toHaveValue("local-user");
    expect(screen.getByLabelText("Password")).toHaveValue("local-password");

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your sign-in was accepted.",
    );
    expect(authenticate).toHaveBeenCalledTimes(2);
  });

  it("TEST-FE-009 completes TOTP or single-use recovery-code challenge without revealing account state", async () => {
    const completeMfa = vi
      .fn()
      .mockResolvedValue({ phase: "authenticated", session });
    const api = mockAuthenticationApi({
      signIn: vi
        .fn()
        .mockResolvedValue({ phase: "mfa_required", session: null }),
      completeMfa,
    });
    render(<App api={api} environment="development" buildId="test-build" />);

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "local-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "local-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", {
        name: "Complete multi-factor authentication",
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Recovery code"));
    fireEvent.change(screen.getByLabelText("Unused recovery code"), {
      target: { value: "one-time-code" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() => {
      expect(completeMfa).toHaveBeenCalledWith({
        method: "recovery_code",
        code: "one-time-code",
      });
    });
    expect(screen.queryByText(/account disabled/i)).not.toBeInTheDocument();
  });

  it("TEST-FE-010 presents enrollment material once and confirms protected TOTP enrollment", async () => {
    const api = mockAuthenticationApi({
      signIn: vi
        .fn()
        .mockResolvedValue({ phase: "mfa_enrollment_required", session: null }),
    });
    render(<App api={api} environment="development" buildId="test-build" />);
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "manager" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Begin protected enrollment" }),
    );
    expect(
      await screen.findByRole("region", {
        name: "One-time enrollment material",
      }),
    ).toHaveTextContent("otpauth://totp/");
    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm enrollment" }));
    await waitFor(() => {
      expect(api.confirmMfaEnrollment).toHaveBeenCalledWith("123456");
    });
  });

  it("TEST-FE-011 returns expired sessions to sign-in without claiming unsaved commands succeeded", async () => {
    vi.useFakeTimers();
    const api = mockAuthenticationApi();
    render(
      <App
        api={api}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:29:59Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "local-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("main")).toHaveAccessibleName("Account and access");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByRole("main")).toHaveAccessibleName("Sign in");
    expect(screen.getByRole("status")).toHaveTextContent(
      "unsaved command was not submitted",
    );
    vi.useRealTimers();
  });

  it("TEST-FE-012 exposes account commands only after server capability and recent-auth checks with explicit consequence confirmation", async () => {
    const user: UserAccount = {
      user_id: "user-1",
      property_id: "property-1",
      username: "staff-one",
      display_name: "Staff One",
      audit_name: "Staff One",
      lifecycle_state: "active",
      mfa_policy_class: "optional",
      version: 1,
    };
    const disableUser = vi.fn().mockResolvedValue({
      ...user,
      lifecycle_state: "disabled",
      version: 2,
    });
    const administrationApi: AccessAdministrationApi = {
      load: vi.fn().mockResolvedValue({
        users: [user],
        capabilities: [],
        roleBundles: [],
        authorizationHistory: [],
      }),
      createUser: vi.fn(),
      disableUser,
      revokeSessions: vi.fn(),
      createRoleBundle: vi.fn(),
      assignRoleBundle: vi.fn(),
      administrativelyRecoverUser: vi.fn(),
    };
    render(
      <App
        administrationApi={administrationApi}
        api={mockAuthenticationApi()}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(await screen.findByLabelText("Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Check administration access" }),
    );
    expect((await screen.findAllByText("Staff One")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Disable account" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "revokes every applicable session",
    );
    expect(disableUser).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm command" }));
    await waitFor(() => {
      expect(disableUser).toHaveBeenCalledWith(user);
    });
  });

  it("TEST-FE-013 presents recovery codes once and clears accessible material on acknowledgement", async () => {
    const api = mockAuthenticationApi();
    render(
      <App
        api={api}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Generate one-time recovery codes",
      }),
    );

    expect(
      await screen.findByRole("region", { name: "One-time recovery codes" }),
    ).toHaveTextContent("code-one");
    fireEvent.click(
      screen.getByRole("button", {
        name: "I saved these codes—clear them",
      }),
    );
    expect(
      screen.queryByRole("region", { name: "One-time recovery codes" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("code-one")).not.toBeInTheDocument();
  });

  it("TEST-FE-014 requires consequence confirmation before administrative recovery", async () => {
    const user: UserAccount = {
      user_id: "user-1",
      property_id: "property-1",
      username: "staff-one",
      display_name: "Staff One",
      audit_name: "Staff One",
      lifecycle_state: "active",
      mfa_policy_class: "optional",
      version: 1,
    };
    const administrativelyRecoverUser = vi.fn().mockResolvedValue({
      user_id: "user-1",
      password_changed: true,
      mfa_reset: true,
      sessions_revoked: 2,
    });
    const administrationApi: AccessAdministrationApi = {
      load: vi.fn().mockResolvedValue({
        users: [user],
        capabilities: [],
        roleBundles: [],
        authorizationHistory: [],
      }),
      createUser: vi.fn(),
      disableUser: vi.fn(),
      revokeSessions: vi.fn(),
      createRoleBundle: vi.fn(),
      assignRoleBundle: vi.fn(),
      administrativelyRecoverUser,
    };
    render(
      <App
        administrationApi={administrationApi}
        api={mockAuthenticationApi()}
        environment="development"
        buildId="test-build"
        now={() => new Date("2026-08-22T10:10:00Z").getTime()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(await screen.findByLabelText("Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Check administration access" }),
    );
    await screen.findByRole("heading", {
      name: "Owner-authorized account recovery",
    });
    fireEvent.change(
      screen.getByLabelText("New password (15–128 characters)"),
      {
        target: { value: "a sufficiently long replacement password" },
      },
    );
    fireEvent.change(screen.getByLabelText("Audit reason"), {
      target: { value: "approved recovery" },
    });
    fireEvent.click(screen.getByLabelText("Reset current MFA enrollment"));
    fireEvent.click(
      screen.getByRole("button", { name: "Review recovery consequences" }),
    );
    expect(administrativelyRecoverUser).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "revokes every applicable session",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm command" }));
    await waitFor(() => {
      expect(administrativelyRecoverUser).toHaveBeenCalledWith("user-1", {
        new_password: "a sufficiently long replacement password",
        reset_mfa: true,
        reason: "approved recovery",
      });
    });
  });

  it("TEST-FE-015 restores a valid server session after a browser refresh", async () => {
    const restoredSession = {
      ...session,
      idle_expires_at: "2099-08-22T10:30:00Z",
      absolute_expires_at: "2099-08-23T10:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            data: restoredSession,
            meta: { request_id: "restore-session" },
          }),
        ),
      ),
    );

    render(<App environment="development" buildId="test-build" />);

    expect(
      await screen.findByRole("heading", { name: "Account and access" }),
    ).toBeInTheDocument();
  });
});
