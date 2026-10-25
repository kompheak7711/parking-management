// V1-058 R2 step C2: the Customer saves of the new dialogs. They keep the earlier form's
// safety rules: each save reserves the browser's one Customer command gate first (one save at
// a time across tabs, kept until its result is known), sends one idempotency key, and proves
// the result with the same fingerprints. A save whose result is unknown keeps the gate; the
// same request can be sent again with the same key, and the server then either saves it once
// or returns the save it already made.

import {
  customerCreateRequestFingerprint,
  customerCreateResultFingerprint,
  customerReconciliationResultFingerprint,
  customerUpdateRequestFingerprint,
  normalizeCustomerText,
  type CustomerReconciliationRequirement,
} from "../CustomerManagement";
import {
  CustomerRequestError,
  type CustomerApi,
  type CustomerDetail,
  type CustomerSource,
} from "../customerClient";

export interface CustomerCommandGate {
  actorId: string;
  /** False while browser coordination is unavailable or another save waits to be checked. */
  open: boolean;
  reserve: (requirement: CustomerReconciliationRequirement) => Promise<boolean>;
  release: (requirement: CustomerReconciliationRequirement) => Promise<boolean>;
  setBusy: (busy: boolean) => void;
}

export type CommandResult =
  | { kind: "saved"; customer: CustomerDetail }
  /** The server refused it; nothing was saved and the gate is free again. */
  | { kind: "refused"; error: unknown }
  /** Nobody knows yet whether it was saved; `again` sends the very same request. */
  | { kind: "unknown"; again: () => Promise<CommandResult> }
  /** Nothing was sent: the gate is closed or the browser cannot prove the result. */
  | { kind: "blocked" };

async function attempt(
  gate: CustomerCommandGate,
  requirement: CustomerReconciliationRequirement,
  send: (key: string) => Promise<CustomerDetail>,
): Promise<CommandResult> {
  gate.setBusy(true);
  try {
    const customer = await send(requirement.commandNonce);
    await gate.release(requirement);
    return { kind: "saved", customer };
  } catch (error: unknown) {
    if (error instanceof CustomerRequestError && error.outcomeUnknown)
      return {
        kind: "unknown",
        again: () => attempt(gate, requirement, send),
      };
    await gate.release(requirement);
    return { kind: "refused", error };
  } finally {
    gate.setBusy(false);
  }
}

async function run(
  gate: CustomerCommandGate,
  requirement: CustomerReconciliationRequirement,
  send: (key: string) => Promise<CustomerDetail>,
): Promise<CommandResult> {
  let reserved = false;
  try {
    reserved = await gate.reserve(requirement);
  } catch {
    reserved = false;
  }
  if (!reserved) return { kind: "blocked" };
  return attempt(gate, requirement, send);
}

export async function createCustomer(
  api: CustomerApi,
  gate: CustomerCommandGate,
  propertyId: string,
  source: CustomerSource,
): Promise<CommandResult> {
  if (!gate.open) return { kind: "blocked" };
  const customerId = crypto.randomUUID();
  const [requestFingerprint, resultFingerprint] = await Promise.all([
    customerCreateRequestFingerprint(source),
    customerCreateResultFingerprint(customerId, source),
  ]);
  if (requestFingerprint === null || resultFingerprint === null)
    return { kind: "blocked" };
  return run(
    gate,
    {
      actorId: gate.actorId,
      commandNonce: crypto.randomUUID(),
      kind: "create",
      customerId,
      propertyId,
      resultFingerprint,
      requestFingerprint,
      createSource: source,
    },
    (key) => api.create(propertyId, customerId, source, key),
  );
}

export async function updateCustomer(
  api: CustomerApi,
  gate: CustomerCommandGate,
  propertyId: string,
  current: CustomerDetail,
  changed: Partial<CustomerSource>,
): Promise<CommandResult> {
  if (!gate.open) return { kind: "blocked" };
  const [resultFingerprint, requestFingerprint] = await Promise.all([
    customerReconciliationResultFingerprint("update", {
      ...current,
      ...changed,
      legal_name: changed.legal_name ?? current.legal_name,
      version: current.version + 1,
    }),
    customerUpdateRequestFingerprint(current, changed),
  ]);
  if (resultFingerprint === null || requestFingerprint === null)
    return { kind: "blocked" };
  return run(
    gate,
    {
      actorId: gate.actorId,
      commandNonce: crypto.randomUUID(),
      kind: "update",
      customerId: current.customer_id,
      propertyId,
      resultFingerprint,
      requestFingerprint,
      expectedVersion: current.version,
      updateSource: changed,
    },
    (key) => api.update(current, changed, key),
  );
}

export async function deactivateCustomer(
  api: CustomerApi,
  gate: CustomerCommandGate,
  propertyId: string,
  current: CustomerDetail,
  reason: string,
): Promise<CommandResult> {
  if (!gate.open) return { kind: "blocked" };
  const fingerprint = await customerReconciliationResultFingerprint(
    "deactivate",
    {
      ...current,
      version: current.version + 1,
      active: false,
      deactivation_reason: reason,
    },
  );
  if (fingerprint === null) return { kind: "blocked" };
  return run(
    gate,
    {
      actorId: gate.actorId,
      commandNonce: crypto.randomUUID(),
      kind: "deactivate",
      customerId: current.customer_id,
      propertyId,
      resultFingerprint: fingerprint,
      requestFingerprint: fingerprint,
      expectedVersion: current.version,
      deactivationReason: reason,
    },
    (key) => api.deactivate(current, reason, key),
  );
}

/** Trimmed the way the server trims; an empty box is "not recorded". */
export function cleanText(value: string): string | null {
  const text = normalizeCustomerText(value);
  return text === "" ? null : text;
}

const FIELDS = [
  "legal_name",
  "phone_number",
  "email_address",
  "contact_address",
  "memo",
  "id_document_number",
  "date_of_birth",
  "gender",
  "nationality",
] as const;

/** Only the fields that differ from the saved Customer are sent. */
export function changedFields(
  current: CustomerDetail,
  source: CustomerSource,
): Partial<CustomerSource> {
  const changed: Partial<CustomerSource> = {};
  for (const field of FIELDS) {
    const value = source[field] ?? null;
    if (value !== current[field]) Object.assign(changed, { [field]: value });
  }
  return changed;
}
