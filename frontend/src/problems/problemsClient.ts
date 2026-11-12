// V1.1 part 7 (DL-124, API-PR-001): Building › Problem reports. One list for Unit Problems (UP)
// and Building problems (BP). The server checks every right, step and amount; this client only
// reads and sends.

export type ProblemKind = "UNIT" | "BUILDING";
export type ProblemStatus =
  | "RECEIVED"
  | "PLANNED"
  | "CHECKED"
  | "WAITING_TENANT"
  | "REPAIR_PLANNED"
  | "WAITING_PARTS"
  | "DONE"
  | "CLOSED"
  | "NOT_ACCEPTED"
  | "JOINED";
export type ProblemSource =
  | "PHONE"
  | "WALKIN"
  | "SEEN"
  | "INSPECTION"
  | "TENANT_BOT"
  | "STAFF_BOT"
  | "ROOM_CHECK";
export type BestTime = "AM" | "PM" | "ANY";

export interface ProblemType {
  id: string;
  code: string;
  name_en: string;
  name_kh: string | null;
  icon: string;
  always_urgent: boolean;
}

export interface SharedPlace {
  id: string;
  code: string;
  name_en: string;
  name_kh: string | null;
}

export interface UnitPlace {
  item_id: string;
  number: number;
  name_en: string;
  name_kh: string | null;
  count: number;
}

export interface ProblemUnit {
  unit_id: string;
  unit_number: string;
  floor: string | null;
  customer_name: string | null;
  places: UnitPlace[];
}

export interface ProblemChoices {
  types: ProblemType[];
  places: SharedPlace[];
  units: ProblemUnit[];
  rules: {
    repeat_count: number;
    repeat_days: number;
    urgent_hours: number;
    plan_workdays: number;
    auto_close_days: number;
  };
  today: string;
}

export interface ReportLink {
  report_id: string;
  report_number: string;
}

export interface HistoryEntry {
  step: string;
  note: string | null;
  details: Record<string, unknown> | null;
  at: string;
  by_name: string | null;
}

export type CostCurrency = "USD" | "KHR";

export interface CostLine {
  kind: "PARTS" | "OUTSIDE_WORKER";
  description: string;
  currency: CostCurrency;
  /** Cents for dollars, whole riel for riel. */
  amount_minor: number;
}

/** DL-130: the latest repair cost typed for a report, its check and its Expense reports. */
export interface RepairCost {
  set_no: number;
  no_cost: boolean;
  note: string | null;
  entered_at: string;
  entered_by_name: string | null;
  lines: CostLine[];
  totals: { currency: CostCurrency; amount_minor: number }[];
  check: {
    checked_at: string;
    checked_by_name: string | null;
    spent_on: string;
    paid_how: "OWN_MONEY" | "CASH";
  } | null;
  expense_requests: {
    request_number: string;
    status: string;
    currency: CostCurrency;
    amount_cents: number;
    original_amount_minor: number | null;
  }[];
  /** Staff may type the cost (again): not checked yet, or every Expense report was refused. */
  can_enter: boolean;
}

export interface RepairCostEntry {
  no_cost: boolean;
  note?: string;
  lines: CostLine[];
}

export interface CostCheck {
  receipt_seen: true;
  spent_on: string;
  paid_how: "OWN_MONEY" | "CASH";
  paid_from_code?: string;
}

