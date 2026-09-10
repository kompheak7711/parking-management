import type { ReactNode } from "react";
import type {
  FinancialCapabilities,
  financialReferenceClient,
} from "./financialReferenceClient";
import type { FinancialRecovery } from "./financialRecovery";
import type { FinancialTransport } from "./financialClient";
import {
  captureFinancialRequest,
  commandBody,
  FinancialContractError,
  financialId,
  financialObject,
  financialInstant,
  financialInteger,
  invalidFinancial,
  isFinancialCommand,
  type FinancialObject,
  type FinancialCommandOperation,
  type FinancialRequest,
} from "./financialContracts";
import {
  captureFinancialScope,
  FinancialClientError,
  type FinancialScope,
} from "./financialClient";
import { FinancialReferenceError } from "./financialReferenceClient";
import {
  ExactJsonNumber,
  FinancialJsonError,
  type FinancialJson,
} from "./financialJson";

const MAX_EVENT_MINOR = 9_000_000_000_000_000n;
const MAX_AGGREGATE = 9_223_372_036_854_775_807n;
export class FinancialInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FinancialInputError";
  }
}

export function parseFinancialAmount(
  value: string,
  currency: "USD" | "KHR" = "USD",
  allowZero = false,
): bigint {
  const match =
    value.length <= 32
      ? /^(0|[1-9][0-9]*)(?:\.([0-9]{1,2}))?$/.exec(value)
      : null;
  if (!match || (currency === "KHR" && match[2] !== undefined))
    throw new FinancialInputError(
      currency === "KHR"
        ? "Enter whole riel without commas or an exponent."
        : "Enter dollars with at most two decimal places, without commas or an exponent.",
    );
  const amount =
    currency === "KHR"
      ? BigInt(match[1] ?? "0")
      : BigInt(match[1] ?? "0") * 100n +
        BigInt((match[2] ?? "").padEnd(2, "0"));
  if (amount < (allowZero ? 0n : 1n) || amount > MAX_EVENT_MINOR)
    throw new FinancialInputError(
      "Enter an amount within the permitted range.",
    );
  return amount;
}

