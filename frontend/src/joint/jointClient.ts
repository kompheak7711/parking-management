// DL-201, DL-243: the Joint Inspection at move-in and move-out. Staff mark every place and item
// Good, Broken or Missing, count the keys, write the meter numbers and take photos; the tenant
// signs on the tablet first, then the staff member. The server checks every right and rule;
// this client only reads and sends.

export type JointKind = "MOVE_IN" | "MOVE_OUT";
export type JointStatus = "DRAFT" | "DONE" | "REPLACED";
export type JointResult = "GOOD" | "BROKEN" | "MISSING";
export type LineKind = "PLACE" | "BUILT_IN" | "ITEM";
export type Utility = "ELECTRICITY" | "WATER";
export type FileRole =
  | "PHOTO"
  | "ELECTRICITY"
  | "WATER"
  | "TENANT_SIGNATURE"
  | "STAFF_SIGNATURE";

export interface JointFileRef {
  file_id: string;
  media_type: string;
}

export interface JointLine {
  line_id: string;
  ordinal: number;
  line_kind: LineKind;
  group_en: string;
  group_km: string | null;
  item_name: string | null;
  item_name_km: string | null;
  item_type_name: string | null;
  item_type_name_km: string | null;
  quantity: number | null;
  result: JointResult | null;
  note: string | null;
  tenant_caused: boolean;
  pet_caused: boolean;
  move_in_result: JointResult | null;
  move_in_note: string | null;
  problem_report: { report_id: string; report_number: string } | null;
  finding_id: string | null;
  photos: JointFileRef[];
}

export interface JointMeter {
  utility_type: Utility;
  serial_number: string;
  measurement_unit_code: string;
  reading: string | null;
  /** The Utilities reading of the same Meter on the inspection day, when there is one. */
  utilities_reading: string | null;
  move_in_reading: string | null;
  photo: JointFileRef | null;
}

export interface JointKeys {
  door_keys: number | null;
  key_cards: number | null;
  mailbox_keys: number | null;
  other_keys: number | null;
  other_keys_note: string | null;
}

export interface JointRef {
  inspection_id: string;
  inspection_number: string;
}

export interface JointInspection {
  inspection_id: string;
  inspection_number: string;
  kind: JointKind;
  status: JointStatus;
  version: number;
  inspection_date: string;
  lease_id: string;
  lease_number: string | null;
  unit_id: string;
  unit_number: string;
  tenant_name: string;
  move_in_id: string | null;
  move_in_number: string | null;
  replaces: JointRef | null;
  replace_reason: string | null;
  replaced_by: JointRef | null;
  keys: JointKeys;
  move_in_keys: Omit<JointKeys, "other_keys_note"> | null;
  started_by: string | null;
  done_at: string | null;
  done_by: string | null;
  lines: JointLine[];
  meters: JointMeter[];
  signatures: {
    tenant: { file_id: string; signed_at: string } | null;
    staff: { file_id: string; signed_at: string; name: string | null } | null;
  };
  move_out_inspection_id: string | null;
}

export interface JointRow {
  inspection_id: string;
  inspection_number: string;
  kind: JointKind;
  status: JointStatus;
  inspection_date: string;
  lease_id: string;
  lease_number: string | null;
  unit_id: string;
  unit_number: string;
  tenant_name: string;
  problems: number;
  new_problems: number | null;
  marked: number;
  lines: number;
  replaces_number: string | null;
  replaced_by_number: string | null;
  done_at: string | null;
}

export interface JointFinished {
  inspection_number: string;
  reports: string[];
  damage_findings: number;
}

export interface LineChange {
  line_id: string;
  result?: JointResult | null;
  note?: string;
  tenant_caused?: boolean;
  pet_caused?: boolean;
}

export interface JointChanges {
  lines?: LineChange[];
  keys?: Partial<JointKeys>;
  meters?: { utility_type: Utility; reading: string | null }[];
}

export interface JointApi {
  list: (propertyId: string, leaseId?: string) => Promise<JointRow[]>;
  get: (propertyId: string, inspectionId: string) => Promise<JointInspection>;
  start: (
    propertyId: string,
    start: {
      lease_id: string;
      kind: JointKind;
      replaces_id?: string;
      reason?: string;
    },
  ) => Promise<JointInspection>;
  save: (
    propertyId: string,
    inspection: JointInspection,
    changes: JointChanges,
  ) => Promise<JointInspection>;
  addFile: (
    propertyId: string,
    inspection: JointInspection,
    role: FileRole,
    file: Blob,
    lineId?: string,
  ) => Promise<JointInspection>;
  removeFile: (propertyId: string, fileId: string) => Promise<void>;
  /** Where the browser reads one photo or signature. */
  fileUrl: (propertyId: string, fileId: string) => string;
  /** DL-244: the PDF copy of a Done inspection, the same file the Tenant bot sends. */
  pdfUrl: (propertyId: string, inspectionId: string) => string;
  finish: (
    propertyId: string,
    inspection: JointInspection,
  ) => Promise<{ inspection: JointInspection; finished: JointFinished }>;
}

