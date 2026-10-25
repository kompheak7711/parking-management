// V1-058 R7b-6b: the Services and Service types of Settings → Rates and services (DL-075; server
// R7b-6a). Each Service has an English and a Khmer name and a Service type; a type is "Only one
// per Lease" or "One or more". The client chooses each new record's id, so sending the same form
// again after a lost answer gives the same record back, never a second one.

export interface ServiceSetting {
  service_id: string;
  service_code: string;
  name_en: string;
  name_km: string | null;
  service_type_id: string | null;
  version: number;
  rate_today_usd_cents: number | null;
  next_rate: { monthly_rate_usd_cents: number; effective_date: string } | null;
  approval_periods: {
    approval_period_id: string;
    effective_from: string;
    effective_through: string | null;
  }[];
  leases_using: number;
}

export interface ServiceType {
  service_type_id: string;
  name_en: string;
  name_km: string | null;
  one_per_lease: boolean;
  removed: boolean;
  version: number;
  services: number;
}

export interface ServiceSettings {
  services: ServiceSetting[];
  service_types: ServiceType[];
  today: string;
  can_manage: boolean;
}

export interface NewService {
  service_id: string;
  name_en: string;
  name_km: string | null;
  service_type_id: string | null;
  monthly_rate_usd_cents: number;
  starts_on: string;
}

export interface ServiceChange {
  name_en: string;
  name_km: string | null;
  service_type_id: string | null;
  version: number;
}

export interface NewServiceType {
  service_type_id: string;
  name_en: string;
  name_km: string | null;
  one_per_lease: boolean;
}

export interface ServiceTypeChange {
  name_en: string;
  name_km: string | null;
  one_per_lease: boolean;
  version: number;
}

export interface ServiceSettingsApi {
  read: (propertyId: string) => Promise<ServiceSettings>;
  addService: (propertyId: string, body: NewService) => Promise<unknown>;
  changeService: (
    propertyId: string,
    serviceId: string,
    body: ServiceChange,
  ) => Promise<unknown>;
  addType: (propertyId: string, body: NewServiceType) => Promise<unknown>;
  changeType: (
    propertyId: string,
    typeId: string,
    body: ServiceTypeChange,
  ) => Promise<unknown>;
  removeType: (
    propertyId: string,
    typeId: string,
    version: number,
  ) => Promise<unknown>;
}

/** What went wrong, in the words the screen needs. */
export type ServiceSettingsFailure =
  | "not_allowed"
  | "invalid"
  | "not_found"
  | "out_of_date"
  | "id_reused"
  | "lease_holds_two"
  | "type_has_services"
  | "unknown";

export class ServiceSettingsError extends Error {
  constructor(readonly failure: ServiceSettingsFailure) {
    super(`Service settings request failed: ${failure}`);
    this.name = "ServiceSettingsError";
  }
}

const CODES: Record<string, ServiceSettingsFailure> = {
  SETTINGS_OUT_OF_DATE: "out_of_date",
  SETTINGS_ID_REUSED: "id_reused",
  LEASE_HOLDS_TWO_OF_TYPE: "lease_holds_two",
  SERVICE_TYPE_HAS_SERVICES: "type_has_services",
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

async function request(path: string, body?: object): Promise<unknown> {
  let headers: HeadersInit | undefined;
  if (body !== undefined) {
    const token = csrfToken();
    if (token === null || token === "") {
      throw new ServiceSettingsError("unknown");
    }
    headers = { "Content-Type": "application/json", "X-CSRF-Token": token };
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      credentials: "include",
      method: body === undefined ? "GET" : "POST",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ServiceSettingsError("unknown");
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.status === 401 || response.status === 403) {
    throw new ServiceSettingsError("not_allowed");
  }
  if (response.status === 404) throw new ServiceSettingsError("not_found");
  if (response.status === 422) throw new ServiceSettingsError("invalid");
  if (response.status === 409) {
    const error =
      isObject(payload) && isObject(payload.error) ? payload.error : null;
    const code = typeof error?.code === "string" ? error.code : "";
    throw new ServiceSettingsError(CODES[code] ?? "unknown");
  }
  if (!response.ok || !isObject(payload) || !("data" in payload)) {
    throw new ServiceSettingsError("unknown");
  }
  return payload.data;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new ServiceSettingsError("unknown");
  return value;
}

function textOrNull(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new ServiceSettingsError("unknown");
  }
  return value;
}

function nextOf(value: unknown): ServiceSetting["next_rate"] {
  if (value === null || value === undefined) return null;
  if (!isObject(value)) throw new ServiceSettingsError("unknown");
  return {
    monthly_rate_usd_cents: count(value.monthly_rate_usd_cents),
    effective_date: text(value.effective_date),
  };
}

function serviceOf(value: unknown): ServiceSetting {
  if (!isObject(value)) throw new ServiceSettingsError("unknown");
  const next = value.next_rate;
  const periods = value.approval_periods;
  if (!Array.isArray(periods)) throw new ServiceSettingsError("unknown");
  return {
    service_id: text(value.service_id),
    service_code: text(value.service_code),
    name_en: text(value.name_en),
    name_km: textOrNull(value.name_km),
    service_type_id: textOrNull(value.service_type_id),
    version: count(value.version),
    rate_today_usd_cents:
      value.rate_today_usd_cents === null
        ? null
        : count(value.rate_today_usd_cents),
    next_rate: nextOf(next),
    approval_periods: periods.map((period: unknown) => {
      if (!isObject(period)) throw new ServiceSettingsError("unknown");
      return {
        approval_period_id: text(period.approval_period_id),
        effective_from: text(period.effective_from),
        effective_through: textOrNull(period.effective_through),
      };
    }),
    leases_using: count(value.leases_using),
  };
}

function typeOf(value: unknown): ServiceType {
  if (!isObject(value) || typeof value.one_per_lease !== "boolean") {
    throw new ServiceSettingsError("unknown");
  }
  return {
    service_type_id: text(value.service_type_id),
    name_en: text(value.name_en),
    name_km: textOrNull(value.name_km),
    one_per_lease: value.one_per_lease,
    removed: value.removed === true,
    version: count(value.version),
    services: count(value.services),
  };
}

/** Reads the answer of the Settings read; anything unexpected is "unknown". */
export function settingsOf(value: unknown): ServiceSettings {
  if (
    !isObject(value) ||
    !Array.isArray(value.services) ||
    !Array.isArray(value.service_types) ||
    typeof value.can_manage !== "boolean"
  ) {
    throw new ServiceSettingsError("unknown");
  }
  return {
    services: value.services.map(serviceOf),
    service_types: value.service_types.map(typeOf),
    today: text(value.today),
    can_manage: value.can_manage,
  };
}

const property = (id: string) => `/properties/${encodeURIComponent(id)}`;

export const serviceSettingsApi: ServiceSettingsApi = {
  read: async (propertyId) =>
    settingsOf(await request(`${property(propertyId)}/service-settings`)),
  addService: (propertyId, body) =>
    request(`${property(propertyId)}/services`, body),
  changeService: (propertyId, serviceId, body) =>
    request(
      `${property(propertyId)}/services/${encodeURIComponent(serviceId)}`,
      body,
    ),
  addType: (propertyId, body) =>
    request(`${property(propertyId)}/service-types`, body),
  changeType: (propertyId, typeId, body) =>
    request(
      `${property(propertyId)}/service-types/${encodeURIComponent(typeId)}`,
      body,
    ),
  removeType: (propertyId, typeId, version) =>
    request(
      `${property(propertyId)}/service-types/${encodeURIComponent(typeId)}/remove`,
      { version },
    ),
};
