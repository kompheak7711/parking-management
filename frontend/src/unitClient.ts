export type UnitType =
  | "STUDIO"
  | "ONE_BEDROOM"
  | "TWO_BEDROOM"
  | "THREE_BEDROOM";

export type UnitStatus =
  | "VACANT"
  | "RESERVED"
  | "OCCUPIED"
  | "UNDER_MAINTENANCE"
  | "CLEANING"
  | "OUT_OF_SERVICE";

export interface UnitResource {
  unit_id: string;
  property_id: string;
  unit_number: string;
  floor: string;
  unit_type: UnitType;
  status: UnitStatus;
  version: number;
  current_reservation: unknown;
  current_lease: unknown;
  current_occupancy: unknown;
  active_meter_summary: unknown;
  operational_alerts: string[];
  can_manage?: boolean;
}

export interface UnitListPage {
  items: UnitResource[];
  next_cursor: string | null;
  can_manage: boolean;
}

export interface UnitTimelineEvent {
  event_id: string;
  occurred_at: string;
  actor_id: string;
  action: string;
  entity_type: string;
  reason: string;
  previous_state: unknown;
  resulting_state: unknown;
  correlation_id: string;
  outcome: string;
}

export interface UnitTimelinePage {
  items: UnitTimelineEvent[];
  next_cursor: string | null;
}

export interface UnitApi {
  list: (
    propertyId: string,
    filters?: { status?: UnitStatus; attention?: boolean; cursor?: string },
  ) => Promise<UnitListPage>;
  get: (unitId: string) => Promise<UnitResource>;
  create: (
    propertyId: string,
    source: {
      unit_number: string;
      floor: string;
      unit_type: UnitType;
      status: UnitStatus;
    },
  ) => Promise<UnitResource>;
  update: (
    unit: UnitResource,
    source: Partial<
      Pick<UnitResource, "unit_number" | "floor" | "unit_type" | "status">
    >,
  ) => Promise<UnitResource>;
  timeline: (unitId: string, cursor?: string) => Promise<UnitTimelinePage>;
}

export class UnitUnavailableError extends Error {
  constructor() {
    super("Unit management is unavailable for this session.");
    this.name = "UnitUnavailableError";
  }
}

export class UnitConflictError extends Error {
  constructor() {
    super("The Unit changed. Reload it before retrying.");
    this.name = "UnitConflictError";
  }
}

