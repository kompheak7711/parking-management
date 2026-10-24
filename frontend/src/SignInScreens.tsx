import {
  ChangeEvent,
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import logoUrl from "./assets/brand/CHETANA_Logo_Horizontal_Reverse.svg";
import {
  AuthenticationApi,
  AuthenticationData,
  PasswordRuleError,
  RateLimitedError,
  ServiceUnavailableError,
} from "./authClient";
import {
  Language,
  TextKey,
  storeLanguage,
  storedLanguage,
  translate,
} from "./signInText";
import "./signIn.css";

// Login sub-slice L6: the full-screen sign-in layer from the owner's mock-up. Nothing of the app
// is shown or reachable behind it. Passwords, codes and the set-up key live only in this
// component's state for the step that needs them; nothing goes to storage or the address bar.

/** Why the sign-in layer opened: a fresh start, a sign-out, or a session that ended. */
export type SignInEntry =
  | { kind: "sign_in"; signedOut?: boolean; note?: string | null }
  | { kind: "idle" | "day"; note?: string | null };

type View =
  | "signin"
  | "code"
  | "forgot"
  | "newpw"
  | "setup"
  | "codes"
  | "out"
  | "day";

type Field =
  | "username"
  | "password"
  | "code"
  | "recovery"
  | "newPassword"
  | "newPasswordAgain"
  | "setupCode"
  | "kept";

// Passwords and codes are read from the box itself, never kept in React state: React writes a
// controlled box's text into its HTML `value` attribute (review round 1).
type SecretField = Exclude<Field, "username" | "kept">;

interface Message {
  key: TextKey;
  argument?: number;
}

const FIELD_IDS: Record<Field, string> = {
  username: "sign-in-username",
  password: "sign-in-password",
  code: "sign-in-code",
  recovery: "sign-in-recovery-code",
  newPassword: "sign-in-new-password",
  newPasswordAgain: "sign-in-new-password-again",
  setupCode: "sign-in-setup-code",
  kept: "sign-in-codes-kept",
};

// The server's pre-authentication step: 5 minutes for a sign-in code, 10 for a new password.
const CODE_STEP_MILLISECONDS = 5 * 60 * 1000;
const PASSWORD_STEP_MILLISECONDS = 10 * 60 * 1000;
const MAX_CODE_LENGTH = 256;

/** Characters as the server counts them: Unicode code points after NFC. */
export function passwordLength(value: string): number {
  // Code points are what the server counts, so emoji sequences count as several.
  return Array.from(value.normalize("NFC")).length;
}

/** The Base32 secret of an `otpauth://totp/` link, in groups of four for typing by hand. */
export function setupKey(provisioningUri: string): string {
  let secret: string | null = null;
  try {
    secret = new URL(provisioningUri).searchParams.get("secret");
  } catch {
    secret = null;
  }
  if (secret === null) return "";
  return (secret.match(/.{1,4}/g) ?? []).join(" ");
}

function waitMessage(seconds: number): Message {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return minutes === 1
    ? { key: "au_e_wait_1" }
    : { key: "au_e_wait_n", argument: minutes };
}

function Icon({ name }: { name: "people" | "phone" | "clock" | "lock" }) {
  const paths = {
    people:
      "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0M17 11a3 3 0 1 0 0-6M22 20a5 5 0 0 0-4-4.9",
    phone:
      "M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Zm4 17h2",
    clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Zm0-15v5l3 2",
    lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  };
  return (
    <svg
      aria-hidden="true"
      fill="none"
      focusable="false"
      height="18"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      width="18"
    >
      <path d={paths[name]} />
    </svg>
  );
}

export interface SignInScreensProps {
  api: AuthenticationApi;
  entry: SignInEntry;
  now: () => number;
  /** The server said the sign-in is complete; `message` greets the person in their language. */
  onAuthenticated: (result: AuthenticationData, message: string) => void;
  /** A sign-in was sent; a session restore still running must not open the app any more. */
  onSignInStarted?: () => void;
  footer?: ReactNode;
}

export function SignInScreens({
  api,
  entry,
  now,
  onAuthenticated,
  onSignInStarted,
  footer,
}: SignInScreensProps) {
  const [language, setLanguage] = useState<Language>(storedLanguage);
  const [view, setView] = useState<View>(
    entry.kind === "idle" ? "out" : entry.kind === "day" ? "day" : "signin",
  );
  const [username, setUsername] = useState("");
  const inputs = useRef<Partial<Record<SecretField, HTMLInputElement | null>>>(
    {},
  );
  // Only the shape of a new password is kept, for the rule list.
  const [newPasswordShape, setNewPasswordShape] = useState({
    length: 0,
    same: false,
  });
  const [pending, setPending] = useState(false);
  const [kept, setKept] = useState(false);
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const [codeMethod, setCodeMethod] = useState<"totp" | "recovery_code">(
    "totp",
  );
  const [errors, setErrors] = useState<Partial<Record<Field, TextKey>>>({});
  const [alert, setAlert] = useState<Message | null>(null);
  const [notes, setNotes] = useState<TextKey[]>(
    entry.kind === "sign_in" && entry.signedOut === true
      ? ["au_signed_out"]
      : [],
  );
  const [entryNote, setEntryNote] = useState<string | null>(entry.note ?? null);
  const [enrollment, setEnrollment] = useState<{
    qr: string;
    key: string;
  } | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [copied, setCopied] = useState(false);
  const [focus, setFocus] = useState<{ target: string; sequence: number }>({
    target: "heading",
    sequence: 0,
  });
  const heldResult = useRef<AuthenticationData | null>(null);
  const stepEndsAt = useRef<number | null>(null);
  const busy = useRef(false);
  // Raised by "Back to sign in": an answer to an older request is dropped (review round 1).
  const generation = useRef(0);
  const mounted = useRef(true);
  // Read through a function: an answer may arrive after the layer was closed.
  const alive = () => mounted.current;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const alertRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
    return () => {
      document.documentElement.lang = "en";
    };
  }, [language]);

  useLayoutEffect(() => {
    if (
      focus.sequence === 0 &&
      focus.target === "heading" &&
      view === "signin"
    ) {
      // The first screen: the username box is where the person starts typing.
      document.getElementById(FIELD_IDS.username)?.focus();
      return;
    }
    if (focus.target === "heading") headingRef.current?.focus();
    else if (focus.target === "alert") alertRef.current?.focus();
    else document.getElementById(focus.target)?.focus();
  }, [focus, view]);

  const t = useCallback(
    (key: TextKey, argument?: string | number) =>
      translate(language, key, argument),
    [language],
  );

  function moveFocus(target: string) {
    setFocus((current) => ({ target, sequence: current.sequence + 1 }));
  }

  function edited(field: Exclude<Field, "kept">) {
    setErrors((current) =>
      current[field] === undefined
        ? current
        : { ...current, [field]: undefined },
    );
    if (field === "newPassword" || field === "newPasswordAgain") {
      const value = secret("newPassword");
      setNewPasswordShape({
        length: passwordLength(value),
        same: value.length > 0 && value === secret("newPasswordAgain"),
      });
    }
  }

  function secret(field: SecretField): string {
    return inputs.current[field]?.value ?? "";
  }

  function clearSecrets(fields: SecretField[]) {
    for (const field of fields) {
      const input = inputs.current[field];
      if (input !== null && input !== undefined) input.value = "";
    }
    if (fields.includes("newPassword")) {
      setNewPasswordShape({ length: 0, same: false });
    }
  }

  /** A request starts; the returned check says whether its answer may still be used. */
  function start(): () => boolean {
    busy.current = true;
    setPending(true);
    const mine = generation.current;
    return () => alive() && generation.current === mine;
  }

  function settle(current: () => boolean) {
    if (!current()) return;
    busy.current = false;
    setPending(false);
  }

  function open(next: View, noteKeys: TextKey[] = []) {
    setView(next);
    setErrors({});
    setAlert(null);
    setNotes(noteKeys);
    setShown({});
    setCopied(false);
    moveFocus(next === "code" ? FIELD_IDS.code : "heading");
  }

  function backToSignIn(message: Message | null = null) {
    generation.current += 1;
    busy.current = false;
    setPending(false);
    stepEndsAt.current = null;
    heldResult.current = null;
    setEnrollment(null);
    setRecoveryCodes(null);
    setKept(false);
    setCodeMethod("totp");
    setEntryNote(null);
    clearSecrets([
      "password",
      "code",
      "recovery",
      "newPassword",
      "newPasswordAgain",
      "setupCode",
    ]);
    open("signin");
    if (message !== null) {
      setAlert(message);
      moveFocus("alert");
    }
  }

  function showAlert(message: Message) {
    setAlert(message);
    moveFocus("alert");
  }

  function stepEnded(): boolean {
    return stepEndsAt.current !== null && now() >= stepEndsAt.current;
  }

  /** One message for a refused try; the same whatever the reason (the screens never say whether
   * an account exists). */
  function refused(error: unknown, wrong: TextKey) {
    if (error instanceof RateLimitedError) {
      showAlert(waitMessage(error.retryAfterSeconds));
    } else if (error instanceof ServiceUnavailableError) {
      showAlert({ key: "au_e_offline" });
    } else if (stepEnded()) {
      backToSignIn({ key: "au_e_step_time" });
    } else {
      showAlert({ key: wrong });
    }
  }

  function finish(result: AuthenticationData, noteKeys: TextKey[]) {
    stepEndsAt.current = null;
    heldResult.current = null;
    setEnrollment(null);
    setRecoveryCodes(null);
    const displayName = result.session?.display_name?.trim() ?? "";
    const name = displayName.length > 0 ? displayName : username.trim();
    const message = [
      t("au_welcome", name),
      ...noteKeys.map((key) => t(key)),
    ].join(" ");
    onAuthenticated(result, message);
  }

  function beginSetup() {
    const mine = generation.current;
    const current = () => alive() && generation.current === mine;
    void api
      .beginMfaEnrollment()
      .then((material) => {
        if (!current()) return;
        setEnrollment({
          qr: material.qr_code_svg,
          key: setupKey(material.provisioning_uri),
        });
      })
      .catch((error: unknown) => {
        if (!current()) return;
        // The set-up material is given once per sign-in, so the person signs in again
        // (review round 1: no screen without a QR code and no way on).
        backToSignIn(
          error instanceof RateLimitedError
            ? waitMessage(error.retryAfterSeconds)
            : error instanceof ServiceUnavailableError
              ? { key: "au_e_offline" }
              : { key: "au_e_step_time" },
        );
      });
  }

  /** Follow the next step the server gives; the app opens only when the server says so. */
  function continueWith(result: AuthenticationData, noteKeys: TextKey[]) {
    if (result.phase === "authenticated") {
      finish(result, noteKeys);
      return;
    }
    if (result.phase === "password_change_required") {
      stepEndsAt.current = now() + PASSWORD_STEP_MILLISECONDS;
      open("newpw", noteKeys);
      return;
    }
    stepEndsAt.current = now() + CODE_STEP_MILLISECONDS;
    setCodeMethod("totp");
    if (result.phase === "mfa_required") {
      open("code", noteKeys);
      return;
    }
    setEnrollment(null);
    open("setup", noteKeys);
    beginSetup();
  }

  function invalid(
    found: Partial<Record<Field, TextKey>>,
    order: Field[],
  ): boolean {
    const first = order.find((field) => found[field] !== undefined);
    if (first === undefined) return false;
    setErrors(found);
    setAlert(null);
    moveFocus(FIELD_IDS[first]);
    return true;
  }

  function submitSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const password = secret("password");
    const found: Partial<Record<Field, TextKey>> = {};
    if (username.trim().length === 0) found.username = "au_e_user";
    if (password.length === 0) found.password = "au_e_pw";
    if (invalid(found, ["username", "password"])) return;
    const current = start();
    onSignInStarted?.();
    setNotes([]);
    setEntryNote(null);
    void api
      .signIn({ username, password })
      .then((result) => {
        if (!current()) return;
        clearSecrets(["password"]);
        continueWith(result, []);
      })
      .catch((error: unknown) => {
        if (!current()) return;
        clearSecrets(["password"]);
        refused(error, "au_e_wrong");
      })
      .finally(() => {
        settle(current);
      });
  }

  function submitCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const recovery = codeMethod === "recovery_code";
    const code = recovery
      ? secret("recovery").trim()
      : secret("code").replace(/\s/g, "");
    if (recovery) {
      if (
        invalid(
          code.length === 0 || code.length > MAX_CODE_LENGTH
            ? { recovery: "au_e_rc" }
            : {},
          ["recovery"],
        )
      ) {
        return;
      }
    } else if (
      invalid(/^\d{6}$/.test(code) ? {} : { code: "au_e_code" }, ["code"])
    ) {
      return;
    }
    const current = start();
    void api
      .completeMfa({ method: codeMethod, code })
      .then((result) => {
        if (!current()) return;
        clearSecrets(["code", "recovery"]);
        continueWith(result, recovery ? ["au_rc_used"] : []);
      })
      .catch((error: unknown) => {
        if (!current()) return;
        clearSecrets(["code", "recovery"]);
        refused(error, recovery ? "au_e_rc_bad" : "au_e_code_bad");
      })
      .finally(() => {
        settle(current);
      });
  }

  function submitNewPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const newPassword = secret("newPassword");
    const length = passwordLength(newPassword);
    const found: Partial<Record<Field, TextKey>> = {};
    if (length < 15) found.newPassword = "au_e_short";
    else if (length > 128) found.newPassword = "au_e_long";
    else if (newPassword !== secret("newPasswordAgain"))
      found.newPasswordAgain = "au_e_same";
    if (invalid(found, ["newPassword", "newPasswordAgain"])) return;
    const current = start();
    void api
      .changePassword(newPassword)
      .then((result) => {
        if (!current()) return;
        clearSecrets(["newPassword", "newPasswordAgain"]);
        continueWith(result, ["au_np_done"]);
      })
      .catch((error: unknown) => {
        if (!current()) return;
        clearSecrets(["newPassword", "newPasswordAgain"]);
        if (error instanceof PasswordRuleError) {
          invalid({ newPassword: "au_e_common" }, ["newPassword"]);
        } else if (error instanceof RateLimitedError) {
          refused(error, "au_e_np_unknown");
        } else {
          // The change may have been saved before a later step failed (L4 review round 1).
          backToSignIn({ key: "au_e_np_unknown" });
        }
      })
      .finally(() => {
        settle(current);
      });
  }

  function submitSetup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const code = secret("setupCode").replace(/\s/g, "");
    if (
      invalid(/^\d{6}$/.test(code) ? {} : { setupCode: "au_e_code" }, [
        "setupCode",
      ])
    )
      return;
    const current = start();
    void api
      .confirmMfaEnrollment(code)
      .then(async (result) => {
        if (!current()) return;
        clearSecrets(["setupCode"]);
        setEnrollment(null);
        if (result.phase !== "authenticated") {
          continueWith(result, []);
          return;
        }
        stepEndsAt.current = null;
        try {
          // The confirmed set-up counts as a reauthentication, which the first codes need.
          const codes = await api.issueRecoveryCodes();
          if (!current()) return;
          heldResult.current = result;
          setRecoveryCodes(codes.codes);
          setKept(false);
          open("codes");
        } catch {
          if (!current()) return;
          finish(result, ["au_rcs_none"]);
        }
      })
      .catch((error: unknown) => {
        if (!current()) return;
        clearSecrets(["setupCode"]);
        refused(error, "au_e_code_bad");
      })
      .finally(() => {
        settle(current);
      });
  }

  function submitCodesKept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!kept) {
      invalid({ kept: "au_rcs_e" }, ["kept"]);
      return;
    }
    const result = heldResult.current;
    setRecoveryCodes(null);
    if (result !== null) finish(result, []);
  }

  function copyCodes() {
    if (recoveryCodes === null) return;
    const clipboard = navigator.clipboard as Clipboard | undefined;
    if (clipboard === undefined) return;
    void clipboard.writeText(recoveryCodes.join("\n")).then(
      () => {
        if (mounted.current) setCopied(true);
      },
      () => undefined,
    );
  }

  function chooseLanguage(next: Language) {
    setLanguage(next);
    storeLanguage(next);
  }

  function describedBy(field: Field, help?: string): string | undefined {
    const ids = [
      help,
      errors[field] !== undefined ? `${FIELD_IDS[field]}-error` : undefined,
    ]
      .filter((id): id is string => id !== undefined)
      .join(" ");
    return ids.length > 0 ? ids : undefined;
  }

  function fieldError(field: Field) {
    const key = errors[field];
    return key === undefined ? null : (
      <p className="sign-in-field-error" id={`${FIELD_IDS[field]}-error`}>
        {t(key)}
      </p>
    );
  }

  function textField(
    field: "username" | "code" | "recovery" | "setupCode",
    label: TextKey,
    help?: TextKey,
  ) {
    const id = FIELD_IDS[field];
    const helpId = help === undefined ? undefined : `${id}-help`;
    const numeric = field === "code" || field === "setupCode";
    // The username is not secret, so its box alone is controlled.
    const content =
      field === "username"
        ? {
            value: username,
            onChange: (event: ChangeEvent<HTMLInputElement>) => {
              setUsername(event.target.value);
              edited(field);
            },
          }
        : {
            ref: (input: HTMLInputElement | null) => {
              inputs.current[field] = input;
            },
            onChange: () => {
              edited(field);
            },
          };
    // A key per field, so a view never reuses another field's box (review round 2: the code
    // box kept the username).
    return (
      <div className="sign-in-field" key={field}>
        <label htmlFor={id}>{t(label)}</label>
        <input
          aria-describedby={describedBy(field, helpId)}
          aria-invalid={errors[field] !== undefined}
          autoCapitalize="off"
          autoComplete={field === "username" ? "username" : "one-time-code"}
          className={
            numeric ? "sign-in-input sign-in-code-input" : "sign-in-input"
          }
          id={id}
          inputMode={numeric ? "numeric" : "text"}
          maxLength={numeric ? 7 : MAX_CODE_LENGTH}
          spellCheck={false}
          type="text"
          {...content}
        />
        {help !== undefined && (
          <p className="sign-in-help" id={helpId}>
            {t(help)}
          </p>
        )}
        {fieldError(field)}
      </div>
    );
  }

  function passwordField(
    field: "password" | "newPassword" | "newPasswordAgain",
    label: TextKey,
    autoComplete: "current-password" | "new-password",
    help?: TextKey,
  ) {
    const id = FIELD_IDS[field];
    const helpId = help === undefined ? undefined : `${id}-help`;
    const visible = shown[field] === true;
    return (
      <div className="sign-in-field" key={field}>
        <label htmlFor={id}>{t(label)}</label>
        <div className="sign-in-password-row">
          <input
            aria-describedby={describedBy(field, helpId)}
            aria-invalid={errors[field] !== undefined}
            autoCapitalize="off"
            autoComplete={autoComplete}
            className="sign-in-input"
            id={id}
            onChange={() => {
              edited(field);
            }}
            ref={(input) => {
              inputs.current[field] = input;
            }}
            spellCheck={false}
            type={visible ? "text" : "password"}
          />
          <button
            aria-label={t(visible ? "au_hide_l" : "au_show_l")}
            aria-pressed={visible}
            className="sign-in-button sign-in-show"
            onClick={() => {
              setShown((current) => ({ ...current, [field]: !visible }));
            }}
            type="button"
          >
            {t(visible ? "au_hide" : "au_show")}
          </button>
        </div>
        {help !== undefined && (
          <p className="sign-in-help" id={helpId}>
            {t(help)}
          </p>
        )}
        {fieldError(field)}
      </div>
    );
  }

  function backLink() {
    return (
      <p className="sign-in-links">
        <button
          className="sign-in-link"
          onClick={() => {
            backToSignIn();
          }}
          type="button"
        >
          {t("au_back_signin")}
        </button>
      </p>
    );
  }

  function submitButton(label: TextKey) {
    return (
      <button
        aria-disabled={pending}
        className="sign-in-button sign-in-primary"
        type="submit"
      >
        {t(pending ? "au_working" : label)}
      </button>
    );
  }

  function heading(key: TextKey) {
    return (
      <h1 id="sign-in-heading" ref={headingRef} tabIndex={-1}>
        {t(key)}
      </h1>
    );
  }

  function messages() {
    return (
      <>
        {entryNote !== null && (
          <p className="sign-in-notice" role="status">
            {entryNote}
          </p>
        )}
        {notes.length > 0 && (
          <div className="sign-in-notice sign-in-notice-ok" role="status">
            {notes.map((key) => (
              <p key={key}>{t(key)}</p>
            ))}
          </div>
        )}
        {alert !== null && (
          <div
            className="sign-in-alert"
            ref={alertRef}
            role="alert"
            tabIndex={-1}
          >
            {t(alert.key, alert.argument)}
          </div>
        )}
      </>
    );
  }

  function screenBody() {
    if (view === "signin") {
      return (
        <>
          {heading("au_signin")}
          <p className="sign-in-muted">{t("au_signin_s")}</p>
          {messages()}
          <form
            aria-busy={pending}
            className="sign-in-form"
            noValidate
            onSubmit={submitSignIn}
          >
            {textField("username", "au_user")}
            {passwordField("password", "au_pw", "current-password")}
            {submitButton("au_signin")}
          </form>
          <p className="sign-in-links">
            <button
              className="sign-in-link"
              onClick={() => {
                setEntryNote(null);
                clearSecrets(["password"]);
                open("forgot");
              }}
              type="button"
            >
              {t("au_forgot")}
            </button>
          </p>
        </>
      );
    }
    if (view === "code") {
      const recovery = codeMethod === "recovery_code";
      return (
        <>
          {heading("au_code_t")}
          <p className="sign-in-muted">
            {t(recovery ? "au_rc_h" : "au_code_s")}
          </p>
          {messages()}
          <form
            aria-busy={pending}
            className="sign-in-form"
            noValidate
            onSubmit={submitCode}
          >
            {recovery
              ? textField("recovery", "au_rc")
              : textField("code", "au_code", "au_code_h")}
            {submitButton("au_verify")}
          </form>
          <p className="sign-in-links">
            <button
              className="sign-in-link"
              onClick={() => {
                setCodeMethod(recovery ? "totp" : "recovery_code");
                clearSecrets(["code", "recovery"]);
                setErrors({});
                setAlert(null);
                moveFocus(recovery ? FIELD_IDS.code : FIELD_IDS.recovery);
              }}
              type="button"
            >
              {t(recovery ? "au_use_app" : "au_use_rc")}
            </button>
          </p>
          {backLink()}
        </>
      );
    }
    if (view === "forgot") {
      return (
        <>
          {heading("au_fg_t")}
          <p className="sign-in-muted">{t("au_fg_s")}</p>
          <section aria-labelledby="sign-in-staff" className="sign-in-box">
            <h2 id="sign-in-staff">
              <Icon name="people" />
              {t("au_fg_staff")}
            </h2>
            <p>{t("au_fg_staff_s")}</p>
          </section>
          <section aria-labelledby="sign-in-owner" className="sign-in-box">
            <h2 id="sign-in-owner">
              <Icon name="lock" />
              {t("au_fg_owner")}
            </h2>
            <p>{t("au_fg_owner_s")}</p>
          </section>
          <p className="sign-in-small sign-in-muted">{t("au_fg_phone")}</p>
          {backLink()}
        </>
      );
    }
    if (view === "newpw") {
      const { length, same } = newPasswordShape;
      const rule = (met: boolean, label: TextKey, extra?: string) => (
        <li className={met ? "sign-in-rule-met" : undefined}>
          <span aria-hidden="true">{met ? "✓" : "•"}</span>
          <span>
            {t(label)}
            {extra !== undefined && <small> · {extra}</small>}
          </span>
        </li>
      );
      return (
        <>
          {heading("au_np_t")}
          <p className="sign-in-muted">{t("au_np_temp")}</p>
          {messages()}
          <form
            aria-busy={pending}
            className="sign-in-form"
            noValidate
            onSubmit={submitNewPassword}
          >
            {/* For password managers: the account the new password belongs to. */}
            <input
              autoComplete="username"
              hidden
              readOnly
              type="text"
              value={username}
            />
            {passwordField("newPassword", "au_new", "new-password", "au_np_h")}
            <ul className="sign-in-rules">
              {rule(length >= 15, "au_r_len", t("au_r_now", length))}
              {rule(length > 0 && length <= 128, "au_r_max")}
              {rule(false, "au_r_common", t("au_r_common_h"))}
              {rule(same, "au_r_same")}
            </ul>
            {passwordField("newPasswordAgain", "au_new2", "new-password")}
            {submitButton("au_np_save")}
          </form>
          {backLink()}
        </>
      );
    }
    if (view === "setup") {
      return (
        <>
          {heading("au_su_t")}
          <p className="sign-in-muted">{t("au_su_s")}</p>
          {messages()}
          <ol className="sign-in-steps">
            <li>
              <p>{t("au_su_1")}</p>
            </li>
            <li>
              <p>{t("au_su_2")}</p>
              {enrollment === null ? (
                <p className="sign-in-muted" role="status">
                  {t("au_su_loading")}
                </p>
              ) : (
                <div className="sign-in-qr-box">
                  <img
                    alt={t("au_su_qr")}
                    className="sign-in-qr"
                    src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(enrollment.qr)}`}
                  />
                  <div>
                    <p className="sign-in-small sign-in-muted">
                      {t("au_su_key")}
                    </p>
                    <p className="sign-in-key" lang="en">
                      {enrollment.key}
                    </p>
                  </div>
                </div>
              )}
            </li>
            <li>
              <p>{t("au_su_3")}</p>
              {enrollment !== null && (
                <form
                  aria-busy={pending}
                  className="sign-in-form"
                  noValidate
                  onSubmit={submitSetup}
                >
                  {textField("setupCode", "au_code", "au_code_h")}
                  {submitButton("au_verify")}
                </form>
              )}
            </li>
          </ol>
          {backLink()}
        </>
      );
    }
    if (view === "codes") {
      return (
        <>
          {heading("au_rcs_t")}
          <p className="sign-in-muted">{t("au_rcs_s")}</p>
          <ol
            aria-label={t("au_rcs_t")}
            className="sign-in-recovery-codes"
            lang="en"
          >
            {(recoveryCodes ?? []).map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ol>
          <div className="sign-in-notice sign-in-notice-warn">
            <Icon name="lock" />
            <p>{t("au_rcs_keep")}</p>
          </div>
          <div className="sign-in-copy">
            <button
              className="sign-in-button"
              onClick={copyCodes}
              type="button"
            >
              {t("au_rcs_copy")}
            </button>
            <p className="sign-in-small sign-in-muted" role="status">
              {copied ? t("au_rcs_copied") : ""}
            </p>
          </div>
          <form className="sign-in-form" noValidate onSubmit={submitCodesKept}>
            <div className="sign-in-field">
              <label className="sign-in-check" htmlFor={FIELD_IDS.kept}>
                <input
                  aria-describedby={describedBy("kept")}
                  aria-invalid={errors.kept !== undefined}
                  checked={kept}
                  id={FIELD_IDS.kept}
                  onChange={(event) => {
                    setKept(event.target.checked);
                    setErrors({});
                  }}
                  type="checkbox"
                />
                <span>{t("au_rcs_ok")}</span>
              </label>
              {fieldError("kept")}
            </div>
            <button className="sign-in-button sign-in-primary" type="submit">
              {t("au_rcs_go")}
            </button>
          </form>
        </>
      );
    }
    return (
      <>
        <div className="sign-in-icon">
          <Icon name="clock" />
        </div>
        {heading("au_out_t")}
        <p>{t(view === "day" ? "au_out_day" : "au_out_idle")}</p>
        <p className="sign-in-muted">{t("au_out_note")}</p>
        {entryNote !== null && (
          <p className="sign-in-notice" role="status">
            {entryNote}
          </p>
        )}
        <button
          className="sign-in-button sign-in-primary"
          onClick={() => {
            setEntryNote(null);
            open("signin");
            moveFocus(FIELD_IDS.username);
          }}
          type="button"
        >
          {t("au_again")}
        </button>
      </>
    );
  }

  return (
    <div className="sign-in-layer">
      <div className="sign-in-wrap">
        <aside className="sign-in-brand">
          <img alt="CHETANA" src={logoUrl} />
          <p className="sign-in-app" lang="en">
            {t("au_app")}
          </p>
          <p className="sign-in-where">{t("au_where")}</p>
          <ul className="sign-in-facts">
            <li>
              <Icon name="people" />
              <span>{t("au_fact1")}</span>
            </li>
            <li>
              <Icon name="phone" />
              <span>{t("au_fact2")}</span>
            </li>
            <li>
              <Icon name="clock" />
              <span>{t("au_fact3")}</span>
            </li>
          </ul>
        </aside>
        <main aria-labelledby="sign-in-heading" className="sign-in-main">
          <div className="sign-in-top">
            <div
              aria-label={t("au_lang")}
              className="sign-in-language"
              role="group"
            >
              <button
                aria-pressed={language === "km"}
                lang="km"
                onClick={() => {
                  chooseLanguage("km");
                }}
                type="button"
              >
                ខ្មែរ
              </button>
              <button
                aria-pressed={language === "en"}
                lang="en"
                onClick={() => {
                  chooseLanguage("en");
                }}
                type="button"
              >
                EN
              </button>
            </div>
          </div>
          <section className="sign-in-card">{screenBody()}</section>
          {footer}
        </main>
      </div>
    </div>
  );
}