export interface ProblemReport {
  report_id: string;
  report_number: string;
  kind: ProblemKind;
  status: ProblemStatus;
  /** The status today: a Done report past its auto-close day reads CLOSED. */
  state: ProblemStatus;
  late: "URGENT" | "NORMAL" | null;
  repeat: (ReportLink & { created_at: string })[] | null;
  unit_id: string | null;
  unit_number: string | null;
  lease_id: string | null;
  customer_id: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  place: {
    item_id: string;
    number: number;
    name_en: string;
    name_kh: string | null;
  } | null;
  problem_place: SharedPlace | null;
  floor: string | null;
  problem_type: ProblemType;
  description: string;
  urgent: boolean;
  always_urgent: boolean;
  may_enter: boolean;
  best_time: BestTime;
  source: ProblemSource;
  reported_by: string | null;
  repair_job: boolean;
  contacted_at: string | null;
  contacted_how: string | null;
  technician: string | null;
  visit_on: string | null;
  visit_at: string | null;
  cause: "WEAR" | "DAMAGE" | "UNSURE" | null;
  cause_note: string | null;
  fixed_at_check: boolean;
  pays: "OWNER" | "TENANT" | null;
  tenant_amount_usd_cents: number | null;
  tenant_reason: string | null;
  decided_on: string | null;
  tenant_answer: "AGREED" | "REFUSED" | null;
  tenant_answer_how: string | null;
  tenant_answer_on: string | null;
  tenant_said: string | null;
  tenant_can_answer: boolean;
  damage: {
    charge_id: string;
    invoice_id: string | null;
    invoice_number: string | null;
    invoice_status: string | null;
    amount_usd_cents: number;
  } | null;
  done_at: string | null;
  /** DL-132: the move-out inspection finding the report was made from. */
  finding: InspectionLink | null;
  /** DL-222: the short stay whose room check reported the problem. */
  stay: StayLink | null;
  /** Only on one report read with its history; null on the list. */
  cost: RepairCost | null;
  closes_on: string | null;
  closed_at: string | null;
  close_note: string | null;
  joined_to: (ReportLink & { state: ProblemStatus }) | null;
  join: {
    reason: string;
    joined_at: string;
    joined_by_name: string | null;
    previous_status: string;
  } | null;
  joined: (ReportLink & {
    source: ProblemSource;
    description: string;
    reported_by: string | null;
    created_at: string;
  })[];
  created_at: string;
  created_by_name: string | null;
  version: number;
  history: HistoryEntry[] | null;
}

/** DL-222: the short stay whose room check reported the problem. */
export interface StayLink {
  booking_id: string;
  booking_number: string;
  guest_name: string;
  check_in_on: string;
  check_out_on: string;
}

/** DL-132: the move-out inspection finding a report was made from. */
export interface InspectionLink {
  finding_id: string;
  inspection_id: string;
  lease_id: string;
  inspection_date: string;
  ordinal: number;
  description: string;
}

/** What a New Problem report copies from a finding, and the report it already has. */
export interface FindingSource extends InspectionLink {
  pet_related: boolean;
  unit_id: string;
  unit_number: string;
  /** The inspection was replaced by a newer one: its findings make no report. */
  replaced: boolean;
  report: ReportLink | null;
}

export interface NewProblemReport {
  kind: ProblemKind;
  source: "PHONE" | "WALKIN" | "SEEN" | "INSPECTION";
  problem_type_id: string;
  description: string;
  urgent: boolean;
  unit_id?: string;
  place_item_id?: string;
  place_number?: number;
  problem_place_id?: string;
  floor?: string;
  may_enter?: boolean;
  best_time?: BestTime;
  reported_by?: string;
  same_as?: string;
  /** Only with the source INSPECTION. */
  finding_id?: string;
}

export type StepName =
  | "CONTACTED"
  | "PLAN"
  | "NOT_A_REPAIR"
  | "MAKE_JOB"
  | "CLEANING"
  | "CLOSE_NOTE"
  | "CHECKED"
  | "DECIDE"
  | "PARTS"
  | "PARTS_ARRIVED"
  | "DONE"
  | "TENANT_FIXED"
  | "TENANT_NOT_FIXED"
  | "CLOSE"
  | "JOIN"
  | "UNJOIN";

export interface ProblemStep {
  step: StepName;
  note?: string;
  how?: "PHONE" | "VISIT";
  technician?: string;
  visit_on?: string;
  visit_at?: string;
  cleaner?: string;
  cause?: "WEAR" | "DAMAGE" | "UNSURE";
  fixed?: boolean;
  pays?: "OWNER" | "TENANT";
  amount_usd_cents?: number;
  reason?: string;
  main_id?: string;
}

export interface TenantAnswer {
  answer: "AGREED" | "REFUSED";
  how: "SIGNED" | "TELEGRAM" | "PHONE" | "IN_PERSON";
  answered_on: string;
  said: string | null;
  after_refusal: "OWNER_PAYS" | "MOVE_OUT" | null;
}