export class UnitRequestError extends Error {
  constructor() {
    super("The Unit request was not completed.");
    this.name = "UnitRequestError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
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

async function request(
  path: string,
  init: RequestInit,
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new UnitRequestError();
  }
  if (response.status === 401 || response.status === 403) {
    throw new UnitUnavailableError();
  }
  if (response.status === 409 || response.status === 412) {
    throw new UnitConflictError();
  }
  if (!response.ok) throw new UnitRequestError();
  try {
    const payload: unknown = await response.json();
    if (!isObject(payload) || !isObject(payload.data))
      throw new UnitRequestError();
    return payload.data;
  } catch (error) {
    if (error instanceof UnitRequestError) throw error;
    throw new UnitRequestError();
  }
}

function stringArray(value: unknown): string[] {
  if (
    !Array.isArray(value) ||
    !value.every((entry) => typeof entry === "string")
  ) {
    throw new UnitRequestError();
  }
  return value;
}

function unit(value: unknown): UnitResource {
  if (
    !isObject(value) ||
    typeof value.unit_id !== "string" ||
    typeof value.property_id !== "string" ||
    typeof value.unit_number !== "string" ||
    typeof value.floor !== "string" ||
    typeof value.unit_type !== "string" ||
    typeof value.status !== "string" ||
    typeof value.version !== "number"
  ) {
    throw new UnitRequestError();
  }
  const types: UnitType[] = [
    "STUDIO",
    "ONE_BEDROOM",
    "TWO_BEDROOM",
    "THREE_BEDROOM",
  ];
  const statuses: UnitStatus[] = [
    "VACANT",
    "RESERVED",
    "OCCUPIED",
    "UNDER_MAINTENANCE",
    "CLEANING",
    "OUT_OF_SERVICE",
  ];
  if (
    !types.includes(value.unit_type as UnitType) ||
    !statuses.includes(value.status as UnitStatus)
  ) {
    throw new UnitRequestError();
  }
  return {
    unit_id: value.unit_id,
    property_id: value.property_id,
    unit_number: value.unit_number,
    floor: value.floor,
    unit_type: value.unit_type as UnitType,
    status: value.status as UnitStatus,
    version: value.version,
    current_reservation: value.current_reservation ?? null,
    current_lease: value.current_lease ?? null,
    current_occupancy: value.current_occupancy ?? null,
    active_meter_summary: value.active_meter_summary ?? null,
    operational_alerts: stringArray(value.operational_alerts),
    can_manage:
      typeof value.can_manage === "boolean" ? value.can_manage : undefined,
  };
}

function mutationHeaders(version?: number): HeadersInit {
  const token = csrfToken();
  if (token === null || token.length === 0) throw new UnitRequestError();
  return {
    "Content-Type": "application/json",
    "X-CSRF-Token": token,
    ...(version === undefined ? {} : { "If-Match": `"${String(version)}"` }),
  };
}

async function list(
  propertyId: string,
  filters: { status?: UnitStatus; attention?: boolean; cursor?: string } = {},
): Promise<UnitListPage> {
  const query = new URLSearchParams();
  if (filters.status !== undefined) query.set("status", filters.status);
  if (filters.attention !== undefined)
    query.set("attention", String(filters.attention));
  if (filters.cursor !== undefined) query.set("cursor", filters.cursor);
  const suffix = query.size === 0 ? "" : `?${query.toString()}`;
  const data = await request(
    `/properties/${encodeURIComponent(propertyId)}/units${suffix}`,
    { method: "GET" },
  );
  if (
    !Array.isArray(data.items) ||
    (data.next_cursor !== null && typeof data.next_cursor !== "string") ||
    typeof data.can_manage !== "boolean"
  ) {
    throw new UnitRequestError();
  }
  return {
    items: data.items.map(unit),
    next_cursor: data.next_cursor,
    can_manage: data.can_manage,
  };
}

async function get(unitId: string): Promise<UnitResource> {
  return unit(
    await request(`/units/${encodeURIComponent(unitId)}`, { method: "GET" }),
  );
}

async function create(
  propertyId: string,
  source: {
    unit_number: string;
    floor: string;
    unit_type: UnitType;
    status: UnitStatus;
  },
): Promise<UnitResource> {
  return unit(
    await request(`/properties/${encodeURIComponent(propertyId)}/units`, {
      method: "POST",
      headers: mutationHeaders(),
      body: JSON.stringify(source),
    }),
  );
}

async function update(
  current: UnitResource,
  source: Partial<
    Pick<UnitResource, "unit_number" | "floor" | "unit_type" | "status">
  >,
): Promise<UnitResource> {
  return unit(
    await request(`/units/${encodeURIComponent(current.unit_id)}`, {
      method: "PATCH",
      headers: mutationHeaders(current.version),
      body: JSON.stringify(source),
    }),
  );
}

async function timeline(
  unitId: string,
  cursor?: string,
): Promise<UnitTimelinePage> {
  const suffix =
    cursor === undefined ? "" : `?cursor=${encodeURIComponent(cursor)}`;
  const data = await request(
    `/units/${encodeURIComponent(unitId)}/timeline${suffix}`,
    {
      method: "GET",
    },
  );
  if (
    !Array.isArray(data.items) ||
    (data.next_cursor !== null && typeof data.next_cursor !== "string")
  ) {
    throw new UnitRequestError();
  }
  const items = data.items.map((value): UnitTimelineEvent => {
    if (
      !isObject(value) ||
      typeof value.event_id !== "string" ||
      typeof value.occurred_at !== "string" ||
      typeof value.actor_id !== "string" ||
      typeof value.action !== "string" ||
      typeof value.entity_type !== "string" ||
      typeof value.reason !== "string" ||
      typeof value.correlation_id !== "string" ||
      typeof value.outcome !== "string"
    ) {
      throw new UnitRequestError();
    }
    return {
      event_id: value.event_id,
      occurred_at: value.occurred_at,
      actor_id: value.actor_id,
      action: value.action,
      entity_type: value.entity_type,
      reason: value.reason,
      previous_state: value.previous_state ?? null,
      resulting_state: value.resulting_state ?? null,
      correlation_id: value.correlation_id,
      outcome: value.outcome,
    };
  });
  return { items, next_cursor: data.next_cursor };
}

export const unitApi: UnitApi = { list, get, create, update, timeline };