export class JointError extends Error {
  /** The HTTP status when the server answered: 403 no right, 404, 409 a step that does not
   * fit, 412 changed meanwhile, 413 too big, 415 not a picture, 422 refused, 503. The detail is
   * the server's plain words, when it gave them. */
  constructor(
    readonly status: number | null = null,
    readonly detail: string | null = null,
  ) {
    super("The Joint Inspection command was not completed.");
    this.name = "JointError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (entry === undefined) throw new JointError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new JointError();
  return token;
}

async function request(
  path: string,
  init: RequestInit = { method: "GET" },
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new JointError();
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail =
      isObject(payload) && typeof payload.detail === "string"
        ? payload.detail
        : null;
    throw new JointError(response.status, detail);
  }
  if (!isObject(payload) || !("data" in payload)) throw new JointError();
  return payload.data;
}

function post(body: unknown, version?: number): RequestInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrfToken(),
  };
  if (version !== undefined) headers["If-Match"] = `"${String(version)}"`;
  return { method: "POST", headers, body: JSON.stringify(body) };
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new JointError();
  return value;
}

function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function whole(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value))
    throw new JointError();
  return value;
}

function maybeWhole(value: unknown): number | null {
  return value === null || value === undefined ? null : whole(value);
}

function record(value: unknown): Record<string, unknown> {
  if (!isObject(value)) throw new JointError();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new JointError();
  return value;
}

function oneOf<T extends string>(values: readonly T[], value: unknown): T {
  const found = values.find((entry) => entry === value);
  if (found === undefined) throw new JointError();
  return found;
}

function maybeOneOf<T extends string>(
  values: readonly T[],
  value: unknown,
): T | null {
  return value === null || value === undefined ? null : oneOf(values, value);
}

const KINDS = ["MOVE_IN", "MOVE_OUT"] as const;
const STATUSES = ["DRAFT", "DONE", "REPLACED"] as const;
const RESULTS = ["GOOD", "BROKEN", "MISSING"] as const;
const LINE_KINDS = ["PLACE", "BUILT_IN", "ITEM"] as const;
const UTILITIES = ["ELECTRICITY", "WATER"] as const;

function fileOf(value: unknown): JointFileRef {
  const row = record(value);
  return { file_id: text(row.file_id), media_type: text(row.media_type) };
}

function refOf(value: unknown): JointRef | null {
  if (value === null || value === undefined) return null;
  const row = record(value);
  return {
    inspection_id: text(row.inspection_id),
    inspection_number: text(row.inspection_number),
  };
}

function keysOf(value: unknown): JointKeys {
  const row = record(value);
  return {
    door_keys: maybeWhole(row.door_keys),
    key_cards: maybeWhole(row.key_cards),
    mailbox_keys: maybeWhole(row.mailbox_keys),
    other_keys: maybeWhole(row.other_keys),
    other_keys_note: maybeText(row.other_keys_note),
  };
}

function lineOf(value: unknown): JointLine {
  const row = record(value);
  const report =
    row.problem_report === null || row.problem_report === undefined
      ? null
      : record(row.problem_report);
  return {
    line_id: text(row.line_id),
    ordinal: whole(row.ordinal),
    line_kind: oneOf(LINE_KINDS, row.line_kind),
    group_en: text(row.group_en),
    group_km: maybeText(row.group_km),
    item_name: maybeText(row.item_name),
    item_name_km: maybeText(row.item_name_km),
    item_type_name: maybeText(row.item_type_name),
    item_type_name_km: maybeText(row.item_type_name_km),
    quantity: maybeWhole(row.quantity),
    result: maybeOneOf(RESULTS, row.result),
    note: maybeText(row.note),
    tenant_caused: row.tenant_caused === true,
    pet_caused: row.pet_caused === true,
    move_in_result: maybeOneOf(RESULTS, row.move_in_result),
    move_in_note: maybeText(row.move_in_note),
    problem_report:
      report === null
        ? null
        : {
            report_id: text(report.report_id),
            report_number: text(report.report_number),
          },
    finding_id: maybeText(row.finding_id),
    photos: list(row.photos ?? []).map(fileOf),
  };
}

function meterOf(value: unknown): JointMeter {
  const row = record(value);
  return {
    utility_type: oneOf(UTILITIES, row.utility_type),
    serial_number: text(row.serial_number),
    measurement_unit_code: text(row.measurement_unit_code),
    reading: maybeText(row.reading),
    utilities_reading: maybeText(row.utilities_reading),
    move_in_reading: maybeText(row.move_in_reading),
    photo:
      row.photo === null || row.photo === undefined ? null : fileOf(row.photo),
  };
}