/** DL-131: the Home card. */
export interface ProblemSummary {
  open: number;
  urgent: number;
  late: number;
  costs_to_check: {
    report_id: string;
    report_number: string;
    unit_number: string | null;
    place_en: string | null;
    place_kh: string | null;
    entered_at: string;
    totals: { currency: CostCurrency; amount_minor: number }[];
  }[];
}

export interface CostRow {
  reports: number;
  parts_usd_cents: number;
  outside_usd_cents: number;
  parts_khr: number;
  outside_khr: number;
}

export interface TypeRef {
  code: string;
  name_en: string;
  name_kh: string | null;
  icon: string;
}

/** DL-131: the Monthly report of one month. */
export interface ProblemMonth {
  month: string;
  received: number;
  joined: number;
  unit_problems: number;
  building_problems: number;
  urgent: number;
  urgent_on_time: number;
  normal: number;
  normal_on_time: number;
  done: number;
  average_days_to_fix: number | null;
  still_open: number;
  not_accepted: number;
  opened_again: number;
  owner_pays: number;
  tenant_pays: number;
  damage_usd_cents: number;
  by_type: (TypeRef & { reports: number })[];
  by_place: {
    kind: ProblemKind;
    unit_number: string | null;
    place_code: string | null;
    place_en: string | null;
    place_kh: string | null;
    reports: number;
  }[];
  repeats: (TypeRef & {
    unit_number: string;
    reports: number;
    found: ReportLink[];
  })[];
  late_now: (ReportLink & { late: "URGENT" | "NORMAL" })[];
  cost_by_unit: (CostRow & { unit_number: string | null })[];
  cost_by_type: (CostRow & TypeRef)[];
}

export interface ProblemsApi {
  list: (propertyId: string) => Promise<ProblemReport[]>;
  get: (propertyId: string, reportId: string) => Promise<ProblemReport>;
  choices: (propertyId: string) => Promise<ProblemChoices>;
  add: (propertyId: string, report: NewProblemReport) => Promise<ProblemReport>;
  step: (
    propertyId: string,
    report: ProblemReport,
    step: ProblemStep,
  ) => Promise<ProblemReport>;
  answer: (
    propertyId: string,
    report: ProblemReport,
    answer: TenantAnswer,
  ) => Promise<ProblemReport>;
  cost: (
    propertyId: string,
    report: ProblemReport,
    cost: RepairCostEntry,
  ) => Promise<ProblemReport>;
  checkCost: (
    propertyId: string,
    report: ProblemReport,
    check: CostCheck,
  ) => Promise<ProblemReport>;
  summary: (propertyId: string) => Promise<ProblemSummary>;
  /** `month` is "yyyy-mm". */
  month: (propertyId: string, month: string) => Promise<ProblemMonth>;
  finding: (propertyId: string, findingId: string) => Promise<FindingSource>;
}

export class ProblemsError extends Error {
  /** The HTTP status when the server answered: 403 no right, 404, 409 a step that does not
   * fit, 412 changed meanwhile, 422 refused. */
  constructor(readonly status: number | null = null) {
    super("The Problem report command was not completed.");
    this.name = "ProblemsError";
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
  if (entry === undefined) throw new ProblemsError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new ProblemsError();
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
    throw new ProblemsError();
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) throw new ProblemsError(response.status);
  if (!isObject(payload) || !("data" in payload)) throw new ProblemsError();
  return payload.data;
}

function send(body: unknown, version?: number): RequestInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrfToken(),
  };
  if (version !== undefined) headers["If-Match"] = `"${String(version)}"`;
  return { method: "POST", headers, body: JSON.stringify(body) };
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new ProblemsError();
  return value;
}

function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function whole(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value))
    throw new ProblemsError();
  return value;
}

function maybeWhole(value: unknown): number | null {
  return value === null || value === undefined ? null : whole(value);
}

function flag(value: unknown): boolean {
  return value === true;
}

