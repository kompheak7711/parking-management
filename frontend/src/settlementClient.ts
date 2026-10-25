// The browser client of the V1-056 slice 11 routes: the move-out cleaning charge and the
// hand-back month (11a), the walk-in Security Deposit and Deposit receipts (11c-4), the shared
// financial drafts and the draft routes of slices 11c and 11d, and the Final Settlement and its
// corrections (11e). Screens build on it; it shows a named refusal's code, text and fields.
import type {
  AddRefundMethodInput,
  AdjustmentReversalCorrectionInput,
  AdjustmentReversalInput,
  ChargeReductionInput,
  CleaningChargeInput,
  CleaningRateInput,
  DepositReceiptCorrectionInput,
  DepositReceiptCreate,
  ExtraChargeInput,
  FinalSettlementDraftInput,
  ForfeitureDraftInput,
  ForfeitureReversalCorrectionInput,
  ForfeitureReversalDraftInput,
  HandBackResolutionInput,
  HeldValueRefundCorrectionInput,
  LateChargeReductionInput,
  LateChargeRefundCorrectionInput,
  MoveCorrectionInput,
  PaymentMoveDraftInput,
  PaymentReturnDraftInput,
  PetClassificationCorrectionInput,
  ReceiptReversalDraftInput,
  RefundCorrectionInput,
  RefundMethodStateInput,
  RefundReturnCorrectionInput,
  ReturnReversalCorrectionInput,
  ReturnedPaymentInput,
  ReversalInput,
  SecurityDepositCreate,
} from "./settlementForms";

export type DraftState = "PENDING" | "CONFIRMED" | "REJECTED" | "WITHDRAWN";

export interface FinancialDraftDecision {
  decision: Exclude<DraftState, "PENDING">;
  reason: string | null;
  decided_at: string;
  decided_by: string;
  authorization_reference: string | null;
  result: unknown;
}

export interface FinancialDraft {
  draft_id: string;
  property_id: string;
  kind: string;
  prepare_capability: string;
  payload: Record<string, unknown>;
  source_revision?: unknown;
  reason: string;
  prepared_at: string;
  prepared_by: string;
  state: DraftState;
  decision: FinancialDraftDecision | null;
}

export interface DraftConfirmation {
  draft: FinancialDraft;
  result: unknown;
}

export interface FinancialDraftPage {
  items: FinancialDraft[];
  next_cursor: string | null;
}

// Answers the screens read field by field; the routes check their shape on the server.
export type SettlementRecord = Record<string, unknown>;

export class SettlementUnavailableError extends Error {
  constructor() {
    super("This service is not available right now. Try again later.");
    this.name = "SettlementUnavailableError";
  }
}

// A refusal the server named: its code, its plain text and the form fields it is about.
export class SettlementRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
    message: string,
    readonly fields: string[] = [],
    readonly ruleIds: string[] = [],
    readonly currentVersion: number | null = null,
  ) {
    super(message);
    this.name = "SettlementRequestError";
  }
}

const FALLBACK =
  "The request was not completed. Check the record before trying again.";

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const values = document.cookie
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part.startsWith(prefix));
  try {
    if (values.length !== 1) throw new Error();
    const value = decodeURIComponent((values[0] ?? "").slice(prefix.length));
    if (!value) throw new Error();
    return value;
  } catch {
    throw new SettlementRequestError(403, null, FALLBACK);
  }
}

function texts(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

// A named refusal names bare form fields; a plain form check names them under "body.".
function formFields(value: unknown): string[] {
  return [
    ...new Set(texts(value).map((field) => field.replace(/^body\./, ""))),
  ];
}

function refusal(status: number, body: unknown): SettlementRequestError {
  const error =
    typeof body === "object" && body !== null && "error" in body
      ? (body as { error: unknown }).error
      : null;
  if (typeof error !== "object" || error === null)
    return new SettlementRequestError(status, null, FALLBACK);
  const named = error as Record<string, unknown>;
  return new SettlementRequestError(
    status,
    typeof named.code === "string" ? named.code : null,
    typeof named.message === "string" ? named.message : FALLBACK,
    formFields(named.fields),
    texts(named.rule_ids),
    typeof named.current_version === "number" ? named.current_version : null,
  );
}

async function send(
  path: string,
  init: RequestInit,
  propertyId?: string,
): Promise<Record<string, unknown>> {
  const headers = new Headers(init.headers);
  if (propertyId !== undefined)
    headers.set("X-Financial-Property-ID", propertyId);
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init, headers });
  } catch {
    throw new SettlementUnavailableError();
  }
  if (response.status === 503) throw new SettlementUnavailableError();
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) throw refusal(response.status, body);
  if (typeof body !== "object" || body === null || !("data" in body))
    throw new SettlementRequestError(response.status, null, FALLBACK);
  return body as Record<string, unknown>;
}

