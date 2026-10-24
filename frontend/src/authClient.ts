export type AuthenticationPhase =
  | "authenticated"
  | "mfa_required"
  | "mfa_enrollment_required"
  | "password_change_required";

export type MfaMethod = "totp" | "recovery_code";

export interface SessionData {
  actor_id: string;
  authenticated_at: string;
  last_activity_at: string;
  idle_expires_at: string;
  absolute_expires_at: string;
  mfa_assurance: "none" | "totp" | "recovery_code";
  reauthenticated_at: string | null;
}

export interface AuthenticationData {
  phase: AuthenticationPhase;
  session: SessionData | null;
}

interface ResponseMeta {
  request_id: string;
}

interface AuthenticationResponse {
  data: AuthenticationData;
  meta: ResponseMeta;
}

interface SessionResponse {
  data: SessionData;
  meta: ResponseMeta;
}

export interface MfaEnrollmentData {
  method: "totp";
  provisioning_uri: string;
}

export interface RecoveryCodeSetData {
  set_id: string;
  codes: string[];
}

interface MfaEnrollmentResponse {
  data: MfaEnrollmentData;
  meta: ResponseMeta;
}

interface RecoveryCodeSetResponse {
  data: RecoveryCodeSetData;
  meta: ResponseMeta;
}

export interface LocalCredentials {
  username: string;
  password: string;
}

export interface MfaChallenge {
  method: MfaMethod;
  code: string;
}

export interface ReauthenticationRequest {
  password: string;
  second_factor?: MfaChallenge;
}

export type LocalSignIn = (
  credentials: LocalCredentials,
) => Promise<AuthenticationData>;

export interface AuthenticationApi {
  signIn: LocalSignIn;
  changePassword: (newPassword: string) => Promise<AuthenticationData>;
  completeMfa: (challenge: MfaChallenge) => Promise<AuthenticationData>;
  beginMfaEnrollment: () => Promise<MfaEnrollmentData>;
  confirmMfaEnrollment: (code: string) => Promise<AuthenticationData>;
  inspectSession: () => Promise<SessionData>;
  reauthenticate: (request: ReauthenticationRequest) => Promise<SessionData>;
  issueRecoveryCodes: () => Promise<RecoveryCodeSetData>;
  regenerateRecoveryCodes: (priorSetId: string) => Promise<RecoveryCodeSetData>;
  logout: () => Promise<void>;
}

export const AUTHENTICATION_ERROR_MESSAGE =
  "Unable to sign in. Check your credentials and try again. If you still need help, contact your administrator.";

const authenticationPhases: ReadonlySet<string> = new Set([
  "authenticated",
  "mfa_required",
  "mfa_enrollment_required",
  "password_change_required",
]);

// Login sub-slice L4: the server's one rule for every new password.
export const PASSWORD_RULE_MESSAGE =
  "Choose a password of 15 to 128 characters that is not a common password, not your name and not the one-time password.";

export class AuthenticationError extends Error {
  constructor() {
    super(AUTHENTICATION_ERROR_MESSAGE);
    this.name = "AuthenticationError";
  }
}

export class SessionExpiredError extends AuthenticationError {
  constructor() {
    super();
    this.name = "SessionExpiredError";
  }
}

/** A new password the server refused by its rule (422 `PASSWORD_RULE`). */
export class PasswordRuleError extends Error {
  constructor() {
    super(PASSWORD_RULE_MESSAGE);
    this.name = "PasswordRuleError";
  }
}

async function isPasswordRuleRefusal(response: Response): Promise<boolean> {
  if (response.status !== 422) return false;
  try {
    const body: unknown = await response.json();
    return (
      typeof body === "object" &&
      body !== null &&
      "error" in body &&
      typeof body.error === "object" &&
      body.error !== null &&
      "code" in body.error &&
      body.error.code === "PASSWORD_RULE"
    );
  } catch {
    return false;
  }
}

function isResponseMeta(value: unknown): value is ResponseMeta {
  return (
    typeof value === "object" &&
    value !== null &&
    "request_id" in value &&
    typeof value.request_id === "string"
  );
}