function record(value: unknown): Record<string, unknown> {
  if (!isObject(value)) throw new ProblemsError();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new ProblemsError();
  return value;
}

function oneOf<T extends string>(values: readonly T[], value: unknown): T {
  const found = values.find((entry) => entry === value);
  if (found === undefined) throw new ProblemsError();
  return found;
}

function maybeOneOf<T extends string>(
  values: readonly T[],
  value: unknown,
): T | null {
  return value === null || value === undefined ? null : oneOf(values, value);
}

export const STATUSES: readonly ProblemStatus[] = [
  "RECEIVED",
  "PLANNED",
  "CHECKED",
  "WAITING_TENANT",
  "REPAIR_PLANNED",
  "WAITING_PARTS",
  "DONE",
  "CLOSED",
  "NOT_ACCEPTED",
  "JOINED",
];
const SOURCES: readonly ProblemSource[] = [
  "PHONE",
  "WALKIN",
  "SEEN",
  "INSPECTION",
  "TENANT_BOT",
  "STAFF_BOT",
  "ROOM_CHECK",
];

const CURRENCIES = ["USD", "KHR"] as const;

function linkOfInspection(value: unknown): InspectionLink {
  const row = record(value);
  return {
    finding_id: text(row.finding_id),
    inspection_id: text(row.inspection_id),
    lease_id: text(row.lease_id),
    inspection_date: text(row.inspection_date),
    ordinal: whole(row.ordinal),
    description: text(row.description),
  };
}

function linkOfStay(value: unknown): StayLink {
  const row = record(value);
  return {
    booking_id: text(row.booking_id),
    booking_number: text(row.booking_number),
    guest_name: text(row.guest_name),
    check_in_on: text(row.check_in_on),
    check_out_on: text(row.check_out_on),
  };
}

export function findingOf(value: unknown): FindingSource {
  const row = record(value);
  const report = row.report == null ? null : record(row.report);
  return {
    ...linkOfInspection(row),
    pet_related: flag(row.pet_related),
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    replaced: flag(row.replaced),
    report:
      report === null
        ? null
        : {
            report_id: text(report.report_id),
            report_number: text(report.report_number),
          },
  };
}

function costOf(value: unknown): RepairCost | null {
  if (value === null || value === undefined) return null;
  const row = record(value);
  const check =
    row.check === null || row.check === undefined ? null : record(row.check);
  return {
    set_no: whole(row.set_no),
    no_cost: flag(row.no_cost),
    note: maybeText(row.note),
    entered_at: text(row.entered_at),
    entered_by_name: maybeText(row.entered_by_name),
    lines: list(row.lines ?? []).map((entry) => {
      const line = record(entry);
      return {
        kind: oneOf(["PARTS", "OUTSIDE_WORKER"] as const, line.kind),
        description: text(line.description),
        currency: oneOf(CURRENCIES, line.currency),
        amount_minor: whole(line.amount_minor),
      };
    }),
    totals: list(row.totals ?? []).map((entry) => {
      const total = record(entry);
      return {
        currency: oneOf(CURRENCIES, total.currency),
        amount_minor: whole(total.amount_minor),
      };
    }),
    check:
      check === null
        ? null
        : {
            checked_at: text(check.checked_at),
            checked_by_name: maybeText(check.checked_by_name),
            spent_on: text(check.spent_on),
            paid_how: oneOf(["OWN_MONEY", "CASH"] as const, check.paid_how),
          },
    expense_requests: list(row.expense_requests ?? []).map((entry) => {
      const made = record(entry);
      return {
        request_number: text(made.request_number),
        status: text(made.status),
        currency: oneOf(CURRENCIES, made.currency),
        amount_cents: whole(made.amount_cents),
        original_amount_minor: maybeWhole(made.original_amount_minor),
      };
    }),
    can_enter: flag(row.can_enter),
  };
}

function typeOf(value: unknown): ProblemType {
  const row = record(value);
  return {
    id: text(row.id),
    code: text(row.code),
    name_en: text(row.name_en),
    name_kh: maybeText(row.name_kh),
    icon: text(row.icon),
    always_urgent: flag(row.always_urgent),
  };
}

