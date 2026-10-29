// V1-058 R2a: a Unit Type is a code from the Property's Unit Types list (DL-075 answer 10).
export type UnitType = string;

export type UnitSetupListKind =
  | "FLOOR"
  | "UNIT_TYPE"
  | "VIEW"
  | "KITCHEN"
  | "ROOM_FEATURE";

export const unitSetupListKinds: UnitSetupListKind[] = [
  "FLOOR",
  "UNIT_TYPE",
  "VIEW",
  "KITCHEN",
  "ROOM_FEATURE",
];

export interface UnitSetupItem {
  item_id: string;
  list_kind: UnitSetupListKind;
  code: string;
  name_en: string;
  name_km: string | null;
  sort_order: number;
  removed: boolean;
  in_use: boolean;
  version: number;
}

export interface UnitSetupLists {
  lists: Record<UnitSetupListKind, UnitSetupItem[]>;
  can_manage: boolean;
}

// DL-078 answer 1: optional Unit details. Size is sent and returned as text such as "42.50".
export interface UnitDetails {
  size_square_metres: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  view_item_id: string | null;
  kitchen_item_id: string | null;
  notes: string | null;
  room_feature_ids: string[];
}

// DL-078 answer 2: the items in a Unit, each with a quantity, in four groups. Every save is a new
// numbered record kept in History; record number 0 means nothing was saved yet.
export type UnitInventoryGroup =
  | "FURNITURE"
  | "APPLIANCES"
  | "KITCHEN"
  | "BATHROOM";

export const unitInventoryGroups: UnitInventoryGroup[] = [
  "FURNITURE",
  "APPLIANCES",
  "KITCHEN",
  "BATHROOM",
];

export interface UnitInventoryLine {
  item_group: UnitInventoryGroup;
  item_name: string;
  quantity: number;
}

export interface UnitInventory {
  unit_id: string;
  record_number: number;
  recorded_at: string | null;
  recorded_by: string | null;
  lines: UnitInventoryLine[];
  counts: Record<UnitInventoryGroup, number>;
  can_manage: boolean;
}

export interface UnitInventoryItemName {
  item_group: UnitInventoryGroup;
  item_name: string;
}

export interface UnitCreateSource extends Partial<UnitDetails> {
  unit_number: string;
  floor_item_id: string;
  unit_type: UnitType;
  status: UnitStatus;
}

// The Unit number cannot change after creation (owner, 2026-10-24).
// `reason` is the Change status reason; it is written to the Unit's History (V1-058 R2).
export type UnitUpdateSource = Partial<
  Pick<UnitResource, "floor_item_id" | "unit_type" | "status"> &
    UnitDetails & { reason: string }
>;

export type UnitStatus =
  | "VACANT"
  | "RESERVED"
  | "OCCUPIED"
  | "UNDER_MAINTENANCE"
  | "CLEANING"
  | "OUT_OF_SERVICE";

export interface UnitResource extends UnitDetails {
  unit_id: string;
  property_id: string;
  unit_number: string;
  floor: string;
  floor_item_id: string | null;
  unit_type: UnitType;
  status: UnitStatus;
  version: number;
  current_reservation: unknown;
  current_lease: unknown;
  current_occupancy: unknown;
  active_meter_summary: unknown;
  operational_alerts: string[];
  can_manage?: boolean;
  /** V1-061 (DL-110): the Rent a new Reservation or Lease draft starts at, in cents. */
  default_monthly_rent_usd_cents?: number | null;
  /** V1-061 (DL-110): the Services every new Lease draft of the Unit holds. */
  required_service_ids?: string[];
}

export interface UnitRentTermsSource {
  default_monthly_rent_usd_cents: number | null;
  required_service_ids: string[];
  /** Parking Step 3: a price change is a money action, so it says why (kept in History). */
  reason: string;
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
  /** Parking Step 3: the display name of who did it, when the server knows it. */
  actor_name?: string | null;
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
    source: UnitCreateSource,
  ) => Promise<UnitResource>;
  update: (
    unit: UnitResource,
    source: UnitUpdateSource,
  ) => Promise<UnitResource>;
  timeline: (unitId: string, cursor?: string) => Promise<UnitTimelinePage>;
  setupLists: (
    propertyId: string,
    options?: { includeRemoved?: boolean },
  ) => Promise<UnitSetupLists>;
  createSetupItem: (
    propertyId: string,
    source: {
      list_kind: UnitSetupListKind;
      name_en: string;
      name_km?: string | null;
      sort_order?: number;
    },
  ) => Promise<UnitSetupItem>;
  updateSetupItem: (
    item: UnitSetupItem,
    source: Partial<Pick<UnitSetupItem, "name_en" | "name_km" | "sort_order">>,
  ) => Promise<UnitSetupItem>;
  removeSetupItem: (item: UnitSetupItem) => Promise<UnitSetupItem>;
  inventory: (unitId: string) => Promise<UnitInventory>;
  saveInventory: (
    current: UnitInventory,
    lines: UnitInventoryLine[],
  ) => Promise<UnitInventory>;
  inventoryItems: (propertyId: string) => Promise<UnitInventoryItemName[]>;
  /** V1-061 (DL-110): a Manager or the Owner sets the default Rent and required Services. */
  setRentTerms: (
    current: UnitResource,
    source: UnitRentTermsSource,
  ) => Promise<UnitResource>;
}

