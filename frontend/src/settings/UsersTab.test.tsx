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
  AdministrationRefusedError,
  AdministrationUnavailableError,
  ReauthenticationRequiredError,
  type UserAccount,
} from "../adminClient";
import { AuthenticationError, RateLimitedError } from "../authClient";
import { UsersTab } from "./UsersTab";

afterEach(() => {
  cleanup();
});

function account(name: string, extra: Partial<UserAccount> = {}): UserAccount {
  return {
    user_id: `user-${name}`,
    property_id: "property-1",
    username: name.toLowerCase(),
    display_name: name,
    audit_name: name,
    lifecycle_state: "active",
    mfa_policy_class: "optional",
    version: 1,
    account_class: "staff",
    settings_access: false,
    ...extra,
  };
}

const OWNER = account("Sok", {
  user_id: "owner-1",
  account_class: "owner",
  mfa_policy_class: "required",
});
const MANAGER = account("Dara", {
  account_class: "manager",
  mfa_policy_class: "required",
  settings_access: true,
});
const STAFF = account("Vanna");
const GONE = account("Rith", { lifecycle_state: "disabled" });
const USERS = [OWNER, MANAGER, STAFF, GONE];

const PASSWORD = {
  value: "river-mango-lotus-44",
  expires_at: "2026-11-04T03:00:00Z",
};

function apiOf(
  users: () => Promise<UserAccount[]> = () => Promise.resolve(USERS),
) {
  return {
    load: vi.fn(() =>
      users().then((list) => ({
        users: list,
        capabilities: [],
        roleBundles: [],
        authorizationHistory: [],
      })),
    ),
    createUser: vi.fn(() =>
      Promise.resolve({
        account: account("Mony"),
        one_time_password: PASSWORD,
      }),
    ),
    disableUser: vi.fn((user: UserAccount) =>
      Promise.resolve({ ...user, lifecycle_state: "disabled" as const }),
    ),
    revokeSessions: vi.fn((userId: string) => Promise.resolve(userId ? 1 : 0)),
    administrativelyRecoverUser: vi.fn(() =>
      Promise.resolve({
        user_id: "user-Dara",
        password_changed: true,
        mfa_reset: true,
        sessions_revoked: 2,
        one_time_password: PASSWORD,
      }),
    ),
    giveSettingsAccess: vi.fn((userId: string) =>
      Promise.resolve({ ...STAFF, user_id: userId, settings_access: true }),
    ),
    removeSettingsAccess: vi.fn((userId: string) =>
      Promise.resolve({ ...MANAGER, user_id: userId, settings_access: false }),
    ),
  };
}

function show(
  api = apiOf(),
  {
    language = "en" as "en" | "km",
    reauthenticate = vi.fn(() => Promise.resolve()),
  } = {},
) {
  render(
    <UsersTab
      active
      api={api}
      language={language}
      myUserId="owner-1"
      propertyId="property-1"
      reauthenticate={reauthenticate}
    />,
  );
  return { api, reauthenticate };
}

const row = (name: string) => {
  const cell = screen.getByText(name, { selector: "b" });
  const found = cell.closest("tr");
  if (found === null) throw new Error(`no row for ${name}`);
  return found;
};