function record(value: unknown): SettlementRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new SettlementRequestError(200, null, FALLBACK);
  return value as SettlementRecord;
}

async function read(
  path: string,
  propertyId?: string,
): Promise<SettlementRecord> {
  return record((await send(path, { method: "GET" }, propertyId)).data);
}

async function post(
  path: string,
  source: object | null,
  key: string | null,
  propertyId?: string,
  version?: number,
): Promise<SettlementRecord> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrfToken(),
  };
  if (key !== null) headers["Idempotency-Key"] = key;
  if (version !== undefined) {
    if (!Number.isSafeInteger(version) || version < 1)
      throw new SettlementRequestError(412, null, FALLBACK);
    headers["If-Match"] = `"${String(version)}"`;
  }
  const init: RequestInit = {
    method: "POST",
    headers,
    body: JSON.stringify(source ?? {}),
  };
  return record((await send(path, init, propertyId)).data);
}

const id = encodeURIComponent;

function property(propertyId: string): string {
  return `/api/v1/properties/${id(propertyId)}`;
}

function settlement(propertyId: string, settlementId: string): string {
  return `${property(propertyId)}/final-settlements/${id(settlementId)}`;
}

function correction(
  route: string,
): (
  propertyId: string,
  settlementId: string,
  form: object,
  key: string,
) => Promise<FinancialDraft> {
  return async (propertyId, settlementId, form, key) =>
    (await post(
      `${settlement(propertyId, settlementId)}/corrections/${route}`,
      form,
      key,
      propertyId,
    )) as unknown as FinancialDraft;
}

type Correction<Form> = (
  propertyId: string,
  settlementId: string,
  form: Form,
  key: string,
) => Promise<FinancialDraft>;