function isSessionData(value: unknown): value is SessionData {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const session = value as Record<string, unknown>;
  return (
    typeof session.actor_id === "string" &&
    typeof session.authenticated_at === "string" &&
    typeof session.last_activity_at === "string" &&
    typeof session.idle_expires_at === "string" &&
    typeof session.absolute_expires_at === "string" &&
    (session.mfa_assurance === "none" ||
      session.mfa_assurance === "totp" ||
      session.mfa_assurance === "recovery_code") &&
    (session.reauthenticated_at === null ||
      typeof session.reauthenticated_at === "string")
  );
}

function isAuthenticationResponse(
  value: unknown,
): value is AuthenticationResponse {
  if (
    typeof value !== "object" ||
    value === null ||
    !("data" in value) ||
    !("meta" in value) ||
    !isResponseMeta(value.meta)
  ) {
    return false;
  }
  const data = value.data;
  if (typeof data !== "object" || data === null) {
    return false;
  }
  const authenticationData = data as Record<string, unknown>;
  if (
    typeof authenticationData.phase !== "string" ||
    !authenticationPhases.has(authenticationData.phase)
  ) {
    return false;
  }
  if (authenticationData.phase === "authenticated") {
    return isSessionData(authenticationData.session);
  }
  return authenticationData.session === null;
}

function isSessionResponse(value: unknown): value is SessionResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "data" in value &&
    "meta" in value &&
    isSessionData(value.data) &&
    isResponseMeta(value.meta)
  );
}

function isMfaEnrollmentResponse(
  value: unknown,
): value is MfaEnrollmentResponse {
  if (
    typeof value !== "object" ||
    value === null ||
    !("data" in value) ||
    !("meta" in value) ||
    !isResponseMeta(value.meta)
  ) {
    return false;
  }
  const data = value.data;
  return (
    typeof data === "object" &&
    data !== null &&
    "method" in data &&
    data.method === "totp" &&
    "provisioning_uri" in data &&
    typeof data.provisioning_uri === "string" &&
    data.provisioning_uri.startsWith("otpauth://totp/")
  );
}

function isRecoveryCodeSetResponse(
  value: unknown,
): value is RecoveryCodeSetResponse {
  if (
    typeof value !== "object" ||
    value === null ||
    !("data" in value) ||
    !("meta" in value) ||
    !isResponseMeta(value.meta)
  ) {
    return false;
  }
  const data = value.data;
  return (
    typeof data === "object" &&
    data !== null &&
    "set_id" in data &&
    typeof data.set_id === "string" &&
    "codes" in data &&
    Array.isArray(data.codes) &&
    data.codes.length > 0 &&
    data.codes.length <= 20 &&
    data.codes.every(
      (code) =>
        typeof code === "string" && code.length > 0 && code.length <= 256,
    ) &&
    new Set(data.codes).size === data.codes.length
  );
}

function csrfToken(cookie = document.cookie): string | null {
  const prefix = "__Host-prm_csrf=";
  const entry = cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return entry === undefined
    ? null
    : decodeURIComponent(entry.slice(prefix.length));
}

function mutationHeaders(jsonBody: boolean): HeadersInit {
  const token = csrfToken();
  if (token === null || token.length === 0) {
    throw new AuthenticationError();
  }
  return {
    ...(jsonBody ? { "Content-Type": "application/json" } : {}),
    "X-CSRF-Token": token,
  };
}

async function requestJson(
  path: string,
  init: RequestInit,
  fetchImplementation: typeof fetch,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImplementation(path, init);
  } catch {
    throw new AuthenticationError();
  }
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/v1/auth/login") {
      throw new SessionExpiredError();
    }
    if (
      path === "/api/v1/auth/password-change" &&
      (await isPasswordRuleRefusal(response))
    ) {
      throw new PasswordRuleError();
    }
    throw new AuthenticationError();
  }
  try {
    return await response.json();
  } catch {
    throw new AuthenticationError();
  }
}