export function inspectionOf(value: unknown): JointInspection {
  const row = record(value);
  const signatures = record(row.signatures);
  const tenant =
    signatures.tenant === null || signatures.tenant === undefined
      ? null
      : record(signatures.tenant);
  const staff =
    signatures.staff === null || signatures.staff === undefined
      ? null
      : record(signatures.staff);
  const moveInKeys =
    row.move_in_keys === null || row.move_in_keys === undefined
      ? null
      : keysOf({ ...record(row.move_in_keys), other_keys_note: null });
  return {
    inspection_id: text(row.inspection_id),
    inspection_number: text(row.inspection_number),
    kind: oneOf(KINDS, row.kind),
    status: oneOf(STATUSES, row.status),
    version: whole(row.version),
    inspection_date: text(row.inspection_date),
    lease_id: text(row.lease_id),
    lease_number: maybeText(row.lease_number),
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    tenant_name: text(row.tenant_name),
    move_in_id: maybeText(row.move_in_id),
    move_in_number: maybeText(row.move_in_number),
    replaces: refOf(row.replaces),
    replace_reason: maybeText(row.replace_reason),
    replaced_by: refOf(row.replaced_by),
    keys: keysOf(row.keys),
    move_in_keys:
      moveInKeys === null
        ? null
        : {
            door_keys: moveInKeys.door_keys,
            key_cards: moveInKeys.key_cards,
            mailbox_keys: moveInKeys.mailbox_keys,
            other_keys: moveInKeys.other_keys,
          },
    started_by: maybeText(row.started_by),
    done_at: maybeText(row.done_at),
    done_by: maybeText(row.done_by),
    lines: list(row.lines).map(lineOf),
    meters: list(row.meters).map(meterOf),
    signatures: {
      tenant:
        tenant === null
          ? null
          : {
              file_id: text(tenant.file_id),
              signed_at: text(tenant.signed_at),
            },
      staff:
        staff === null
          ? null
          : {
              file_id: text(staff.file_id),
              signed_at: text(staff.signed_at),
              name: maybeText(staff.name),
            },
    },
    move_out_inspection_id: maybeText(row.move_out_inspection_id),
  };
}

export function rowOf(value: unknown): JointRow {
  const row = record(value);
  return {
    inspection_id: text(row.inspection_id),
    inspection_number: text(row.inspection_number),
    kind: oneOf(KINDS, row.kind),
    status: oneOf(STATUSES, row.status),
    inspection_date: text(row.inspection_date),
    lease_id: text(row.lease_id),
    lease_number: maybeText(row.lease_number),
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    tenant_name: text(row.tenant_name),
    problems: whole(row.problems),
    new_problems: maybeWhole(row.new_problems),
    marked: whole(row.marked),
    lines: whole(row.lines),
    replaces_number: maybeText(row.replaces_number),
    replaced_by_number: maybeText(row.replaced_by_number),
    done_at: maybeText(row.done_at),
  };
}

function base(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}`;
}

function one(propertyId: string, inspectionId: string): string {
  return `${base(propertyId)}/joint-inspections/${encodeURIComponent(inspectionId)}`;
}

export const jointApi: JointApi = {
  list: async (propertyId, leaseId) =>
    list(
      await request(
        leaseId === undefined
          ? `${base(propertyId)}/joint-inspections`
          : `${base(propertyId)}/joint-inspections?lease_id=${encodeURIComponent(leaseId)}`,
      ),
    ).map(rowOf),
  get: async (propertyId, inspectionId) =>
    inspectionOf(await request(one(propertyId, inspectionId))),
  start: async (propertyId, start) =>
    inspectionOf(
      await request(`${base(propertyId)}/joint-inspections`, post(start)),
    ),
  save: async (propertyId, inspection, changes) =>
    inspectionOf(
      await request(
        `${one(propertyId, inspection.inspection_id)}/save`,
        post(changes, inspection.version),
      ),
    ),
  addFile: async (propertyId, inspection, role, file, lineId) => {
    const query = new URLSearchParams({ role });
    if (lineId !== undefined) query.set("line_id", lineId);
    return inspectionOf(
      await request(
        `${one(propertyId, inspection.inspection_id)}/files?${query.toString()}`,
        {
          method: "POST",
          headers: {
            "Content-Type": file.type,
            "X-CSRF-Token": csrfToken(),
            "If-Match": `"${String(inspection.version)}"`,
          },
          body: file,
        },
      ),
    );
  },
  removeFile: async (propertyId, fileId) => {
    await request(
      `${base(propertyId)}/joint-inspection-files/${encodeURIComponent(fileId)}/remove`,
      post({}),
    );
  },
  fileUrl: (propertyId, fileId) =>
    `${base(propertyId)}/joint-inspection-files/${encodeURIComponent(fileId)}`,
  pdfUrl: (propertyId, inspectionId) => `${one(propertyId, inspectionId)}/pdf`,
  finish: async (propertyId, inspection) => {
    const data = record(
      await request(
        `${one(propertyId, inspection.inspection_id)}/finish`,
        post({}, inspection.version),
      ),
    );
    const finished = record(data.finished);
    return {
      inspection: inspectionOf(data),
      finished: {
        inspection_number: text(finished.inspection_number),
        reports: list(finished.reports).map(text),
        damage_findings: whole(finished.damage_findings),
      },
    };
  },
};