export interface SettlementApi {
  // Slice 11a: the move-out cleaning charge and the hand-back month.
  cleaningRate: (
    propertyId: string,
    unitId: string,
  ) => Promise<SettlementRecord>;
  // The form's rate_id and charge_id are the retry identity; these routes take no key.
  setCleaningRate: (
    propertyId: string,
    unitId: string,
    form: CleaningRateInput,
  ) => Promise<SettlementRecord>;
  chargeCleaning: (
    propertyId: string,
    leaseId: string,
    form: CleaningChargeInput,
  ) => Promise<SettlementRecord>;
  handBackAssessment: (invoiceId: string) => Promise<SettlementRecord>;
  // version is the Invoice version the screen showed (sent as If-Match). After a lost answer,
  // retry with the same key and the same version: a new version with the same key is refused.
  resolveHandBack: (
    invoiceId: string,
    version: number,
    form: HandBackResolutionInput,
    key: string,
  ) => Promise<SettlementRecord>;
  // Slice 11c-4: the walk-in Security Deposit and a receipt into a Deposit.
  createSecurityDeposit: (
    leaseId: string,
    form: SecurityDepositCreate,
    key: string,
  ) => Promise<SettlementRecord>;
  receiveIntoDeposit: (
    depositId: string,
    form: DepositReceiptCreate,
    key: string,
  ) => Promise<SettlementRecord>;
  // Slice 11b and 11c-1: the shared drafts and the Refund methods a draft may name.
  // A cursor goes back with the same state it came with; limit is 1 to 100.
  drafts: (
    propertyId: string,
    options?: { state?: DraftState; limit?: number; cursor?: string },
  ) => Promise<FinancialDraftPage>;
  draft: (propertyId: string, draftId: string) => Promise<FinancialDraft>;
  confirmDraft: (
    propertyId: string,
    draftId: string,
    key: string,
  ) => Promise<DraftConfirmation>;
  rejectDraft: (
    propertyId: string,
    draftId: string,
    form: ReversalInput,
    key: string,
  ) => Promise<SettlementRecord>;
  withdrawDraft: (
    propertyId: string,
    draftId: string,
    form: ReversalInput,
    key: string,
  ) => Promise<SettlementRecord>;
  refundMethods: (propertyId: string) => Promise<SettlementRecord[]>;
  // Slice 11h: adding a Refund method and turning one off or on (Settings access). The id is
  // chosen by the client, so sending the same form again answers the same method.
  addRefundMethod: (
    propertyId: string,
    form: AddRefundMethodInput,
  ) => Promise<SettlementRecord>;
  setRefundMethodState: (
    propertyId: string,
    refundMethodId: string,
    form: RefundMethodStateInput,
  ) => Promise<SettlementRecord>;
  // Slices 11c-3, 11d and 11e-2: drafts recorded on their own record.
  forfeitureDraft: (
    propertyId: string,
    depositId: string,
    form: ForfeitureDraftInput,
    key: string,
  ) => Promise<FinancialDraft>;
  forfeitureReversalDraft: (
    propertyId: string,
    dispositionId: string,
    form: ForfeitureReversalDraftInput,
    key: string,
  ) => Promise<FinancialDraft>;
  receiptReversalDraft: (
    propertyId: string,
    receiptId: string,
    form: ReceiptReversalDraftInput,
    key: string,
  ) => Promise<FinancialDraft>;
  paymentReturnDraft: (
    propertyId: string,
    paymentId: string,
    form: PaymentReturnDraftInput,
    key: string,
  ) => Promise<FinancialDraft>;
  paymentMoveDraft: (
    propertyId: string,
    allocationId: string,
    form: PaymentMoveDraftInput,
    key: string,
  ) => Promise<FinancialDraft>;
  adjustmentReversalDraft: (
    propertyId: string,
    adjustmentId: string,
    form: AdjustmentReversalInput,
    key: string,
  ) => Promise<FinancialDraft>;
  // Slice 11e-1: the Final Settlement.
  startSettlement: (
    propertyId: string,
    leaseId: string,
    key: string,
  ) => Promise<SettlementRecord>;
  settlementPreview: (
    propertyId: string,
    settlementId: string,
  ) => Promise<SettlementRecord>;
  settlementDraft: Correction<FinalSettlementDraftInput>;
  // Slices 11e-2 and 11e-3: the post-settlement corrections.
  extraCharge: Correction<ExtraChargeInput>;
  chargeReduction: Correction<ChargeReductionInput>;
  lateChargeReduction: Correction<LateChargeReductionInput>;
  returnedPayment: Correction<ReturnedPaymentInput>;
  paymentMove: Correction<MoveCorrectionInput>;
  adjustmentReversal: Correction<AdjustmentReversalCorrectionInput>;
  refund: Correction<RefundCorrectionInput>;
  lateChargeRefund: Correction<LateChargeRefundCorrectionInput>;
  petClassification: Correction<PetClassificationCorrectionInput>;
  refundReturn: Correction<RefundReturnCorrectionInput>;
  heldValueRefund: Correction<HeldValueRefundCorrectionInput>;
  forfeitureReversal: Correction<ForfeitureReversalCorrectionInput>;
  depositReceiptCorrection: Correction<DepositReceiptCorrectionInput>;
  returnReversal: Correction<ReturnReversalCorrectionInput>;
}

function draftOn(
  resource: string,
  route: string,
): (
  propertyId: string,
  identity: string,
  form: object,
  key: string,
) => Promise<FinancialDraft> {
  return async (propertyId, identity, form, key) =>
    (await post(
      `${property(propertyId)}/${resource}/${id(identity)}/${route}`,
      form,
      key,
      propertyId,
    )) as unknown as FinancialDraft;
}