function sharedOf(value: unknown): SharedPlace {
  const row = record(value);
  return {
    id: text(row.id),
    code: text(row.code),
    name_en: text(row.name_en),
    name_kh: maybeText(row.name_kh),
  };
}

function linkOf(value: unknown): ReportLink {
  const row = record(value);
  return {
    report_id: text(row.report_id),
    report_number: text(row.report_number),
  };
}

export function reportOf(value: unknown): ProblemReport {
  const row = record(value);
  const place =
    row.place === null || row.place === undefined ? null : record(row.place);
  const damage =
    row.damage === null || row.damage === undefined ? null : record(row.damage);
  const joinedTo =
    row.joined_to === null || row.joined_to === undefined
      ? null
      : record(row.joined_to);
  const join =
    row.join === null || row.join === undefined ? null : record(row.join);
  return {
    report_id: text(row.report_id),
    report_number: text(row.report_number),
    kind: oneOf(["UNIT", "BUILDING"] as const, row.kind),
    status: oneOf(STATUSES, row.status),
    state: oneOf(STATUSES, row.state),
    late: maybeOneOf(["URGENT", "NORMAL"] as const, row.late),
    repeat:
      row.repeat === null || row.repeat === undefined
        ? null
        : list(row.repeat).map((entry) => ({
            ...linkOf(entry),
            created_at: text(record(entry).created_at),
          })),
    unit_id: maybeText(row.unit_id),
    unit_number: maybeText(row.unit_number),
    lease_id: maybeText(row.lease_id),
    customer_id: maybeText(row.customer_id),
    customer_name: maybeText(row.customer_name),
    customer_phone: maybeText(row.customer_phone),
    place:
      place === null
        ? null
        : {
            item_id: text(place.item_id),
            number: whole(place.number),
            name_en: text(place.name_en),
            name_kh: maybeText(place.name_kh),
          },
    problem_place:
      row.problem_place === null || row.problem_place === undefined
        ? null
        : sharedOf(row.problem_place),
    floor: maybeText(row.floor),
    problem_type: typeOf(row.problem_type),
    description: text(row.description),
    urgent: flag(row.urgent),
    always_urgent: flag(row.always_urgent),
    may_enter: flag(row.may_enter),
    best_time: oneOf(["AM", "PM", "ANY"] as const, row.best_time),
    source: oneOf(SOURCES, row.source),
    reported_by: maybeText(row.reported_by),
    repair_job: flag(row.repair_job),
    contacted_at: maybeText(row.contacted_at),
    contacted_how: maybeText(row.contacted_how),
    technician: maybeText(row.technician),
    visit_on: maybeText(row.visit_on),
    visit_at: maybeText(row.visit_at),
    cause: maybeOneOf(["WEAR", "DAMAGE", "UNSURE"] as const, row.cause),
    cause_note: maybeText(row.cause_note),
    fixed_at_check: flag(row.fixed_at_check),
    pays: maybeOneOf(["OWNER", "TENANT"] as const, row.pays),
    tenant_amount_usd_cents: maybeWhole(row.tenant_amount_usd_cents),
    tenant_reason: maybeText(row.tenant_reason),
    decided_on: maybeText(row.decided_on),
    tenant_answer: maybeOneOf(
      ["AGREED", "REFUSED"] as const,
      row.tenant_answer,
    ),
    tenant_answer_how: maybeText(row.tenant_answer_how),
    tenant_answer_on: maybeText(row.tenant_answer_on),
    tenant_said: maybeText(row.tenant_said),
    tenant_can_answer: flag(row.tenant_can_answer),
    damage:
      damage === null
        ? null
        : {
            charge_id: text(damage.charge_id),
            invoice_id: maybeText(damage.invoice_id),
            invoice_number: maybeText(damage.invoice_number),
            invoice_status: maybeText(damage.invoice_status),
            amount_usd_cents: whole(damage.amount_usd_cents),
          },
    done_at: maybeText(row.done_at),
    finding: row.finding == null ? null : linkOfInspection(row.finding),
    stay: row.stay == null ? null : linkOfStay(row.stay),
    cost: costOf(row.cost),
    closes_on: maybeText(row.closes_on),
    closed_at: maybeText(row.closed_at),
    close_note: maybeText(row.close_note),
    joined_to:
      joinedTo === null
        ? null
        : { ...linkOf(joinedTo), state: oneOf(STATUSES, joinedTo.state) },
    join:
      join === null
        ? null
        : {
            reason: text(join.reason),
            joined_at: text(join.joined_at),
            joined_by_name: maybeText(join.joined_by_name),
            previous_status: text(join.previous_status),
          },
    joined: list(row.joined ?? []).map((entry) => {
      const kid = record(entry);
      return {
        ...linkOf(kid),
        source: oneOf(SOURCES, kid.source),
        description: text(kid.description),
        reported_by: maybeText(kid.reported_by),
        created_at: text(kid.created_at),
      };
    }),
    created_at: text(row.created_at),
    created_by_name: maybeText(row.created_by_name),
    version: whole(row.version),
    history:
      row.history === null || row.history === undefined
        ? null
        : list(row.history).map((entry) => {
            const event = record(entry);
            return {
              step: text(event.step),
              note: maybeText(event.note),
              details: isObject(event.details) ? event.details : null,
              at: text(event.at),
              by_name: maybeText(event.by_name),
            };
          }),
  };
}

