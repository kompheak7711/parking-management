import type {
  FinancialRequest,
  FinancialOperation,
  FinancialObject,
} from "../financialContracts";
import type { FinancialJson } from "../financialJson";
export const ids = {
  actor: "11111111-1111-4111-8111-111111111111",
  property: "22222222-2222-4222-8222-222222222222",
  payment: "33333333-3333-4333-8333-333333333333",
  customer: "44444444-4444-4444-8444-444444444444",
  credit: "55555555-5555-4555-8555-555555555555",
  refund: "66666666-6666-4666-8666-666666666666",
  allocation: "77777777-7777-4777-8777-777777777777",
  receipt: "88888888-8888-4888-8888-888888888888",
  application: "99999999-9999-4999-8999-999999999999",
  event: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  invoice: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  method: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  key: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  other: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
};
export const paymentBody: FinancialObject = {
  payer_customer_id: ids.customer,
  payment_method_id: ids.method,
  received_at: "2026-09-01T12:00:00+07:00",
  evidence_reference: "Synthetic receipt",
  amount: { currency: "USD", minor_units: 100 },
};
export const commands: FinancialRequest[] = [
  { operation: "paymentRecord", target: {}, body: paymentBody },
  {
    operation: "allocationPost",
    target: { id: ids.payment },
    body: {
      intent: {
        mode: "DIRECT_CHARGE",
        late_payment_charge_id: ids.invoice,
        amount_usd_cents: 100,
      },
    },
  },
  {
    operation: "allocationReverse",
    target: { id: ids.allocation },
    body: { reason: "Synthetic correction" },
  },
  {
    operation: "paymentReverse",
    target: { id: ids.payment },
    body: { reason: "Synthetic correction", expected_status: "RECEIVED" },
  },
  {
    operation: "receiptReprint",
    target: { id: ids.receipt },
    body: { reason: "Synthetic reprint", delivery_reference: "Desk" },
  },
  {
    operation: "creditRecognize",
    target: { id: ids.payment },
    body: {
      currency: "USD",
      amount_usd_cents: 100,
      payer_authorization_reference: "Synthetic payer approval",
      reason: "Synthetic recognition",
    },
  },
  {
    operation: "creditReverse",
    target: { id: ids.credit },
    body: { reason: "Synthetic correction" },
  },
  {
    operation: "creditApply",
    target: { id: ids.credit },
    body: {
      currency: "USD",
      intent: {
        mode: "DIRECT_CHARGE",
        late_payment_charge_id: ids.invoice,
        amount_usd_cents: 100,
      },
    },
  },
  {
    operation: "creditApplicationReverse",
    target: { id: ids.application },
    body: { reason: "Synthetic correction" },
  },
  {
    operation: "refundCreate",
    target: {},
    body: {
      currency: "USD",
      source_type: "PAYMENT",
      source_id: ids.payment,
      amount_usd_cents: 100,
      reason: "Synthetic refund",
    },
  },
  {
    operation: "refundReturn",
    target: { id: ids.refund },
    body: {
      currency: "USD",
      returned_amount_minor: 100,
      returned_at: "2026-09-01T12:00:00Z",
      return_method_reference: "Synthetic evidence",
      evidence_reference: "Synthetic evidence",
      reason: "Synthetic return",
    },
  },
  {
    operation: "refundReturnReverse",
    target: { id: ids.refund, correctionId: ids.event },
    body: {
      evidence_reference: "Synthetic evidence",
      reason: "Synthetic correction",
    },
  },
];
export const reads: FinancialRequest[] = [
  { operation: "paymentList", target: {} },
  { operation: "paymentGet", target: { id: ids.payment } },
  { operation: "allocationProposal", target: { id: ids.payment } },
  { operation: "allocationList", target: { id: ids.payment } },
  { operation: "paymentReceipt", target: { id: ids.payment } },
  { operation: "receiptGet", target: { id: ids.receipt } },
  { operation: "creditList", target: { id: ids.customer } },
  { operation: "creditGet", target: { id: ids.credit } },
  { operation: "creditLedger", target: { id: ids.credit } },
  {
    operation: "creditProposal",
    target: { id: ids.credit },
    query: { invoice_id: ids.invoice, amount_usd_cents: 100 },
  },
  { operation: "creditApplication", target: { id: ids.application } },
  { operation: "refundList", target: {} },
  { operation: "refundGet", target: { id: ids.refund } },
  {
    operation: "refundSource",
    target: { id: ids.payment, sourceType: "PAYMENT" },
  },
];
export function fixture(
  operation: FinancialOperation,
): FinancialObject & { data: FinancialJson; meta: FinancialObject } {
  const page = { limit: 50, next_cursor: null },
    history = { items: [], page };
  const payment = {
    id: ids.payment,
    property_id: ids.property,
    payer_customer_id: ids.customer,
    payment_method_id: ids.method,
    status: "RECEIVED",
    received_currency: "USD",
    received_amount_minor: 100,
    usd_accounting_value_cents: 100,
  };
  const paymentResource = {
    payment,
    position: { available_usd_cents: 100 },
    receipt: { id: ids.receipt },
  };
  const credit = {
    credit: {
      id: ids.credit,
      customer_id: ids.customer,
      source_payment_id: ids.payment,
      recognized_usd_cents: 100,
    },
    source_payment: payment,
    available_usd_cents: 100,
  };
  const application = {
    application: {
      id: ids.application,
      customer_credit_id: ids.credit,
      late_payment_charge_id: ids.invoice,
      amount_usd_cents: 100,
    },
    credit_position: credit,
    details: [],
    target_balance_usd_cents: 0,
    target_invoice_status: null,
  };
  const refund = {
    refund: {
      id: ids.refund,
      recipient_customer_id: ids.customer,
      refund_currency: "USD",
      refund_amount_minor: 100,
      source_payment_id: ids.payment,
    },
    source: { type: "PAYMENT", id: ids.payment, property_id: ids.property },
    net_refund_usd_cents: 100,
    corrections: history,
  };
  const receipt = {
    receipt: {
      id: ids.receipt,
      payment_id: ids.payment,
      receipt_number: "R-SYNTHETIC",
    },
    payment,
    financial_position: { available_usd_cents: 100 },
    reprints: history,
  };
  const map: Record<FinancialOperation, FinancialJson> = {
    paymentList: [paymentResource],
    paymentGet: paymentResource,
    paymentRecord: {
      payment,
      receipt: {
        id: ids.receipt,
        payment_id: ids.payment,
        receipt_number: "R-SYNTHETIC",
        issued_at: "2026-09-01T12:00:00+00:00",
      },
      received_at: "2026-09-01T05:00:00+00:00",
      evidence_reference: "Synthetic receipt",
      property_timezone: "Asia/Phnom_Penh",
    },
    allocationProposal: {
      property_id: ids.property,
      payment_id: ids.payment,
      available_usd_cents: 100,
      targets: [],
    },
    allocationList: [
      { id: ids.allocation, payment_id: ids.payment, amount_usd_cents: 100 },
    ],
    allocationPost: {
      payment_id: ids.payment,
      allocation_ids: [ids.allocation],
      available_usd_cents: 0,
    },
    allocationReverse: {
      allocation_id: ids.allocation,
      reversal_id: ids.event,
      payment_id: ids.payment,
      available_usd_cents: 100,
    },
    paymentReverse: {
      payment_id: ids.payment,
      reversal_id: ids.event,
      status: "REVERSED",
    },
    paymentReceipt: receipt,
    receiptGet: receipt,
    receiptReprint: {
      receipt_id: ids.receipt,
      receipt_number: "R-SYNTHETIC",
      reprint: { id: ids.event, receipt_id: ids.receipt },
    },
    creditList: [credit],
    creditGet: credit,
    creditLedger: { ...credit, history },
    creditRecognize: credit,
    creditReverse: {
      ...credit,
      recognition_reversal: { id: ids.event, customer_credit_id: ids.credit },
    },
    creditProposal: {
      property_id: ids.property,
      credit_id: ids.credit,
      invoice_id: ids.invoice,
      amount_usd_cents: 100,
      details: [],
    },
    creditApply: application,
    creditApplication: application,
    creditApplicationReverse: {
      ...application,
      reversal: { id: ids.event, credit_application_id: ids.application },
    },
    refundList: [refund],
    refundGet: refund,
    refundCreate: refund,
    refundReturn: {
      ...refund,
      net_refund_usd_cents: 0,
      corrections: {
        page,
        items: [
          {
            id: ids.event,
            refund_id: ids.refund,
            correction_kind: "VALUE_CORRECTION",
            reverses_correction_id: null,
            source_balance_effect_usd_cents: 100,
            source_balance_effect_original_minor: 100,
            previous_net_refund_usd_cents: 100,
            resulting_net_refund_usd_cents: 0,
            verified_return_amount_minor: 100,
            verified_return_currency: "USD",
            verified_returned_at: "2026-09-01T12:00:00+00:00",
            return_method_reference: "Synthetic evidence",
            reason: "Synthetic return",
            evidence_reference: "Synthetic evidence",
          },
        ],
      },
    },
    refundReturnReverse: {
      ...refund,
      corrections: {
        page,
        items: [
          {
            id: ids.other,
            refund_id: ids.refund,
            correction_kind: "CORRECTION_REVERSAL",
            reverses_correction_id: ids.event,
            source_balance_effect_usd_cents: -100,
            source_balance_effect_original_minor: -100,
            previous_net_refund_usd_cents: 0,
            resulting_net_refund_usd_cents: 100,
            verified_return_amount_minor: null,
            verified_return_currency: null,
            verified_returned_at: null,
            return_method_reference: null,
            reason: "Synthetic correction",
            evidence_reference: "Synthetic evidence",
          },
        ],
      },
    },
    refundSource: {
      property_id: ids.property,
      source_type: "PAYMENT",
      source_id: ids.payment,
      refund_currency: "USD",
      available_usd_cents: 100,
      eligible: true,
    },
  };
  const data = map[operation];
  return {
    data,
    ...(Array.isArray(data) ? { page } : {}),
    meta: { property_id: ids.property, request_id: ids.key },
  };
}

export function command(index: number): FinancialRequest {
  const value = commands[index];
  if (!value) throw new Error("Missing command fixture");
  return value;
}
export function read(index: number): FinancialRequest {
  const value = reads[index];
  if (!value) throw new Error("Missing read fixture");
  return value;
}
