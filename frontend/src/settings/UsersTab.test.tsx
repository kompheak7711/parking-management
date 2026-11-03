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
import { rolesApiOf } from "../test/rolesFixtures";
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
  };
}

function show(
  api = apiOf(),
  {
    language = "en" as "en" | "km",
    reauthenticate = vi.fn(() => Promise.resolve()),
    roles = rolesApiOf(),
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
      rolesApi={roles}
    />,
  );
  return { api, reauthenticate, roles };
}

const row = (name: string) => {
  const cell = screen.getByText(name, { selector: "b" });
  const found = cell.closest("tr");
  if (found === null) throw new Error(`no row for ${name}`);
  return found;
};

describe("Settings: Users and sign-in", () => {
  it("TEST-FE-944 lists each user with account type, roles, MFA and state; only active users who are not the Owner get Reset and Disable; End all sessions leaves the Owner signed in; the roles and sign-in rules show (V1.1 part 3)", async () => {
    const { api } = show();
    const users = await screen.findByRole("region", { name: "Users" });
    expect(api.load).toHaveBeenCalledWith("property-1");
    expect(
      Array.from(users.querySelectorAll("th")).map((th) => th.textContent),
    ).toEqual([
      "Name",
      "Account type",
      "Roles",
      "MFA",
      "State",
      "Sign-in help",
    ]);
    const cells = (name: string) =>
      Array.from(row(name).querySelectorAll("td")).map((td) => td.textContent);
    expect(cells("Sok")).toEqual([
      "Soksok",
      "Owner",
      "Owner Change",
      "Needed",
      "Active",
      "—",
    ]);
    expect(cells("Dara").slice(0, 5)).toEqual([
      "Daradara",
      "Manager",
      "Manager Change",
      "Needed",
      "Active",
    ]);
    expect(cells("Vanna").slice(1, 5)).toEqual([
      "Staff",
      "Staff Change",
      "Not needed",
      "Active",
    ]);
    expect(cells("Rith")).toEqual([
      "Rithrith",
      "Staff",
      "No role",
      "Not needed",
      "Disabled",
      "—",
    ]);
    expect(
      screen.queryByRole("button", { name: "Settings access" }),
    ).toBeNull();
    expect(
      within(row("Vanna")).getByRole("button", { name: "Reset: Vanna" }),
    ).toBeTruthy();
    expect(
      within(row("Vanna")).getByRole("button", { name: "Disable: Vanna" }),
    ).toBeTruthy();
    expect(users.textContent).toContain(
      "Only the Owner sees and changes this tab.",
    );

    const roles = screen.getByRole("region", { name: "Roles" });
    const roleRows = Array.from(roles.querySelectorAll("tbody tr")).map((tr) =>
      Array.from(tr.querySelectorAll("td"))
        .slice(0, 4)
        .map((td) => td.textContent),
    );
    expect(roleRows).toEqual([
      ["Owner", "1", "5 of 5", "Required"],
      ["Manager", "1", "2 of 5", "Optional"],
      ["Staff", "1", "1 of 5", "Optional"],
      ["Night desk Turned off", "0", "0 of 5", "Optional"],
    ]);
    const rules = screen.getByRole("region", { name: "Sign-in rules" });
    expect(within(rules).getAllByRole("listitem")).toHaveLength(6);
    expect(rules.textContent).toContain(
      "Two-step sign-in is needed for the Owner and for every role that can change business rules.",
    );

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
    const roles = rolesApiOf();
    roles.giveRole
      .mockRejectedValueOnce(new ReauthenticationRequiredError())
      .mockRejectedValueOnce(
        new AdministrationRefusedError(
          409,
          "SIGN_IN_CODE_REQUIRED",
          "A Staff account gets Change business rules only after it has set up its sign-in code.",
        ),
      );
    const reauthenticate = vi
      .fn()
      .mockRejectedValueOnce(new AuthenticationError())
      .mockRejectedValueOnce(new RateLimitedError(280))
      .mockResolvedValue(undefined);
    show(api, { reauthenticate, roles });
    fireEvent.click(
      await screen.findByRole("button", { name: "Roles: Vanna" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Roles for Vanna" });
    const boxes = within(dialog).getAllByRole("checkbox");
    // The Owner role is only for the Owner; a turned-off role is not offered.
    expect(
      boxes.map((box) => [
        box.parentElement?.textContent,
        (box as HTMLInputElement).checked,
      ]),
    ).toEqual([
      ["Manager", false],
      ["Staff", true],
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Nothing was changed.")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Manager/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Staff/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Write the reason.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Night shift" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    dialog = await screen.findByRole("dialog", { name: "Confirm it is you" });
    expect(roles.takeRole).not.toHaveBeenCalled();
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
        "Vanna (Manager): a Staff account gets a role that changes business rules only after it has set up its sign-in code.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(roles.giveRole).toHaveBeenCalledTimes(2);
    expect(roles.giveRole).toHaveBeenLastCalledWith(
      "user-Vanna",
      "role-manager",
    );
    expect(roles.takeRole).toHaveBeenCalledTimes(1);
    expect(roles.takeRole).toHaveBeenCalledWith(
      "user-Vanna",
      "role-staff",
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
    const { roles } = show(api);
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

    // Manager is given; then the server asks again before Staff is taken away.
    roles.takeRole.mockRejectedValueOnce(new ReauthenticationRequiredError());
    fireEvent.click(screen.getByRole("button", { name: "Roles: Vanna" }));
    dialog = screen.getByRole("dialog", { name: "Roles for Vanna" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Manager/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Staff/ }));
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
    expect(roles.giveRole).toHaveBeenCalledTimes(1);
    expect(roles.takeRole).toHaveBeenCalledTimes(2);
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
      rolesApi: rolesApiOf(),
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

  it("TEST-FE-1141 Roles: Add role checks the name and saves whole permissions; Edit shows part of a permission, keeps the Owner role's name and Users and roles locked, and a role with users cannot be turned off (V1.1 part 3, DL-120)", async () => {
    const { roles } = show();
    fireEvent.click(await screen.findByRole("button", { name: "Add role" }));
    let dialog = screen.getByRole("dialog", { name: "Add role" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Write the name in English.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "manager" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Another role already has this name."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "Cashier" },
    });
    expect(
      within(dialog)
        .getAllByRole("group")
        .map((group) => group.querySelector("legend")?.textContent),
    ).toEqual(["Operations", "Money approval", "Administration"]);
    const users = within(dialog).getByRole<HTMLInputElement>("checkbox", {
      name: /Users and roles/,
    });
    expect(users.disabled).toBe(true);
    expect(users.checked).toBe(false);
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: /Receive payment/ }),
    );
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: /Change business rules/ }),
    );
    expect(dialog.textContent).toContain(
      "A role with this needs two-step sign-in.",
    );
    // A new role cannot be turned off before it has been made.
    expect(
      within(dialog).queryByRole("checkbox", { name: /Turn this role off/ }),
    ).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Role saved: Cashier")).toBeTruthy();
    expect(roles.createRole).toHaveBeenCalledWith("property-1", {
      name: "Cashier",
      name_kh: null,
      capability_ids: [
        "payments.allocate",
        "payments.record",
        "settings.manage",
      ],
      turned_off: false,
    });
    expect(roles.load).toHaveBeenCalledTimes(2);

    // The Manager role has part of Approve money changes; ticking it gives the whole one.
    fireEvent.click(screen.getByRole("button", { name: "Edit: Manager" }));
    dialog = screen.getByRole("dialog", { name: "Edit role: Manager" });
    const approve = within(dialog).getByRole<HTMLInputElement>("checkbox", {
      name: /Approve money changes/,
    });
    expect(approve.indeterminate).toBe(true);
    expect(approve.parentElement?.textContent).toContain("Part of it");
    const off = within(dialog).getByRole<HTMLInputElement>("checkbox", {
      name: /Turn this role off/,
    });
    expect(off.disabled).toBe(true);
    expect(dialog.textContent).toContain(
      "A role with users cannot be turned off. Give them another role first.",
    );
    fireEvent.click(approve);
    fireEvent.change(within(dialog).getByLabelText(/^Name in Khmer/), {
      target: { value: "អ្នកគ្រប់គ្រងថ្មី" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Role saved: Manager");
    const [saved, change] = roles.saveRole.mock.calls[0] ?? [];
    expect(saved?.role_bundle_id).toBe("role-manager");
    expect(change).toEqual({
      name: "Manager",
      name_kh: "អ្នកគ្រប់គ្រងថ្មី",
      capability_ids: [
        "financial.approve",
        "invoices.read",
        "invoices.void",
        "payments.allocate",
        "payments.record",
      ],
      turned_off: false,
    });

    // The Owner role: its name is kept, Users and roles stays ticked, and it is never turned off.
    fireEvent.click(screen.getByRole("button", { name: "Edit: Owner" }));
    dialog = screen.getByRole("dialog", { name: "Edit role: Owner" });
    expect(
      within(dialog).getByLabelText<HTMLInputElement>(/^Name in English/)
        .disabled,
    ).toBe(true);
    const ownerUsers = within(dialog).getByRole<HTMLInputElement>("checkbox", {
      name: /Users and roles/,
    });
    expect([ownerUsers.checked, ownerUsers.disabled]).toEqual([true, true]);
    expect(
      within(dialog).queryByRole("checkbox", { name: /Turn this role off/ }),
    ).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    // A turned-off role with no users can be turned on again.
    fireEvent.click(screen.getByRole("button", { name: "Edit: Night desk" }));
    dialog = screen.getByRole("dialog", { name: "Edit role: Night desk" });
    const turnOff = within(dialog).getByRole<HTMLInputElement>("checkbox", {
      name: /Turn this role off/,
    });
    expect([turnOff.checked, turnOff.disabled]).toEqual([true, false]);
    fireEvent.click(turnOff);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(roles.saveRole).toHaveBeenCalledTimes(2);
    });
    expect(roles.saveRole.mock.calls[1]?.[1]).toMatchObject({
      name: "Night desk",
      turned_off: false,
    });
  });

  it("TEST-FE-1142 Roles for the Owner keep the Owner role locked; a refusal from the server stays in the role form with its English words; Khmer role names show (V1.1 part 3, DL-120)", async () => {
    const roles = rolesApiOf();
    roles.saveRole.mockRejectedValueOnce(
      new AdministrationRefusedError(
        409,
        "ROLE_TURNED_OFF",
        "This role is turned off. Turn it on first.",
      ),
    );
    show(apiOf(), { roles });
    fireEvent.click(await screen.findByRole("button", { name: "Roles: Sok" }));
    let dialog = screen.getByRole("dialog", { name: "Roles for Sok" });
    const owner = within(dialog).getByRole<HTMLInputElement>("checkbox", {
      name: /Owner/,
    });
    expect([owner.checked, owner.disabled]).toEqual([true, true]);
    expect(dialog.textContent).toContain(
      "The Owner always keeps the Owner role.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "Edit: Staff" }));
    dialog = screen.getByRole("dialog", { name: "Edit role: Staff" });
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: /Open Invoices/ }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    const said = await within(dialog).findByText(
      "This role is turned off. Turn it on first.",
    );
    expect(said.getAttribute("lang")).toBe("en");
    expect(
      screen.getByRole("dialog", { name: "Edit role: Staff" }),
    ).toBeTruthy();
    cleanup();

    show(apiOf(), { language: "km" });
    const region = await screen.findByRole("region", { name: "តួនាទី" });
    expect(region.textContent).toContain("អ្នកគ្រប់គ្រង");
    expect(region.textContent).toContain("ត្រូវការ");
    expect(screen.getByRole("button", { name: "បន្ថែមតួនាទី" })).toBeTruthy();
  });
});