function totalsOf(
  value: unknown,
): { currency: CostCurrency; amount_minor: number }[] {
  return list(value ?? []).map((entry) => {
    const total = record(entry);
    return {
      currency: oneOf(CURRENCIES, total.currency),
      amount_minor: whole(total.amount_minor),
    };
  });
}

export function summaryOf(value: unknown): ProblemSummary {
  const row = record(value);
  return {
    open: whole(row.open),
    urgent: whole(row.urgent),
    late: whole(row.late),
    costs_to_check: list(row.costs_to_check ?? []).map((entry) => {
      const item = record(entry);
      return {
        report_id: text(item.report_id),
        report_number: text(item.report_number),
        unit_number: maybeText(item.unit_number),
        place_en: maybeText(item.place_en),
        place_kh: maybeText(item.place_kh),
        entered_at: text(item.entered_at),
        totals: totalsOf(item.totals),
      };
    }),
  };
}

function typeRefOf(row: Record<string, unknown>): TypeRef {
  return {
    code: text(row.code),
    name_en: text(row.name_en),
    name_kh: maybeText(row.name_kh),
    icon: text(row.icon),
  };
}

function costRowOf(row: Record<string, unknown>): CostRow {
  return {
    reports: whole(row.reports),
    parts_usd_cents: whole(row.parts_usd_cents),
    outside_usd_cents: whole(row.outside_usd_cents),
    parts_khr: whole(row.parts_khr),
    outside_khr: whole(row.outside_khr),
  };
}

export function monthOf(value: unknown): ProblemMonth {
  const row = record(value);
  const count = (key: string) => whole(row[key]);
  return {
    month: text(row.month),
    received: count("received"),
    joined: count("joined"),
    unit_problems: count("unit_problems"),
    building_problems: count("building_problems"),
    urgent: count("urgent"),
    urgent_on_time: count("urgent_on_time"),
    normal: count("normal"),
    normal_on_time: count("normal_on_time"),
    done: count("done"),
    average_days_to_fix:
      row.average_days_to_fix === null || row.average_days_to_fix === undefined
        ? null
        : Number(row.average_days_to_fix),
    still_open: count("still_open"),
    not_accepted: count("not_accepted"),
    opened_again: count("opened_again"),
    owner_pays: count("owner_pays"),
    tenant_pays: count("tenant_pays"),
    damage_usd_cents: count("damage_usd_cents"),
    by_type: list(row.by_type ?? []).map((entry) => {
      const item = record(entry);
      return { ...typeRefOf(item), reports: whole(item.reports) };
    }),
    by_place: list(row.by_place ?? []).map((entry) => {
      const item = record(entry);
      return {
        kind: oneOf(["UNIT", "BUILDING"] as const, item.kind),
        unit_number: maybeText(item.unit_number),
        place_code: maybeText(item.place_code),
        place_en: maybeText(item.place_en),
        place_kh: maybeText(item.place_kh),
        reports: whole(item.reports),
      };
    }),
    repeats: list(row.repeats ?? []).map((entry) => {
      const item = record(entry);
      return {
        ...typeRefOf(item),
        unit_number: text(item.unit_number),
        reports: whole(item.reports),
        found: list(item.found ?? []).map(linkOf),
      };
    }),
    late_now: list(row.late_now ?? []).map((entry) => {
      const item = record(entry);
      return {
        ...linkOf(item),
        late: oneOf(["URGENT", "NORMAL"] as const, item.late),
      };
    }),
    cost_by_unit: list(row.cost_by_unit ?? []).map((entry) => {
      const item = record(entry);
      return { ...costRowOf(item), unit_number: maybeText(item.unit_number) };
    }),
    cost_by_type: list(row.cost_by_type ?? []).map((entry) => {
      const item = record(entry);
      return { ...costRowOf(item), ...typeRefOf(item) };
    }),
  };
}