export async function signIn(
  credentials: LocalCredentials,
  fetchImplementation: typeof fetch = fetch,
): Promise<AuthenticationData> {
  const payload = await requestJson(
    "/api/v1/auth/login",
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
    },
    fetchImplementation,
  );
  if (!isAuthenticationResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

/** Login sub-slice L4: replaces a one-time password before the sign-in continues. */
export async function changePassword(
  newPassword: string,
  fetchImplementation: typeof fetch = fetch,
): Promise<AuthenticationData> {
  const payload = await requestJson(
    "/api/v1/auth/password-change",
    {
      method: "POST",
      credentials: "include",
      headers: mutationHeaders(true),
      body: JSON.stringify({ new_password: newPassword }),
    },
    fetchImplementation,
  );
  if (!isAuthenticationResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

export async function completeMfa(
  challenge: MfaChallenge,
  fetchImplementation: typeof fetch = fetch,
): Promise<AuthenticationData> {
  const payload = await requestJson(
    "/api/v1/auth/mfa/challenge",
    {
      method: "POST",
      credentials: "include",
      headers: mutationHeaders(true),
      body: JSON.stringify(challenge),
    },
    fetchImplementation,
  );
  if (!isAuthenticationResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

export async function beginMfaEnrollment(
  fetchImplementation: typeof fetch = fetch,
): Promise<MfaEnrollmentData> {
  const payload = await requestJson(
    "/api/v1/auth/mfa/enrollment",
    {
      method: "POST",
      credentials: "include",
      headers: mutationHeaders(false),
    },
    fetchImplementation,
  );
  if (!isMfaEnrollmentResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

export async function confirmMfaEnrollment(
  code: string,
  fetchImplementation: typeof fetch = fetch,
): Promise<AuthenticationData> {
  const payload = await requestJson(
    "/api/v1/auth/mfa/enrollment/confirm",
    {
      method: "POST",
      credentials: "include",
      headers: mutationHeaders(true),
      body: JSON.stringify({ code }),
    },
    fetchImplementation,
  );
  if (!isAuthenticationResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

export async function inspectSession(
  fetchImplementation: typeof fetch = fetch,
): Promise<SessionData> {
  const payload = await requestJson(
    "/api/v1/auth/session",
    { method: "GET", credentials: "include" },
    fetchImplementation,
  );
  if (!isSessionResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

export async function reauthenticate(
  request: ReauthenticationRequest,
  fetchImplementation: typeof fetch = fetch,
): Promise<SessionData> {
  const payload = await requestJson(
    "/api/v1/auth/reauthenticate",
    {
      method: "POST",
      credentials: "include",
      headers: mutationHeaders(true),
      body: JSON.stringify(request),
    },
    fetchImplementation,
  );
  if (!isSessionResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

export async function issueRecoveryCodes(
  fetchImplementation: typeof fetch = fetch,
): Promise<RecoveryCodeSetData> {
  const payload = await requestJson(
    "/api/v1/auth/recovery-codes",
    {
      method: "POST",
      credentials: "include",
      headers: mutationHeaders(false),
    },
    fetchImplementation,
  );
  if (!isRecoveryCodeSetResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

export async function regenerateRecoveryCodes(
  priorSetId: string,
  fetchImplementation: typeof fetch = fetch,
): Promise<RecoveryCodeSetData> {
  const payload = await requestJson(
    "/api/v1/auth/recovery-codes/regenerate",
    {
      method: "POST",
      credentials: "include",
      headers: mutationHeaders(true),
      body: JSON.stringify({ prior_set_id: priorSetId }),
    },
    fetchImplementation,
  );
  if (!isRecoveryCodeSetResponse(payload)) {
    throw new AuthenticationError();
  }
  return payload.data;
}

export async function logout(
  fetchImplementation: typeof fetch = fetch,
): Promise<void> {
  let response: Response;
  try {
    response = await fetchImplementation("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: mutationHeaders(false),
    });
  } catch {
    throw new AuthenticationError();
  }
  if (!response.ok && response.status !== 401) {
    throw new AuthenticationError();
  }
}

export const authenticationApi: AuthenticationApi = {
  signIn,
  changePassword,
  completeMfa,
  beginMfaEnrollment,
  confirmMfaEnrollment,
  inspectSession,
  reauthenticate,
  issueRecoveryCodes,
  regenerateRecoveryCodes,
  logout,
};
