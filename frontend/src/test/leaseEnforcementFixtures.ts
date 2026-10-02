import {
  financialObject,
  type FinancialObject,
  type EnforcementCommandOperation,
} from "../financialContracts";
import { stringifyFinancialJson } from "../financialJson";
import type { FinancialCommandRequest } from "../financialUi";
import {
  ENFORCEMENT_CAPABILITIES,
  type EnforcementRead,
} from "../leaseEnforcementContract";
import type { FinancialAttemptCoordinator } from "../financialRecovery";
import type { OpenIntent, SealedIntentStore } from "../sealedIntentStore";
import { ids as financeIds } from "./financialFixtures";

export const ids = {
  ...financeIds,
  lease: "12121212-1212-4212-8212-121212121212",
  rent: "13131313-1313-4313-8313-131313131313",
  case: "14141414-1414-4414-8414-141414141414",
  secondRent: "16161616-1616-4616-8616-161616161616",
  secondInvoice: "17171717-1717-4717-8717-171717171717",
  warning: "15151515-1515-4515-8515-151515151515",
};
export const instant = "2026-09-10T01:00:00+00:00";
export function grants(
  allow: readonly string[] = ENFORCEMENT_CAPABILITIES,
): FinancialObject {
  return Object.fromEntries(
    ENFORCEMENT_CAPABILITIES.map((key) => [key, allow.includes(key)]),
  );
}
export function assessment(voided = false): FinancialObject {
  return {
    as_of: instant,
    timezone: "Asia/Phnom_Penh",
    business_date: "2026-09-10",
    days_overdue: 40,
    invoice_status: voided ? "VOID" : "UNPAID",
    remaining_rent: { currency: "USD", minor_units: voided ? 0 : 80000 },
    source_applicable: !voided,
    twenty_day_warning_eligible: !voided,
    thirty_day_default_eligible: !voided,
    cure_eligible: false,
    warning_recorded: false,
    serious_default_recorded: false,
  };
}
export function source(voided = false): FinancialObject {
  return {
    rent_invoice_line_id: ids.rent,
    invoice_id: ids.invoice,
    invoice_number: "SYNTHETIC-RENT-054",
    property_id: ids.property,
    lease_id: ids.lease,
    customer_id: ids.customer,
    due_date: "2026-08-01",
    case_id: null,
    assessment: assessment(voided),
  };
}
export function additionalRentSource(): FinancialObject {
  return {
    ...source(),
    rent_invoice_line_id: ids.secondRent,
    invoice_id: ids.secondInvoice,
    invoice_number: "SYNTHETIC-RENT-054-SECOND",
  };
}
export function caseRecord(voided = false, minimal = false): FinancialObject {
  return {
    id: ids.case,
    property_id: ids.property,
    lease_id: ids.lease,
    customer_id: ids.customer,
    invoice_id: ids.invoice,
    rent_invoice_line_id: ids.rent,
    due_date_snapshot: "2026-08-01",
    assessment: assessment(voided),
    ...(minimal
      ? {}
      : { opened_at: instant, opened_by: ids.actor, event_count: 0 }),
  };
}
export const warningBody: FinancialObject = {
  warning_sequence: 1,
  violation_date: "2026-09-09",
  warning_date: "2026-09-10",
  violation_description: "Synthetic quiet-hours violation",
  lease_provision: "Synthetic Clause 7",
  communication_record: "Synthetic written communication",
  reason: "Synthetic authorized record",
};
export function warningRecord(body = warningBody): FinancialObject {
  const fields = { ...body };
  delete fields.reason;
  return {
    id: ids.warning,
    lease_id: ids.lease,
    ...fields,
    occurred_at: instant,
    actor_id: ids.actor,
  };
}
export const eventBody: FinancialObject = {
  event_kind: "TWENTY_DAY_WARNING",
  reason: "Synthetic Warning Notice",
  notice_document_reference: "SYNTHETIC-NOTICE-054",
  communication_record: "Synthetic Notice delivery",
};
export function eventRecord(
  body = eventBody,
  command = false,
  voided = false,
): FinancialObject {
  return {
    id: ids.event,
    rent_nonpayment_case_id: ids.case,
    event_kind: body.event_kind ?? "TWENTY_DAY_WARNING",
    event_date: "2026-09-10",
    remaining_rent_usd_cents: voided ? 0 : 80000,
    notice_document_reference: body.notice_document_reference ?? null,
    communication_record: body.communication_record ?? null,
    authorization_reference: body.authorization_reference ?? null,
    reason: body.reason ?? "Synthetic record",
    occurred_at: instant,
    actor_id: ids.actor,
    ...(command
      ? {
          property_id: ids.property,
          lease_id: ids.lease,
          customer_id: ids.customer,
          invoice_id: ids.invoice,
          rent_invoice_line_id: ids.rent,
          due_date_snapshot: "2026-08-01",
        }
      : {}),
  };
}
export const commands: FinancialCommandRequest[] = [
  {
    operation: "leaseWarningRecord",
    target: { id: ids.lease },
    body: warningBody,
  },
  {
    operation: "rentNonpaymentOpen",
    target: { id: ids.lease },
    body: { rent_invoice_line_id: ids.rent, reason: "Synthetic Rent case" },
  },
  {
    operation: "rentNonpaymentEvent",
    target: { id: ids.case },
    body: eventBody,
  },
];
export function commandData(
  operation: EnforcementCommandOperation,
  body?: FinancialObject,
): FinancialObject {
  return operation === "leaseWarningRecord"
    ? warningRecord(body)
    : operation === "rentNonpaymentOpen"
      ? caseRecord()
      : eventRecord(body, true);
}
export const readInputs: EnforcementRead[] = [
  { kind: "workspaces" },
  { kind: "leases", purpose: "WARNINGS" },
  { kind: "leases", purpose: "NONPAYMENT" },
  { kind: "sources", leaseId: ids.lease },
  { kind: "actionCases", leaseId: ids.lease },
  { kind: "warnings", leaseId: ids.lease },
  { kind: "cases", leaseId: ids.lease },
  { kind: "events", caseId: ids.case },
  { kind: "case", caseId: ids.case },
  { kind: "eventContext", caseId: ids.case },
  { kind: "warningContext", leaseId: ids.lease },
  { kind: "alerts" },
  { kind: "initialRentAlerts" },
];
export function readData(
  input: EnforcementRead,
  voided = false,
  allow: readonly string[] = ENFORCEMENT_CAPABILITIES,
): FinancialObject {
  const page = (items: FinancialObject[]) => ({ items, next_cursor: null });
  const history = (items: FinancialObject[]) => ({
    items,
    total: items.length,
    limit: "limit" in input ? (input.limit ?? 50) : 50,
    offset: "offset" in input ? (input.offset ?? 0) : 0,
  });
  switch (input.kind) {
    case "workspaces":
      return page([
        {
          property_id: ids.property,
          name: "Synthetic River Property",
          timezone: "Asia/Phnom_Penh",
          capabilities: grants(allow),
        },
      ]);
    case "leases":
      return page([
        {
          id: ids.lease,
          start_date: "2026-01-01",
          end_date: "2026-12-31",
          status: "ACTIVE",
          unit_number: "SYNTHETIC-A1",
          property_id: ids.property,
        },
      ]);
    case "sources":
      return page(voided ? [] : [source()]);
    case "actionCases":
      return page([caseRecord(voided, true)]);
    case "cases":
      return history([caseRecord(voided)]);
    case "warnings":
      return history([warningRecord()]);
    case "events":
      return history([eventRecord()]);
    case "case":
      return caseRecord(voided);
    case "eventContext":
      return caseRecord(voided, true);
    case "warningContext":
      return {
        property_id: ids.property,
        lease_id: ids.lease,
        suggested_sequence: 1,
        business_date: "2026-09-10",
      };
    case "initialRentAlerts":
      return {
        ...page(
          voided
            ? []
            : [
                {
                  invoice_id: ids.invoice,
                  invoice_number: "INV-INITIAL-1",
                  property_id: ids.property,
                  lease_id: ids.lease,
                  customer_id: ids.customer,
                  invoice_status: "UNPAID",
                  due_date: "2026-09-05",
                  alert_date: "2026-09-06",
                  remaining: { currency: "USD", minor_units: 31000 },
                },
              ],
        ),
        as_of: instant,
        business_date: "2026-09-10",
        timezone: "Asia/Phnom_Penh",
      };
    case "alerts":
      return {
        ...page(voided ? [] : [source()]),
        as_of: instant,
        business_date: "2026-09-10",
        timezone: "Asia/Phnom_Penh",
      };
  }
}
export function readResponse(
  input: EnforcementRead,
  init?: RequestInit,
  data = readData(input),
): Response {
  const headers = new Headers(init?.headers),
    requestId = headers.get("X-Request-ID") ?? ids.key;
  return new Response(
    stringifyFinancialJson({
      data,
      meta: {
        request_id: requestId,
        ...(input.kind === "workspaces"
          ? { actor_id: ids.actor }
          : { property_id: ids.property }),
      },
    }),
    {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
    },
  );
}
export function scope() {
  return {
    actorId: ids.actor,
    propertyId: ids.property,
    signal: new AbortController().signal,
  };
}
export function memory() {
  const records = new Map<string, OpenIntent>();
  const store: SealedIntentStore = {
    read: async (actor) => Promise.resolve(records.get(actor) ?? null),
    begin: async (actor, value) => {
      if (records.has(actor)) throw new Error("Reserved");
      records.set(actor, { ...value });
      await Promise.resolve();
    },
    clear: async (actor, key) => {
      if (records.get(actor)?.requestKey !== key) throw new Error("Wrong key");
      records.delete(actor);
      await Promise.resolve();
    },
  };
  const held = new Set<string>();
  const attempts: FinancialAttemptCoordinator = {
    async run<T>(actor: string, action: () => Promise<T>): Promise<T | null> {
      if (held.has(actor)) return null;
      held.add(actor);
      try {
        return await action();
      } finally {
        held.delete(actor);
      }
    },
  };
  return { records, store, attempts };
}
export function commandResponse(
  operation: EnforcementCommandOperation,
  init: RequestInit | undefined,
  body?: FinancialObject,
  mutate?: (data: FinancialObject) => void,
): Response {
  const headers = new Headers(init?.headers),
    requestId = headers.get("X-Request-ID") ?? ids.key,
    data = commandData(operation, body);
  mutate?.(data);
  return new Response(
    stringifyFinancialJson({
      data,
      meta: { property_id: ids.property, request_id: requestId },
    }),
    {
      status: 201,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
    },
  );
}
export function rentMinor(data: FinancialObject) {
  return financialObject(financialObject(data.assessment).remaining_rent)
    .minor_units;
}
