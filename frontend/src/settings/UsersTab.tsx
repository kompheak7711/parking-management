// V1-058 R7b-3: Settings → Users and sign-in (mock-up rounds 4–8, DL-081): the users with their
// account type, roles, MFA and state; Add user, Roles, Reset, Disable and End all sessions; the
// roles and their permissions (V1.1 part 3, DL-120, which replaced the Settings access ticks
// with the role right "Change business rules") and the sign-in rules. The Owner alone opens this tab. An
// action that changes who may use the app asks for the password and sign-in code again when the
// server says so (login sub-slice L3d-2), then runs once more; nothing was written before.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type AccessAdministrationApi,
  AdministrationRefusedError,
  AdministrationUnavailableError,
  type OneTimePassword,
  ReauthenticationRequiredError,
  type UserAccount,
} from "../adminClient";
import {
  RateLimitedError,
  type ReauthenticationRequest,
  ServiceUnavailableError,
} from "../authClient";
import {
  RoleEditorDialog,
  RolesSection,
  UserRolesDialog,
  userRoleNames,
} from "../access/RolesSection";
import {
  type Role,
  type RolesAndPermissions,
  type RolesApi,
} from "../access/rolesClient";
import { at } from "../access/text";
import { momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { type SettingsTextKey, sst } from "./text";

export type UsersApi = Pick<
  AccessAdministrationApi,
  | "load"
  | "createUser"
  | "disableUser"
  | "revokeSessions"
  | "administrativelyRecoverUser"
>;

const SIGN_IN_RULES: readonly SettingsTextKey[] = [
  "se_signin_1",
  "se_signin_2",
  "se_signin_3",
  "se_signin_5",
  "se_signin_4",
];

const REASONS = [
  "ur_r_forgot",
  "ur_r_phone",
  "ur_r_risk",
  "ur_r_other",
] as const;

type Open =
  | { kind: "add" }
  | { kind: "roles"; user: UserAccount }
  | { kind: "role"; role: Role | null }
  | { kind: "revoke" }
  | { kind: "reset"; user: UserAccount }
  | { kind: "disable"; user: UserAccount };

interface Problem {
  text: string;
  /** The server's own words, in English. */
  server?: string;
}

function roleText(language: Language, user: UserAccount): string {
  return sst(
    language,
    user.account_class === null ? "role_other" : `role_${user.account_class}`,
  );
}

function ProblemNotice({ problem }: { problem: Problem | null }) {
  if (problem === null) return null;
  return (
    <div className="ui-notice warn" role="alert">
      <Icon name="alert" />
      <p>
        {problem.text}
        {problem.server !== undefined && (
          <>
            {" "}
            <span lang="en">{problem.server}</span>
          </>
        )}
      </p>
    </div>
  );
}

function FieldError({ id, text }: { id: string; text: string | undefined }) {
  if (text === undefined) return null;
  return (
    <p className="ui-error" id={id} role="alert">
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

function AddUserDialog({
  language,
  users,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  users: UserAccount[];
  busy: boolean;
  problem: Problem | null;
  onClose: () => void;
  onSave: (user: {
    name: string;
    username: string;
    role: "staff" | "manager";
  }) => void;
}) {
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<"staff" | "manager">("staff");
  const [errors, setErrors] = useState<{ name?: string; username?: string }>(
    {},
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const shown = name.trim();
    const login = username.trim();
    const found: { name?: string; username?: string } = {};
    if (shown === "") found.name = sst(language, "se_e_name");
    if (login === "") found.username = sst(language, "e_username");
    else if (
      users.some((user) => user.username.toLowerCase() === login.toLowerCase())
    ) {
      found.username = sst(language, "se_e_dup", login);
    }
    setErrors(found);
    if (found.name !== undefined || found.username !== undefined) {
      document
        .getElementById(found.name !== undefined ? "nu-name" : "nu-user")
        ?.focus();
      return;
    }
    onSave({ name: shown, username: login, role });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "save")}
      title={sst(language, "se_new_user")}
    >
      <div className="ui-field">
        <label htmlFor="nu-name">
          {sst(language, "se_user")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={errors.name === undefined ? undefined : "nu-name-e"}
          aria-invalid={errors.name !== undefined}
          autoComplete="off"
          id="nu-name"
          maxLength={128}
          onChange={(event) => {
            setName(event.currentTarget.value);
          }}
          value={name}
        />
        <FieldError id="nu-name-e" text={errors.name} />
      </div>
      <div className="ui-field">
        <label htmlFor="nu-user">
          {sst(language, "username")}
          <span className="req">{sst(language, "required")}</span>
        </label>
        <input
          aria-describedby={
            errors.username === undefined ? "nu-user-h" : "nu-user-h nu-user-e"
          }
          aria-invalid={errors.username !== undefined}
          autoCapitalize="none"
          autoComplete="off"
          id="nu-user"
          lang="en"
          maxLength={128}
          onChange={(event) => {
            setUsername(event.currentTarget.value);
          }}
          spellCheck={false}
          value={username}
        />
        <p className="help" id="nu-user-h">
          {sst(language, "username_h")}
        </p>
        <FieldError id="nu-user-e" text={errors.username} />
      </div>
      <div className="ui-field">
        <label htmlFor="nu-role">{sst(language, "se_role")}</label>
        <select
          id="nu-role"
          onChange={(event) => {
            setRole(
              event.currentTarget.value === "manager" ? "manager" : "staff",
            );
          }}
          value={role}
        >
          <option value="staff">{sst(language, "role_staff")}</option>
          <option value="manager">{sst(language, "role_manager")}</option>
        </select>
        <p className="help">{sst(language, "owner_one")}</p>
      </div>
      <p className="ui-small ui-muted">{sst(language, "se_user_note")}</p>
      <ProblemNotice problem={problem} />
    </Dialog>
  );
}

function ResetDialog({
  language,
  user,
  busy,
  problem,
  onClose,
  onSave,
}: {
  language: Language;
  user: UserAccount;
  busy: boolean;
  problem: Problem | null;
  onClose: () => void;
  onSave: (resetMfa: boolean, reason: string) => void;
}) {
  const [what, setWhat] = useState<"pw" | "mfa" | null>(null);
  const [reason, setReason] = useState<(typeof REASONS)[number] | "">("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Set<"what" | "reason" | "note">>(
    new Set(),
  );
  const name = user.display_name;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = new Set<"what" | "reason" | "note">();
    if (what === null) found.add("what");
    if (reason === "") found.add("reason");
    if (reason === "ur_r_other" && note.trim() === "") found.add("note");
    setErrors(found);
    const first = (["what", "reason", "note"] as const).find((key) =>
      found.has(key),
    );
    if (first !== undefined || what === null || reason === "") {
      document
        .querySelector<HTMLElement>(
          first === "what" ? '[name="ur-what"]' : `#ur-${first ?? "note"}`,
        )
        ?.focus();
      return;
    }
    // The reason is kept in History in the words the Owner saw.
    const why = sst(language, reason) + (note.trim() ? `: ${note.trim()}` : "");
    onSave(what === "mfa", why);
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "ur_ok")}
      title={sst(language, "ur_t", name)}
    >
      <fieldset
        aria-describedby={errors.has("what") ? "ur-what-e" : undefined}
        className="ui-radios"
      >
        <legend>{sst(language, "ur_what")}</legend>
        <label className="ui-chk">
          <input
            checked={what === "pw"}
            name="ur-what"
            onChange={() => {
              setWhat("pw");
            }}
            type="radio"
          />
          <span>
            {sst(language, "ur_pw")}
            <small className="ui-sub2">{sst(language, "ur_pw_s")}</small>
          </span>
        </label>
        {user.mfa_policy_class === "required" && (
          <label className="ui-chk">
            <input
              checked={what === "mfa"}
              name="ur-what"
              onChange={() => {
                setWhat("mfa");
              }}
              type="radio"
            />
            <span>
              {sst(language, "ur_mfa")}
              <small className="ui-sub2">
                {sst(language, "ur_mfa_s")} {sst(language, "ur_mfa_pw")}
              </small>
            </span>
          </label>
        )}
        <FieldError
          id="ur-what-e"
          text={errors.has("what") ? sst(language, "ur_e_what") : undefined}
        />
      </fieldset>
      <div className="ui-field">
        <label htmlFor="ur-reason">{sst(language, "ur_reason")}</label>
        <select
          aria-describedby={errors.has("reason") ? "ur-reason-e" : undefined}
          aria-invalid={errors.has("reason")}
          id="ur-reason"
          onChange={(event) => {
            const value = event.currentTarget.value;
            setReason(REASONS.find((key) => key === value) ?? "");
          }}
          value={reason}
        >
          <option value="">{sst(language, "ur_choose")}</option>
          {REASONS.map((key) => (
            <option key={key} value={key}>
              {sst(language, key)}
            </option>
          ))}
        </select>
        <FieldError
          id="ur-reason-e"
          text={errors.has("reason") ? sst(language, "ur_e_reason") : undefined}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="ur-note">{sst(language, "ur_note")}</label>
        <input
          aria-describedby={errors.has("note") ? "ur-note-e" : undefined}
          aria-invalid={errors.has("note")}
          autoComplete="off"
          id="ur-note"
          maxLength={120}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
          placeholder={sst(language, "ur_note_ph")}
          value={note}
        />
        <FieldError
          id="ur-note-e"
          text={errors.has("note") ? sst(language, "ur_e_note") : undefined}
        />
      </div>
      <div className="ui-notice warn" role="note">
        <Icon name="alert" />
        <p>{sst(language, "ur_conseq", name)}</p>
      </div>
      <ProblemNotice problem={problem} />
    </Dialog>
  );
}