describe("Settings: Users and sign-in", () => {
  it("TEST-FE-944 lists each user with role, MFA, Settings access and state; only active users who are not the Owner get Reset and Disable; End all sessions leaves the Owner signed in; the role table and sign-in rules show", async () => {
    const { api } = show();
    const users = await screen.findByRole("region", { name: "Users" });
    expect(api.load).toHaveBeenCalledWith("property-1");
    expect(
      Array.from(users.querySelectorAll("th")).map((th) => th.textContent),
    ).toEqual([
      "Name",
      "Role",
      "MFA",
      "Can change settings",
      "State",
      "Sign-in help",
    ]);
    const cells = (name: string) =>
      Array.from(row(name).querySelectorAll("td")).map((td) => td.textContent);
    expect(cells("Sok")).toEqual([
      "Soksok",
      "Owner",
      "Needed",
      "Yes",
      "Active",
      "—",
    ]);
    expect(cells("Dara").slice(0, 5)).toEqual([
      "Daradara",
      "Manager",
      "Needed",
      "Yes",
      "Active",
    ]);
    expect(cells("Vanna").slice(1, 5)).toEqual([
      "Staff",
      "Not needed",
      "—No",
      "Active",
    ]);
    expect(cells("Rith")).toEqual([
      "Rithrith",
      "Staff",
      "Not needed",
      "—No",
      "Disabled",
      "—",
    ]);
    expect(
      within(row("Vanna")).getByRole("button", { name: "Reset: Vanna" }),
    ).toBeTruthy();
    expect(
      within(row("Vanna")).getByRole("button", { name: "Disable: Vanna" }),
    ).toBeTruthy();
    expect(users.textContent).toContain(
      "Only the Owner sees and changes this tab.",
    );

    const roles = screen.getByRole("region", { name: "What each role can do" });
    expect(roles.textContent).toContain("Business settings, users and roles");
    expect(within(roles).getAllByText("If the Owner allows")).toHaveLength(2);
    const rules = screen.getByRole("region", { name: "Sign-in rules" });
    expect(within(rules).getAllByRole("listitem")).toHaveLength(5);

    fireEvent.click(screen.getByRole("button", { name: "End all sessions" }));
    const dialog = screen.getByRole("dialog", { name: "End all sessions" });
    expect(dialog.textContent).toContain(
      "Everyone except you is signed out now.",
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "End all sessions" }),
    );
    expect(
      await screen.findByText("Everyone else is signed out."),
    ).toBeTruthy();
    expect(api.revokeSessions.mock.calls.map(([id]) => id)).toEqual([
      "user-Dara",
      "user-Vanna",
    ]);
    expect(api.load).toHaveBeenCalledTimes(2);
  });

  it("TEST-FE-945 Add user checks the name and username, makes a Staff or Manager and shows the one-time password once; Reset asks what and why, then shows the one-time password", async () => {
    const { api } = show();
    fireEvent.click(await screen.findByRole("button", { name: "Add user" }));
    let dialog = screen.getByRole("dialog", { name: "Add user" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Enter a name.")).toBeTruthy();
    expect(within(dialog).getByText("Type a username.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Name/), {
      target: { value: " Mony " },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Username/), {
      target: { value: "DARA" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("DARA already exists.")).toBeTruthy();
    expect(
      Array.from(
        within(dialog).getByLabelText<HTMLSelectElement>("Role").options,
      ).map((option) => option.textContent),
    ).toEqual(["Staff", "Manager"]);
    fireEvent.change(within(dialog).getByLabelText(/^Username/), {
      target: { value: "mony" },
    });
    fireEvent.change(within(dialog).getByLabelText("Role"), {
      target: { value: "manager" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    dialog = await screen.findByRole("dialog", {
      name: "One-time password for Mony",
    });
    expect(api.createUser).toHaveBeenCalledWith("property-1", {
      username: "mony",
      display_name: "Mony",
      audit_name: "Mony",
      account_class: "manager",
    });
    expect(dialog.textContent).toContain("river-mango-lotus-44");
    expect(dialog.textContent).toContain("Give it to Mony in person.");
    expect(dialog.textContent).toContain("Works until 04/11/2026 10:00.");
    expect(screen.getByText("Mony added.")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(screen.queryByText("river-mango-lotus-44")).toBeNull();

    // Staff with MFA not needed are offered only the password.
    fireEvent.click(screen.getByRole("button", { name: "Reset: Vanna" }));
    dialog = screen.getByRole("dialog", { name: "Reset sign-in for Vanna" });
    expect(within(dialog).getAllByRole("radio")).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "Reset: Dara" }));
    dialog = screen.getByRole("dialog", { name: "Reset sign-in for Dara" });
    expect(dialog.textContent).toContain(
      "Dara is signed out everywhere at once. This is written to History.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset now" }));
    expect(within(dialog).getByText("Choose what to reset.")).toBeTruthy();
    expect(within(dialog).getByText("Choose a reason.")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("radio", { name: /Two-step/ }));
    fireEvent.change(within(dialog).getByLabelText("Reason"), {
      target: { value: "ur_r_other" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset now" }));
    expect(within(dialog).getByText("Write what happened.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Note"), {
      target: { value: "new phone at reception" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset now" }));
    await screen.findByRole("dialog", { name: "One-time password for Dara" });
    expect(api.administrativelyRecoverUser).toHaveBeenCalledWith("user-Dara", {
      reset_mfa: true,
      reason: "Other: new phone at reception",
    });
  });

  it("TEST-FE-946 an action that needs the password and code again asks for them, then runs once more; a refusal names the user; a changed account reads the list again", async () => {
    const api = apiOf();
    api.removeSettingsAccess.mockRejectedValueOnce(
      new ReauthenticationRequiredError(),
    );
    api.giveSettingsAccess.mockRejectedValueOnce(
      new AdministrationRefusedError(
        409,
        "SIGN_IN_CODE_REQUIRED",
        "A Staff account gets Settings access only after it has set up its sign-in code.",
      ),
    );
    const reauthenticate = vi
      .fn()
      .mockRejectedValueOnce(new AuthenticationError())
      .mockRejectedValueOnce(new RateLimitedError(280))
      .mockResolvedValue(undefined);
    show(api, { reauthenticate });
    fireEvent.click(
      await screen.findByRole("button", { name: "Settings access" }),
    );
    let dialog = screen.getByRole("dialog", {
      name: "Who can change settings",
    });
    const boxes = within(dialog).getAllByRole("checkbox");
    // The Owner always can; the disabled user is not listed.
    expect(boxes.map((box) => (box as HTMLInputElement).checked)).toEqual([
      true,
      true,
      false,
    ]);
    expect((boxes[0] as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Nothing was changed.")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Vanna/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Dara/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Write the reason.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Night shift" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    dialog = await screen.findByRole("dialog", { name: "Confirm it is you" });
    expect(api.giveSettingsAccess).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).getByText("Type your password.")).toBeTruthy();
    expect(
      within(dialog).getByText("Type the 6 digits from your phone."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Your password"), {
      target: { value: "my blue door opens" },
    });
    fireEvent.change(within(dialog).getByLabelText("6-digit code"), {
      target: { value: "123 456" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(
      await within(dialog).findByText(
        "The password or code is not right, or you were signed out. Check both and try again.",
      ),
    ).toBeTruthy();
    expect(reauthenticate).toHaveBeenCalledWith({
      password: "my blue door opens",
      second_factor: { method: "totp", code: "123456" },
    });
    fireEvent.change(within(dialog).getByLabelText("6-digit code"), {
      target: { value: "654321" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(
      await within(dialog).findByText(
        "Too many tries. Wait 5 minutes, then try again.",
      ),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("6-digit code"), {
      target: { value: "111222" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(
      await screen.findByText(
        "Vanna: a Staff account gets Settings access only after it has set up its sign-in code.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.removeSettingsAccess).toHaveBeenCalledTimes(2);
    expect(api.removeSettingsAccess).toHaveBeenLastCalledWith(
      "user-Dara",
      "Night shift",
    );
    expect(api.giveSettingsAccess).toHaveBeenCalledWith(
      "user-Vanna",
      "Night shift",
    );

    // Cancelling the question changes nothing.
    api.disableUser.mockRejectedValueOnce(new ReauthenticationRequiredError());
    fireEvent.click(screen.getByRole("button", { name: "Disable: Vanna" }));
    dialog = screen.getByRole("dialog", { name: "Disable Vanna" });
    expect(dialog.textContent).toContain(
      "Vanna is signed out at once and can no longer sign in. Nothing is deleted.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Disable" }));
    dialog = await screen.findByRole("dialog", { name: "Confirm it is you" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Nothing was changed.")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();

    // An account changed by someone else: the form closes and the list is read again.
    api.disableUser.mockRejectedValueOnce(
      new AdministrationRefusedError(
        412,
        "STALE_VERSION",
        "The record changed since it was read. Reload it.",
      ),
    );
    const reads = api.load.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Disable: Vanna" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Disable",
      }),
    );
    expect(
      await screen.findByText(
        "Someone changed this account. The list was read again; check and try again.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => {
      expect(api.load).toHaveBeenCalledTimes(reads + 1);
    });

    // Another refusal stays in the form with the server's English words.
    api.disableUser.mockRejectedValueOnce(
      new AdministrationRefusedError(
        409,
        "ACCOUNT_DISABLED",
        "A disabled account cannot be changed.",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Disable: Vanna" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Disable",
      }),
    );
    const said = await screen.findByText(
      "A disabled account cannot be changed.",
    );
    expect(said.getAttribute("lang")).toBe("en");
    expect(screen.getByRole("dialog").textContent).toContain(
      "Not done. The server said:",
    );
  });

  it("TEST-FE-947 Khmer words come from the mock-up; a failed read offers Retry; without the right the tab says so", async () => {
    show(apiOf(), { language: "km" });
    expect(
      await screen.findByRole("region", { name: "អ្នកប្រើ" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "បន្ថែមអ្នកប្រើ" })).toBeTruthy();
    expect(screen.getByText("ច្បាប់ចូល")).toBeTruthy();
    cleanup();

    let fail = true;
    const flaky = apiOf(() =>
      fail ? Promise.reject(new Error("down")) : Promise.resolve(USERS),
    );
    show(flaky);
    const retry = await screen.findByRole("button", { name: "Retry" });
    fail = false;
    fireEvent.click(retry);
    expect(await screen.findByRole("region", { name: "Users" })).toBeTruthy();
    cleanup();

    show(apiOf(() => Promise.reject(new AdministrationUnavailableError())));
    expect(
      await screen.findByText("Your account cannot open this tab."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("TEST-FE-949 after the password and code, a refused form keeps what was typed; a run stopped part-way does the rest only; a one-time password still shows after the Property changed", async () => {
    const api = apiOf();
    api.createUser
      .mockRejectedValueOnce(new ReauthenticationRequiredError())
      .mockRejectedValueOnce(
        new AdministrationRefusedError(
          409,
          "USERNAME_TAKEN",
          "Another account already has this username.",
        ),
      );
    show(api);
    fireEvent.click(await screen.findByRole("button", { name: "Add user" }));
    let dialog = screen.getByRole("dialog", { name: "Add user" });
    fireEvent.change(within(dialog).getByLabelText(/^Name/), {
      target: { value: "Mony" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Username/), {
      target: { value: "mony" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    dialog = await screen.findByRole("dialog", { name: "Confirm it is you" });
    fireEvent.change(within(dialog).getByLabelText("Your password"), {
      target: { value: "my blue door opens" },
    });
    fireEvent.change(within(dialog).getByLabelText("6-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(
      await screen.findByText("Another account already has this username."),
    ).toBeTruthy();
    dialog = screen.getByRole("dialog", { name: "Add user" });
    expect(within(dialog).getByLabelText<HTMLInputElement>(/^Name/).value).toBe(
      "Mony",
    );
    expect(
      within(dialog).getByLabelText<HTMLInputElement>(/^Username/).value,
    ).toBe("mony");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    // Dara's access is removed; then the server asks again before Vanna's is given.
    api.giveSettingsAccess.mockRejectedValueOnce(
      new ReauthenticationRequiredError(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Settings access" }));
    dialog = screen.getByRole("dialog", { name: "Who can change settings" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Vanna/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Dara/ }));
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Night shift" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    dialog = await screen.findByRole("dialog", { name: "Confirm it is you" });
    fireEvent.change(within(dialog).getByLabelText("Your password"), {
      target: { value: "my blue door opens" },
    });
    fireEvent.change(within(dialog).getByLabelText("6-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Saved.")).toBeTruthy();
    expect(api.removeSettingsAccess).toHaveBeenCalledTimes(1);
    expect(api.giveSettingsAccess).toHaveBeenCalledTimes(2);
    cleanup();

    // The Property changes while a reset is on its way: its password is still shown.
    let answer: (
      value: Awaited<
        ReturnType<ReturnType<typeof apiOf>["administrativelyRecoverUser"]>
      >,
    ) => void = () => undefined;
    const slow = apiOf();
    slow.administrativelyRecoverUser.mockReturnValueOnce(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    const props = {
      active: true,
      api: slow,
      language: "en" as const,
      myUserId: "owner-1",
      reauthenticate: vi.fn(() => Promise.resolve()),
    };
    const { rerender } = render(
      <UsersTab {...props} propertyId="property-1" />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Reset: Vanna" }),
    );
    dialog = screen.getByRole("dialog", { name: "Reset sign-in for Vanna" });
    fireEvent.click(within(dialog).getByRole("radio", { name: /Password/ }));
    fireEvent.change(within(dialog).getByLabelText("Reason"), {
      target: { value: "ur_r_forgot" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset now" }));
    rerender(<UsersTab {...props} propertyId="property-2" />);
    answer({
      user_id: "user-Vanna",
      password_changed: true,
      mfa_reset: false,
      sessions_revoked: 0,
      one_time_password: PASSWORD,
    });
    expect(
      await screen.findByRole("dialog", {
        name: "One-time password for Vanna",
      }),
    ).toBeTruthy();
  });
});