export function choicesOf(value: unknown): ProblemChoices {
  const row = record(value);
  const rules = record(row.rules);
  return {
    types: list(row.types).map(typeOf),
    places: list(row.places).map(sharedOf),
    units: list(row.units).map((entry) => {
      const unit = record(entry);
      return {
        unit_id: text(unit.unit_id),
        unit_number: text(unit.unit_number),
        floor:
          unit.floor === null || unit.floor === undefined
            ? null
            : String(unit.floor as string | number),
        customer_name: maybeText(unit.customer_name),
        places: list(unit.places ?? []).map((spot) => {
          const place = record(spot);
          return {
            item_id: text(place.item_id),
            number: whole(place.number),
            name_en: text(place.name_en),
            name_kh: maybeText(place.name_kh),
            count: whole(place.count),
          };
        }),
      };
    }),
    rules: {
      repeat_count: Number(rules.repeat_count),
      repeat_days: Number(rules.repeat_days),
      urgent_hours: Number(rules.urgent_hours),
      plan_workdays: Number(rules.plan_workdays),
      auto_close_days: Number(rules.auto_close_days),
    },
    today: text(row.today),
  };
}

function base(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}`;
}

function one(propertyId: string, reportId: string): string {
  return `${base(propertyId)}/problem-reports/${encodeURIComponent(reportId)}`;
}

export const problemsApi: ProblemsApi = {
  list: async (propertyId) =>
    list(await request(`${base(propertyId)}/problem-reports`)).map(reportOf),
  get: async (propertyId, reportId) =>
    reportOf(await request(one(propertyId, reportId))),
  choices: async (propertyId) =>
    choicesOf(await request(`${base(propertyId)}/problem-report-choices`)),
  add: async (propertyId, report) =>
    reportOf(
      await request(`${base(propertyId)}/problem-reports`, send(report)),
    ),
  step: async (propertyId, report, step) =>
    reportOf(
      await request(
        `${one(propertyId, report.report_id)}/steps`,
        send(step, report.version),
      ),
    ),
  answer: async (propertyId, report, answer) =>
    reportOf(
      await request(
        `${one(propertyId, report.report_id)}/tenant-answer`,
        send(answer, report.version),
      ),
    ),
  cost: async (propertyId, report, cost) =>
    reportOf(
      await request(
        `${one(propertyId, report.report_id)}/cost`,
        send(cost, report.version),
      ),
    ),
  summary: async (propertyId) =>
    summaryOf(await request(`${base(propertyId)}/problem-report-summary`)),
  month: async (propertyId, month) =>
    monthOf(
      await request(
        `${base(propertyId)}/problem-report-month?month=${encodeURIComponent(month)}`,
      ),
    ),
  finding: async (propertyId, findingId) =>
    findingOf(
      await request(
        `${base(propertyId)}/problem-report-findings/${encodeURIComponent(findingId)}`,
      ),
    ),
  checkCost: async (propertyId, report, check) =>
    reportOf(
      await request(
        `${one(propertyId, report.report_id)}/cost-check`,
        send(check, report.version),
      ),
    ),
};