export function parseFinancialRate(value: string): string {
  if (!/^(0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$/.test(value))
    throw new FinancialInputError(
      "Enter a positive rate with at most six decimal places.",
    );
  const [whole = "0", fraction = ""] = value.split(".");
  if (BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0")) <= 0n)
    throw new FinancialInputError(
      "Enter a positive rate with at most six decimal places.",
    );
  return value;
}

export function financialLocalInstant(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?$/.test(value))
    throw new FinancialInputError(
      "Enter the date and time in Asia/Phnom_Penh.",
    );
  const result = value + (value.length === 16 ? ":00" : "") + "+07:00";
  try {
    financialInstant(result);
  } catch {
    throw new FinancialInputError(
      "Enter a valid date and time in Asia/Phnom_Penh.",
    );
  }
  return result;
}

export function financialTimestamp(value: unknown): string {
  try {
    financialInstant(value);
    return typeof value === "string" ? value.replace("T", " ") : "Unavailable";
  } catch {
    return "Unavailable";
  }
}

function grouped(value: bigint): string {
  return value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
export function financialMoney(
  value: unknown,
  currency: "USD" | "KHR" = "USD",
): string {
  try {
    const amount = BigInt(
      financialInteger(value, -MAX_AGGREGATE - 1n, MAX_AGGREGATE),
    );
    const absolute = amount < 0n ? -amount : amount;
    const sign = amount < 0n ? "−" : "";
    return currency === "KHR"
      ? `KHR ${sign}${grouped(absolute)}`
      : `USD ${sign}${grouped(absolute / 100n)}.${(absolute % 100n).toString().padStart(2, "0")}`;
  } catch {
    return "Unavailable";
  }
}
export function financialLabel(value: unknown): string {
  return typeof value === "string" && value.length > 0 ? value : "Unavailable";
}

export function financialUiError(error: unknown): string {
  if (error instanceof FinancialInputError) return error.message;
  if (
    error instanceof FinancialContractError ||
    error instanceof FinancialJsonError
  )
    return "Check the financial fields and source references before continuing.";
  if (
    error instanceof FinancialClientError ||
    error instanceof FinancialReferenceError
  ) {
    if (error.code === "WORKSPACE_INVALIDATED")
      return "This workspace changed. Load the current financial records again.";
    if (error.code === "RESPONSE_TOO_LARGE")
      return "The financial evidence exceeds the display limit. A complete view is unavailable.";
    if (error.code === "INVALID_REQUEST")
      return "Check the financial fields and source references before continuing.";
    if (error.status === 403)
      return "You do not have permission for this financial action or record.";
    if (error.status === 404)
      return "The financial record is unavailable in this Property.";
    if (error.status === 409)
      return "The financial request could not be completed. Review its outcome and reload the current facts.";
  }
  return "Financial evidence is unavailable. Review any unresolved command before trying again.";
}

export type FinancialCommandRequest = Extract<
  FinancialRequest,
  { body: FinancialObject }
>;
export type FinancialReadRequest = Exclude<
  FinancialRequest,
  FinancialCommandRequest
>;
export interface FinancialUiServices {
  references: Pick<typeof financialReferenceClient, "read">;
  transport: FinancialTransport;
  recovery: FinancialRecovery;
}
export const FINANCIAL_COMMAND_CAPABILITIES: Record<
  FinancialCommandOperation,
  keyof FinancialCapabilities | null
> = {
  leaseWarningRecord: null,
  rentNonpaymentOpen: null,
  rentNonpaymentEvent: null,
  paymentRecord: "payments.record",
  allocationPost: "payments.allocate",
  allocationReverse: "payments.allocations.reverse",
  paymentReverse: "payments.reverse",
  receiptReprint: "receipts.reprint",
  creditRecognize: "credits.recognize",
  creditReverse: "credits.reverse",
  creditApply: "credits.apply",
  creditApplicationReverse: "credits.applications.reverse",
  refundCreate: "refunds.create",
  refundReturn: "refunds.correct",
  refundReturnReverse: "refunds.corrections.reverse",
};
/** Enforcement recovery stays in its own authorized staff workspace. */
export function financialCommandAllowed(
  capabilities: FinancialCapabilities | null | undefined,
  operation: FinancialCommandOperation,
): boolean {
  const capability = FINANCIAL_COMMAND_CAPABILITIES[operation];
  return capability !== null && capabilities?.[capability] === true;
}
export interface FinancialCommandReview {
  onRecorded?: () => void;
  consequence: string;
  evidence: ReactNode;
}
/** A shared, scope-bound preparation may publish only while it still owns the review. */
export interface FinancialReviewPreparation {
  isCurrent: () => boolean;
  review: (
    request: FinancialCommandRequest,
    review: FinancialCommandReview,
  ) => void;
}
export function originalFinancialReceiptId(resource: unknown): string | null {
  try {
    return financialId(financialObject(financialObject(resource).receipt).id);
  } catch {
    return null;
  }
}
export interface FinancialReceiptHandoff {
  readonly scope: FinancialScope;
  readonly receiptId: string;
}
export interface FinancialWorkspaceProps {
  onDirtyStateChange?: (dirty: boolean) => void;
  scope: FinancialScope;
  capabilities: FinancialCapabilities;
  services: FinancialUiServices;
  commands: {
    ready: boolean;
    busy: boolean;
    revision: number;
    beginReview: () => FinancialReviewPreparation;
    invalidate: () => void;
  };
}
export interface PreparedFinancialCommand {
  readonly actorId: string;
  readonly propertyId: string;
  readonly request: FinancialCommandRequest;
  readonly wireBody: string;
}
const preparedCommands = new WeakMap<object, AbortSignal>();
function freezeFinancial(value: FinancialJson): void {
  const pending = [value];
  while (pending.length > 0) {
    const item = pending.pop();
    if (item !== null && typeof item === "object") {
      if (!(item instanceof ExactJsonNumber))
        for (const child of Object.values(item)) pending.push(child);
      Object.freeze(item);
    }
  }
}

/** A confirmation owns the exact detached input that its labels describe. */
export function prepareFinancialCommand(
  suppliedScope: FinancialScope,
  input: FinancialCommandRequest,
): PreparedFinancialCommand {
  const scope = captureFinancialScope(suppliedScope);
  const captured = captureFinancialRequest(input);
  if (!isFinancialCommand(captured.operation) || captured.wireBody === null)
    return invalidFinancial();
  const body = commandBody(captured.operation, captured.wireBody);
  freezeFinancial(body);
  // captureFinancialRequest has already checked this operation's exact target keys.
  const request = Object.freeze({
    operation: captured.operation,
    target: Object.freeze({ ...captured.target }),
    body,
  }) as FinancialCommandRequest;
  const prepared = Object.freeze({
    actorId: scope.actorId,
    propertyId: scope.propertyId,
    request,
    wireBody: captured.wireBody,
  });
  preparedCommands.set(prepared, scope.signal);
  return prepared;
}

export function confirmedFinancialRequest(
  suppliedScope: FinancialScope,
  prepared: PreparedFinancialCommand,
): FinancialCommandRequest {
  const scope = captureFinancialScope(suppliedScope);
  if (
    preparedCommands.get(prepared) !== scope.signal ||
    scope.actorId !== prepared.actorId ||
    scope.propertyId !== prepared.propertyId
  )
    throw new FinancialClientError("WORKSPACE_INVALIDATED", false);
  if (captureFinancialRequest(prepared.request).wireBody !== prepared.wireBody)
    return invalidFinancial();
  return prepared.request;
}

export function selectedFinancialLineIntent(
  data: FinancialObject,
  values: Record<string, string>,
) {
  const rows = Array.isArray(data.items) ? data.items.map(financialObject) : [];
  const details: FinancialObject[] = [];
  let total = 0n;
  for (const [id, text] of Object.entries(values)) {
    if (!text) continue;
    const amount = parseFinancialAmount(text, "USD", true);
    if (amount === 0n) continue;
    const line = rows.find(
      (item) => item.id === id && item.kind === "INVOICE_LINE",
    );
    if (
      !line ||
      amount >
        BigInt(
          financialInteger(financialObject(line.data).outstanding_usd_cents),
        )
    )
      throw new FinancialInputError(
        "A selected line changed or the designated USD exceeds its current outstanding amount. Reload the target and review the designation.",
      );
    details.push({
      invoice_line_id: financialId(id),
      amount_usd_cents: amount,
    });
    total += amount;
  }
  if (!details.length || details.length > 500 || total > 9_000_000_000_000_000n)
    throw new FinancialInputError(
      "Select positive USD amounts on one to 500 current Invoice lines within the permitted amount.",
    );
  return { details, total };
}
