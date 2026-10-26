// V1-058 R3 Move-out: the move-out record of a Lease (the hand-back). A record says when the
// tenants left and what the Unit needs before it is let again; it creates no charge. Records
// are never changed: a correction is a new record that names the one it replaces.

export type UnitCondition = "CLEANING" | "UNDER_MAINTENANCE" | "OUT_OF_SERVICE";

export interface MoveOutOccupancy {
  occupancy_id: string;
  customer_id: string;
  move_out_date: string | null;
}

export interface MoveOutRecord {
  event_id: string;
  lease_id: string;
  termination_event_id: string;
  actual_move_out_date: string;
  unit_condition: UnitCondition;
  resulting_unit_status: string;
  reason: string;
  evidence_reference: string;
  supersedes_event_id: string | null;
  occurred_at: string;
  actor_id: string;
  /** Read pages only: a later record replaced this one. */
  event_status?: "CURRENT" | "SUPERSEDED";
  occupancies: MoveOutOccupancy[];
}

export interface OpenOccupancy {
  occupancy_id: string;
  customer_id: string;
  move_in_date: string;
  version: number;
}

export interface MoveOutPage {
  items: MoveOutRecord[];
  total: number;
  /** The Lease's Occupancies with no move-out date yet (at most 20). */
  open_occupancies: OpenOccupancy[];
}

export interface MoveOutSource {
  event_id: string;
  termination_event_id: string;
  expected_lease_version: number;
  expected_unit_version: number;
  actual_move_out_date: string;
  unit_condition: UnitCondition;
  occupancies: { occupancy_id: string; expected_version: number }[];
  reason: string;
  authorization_reference: string;
  evidence_reference: string;
  supersedes_event_id: string | null;
}

export interface InspectionFinding {
  id: string;
  ordinal: number;
  description: string;
  pet_related: boolean;
}

/** A move-out inspection: what was found. It charges nothing (BR-MOVEOUT-006). */
export interface MoveOutInspection {
  id: string;
  lease_id: string;
  inspection_date: string;
  result_text: string;
  evidence_reference: string;
  reason: string;
  completed_at: string;
  supersedes_inspection_id: string | null;
  current_effect: "INSPECTION_ONLY" | "SUPERSEDED";
  findings: InspectionFinding[];
}

export interface InspectionPage {
  items: MoveOutInspection[];
  total: number;
}

export interface InspectionSource {
  inspection_id: string;
  expected_lease_version: number;
  inspection_date: string;
  result_text: string;
  authorization_reference: string;
  evidence_reference: string;
  reason: string;
  findings: { finding_id: string; description: string; pet_related: boolean }[];
  supersedes_inspection_id: string | null;
}

export interface MoveOutApi {
  read: (propertyId: string, leaseId: string) => Promise<MoveOutPage>;
  record: (
    propertyId: string,
    leaseId: string,
    source: MoveOutSource,
    key: string,
  ) => Promise<MoveOutRecord>;
  /** Oldest first, 20 a page. Needs leases.read. */
  inspections: (
    propertyId: string,
    leaseId: string,
    offset: number,
  ) => Promise<InspectionPage>;
  /** Needs leases.inspect. A correction names the inspection it replaces. */
  inspect: (
    propertyId: string,
    leaseId: string,
    source: InspectionSource,
    key: string,
  ) => Promise<MoveOutInspection>;
}

/** The Lease, the Unit or an Occupancy changed meanwhile, or the key was used for other values. */
export class MoveOutConflictError extends Error {
  constructor() {
    super("The move-out sources changed meanwhile.");
    this.name = "MoveOutConflictError";
  }
}

/** No answer: the request may or may not have been saved. */
export class MoveOutUnavailableError extends Error {
  constructor() {
    super("The move-out service did not answer.");
    this.name = "MoveOutUnavailableError";
  }
}