function ReauthenticationDialog({
  language,
  onClose,
  onConfirm,
}: {
  language: Language;
  onClose: () => void;
  onConfirm: (request: ReauthenticationRequest) => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [errors, setErrors] = useState<{ pw?: string; code?: string }>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const digits = code.replace(/\s/g, "");
    const found: { pw?: string; code?: string } = {};
    if (password === "") found.pw = sst(language, "ra_e_pw");
    if (!/^\d{6}$/.test(digits)) found.code = sst(language, "ra_e_code");
    setErrors(found);
    setProblem(null);
    if (found.pw !== undefined || found.code !== undefined) {
      document
        .getElementById(found.pw !== undefined ? "ra-pw" : "ra-code")
        ?.focus();
      return;
    }
    setBusy(true);
    onConfirm({
      password,
      second_factor: { method: "totp", code: digits },
    }).catch((error: unknown) => {
      setBusy(false);
      setCode("");
      setProblem(
        error instanceof RateLimitedError
          ? sst(
              language,
              "ra_wait",
              Math.max(1, Math.ceil(error.retryAfterSeconds / 60)),
            )
          : error instanceof ServiceUnavailableError
            ? sst(language, "ra_down")
            : sst(language, "ra_bad"),
      );
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={sst(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={sst(language, "ra_ok")}
      title={sst(language, "ra_t")}
    >
      <p>{sst(language, "ra_s")}</p>
      <div className="ui-field">
        <label htmlFor="ra-pw">{sst(language, "ra_pw")}</label>
        <input
          aria-describedby={errors.pw === undefined ? undefined : "ra-pw-e"}
          aria-invalid={errors.pw !== undefined}
          autoComplete="current-password"
          id="ra-pw"
          maxLength={128}
          onChange={(event) => {
            setPassword(event.currentTarget.value);
          }}
          type="password"
          value={password}
        />
        <FieldError id="ra-pw-e" text={errors.pw} />
      </div>
      <div className="ui-field">
        <label htmlFor="ra-code">{sst(language, "ra_code")}</label>
        <input
          aria-describedby={errors.code === undefined ? undefined : "ra-code-e"}
          aria-invalid={errors.code !== undefined}
          autoComplete="one-time-code"
          id="ra-code"
          inputMode="numeric"
          maxLength={7}
          onChange={(event) => {
            setCode(event.currentTarget.value);
          }}
          value={code}
        />
        <FieldError id="ra-code-e" text={errors.code} />
      </div>
      {problem !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{problem}</p>
        </div>
      )}
    </Dialog>
  );
}

function PasswordDialog({
  language,
  name,
  password,
  onClose,
}: {
  language: Language;
  name: string;
  password: OneTimePassword;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState<boolean | null>(null);
  return (
    <Dialog
      closeLabel={sst(language, "ur_close")}
      onClose={onClose}
      title={sst(language, "ur_done_t", name)}
    >
      <p>{sst(language, "ur_done_s", name)}</p>
      <div className="ui-otp">
        <code className="ui-num" lang="en">
          {password.value}
        </code>
        <button
          className="ui-btn"
          onClick={() => {
            const clipboard = navigator.clipboard as Clipboard | undefined;
            if (clipboard === undefined) {
              setCopied(false);
              return;
            }
            clipboard.writeText(password.value).then(
              () => {
                setCopied(true);
              },
              () => {
                setCopied(false);
              },
            );
          }}
          type="button"
        >
          {sst(language, "ur_copy")}
        </button>
        <span aria-live="polite" className="ui-small" role="status">
          {copied === null
            ? ""
            : sst(language, copied ? "ur_copied" : "copy_failed")}
        </span>
      </div>
      <p className="ui-small">
        {sst(language, "otp_until", momentText(password.expires_at))}
      </p>
      <p className="ui-small ui-muted">{sst(language, "ur_done_once")}</p>
    </Dialog>
  );
}

export function UsersTab({
  language,
  propertyId,
  active,
  api,
  rolesApi,
  myUserId,
  reauthenticate,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: UsersApi;
  rolesApi: RolesApi;
  /** The signed-in person, whom End all sessions leaves signed in. */
  myUserId: string | null;
  reauthenticate: (request: ReauthenticationRequest) => Promise<void>;
}) {
  const [users, setUsers] = useState<UserAccount[] | null>(null);
  const [roles, setRoles] = useState<RolesAndPermissions | null>(null);
  const [failure, setFailure] = useState<"failed" | "not_allowed" | null>(null);
  const [open, setOpen] = useState<Open | null>(null);
  const [reauth, setReauth] = useState<{
    id: number;
    retry: () => void;
  } | null>(null);
  const reauthCount = useRef(0);
  const [issued, setIssued] = useState<{
    name: string;
    password: OneTimePassword;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const shownProperty = useRef(propertyId);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailure(null);
    Promise.all([api.load(propertyId), rolesApi.load(propertyId)])
      .then(([loaded, roleList]) => {
        if (operation !== sequence.current) return;
        setUsers(loaded.users);
        setRoles(roleList);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setUsers(null);
        setRoles(null);
        setFailure(
          error instanceof AdministrationUnavailableError
            ? "not_allowed"
            : "failed",
        );
      });
  }, [api, rolesApi, propertyId]);

  // Another Property never shows the users of the one before, and a one-time password made for
  // the one before is gone.
  useEffect(() => {
    shownProperty.current = propertyId;
    sequence.current++;
    setUsers(null);
    setRoles(null);
    setFailure(null);
    setOpen(null);
    setReauth(null);
    setIssued(null);
    setProblem(null);
    setToast(null);
  }, [propertyId]);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  /**
   * `keep`: the answer holds a one-time password, shown even if the Property changed meanwhile,
   * because the account was changed and the password is never shown again.
   */
  function run<T>(
    work: () => Promise<T>,
    done: (result: T) => void,
    keep = false,
  ) {
    const asked = propertyId;
    setBusy(true);
    setProblem(null);
    work()
      .then((result) => {
        if (shownProperty.current !== asked) {
          if (keep) done(result);
          return;
        }
        setReauth(null);
        setOpen(null);
        done(result);
        load();
      })
      .catch((error: unknown) => {
        if (shownProperty.current !== asked) return;
        if (error instanceof ReauthenticationRequiredError) {
          // Nothing was written; it runs again once the Owner has confirmed.
          // A new dialog each time, so one asked again starts empty and not busy.
          setReauth({
            id: ++reauthCount.current,
            retry: () => {
              run(work, done, keep);
            },
          });
        } else if (error instanceof AdministrationUnavailableError) {
          setReauth(null);
          setProblem({ text: sst(language, "no_tab") });
        } else if (
          error instanceof AdministrationRefusedError &&
          (error.status === 412 ||
            error.status === 404 ||
            error.code === "CONFLICT" ||
            error.code === "TRY_AGAIN")
        ) {
          // The open form holds the old account, so it closes; the list is read again.
          setReauth(null);
          setOpen(null);
          setToast({ ok: false, text: sst(language, "users_changed") });
          load();
        } else if (error instanceof AdministrationRefusedError) {
          setReauth(null);
          setProblem({
            text: sst(language, "users_refused"),
            server: error.serverMessage,
          });
        } else {
          setReauth(null);
          setProblem({ text: sst(language, "users_unknown") });
          load();
        }
      })
      .finally(() => {
        setBusy(false);
      });
  }

  function start(next: Open) {
    setProblem(null);
    setToast(null);
    setOpen(next);
  }

  if (failure !== null) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{sst(language, failure === "failed" ? "users_failed" : "no_tab")}</p>
        {failure === "failed" && (
          <button className="ui-btn" onClick={load} type="button">
            {sst(language, "retry")}
          </button>
        )}
      </div>
    );
  }
  if (users === null || roles === null) {
    return (
      <p className="ui-muted" role="status">
        {sst(language, "users_loading")}
      </p>
    );
  }

  const others = users.filter(
    (user) => user.lifecycle_state === "active" && user.user_id !== myUserId,
  );
  const closeOpen = () => {
    if (!busy) setOpen(null);
  };

  return (
    <>
      <div aria-live="polite" role="status">
        {toast !== null && (
          <div className={toast.ok ? "ui-notice ok" : "ui-notice warn"}>
            <Icon name={toast.ok ? "check" : "alert"} />
            <p>{toast.text}</p>
          </div>
        )}
      </div>
      <section aria-labelledby="settings-users" className="ui-card pad0">
        <header className="ui-chead pad">
          <h2 id="settings-users">{sst(language, "se_users")}</h2>
          <span className="ui-actions">
            <button
              className="ui-btn primary"
              onClick={() => {
                start({ kind: "add" });
              }}
              type="button"
            >
              <Icon name="plus" small />
              {sst(language, "se_new_user")}
            </button>
          </span>
        </header>
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{sst(language, "se_user")}</th>
                <th scope="col">{sst(language, "se_class")}</th>
                <th scope="col">{at(language, "ur_roles_col")}</th>
                <th scope="col">{sst(language, "se_mfa")}</th>
                <th scope="col">{sst(language, "se_state")}</th>
                <th scope="col">{sst(language, "ur_col")}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const owner = user.account_class === "owner";
                const helpable =
                  !owner &&
                  user.lifecycle_state === "active" &&
                  user.user_id !== myUserId;
                return (
                  <tr key={user.user_id}>
                    <td>
                      <b>{user.display_name}</b>
                      <span className="ui-sub2 ui-num" lang="en">
                        {user.username}
                      </span>
                    </td>
                    <td>{roleText(language, user)}</td>
                    <td className="wrap">
                      <span>{userRoleNames(language, user, roles)}</span>
                      {user.lifecycle_state === "active" && (
                        <>
                          {" "}
                          <button
                            aria-label={`${at(language, "ur_roles_col")}: ${user.display_name}`}
                            className="ui-btn link"
                            onClick={() => {
                              start({ kind: "roles", user });
                            }}
                            type="button"
                          >
                            {at(language, "ur_roles_btn")}
                          </button>
                        </>
                      )}
                    </td>
                    <td>
                      {user.mfa_policy_class === "required" ? (
                        <Chip icon="lock" tone="info">
                          {sst(language, "mfa_needed")}
                        </Chip>
                      ) : (
                        <span className="ui-muted">
                          {sst(language, "se_mfa_off")}
                        </span>
                      )}
                    </td>
                    <td>
                      {user.lifecycle_state === "active" ? (
                        <Chip icon="check" tone="ok">
                          {sst(language, "se_active")}
                        </Chip>
                      ) : (
                        <Chip tone="neutral">
                          {sst(language, "se_disabled")}
                        </Chip>
                      )}
                    </td>
                    <td>
                      {helpable ? (
                        <span className="ui-actions">
                          <button
                            aria-label={`${sst(language, "ur_btn")}: ${user.display_name}`}
                            className="ui-btn"
                            onClick={() => {
                              start({ kind: "reset", user });
                            }}
                            type="button"
                          >
                            <Icon name="lock" small />
                            {sst(language, "ur_btn")}
                          </button>
                          <button
                            aria-label={`${sst(language, "dis_btn")}: ${user.display_name}`}
                            className="ui-btn link"
                            onClick={() => {
                              start({ kind: "disable", user });
                            }}
                            type="button"
                          >
                            {sst(language, "dis_btn")}
                          </button>
                        </span>
                      ) : (
                        <span className="ui-muted">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="ui-tfoot ui-tfoot-row">
          <span>{sst(language, "users_note")}</span>
          {myUserId !== null && others.length > 0 && (
            <button
              className="ui-btn"
              onClick={() => {
                start({ kind: "revoke" });
              }}
              type="button"
            >
              <Icon name="lock" small />
              {sst(language, "se_revoke")}
            </button>
          )}
        </div>
      </section>
      {/* One under the other: the role table needs the width for its columns. */}
      <div className="ui-stack">
        <RolesSection
          data={roles}
          language={language}
          onAdd={() => {
            start({ kind: "role", role: null });
          }}
          onEdit={(role) => {
            start({ kind: "role", role });
          }}
        />
        <section aria-labelledby="settings-signin" className="ui-card">
          <h2 id="settings-signin">{sst(language, "se_signin")}</h2>
          <ul className="ui-steps">
            {SIGN_IN_RULES.map((key) => (
              <li key={key}>{sst(language, key)}</li>
            ))}
            <li>{at(language, "se_signin_roles")}</li>
          </ul>
        </section>
      </div>

      {reauth !== null && (
        <ReauthenticationDialog
          key={reauth.id}
          language={language}
          onClose={() => {
            setReauth(null);
            setOpen(null);
            setToast({ ok: false, text: sst(language, "ua_e_none") });
          }}
          onConfirm={async (request) => {
            await reauthenticate(request);
            reauth.retry();
          }}
        />
      )}
      {/* The open form stays (hidden) while the password and code are asked, so what was typed
          is still there if the server then refuses. */}
      <div hidden={reauth !== null}>
        {open?.kind === "add" && (
          <AddUserDialog
            busy={busy}
            language={language}
            onClose={closeOpen}
            onSave={({ name, username, role }) => {
              run(
                () =>
                  api.createUser(propertyId, {
                    username,
                    display_name: name,
                    audit_name: name,
                    account_class: role,
                  }),
                (created) => {
                  setToast({
                    ok: true,
                    text: sst(
                      language,
                      "se_user_saved",
                      created.account.display_name,
                    ),
                  });
                  setIssued({
                    name: created.account.display_name,
                    password: created.one_time_password,
                  });
                },
                true,
              );
            }}
            problem={problem}
            users={users}
          />
        )}
        {open?.kind === "roles" && (
          <UserRolesDialog
            busy={busy}
            data={roles}
            language={language}
            notice={<ProblemNotice problem={problem} />}
            onClose={closeOpen}
            onSave={({ give, take, reason }) => {
              const { user } = open;
              // A run asked to confirm the Owner part-way runs again for the rest only.
              const finished = new Set<string>();
              const refused: string[] = [];
              const named = (id: string) => {
                const role = roles.roles.find(
                  (one) => one.role_bundle_id === id,
                );
                return role === undefined
                  ? user.display_name
                  : `${user.display_name} (${language === "km" && role.name_kh !== null ? role.name_kh : role.name})`;
              };
              run(
                async () => {
                  const steps = [
                    ...give.map((id) => ({ id, giving: true })),
                    ...take.map((id) => ({ id, giving: false })),
                  ];
                  for (const { id, giving } of steps) {
                    if (finished.has(id)) continue;
                    try {
                      await (giving
                        ? rolesApi.giveRole(user.user_id, id)
                        : rolesApi.takeRole(user.user_id, id, reason));
                      finished.add(id);
                    } catch (error: unknown) {
                      // Only a refusal of this one role is reported here; anything else
                      // stops the rest.
                      if (
                        !(error instanceof AdministrationRefusedError) ||
                        error.status === 412
                      ) {
                        throw error;
                      }
                      finished.add(id);
                      refused.push(
                        at(
                          language,
                          error.code === "SIGN_IN_CODE_REQUIRED"
                            ? "ur_roles_code"
                            : "ur_roles_one",
                          named(id),
                        ),
                      );
                    }
                  }
                  return [...refused];
                },
                (refused) => {
                  setToast(
                    refused.length === 0
                      ? { ok: true, text: sst(language, "se_saved") }
                      : { ok: false, text: refused.join(" ") },
                  );
                },
              );
            }}
            user={open.user}
          />
        )}
        {open?.kind === "role" && (
          <RoleEditorDialog
            busy={busy}
            data={roles}
            language={language}
            notice={<ProblemNotice problem={problem} />}
            onClose={closeOpen}
            onSave={(change) => {
              const { role } = open;
              run(
                () =>
                  role === null
                    ? rolesApi.createRole(propertyId, change)
                    : rolesApi.saveRole(role, change),
                (saved) => {
                  setToast({
                    ok: true,
                    text: at(
                      language,
                      "ro_saved",
                      language === "km" && saved.name_kh !== null
                        ? saved.name_kh
                        : saved.name,
                    ),
                  });
                },
              );
            }}
            role={open.role}
          />
        )}
        {open?.kind === "reset" && (
          <ResetDialog
            busy={busy}
            language={language}
            onClose={closeOpen}
            onSave={(resetMfa, reason) => {
              const { user } = open;
              run(
                () =>
                  api.administrativelyRecoverUser(user.user_id, {
                    reset_mfa: resetMfa,
                    reason,
                  }),
                (result) => {
                  setIssued({
                    name: user.display_name,
                    password: result.one_time_password,
                  });
                },
                true,
              );
            }}
            problem={problem}
            user={open.user}
          />
        )}
        {open?.kind === "disable" && (
          <Dialog
            actions={
              <button
                className="ui-btn danger"
                disabled={busy}
                onClick={() => {
                  const { user } = open;
                  run(
                    () => api.disableUser(user),
                    () => {
                      setToast({
                        ok: true,
                        text: sst(language, "dis_done", user.display_name),
                      });
                    },
                  );
                }}
                type="button"
              >
                {sst(language, "dis_btn")}
              </button>
            }
            busy={busy}
            closeLabel={sst(language, "cancel")}
            onClose={closeOpen}
            title={sst(language, "dis_t", open.user.display_name)}
          >
            <p>{sst(language, "dis_q", open.user.display_name)}</p>
            <ProblemNotice problem={problem} />
          </Dialog>
        )}
        {open?.kind === "revoke" && (
          <Dialog
            actions={
              <button
                className="ui-btn danger"
                disabled={busy}
                onClick={() => {
                  run(
                    async () => {
                      const results = await Promise.allSettled(
                        others.map((user) => api.revokeSessions(user.user_id)),
                      );
                      return results.every(
                        (result) => result.status === "fulfilled",
                      );
                    },
                    (all) => {
                      setToast(
                        all
                          ? {
                              ok: true,
                              text: sst(language, "se_revoke_done"),
                            }
                          : { ok: false, text: sst(language, "revoke_some") },
                      );
                    },
                  );
                }}
                type="button"
              >
                {sst(language, "se_revoke")}
              </button>
            }
            busy={busy}
            closeLabel={sst(language, "cancel")}
            onClose={closeOpen}
            title={sst(language, "se_revoke")}
          >
            <p>{sst(language, "se_revoke_q")}</p>
            <ProblemNotice problem={problem} />
          </Dialog>
        )}
      </div>
      {issued !== null && (
        <PasswordDialog
          language={language}
          name={issued.name}
          onClose={() => {
            setIssued(null);
          }}
          password={issued.password}
        />
      )}
    </>
  );
}
