import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  AUTHENTICATION_ERROR_MESSAGE,
  AuthenticationApi,
  AuthenticationData,
  LocalSignIn,
  MfaEnrollmentData,
  MfaMethod,
  RecoveryCodeSetData,
  SessionData,
  authenticationApi,
  signIn,
} from "./authClient";
import {
  AccessAdministrationApi,
  AccessAdministrationSnapshot,
  AdministrationUnavailableError,
  UserAccount,
  accessAdministrationApi,
} from "./adminClient";

export interface AppProps {
  environment: string;
  buildId: string;
  authenticate?: LocalSignIn;
  api?: AuthenticationApi;
  administrationApi?: AccessAdministrationApi;
  now?: () => number;
}

type SubmissionState = "idle" | "submitting" | "succeeded" | "failed";
type Screen =
  | "sign_in"
  | "mfa_required"
  | "mfa_enrollment_required"
  | "authenticated";

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unavailable" : parsed.toISOString();
}

function phaseScreen(result: AuthenticationData): Screen {
  return result.phase;
}

export function App({
  environment,
  buildId,
  authenticate = signIn,
  api,
  administrationApi = accessAdministrationApi,
  now = Date.now,
}: AppProps) {
  const client = useMemo<AuthenticationApi>(
    () => api ?? { ...authenticationApi, signIn: authenticate },
    [api, authenticate],
  );
  const [screen, setScreen] = useState<Screen>("sign_in");
  const [session, setSession] = useState<SessionData | null>(null);
  const [submissionState, setSubmissionState] =
    useState<SubmissionState>("idle");
  const [notice, setNotice] = useState<string | null>(null);
  const [enrollment, setEnrollment] = useState<MfaEnrollmentData | null>(null);
  const [recoveryCodes, setRecoveryCodes] =
    useState<RecoveryCodeSetData | null>(null);
  const [mfaMethod, setMfaMethod] = useState<MfaMethod>("totp");
  const [showReauthentication, setShowReauthentication] = useState(false);
  const [administration, setAdministration] =
    useState<AccessAdministrationSnapshot | null>(null);
  const [administrationStatus, setAdministrationStatus] = useState<
    string | null
  >(null);
  const [propertyId, setPropertyId] = useState("");
  const [pendingCommand, setPendingCommand] = useState<{
    kind: "disable" | "revoke" | "recover";
    user: UserAccount;
    recovery?: { new_password: string; reset_mfa: boolean; reason: string };
  } | null>(null);

  function acceptAuthentication(result: AuthenticationData) {
    setSession(result.session);
    setScreen(phaseScreen(result));
    setSubmissionState("succeeded");
    setNotice(
      result.phase === "authenticated" ? "Your sign-in was accepted." : null,
    );
  }

  function returnToSignIn(message: string | null) {
    setScreen("sign_in");
    setSession(null);
    setEnrollment(null);
    setRecoveryCodes(null);
    setSubmissionState("idle");
    setShowReauthentication(false);
    setNotice(message);
  }

  useEffect(() => {
    if (api !== undefined || authenticate !== signIn) return;
    let active = true;
    void client
      .inspectSession()
      .then((restored) => {
        if (!active) return;
        setSession(restored);
        setScreen("authenticated");
      })
      .catch(() => {
        // A missing or expired cookie is the normal anonymous state.
      });
    return () => {
      active = false;
    };
  }, [api, authenticate, client]);

  useEffect(() => {
    if (screen !== "authenticated" || session === null) {
      return;
    }
    const expiresAt = Math.min(
      new Date(session.idle_expires_at).getTime(),
      new Date(session.absolute_expires_at).getTime(),
    );
    const delay = Math.min(2_147_483_647, Math.max(0, expiresAt - now()));
    const timer = window.setTimeout(() => {
      returnToSignIn(
        "Your session expired. Any unsaved command was not submitted. Sign in again to continue.",
      );
    }, delay);
    return () => {
      window.clearTimeout(timer);
    };
  }, [now, screen, session]);

  function handleSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const username = formData.get("username");
    const password = formData.get("password");

    setNotice(null);
    setSubmissionState("submitting");
    void client
      .signIn({
        username: typeof username === "string" ? username : "",
        password: typeof password === "string" ? password : "",
      })
      .then((result) => {
        if (result.phase === "authenticated") {
          form.reset();
        }
        acceptAuthentication(result);
      })
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function handleMfaChallenge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const code = data.get("mfa-code");
    setSubmissionState("submitting");
    void client
      .completeMfa({
        method: mfaMethod,
        code: typeof code === "string" ? code : "",
      })
      .then(acceptAuthentication)
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function beginEnrollment() {
    setSubmissionState("submitting");
    void client
      .beginMfaEnrollment()
      .then((result) => {
        setEnrollment(result);
        setSubmissionState("idle");
      })
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function confirmEnrollment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const code = data.get("enrollment-code");
    setSubmissionState("submitting");
    void client
      .confirmMfaEnrollment(typeof code === "string" ? code : "")
      .then((result) => {
        setEnrollment(null);
        acceptAuthentication(result);
      })
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function handleReauthentication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const password = data.get("reauth-password");
    const code = data.get("reauth-code");
    setSubmissionState("submitting");
    void client
      .reauthenticate({
        password: typeof password === "string" ? password : "",
        ...(typeof code === "string" && code.length > 0
          ? { second_factor: { method: "totp" as const, code } }
          : {}),
      })
      .then((result) => {
        setSession(result);
        setShowReauthentication(false);
        setSubmissionState("succeeded");
        setNotice(
          "Recent authentication confirmed for protected administration.",
        );
      })
      .catch(() => {
        setSubmissionState("failed");
      });
  }

  function handleLogout() {
    setSubmissionState("submitting");
    void client
      .logout()
      .then(() => {
        returnToSignIn("You signed out.");
      })
      .catch(() => {
        returnToSignIn(
          "Your local session was cleared. Sign in again to continue.",
        );
      });
  }

  function issueRecoveryCodes() {
    setSubmissionState("submitting");
    void client
      .issueRecoveryCodes()
      .then((result) => {
        setRecoveryCodes(result);
        setSubmissionState("succeeded");
        setNotice(
          "Recovery codes were generated. Save them now; they will not be shown again.",
        );
      })
      .catch(() => {
        setSubmissionState("failed");
        setNotice("Recovery codes could not be generated.");
      });
  }

  function regenerateRecoveryCodes() {
    if (recoveryCodes === null) return;
    setSubmissionState("submitting");
    void client
      .regenerateRecoveryCodes(recoveryCodes.set_id)
      .then((result) => {
        setRecoveryCodes(result);
        setSubmissionState("succeeded");
        setNotice(
          "The prior recovery-code set was invalidated. Save this replacement set now.",
        );
      })
      .catch(() => {
        setSubmissionState("failed");
        setNotice("Recovery codes could not be replaced.");
      });
  }

  function loadAdministration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAdministrationStatus(
      "Checking server-authorized administration access…",
    );
    void administrationApi
      .load(propertyId)
      .then((result) => {
        setAdministration(result);
        setAdministrationStatus(
          "Administration access confirmed by the server.",
        );
      })
      .catch((error: unknown) => {
        setAdministration(null);
        setAdministrationStatus(
          error instanceof AdministrationUnavailableError
            ? "Administration is not available for this session and property."
            : "Administration data could not be loaded.",
        );
      });
  }

  function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const value = (name: string) => {
      const field = data.get(name);
      return typeof field === "string" ? field : "";
    };
    setAdministrationStatus("Submitting the audited account command…");
    void administrationApi
      .createUser(propertyId, {
        username: value("new-username"),
        display_name: value("new-display-name"),
        audit_name: value("new-audit-name"),
        mfa_policy_class:
          value("new-mfa-policy") === "required" ? "required" : "optional",
      })
      .then((user) => {
        setAdministration((current) =>
          current === null
            ? current
            : { ...current, users: [...current.users, user] },
        );
        setAdministrationStatus("Account created and recorded for audit.");
        form.reset();
      })
      .catch(() => {
        setAdministrationStatus("The account command was not completed.");
      });
  }

  function confirmAdministrativeCommand() {
    if (pendingCommand === null) return;
    const command = pendingCommand;
    setAdministrationStatus("Submitting the confirmed protected command…");
    if (command.kind === "disable") {
      void administrationApi
        .disableUser(command.user)
        .then((updated) => {
          setAdministration((current) =>
            current === null
              ? current
              : {
                  ...current,
                  users: current.users.map((user) =>
                    user.user_id === updated.user_id ? updated : user,
                  ),
                },
          );
          setAdministrationStatus(
            "Account disabled and applicable sessions revoked by the server.",
          );
          setPendingCommand(null);
        })
        .catch(() => {
          setAdministrationStatus("The protected command was not completed.");
          setPendingCommand(null);
        });
      return;
    }
    if (command.kind === "recover" && command.recovery !== undefined) {
      void administrationApi
        .administrativelyRecoverUser(command.user.user_id, command.recovery)
        .then((result) => {
          setAdministrationStatus(
            `Recovery completed; ${String(result.sessions_revoked)} applicable session(s) revoked.`,
          );
          setPendingCommand(null);
        })
        .catch(() => {
          setAdministrationStatus("The protected recovery was not completed.");
          setPendingCommand(null);
        });
      return;
    }
    void administrationApi
      .revokeSessions(command.user.user_id)
      .then((count) => {
        setAdministrationStatus(
          `${String(count)} applicable session(s) revoked.`,
        );
        setPendingCommand(null);
      })
      .catch(() => {
        setAdministrationStatus("The protected command was not completed.");
        setPendingCommand(null);
      });
  }

  function prepareAdministrativeRecovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (administration === null) return;
    const data = new FormData(event.currentTarget);
    const userId = data.get("recovery-user");
    const selected = administration.users.find(
      (user) => user.user_id === userId,
    );
    const password = data.get("recovery-password");
    const reason = data.get("recovery-reason");
    if (selected === undefined) return;
    setPendingCommand({
      kind: "recover",
      user: selected,
      recovery: {
        new_password: typeof password === "string" ? password : "",
        reset_mfa: data.get("recovery-reset-mfa") === "yes",
        reason: typeof reason === "string" ? reason : "",
      },
    });
  }

  function createRoleBundle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const name = data.get("bundle-name");
    const capabilityIds = data
      .getAll("bundle-capability")
      .filter((value): value is string => typeof value === "string");
    setAdministrationStatus("Submitting the audited role-bundle command…");
    void administrationApi
      .createRoleBundle(propertyId, {
        name: typeof name === "string" ? name : "",
        capability_ids: capabilityIds,
      })
      .then((bundle) => {
        setAdministration((current) =>
          current === null
            ? current
            : {
                ...current,
                roleBundles: [...current.roleBundles, bundle],
              },
        );
        setAdministrationStatus("Role bundle created and recorded for audit.");
        form.reset();
      })
      .catch(() => {
        setAdministrationStatus("The role-bundle command was not completed.");
      });
  }

  function assignRoleBundle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const userId = data.get("assignment-user");
    const bundleId = data.get("assignment-bundle");
    setAdministrationStatus("Submitting the audited role assignment…");
    void administrationApi
      .assignRoleBundle(
        typeof userId === "string" ? userId : "",
        typeof bundleId === "string" ? bundleId : "",
      )
      .then(() => {
        setAdministrationStatus("Role bundle assigned and recorded for audit.");
      })
      .catch(() => {
        setAdministrationStatus("The role assignment was not completed.");
      });
  }

  const isSubmitting = submissionState === "submitting";
  const hasError = submissionState === "failed";

  return (
    <div className="app-shell">
      <header className="app-header">
        <p className="eyebrow">Staff application</p>
        <h1>Property Rental Management</h1>
      </header>

      <main aria-labelledby="screen-heading" className="app-content">
        {notice !== null && (
          <p className="global-status" role="status">
            {notice}
          </p>
        )}

        {screen === "sign_in" && (
          <section className="auth-panel">
            <div>
              <p className="eyebrow">Secure access</p>
              <h2 id="screen-heading">Sign in</h2>
              <p className="panel-introduction">
                Use your local staff username and password.
              </p>
            </div>
            <form
              aria-describedby={hasError ? "authentication-error" : undefined}
              className="form-stack"
              onSubmit={handleSignIn}
            >
              <div className="form-field">
                <label htmlFor="username">Username</label>
                <input
                  aria-describedby={
                    hasError ? "authentication-error" : undefined
                  }
                  aria-invalid={hasError}
                  autoComplete="username"
                  disabled={isSubmitting}
                  id="username"
                  name="username"
                  required
                  type="text"
                />
              </div>
              <div className="form-field">
                <label htmlFor="password">Password</label>
                <input
                  aria-describedby={
                    hasError ? "authentication-error" : undefined
                  }
                  aria-invalid={hasError}
                  autoComplete="current-password"
                  disabled={isSubmitting}
                  id="password"
                  name="password"
                  required
                  type="password"
                />
              </div>
              {hasError && (
                <p
                  className="authentication-error"
                  id="authentication-error"
                  role="alert"
                >
                  {AUTHENTICATION_ERROR_MESSAGE}
                </p>
              )}
              <button disabled={isSubmitting} type="submit">
                {isSubmitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
            <p className="panel-help">
              Need help signing in? Contact your administrator.
            </p>
          </section>
        )}

        {screen === "mfa_required" && (
          <section className="auth-panel">
            <p className="eyebrow">Protected verification</p>
            <h2 id="screen-heading">Complete multi-factor authentication</h2>
            <p className="panel-introduction">
              Enter a current authenticator code or one unused recovery code.
            </p>
            <form className="form-stack" onSubmit={handleMfaChallenge}>
              <fieldset>
                <legend>Verification method</legend>
                <label>
                  <input
                    checked={mfaMethod === "totp"}
                    name="mfa-method"
                    onChange={() => {
                      setMfaMethod("totp");
                    }}
                    type="radio"
                  />
                  Authenticator code
                </label>
                <label>
                  <input
                    checked={mfaMethod === "recovery_code"}
                    name="mfa-method"
                    onChange={() => {
                      setMfaMethod("recovery_code");
                    }}
                    type="radio"
                  />
                  Recovery code
                </label>
              </fieldset>
              <div className="form-field">
                <label htmlFor="mfa-code">
                  {mfaMethod === "totp"
                    ? "Authenticator code"
                    : "Unused recovery code"}
                </label>
                <input
                  autoComplete="one-time-code"
                  id="mfa-code"
                  inputMode={mfaMethod === "totp" ? "numeric" : "text"}
                  name="mfa-code"
                  required
                />
              </div>
              {hasError && (
                <p className="authentication-error" role="alert">
                  Verification was not accepted. Try again or contact your
                  administrator.
                </p>
              )}
              <button disabled={isSubmitting} type="submit">
                Verify
              </button>
            </form>
            <p className="panel-help">
              A recovery code is single-use. Store remaining codes outside this
              application.
            </p>
          </section>
        )}

        {screen === "mfa_enrollment_required" && (
          <section className="auth-panel protected-material">
            <p className="eyebrow">Required enrollment</p>
            <h2 id="screen-heading">Enroll an authenticator</h2>
            {enrollment === null ? (
              <>
                <p className="panel-introduction">
                  Enrollment material is shown once. Continue only in a private
                  location.
                </p>
                <button
                  disabled={isSubmitting}
                  onClick={beginEnrollment}
                  type="button"
                >
                  Begin protected enrollment
                </button>
              </>
            ) : (
              <>
                <div
                  className="one-time-material"
                  role="region"
                  aria-label="One-time enrollment material"
                >
                  <p>
                    <strong>Show once:</strong> add this TOTP address to your
                    authenticator.
                  </p>
                  <code>{enrollment.provisioning_uri}</code>
                </div>
                <form className="form-stack" onSubmit={confirmEnrollment}>
                  <div className="form-field">
                    <label htmlFor="enrollment-code">Authenticator code</label>
                    <input
                      autoComplete="one-time-code"
                      id="enrollment-code"
                      inputMode="numeric"
                      name="enrollment-code"
                      pattern="[0-9]{6,8}"
                      required
                    />
                  </div>
                  <button disabled={isSubmitting} type="submit">
                    Confirm enrollment
                  </button>
                </form>
              </>
            )}
            {hasError && (
              <p className="authentication-error" role="alert">
                Enrollment could not be completed. Restart the protected flow.
              </p>
            )}
          </section>
        )}

        {screen === "authenticated" && session !== null && (
          <section className="workspace-panel">
            <div className="workspace-heading">
              <div>
                <p className="eyebrow">Authenticated workspace</p>
                <h2 id="screen-heading">Account and access</h2>
              </div>
              <button
                disabled={isSubmitting}
                onClick={handleLogout}
                type="button"
              >
                Sign out
              </button>
            </div>
            <section
              aria-labelledby="session-heading"
              className="information-card"
            >
              <h3 id="session-heading">Current session</h3>
              <dl className="detail-list">
                <div>
                  <dt>Inactivity expiry</dt>
                  <dd>{formatDateTime(session.idle_expires_at)}</dd>
                </div>
                <div>
                  <dt>Absolute expiry</dt>
                  <dd>{formatDateTime(session.absolute_expires_at)}</dd>
                </div>
                <div>
                  <dt>MFA assurance</dt>
                  <dd>{session.mfa_assurance.replace("_", " ")}</dd>
                </div>
                <div>
                  <dt>Recent authentication</dt>
                  <dd>
                    {session.reauthenticated_at === null
                      ? "Not recorded"
                      : formatDateTime(session.reauthenticated_at)}
                  </dd>
                </div>
              </dl>
              <p className="panel-help">
                The application returns to sign-in after 30 minutes of
                inactivity or 24 hours total. Unsaved commands are never
                reported as successful. Session timestamps are shown in UTC.
              </p>
              <button
                onClick={() => {
                  setShowReauthentication((shown) => !shown);
                }}
                type="button"
              >
                {showReauthentication
                  ? "Cancel reauthentication"
                  : "Reauthenticate for protected administration"}
              </button>
              {showReauthentication && (
                <form
                  className="form-stack nested-form"
                  onSubmit={handleReauthentication}
                >
                  <div className="form-field">
                    <label htmlFor="reauth-password">Password</label>
                    <input
                      autoComplete="current-password"
                      id="reauth-password"
                      name="reauth-password"
                      required
                      type="password"
                    />
                  </div>
                  <div className="form-field">
                    <label htmlFor="reauth-code">
                      Authenticator code, when required
                    </label>
                    <input
                      autoComplete="one-time-code"
                      id="reauth-code"
                      inputMode="numeric"
                      name="reauth-code"
                    />
                  </div>
                  <button disabled={isSubmitting} type="submit">
                    Confirm recent authentication
                  </button>
                </form>
              )}
            </section>
            <section
              aria-labelledby="recovery-heading"
              className="information-card"
            >
              <h3 id="recovery-heading">Recovery safety</h3>
              <p>
                Recovery codes are single-use and are never displayed again
                after issuance. Authorized administrative recovery requires
                explicit consequence and audit confirmation.
              </p>
              <p className="panel-help">
                Staff are not granted recovery authority for Owner or Manager
                accounts. Role labels never replace server-side capability
                checks.
              </p>
              {session.reauthenticated_at === null ? (
                <p className="muted">
                  Reauthenticate before generating or replacing recovery codes.
                </p>
              ) : recoveryCodes === null ? (
                <button
                  disabled={isSubmitting}
                  onClick={issueRecoveryCodes}
                  type="button"
                >
                  Generate one-time recovery codes
                </button>
              ) : (
                <div
                  aria-label="One-time recovery codes"
                  className="one-time-material"
                  role="region"
                >
                  <p>
                    <strong>Shown once:</strong> save each code outside this
                    application. Each code can be used only once.
                  </p>
                  <ol>
                    {recoveryCodes.codes.map((code) => (
                      <li key={code}>
                        <code>{code}</code>
                      </li>
                    ))}
                  </ol>
                  <div className="button-row">
                    <button
                      disabled={isSubmitting}
                      onClick={regenerateRecoveryCodes}
                      type="button"
                    >
                      Invalidate and replace this set
                    </button>
                    <button
                      onClick={() => {
                        setRecoveryCodes(null);
                        setNotice(
                          "Recovery codes were cleared from this screen and cannot be displayed again.",
                        );
                      }}
                      type="button"
                    >
                      I saved these codes—clear them
                    </button>
                  </div>
                </div>
              )}
            </section>
            <section
              aria-labelledby="administration-heading"
              className="information-card"
            >
              <h3 id="administration-heading">
                Capability-checked administration
              </h3>
              <p>
                Enter the exact property identifier. The server decides whether
                this session has the required capability; role labels are never
                treated as authority.
              </p>
              <form
                className="form-stack inline-form"
                onSubmit={loadAdministration}
              >
                <div className="form-field">
                  <label htmlFor="property-id">Property identifier</label>
                  <input
                    id="property-id"
                    name="property-id"
                    onChange={(event) => {
                      setPropertyId(event.currentTarget.value);
                    }}
                    required
                    value={propertyId}
                  />
                </div>
                <button type="submit">Check administration access</button>
              </form>
              {administrationStatus !== null && (
                <p role="status">{administrationStatus}</p>
              )}

              {administration !== null && (
                <div className="administration-grid">
                  <section aria-labelledby="users-heading">
                    <h4 id="users-heading">Accounts</h4>
                    {administration.users.length === 0 ? (
                      <p>No accounts were returned for this property.</p>
                    ) : (
                      <ul className="record-list">
                        {administration.users.map((user) => (
                          <li key={user.user_id}>
                            <div>
                              <strong>{user.display_name}</strong>
                              <span>
                                {user.username} · {user.lifecycle_state} · MFA{" "}
                                {user.mfa_policy_class}
                              </span>
                            </div>
                            {session.reauthenticated_at === null ? (
                              <span className="muted">
                                Reauthenticate before protected commands.
                              </span>
                            ) : (
                              <div className="button-row">
                                {user.lifecycle_state === "active" && (
                                  <button
                                    onClick={() => {
                                      setPendingCommand({
                                        kind: "disable",
                                        user,
                                      });
                                    }}
                                    type="button"
                                  >
                                    Disable account
                                  </button>
                                )}
                                <button
                                  onClick={() => {
                                    setPendingCommand({ kind: "revoke", user });
                                  }}
                                  type="button"
                                >
                                  Revoke sessions
                                </button>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section aria-labelledby="authorization-heading">
                    <h4 id="authorization-heading">
                      Authorization configuration
                    </h4>
                    <p className="panel-help">
                      This current configuration is audit context, not proof of
                      authority. Historical authorization events remain
                      immutable on the server. Event timestamps are shown in
                      UTC.
                    </p>
                    <ul className="record-list">
                      {administration.roleBundles.map((bundle) => (
                        <li key={bundle.role_bundle_id}>
                          <div>
                            <strong>{bundle.name}</strong>
                            <span>
                              {bundle.capability_ids.length} configured
                              capabilities
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                    <h5>Authorization history</h5>
                    {administration.authorizationHistory.length === 0 ? (
                      <p>No authorization events were returned.</p>
                    ) : (
                      <ol className="record-list">
                        {administration.authorizationHistory.map((event) => (
                          <li key={event.event_id}>
                            <div>
                              <strong>{event.action}</strong>
                              <span>
                                {formatDateTime(event.occurred_at)} ·{" "}
                                {event.outcome}
                                {" · actor "}
                                {event.actor_id}
                                {" · target "}
                                {event.target_id}
                              </span>
                            </div>
                          </li>
                        ))}
                      </ol>
                    )}
                    <details>
                      <summary>Capability catalog</summary>
                      <ul>
                        {administration.capabilities.map((capability) => (
                          <li key={capability.capability_id}>
                            <strong>{capability.name}</strong> —{" "}
                            {capability.description}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </section>

                  {session.reauthenticated_at !== null && (
                    <section aria-labelledby="protected-admin-heading">
                      <h4 id="protected-admin-heading">
                        Protected account and capability commands
                      </h4>
                      <form className="form-stack" onSubmit={createUser}>
                        <h5>Create account</h5>
                        <div className="form-field">
                          <label htmlFor="new-username">Username</label>
                          <input
                            id="new-username"
                            name="new-username"
                            required
                          />
                        </div>
                        <div className="form-field">
                          <label htmlFor="new-display-name">Display name</label>
                          <input
                            id="new-display-name"
                            name="new-display-name"
                            required
                          />
                        </div>
                        <div className="form-field">
                          <label htmlFor="new-audit-name">Audit name</label>
                          <input
                            id="new-audit-name"
                            name="new-audit-name"
                            required
                          />
                        </div>
                        <div className="form-field">
                          <label htmlFor="new-mfa-policy">MFA policy</label>
                          <select id="new-mfa-policy" name="new-mfa-policy">
                            <option value="optional">Optional</option>
                            <option value="required">Required</option>
                          </select>
                        </div>
                        <button type="submit">Create audited account</button>
                      </form>
                      <form
                        className="form-stack nested-form"
                        onSubmit={createRoleBundle}
                      >
                        <h5>Create role bundle</h5>
                        <div className="form-field">
                          <label htmlFor="bundle-name">Bundle name</label>
                          <input id="bundle-name" name="bundle-name" required />
                        </div>
                        <fieldset>
                          <legend>Explicit capabilities</legend>
                          {administration.capabilities.map((capability) => (
                            <label key={capability.capability_id}>
                              <input
                                name="bundle-capability"
                                type="checkbox"
                                value={capability.capability_id}
                              />
                              {capability.name}
                            </label>
                          ))}
                        </fieldset>
                        <button type="submit">
                          Create audited role bundle
                        </button>
                      </form>
                      {administration.users.length > 0 &&
                        administration.roleBundles.length > 0 && (
                          <form
                            className="form-stack nested-form"
                            onSubmit={assignRoleBundle}
                          >
                            <h5>Assign configured role bundle</h5>
                            <div className="form-field">
                              <label htmlFor="assignment-user">Account</label>
                              <select
                                id="assignment-user"
                                name="assignment-user"
                              >
                                {administration.users.map((user) => (
                                  <option
                                    key={user.user_id}
                                    value={user.user_id}
                                  >
                                    {user.display_name}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div className="form-field">
                              <label htmlFor="assignment-bundle">
                                Role bundle
                              </label>
                              <select
                                id="assignment-bundle"
                                name="assignment-bundle"
                              >
                                {administration.roleBundles.map((bundle) => (
                                  <option
                                    key={bundle.role_bundle_id}
                                    value={bundle.role_bundle_id}
                                  >
                                    {bundle.name}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <button type="submit">
                              Assign audited role bundle
                            </button>
                          </form>
                        )}
                      {administration.users.length > 0 && (
                        <form
                          className="form-stack nested-form"
                          onSubmit={prepareAdministrativeRecovery}
                        >
                          <h5>Owner-authorized account recovery</h5>
                          <p className="panel-help">
                            The server permits only Owner recovery of Manager or
                            Staff. It rejects Staff recovery of Owner or Manager
                            and does not grant Manager recovery of Staff.
                          </p>
                          <div className="form-field">
                            <label htmlFor="recovery-user">Account</label>
                            <select id="recovery-user" name="recovery-user">
                              {administration.users.map((user) => (
                                <option key={user.user_id} value={user.user_id}>
                                  {user.display_name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="form-field">
                            <label htmlFor="recovery-password">
                              New password (15–128 characters)
                            </label>
                            <input
                              autoComplete="new-password"
                              id="recovery-password"
                              maxLength={128}
                              minLength={15}
                              name="recovery-password"
                              required
                              type="password"
                            />
                          </div>
                          <div className="form-field">
                            <label htmlFor="recovery-reason">
                              Audit reason
                            </label>
                            <input
                              id="recovery-reason"
                              maxLength={128}
                              name="recovery-reason"
                              required
                            />
                          </div>
                          <label>
                            <input
                              name="recovery-reset-mfa"
                              type="checkbox"
                              value="yes"
                            />
                            Reset current MFA enrollment
                          </label>
                          <button type="submit">
                            Review recovery consequences
                          </button>
                        </form>
                      )}
                    </section>
                  )}
                </div>
              )}

              {pendingCommand !== null && (
                <div
                  aria-labelledby="confirmation-heading"
                  aria-modal="true"
                  className="confirmation-panel"
                  role="alertdialog"
                >
                  <h4 id="confirmation-heading">Confirm protected command</h4>
                  <p>
                    {pendingCommand.kind === "disable"
                      ? "Disabling this account also revokes every applicable session."
                      : pendingCommand.kind === "recover"
                        ? "Recovery changes the selected account credentials, may reset MFA, and revokes every applicable session."
                        : "This revokes every applicable session for the selected account."}{" "}
                    The server records the acting account and request for audit.
                  </p>
                  <div className="button-row">
                    <button
                      onClick={confirmAdministrativeCommand}
                      type="button"
                    >
                      Confirm command
                    </button>
                    <button
                      onClick={() => {
                        setPendingCommand(null);
                      }}
                      type="button"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </section>
          </section>
        )}
      </main>

      <footer aria-label="Build information" className="app-footer">
        {environment !== "production" && (
          <span className="environment">{environment}</span>
        )}
        <span>Build {buildId}</span>
      </footer>
    </div>
  );
}