/** Not signed in, not allowed, or not found (a read without leases.read answers 404). */
export class MoveOutNotAllowedError extends Error {
  constructor() {
    super("This account cannot use this move-out record.");
    this.name = "MoveOutNotAllowedError";
  }
}

export class MoveOutRequestError extends Error {
  constructor() {
    super("The move-out request was not completed.");
    this.name = "MoveOutRequestError";
  }
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const value = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (value === undefined) throw new MoveOutRequestError();
  return decodeURIComponent(value.slice(prefix.length));
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function request(path: string, init: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    response = await fetch(path, { credentials: "include", ...init, headers });
  } catch {
    throw new MoveOutUnavailableError();
  }
  if ([401, 403, 404].includes(response.status))
    throw new MoveOutNotAllowedError();
  if (response.status === 409) throw new MoveOutConflictError();
  if (response.status >= 500) throw new MoveOutUnavailableError();
  if (!response.ok) throw new MoveOutRequestError();
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new MoveOutUnavailableError();
  }
  // Answered but unreadable: a change may be saved, so it is no answer, never a refusal.
  if (!isObject(value) || !isObject(value.data))
    throw new MoveOutUnavailableError();
  return value.data;
}

function record(value: unknown): MoveOutRecord {
  if (
    !isObject(value) ||
    typeof value.event_id !== "string" ||
    typeof value.actual_move_out_date !== "string" ||
    !Array.isArray(value.occupancies)
  )
    throw new MoveOutRequestError();
  return value as unknown as MoveOutRecord;
}

function inspection(value: unknown): MoveOutInspection {
  if (
    !isObject(value) ||
    typeof value.id !== "string" ||
    typeof value.inspection_date !== "string" ||
    typeof value.completed_at !== "string" ||
    !Array.isArray(value.findings)
  )
    throw new MoveOutRequestError();
  return value as unknown as MoveOutInspection;
}

const leasePath = (propertyId: string, leaseId: string) =>
  `/api/v1/properties/${encodeURIComponent(propertyId)}/leases/${encodeURIComponent(leaseId)}`;
const path = (propertyId: string, leaseId: string) =>
  `${leasePath(propertyId, leaseId)}/move-outs`;
const inspectionsPath = (propertyId: string, leaseId: string) =>
  `${leasePath(propertyId, leaseId)}/move-out-inspections`;

function post(path: string, source: unknown, key: string): Promise<unknown> {
  return request(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": key,
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify(source),
  });
}

export const moveOutApi: MoveOutApi = {
  read: async (propertyId, leaseId) => {
    const found = await request(`${path(propertyId, leaseId)}?limit=20`, {
      method: "GET",
    });
    if (
      !isObject(found) ||
      !Array.isArray(found.items) ||
      !Array.isArray(found.open_occupancies) ||
      typeof found.total !== "number"
    )
      throw new MoveOutRequestError();
    return {
      items: found.items.map(record),
      total: found.total,
      open_occupancies: found.open_occupancies as OpenOccupancy[],
    };
  },
  record: async (propertyId, leaseId, source, key) => {
    const saved = await post(path(propertyId, leaseId), source, key);
    try {
      return record(saved);
    } catch {
      // Answered but unreadable: it may be saved, so Try again sends the same request.
      throw new MoveOutUnavailableError();
    }
  },
  inspections: async (propertyId, leaseId, offset) => {
    const found = await request(
      `${inspectionsPath(propertyId, leaseId)}?limit=20&offset=${String(offset)}`,
      { method: "GET" },
    );
    if (
      !isObject(found) ||
      !Array.isArray(found.items) ||
      typeof found.total !== "number"
    )
      throw new MoveOutRequestError();
    return { items: found.items.map(inspection), total: found.total };
  },
  inspect: async (propertyId, leaseId, source, key) => {
    const saved = await post(inspectionsPath(propertyId, leaseId), source, key);
    try {
      return inspection(saved);
    } catch {
      // Answered but unreadable: it may be saved, so Try again sends the same request.
      throw new MoveOutUnavailableError();
    }
  },
};
