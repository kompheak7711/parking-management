import { validateEnforcementCommandReply } from "./leaseEnforcementContract";
import type { FinancialJson } from "./financialJson";
import {
  commandBody,
  financialId,
  financialInteger,
  financialInstant,
  financialObject,
  invalidFinancial,
  isFinancialCommand,
  type CapturedFinancialRequest,
  type FinancialObject,
} from "./financialContracts";

export interface FinancialReply {
  data: FinancialJson;
  page?: FinancialObject;
  requestId: string;
  propertyId: string;
}
function same(value: unknown, expected: unknown): void {
  if (financialId(value) !== financialId(expected)) invalidFinancial();
}
function array(value: unknown): FinancialJson[] {
  if (!Array.isArray(value)) return invalidFinancial();
  return value as FinancialJson[];
}
function nonempty(value: unknown): void {
  if (typeof value !== "string" || !value) invalidFinancial();
}
function money(value: unknown): void {
  financialInteger(value);
}
function payment(value: unknown, prop: string): FinancialObject {
  const row = financialObject(value);
  financialId(row.id);
  same(row.property_id, prop);
  financialId(row.payer_customer_id);
  if (
    !["USD", "KHR"].includes(
      typeof row.received_currency === "string" ? row.received_currency : "",
    ) ||
    !["RECEIVED", "REVERSED"].includes(
      typeof row.status === "string" ? row.status : "",
    )
  )
    invalidFinancial();
  financialInteger(row.received_amount_minor, 1n);
  financialInteger(row.usd_accounting_value_cents, 1n);
  return row;
}
function credit(
  value: unknown,
  prop: string,
  expected?: string,
): FinancialObject {
  const row = financialObject(value),
    source = financialObject(row.source_payment),
    item = financialObject(row.credit);
  financialId(item.id);
  if (expected) same(item.id, expected);
  financialId(item.customer_id);
  same(source.property_id, prop);
  same(item.source_payment_id, source.id as string);
  money(item.recognized_usd_cents);
  if (Object.hasOwn(row, "available_usd_cents")) money(row.available_usd_cents);
  else financialObject(row.position);
  return row;
}
function refund(
  value: unknown,
  prop: string,
  expected?: string,
): FinancialObject {
  const row = financialObject(value),
    item = financialObject(row.refund),
    source = financialObject(row.source);
  financialId(item.id);
  if (expected) same(item.id, expected);
  same(source.property_id, prop);
  financialId(source.id);
  if (
    !["PAYMENT", "CREDIT", "DEPOSIT"].includes(
      typeof source.type === "string" ? source.type : "",
    ) ||
    item.refund_currency !== "USD"
  )
    invalidFinancial();
  financialInteger(item.refund_amount_minor, 1n);
  money(row.net_refund_usd_cents);
  const sourceField =
    source.type === "PAYMENT"
      ? "source_payment_id"
      : source.type === "CREDIT"
        ? "source_customer_credit_id"
        : "source_deposit_id";
  same(item[sourceField], source.id as string);
  return row;
}
function page(
  value: unknown,
  items: FinancialJson[],
  request: CapturedFinancialRequest,
): FinancialObject {
  const row = financialObject(value);
  const limit = Number(financialInteger(row.limit, 1n, 100n));
  const expected = Number(request.query.limit ?? 50);
  if (
    limit !== expected ||
    items.length > limit ||
    !(
      row.next_cursor === null ||
      (typeof row.next_cursor === "string" &&
        row.next_cursor.length > 0 &&
        row.next_cursor.length <= 1024)
    )
  )
    invalidFinancial();
  return row;
}
function history(value: unknown, request: CapturedFinancialRequest): void {
  const row = financialObject(value);
  page(row.page, array(row.items), request);
}
/** Exact numeric evidence is retained. Money tokens and Property references fail closed. */
function exactEvidence(data: FinancialJson, prop: string): void {
  const stack: FinancialJson[] = [data];
  while (stack.length) {
    const value = stack.pop();
    if (value === undefined) return invalidFinancial();
    if (Array.isArray(value)) {
      for (const child of value) stack.push(child);
    } else if (value !== null && typeof value === "object") {
      // Decimal evidence has no nested financial fields; the exact codec owns its token.
      for (const [key, child] of Object.entries(value)) {
        if (key === "property_id" && child !== null) same(child, prop);
        if (child !== null && /(?:_cents|_minor|^minor_units)$/.test(key))
          financialInteger(child, -9_223_372_036_854_775_807n);
        if (key === "refund_currency" && child !== "USD") invalidFinancial();
        stack.push(child as FinancialJson);
      }
    }
  }
}
function validateCreditProposalBatch(
  row: FinancialObject,
  request: CapturedFinancialRequest,
): void {
  const requested = BigInt(
    financialInteger(
      request.query.amount_usd_cents,
      1n,
      9_000_000_000_000_000n,
    ),
  );
  const batch = BigInt(financialInteger(row.amount_usd_cents, 1n, requested));
  const details = array(row.details);
  const continuationFields = [
    "requested_amount_usd_cents",
    "remaining_requested_usd_cents",
    "continuation_status",
    "continuation",
  ];
  // Retain the accepted complete-response contract. Partial batches, and every
  // response declaring continuation, must prove the complete continuation tuple.
  if (
    batch === requested &&
    !continuationFields.some((key) => Object.hasOwn(row, key))
  )
    return;
  if (
    BigInt(financialInteger(row.requested_amount_usd_cents, 1n, requested)) !==
      requested ||
    BigInt(
      financialInteger(row.remaining_requested_usd_cents, 0n, requested),
    ) !==
      requested - batch ||
    row.continuation_status !==
      (batch === requested ? "COMPLETE" : "MORE_ELIGIBLE") ||
    row.continuation !== "CONFIRM_PAGE_THEN_REQUEST_FRESH_PROPOSAL" ||
    row.policy !== "RENT_SERVICE_SOURCE_ORDER" ||
    details.length < 1 ||
    details.length > 500
  )
    invalidFinancial();
  financialInteger(row.available_usd_cents, requested);
  financialId(row.customer_id);
  financialInteger(row.invoice_version, 1n);
  financialInstant(row.generated_at);
  const seen = new Set<string>();
  let total = 0n;
  for (const value of details) {
    const line = financialObject(value),
      id = financialId(line.invoice_line_id);
    if (seen.has(id)) invalidFinancial();
    seen.add(id);
    const amount = BigInt(financialInteger(line.amount_usd_cents, 1n, batch));
    financialInteger(line.outstanding_usd_cents, amount);
    nonempty(line.category);
    if (
      typeof line.attribution_basis !== "string" ||
      !["RENT_FIRST_PROPOSAL", "SERVICE_PROPOSAL", "OTHER_CONFIRMED"].includes(
        line.attribution_basis,
      )
    )
      invalidFinancial();
    total += amount;
    if (total > batch) invalidFinancial();
  }
  if (total !== batch) invalidFinancial();
}

