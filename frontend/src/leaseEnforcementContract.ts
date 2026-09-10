import {
  exactKeys,
  financialCalendarDate,
  financialId,
  financialInstant,
  financialInteger,
  financialObject,
  financialText,
  invalidFinancial,
  type EnforcementCommandOperation,
  type FinancialObject,
} from "./financialContracts";
import {
  parseFinancialJson,
  stringifyFinancialJson,
  type FinancialJson,
} from "./financialJson";

export const ENFORCEMENT_CAPABILITIES = [
  "leases.read",
  "leases.warn",
  "rent_nonpayment.read",
  "rent_nonpayment.case_manage",
  "rent_nonpayment.event_post",
] as const;
export type EnforcementCapabilities = Record<
  (typeof ENFORCEMENT_CAPABILITIES)[number],
  boolean
>;
export const ENFORCEMENT_COMMAND_CAPABILITIES: Record<
  EnforcementCommandOperation,
  keyof EnforcementCapabilities
> = {
  leaseWarningRecord: "leases.warn",
  rentNonpaymentOpen: "rent_nonpayment.case_manage",
  rentNonpaymentEvent: "rent_nonpayment.event_post",
};
export const ENFORCEMENT_EVENTS = {
  TWENTY_DAY_WARNING: "20-day Warning Notice",
  THIRTY_DAY_SERIOUS_DEFAULT: "30-day Serious Nonpayment Default",
  CURE: "Cure",
  AUTHORIZED_FOLLOW_UP: "Authorized follow-up",
} as const;
export type EnforcementEvent = keyof typeof ENFORCEMENT_EVENTS;
interface Keyset {
  limit?: number;
  cursor?: string;
}
interface HistoryPage {
  limit?: number;
  offset?: number;
}
export type EnforcementRead =
  | ({ kind: "workspaces" | "alerts" } & Keyset)
  | ({ kind: "leases"; purpose: "WARNINGS" | "NONPAYMENT" } & Keyset)
  | ({ kind: "sources" | "actionCases"; leaseId: string } & Keyset)
  | ({ kind: "warnings" | "cases"; leaseId: string } & HistoryPage)
  | ({ kind: "events"; caseId: string } & HistoryPage)
  | { kind: "case" | "eventContext"; caseId: string }
  | { kind: "warningContext"; leaseId: string };
export const ENFORCEMENT_HISTORY_KINDS = ["warnings", "cases", "events"];
export const ENFORCEMENT_KEYSET_KINDS = [
  "workspaces",
  "alerts",
  "leases",
  "sources",
  "actionCases",
];

