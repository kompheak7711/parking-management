import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import {
  AuthenticationApi,
  AuthenticationData,
  AuthenticationError,
  RateLimitedError,
  ServiceUnavailableError,
  SessionData,
} from "./authClient";
import { SignInEntry, SignInScreens, passwordLength } from "./SignInScreens";
import { LANGUAGE_STORAGE_KEY } from "./signInText";

// Login sub-slice L6: the sign-in screens of the owner's mock-up, with synthetic data only.

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    clear: () => {
      values.clear();
    },
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    },
    removeItem: (key) => {
      values.delete(key);
    },
    setItem: (key, value) => {
      values.set(key, value);
    },
  };
}

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: memoryStorage(),
  });
  Object.defineProperty(window, "sessionStorage", {
    configurable: true,
    value: memoryStorage(),
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.documentElement.lang = "en";
});

const session: SessionData = {
  actor_id: "actor-1",
  authenticated_at: "2026-08-22T10:00:00Z",
  last_activity_at: "2026-08-22T10:00:00Z",
  idle_expires_at: "2026-08-22T10:30:00Z",
  absolute_expires_at: "2026-08-23T10:00:00Z",
  mfa_assurance: "totp",
  reauthenticated_at: null,
  display_name: "Sokha Chan",
};

const SETUP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
const RECOVERY_CODES = ["first-recovery-code", "second-recovery-code"];

