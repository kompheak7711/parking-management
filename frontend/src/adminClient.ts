export interface UserAccount {
  user_id: string;
  property_id: string;
  username: string;
  display_name: string;
  audit_name: string;
  lifecycle_state: "active" | "disabled";
  mfa_policy_class: "required" | "optional";
  version: number;
  account_class: "owner" | "manager" | "staff" | null;
  settings_access: boolean;
}

export interface Capability {
  capability_id: string;
  name: string;
  description: string;
}

export interface RoleBundle {
  role_bundle_id: string;
  property_id: string;
  name: string;
  capability_ids: string[];
  version: number;
}

export interface AuthorizationHistoryEvent {
  event_id: string;
  property_id: string;
  occurred_at: string;
  action: string;
  actor_id: string;
  target_id: string;
  outcome: "completed" | "rejected";
}

/** A one-time password the server made (login sub-slice L4): shown once, never stored. */
export interface OneTimePassword {
  value: string;
  expires_at: string;
}

export interface CreatedUserAccount {
  account: UserAccount;
  one_time_password: OneTimePassword;
}

export interface AdministrativeRecoveryResult {
  user_id: string;
  password_changed: boolean;
  mfa_reset: boolean;
  sessions_revoked: number;
  one_time_password: OneTimePassword;
}

export interface AccessAdministrationSnapshot {
  users: UserAccount[];
  capabilities: Capability[];
  roleBundles: RoleBundle[];
  authorizationHistory: AuthorizationHistoryEvent[];
}

export interface NewUser {
  username: string;
  display_name: string;
  audit_name: string;
  account_class: "manager" | "staff";
}

export interface NewRoleBundle {
  name: string;
  capability_ids: string[];
}

export interface AccessAdministrationApi {
  load: (propertyId: string) => Promise<AccessAdministrationSnapshot>;
  createUser: (
    propertyId: string,
    user: NewUser,
  ) => Promise<CreatedUserAccount>;
  disableUser: (user: UserAccount) => Promise<UserAccount>;
  revokeSessions: (userId: string) => Promise<number>;
  createRoleBundle: (
    propertyId: string,
    roleBundle: NewRoleBundle,
  ) => Promise<RoleBundle>;
  assignRoleBundle: (userId: string, roleBundleId: string) => Promise<void>;
  administrativelyRecoverUser: (
    userId: string,
    request: { reset_mfa: boolean; reason: string },
  ) => Promise<AdministrativeRecoveryResult>;
}

export class AdministrationUnavailableError extends Error {
  constructor() {
    super("Account administration is unavailable for this session.");
    this.name = "AdministrationUnavailableError";
  }
}

export class AdministrationError extends Error {
  constructor() {
    super("The administrative command was not completed.");
    this.name = "AdministrationError";
  }
}

function csrfToken(): string | null {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return entry === undefined
    ? null
    : decodeURIComponent(entry.slice(prefix.length));
}

function mutationHeaders(extra: HeadersInit = {}): HeadersInit {
  const token = csrfToken();
  if (token === null || token.length === 0) {
    throw new AdministrationError();
  }
  const headers = new Headers(extra);
  headers.set("Content-Type", "application/json");
  headers.set("X-CSRF-Token", token);
  return headers;
}