export function captureEnforcementRead(
  value: EnforcementRead,
): FinancialObject {
  const row = financialObject(
    parseFinancialJson(stringifyFinancialJson(value, 32768), 32768),
  );
  const kind = typeof row.kind === "string" ? row.kind : invalidFinancial();
  if (
    ![
      ...ENFORCEMENT_HISTORY_KINDS,
      ...ENFORCEMENT_KEYSET_KINDS,
      "case",
      "eventContext",
      "warningContext",
    ].includes(kind)
  )
    invalidFinancial();
  const lease = [
    "sources",
    "actionCases",
    "warnings",
    "cases",
    "warningContext",
  ].includes(kind);
  const singleCase = ["events", "case", "eventContext"].includes(kind);
  exactKeys(
    row,
    [
      "kind",
      ...(lease ? ["leaseId"] : []),
      ...(singleCase ? ["caseId"] : []),
      ...(kind === "leases" ? ["purpose"] : []),
    ],
    ENFORCEMENT_HISTORY_KINDS.includes(kind)
      ? ["limit", "offset"]
      : ENFORCEMENT_KEYSET_KINDS.includes(kind)
        ? ["limit", "cursor"]
        : [],
  );
  if (lease) row.leaseId = financialId(row.leaseId);
  if (singleCase) row.caseId = financialId(row.caseId);
  if (
    kind === "leases" &&
    row.purpose !== "WARNINGS" &&
    row.purpose !== "NONPAYMENT"
  )
    invalidFinancial();
  if (row.limit !== undefined) financialInteger(row.limit, 1n, 100n);
  if (row.offset !== undefined) financialInteger(row.offset, 0n, 1_000_000n);
  if (row.cursor !== undefined) row.cursor = financialId(row.cursor);
  return row;
}
export function enforcementPath(
  row: FinancialObject,
  propertyId: string | null,
): string {
  const lease = () => `/api/v1/leases/${financialId(row.leaseId)}`;
  const casePath = () =>
    `/api/v1/rent-nonpayment-cases/${financialId(row.caseId)}`;
  const prop = () => `/api/v1/properties/${financialId(propertyId)}`;
  const path =
    row.kind === "workspaces"
      ? "/api/v1/lease-enforcement-workspaces"
      : row.kind === "leases"
        ? `${prop()}/lease-enforcement-leases`
        : row.kind === "alerts"
          ? `${prop()}/rent-nonpayment-alerts`
          : row.kind === "sources"
            ? `${lease()}/rent-nonpayment-sources`
            : row.kind === "actionCases"
              ? `${lease()}/rent-nonpayment-action-cases`
              : row.kind === "warningContext"
                ? `${lease()}/violation-warning-context`
                : row.kind === "warnings"
                  ? `${lease()}/violation-warnings`
                  : row.kind === "cases"
                    ? `${lease()}/rent-nonpayment-cases`
                    : row.kind === "events"
                      ? `${casePath()}/events`
                      : row.kind === "eventContext"
                        ? `${casePath()}/action-context`
                        : row.kind === "case"
                          ? casePath()
                          : invalidFinancial();
  const query = new URLSearchParams();
  for (const key of ["limit", "offset", "cursor", "purpose"])
    if (row[key] !== undefined) query.set(key, enforcementValue(row[key]));
  return path + (query.size ? `?${query}` : "");
}
function same(value: unknown, expected: unknown): void {
  if (financialId(value) !== financialId(expected)) invalidFinancial();
}
function rows(value: unknown): FinancialObject[] {
  if (!Array.isArray(value)) return invalidFinancial();
  return value.map(financialObject);
}
export function enforcementGrants(value: unknown): EnforcementCapabilities {
  const row = financialObject(value);
  exactKeys(row, [...ENFORCEMENT_CAPABILITIES]);
  for (const cap of ENFORCEMENT_CAPABILITIES)
    if (typeof row[cap] !== "boolean") invalidFinancial();
  return row as EnforcementCapabilities;
}
export function enforcementAssessment(value: unknown): FinancialObject {
  const row = financialObject(value);
  const flags = [
    "source_applicable",
    "twenty_day_warning_eligible",
    "thirty_day_default_eligible",
    "cure_eligible",
    "warning_recorded",
    "serious_default_recorded",
  ];
  exactKeys(row, [
    "as_of",
    "timezone",
    "business_date",
    "days_overdue",
    "invoice_status",
    "remaining_rent",
    ...flags,
  ]);
  financialInstant(row.as_of);
  financialCalendarDate(row.business_date);
  financialInteger(row.days_overdue, 0n, 3_652_058n);
  if (
    row.timezone !== "Asia/Phnom_Penh" ||
    !["DRAFT", "UNPAID", "PARTIALLY_PAID", "PAID", "VOID"].includes(
      typeof row.invoice_status === "string" ? row.invoice_status : "",
    )
  )
    invalidFinancial();
  for (const key of flags)
    if (typeof row[key] !== "boolean") invalidFinancial();
  const amount = financialObject(row.remaining_rent);
  exactKeys(amount, ["currency", "minor_units"]);
  if (amount.currency !== "USD") invalidFinancial();
  financialInteger(amount.minor_units);
  if (
    !row.source_applicable &&
    (BigInt(financialInteger(amount.minor_units)) !== 0n ||
      row.twenty_day_warning_eligible ||
      row.thirty_day_default_eligible ||
      row.cure_eligible)
  )
    invalidFinancial();
  return row;
}
function sourceScope(row: FinancialObject, prop: string): void {
  same(row.property_id, prop);
  for (const key of [
    "lease_id",
    "customer_id",
    "invoice_id",
    "rent_invoice_line_id",
  ])
    financialId(row[key]);
}
export function enforcementCase(
  value: unknown,
  prop: string,
  minimal = false,
): FinancialObject {
  const row = financialObject(value);
  exactKeys(row, [
    "id",
    "property_id",
    "lease_id",
    "customer_id",
    "invoice_id",
    "rent_invoice_line_id",
    "due_date_snapshot",
    "assessment",
    ...(minimal ? [] : ["opened_at", "opened_by", "event_count"]),
  ]);
  financialId(row.id);
  sourceScope(row, prop);
  financialCalendarDate(row.due_date_snapshot);
  enforcementAssessment(row.assessment);
  if (!minimal) {
    financialInstant(row.opened_at);
    financialId(row.opened_by);
    financialInteger(row.event_count);
  }
  return row;
}
export function enforcementWarning(
  value: unknown,
  lease: string,
): FinancialObject {
  const row = financialObject(value);
  exactKeys(row, [
    "id",
    "lease_id",
    "warning_sequence",
    "violation_date",
    "warning_date",
    "violation_description",
    "lease_provision",
    "communication_record",
    "occurred_at",
    "actor_id",
  ]);
  financialId(row.id);
  same(row.lease_id, lease);
  financialId(row.actor_id);
  financialInstant(row.occurred_at);
  financialInteger(row.warning_sequence, 1n, 32767n);
  financialCalendarDate(row.violation_date);
  financialCalendarDate(row.warning_date);
  // Published Lease history predates command input limits; retain its full text
  // inside the bounded reply rather than reapplying the new command's 2000 limit.
  for (const key of [
    "violation_description",
    "lease_provision",
    "communication_record",
  ]) {
    const value = row[key];
    if (
      typeof value !== "string" ||
      !value ||
      value.startsWith(" ") ||
      value.endsWith(" ") ||
      value.includes("\0")
    )
      invalidFinancial();
  }
  return row;
}
export function enforcementEvent(
  value: unknown,
  caseId: string,
  prop?: string,
): FinancialObject {
  const row = financialObject(value);
  const extra = prop
    ? [
        "property_id",
        "lease_id",
        "customer_id",
        "invoice_id",
        "rent_invoice_line_id",
        "due_date_snapshot",
      ]
    : [];
  exactKeys(row, [
    "id",
    "rent_nonpayment_case_id",
    "event_kind",
    "event_date",
    "remaining_rent_usd_cents",
    "notice_document_reference",
    "communication_record",
    "reason",
    "occurred_at",
    "actor_id",
    "authorization_reference",
    ...extra,
  ]);
  financialId(row.id);
  same(row.rent_nonpayment_case_id, caseId);
  financialId(row.actor_id);
  financialInstant(row.occurred_at);
  financialCalendarDate(row.event_date);
  financialInteger(row.remaining_rent_usd_cents);
  if (
    typeof row.event_kind !== "string" ||
    !Object.hasOwn(ENFORCEMENT_EVENTS, row.event_kind)
  )
    invalidFinancial();
  financialText(row.reason, 500);
  for (const field of [
    "notice_document_reference",
    "communication_record",
    "authorization_reference",
  ])
    if (row[field] !== null)
      financialText(row[field], field === "communication_record" ? 2000 : 500);
  if (
    row.event_kind === "TWENTY_DAY_WARNING" &&
    row.notice_document_reference === null
  )
    invalidFinancial();
  if (
    row.event_kind === "AUTHORIZED_FOLLOW_UP" &&
    row.authorization_reference === null
  )
    invalidFinancial();
  if (prop) {
    sourceScope(row, prop);
    financialCalendarDate(row.due_date_snapshot);
  }
  return row;
}
export function validateEnforcementCommandReply(
  row: FinancialObject,
  body: FinancialObject,
  op: EnforcementCommandOperation,
  target: string,
  prop: string,
  actor: string,
): void {
  if (op === "leaseWarningRecord") {
    enforcementWarning(row, target);
    same(row.actor_id, actor);
    if (
      BigInt(financialInteger(row.warning_sequence)) !==
      BigInt(financialInteger(body.warning_sequence))
    )
      invalidFinancial();
    for (const key of [
      "violation_date",
      "warning_date",
      "violation_description",
      "lease_provision",
      "communication_record",
    ])
      if (row[key] !== body[key]) invalidFinancial();
  } else if (op === "rentNonpaymentOpen") {
    enforcementCase(row, prop);
    same(row.lease_id, target);
    same(row.rent_invoice_line_id, body.rent_invoice_line_id);
    same(row.opened_by, actor);
  } else {
    enforcementEvent(row, target, prop);
    same(row.actor_id, actor);
    for (const key of [
      "event_kind",
      "reason",
      "notice_document_reference",
      "communication_record",
      "authorization_reference",
    ])
      if (row[key] !== (body[key] ?? null)) invalidFinancial();
  }
}
export function validateEnforcementRead(
  envelope: FinancialObject,
  input: FinancialObject,
  actor: string,
  prop: string | null,
  requestId: string,
): FinancialObject {
  exactKeys(envelope, ["data", "meta"]);
  const meta = financialObject(envelope.meta);
  exactKeys(meta, ["request_id", ...(prop ? ["property_id"] : ["actor_id"])]);
  if (
    meta.request_id !== requestId ||
    (prop ? meta.property_id !== prop : meta.actor_id !== actor)
  )
    invalidFinancial();
  const data = financialObject(envelope.data),
    kind = typeof input.kind === "string" ? input.kind : invalidFinancial();
  if (kind === "case" || kind === "eventContext") {
    enforcementCase(data, financialId(prop), kind === "eventContext");
    same(data.id, input.caseId);
    return data;
  }
  if (kind === "warningContext") {
    exactKeys(data, [
      "property_id",
      "lease_id",
      "suggested_sequence",
      "business_date",
    ]);
    same(data.property_id, prop);
    same(data.lease_id, input.leaseId);
    financialCalendarDate(data.business_date);
    if (data.suggested_sequence !== null)
      financialInteger(data.suggested_sequence, 1n, 32767n);
    return data;
  }
  const history = ENFORCEMENT_HISTORY_KINDS.includes(kind),
    limit = Number(financialInteger(input.limit ?? 50, 1n, 100n));
  exactKeys(
    data,
    history
      ? ["items", "total", "limit", "offset"]
      : [
          "items",
          "next_cursor",
          ...(kind === "alerts" ? ["as_of", "business_date", "timezone"] : []),
        ],
  );
  const items = rows(data.items);
  if (items.length > limit) invalidFinancial();
  if (history) {
    if (data.limit !== limit || data.offset !== (input.offset ?? 0))
      invalidFinancial();
    financialInteger(data.total, BigInt(items.length));
  } else if (data.next_cursor !== null) financialId(data.next_cursor);
  if (kind === "alerts") {
    financialInstant(data.as_of);
    financialCalendarDate(data.business_date);
    if (data.timezone !== "Asia/Phnom_Penh") invalidFinancial();
  }
  const seen = new Set<string>();
  let last = typeof input.cursor === "string" ? input.cursor : null;
  for (const row of items) {
    const idKey =
      kind === "workspaces"
        ? "property_id"
        : kind === "sources" || kind === "alerts"
          ? "rent_invoice_line_id"
          : "id";
    const identity = financialId(row[idKey]);
    if (seen.has(identity) || (!history && last !== null && identity <= last))
      invalidFinancial();
    seen.add(identity);
    last = identity;
    if (kind === "workspaces") {
      exactKeys(row, ["property_id", "name", "timezone", "capabilities"]);
      financialText(row.name, 500);
      if (row.timezone !== "Asia/Phnom_Penh") invalidFinancial();
      enforcementGrants(row.capabilities);
    } else if (kind === "leases") {
      exactKeys(row, [
        "id",
        "start_date",
        "end_date",
        "status",
        "unit_number",
        "property_id",
      ]);
      same(row.property_id, prop);
      financialCalendarDate(row.start_date);
      financialCalendarDate(row.end_date);
      financialText(row.status, 50);
      financialText(row.unit_number, 100);
    } else if (kind === "warnings")
      enforcementWarning(row, financialId(input.leaseId));
    else if (kind === "events")
      enforcementEvent(row, financialId(input.caseId));
    else if (kind === "cases" || kind === "actionCases") {
      enforcementCase(row, financialId(prop), kind === "actionCases");
      same(row.lease_id, input.leaseId);
    } else {
      exactKeys(row, [
        "rent_invoice_line_id",
        "invoice_id",
        "invoice_number",
        "property_id",
        "lease_id",
        "customer_id",
        "due_date",
        "case_id",
        "assessment",
      ]);
      sourceScope(row, financialId(prop));
      financialText(row.invoice_number, 100);
      financialCalendarDate(row.due_date);
      enforcementAssessment(row.assessment);
      if (row.case_id !== null) financialId(row.case_id);
      if (kind === "sources") {
        same(row.lease_id, input.leaseId);
        if (row.case_id !== null) invalidFinancial();
      }
    }
  }
  if (
    !history &&
    data.next_cursor !== null &&
    (items.length !== limit || data.next_cursor !== last)
  )
    invalidFinancial();
  return data;
}
export function enforcementRows(
  data: FinancialObject | null,
): FinancialObject[] {
  return data === null ? [] : rows(data.items);
}
export function enforcementValue(value: FinancialJson | undefined): string {
  if (value == null) return "Not recorded";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "bigint" ||
    typeof value === "boolean"
  )
    return String(value);
  return invalidFinancial();
}