export const settlementApi: SettlementApi = {
  cleaningRate: (propertyId, unitId) =>
    read(`${property(propertyId)}/units/${id(unitId)}/cleaning-rate`),
  setCleaningRate: (propertyId, unitId, form) =>
    post(
      `${property(propertyId)}/units/${id(unitId)}/cleaning-rates`,
      form,
      null,
    ),
  chargeCleaning: (propertyId, leaseId, form) =>
    post(
      `${property(propertyId)}/leases/${id(leaseId)}/cleaning-charge`,
      form,
      null,
    ),
  handBackAssessment: (invoiceId) =>
    read(`/api/v1/invoices/${id(invoiceId)}/hand-back-assessment`),
  resolveHandBack: (invoiceId, version, form, key) =>
    post(
      `/api/v1/invoices/${id(invoiceId)}/hand-back-resolution`,
      form,
      key,
      undefined,
      version,
    ),
  createSecurityDeposit: (leaseId, form, key) =>
    post(`/api/v1/leases/${id(leaseId)}/security-deposit`, form, key),
  receiveIntoDeposit: (depositId, form, key) =>
    post(`/api/v1/deposits/${id(depositId)}/receipts`, form, key),
  drafts: async (propertyId, options = {}) => {
    const query = new URLSearchParams();
    if (options.state !== undefined) query.set("state", options.state);
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    if (options.cursor !== undefined) query.set("cursor", options.cursor);
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    const body = await send(
      `${property(propertyId)}/financial-drafts${suffix}`,
      { method: "GET" },
      propertyId,
    );
    if (!Array.isArray(body.data))
      throw new SettlementRequestError(200, null, FALLBACK);
    const page =
      typeof body.page === "object" && body.page !== null
        ? (body.page as Record<string, unknown>)
        : {};
    return {
      items: body.data.map(record) as unknown as FinancialDraft[],
      next_cursor:
        typeof page.next_cursor === "string" ? page.next_cursor : null,
    };
  },
  draft: async (propertyId, draftId) =>
    (await read(
      `${property(propertyId)}/financial-drafts/${id(draftId)}`,
      propertyId,
    )) as unknown as FinancialDraft,
  confirmDraft: async (propertyId, draftId, key) => {
    const answer = await post(
      `${property(propertyId)}/financial-drafts/${id(draftId)}/confirm`,
      null,
      key,
      propertyId,
    );
    return {
      draft: record(answer.draft) as unknown as FinancialDraft,
      result: answer.result,
    };
  },
  rejectDraft: (propertyId, draftId, form, key) =>
    post(
      `${property(propertyId)}/financial-drafts/${id(draftId)}/reject`,
      form,
      key,
      propertyId,
    ),
  withdrawDraft: (propertyId, draftId, form, key) =>
    post(
      `${property(propertyId)}/financial-drafts/${id(draftId)}/withdraw`,
      form,
      key,
      propertyId,
    ),
  refundMethods: async (propertyId) => {
    const body = await send(
      `${property(propertyId)}/refund-methods`,
      { method: "GET" },
      propertyId,
    );
    if (!Array.isArray(body.data))
      throw new SettlementRequestError(200, null, FALLBACK);
    return body.data.map(record);
  },
  addRefundMethod: (propertyId, form) =>
    post(`${property(propertyId)}/refund-methods`, form, null, propertyId),
  setRefundMethodState: (propertyId, refundMethodId, form) =>
    post(
      `${property(propertyId)}/refund-methods/${id(refundMethodId)}/state`,
      form,
      null,
      propertyId,
    ),
  forfeitureDraft: draftOn("deposits", "forfeiture-drafts"),
  forfeitureReversalDraft: draftOn("deposit-dispositions", "reversal-drafts"),
  receiptReversalDraft: draftOn("deposit-receipts", "reversal-drafts"),
  paymentReturnDraft: draftOn("payments", "return-drafts"),
  paymentMoveDraft: draftOn("payment-allocations", "move-drafts"),
  adjustmentReversalDraft: draftOn("invoice-adjustments", "reversal-drafts"),
  startSettlement: (propertyId, leaseId, key) =>
    post(
      `${property(propertyId)}/leases/${id(leaseId)}/final-settlement`,
      null,
      key,
      propertyId,
    ),
  settlementPreview: (propertyId, settlementId) =>
    read(`${settlement(propertyId, settlementId)}/preview`, propertyId),
  settlementDraft: async (propertyId, settlementId, form, key) =>
    (await post(
      `${settlement(propertyId, settlementId)}/drafts`,
      form,
      key,
      propertyId,
    )) as unknown as FinancialDraft,
  extraCharge: correction("extra-charges"),
  chargeReduction: correction("charge-reductions"),
  lateChargeReduction: correction("late-charge-reductions"),
  returnedPayment: correction("returned-payments"),
  paymentMove: correction("payment-moves"),
  adjustmentReversal: correction("adjustment-reversals"),
  refund: correction("refunds"),
  lateChargeRefund: correction("late-charge-refunds"),
  petClassification: correction("pet-classifications"),
  refundReturn: correction("refund-returns"),
  heldValueRefund: correction("held-value-refunds"),
  forfeitureReversal: correction("forfeiture-reversals"),
  depositReceiptCorrection: correction("deposit-receipt-corrections"),
  returnReversal: correction("return-reversals"),
};