export class UnitUnavailableError extends Error {
  constructor() {
    super("Parking management is unavailable for this session.");
    this.name = "UnitUnavailableError";
  }
}

export class UnitConflictError extends Error {
  constructor() {
    super("The Parking changed. Reload it before retrying.");
    this.name = "UnitConflictError";
  }
}

export class UnitRequestError extends Error {
  constructor() {
    super("The Parking request was not completed.");
    this.name = "UnitRequestError";
  }
}

export class UnitInvalidError extends Error {
  constructor() {
    super(
      "Check the Parking details. The Parking number may already be used, or a list item may have been removed.",
    );
    this.name = "UnitInvalidError";
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
  if (response.status === 422) throw new UnitInvalidError();
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

function nullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

function nullableNumber(value: unknown): value is number | null | undefined {
  return (
    value === undefined ||
    value === null ||
    (typeof value === "number" && Number.isInteger(value))
  );
}

function setupItem(value: unknown): UnitSetupItem {
  if (
    !isObject(value) ||
    typeof value.item_id !== "string" ||
    typeof value.list_kind !== "string" ||
    !unitSetupListKinds.includes(value.list_kind as UnitSetupListKind) ||
    typeof value.code !== "string" ||
    typeof value.name_en !== "string" ||
    !nullableString(value.name_km) ||
    typeof value.sort_order !== "number" ||
    typeof value.removed !== "boolean" ||
    typeof value.in_use !== "boolean" ||
    typeof value.version !== "number"
  ) {
    throw new UnitRequestError();
  }
  return {
    item_id: value.item_id,
    list_kind: value.list_kind as UnitSetupListKind,
    code: value.code,
    name_en: value.name_en,
    name_km: value.name_km ?? null,
    sort_order: value.sort_order,
    removed: value.removed,
    in_use: value.in_use,
    version: value.version,
  };
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
    typeof value.version !== "number" ||
    !nullableString(value.floor_item_id) ||
    !nullableString(value.size_square_metres) ||
    !nullableNumber(value.bedrooms) ||
    !nullableNumber(value.bathrooms) ||
    !nullableString(value.view_item_id) ||
    !nullableString(value.kitchen_item_id) ||
    !nullableString(value.notes) ||
    !nullableNumber(value.default_monthly_rent_usd_cents)
  ) {
    throw new UnitRequestError();
  }
  const statuses: UnitStatus[] = [
    "VACANT",
    "RESERVED",
    "OCCUPIED",
    "UNDER_MAINTENANCE",
    "CLEANING",
    "OUT_OF_SERVICE",
  ];
  if (
    !/^[A-Z0-9][A-Z0-9_]{0,39}$/.test(value.unit_type) ||
    !statuses.includes(value.status as UnitStatus)
  ) {
    throw new UnitRequestError();
  }
  return {
    unit_id: value.unit_id,
    property_id: value.property_id,
    unit_number: value.unit_number,
    floor: value.floor,
    floor_item_id: value.floor_item_id ?? null,
    unit_type: value.unit_type,
    status: value.status as UnitStatus,
    version: value.version,
    size_square_metres: value.size_square_metres ?? null,
    bedrooms: value.bedrooms ?? null,
    bathrooms: value.bathrooms ?? null,
    view_item_id: value.view_item_id ?? null,
    kitchen_item_id: value.kitchen_item_id ?? null,
    notes: value.notes ?? null,
    room_feature_ids: stringArray(value.room_feature_ids ?? []),
    current_reservation: value.current_reservation ?? null,
    current_lease: value.current_lease ?? null,
    current_occupancy: value.current_occupancy ?? null,
    active_meter_summary: value.active_meter_summary ?? null,
    operational_alerts: stringArray(value.operational_alerts),
    can_manage:
      typeof value.can_manage === "boolean" ? value.can_manage : undefined,
    default_monthly_rent_usd_cents:
      value.default_monthly_rent_usd_cents ?? null,
    required_service_ids: stringArray(value.required_service_ids ?? []),
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
  source: UnitCreateSource,
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
  source: UnitUpdateSource,
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

async function setupLists(
  propertyId: string,
  options: { includeRemoved?: boolean } = {},
): Promise<UnitSetupLists> {
  const suffix = options.includeRemoved === true ? "?include_removed=true" : "";
  const data = await request(
    `/properties/${encodeURIComponent(propertyId)}/unit-setup${suffix}`,
    { method: "GET" },
  );
  if (!isObject(data.lists) || typeof data.can_manage !== "boolean") {
    throw new UnitRequestError();
  }
  const source = data.lists;
  const lists = Object.fromEntries(
    unitSetupListKinds.map((kind) => {
      const entries = source[kind];
      if (!Array.isArray(entries)) throw new UnitRequestError();
      const items = entries.map(setupItem);
      if (items.some((item) => item.list_kind !== kind)) {
        throw new UnitRequestError();
      }
      return [kind, items];
    }),
  ) as Record<UnitSetupListKind, UnitSetupItem[]>;
  return { lists, can_manage: data.can_manage };
}

async function createSetupItem(
  propertyId: string,
  source: {
    list_kind: UnitSetupListKind;
    name_en: string;
    name_km?: string | null;
    sort_order?: number;
  },
): Promise<UnitSetupItem> {
  return setupItem(
    await request(
      `/properties/${encodeURIComponent(propertyId)}/unit-setup/items`,
      {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify(source),
      },
    ),
  );
}

async function updateSetupItem(
  current: UnitSetupItem,
  source: Partial<Pick<UnitSetupItem, "name_en" | "name_km" | "sort_order">>,
): Promise<UnitSetupItem> {
  return setupItem(
    await request(`/unit-setup/items/${encodeURIComponent(current.item_id)}`, {
      method: "PATCH",
      headers: mutationHeaders(current.version),
      body: JSON.stringify(source),
    }),
  );
}

async function removeSetupItem(current: UnitSetupItem): Promise<UnitSetupItem> {
  return setupItem(
    await request(
      `/unit-setup/items/${encodeURIComponent(current.item_id)}/remove`,
      { method: "POST", headers: mutationHeaders(current.version) },
    ),
  );
}

function inventoryGroup(value: unknown): UnitInventoryGroup {
  if (
    typeof value !== "string" ||
    !unitInventoryGroups.includes(value as UnitInventoryGroup)
  ) {
    throw new UnitRequestError();
  }
  return value as UnitInventoryGroup;
}

function inventoryLine(value: unknown): UnitInventoryLine {
  if (
    !isObject(value) ||
    typeof value.item_name !== "string" ||
    typeof value.quantity !== "number" ||
    !Number.isInteger(value.quantity)
  ) {
    throw new UnitRequestError();
  }
  return {
    item_group: inventoryGroup(value.item_group),
    item_name: value.item_name,
    quantity: value.quantity,
  };
}

function inventoryOf(data: Record<string, unknown>): UnitInventory {
  if (
    typeof data.unit_id !== "string" ||
    typeof data.record_number !== "number" ||
    !nullableString(data.recorded_at) ||
    !nullableString(data.recorded_by) ||
    !Array.isArray(data.lines) ||
    !isObject(data.counts) ||
    typeof data.can_manage !== "boolean"
  ) {
    throw new UnitRequestError();
  }
  const source = data.counts;
  const counts = Object.fromEntries(
    unitInventoryGroups.map((group) => {
      const count = source[group];
      if (typeof count !== "number") throw new UnitRequestError();
      return [group, count];
    }),
  ) as Record<UnitInventoryGroup, number>;
  return {
    unit_id: data.unit_id,
    record_number: data.record_number,
    recorded_at: data.recorded_at ?? null,
    recorded_by: data.recorded_by ?? null,
    lines: data.lines.map(inventoryLine),
    counts,
    can_manage: data.can_manage,
  };
}

async function inventory(unitId: string): Promise<UnitInventory> {
  return inventoryOf(
    await request(`/units/${encodeURIComponent(unitId)}/inventory`, {
      method: "GET",
    }),
  );
}

async function saveInventory(
  current: UnitInventory,
  lines: UnitInventoryLine[],
): Promise<UnitInventory> {
  return inventoryOf(
    await request(`/units/${encodeURIComponent(current.unit_id)}/inventory`, {
      method: "PUT",
      headers: mutationHeaders(current.record_number),
      body: JSON.stringify({ lines }),
    }),
  );
}

async function setRentTerms(
  current: UnitResource,
  source: UnitRentTermsSource,
): Promise<UnitResource> {
  return unit(
    await request(`/units/${encodeURIComponent(current.unit_id)}/rent-terms`, {
      method: "PUT",
      headers: mutationHeaders(current.version),
      body: JSON.stringify(source),
    }),
  );
}

async function inventoryItems(
  propertyId: string,
): Promise<UnitInventoryItemName[]> {
  const data = await request(
    `/properties/${encodeURIComponent(propertyId)}/unit-inventory-items`,
    { method: "GET" },
  );
  if (!Array.isArray(data.items)) throw new UnitRequestError();
  return data.items.map((value): UnitInventoryItemName => {
    if (!isObject(value) || typeof value.item_name !== "string") {
      throw new UnitRequestError();
    }
    return {
      item_group: inventoryGroup(value.item_group),
      item_name: value.item_name,
    };
  });
}

export const unitApi: UnitApi = {
  list,
  get,
  create,
  update,
  timeline,
  setupLists,
  createSetupItem,
  updateSetupItem,
  removeSetupItem,
  inventory,
  saveInventory,
  inventoryItems,
  setRentTerms,
};
