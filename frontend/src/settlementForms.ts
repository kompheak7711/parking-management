// Written from the API's request models by
// backend/tests/test_settlement_forms_ts.py (V1-056 slice 11). Do not edit by hand:
// change the model, then write this file again.
// Amounts are integer US cents; ids are UUID text; instants are RFC3339 text with an offset;
// a due_date is a plain YYYY-MM-DD date. Rules between fields (a reason that comes with its
// choice, a finding a Damage charge needs) are checked by the server and answer 422 on the field.

export interface AddRefundMethodInput {
  refund_method_id: string;
  code: string;
  display_name: string;
}

export interface AdjustmentReversalCorrectionInput {
  adjustment_id: string;
  reason: string;
}

export interface AdjustmentReversalInput {
  reason: string;
}

export interface ChargeReductionInput {
  invoice_id: string;
  invoice_line_id: string;
  amount_usd_cents: number;
  reason: string;
}

export interface CleaningChargeInput {
  charge_id: string;
  expected_rate_id: string;
}

export interface CleaningRateInput {
  rate_id: string;
  expected_current_rate_id: string | null;
  rate_usd_cents: number;
  reason: string;
}

export interface CorrectionReceiptInput {
  deposit_id: string;
  amount_usd_cents: number;
  outcome?: "DL_032" | "FORFEIT" | null;
  outcome_reason?: string | null;
}

export interface CreditStepInput {
  kind: "CUSTOMER_CREDIT";
  customer_credit_id: string;
  target_kind: "INVOICE_LINE" | "LATE_PAYMENT_CHARGE";
  target_id: string;
  amount_usd_cents: number;
  customer_designation?: string | null;
}

export interface DepositReceiptCorrectionInput {
  steps?: (CreditStepInput | DepositStepInput | DepositRefundStepInput)[];
  pet_remainder?: PetRemainderInput | null;
  deposit_receipt_id: string;
  reason: string;
  evidence_reference: string;
  receipts?: CorrectionReceiptInput[];
}

export interface DepositReceiptCreate {
  receipt_id: string;
  payment_id: string;
  amount_usd_cents: number;
  reason: string;
}

export interface DepositRefundStepInput {
  kind: "DEPOSIT_REFUNDS";
  deposit_id: string;
  amount_usd_cents: number;
  refund_method_id: string;
  reference_note: string;
  recipient_customer_id: string;
  signer_agreement?: string | null;
}

export interface DepositStepInput {
  kind: "PET_DEPOSIT_PET_DAMAGE" | "SECURITY_DEPOSIT" | "PET_DEPOSIT_REMAINDER";
  deposit_id: string;
  target_kind: "INVOICE_LINE" | "LATE_PAYMENT_CHARGE";
  target_id: string;
  amount_usd_cents: number;
}

export interface ExtraChargeInput {
  category: "MISCELLANEOUS_CHARGES" | "DAMAGE_CHARGES";
  description: string;
  amount_usd_cents: number;
  evidence_reference: string;
  reason: string;
  inspection_damage_finding_id?: string | null;
  corrects_invoice_id?: string | null;
  due_date?: string | null;
  due_date_reason?: string | null;
}

export interface FinalSettlementDraftInput {
  steps: (CreditStepInput | DepositStepInput | DepositRefundStepInput)[];
  reason: string;
  pet_remainder?: PetRemainderInput | null;
}

export interface ForfeitureDraftInput {
  reason: string;
  disposition_id: string;
}

export interface ForfeitureReversalCorrectionInput {
  steps?: (CreditStepInput | DepositStepInput | DepositRefundStepInput)[];
  pet_remainder?: PetRemainderInput | null;
  deposit_disposition_id: string;
  reason: string;
  evidence_reference: string;
  refund_method_id: string;
  reference_note: string;
}

export interface ForfeitureReversalDraftInput {
  reason: string;
  reversal_id: string;
  evidence_reference: string;
}

export interface HandBackResolutionInput {
  action: "VOID" | "CREDIT_ADJUSTMENT";
  expected_outstanding_usd_cents: number;
  reason: string;
}

export interface HeldValueRefundCorrectionInput {
  steps?: (CreditStepInput | DepositStepInput | DepositRefundStepInput)[];
  pet_remainder?: PetRemainderInput | null;
  held_from_correction_id: string;
  reason: string;
  new_refund_method_id: string;
  new_refund_reference_note: string;
}

export interface LateChargeReductionInput {
  late_payment_charge_id: string;
  amount_usd_cents: number;
  reason: string;
}

export interface LateChargeRefundCorrectionInput {
  steps?: (CreditStepInput | DepositStepInput | DepositRefundStepInput)[];
  pet_remainder?: PetRemainderInput | null;
  late_payment_charge_id: string;
  amount_usd_cents: number;
  refund_method_id: string;
  reference_note: string;
  reason: string;
}

export interface MoveCorrectionInput {
  allocation_id: string;
  target_invoice_id: string;
  reason: string;
  source_acknowledgement: string;
  target_acknowledgement: string;
}

export interface PaymentMoveDraftInput {
  reason: string;
  target_invoice_id: string;
  source_acknowledgement: string;
  target_acknowledgement: string;
}

export interface PaymentReturnDraftInput {
  reason: string;
  evidence_reference: string;
}

export interface PetClassificationCorrectionInput {
  steps?: (CreditStepInput | DepositStepInput | DepositRefundStepInput)[];
  pet_remainder?: PetRemainderInput | null;
  invoice_id: string;
  invoice_line_id: string;
  pet_related: boolean;
  evidence_reference: string;
  reason: string;
}

export interface PetRemainderInput {
  basis: "CUSTOMER_CHOICE" | "STAFF_REASON";
  staff_reason: string;
  customer_choice?: string | null;
}

export interface ReceiptReversalDraftInput {
  reason: string;
  reversal_id: string;
}

export interface RefundCorrectionInput {
  steps?: (CreditStepInput | DepositStepInput | DepositRefundStepInput)[];
  pet_remainder?: PetRemainderInput | null;
  invoice_id: string;
  invoice_line_id: string;
  amount_usd_cents: number;
  refund_method_id: string;
  reference_note: string;
  reason: string;
}

export interface RefundMethodStateInput {
  active: boolean;
}

export interface RefundReturnCorrectionInput {
  steps?: (CreditStepInput | DepositStepInput | DepositRefundStepInput)[];
  pet_remainder?: PetRemainderInput | null;
  refund_id: string;
  returned_amount_usd_cents: number;
  returned_at: string;
  return_method_reference: string;
  evidence_reference: string;
  reason: string;
  new_refund_method_id?: string | null;
  new_refund_reference_note?: string | null;
}

export interface ReturnReversalCorrectionInput {
  earlier_correction_id: string;
  reason: string;
  evidence_reference: string;
}

export interface ReturnedPaymentInput {
  payment_id: string;
  reason: string;
  evidence_reference: string;
}

export interface ReversalInput {
  reason: string;
}

export interface SecurityDepositCreate {
  deposit_id: string;
  required_usd_cents: number;
  reason: string;
}