export function validateFinancialReply(
  envelope: FinancialObject,
  request: CapturedFinancialRequest,
  prop: string,
  requestId: string,
  actorId?: string,
): FinancialReply {
  if (!Object.hasOwn(envelope, "data") || Object.hasOwn(envelope, "error"))
    return invalidFinancial();
  const meta = financialObject(envelope.meta);
  same(meta.property_id, prop);
  if (meta.request_id !== requestId) invalidFinancial();
  const data = envelope.data;
  if (data === undefined) return invalidFinancial();
  const op = request.operation,
    id = request.target.id;
  exactEvidence(data, prop);
  let topPage: FinancialObject | undefined;
  if (
    ["paymentList", "creditList", "refundList"].includes(op) ||
    (op === "allocationList" && !request.query.allocation_id)
  ) {
    const rows = array(data);
    topPage = page(envelope.page, rows, request);
    for (const value of rows) {
      if (op === "paymentList") {
        const p = payment(financialObject(value).payment, prop);
        if (request.query.customer_id)
          same(p.payer_customer_id, request.query.customer_id as string);
        if (request.query.payment_method_id)
          same(p.payment_method_id, request.query.payment_method_id as string);
        if (request.query.status && p.status !== request.query.status)
          invalidFinancial();
      } else if (op === "creditList")
        same(financialObject(credit(value, prop).credit).customer_id, id);
      else if (op === "refundList") {
        const item = financialObject(refund(value, prop).refund);
        if (request.query.customer_id)
          same(item.recipient_customer_id, request.query.customer_id as string);
      } else {
        const item = financialObject(value);
        financialId(item.id);
        same(item.payment_id, id);
      }
    }
  } else {
    const row = financialObject(data);
    const body = isFinancialCommand(op)
      ? commandBody(op, request.wireBody ?? invalidFinancial())
      : {};
    switch (op) {
      case "leaseWarningRecord":
      case "rentNonpaymentOpen":
      case "rentNonpaymentEvent":
        validateEnforcementCommandReply(
          row,
          body,
          op,
          financialId(id),
          prop,
          financialId(actorId),
        );
        break;
      case "paymentGet":
      case "paymentRecord": {
        const item = payment(row.payment, prop);
        if (op === "paymentGet") {
          same(item.id, id);
          financialObject(row.position);
        } else {
          same(item.payer_customer_id, body.payer_customer_id as string);
          same(item.payment_method_id, body.payment_method_id as string);
          if (item.status !== "RECEIVED") invalidFinancial();
          const amount = financialObject(body.amount);
          if (
            item.received_currency !== amount.currency ||
            BigInt(financialInteger(item.received_amount_minor)) !==
              BigInt(financialInteger(amount.minor_units))
          )
            invalidFinancial();
          const usd =
            amount.currency === "USD"
              ? amount
              : financialObject(body.usd_accounting_amount);
          if (
            BigInt(financialInteger(item.usd_accounting_value_cents)) !==
            BigInt(financialInteger(usd.minor_units))
          )
            invalidFinancial();
          const receipt = financialObject(row.receipt);
          financialId(receipt.id);
          same(receipt.payment_id, item.id);
          nonempty(receipt.receipt_number);
        }
        break;
      }
      case "allocationProposal":
        same(row.payment_id, id);
        same(row.property_id, prop);
        money(row.available_usd_cents);
        array(row.targets);
        break;
      case "allocationList": {
        const selected = financialObject(row.allocation);
        same(selected.id, request.query.allocation_id as string);
        same(selected.payment_id, id);
        topPage = page(envelope.page, array(row.details), request);
        break;
      }
      case "allocationPost":
        same(row.payment_id, id);
        if (!array(row.allocation_ids).length) invalidFinancial();
        for (const value of array(row.allocation_ids)) financialId(value);
        money(row.available_usd_cents);
        break;
      case "allocationReverse":
        same(row.allocation_id, id);
        financialId(row.reversal_id);
        financialId(row.payment_id);
        money(row.available_usd_cents);
        break;
      case "paymentReverse":
        same(row.payment_id, id);
        financialId(row.reversal_id);
        if (row.status !== "REVERSED") invalidFinancial();
        break;
      case "paymentReceipt":
      case "receiptGet": {
        const item = financialObject(row.receipt);
        const p = payment(row.payment, prop);
        financialId(item.id);
        same(item.payment_id, p.id as string);
        if (op === "paymentReceipt") same(p.id, id);
        else same(item.id, id);
        nonempty(item.receipt_number);
        financialObject(row.financial_position);
        history(row.reprints, request);
        break;
      }
      case "receiptReprint":
        same(row.receipt_id, id);
        nonempty(row.receipt_number);
        financialId(financialObject(row.reprint).id);
        same(financialObject(row.reprint).receipt_id, id);
        break;
      case "creditGet":
      case "creditLedger":
      case "creditReverse":
        credit(row, prop, id);
        if (op === "creditLedger") history(row.history, request);
        if (op === "creditReverse") {
          const reversal = financialObject(row.recognition_reversal);
          financialId(reversal.id);
          same(reversal.customer_credit_id, id);
        }
        break;
      case "creditRecognize": {
        const item = financialObject(credit(row, prop).credit);
        same(item.source_payment_id, id);
        if (
          BigInt(financialInteger(item.recognized_usd_cents)) !==
          BigInt(financialInteger(body.amount_usd_cents))
        )
          invalidFinancial();
        break;
      }
      case "creditProposal":
        same(row.credit_id, id);
        same(row.property_id, prop);
        same(row.invoice_id, request.query.invoice_id as string);
        validateCreditProposalBatch(row, request);
        break;
      case "creditApply":
      case "creditApplication":
      case "creditApplicationReverse": {
        const item = financialObject(row.application);
        financialId(item.id);
        financialId(item.customer_credit_id);
        array(row.details);
        credit(row.credit_position, prop, item.customer_credit_id as string);
        money(row.target_balance_usd_cents);
        if (op === "creditApply") {
          same(item.customer_credit_id, id);
          const intent = financialObject(body.intent);
          const target =
            intent.mode === "PROPOSAL"
              ? financialObject(intent.proposal)
              : intent;
          const field = Object.hasOwn(target, "invoice_id")
            ? "invoice_id"
            : "late_payment_charge_id";
          same(item[field], target[field]);
          if (
            BigInt(financialInteger(item.amount_usd_cents)) !==
            BigInt(financialInteger(target.amount_usd_cents))
          )
            invalidFinancial();
        } else same(item.id, id);
        if (op === "creditApplicationReverse") {
          const reversal = financialObject(row.reversal);
          financialId(reversal.id);
          same(reversal.credit_application_id, id);
        }
        break;
      }
      case "refundGet":
        refund(row, prop, id);
        history(row.corrections, request);
        break;
      case "refundReturn":
      case "refundReturnReverse": {
        refund(row, prop, id);
        history(row.corrections, request);
        // Both commands append strictly after all existing corrections and save
        // this exact response for replay. The first event is their consequence.
        const event = financialObject(
          array(financialObject(row.corrections).items)[0],
        );
        financialId(event.id);
        same(event.refund_id, id);
        if (
          event.reason !== body.reason ||
          event.evidence_reference !== body.evidence_reference
        )
          invalidFinancial();
        const effect = BigInt(
          financialInteger(
            event.source_balance_effect_usd_cents,
            -9_000_000_000_000_000n,
          ),
        );
        if (
          BigInt(
            financialInteger(
              event.source_balance_effect_original_minor,
              -9_000_000_000_000_000n,
            ),
          ) !== effect
        )
          invalidFinancial();
        const payout = BigInt(
          financialInteger(
            financialObject(row.refund).refund_amount_minor,
            1n,
            9_000_000_000_000_000n,
          ),
        );
        const previous = BigInt(
          financialInteger(event.previous_net_refund_usd_cents, 0n, payout),
        );
        const resulting = BigInt(
          financialInteger(event.resulting_net_refund_usd_cents, 0n, payout),
        );
        if (
          resulting !== previous - effect ||
          BigInt(financialInteger(row.net_refund_usd_cents)) !== resulting
        )
          invalidFinancial();
        if (op === "refundReturn") {
          if (
            event.correction_kind !== "VALUE_CORRECTION" ||
            event.reverses_correction_id !== null ||
            event.verified_return_currency !== "USD" ||
            effect !==
              BigInt(financialInteger(body.returned_amount_minor, 1n)) ||
            BigInt(financialInteger(event.verified_return_amount_minor, 1n)) !==
              effect ||
            event.return_method_reference !== body.return_method_reference ||
            financialInstant(event.verified_returned_at) !==
              financialInstant(body.returned_at)
          )
            invalidFinancial();
        } else {
          same(event.reverses_correction_id, request.target.correctionId);
          if (
            event.correction_kind !== "CORRECTION_REVERSAL" ||
            effect >= 0n ||
            financialId(event.id) ===
              financialId(request.target.correctionId) ||
            event.verified_return_amount_minor !== null ||
            event.verified_return_currency !== null ||
            event.verified_returned_at !== null ||
            event.return_method_reference !== null
          )
            invalidFinancial();
        }
        break;
      }
      case "refundCreate": {
        const item = refund(row, prop);
        const source = financialObject(item.source),
          r = financialObject(item.refund);
        same(source.id, body.source_id as string);
        if (
          source.type !==
            (body.source_type === "PET_DEPOSIT"
              ? "DEPOSIT"
              : body.source_type) ||
          BigInt(financialInteger(r.refund_amount_minor)) !==
            BigInt(financialInteger(body.amount_usd_cents))
        )
          invalidFinancial();
        if (body.source_type === "PET_DEPOSIT") {
          same(r.pet_refund_review_id, body.pet_refund_review_id as string);
          same(
            financialObject(row.pet_refund_review).id,
            body.pet_refund_review_id as string,
          );
        }
        history(row.corrections, request);
        break;
      }
      case "refundSource":
        same(row.source_id, id);
        same(row.property_id, prop);
        if (
          row.source_type !== request.target.sourceType ||
          row.refund_currency !== "USD" ||
          typeof row.eligible !== "boolean"
        )
          invalidFinancial();
        money(row.available_usd_cents);
        if (request.target.sourceType === "PET_DEPOSIT")
          same(
            row.pet_refund_review_id,
            request.query.pet_refund_review_id as string,
          );
        break;
      default:
        invalidFinancial();
    }
  }
  return {
    data,
    ...(topPage ? { page: topPage } : {}),
    requestId,
    propertyId: prop,
  };
}
