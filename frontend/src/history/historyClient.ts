// V1-058 R7c: the History page reads the Property's audit events (API-AUD, audit.view). The first
// page of a new search writes its own `audit.searched` event (DL-072 answer 14); later pages do
// not. Events are never changed, so the page only reads.

export interface HistoryEvent {
  event_id: string;
  actor_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  occurred_at: string;
  business_date: string;
  reason: string;
  outcome: string;
  source: string;
  linked_source_event_id: string | null;
}

export interface HistoryFilter {
  from?: string;
  actorId?: string;
  unitId?: string;
  cursor?: string;
}

export interface HistoryPage {
  events: HistoryEvent[];
  nextCursor: string | null;
}

export interface HistoryApi {
  search: (propertyId: string, filter: HistoryFilter) => Promise<HistoryPage>;
}

export class HistoryNotAllowedError extends Error {
  constructor() {
    super("This account cannot read History.");
    this.name = "HistoryNotAllowedError";
  }
}

export class HistoryUnavailableError extends Error {
  constructor() {
    super("History could not be read.");
    this.name = "HistoryUnavailableError";
  }
}

const PAGE_SIZE = 50;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new HistoryUnavailableError();
  return value;
}

function event(value: unknown): HistoryEvent {
  if (!isObject(value)) throw new HistoryUnavailableError();
  const linked = value.linked_source_event_id;
  return {
    event_id: text(value.event_id),
    actor_id: text(value.actor_id),
    action: text(value.action),
    resource_type: text(value.resource_type),
    resource_id: text(value.resource_id),
    occurred_at: text(value.occurred_at),
    business_date: text(value.business_date),
    reason: text(value.reason),
    outcome: text(value.outcome),
    source: text(value.source),
    linked_source_event_id: linked === null ? null : text(linked),
  };
}

async function search(
  propertyId: string,
  filter: HistoryFilter,
): Promise<HistoryPage> {
  const query = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (filter.from !== undefined) query.set("from_date", filter.from);
  if (filter.actorId !== undefined) query.set("actor_id", filter.actorId);
  if (filter.unitId !== undefined) query.set("unit_id", filter.unitId);
  if (filter.cursor !== undefined) query.set("cursor", filter.cursor);
  let response: Response;
  try {
    response = await fetch(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/audit-events?${query.toString()}`,
      { credentials: "include", headers: { Accept: "application/json" } },
    );
  } catch {
    throw new HistoryUnavailableError();
  }
  if (response.status === 401 || response.status === 403) {
    throw new HistoryNotAllowedError();
  }
  if (!response.ok) throw new HistoryUnavailableError();
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new HistoryUnavailableError();
  }
  if (
    !isObject(payload) ||
    !Array.isArray(payload.data) ||
    !isObject(payload.meta)
  ) {
    throw new HistoryUnavailableError();
  }
  const next = payload.meta.next_cursor;
  return {
    events: payload.data.map(event),
    nextCursor: typeof next === "string" && next !== "" ? next : null,
  };
}

export const historyApi: HistoryApi = { search };