async function request(path: string, init: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new AdministrationError();
  }
  if (response.status === 401 || response.status === 403) {
    throw new AdministrationUnavailableError();
  }
  if (!response.ok) {
    throw new AdministrationError();
  }
  try {
    return await response.json();
  } catch {
    throw new AdministrationError();
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function responseMeta(value: unknown): boolean {
  return isObject(value) && typeof value.request_id === "string";
}

function collectionPage(value: unknown): {
  items: unknown[];
  nextCursor: string | null;
} {
  if (
    !isObject(value) ||
    !("data" in value) ||
    !Array.isArray(value.data) ||
    !("meta" in value) ||
    !responseMeta(value.meta) ||
    !("page" in value) ||
    !isObject(value.page) ||
    !("next_cursor" in value.page) ||
    (value.page.next_cursor !== null &&
      typeof value.page.next_cursor !== "string") ||
    typeof value.page.limit !== "number"
  ) {
    throw new AdministrationError();
  }
  return { items: value.data, nextCursor: value.page.next_cursor };
}

function oneData(value: unknown): Record<string, unknown> {
  if (
    !isObject(value) ||
    !("data" in value) ||
    !isObject(value.data) ||
    !("meta" in value) ||
    !responseMeta(value.meta)
  ) {
    throw new AdministrationError();
  }
  return value.data;
}

async function loadCollection(path: string): Promise<unknown[]> {
  const items: unknown[] = [];
  const observedCursors = new Set<string>();
  let cursor: string | null = null;
  for (let pageNumber = 0; pageNumber < 100; pageNumber += 1) {
    const separator = path.includes("?") ? "&" : "?";
    const payload = await request(
      `${path}${separator}limit=100${cursor === null ? "" : `&cursor=${encodeURIComponent(cursor)}`}`,
      { method: "GET" },
    );
    const page = collectionPage(payload);
    items.push(...page.items);
    if (page.nextCursor === null) return items;
    if (observedCursors.has(page.nextCursor)) throw new AdministrationError();
    observedCursors.add(page.nextCursor);
    cursor = page.nextCursor;
  }
  throw new AdministrationError();
}

function userAccount(value: unknown): UserAccount {
  if (!isObject(value)) throw new AdministrationError();
  const lifecycle = value.lifecycle_state;
  const mfaPolicy = value.mfa_policy_class;
  const accountClass = value.account_class;
  if (
    typeof value.user_id !== "string" ||
    typeof value.property_id !== "string" ||
    typeof value.username !== "string" ||
    typeof value.display_name !== "string" ||
    typeof value.audit_name !== "string" ||
    (lifecycle !== "active" && lifecycle !== "disabled") ||
    (mfaPolicy !== "required" && mfaPolicy !== "optional") ||
    typeof value.version !== "number" ||
    (accountClass !== "owner" &&
      accountClass !== "manager" &&
      accountClass !== "staff" &&
      accountClass !== null) ||
    typeof value.settings_access !== "boolean"
  ) {
    throw new AdministrationError();
  }
  return {
    user_id: value.user_id,
    property_id: value.property_id,
    username: value.username,
    display_name: value.display_name,
    audit_name: value.audit_name,
    lifecycle_state: lifecycle,
    mfa_policy_class: mfaPolicy,
    version: value.version,
    account_class: accountClass,
    settings_access: value.settings_access,
  };
}

function oneTimePassword(value: unknown): OneTimePassword {
  if (
    !isObject(value) ||
    typeof value.value !== "string" ||
    value.value.length === 0 ||
    value.value.length > 256 ||
    typeof value.expires_at !== "string"
  ) {
    throw new AdministrationError();
  }
  return { value: value.value, expires_at: value.expires_at };
}

function capability(value: unknown): Capability {
  if (
    !isObject(value) ||
    typeof value.capability_id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.description !== "string"
  ) {
    throw new AdministrationError();
  }
  return {
    capability_id: value.capability_id,
    name: value.name,
    description: value.description,
  };
}

function roleBundle(value: unknown): RoleBundle {
  if (
    !isObject(value) ||
    typeof value.role_bundle_id !== "string" ||
    typeof value.property_id !== "string" ||
    typeof value.name !== "string" ||
    !Array.isArray(value.capability_ids) ||
    !value.capability_ids.every((item) => typeof item === "string") ||
    typeof value.version !== "number"
  ) {
    throw new AdministrationError();
  }
  return {
    role_bundle_id: value.role_bundle_id,
    property_id: value.property_id,
    name: value.name,
    capability_ids: value.capability_ids,
    version: value.version,
  };
}

function authorizationHistoryEvent(value: unknown): AuthorizationHistoryEvent {
  if (!isObject(value)) throw new AdministrationError();
  const outcome = value.outcome;
  if (
    typeof value.event_id !== "string" ||
    typeof value.property_id !== "string" ||
    typeof value.occurred_at !== "string" ||
    typeof value.action !== "string" ||
    typeof value.actor_id !== "string" ||
    typeof value.target_id !== "string" ||
    (outcome !== "completed" && outcome !== "rejected")
  ) {
    throw new AdministrationError();
  }
  return {
    event_id: value.event_id,
    property_id: value.property_id,
    occurred_at: value.occurred_at,
    action: value.action,
    actor_id: value.actor_id,
    target_id: value.target_id,
    outcome,
  };
}

export const accessAdministrationApi: AccessAdministrationApi = {
  async load(propertyId) {
    const encoded = encodeURIComponent(propertyId);
    const [users, capabilities, roleBundles, authorizationHistory] =
      await Promise.all([
        loadCollection(`/api/v1/properties/${encoded}/users`),
        loadCollection("/api/v1/capabilities"),
        loadCollection(`/api/v1/properties/${encoded}/role-bundles`),
        loadCollection(`/api/v1/properties/${encoded}/authorization-history`),
      ]);
    return {
      users: users.map(userAccount),
      capabilities: capabilities.map(capability),
      roleBundles: roleBundles.map(roleBundle),
      authorizationHistory: authorizationHistory.map(authorizationHistoryEvent),
    };
  },

  async createUser(propertyId, user) {
    const payload = await request(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/users`,
      {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify(user),
      },
    );
    const account = userAccount(oneData(payload));
    if (!isObject(payload)) throw new AdministrationError();
    return {
      account,
      one_time_password: oneTimePassword(payload.one_time_password),
    };
  },

  async disableUser(user) {
    const payload = await request(
      `/api/v1/users/${encodeURIComponent(user.user_id)}`,
      {
        method: "PATCH",
        headers: mutationHeaders({ "If-Match": `"${String(user.version)}"` }),
        body: JSON.stringify({ lifecycle_state: "disabled" }),
      },
    );
    return userAccount(oneData(payload));
  },

  async revokeSessions(userId) {
    const payload = await request(
      `/api/v1/users/${encodeURIComponent(userId)}/revoke-sessions`,
      { method: "POST", headers: mutationHeaders() },
    );
    const data = oneData(payload);
    if (typeof data.sessions_revoked !== "number") {
      throw new AdministrationError();
    }
    return data.sessions_revoked;
  },

  async createRoleBundle(propertyId, bundle) {
    const payload = await request(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/role-bundles`,
      {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify(bundle),
      },
    );
    return roleBundle(oneData(payload));
  },

  async assignRoleBundle(userId, roleBundleId) {
    await request(
      `/api/v1/users/${encodeURIComponent(userId)}/role-assignments`,
      {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify({ role_bundle_id: roleBundleId }),
      },
    );
  },

  async administrativelyRecoverUser(userId, recoveryRequest) {
    const payload = await request(
      `/api/v1/users/${encodeURIComponent(userId)}/administrative-recovery`,
      {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify(recoveryRequest),
      },
    );
    const data = oneData(payload);
    if (
      typeof data.user_id !== "string" ||
      typeof data.password_changed !== "boolean" ||
      typeof data.mfa_reset !== "boolean" ||
      typeof data.sessions_revoked !== "number"
    ) {
      throw new AdministrationError();
    }
    return {
      user_id: data.user_id,
      password_changed: data.password_changed,
      mfa_reset: data.mfa_reset,
      sessions_revoked: data.sessions_revoked,
      one_time_password: oneTimePassword(data.one_time_password),
    };
  },
};