function api(overrides: Partial<AuthenticationApi> = {}): AuthenticationApi {
  return {
    signIn: vi.fn().mockResolvedValue({ phase: "authenticated", session }),
    changePassword: vi
      .fn()
      .mockResolvedValue({ phase: "authenticated", session }),
    completeMfa: vi.fn().mockResolvedValue({ phase: "authenticated", session }),
    beginMfaEnrollment: vi.fn().mockResolvedValue({
      method: "totp",
      provisioning_uri: `otpauth://totp/CHETANA:sokha?secret=${SETUP_SECRET}&issuer=CHETANA`,
      qr_code_svg:
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="M0,0h1v1h-1z"/></svg>',
    }),
    confirmMfaEnrollment: vi
      .fn()
      .mockResolvedValue({ phase: "authenticated", session }),
    inspectSession: vi.fn().mockResolvedValue(session),
    reauthenticate: vi.fn().mockResolvedValue(session),
    issueRecoveryCodes: vi
      .fn()
      .mockResolvedValue({ set_id: "set-1", codes: RECOVERY_CODES }),
    regenerateRecoveryCodes: vi.fn(),
    liveRecoveryCodeSet: vi.fn().mockResolvedValue(null),
    logout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const START = new Date("2026-08-22T10:10:00Z").getTime();

function renderScreens(
  client: AuthenticationApi,
  {
    entry = { kind: "sign_in" } as SignInEntry,
    now = () => START,
  }: { entry?: SignInEntry; now?: () => number } = {},
) {
  const onAuthenticated = vi.fn();
  render(
    <SignInScreens
      api={client}
      entry={entry}
      now={now}
      onAuthenticated={onAuthenticated}
    />,
  );
  return onAuthenticated;
}

function signIn(username = "sokha", password = "a password of mine") {
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: username },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("sign-in screens", () => {
  it("TEST-FE-686 switches every label between English and Khmer and remembers only the language", () => {
    renderScreens(api());

    expect(screen.getByRole("main")).toHaveAccessibleName("Sign in");
    expect(screen.getByLabelText("Username")).toHaveFocus();
    const english = screen.getByRole("button", { name: "EN" });
    expect(english).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "ខ្មែរ" }));

    expect(document.documentElement.lang).toBe("km");
    expect(
      screen.getByRole("heading", { name: "ចូលប្រព័ន្ធ" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("ឈ្មោះអ្នកប្រើ")).toBeInTheDocument();
    expect(screen.getByLabelText("ពាក្យសម្ងាត់")).toBeInTheDocument();
    expect(
      screen.getByText(/ម្ចាស់ អ្នកគ្រប់គ្រង និងបុគ្គលិកដែលអាចប្តូរការកំណត់/),
    ).toBeInTheDocument();
    // The app name stays in English in both languages (DESIGN.md).
    expect(screen.getByText("Residence Management")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ខ្មែរ" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("km");
    expect(window.localStorage.length).toBe(1);

    cleanup();
    renderScreens(api());
    expect(
      screen.getByRole("heading", { name: "ចូលប្រព័ន្ធ" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(
      screen.getByRole("heading", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });

  it("TEST-FE-687 shows each missing field under it, focuses the first and sends nothing", () => {
    const client = api();
    renderScreens(client);

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const username = screen.getByLabelText("Username");
    const password = screen.getByLabelText("Password");
    expect(username).toHaveAttribute("aria-invalid", "true");
    expect(username).toHaveAccessibleDescription("Type your username.");
    expect(password).toHaveAccessibleDescription("Type your password.");
    expect(username).toHaveFocus();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(client.signIn).not.toHaveBeenCalled();

    fireEvent.change(username, { target: { value: "sokha" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(password).toHaveFocus();
    expect(username).toHaveAttribute("aria-invalid", "false");
    expect(client.signIn).not.toHaveBeenCalled();
  });

  it("TEST-FE-688 shows the wait with the minutes left in both languages and keeps the button usable", async () => {
    const signInCall = vi
      .fn()
      .mockRejectedValueOnce(new RateLimitedError(290))
      .mockRejectedValueOnce(new RateLimitedError(45))
      .mockRejectedValueOnce(new RateLimitedError(600));
    renderScreens(api({ signIn: signInCall }));

    signIn();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Too many tries. Wait 5 minutes, then try again. If you forgot your password, ask the Owner.",
    );
    expect(alert).toHaveFocus();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toBeEnabled();

    signIn();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Too many tries. Wait 1 minute, then try again.",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "ខ្មែរ" }));
    fireEvent.change(screen.getByLabelText("ពាក្យសម្ងាត់"), {
      target: { value: "a password of mine" },
    });
    fireEvent.click(screen.getByRole("button", { name: "ចូលប្រព័ន្ធ" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "សាកច្រើនដងពេក។ សូមរង់ចាំ ១០ នាទី រួចសាកម្តងទៀត។",
      );
    });
    expect(signInCall).toHaveBeenCalledTimes(3);
  });

  it("TEST-FE-689 tells an unreachable server apart from wrong details without naming the account", async () => {
    const signInCall = vi
      .fn()
      .mockRejectedValueOnce(new ServiceUnavailableError())
      .mockRejectedValueOnce(new AuthenticationError());
    renderScreens(api({ signIn: signInCall }));

    signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The app could not reach the office computer. Try again.",
    );
    signIn("someone-else");
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "The username or password is not right. Check both and try again.",
      );
    });
  });

  it("TEST-FE-690 checks the sign-in code, refuses a wrong one and a wait, then opens the app", async () => {
    const completeMfa = vi
      .fn()
      .mockRejectedValueOnce(new AuthenticationError())
      .mockRejectedValueOnce(new RateLimitedError(120))
      .mockResolvedValueOnce({ phase: "authenticated", session });
    const onAuthenticated = renderScreens(
      api({
        signIn: vi
          .fn()
          .mockResolvedValue({ phase: "mfa_required", session: null }),
        completeMfa,
      }),
    );
    signIn();

    expect(
      await screen.findByRole("heading", { name: "Two-step sign-in" }),
    ).toBeInTheDocument();
    const code = screen.getByLabelText("6-digit code");
    expect(code).toHaveFocus();
    expect(code).toHaveAttribute("inputmode", "numeric");
    expect(code).toHaveAttribute("autocomplete", "one-time-code");
    expect(code).toHaveAccessibleDescription(
      "The code changes every 30 seconds.",
    );

    fireEvent.change(code, { target: { value: "12a" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(code).toHaveAccessibleDescription(
      "The code changes every 30 seconds. Type the 6 digits from your phone.",
    );
    expect(completeMfa).not.toHaveBeenCalled();

    fireEvent.change(code, { target: { value: "123 456" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That code is not right. Type the newest code from your phone.",
    );
    expect(screen.getByLabelText("6-digit code")).toHaveValue("");

    fireEvent.change(screen.getByLabelText("6-digit code"), {
      target: { value: "654321" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Too many tries. Wait 2 minutes, then try again.",
      );
    });

    fireEvent.change(screen.getByLabelText("6-digit code"), {
      target: { value: "246810" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => {
      expect(onAuthenticated).toHaveBeenCalledWith(
        { phase: "authenticated", session },
        "Signed in as Sokha Chan.",
      );
    });
    expect(completeMfa).toHaveBeenNthCalledWith(1, {
      method: "totp",
      code: "123456",
    });
  });

  it("TEST-FE-691 sends the person back to sign in when the 5-minute code step has ended", async () => {
    let clock = START;
    renderScreens(
      api({
        signIn: vi
          .fn()
          .mockResolvedValue({ phase: "mfa_required", session: null }),
        completeMfa: vi.fn().mockRejectedValue(new AuthenticationError()),
      }),
      { now: () => clock },
    );
    signIn();
    fireEvent.change(await screen.findByLabelText("6-digit code"), {
      target: { value: "123456" },
    });
    clock = START + 5 * 60 * 1000;
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This step took too long. Sign in again to carry on.",
    );
    expect(screen.getByLabelText("Username")).toHaveValue("sokha");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("TEST-FE-692 explains the forgotten-password ways in person and sends nothing", () => {
    const client = api();
    renderScreens(client);

    fireEvent.click(
      screen.getByRole("button", { name: "Forgot your password?" }),
    );

    const heading = screen.getByRole("heading", {
      level: 1,
      name: "Forgot your password?",
    });
    expect(heading).toHaveFocus();
    expect(
      screen.getByText(/never sends passwords by email, SMS or Telegram/),
    ).toBeInTheDocument();
    const staff = screen.getByRole("region", { name: "Staff and Managers" });
    expect(staff).toHaveTextContent(/Ask the Owner/);
    const owner = screen.getByRole("region", { name: "Owner" });
    expect(owner).toHaveTextContent(/server emergency procedure/);
    expect(within(owner).queryByRole("button")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Lost only your phone? Sign in with your password, then use a recovery code.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to sign in" }));
    expect(screen.getByRole("heading", { name: "Sign in" })).toHaveFocus();
    expect(client.signIn).not.toHaveBeenCalled();
    expect(client.changePassword).not.toHaveBeenCalled();
  });

  it("TEST-FE-693 ticks the new-password rules as the person types and counts characters as the server does", async () => {
    renderScreens(
      api({
        signIn: vi.fn().mockResolvedValue({
          phase: "password_change_required",
          session: null,
        }),
      }),
    );
    signIn("sokha", "k7m2-x9qp-4hrt-w3nd");
    const first = await screen.findByLabelText("New password");
    expect(first).toHaveAttribute("autocomplete", "new-password");
    expect(
      screen.getByText(
        "You signed in with a one-time password. Choose your own password now.",
      ),
    ).toBeInTheDocument();
    const rules = within(screen.getByRole("main")).getByRole("list");
    // Review round 1: the list is not a live region, so it is not read out on every key.
    expect(rules).not.toHaveAttribute("aria-live");

    // "é" written as e plus a combining accent is one character after NFC.
    fireEvent.change(first, { target: { value: "café" } });
    expect(passwordLength("café")).toBe(4);
    expect(within(rules).getByText(/now 4/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));
    expect(first).toHaveAccessibleDescription(/Use at least 15 characters\.$/);
    expect(first).toHaveFocus();

    fireEvent.change(first, { target: { value: "x".repeat(129) } });
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));
    expect(first).toHaveAccessibleDescription(
      /Use no more than 128 characters\.$/,
    );

    fireEvent.change(first, {
      target: { value: "my blue door opens at seven" },
    });
    fireEvent.change(screen.getByLabelText("Type the new password again"), {
      target: { value: "my blue door opens at seven" },
    });
    const met = within(rules)
      .getAllByRole("listitem")
      .filter((item) => item.classList.contains("sign-in-rule-met"));
    expect(met).toHaveLength(3);
  });

  it("TEST-FE-694 sets up the sign-in code with the QR picture and key, then shows the recovery codes once", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const confirm = vi
      .fn()
      .mockRejectedValueOnce(new AuthenticationError())
      .mockResolvedValueOnce({ phase: "authenticated", session });
    const client = api({
      signIn: vi
        .fn()
        .mockResolvedValue({ phase: "mfa_enrollment_required", session: null }),
      confirmMfaEnrollment: confirm,
    });
    const onAuthenticated = renderScreens(client);
    signIn();

    expect(
      await screen.findByRole("heading", { name: "Set up two-step sign-in" }),
    ).toHaveFocus();
    expect(
      screen.getByText(
        "You must do this once before using the app. It takes about two minutes.",
      ),
    ).toBeInTheDocument();
    const picture = await screen.findByRole("img", {
      name: "QR code for your authenticator app",
    });
    expect(picture.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(
      screen.getByText("JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP"),
    ).toBeInTheDocument();
    expect(client.beginMfaEnrollment).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("6-digit code"), {
      target: { value: "111111" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That code is not right.",
    );
    fireEvent.change(screen.getByLabelText("6-digit code"), {
      target: { value: "222222" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(
      await screen.findByRole("heading", { name: "Your recovery codes" }),
    ).toHaveFocus();
    expect(screen.queryByText(/JBSW Y3DP/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: "QR code for your authenticator app" }),
    ).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Your recovery codes" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(list).toHaveTextContent("first-recovery-code");

    fireEvent.click(screen.getByRole("button", { name: "Copy codes" }));
    expect(
      await screen.findByText(
        "Codes copied. Paste them only where you keep them safe.",
      ),
    ).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(
      "first-recovery-code\nsecond-recovery-code",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Finish and open the app" }),
    );
    const kept = screen.getByLabelText(
      "I wrote these codes down and keep them safe.",
    );
    expect(kept).toHaveAccessibleDescription(
      "Tick the box to show you have kept the codes.",
    );
    expect(kept).toHaveFocus();
    expect(onAuthenticated).not.toHaveBeenCalled();
    fireEvent.click(kept);
    fireEvent.click(
      screen.getByRole("button", { name: "Finish and open the app" }),
    );
    expect(onAuthenticated).toHaveBeenCalledWith(
      { phase: "authenticated", session },
      "Signed in as Sokha Chan.",
    );
    expect(screen.queryByText("first-recovery-code")).not.toBeInTheDocument();
  });

  it("TEST-FE-695 opens the app with a reminder when the first recovery codes cannot be made", async () => {
    const onAuthenticated = renderScreens(
      api({
        signIn: vi.fn().mockResolvedValue({
          phase: "mfa_enrollment_required",
          session: null,
        }),
        issueRecoveryCodes: vi
          .fn()
          .mockRejectedValue(new AuthenticationError()),
      }),
    );
    signIn();
    fireEvent.change(await screen.findByLabelText("6-digit code"), {
      target: { value: "222222" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => {
      expect(onAuthenticated).toHaveBeenCalledWith(
        { phase: "authenticated", session },
        "Signed in as Sokha Chan. Two-step sign-in is set up, but your recovery codes were not made. Make new codes in your account soon.",
      );
    });
  });

  it("TEST-FE-696 shows the signed-out screens for no use, the day limit and a sign-out", () => {
    renderScreens(api(), { entry: { kind: "idle" } });
    expect(
      screen.getByRole("heading", { name: "You were signed out" }),
    ).toHaveFocus();
    expect(
      screen.getByText(
        "Nobody used the app on this computer for 30 minutes, so it signed you out to keep the records safe.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign in again" }));
    expect(screen.getByLabelText("Username")).toHaveFocus();
    cleanup();

    renderScreens(api(), { entry: { kind: "day" } });
    expect(
      screen.getByText(
        "You were signed in for 24 hours. Everyone signs in again at least once a day.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "ខ្មែរ" }));
    expect(
      screen.getByText(
        "អ្នកបានចូលរយៈពេល ២៤ ម៉ោង។ អ្នករាល់គ្នាចូលម្តងទៀតយ៉ាងតិចម្តងក្នុងមួយថ្ងៃ។",
      ),
    ).toBeInTheDocument();
    cleanup();

    renderScreens(api(), { entry: { kind: "sign_in", signedOut: true } });
    expect(screen.getByRole("status")).toHaveTextContent("អ្នកបានចាកចេញហើយ។");
  });

  it("TEST-FE-697 shows and hides a password with a pressed button", () => {
    renderScreens(api());
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("type", "password");
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toHaveTextContent("Show");

    fireEvent.click(toggle);
    expect(password).toHaveAttribute("type", "text");
    const hide = screen.getByRole("button", { name: "Hide password" });
    expect(hide).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(hide);
    expect(password).toHaveAttribute("type", "password");
  });

  it("TEST-FE-698 keeps passwords, codes and the set-up key out of browser storage and the address", async () => {
    const before = window.location.href;
    const onAuthenticated = renderScreens(
      api({
        signIn: vi.fn().mockResolvedValue({
          phase: "password_change_required",
          session: null,
        }),
        changePassword: vi.fn().mockResolvedValue({
          phase: "mfa_enrollment_required",
          session: null,
        }),
      }),
    );
    signIn("sokha", "k7m2-x9qp-4hrt-w3nd");
    fireEvent.change(await screen.findByLabelText("New password"), {
      target: { value: "my blue door opens at seven" },
    });
    fireEvent.change(screen.getByLabelText("Type the new password again"), {
      target: { value: "my blue door opens at seven" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));
    expect(
      await screen.findByText(
        "Password changed. You are signed out on every other computer.",
      ),
    ).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("6-digit code"), {
      target: { value: "222222" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(
      await screen.findByLabelText(
        "I wrote these codes down and keep them safe.",
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Finish and open the app" }),
    );
    expect(onAuthenticated).toHaveBeenCalled();

    expect(window.location.href).toBe(before);
    expect(window.sessionStorage.length).toBe(0);
    const kept = [...Array(window.localStorage.length).keys()].map((index) => {
      const key = window.localStorage.key(index) ?? "";
      return `${key}=${window.localStorage.getItem(key) ?? ""}`;
    });
    expect(kept.every((entry) => entry.startsWith(LANGUAGE_STORAGE_KEY))).toBe(
      true,
    );
    for (const secret of [
      "k7m2-x9qp-4hrt-w3nd",
      "my blue door opens at seven",
      "222222",
      SETUP_SECRET,
      "first-recovery-code",
    ]) {
      expect(kept.join("\n")).not.toContain(secret);
      expect(document.body.innerHTML).not.toContain(secret);
    }
  });

  it("TEST-FE-699 follows the server's order: one-time password, then the sign-in code, then the app", async () => {
    const client = api({
      signIn: vi.fn().mockResolvedValue({
        phase: "password_change_required",
        session: null,
      }),
      changePassword: vi
        .fn()
        .mockResolvedValue({ phase: "mfa_required", session: null }),
    });
    const onAuthenticated = renderScreens(client);
    signIn("sokha", "k7m2-x9qp-4hrt-w3nd");
    fireEvent.change(await screen.findByLabelText("New password"), {
      target: { value: "my blue door opens at seven" },
    });
    fireEvent.change(screen.getByLabelText("Type the new password again"), {
      target: { value: "my blue door opens at seven" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));

    expect(
      await screen.findByRole("heading", { name: "Two-step sign-in" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Password changed.");
    expect(onAuthenticated).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("6-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => {
      expect(onAuthenticated).toHaveBeenCalledTimes(1);
    });
  });

  it("TEST-FE-702 keeps typed passwords and codes out of the page's HTML while they are typed", async () => {
    renderScreens(
      api({
        signIn: vi
          .fn()
          .mockResolvedValue({ phase: "mfa_required", session: null }),
        completeMfa: vi.fn(() => new Promise<never>(() => undefined)),
      }),
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "sokha" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "k7m2-x9qp-4hrt-w3nd" },
    });
    expect(screen.getByLabelText("Password")).toHaveValue(
      "k7m2-x9qp-4hrt-w3nd",
    );
    expect(document.body.innerHTML).not.toContain("k7m2-x9qp-4hrt-w3nd");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(await screen.findByLabelText("6-digit code"), {
      target: { value: "481516" },
    });
    expect(document.body.innerHTML).not.toContain("481516");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(document.body.innerHTML).not.toContain("481516");
  });

  it("TEST-FE-703 shows that a request is running and drops its answer after Back to sign in", async () => {
    let answer!: (value: AuthenticationData) => void;
    const onAuthenticated = renderScreens(
      api({
        signIn: vi
          .fn()
          .mockResolvedValue({ phase: "mfa_required", session: null }),
        completeMfa: vi.fn(
          () =>
            new Promise<AuthenticationData>((resolve) => {
              answer = resolve;
            }),
        ),
      }),
    );
    signIn();
    fireEvent.change(await screen.findByLabelText("6-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const waiting = screen.getByRole("button", { name: "Please wait…" });
    expect(waiting).toHaveAttribute("aria-disabled", "true");
    expect(waiting.closest("form")).toHaveAttribute("aria-busy", "true");

    fireEvent.click(screen.getByRole("button", { name: "Back to sign in" }));
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute(
      "aria-disabled",
      "false",
    );
    await act(async () => {
      answer({ phase: "authenticated", session });
      await Promise.resolve();
    });
    expect(onAuthenticated).not.toHaveBeenCalled();
    expect(screen.getByRole("main")).toHaveAccessibleName("Sign in");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("TEST-FE-704 shows the QR picture is coming and sends the person back with the wait when set-up cannot start", async () => {
    let refuse!: (error: unknown) => void;
    renderScreens(
      api({
        signIn: vi.fn().mockResolvedValue({
          phase: "mfa_enrollment_required",
          session: null,
        }),
        beginMfaEnrollment: vi.fn(
          () =>
            new Promise<never>((_, reject) => {
              refuse = reject;
            }),
        ),
      }),
    );
    signIn();
    expect(
      await screen.findByText("Getting your QR code…"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("6-digit code")).not.toBeInTheDocument();
    await act(async () => {
      refuse(new RateLimitedError(120));
      await Promise.resolve();
    });
    expect(screen.getByRole("main")).toHaveAccessibleName("Sign in");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Too many tries. Wait 2 minutes, then try again.",
    );
  });

  it("TEST-FE-708 opens every code and password box empty after the step before it", async () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    renderScreens(
      api({
        signIn: vi
          .fn()
          .mockResolvedValueOnce({ phase: "mfa_required", session: null })
          .mockResolvedValueOnce({
            phase: "password_change_required",
            session: null,
          }),
        changePassword: vi.fn().mockResolvedValue({
          phase: "mfa_enrollment_required",
          session: null,
        }),
      }),
    );
    signIn("sokha.chan", "a password of mine");
    expect(await screen.findByLabelText("6-digit code")).toHaveValue("");
    // Review round 3: a code typed before a switch never reaches the next box.
    fireEvent.change(screen.getByLabelText("6-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Lost your phone? Use a recovery code",
      }),
    );
    expect(screen.getByLabelText("Recovery code")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Recovery code"), {
      target: { value: "first-recovery-code" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Use the code from my phone" }),
    );
    expect(screen.getByLabelText("6-digit code")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Back to sign in" }));
    expect(screen.getByLabelText("Username")).toHaveValue("sokha.chan");
    expect(screen.getByLabelText("Password")).toHaveValue("");

    signIn("sokha.chan", "k7m2-x9qp-4hrt-w3nd");
    expect(await screen.findByLabelText("New password")).toHaveValue("");
    expect(screen.getByLabelText("Type the new password again")).toHaveValue(
      "",
    );
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "my blue door opens at seven" },
    });
    fireEvent.change(screen.getByLabelText("Type the new password again"), {
      target: { value: "my blue door opens at seven" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByLabelText("6-digit code")).toHaveValue("");
    expect(consoleError).not.toHaveBeenCalled();
  });
});

describe("sign-in layer in the app", () => {
  it("TEST-FE-700 shows the person's name and tells the day limit from no use when the server ends the session", async () => {
    vi.useFakeTimers();
    const dayEnds: SessionData = {
      ...session,
      idle_expires_at: "2026-08-23T10:00:00Z",
      absolute_expires_at: "2026-08-23T10:00:00Z",
    };
    const client = api({
      signIn: vi
        .fn()
        .mockResolvedValueOnce({ phase: "authenticated", session })
        .mockResolvedValueOnce({ phase: "authenticated", session: dayEnds }),
      // Review round 1: the server is asked first and says the session ended.
      inspectSession: vi.fn().mockRejectedValue(new AuthenticationError()),
    });
    render(
      <App
        api={client}
        buildId="test-build"
        environment="development"
        now={() => new Date("2026-08-23T09:59:59Z").getTime()}
      />,
    );
    expect(screen.getByText("Build test-build")).toBeInTheDocument();
    signIn();
    await act(async () => {
      await Promise.resolve();
    });
    // The first session's 30 minutes without use have passed on this clock.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(
      screen.getByText(/Nobody used the app on this computer for 30 minutes/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sign in again" }));
    signIn();
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("main")).toHaveAccessibleName("Account and access");
    expect(screen.getByText("Sokha Chan")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Signed in as Sokha Chan.",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(
      screen.getByText(
        "You were signed in for 24 hours. Everyone signs in again at least once a day.",
      ),
    ).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("TEST-FE-701 signs out to the sign-in screen with the signed-out note", async () => {
    const client = api();
    render(
      <App
        api={client}
        buildId="test-build"
        environment="development"
        now={() => START}
      />,
    );
    signIn();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("You are signed out.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(client.logout).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-705 keeps the app open when the server says the session is still in use", async () => {
    vi.useFakeTimers();
    const used: SessionData = {
      ...session,
      idle_expires_at: "2026-08-22T10:40:00Z",
    };
    const client = api({
      signIn: vi.fn().mockResolvedValue({
        phase: "authenticated",
        session: { ...session, idle_expires_at: "2026-08-22T10:10:01Z" },
      }),
      inspectSession: vi.fn().mockResolvedValue(used),
    });
    render(
      <App
        api={client}
        buildId="test-build"
        environment="development"
        now={() => START}
      />,
    );
    signIn();
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(client.inspectSession).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("main")).toHaveAccessibleName("Account and access");
    expect(
      screen.queryByText(/Nobody used the app on this computer/),
    ).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("TEST-FE-709 ends the app when the server answers for another person or cannot be reached", async () => {
    vi.useFakeTimers();
    for (const answer of [
      vi.fn().mockResolvedValue({
        ...session,
        actor_id: "actor-2",
        idle_expires_at: "2026-08-22T10:40:00Z",
      }),
      vi.fn().mockRejectedValue(new ServiceUnavailableError()),
    ]) {
      const client = api({
        signIn: vi.fn().mockResolvedValue({
          phase: "authenticated",
          session: { ...session, idle_expires_at: "2026-08-22T10:10:01Z" },
        }),
        inspectSession: answer,
      });
      render(
        <App
          api={client}
          buildId="test-build"
          environment="development"
          now={() => START}
        />,
      );
      signIn();
      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByRole("main")).toHaveAccessibleName(
        "Account and access",
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(client.inspectSession).toHaveBeenCalledTimes(1);
      expect(
        screen.getByRole("heading", { name: "You were signed out" }),
      ).toBeInTheDocument();
      cleanup();
    }
    vi.useRealTimers();
  });
});
