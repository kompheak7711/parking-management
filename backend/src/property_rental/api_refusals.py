"""Refusals with a stable code and a plain message (V1-056 slice 11).

A route raises ``RefusedRequest`` when the staff screen needs to know why a command was refused,
for example that a draft was already decided. The handler in ``app.py`` answers with the error
envelope of API-013: the fixed code and message, never database text.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import psycopg


@dataclass(frozen=True, slots=True)
class Refusal:
    status_code: int
    code: str
    message: str
    rule_ids: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()


class RefusedRequest(Exception):
    def __init__(self, refusal: Refusal) -> None:
        super().__init__(refusal.code)
        self.refusal = refusal


def database_refusal(exc: BaseException, table: Mapping[str, Refusal]) -> Refusal | None:
    """The coded refusal for a service error whose cause is a named database refusal.

    Services raise their own error ``from`` the psycopg error; the route reads that cause's
    primary message, so the service classes and their tests stay as they are.
    """
    cause = exc if isinstance(exc, psycopg.Error) else exc.__cause__
    if not isinstance(cause, psycopg.Error):
        return None
    return table.get(cause.diag.message_primary or "")


DRAFT_ALREADY_DECIDED = Refusal(
    409,
    "DRAFT_ALREADY_DECIDED",
    "This draft was already confirmed, rejected or withdrawn.",
    ("BR-AUTH-010",),
)
DRAFT_WITHDRAW_PREPARER_ONLY = Refusal(
    403,
    "DRAFT_WITHDRAW_PREPARER_ONLY",
    "Only the person who prepared this draft may withdraw it.",
    ("BR-AUTH-010",),
)
DRAFT_DECISION_NOT_ALLOWED = Refusal(
    409,
    "DRAFT_DECISION_NOT_ALLOWED",
    "This draft cannot be decided this way.",
    ("BR-AUTH-010",),
)
DRAFT_OUT_OF_DATE = Refusal(
    409,
    "DRAFT_OUT_OF_DATE",
    "This draft is out of date because the records changed after it was prepared. Reject it "
    "and record it again.",
    ("BR-AUTH-010",),
)
DRAFT_CONFIRM_REFUSED = Refusal(
    409,
    "DRAFT_CONFIRM_REFUSED",
    "This draft cannot be confirmed with the records as they are now.",
    ("BR-AUTH-010",),
)
DRAFT_CONFIRM_NOT_AVAILABLE = Refusal(
    409,
    "DRAFT_CONFIRM_NOT_AVAILABLE",
    "This draft cannot be confirmed here.",
    ("BR-AUTH-010",),
)
LEASE_END_DATE_NOT_MONTH_END = Refusal(
    422,
    "LEASE_END_DATE_NOT_MONTH_END",
    "The Lease End Date must be the last day of a month.",
    ("BR-LEASE-031",),
    ("end_date",),
)

# V1-056 slice 11a: the move-out cleaning charge and the hand-back month (business state).
CLEANING_CHARGE_NOT_MOVED_IN = Refusal(
    409,
    "CLEANING_CHARGE_NOT_MOVED_IN",
    "There is no cleaning charge, because the Customer never moved in.",
    ("BR-MOVEOUT-013",),
)
CLEANING_CHARGE_NEEDS_MOVE_OUT = Refusal(
    409,
    "CLEANING_CHARGE_NEEDS_MOVE_OUT",
    "Record the move-out before the cleaning charge.",
    ("BR-MOVEOUT-013",),
)
CLEANING_CHARGE_ALREADY_RECORDED = Refusal(
    409,
    "CLEANING_CHARGE_ALREADY_RECORDED",
    "The cleaning charge is already recorded for this Lease.",
    ("BR-MOVEOUT-013",),
)
CLEANING_RATE_NOT_SET = Refusal(
    409,
    "CLEANING_RATE_NOT_SET",
    "This Unit has no cleaning rate. Set the rate first.",
    ("BR-UNIT-014",),
)
CLEANING_RATE_ZERO = Refusal(
    409,
    "CLEANING_RATE_ZERO",
    "This Unit's cleaning rate is zero, so there is no cleaning charge.",
    ("BR-UNIT-014",),
)
CLEANING_RATE_CHANGED = Refusal(
    409,
    "CLEANING_RATE_CHANGED",
    "The cleaning rate changed. Reload it and try again.",
    ("BR-UNIT-014",),
)
HAND_BACK_NOT_MONTHLY_RENT = Refusal(
    409,
    "HAND_BACK_NOT_MONTHLY_RENT",
    "The hand-back rule covers only monthly Rent Invoices.",
    ("BR-RENT-030",),
)
HAND_BACK_INVOICE_NOT_ISSUED = Refusal(
    409,
    "HAND_BACK_INVOICE_NOT_ISSUED",
    "The hand-back action is only for an issued Invoice that is not VOID.",
    ("BR-RENT-030",),
)
HAND_BACK_NOT_EARLY_TERMINATION = Refusal(
    409,
    "HAND_BACK_NOT_EARLY_TERMINATION",
    "The hand-back rule covers only a Lease the Customer chose to end early.",
    ("BR-RENT-030",),
)
HAND_BACK_NEEDS_MOVE_OUT = Refusal(
    409,
    "HAND_BACK_NEEDS_MOVE_OUT",
    "Record the move-out before the hand-back action.",
    ("BR-RENT-030",),
)
HAND_BACK_MOVE_OUT_UNCLEAR = Refusal(
    409,
    "HAND_BACK_MOVE_OUT_UNCLEAR",
    "The move-out records of this Lease are unclear. Ask the Owner to check them.",
    ("BR-RENT-030",),
)
HAND_BACK_MONTH_NOT_COVERED = Refusal(
    409,
    "HAND_BACK_MONTH_NOT_COVERED",
    "The hand-back date does not cover this Invoice's month.",
    ("BR-RENT-030",),
)
HAND_BACK_ALREADY_RESOLVED = Refusal(
    409,
    "HAND_BACK_ALREADY_RESOLVED",
    "This Invoice already has a hand-back action.",
    ("BR-RENT-030",),
)
HAND_BACK_PAID_INVOICE_KEPT = Refusal(
    409, "HAND_BACK_PAID_INVOICE_KEPT", "A fully paid Invoice is kept as it is.", ("BR-RENT-030",)
)
HAND_BACK_ASSESSMENT_CHANGED = Refusal(
    409,
    "HAND_BACK_ASSESSMENT_CHANGED",
    "The amounts changed since you looked. Reload and try again.",
    ("BR-RENT-030",),
)
HAND_BACK_VOID_BLOCKED = Refusal(
    409,
    "HAND_BACK_VOID_BLOCKED",
    "This Invoice has an Adjustment, a Late-payment Charge or a billing run that must be "
    "settled or reversed before it can be VOID.",
    ("BR-RENT-030",),
)
FINAL_SETTLEMENT_CLOSED = Refusal(
    409,
    "FINAL_SETTLEMENT_CLOSED",
    "The Final Settlement of this Lease is closed. Use a post-settlement correction instead.",
    ("BR-SETTLE-012",),
)
IDEMPOTENCY_KEY_REUSED = Refusal(
    409,
    "IDEMPOTENCY_KEY_REUSED",
    "The idempotency key was already used for different input.",
    ("API-016",),
)

# V1-056 slice 11c: Refund drafts, their confirm and the verified-return routes.
REFUND_METHOD_OFF = Refusal(
    409,
    "REFUND_METHOD_OFF",
    "This Refund method is turned off. Choose another.",
    ("BR-REFUND-014",),
)
# V1-056 slice 11h: adding and turning off Refund methods in Settings (owner answer of
# 2026-10-25).
REFUND_METHOD_CODE_USED = Refusal(
    409,
    "REFUND_METHOD_CODE_USED",
    "Another Refund method already has this code.",
    ("BR-REFUND-014",),
    ("code",),
)
REFUND_METHOD_ID_REUSED = Refusal(
    409,
    "REFUND_METHOD_ID_REUSED",
    "This Refund method id was already used with other details.",
    ("BR-REFUND-014",),
    ("refund_method_id",),
)
REFUND_METHOD_LAST_ON = Refusal(
    409,
    "REFUND_METHOD_LAST_ON",
    "At least one Refund method stays on. Turn another one on first.",
    ("BR-REFUND-014",),
)
REFUND_AMOUNT_NOT_AVAILABLE = Refusal(
    409,
    "REFUND_AMOUNT_NOT_AVAILABLE",
    "The money this Refund would pay back is no longer available.",
    ("BR-REFUND-003",),
)
REFUND_PAYER_HAS_UNPAID = Refusal(
    409,
    "REFUND_PAYER_HAS_UNPAID",
    "The payer now has unpaid Invoices, which this money must pay first.",
    ("BR-REFUND-003",),
)
REFUND_PET_SOURCE_NOT_QUALIFIED = Refusal(
    409,
    "REFUND_PET_SOURCE_NOT_QUALIFIED",
    "The Pet Deposit no longer qualifies for this Refund.",
    ("BR-REFUND-013",),
)
REFUND_RECIPIENT_NOT_SIGNER = Refusal(
    409,
    "REFUND_RECIPIENT_NOT_SIGNER",
    "The person named to receive this Refund is not a Signer of the Lease.",
    ("BR-REFUND-015",),
)
REFUND_RETURN_THROUGH_CORRECTION = Refusal(
    409,
    "REFUND_RETURN_THROUGH_CORRECTION",
    "This Refund is corrected through its Final Settlement or Reservation correction.",
    ("BR-SETTLE-013",),
)
REFUND_CREDIT_CUSTOMER_ONLY = Refusal(
    409,
    "REFUND_CREDIT_CUSTOMER_ONLY",
    "Only a Credit that a credit Adjustment gave to a Customer other than the payer is refunded "
    "to that Customer this way.",
    ("BR-CREDIT-014",),
)
REFUND_THROUGH_HELD_VALUE_CORRECTION = Refusal(
    409,
    "REFUND_THROUGH_HELD_VALUE_CORRECTION",
    "This Credit holds money a Final Settlement correction brought back. Refund it through a "
    "held-value correction of that Final Settlement.",
    ("BR-SETTLE-013",),
)
REFUND_RETURN_REVERSAL_REFUSED = Refusal(
    409,
    "REFUND_RETURN_REVERSAL_REFUSED",
    "The money of this return is no longer available to reverse.",
    ("BR-REFUND-010",),
)
REFUND_RETURN_ALREADY_REVERSED = Refusal(
    409,
    "REFUND_RETURN_ALREADY_REVERSED",
    "This return was already reversed.",
    ("BR-REFUND-010",),
)
REFUND_RETURN_EVIDENCE_NOT_EXACT = Refusal(
    422,
    "REFUND_RETURN_EVIDENCE_NOT_EXACT",
    "The returned amount must not be more than this Refund still holds, and the return date must "
    "be on or after the Refund's date and not in the future.",
    ("BR-REFUND-010",),
    ("returned_amount_minor", "returned_at"),
)
# On a draft's record the method and the recipient come from the form, so a wrong one is bad
# input (slice 11c-2 review round 1); at confirm the same database refusals are business state.
REFUND_METHOD_NOT_AVAILABLE = Refusal(
    422,
    "REFUND_METHOD_NOT_AVAILABLE",
    "This Refund method is not available. Choose another.",
    ("BR-REFUND-014",),
    ("refund_method_id",),
)
REFUND_RECIPIENT_NOT_A_SIGNER = Refusal(
    422,
    "REFUND_RECIPIENT_NOT_A_SIGNER",
    "The person named to receive this Refund is not a Signer of the Lease.",
    ("BR-REFUND-015",),
    ("recipient_customer_id",),
)
REFUND_CREDIT_FOR_ANOTHER_CUSTOMER = Refusal(
    409,
    "REFUND_CREDIT_FOR_ANOTHER_CUSTOMER",
    "This Credit belongs to another Customer. Prepare a CREDIT_CUSTOMER Refund draft for it.",
    ("BR-CREDIT-014",),
)
REFUND_DEPOSIT_RECEIPT_REVERSAL_WAITING = Refusal(
    409,
    "REFUND_DEPOSIT_RECEIPT_REVERSAL_WAITING",
    "The reversal draft of this Deposit's receipt waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)

# V1-056 slice 11c-3: Deposit forfeiture, Deposit correction and returned-Payment draft routes.
DRAFT_RECORD_ID_IN_USE = Refusal(
    409,
    "DRAFT_RECORD_ID_IN_USE",
    "The record id this form chose is already used. Open the form again.",
    ("API-016",),
)
DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED = Refusal(
    409,
    "DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED",
    "The Lease of this Deposit is not terminated, so the Deposit cannot be forfeited.",
    ("BR-DEP-026",),
)
DEPOSIT_FORFEITURE_NO_GROUND = Refusal(
    409,
    "DEPOSIT_FORFEITURE_NO_GROUND",
    "The termination of this Lease gives no ground to forfeit this Deposit.",
    ("BR-DEP-026",),
)
DEPOSIT_FORFEITURE_PET_AT_SETTLEMENT = Refusal(
    409,
    "DEPOSIT_FORFEITURE_PET_AT_SETTLEMENT",
    "This Pet Deposit is decided in the Final Settlement, not forfeited here.",
    ("BR-DEP-024", "BR-DEP-027"),
)
DEPOSIT_FORFEITURE_NOTHING_HELD = Refusal(
    409,
    "DEPOSIT_FORFEITURE_NOTHING_HELD",
    "This Deposit holds no money to forfeit.",
    ("BR-DEP-026",),
)
DEPOSIT_FORFEITURE_DRAFT_WAITING = Refusal(
    409,
    "DEPOSIT_FORFEITURE_DRAFT_WAITING",
    "A forfeiture draft of this Deposit waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)
DEPOSIT_FORFEITURE_ALREADY_REVERSED = Refusal(
    409,
    "DEPOSIT_FORFEITURE_ALREADY_REVERSED",
    "This forfeiture was reversed before.",
    ("BR-DEP-026",),
)
DEPOSIT_FORFEITURE_REVERSAL_DRAFT_WAITING = Refusal(
    409,
    "DEPOSIT_FORFEITURE_REVERSAL_DRAFT_WAITING",
    "A reversal draft of this forfeiture waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)
DEPOSIT_RECEIPT_ALREADY_REVERSED = Refusal(
    409,
    "DEPOSIT_RECEIPT_ALREADY_REVERSED",
    "This Deposit receipt was reversed before.",
    ("BR-AUTH-010",),
)
DEPOSIT_DRAFT_WAITING = Refusal(
    409,
    "DEPOSIT_DRAFT_WAITING",
    "Another draft of this Deposit waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)
PAYMENT_RETURN_NOT_RECEIVED = Refusal(
    409,
    "PAYMENT_RETURN_NOT_RECEIVED",
    "This Payment is not in the received state, so it cannot be returned.",
    ("BR-SETTLE-013",),
)
PAYMENT_RETURN_THROUGH_CORRECTION = Refusal(
    409,
    "PAYMENT_RETURN_THROUGH_CORRECTION",
    "A closed Final Settlement used this Payment. Return it through a correction of that "
    "Final Settlement.",
    ("BR-SETTLE-013",),
)
PAYMENT_RETURN_REFUND_NOT_RETURNED = Refusal(
    409,
    "PAYMENT_RETURN_REFUND_NOT_RETURNED",
    "Money from this Payment was refunded and has not all come back. Record the Refund's "
    "return first.",
    ("BR-SETTLE-013",),
)
PAYMENT_RETURN_REFUND_NO_RECOVERY = Refusal(
    409,
    "PAYMENT_RETURN_REFUND_NO_RECOVERY",
    "Money from this Payment was refunded and the app cannot plan how to charge it back. "
    "Record the Refund's return first.",
    ("BR-SETTLE-013",),
)
PAYMENT_RETURN_SETTLEMENT_NOT_CORRECTABLE = Refusal(
    409,
    "PAYMENT_RETURN_SETTLEMENT_NOT_CORRECTABLE",
    "A Refund from this Payment would be charged on a Lease whose closed Final Settlement this "
    "return cannot correct.",
    ("BR-SETTLE-013",),
)
PAYMENT_RETURN_FORFEITURE_ACTIVE = Refusal(
    409,
    "PAYMENT_RETURN_FORFEITURE_ACTIVE",
    "A Deposit this Payment paid is forfeited. Reverse the forfeiture first.",
    ("BR-SETTLE-013",),
)
PAYMENT_RETURN_DEPOSIT_USED = Refusal(
    409,
    "PAYMENT_RETURN_DEPOSIT_USED",
    "A Deposit this Payment paid was used to pay debts. Reverse that use first.",
    ("BR-SETTLE-013",),
)
PAYMENT_RETURN_DRAFT_WAITING = Refusal(
    409,
    "PAYMENT_RETURN_DRAFT_WAITING",
    "A draft about this Payment or its records waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)
PAYMENT_RETURN_TOO_LARGE = Refusal(
    409,
    "PAYMENT_RETURN_TOO_LARGE",
    "This Payment has too many records to return in one draft.",
    ("BR-SETTLE-013",),
)

# V1-056 slice 11c-4: the walk-in Lease's Security Deposit and a receipt into an existing Deposit.
DEPOSIT_SECURITY_LEASE_NOT_SIGNED = Refusal(
    409,
    "DEPOSIT_SECURITY_LEASE_NOT_SIGNED",
    "The Security Deposit is created here only for a signed Lease.",
    ("BR-DEP-004",),
)
DEPOSIT_SECURITY_NOT_WALK_IN = Refusal(
    409,
    "DEPOSIT_SECURITY_NOT_WALK_IN",
    "This Lease was not signed as a walk-in Lease, so its Security Deposit is not created on "
    "this form.",
    ("BR-DEP-005",),
)
DEPOSIT_SECURITY_RENEWAL = Refusal(
    409,
    "DEPOSIT_SECURITY_RENEWAL",
    "This Lease renews an earlier Lease, so its Security Deposit is not created on this form.",
    ("BR-DEP-005",),
)
DEPOSIT_SECURITY_ALREADY_EXISTS = Refusal(
    409,
    "DEPOSIT_SECURITY_ALREADY_EXISTS",
    "This Lease already has a Security Deposit.",
    ("BR-DEP-004",),
)
DEPOSIT_RECEIPT_LEASE_NOT_SIGNED = Refusal(
    409,
    "DEPOSIT_RECEIPT_LEASE_NOT_SIGNED",
    "The Lease of this Deposit is not signed, so no receipt is recorded here.",
    ("BR-DEP-011",),
)
DEPOSIT_RECEIPT_RESERVATION_NOT_ACTIVE = Refusal(
    409,
    "DEPOSIT_RECEIPT_RESERVATION_NOT_ACTIVE",
    "The Reservation of this Deposit is not active or has expired, so no receipt is recorded here.",
    ("BR-DEP-002",),
)
DEPOSIT_RECEIPT_GROUND_KEEPS_DEPOSIT = Refusal(
    409,
    "DEPOSIT_RECEIPT_GROUND_KEEPS_DEPOSIT",
    "The termination of this Lease keeps this Deposit. Record this money as a normal Payment.",
    ("BR-DEP-022", "BR-DEP-023"),
)
DEPOSIT_RECEIPT_FORFEITURE_ACTIVE = Refusal(
    409,
    "DEPOSIT_RECEIPT_FORFEITURE_ACTIVE",
    "This Deposit is forfeited. Reverse the forfeiture first.",
    ("BR-DEP-026",),
)
DEPOSIT_RECEIPT_PAYMENT_OWED = Refusal(
    409,
    "DEPOSIT_RECEIPT_PAYMENT_OWED",
    "This Payment still pays an Invoice or a Late-payment Charge that is owed. Only what is left "
    "after that may go into a Deposit.",
    ("BR-DEP-013",),
)
DEPOSIT_RECEIPT_PAYMENT_INELIGIBLE = Refusal(
    422,
    "DEPOSIT_RECEIPT_PAYMENT_INELIGIBLE",
    "This Payment cannot pay this Deposit. It must be a received Payment of this Property from "
    "the Deposit's Customer or for its Lease.",
    ("BR-DEP-013",),
    ("payment_id",),
)
DEPOSIT_RECEIPT_PAYMENT_ALREADY_USED = Refusal(
    409,
    "DEPOSIT_RECEIPT_PAYMENT_ALREADY_USED",
    "This Deposit already holds a receipt from this Payment.",
    ("BR-DEP-004",),
)
DEPOSIT_RECEIPT_PAYMENT_NOT_FOUND = Refusal(
    422,
    "DEPOSIT_RECEIPT_PAYMENT_NOT_FOUND",
    "No Payment with this id is in this Property.",
    ("BR-DEP-013",),
    ("payment_id",),
)
DEPOSIT_RECEIPT_OVER_REQUIRED = Refusal(
    422,
    "DEPOSIT_RECEIPT_OVER_REQUIRED",
    "This amount is more than the Pet Deposit still needs.",
    ("BR-DEP-009",),
    ("amount_usd_cents",),
)
DEPOSIT_RECEIPT_AMOUNT_NOT_ALLOWED = Refusal(
    422,
    "DEPOSIT_RECEIPT_AMOUNT_NOT_ALLOWED",
    "This amount does not fit this Deposit. It may not be more than the Deposit still needs, and "
    "a Reservation's Deposit with no active receipt takes exactly its accepted amount.",
    ("BR-DEP-002", "BR-DEP-004"),
    ("amount_usd_cents",),
)
DEPOSIT_RECEIPT_OVER_PAYMENT = Refusal(
    422,
    "DEPOSIT_RECEIPT_OVER_PAYMENT",
    "This amount is more than this Payment still has available.",
    ("BR-DEP-013",),
    ("amount_usd_cents",),
)

# V1-056 slice 11d: the wrong-Unit Payment move draft (BR-PAY-042).
PAYMENT_MOVE_NOT_INVOICE_ALLOCATION = Refusal(
    409,
    "PAYMENT_MOVE_NOT_INVOICE_ALLOCATION",
    "Only an allocation to an Invoice can be moved.",
    ("BR-PAY-042",),
)
PAYMENT_MOVE_TARGET_SAME_UNIT = Refusal(
    422,
    "PAYMENT_MOVE_TARGET_SAME_UNIT",
    "Choose an Invoice of a Lease on another Unit as the correct Invoice.",
    ("BR-PAY-042",),
    ("target_invoice_id",),
)
PAYMENT_MOVE_TARGET_NOT_FOUND = Refusal(
    422,
    "PAYMENT_MOVE_TARGET_NOT_FOUND",
    "No Invoice with this id is in this Property.",
    ("BR-PAY-042",),
    ("target_invoice_id",),
)
PAYMENT_MOVE_TARGET_NOTHING_OWED = Refusal(
    422,
    "PAYMENT_MOVE_TARGET_NOTHING_OWED",
    "The correct Invoice has nothing left to pay.",
    ("BR-PAY-042",),
    ("target_invoice_id",),
)
PAYMENT_MOVE_TARGET_TOO_LARGE = Refusal(
    409,
    "PAYMENT_MOVE_TARGET_TOO_LARGE",
    "The correct Invoice has too many lines to move this Payment in one draft.",
    ("BR-PAY-042",),
)
PAYMENT_MOVE_PAYMENT_REVERSED = Refusal(
    409,
    "PAYMENT_MOVE_PAYMENT_REVERSED",
    "This Payment is reversed, so it cannot be moved.",
    ("BR-PAY-042",),
)
PAYMENT_MOVE_ALREADY_MOVED = Refusal(
    409,
    "PAYMENT_MOVE_ALREADY_MOVED",
    "This allocation has been moved already.",
    ("BR-PAY-042",),
)
PAYMENT_MOVE_RELEASED_BY_ADJUSTMENT = Refusal(
    409,
    "PAYMENT_MOVE_RELEASED_BY_ADJUSTMENT",
    "This allocation was released by a credit Adjustment, so it cannot be moved.",
    ("BR-PAY-042",),
)
PAYMENT_MOVE_CREDIT_OR_REFUND_FIRST = Refusal(
    409,
    "PAYMENT_MOVE_CREDIT_OR_REFUND_FIRST",
    "Part of this Payment became Customer Credit or a Refund. Reverse that first.",
    ("BR-PAY-042",),
)
PAYMENT_MOVE_VALUE_GONE = Refusal(
    409,
    "PAYMENT_MOVE_VALUE_GONE",
    "This Payment no longer holds the money to move.",
    ("BR-PAY-042",),
)
PAYMENT_MOVE_DRAFT_WAITING = Refusal(
    409,
    "PAYMENT_MOVE_DRAFT_WAITING",
    "A move draft for this allocation waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)
PAYMENT_MOVE_THROUGH_CORRECTION = Refusal(
    409,
    "PAYMENT_MOVE_THROUGH_CORRECTION",
    "A closed Final Settlement relied on this allocation. Move it through a correction of that "
    "Final Settlement.",
    ("BR-SETTLE-012",),
)
PAYMENT_MOVE_TOO_LARGE = Refusal(
    422,
    "PAYMENT_MOVE_TOO_LARGE",
    "This move is too large for one draft (the acknowledgements and the correct Invoice's "
    "lines). Shorten the acknowledgements.",
    ("BR-PAY-042",),
    ("source_acknowledgement", "target_acknowledgement"),
)
ALLOCATION_MOVED = Refusal(
    409,
    "ALLOCATION_MOVED",
    "This allocation was moved to another Unit's Invoice. Correct it with another move draft or "
    "a credit Adjustment.",
    ("BR-PAY-042",),
)
# V1-056 slice 11e-1: the Final Settlement start, preview and draft routes. A refusal of the
# chosen steps answers 422 on the form field; the state of the Lease or Settlement answers 409.
FINAL_SETTLEMENT_LEASE_NOT_TERMINATED = Refusal(
    409,
    "FINAL_SETTLEMENT_LEASE_NOT_TERMINATED",
    "A Final Settlement is only for a terminated Lease. Record the termination first.",
    ("BR-SETTLE-001",),
)
FINAL_SETTLEMENT_RECORD_UNCLEAR = Refusal(
    409,
    "FINAL_SETTLEMENT_RECORD_UNCLEAR",
    "The Lease's termination or move-out record is not clear. Correct it first.",
    ("BR-SETTLE-002",),
)
FINAL_SETTLEMENT_DRAFT_WAITING = Refusal(
    409,
    "FINAL_SETTLEMENT_DRAFT_WAITING",
    "A Final Settlement draft waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)
FINAL_SETTLEMENT_BLOCKING_ISSUES = Refusal(
    409,
    "FINAL_SETTLEMENT_BLOCKING_ISSUES",
    "The Final Settlement still has blocking issues. Open the preview to see them.",
    ("BR-SETTLE-011",),
)
FINAL_SETTLEMENT_STEP_ORDER = Refusal(
    422,
    "FINAL_SETTLEMENT_STEP_ORDER",
    "Put the steps in the DL-032 order: Credit, pet damage, Security Deposit, remaining Pet "
    "Deposit, then Refunds.",
    ("BR-SETTLE-004",),
    ("steps",),
)
FINAL_SETTLEMENT_CREDIT_OTHER_CUSTOMER = Refusal(
    422,
    "FINAL_SETTLEMENT_CREDIT_OTHER_CUSTOMER",
    "A Customer's Credit can pay only that same Customer's debt.",
    (
        "BR-SETTLE-004",
        "BR-CREDIT-008",
    ),
    ("steps",),
)
FINAL_SETTLEMENT_CREDIT_FIRST = Refusal(
    422,
    "FINAL_SETTLEMENT_CREDIT_FIRST",
    "Use each Customer's Credit on that Customer's open debt, as far as it goes, before any "
    "Deposit.",
    ("BR-SETTLE-004",),
    ("steps",),
)
FINAL_SETTLEMENT_CREDIT_RENT_FIRST = Refusal(
    422,
    "FINAL_SETTLEMENT_CREDIT_RENT_FIRST",
    "Credit pays the Rent line first on this Invoice, unless the Customer chose the line. "
    "Record who chose it.",
    (
        "BR-SETTLE-004",
        "BR-CREDIT-006",
    ),
    ("steps",),
)
FINAL_SETTLEMENT_CREDIT_NOT_AVAILABLE = Refusal(
    422,
    "FINAL_SETTLEMENT_CREDIT_NOT_AVAILABLE",
    "This Customer Credit cannot be used in this Final Settlement.",
    ("BR-SETTLE-004",),
    ("steps",),
)
FINAL_SETTLEMENT_CREDIT_OVER = Refusal(
    422,
    "FINAL_SETTLEMENT_CREDIT_OVER",
    "This amount is more than the Customer Credit has left.",
    ("BR-SETTLE-004",),
    ("steps",),
)
FINAL_SETTLEMENT_DEPOSIT_NOT_USABLE = Refusal(
    422,
    "FINAL_SETTLEMENT_DEPOSIT_NOT_USABLE",
    "This Deposit holds no money that this Final Settlement may use.",
    ("BR-SETTLE-006",),
    ("steps",),
)
FINAL_SETTLEMENT_DEPOSIT_WRONG_STEP = Refusal(
    422,
    "FINAL_SETTLEMENT_DEPOSIT_WRONG_STEP",
    "This Deposit type does not belong in this step.",
    ("BR-SETTLE-006",),
    ("steps",),
)
FINAL_SETTLEMENT_DEPOSIT_OVER = Refusal(
    422,
    "FINAL_SETTLEMENT_DEPOSIT_OVER",
    "This amount is more than the Deposit has left.",
    ("BR-SETTLE-006",),
    ("steps",),
)
FINAL_SETTLEMENT_OBLIGATION_OVER = Refusal(
    422,
    "FINAL_SETTLEMENT_OBLIGATION_OVER",
    "This amount is more than the Invoice line or charge still owes.",
    ("BR-SETTLE-003",),
    ("steps",),
)
FINAL_SETTLEMENT_TARGET_NOT_OPEN = Refusal(
    422,
    "FINAL_SETTLEMENT_TARGET_NOT_OPEN",
    "This Invoice line or charge is not open debt of this Final Settlement.",
    ("BR-SETTLE-003",),
    ("steps",),
)
FINAL_SETTLEMENT_PET_DAMAGE_ONLY = Refusal(
    422,
    "FINAL_SETTLEMENT_PET_DAMAGE_ONLY",
    "In the pet damage step the Pet Deposit pays only pet damage.",
    ("BR-SETTLE-005",),
    ("steps",),
)
FINAL_SETTLEMENT_PET_DAMAGE_FIRST = Refusal(
    422,
    "FINAL_SETTLEMENT_PET_DAMAGE_FIRST",
    "The Pet Deposit must pay the open pet damage before any other use or Refund.",
    ("BR-SETTLE-005",),
    ("steps",),
)
FINAL_SETTLEMENT_PET_REMAINDER_AFTER_SECURITY = Refusal(
    422,
    "FINAL_SETTLEMENT_PET_REMAINDER_AFTER_SECURITY",
    "The rest of the Pet Deposit may pay only debt left after the Security Deposit is used up.",
    ("BR-SETTLE-017",),
    ("steps",),
)
FINAL_SETTLEMENT_PET_REMAINDER_CUSTOMER_ONLY = Refusal(
    422,
    "FINAL_SETTLEMENT_PET_REMAINDER_CUSTOMER_ONLY",
    "For this kind of termination, only the Customer may choose to use the rest of the Pet "
    "Deposit. Record the Customer's choice.",
    (
        "BR-SETTLE-017",
        "BR-DEP-027",
    ),
    ("pet_remainder",),
)
FINAL_SETTLEMENT_PET_REMAINDER_REASON = Refusal(
    422,
    "FINAL_SETTLEMENT_PET_REMAINDER_REASON",
    "Using the rest of the Pet Deposit needs the Customer's choice or a staff reason.",
    ("BR-SETTLE-017",),
    ("pet_remainder",),
)
FINAL_SETTLEMENT_PET_REMAINDER_NO_STEP = Refusal(
    422,
    "FINAL_SETTLEMENT_PET_REMAINDER_NO_STEP",
    "A reason for the rest of the Pet Deposit needs a step that uses it.",
    ("BR-SETTLE-017",),
    ("pet_remainder",),
)
FINAL_SETTLEMENT_DEPOSIT_LEFT = Refusal(
    422,
    "FINAL_SETTLEMENT_DEPOSIT_LEFT",
    "Each Deposit's remaining money must be used for debt or refunded.",
    ("BR-SETTLE-008",),
    ("steps",),
)
FINAL_SETTLEMENT_REFUND_WHILE_DEBT = Refusal(
    422,
    "FINAL_SETTLEMENT_REFUND_WHILE_DEBT",
    "No Deposit Refund while the Lease still has debt that the Deposit could pay.",
    ("BR-SETTLE-008",),
    ("steps",),
)
FINAL_SETTLEMENT_ONE_REFUND_PER_DEPOSIT = Refusal(
    422,
    "FINAL_SETTLEMENT_ONE_REFUND_PER_DEPOSIT",
    "Each Deposit can have only one Refund step.",
    ("BR-SETTLE-008",),
    ("steps",),
)
FINAL_SETTLEMENT_REFUND_RECIPIENT = Refusal(
    422,
    "FINAL_SETTLEMENT_REFUND_RECIPIENT",
    "The Refund must go to a Signer of this Lease.",
    ("BR-REFUND-015",),
    ("steps",),
)
FINAL_SETTLEMENT_SIGNER_AGREEMENT = Refusal(
    422,
    "FINAL_SETTLEMENT_SIGNER_AGREEMENT",
    "A Refund to a Signer other than the Primary Tenant needs the written agreement of all "
    "Signers.",
    ("BR-REFUND-015",),
    ("steps",),
)
FINAL_SETTLEMENT_NO_AGREEMENT_FOR_PRIMARY = Refusal(
    422,
    "FINAL_SETTLEMENT_NO_AGREEMENT_FOR_PRIMARY",
    "Leave the Signer agreement empty for a Refund to the Primary Tenant.",
    ("BR-REFUND-015",),
    ("steps",),
)
FINAL_SETTLEMENT_REFUND_METHOD_OFF = Refusal(
    422,
    "FINAL_SETTLEMENT_REFUND_METHOD_OFF",
    "This Refund method is turned off. Choose another method.",
    ("BR-REFUND-014",),
    ("steps",),
)
FINAL_SETTLEMENT_TOO_LARGE = Refusal(
    422,
    "FINAL_SETTLEMENT_TOO_LARGE",
    "This Final Settlement draft is too large. Use fewer steps or shorter notes.",
    ("BR-SETTLE-002",),
    ("steps",),
)
# V1-056 slice 11e-2: the post-settlement correction drafts with no DL-032 plan and the
# Adjustment reversal draft. A record the form chose answers 422 on its field; state answers 409.
CORRECTION_SETTLEMENT_NOT_CLOSED = Refusal(
    409,
    "CORRECTION_SETTLEMENT_NOT_CLOSED",
    "A post-settlement correction is only for a closed Final Settlement. Use the Final "
    "Settlement draft instead.",
    ("BR-SETTLE-013",),
)
CORRECTION_SOURCE_DRAFT_WAITING = Refusal(
    409,
    "CORRECTION_SOURCE_DRAFT_WAITING",
    "A draft on a record of this Final Settlement waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)
CORRECTION_DAMAGE_TO_PRIMARY = Refusal(
    422,
    "CORRECTION_DAMAGE_TO_PRIMARY",
    "A Damage charge goes to the Primary Tenant. Choose an Invoice of the Primary Tenant, or none.",
    (
        "BR-SETTLE-013",
        "BR-INV-044",
    ),
    ("corrects_invoice_id",),
)
CORRECTION_CORRECTED_INVOICE_NOT_OF_SETTLEMENT = Refusal(
    422,
    "CORRECTION_CORRECTED_INVOICE_NOT_OF_SETTLEMENT",
    "Choose an issued Invoice of this Final Settlement's Lease.",
    ("BR-SETTLE-013",),
    ("corrects_invoice_id",),
)
CORRECTION_FINDING_BILLED = Refusal(
    409,
    "CORRECTION_FINDING_BILLED",
    "This damage finding is billed already.",
    ("BR-INV-044",),
)
CORRECTION_FINDING_NOT_CURRENT = Refusal(
    422,
    "CORRECTION_FINDING_NOT_CURRENT",
    "Choose a damage finding of the current move-out inspection.",
    ("BR-INV-044",),
    ("inspection_damage_finding_id",),
)
CORRECTION_DUE_DATE_BEFORE_ISSUE = Refusal(
    422,
    "CORRECTION_DUE_DATE_BEFORE_ISSUE",
    "The Due Date cannot be before the issue date.",
    ("BR-SETTLE-013",),
    ("due_date",),
)
CORRECTION_PAID_BY_DEPOSIT = Refusal(
    409,
    "CORRECTION_PAID_BY_DEPOSIT",
    "A Deposit paid this charge at Final Settlement, so it cannot be reduced this way.",
    ("BR-SETTLE-013",),
)
CORRECTION_WOULD_RELEASE_PAID = Refusal(
    409,
    "CORRECTION_WOULD_RELEASE_PAID",
    "This reduction is more than the unpaid part of the charge. A paid part is given back with "
    "a Refund correction.",
    ("BR-SETTLE-013",),
)
CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT = Refusal(
    422,
    "CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT",
    "Choose an issued Invoice of this Final Settlement's Lease.",
    ("BR-SETTLE-013",),
    ("invoice_id",),
)
CORRECTION_INVOICE_LINE_NOT_FOUND = Refusal(
    422,
    "CORRECTION_INVOICE_LINE_NOT_FOUND",
    "No line with this id is on the chosen Invoice.",
    ("BR-SETTLE-013",),
    ("invoice_line_id",),
)
CORRECTION_LATE_CHARGE_NOT_OF_SETTLEMENT = Refusal(
    422,
    "CORRECTION_LATE_CHARGE_NOT_OF_SETTLEMENT",
    "Choose an open Late-payment Charge of this Final Settlement's Lease.",
    ("BR-SETTLE-013",),
    ("late_payment_charge_id",),
)
ADJUSTMENT_REVERSAL_NOT_CREDIT = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_NOT_CREDIT",
    "Only a credit Adjustment can be reversed this way.",
    ("BR-INV-044",),
)
ADJUSTMENT_REVERSAL_ALREADY_REVERSED = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_ALREADY_REVERSED",
    "This Adjustment is reversed already.",
    ("BR-INV-044",),
)
ADJUSTMENT_REVERSAL_INVOICE_NOT_ISSUED = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_INVOICE_NOT_ISSUED",
    "This Adjustment's Invoice is not issued.",
    ("BR-INV-044",),
)
ADJUSTMENT_REVERSAL_BY_RESOLUTION = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_BY_RESOLUTION",
    "A resolution wrote this Adjustment, so it cannot be reversed this way.",
    ("BR-INV-044",),
)
ADJUSTMENT_REVERSAL_OF_CORRECTION = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_OF_CORRECTION",
    "A post-settlement correction wrote this Adjustment. Reverse it through a correction of "
    "that Final Settlement.",
    ("BR-SETTLE-013",),
)
ADJUSTMENT_REVERSAL_THROUGH_CORRECTION = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_THROUGH_CORRECTION",
    "The Lease's Final Settlement is closed. Reverse this Adjustment through a correction of "
    "that Final Settlement.",
    ("BR-SETTLE-013",),
)
ADJUSTMENT_REVERSAL_NOT_OF_SETTLEMENT = Refusal(
    422,
    "ADJUSTMENT_REVERSAL_NOT_OF_SETTLEMENT",
    "Choose an Adjustment on an Invoice of this Final Settlement's Lease.",
    ("BR-SETTLE-013",),
    ("adjustment_id",),
)
ADJUSTMENT_REVERSAL_ONLY_CHARGE_REDUCTION = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_ONLY_CHARGE_REDUCTION",
    "Of the Adjustments that corrections wrote, only a charge reduction's can be reversed.",
    ("BR-SETTLE-013",),
)
ADJUSTMENT_REVERSAL_DRAFT_WAITING = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_DRAFT_WAITING",
    "A reversal draft of this Adjustment waits for a decision. Decide it first.",
    ("BR-AUTH-010",),
)
ADJUSTMENT_REVERSAL_TOO_LARGE = Refusal(
    409,
    "ADJUSTMENT_REVERSAL_TOO_LARGE",
    "This Adjustment reversal is too large for one draft.",
    ("BR-INV-044",),
)
RETURNED_PAYMENT_DEPOSIT_MIXED = Refusal(
    409,
    "RETURNED_PAYMENT_DEPOSIT_MIXED",
    "A Deposit this Payment paid also holds another Payment's money beside a forfeiture and "
    "a Deposit use. This correction cannot return the Payment.",
    ("BR-SETTLE-013",),
)
RETURNED_PAYMENT_OTHER_SETTLEMENT_USE = Refusal(
    409,
    "RETURNED_PAYMENT_OTHER_SETTLEMENT_USE",
    "A Deposit this Payment paid was used by another Final Settlement.",
    ("BR-SETTLE-013",),
)
RETURNED_PAYMENT_PAY_BACK_HELD = Refusal(
    409,
    "RETURNED_PAYMENT_PAY_BACK_HELD",
    "A Deposit this Payment paid holds the Customer's pay-back money beside a forfeiture. "
    "This correction cannot return the Payment.",
    ("BR-SETTLE-013",),
)
RETURNED_PAYMENT_DEPOSIT_LEFT = Refusal(
    409,
    "RETURNED_PAYMENT_DEPOSIT_LEFT",
    "A Deposit this Payment paid would still hold money after the return.",
    ("BR-SETTLE-013",),
)
RETURNED_PAYMENT_TWO_SETTLEMENTS = Refusal(
    409,
    "RETURNED_PAYMENT_TWO_SETTLEMENTS",
    "Two closed Final Settlements relied on this Payment, so it cannot be returned.",
    ("BR-SETTLE-013",),
)
RETURNED_PAYMENT_OTHER_SETTLEMENT = Refusal(
    409,
    "RETURNED_PAYMENT_OTHER_SETTLEMENT",
    "This Final Settlement did not rely on this Payment. Return it through a correction of "
    "the Final Settlement that did.",
    ("BR-SETTLE-013",),
)
RETURNED_PAYMENT_USE_RETURN_DRAFT = Refusal(
    409,
    "RETURNED_PAYMENT_USE_RETURN_DRAFT",
    "This Final Settlement did not rely on this Payment. Return it with a Payment return draft.",
    ("BR-SETTLE-013",),
)
RETURNED_PAYMENT_NOT_FOUND = Refusal(
    422,
    "RETURNED_PAYMENT_NOT_FOUND",
    "No Payment with this id is in this Property.",
    ("BR-SETTLE-013",),
    ("payment_id",),
)
MOVE_CORRECTION_OTHER_SETTLEMENT = Refusal(
    409,
    "MOVE_CORRECTION_OTHER_SETTLEMENT",
    "A correction of another Final Settlement wrote this allocation, so this correction "
    "cannot move it.",
    (
        "BR-SETTLE-013",
        "BR-PAY-042",
    ),
)
MOVE_CORRECTION_USE_MOVE_DRAFT = Refusal(
    409,
    "MOVE_CORRECTION_USE_MOVE_DRAFT",
    "This allocation was made after the closure. Move it with the ordinary move draft.",
    ("BR-PAY-042",),
)
MOVE_CORRECTION_NOT_OF_SETTLEMENT = Refusal(
    422,
    "MOVE_CORRECTION_NOT_OF_SETTLEMENT",
    "Choose an allocation that pays an Invoice of this Final Settlement's Lease.",
    (
        "BR-SETTLE-013",
        "BR-PAY-042",
    ),
    ("allocation_id",),
)
MOVE_CORRECTION_ALLOCATION_NOT_FOUND = Refusal(
    422,
    "MOVE_CORRECTION_ALLOCATION_NOT_FOUND",
    "No Payment allocation with this id is in this Property.",
    ("BR-PAY-042",),
    ("allocation_id",),
)
MOVE_CORRECTION_ALLOCATION_REVERSED = Refusal(
    409,
    "MOVE_CORRECTION_ALLOCATION_REVERSED",
    "This allocation is reversed already.",
    ("BR-PAY-042",),
)
ADJUSTMENT_REVERSAL_CORRECTION_NOT_FOUND = Refusal(
    422,
    "ADJUSTMENT_REVERSAL_CORRECTION_NOT_FOUND",
    "No Invoice Adjustment with this id is in this Property.",
    ("BR-SETTLE-013",),
    ("adjustment_id",),
)
# V1-056 slice 11e-3: the post-settlement corrections with a DL-032 plan for the value they
# release, the Deposit receipt correction and the return reversal.
CORRECTION_ONE_REFUND_CHOICE = Refusal(
    422,
    "CORRECTION_ONE_REFUND_CHOICE",
    "Use one Refund method, reference note, recipient and agreement for every Refund of this "
    "correction.",
    ("BR-SETTLE-013", "BR-REFUND-014"),
    ("steps",),
)
CORRECTION_RETURNED_MONEY_PAYS_DEBT = Refusal(
    422,
    "CORRECTION_RETURNED_MONEY_PAYS_DEBT",
    "Returned Deposit money pays the Lease's open debt first. Add the steps that pay it.",
    ("BR-SETTLE-013", "BR-SETTLE-008"),
    ("steps",),
)
CORRECTION_RELEASED_CREDIT_FIRST = Refusal(
    422,
    "CORRECTION_RELEASED_CREDIT_FIRST",
    "Credit this correction releases first pays its own Customer's open debt on this Lease. "
    "Add that step before any Refund.",
    ("BR-SETTLE-013", "BR-CREDIT-008"),
    ("steps",),
)
CORRECTION_NEW_CUSTOMER_CHOICE = Refusal(
    422,
    "CORRECTION_NEW_CUSTOMER_CHOICE",
    "Record the Customer's choice again for this correction. An earlier choice is not used again.",
    ("BR-SETTLE-013", "BR-SETTLE-008"),
    ("pet_remainder",),
)
CORRECTION_HELD_VALUE_OVER = Refusal(
    422,
    "CORRECTION_HELD_VALUE_OVER",
    "A held-value correction uses at most what the earlier correction left in each Deposit.",
    ("BR-SETTLE-013",),
    ("steps",),
)
CORRECTION_STEP_OUTSIDE_SETTLEMENT = Refusal(
    409,
    "CORRECTION_STEP_OUTSIDE_SETTLEMENT",
    "This correction releases a Credit, Deposit or obligation that is not part of this Final "
    "Settlement.",
    ("BR-SETTLE-013",),
)
CORRECTION_REFUND_OVER_CHARGE = Refusal(
    422,
    "CORRECTION_REFUND_OVER_CHARGE",
    "The Refund is more than the charge.",
    ("BR-SETTLE-013", "BR-REFUND-014"),
    ("amount_usd_cents",),
)
CORRECTION_REFUND_OVER_PAID = Refusal(
    422,
    "CORRECTION_REFUND_OVER_PAID",
    "The Refund is more than was paid on the charge.",
    ("BR-SETTLE-013", "BR-REFUND-014"),
    ("amount_usd_cents",),
)
CORRECTION_REFUND_RELEASES_NOTHING = Refusal(
    409,
    "CORRECTION_REFUND_RELEASES_NOTHING",
    "Nothing of this charge is paid. Use a charge reduction for an unpaid charge.",
    ("BR-SETTLE-013",),
)
CORRECTION_REFUNDED_LATE_CHARGE_NOT_OF_SETTLEMENT = Refusal(
    422,
    "CORRECTION_REFUNDED_LATE_CHARGE_NOT_OF_SETTLEMENT",
    "Choose a Late-payment Charge of this Final Settlement's Lease.",
    ("BR-SETTLE-013",),
    ("late_payment_charge_id",),
)
CORRECTION_PET_LINE_NOT_DAMAGE = Refusal(
    422,
    "CORRECTION_PET_LINE_NOT_DAMAGE",
    "Choose a Damage line billed from a move-out inspection finding of this Lease.",
    ("BR-SETTLE-013", "BR-SETTLE-008"),
    ("invoice_line_id",),
)
CORRECTION_PET_SAME = Refusal(
    422,
    "CORRECTION_PET_SAME",
    "The line already has this pet classification.",
    ("BR-SETTLE-013",),
    ("pet_related",),
)
CORRECTION_REFUND_NOT_FOUND = Refusal(
    422,
    "CORRECTION_REFUND_NOT_FOUND",
    "No Refund with this id is in this Property.",
    ("BR-SETTLE-013",),
    ("refund_id",),
)
CORRECTION_REFUND_NOT_RETURNABLE = Refusal(
    422,
    "CORRECTION_REFUND_NOT_RETURNABLE",
    "Choose a Refund of this Final Settlement or of one of its corrections.",
    ("BR-SETTLE-013",),
    ("refund_id",),
)
CORRECTION_RETURN_OVER_REFUND = Refusal(
    422,
    "CORRECTION_RETURN_OVER_REFUND",
    "The returned amount is more than the Refund paid.",
    ("BR-SETTLE-013",),
    ("returned_amount_usd_cents",),
)
CORRECTION_RETURN_DATE = Refusal(
    422,
    "CORRECTION_RETURN_DATE",
    "The return date must not be before the Refund or in the future.",
    ("BR-SETTLE-013",),
    ("returned_at",),
)
CORRECTION_RETURN_ONLY_NO_STEPS = Refusal(
    422,
    "CORRECTION_RETURN_ONLY_NO_STEPS",
    "A return of a Deposit Refund that only records the return has no steps.",
    ("BR-SETTLE-013",),
    ("steps",),
)
CORRECTION_RETURNED_DEPOSIT_OFF_PATH = Refusal(
    409,
    "CORRECTION_RETURNED_DEPOSIT_OFF_PATH",
    "This returned Deposit money does not follow DL-032, so it cannot pay debt or be refunded "
    "again here.",
    ("BR-SETTLE-013", "BR-SETTLE-008"),
)
CORRECTION_HELD_FROM_NOT_FOUND = Refusal(
    422,
    "CORRECTION_HELD_FROM_NOT_FOUND",
    "No correction with this id is in this Final Settlement.",
    ("BR-SETTLE-013",),
    ("held_from_correction_id",),
)
CORRECTION_HELD_FROM_NOT_RETURN_ONLY = Refusal(
    422,
    "CORRECTION_HELD_FROM_NOT_RETURN_ONLY",
    "Choose a returned-Refund correction that only recorded the return.",
    ("BR-SETTLE-013",),
    ("held_from_correction_id",),
)
CORRECTION_HELD_VALUE_NOTHING_LEFT = Refusal(
    409,
    "CORRECTION_HELD_VALUE_NOTHING_LEFT",
    "Nothing that the earlier correction held is left to refund.",
    ("BR-SETTLE-013",),
)
CORRECTION_FORFEITURE_NOT_FOUND = Refusal(
    422,
    "CORRECTION_FORFEITURE_NOT_FOUND",
    "No Deposit forfeiture with this id belongs to this Final Settlement's Lease.",
    ("BR-SETTLE-013", "BR-DEP-027"),
    ("deposit_disposition_id",),
)
CORRECTION_FORFEITURE_ALREADY_REVERSED = Refusal(
    409,
    "CORRECTION_FORFEITURE_ALREADY_REVERSED",
    "This forfeiture is reversed already.",
    ("BR-SETTLE-013", "BR-DEP-027"),
)
CORRECTION_FORFEITURE_OTHER_ACTIVE = Refusal(
    409,
    "CORRECTION_FORFEITURE_OTHER_ACTIVE",
    "Another forfeiture of this Deposit stays active. Reverse it first.",
    ("BR-SETTLE-013", "BR-DEP-027"),
)
RECEIPT_CORRECTION_NOT_FOUND = Refusal(
    422,
    "RECEIPT_CORRECTION_NOT_FOUND",
    "No Deposit receipt with this id is in this Property.",
    ("BR-SETTLE-013",),
    ("deposit_receipt_id",),
)
RECEIPT_CORRECTION_NOT_OF_SETTLEMENT = Refusal(
    422,
    "RECEIPT_CORRECTION_NOT_OF_SETTLEMENT",
    "Choose a receipt of a Deposit of this Final Settlement's Lease.",
    ("BR-SETTLE-013",),
    ("deposit_receipt_id",),
)
RECEIPT_CORRECTION_ALREADY_REVERSED = Refusal(
    409,
    "RECEIPT_CORRECTION_ALREADY_REVERSED",
    "This Deposit receipt is reversed already.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_PAYMENT_NOT_RECEIVED = Refusal(
    409,
    "RECEIPT_CORRECTION_PAYMENT_NOT_RECEIVED",
    "Only a receipt of a received Payment can be corrected.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_DRAFT_WAITING = Refusal(
    409,
    "RECEIPT_CORRECTION_DRAFT_WAITING",
    "A draft on this Deposit receipt, its Deposit or its Payment waits for a decision. Decide "
    "it first.",
    ("BR-SETTLE-013", "BR-AUTH-010"),
)
RECEIPT_CORRECTION_NO_CHANGE = Refusal(
    422,
    "RECEIPT_CORRECTION_NO_CHANGE",
    "A receipt correction must change the Deposit or the amount.",
    ("BR-SETTLE-013",),
    ("receipts",),
)
RECEIPT_CORRECTION_DEPOSIT_NOT_FOUND = Refusal(
    422,
    "RECEIPT_CORRECTION_DEPOSIT_NOT_FOUND",
    "No Deposit with this id is in this Property.",
    ("BR-SETTLE-013",),
    ("receipts",),
)
RECEIPT_CORRECTION_DEPOSIT_NOT_OF_LEASE = Refusal(
    422,
    "RECEIPT_CORRECTION_DEPOSIT_NOT_OF_LEASE",
    "A new receipt goes only into a Deposit of this Final Settlement's Lease.",
    ("BR-SETTLE-013",),
    ("receipts",),
)
RECEIPT_CORRECTION_DEPOSIT_KEPT = Refusal(
    422,
    "RECEIPT_CORRECTION_DEPOSIT_KEPT",
    "A new receipt cannot go into a Deposit the Property keeps.",
    ("BR-SETTLE-013", "BR-DEP-027"),
    ("receipts",),
)
RECEIPT_CORRECTION_DEPOSIT_HAS_RECEIPT = Refusal(
    422,
    "RECEIPT_CORRECTION_DEPOSIT_HAS_RECEIPT",
    "This Deposit already holds a receipt from this Payment.",
    ("BR-SETTLE-013",),
    ("receipts",),
)
RECEIPT_CORRECTION_OVER_REQUIRED = Refusal(
    422,
    "RECEIPT_CORRECTION_OVER_REQUIRED",
    "A new receipt would be more than the Deposit's required amount.",
    ("BR-SETTLE-013",),
    ("receipts",),
)
RECEIPT_CORRECTION_RECEIPTS_OVER = Refusal(
    422,
    "RECEIPT_CORRECTION_RECEIPTS_OVER",
    "The new receipts take more than the corrected receipt frees.",
    ("BR-SETTLE-013",),
    ("receipts",),
)
RECEIPT_CORRECTION_PAYMENT_CANNOT_FUND = Refusal(
    422,
    "RECEIPT_CORRECTION_PAYMENT_CANNOT_FUND",
    "The corrected receipt's Payment cannot pay into this Deposit.",
    ("BR-SETTLE-013",),
    ("receipts",),
)
RECEIPT_CORRECTION_OUTCOME_NEEDED = Refusal(
    422,
    "RECEIPT_CORRECTION_OUTCOME_NEEDED",
    "This Deposit's forfeiture was reversed. Choose DL-032 or a forfeiture again for the new "
    "receipt.",
    ("BR-SETTLE-013", "BR-DEP-027"),
    ("receipts",),
)
RECEIPT_CORRECTION_OUTCOME_NOT_TAKEN = Refusal(
    422,
    "RECEIPT_CORRECTION_OUTCOME_NOT_TAKEN",
    "Only a Deposit whose forfeiture was reversed takes a choice of outcome.",
    ("BR-SETTLE-013", "BR-DEP-027"),
    ("receipts",),
)
RECEIPT_CORRECTION_FORFEIT_NEW_MONEY_ONLY = Refusal(
    422,
    "RECEIPT_CORRECTION_FORFEIT_NEW_MONEY_ONLY",
    "A forfeiture in a receipt correction takes only the new receipt's money.",
    ("BR-SETTLE-013", "BR-DEP-027"),
    ("receipts",),
)
RECEIPT_CORRECTION_NOTHING_TO_FORFEIT = Refusal(
    422,
    "RECEIPT_CORRECTION_NOTHING_TO_FORFEIT",
    "Nothing beyond the Customer's pay-back money is left to forfeit. Choose DL-032.",
    ("BR-SETTLE-013", "BR-DEP-027"),
    ("receipts",),
)
RECEIPT_CORRECTION_MIXED_DEPOSIT = Refusal(
    409,
    "RECEIPT_CORRECTION_MIXED_DEPOSIT",
    "A new receipt into a Deposit that holds another Payment's money and the Customer's "
    "pay-back money is not available yet.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_CREDIT_AFTER_REAPPLY = Refusal(
    422,
    "RECEIPT_CORRECTION_CREDIT_AFTER_REAPPLY",
    "A Credit step cannot follow a Deposit use this correction writes again. Refund or apply "
    "the Customer's Credit first, or correct the receipt without new receipts.",
    ("BR-SETTLE-013", "BR-SETTLE-008"),
    ("steps",),
)
RECEIPT_CORRECTION_STEP_BEFORE_REAPPLY = Refusal(
    422,
    "RECEIPT_CORRECTION_STEP_BEFORE_REAPPLY",
    "A Deposit step comes before, in the DL-032 order, a Deposit use this correction writes again.",
    ("BR-SETTLE-013", "BR-SETTLE-008"),
    ("steps",),
)
RECEIPT_CORRECTION_STEP_REPEATS_REAPPLY = Refusal(
    422,
    "RECEIPT_CORRECTION_STEP_REPEATS_REAPPLY",
    "A Deposit step repeats a Deposit use this correction writes again. Split the step.",
    ("BR-SETTLE-013", "BR-SETTLE-008"),
    ("steps",),
)
RECEIPT_CORRECTION_DEPOSIT_NOT_EMPTY = Refusal(
    422,
    "RECEIPT_CORRECTION_DEPOSIT_NOT_EMPTY",
    "After this correction the Deposit would still hold money the steps must use or refund.",
    ("BR-SETTLE-013", "BR-SETTLE-008"),
    ("steps",),
)
RECEIPT_CORRECTION_HELD_MONEY_FIRST = Refusal(
    409,
    "RECEIPT_CORRECTION_HELD_MONEY_FIRST",
    "The corrected receipt's Deposit would still hold other money. Pay it out with a "
    "held-value Refund correction first.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_SHARED_DEPOSIT_REFUND = Refusal(
    409,
    "RECEIPT_CORRECTION_SHARED_DEPOSIT_REFUND",
    "A Deposit this Payment paid into also holds another Payment's money and has a Refund that "
    "is not fully returned.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_RESERVATION_REFUND = Refusal(
    409,
    "RECEIPT_CORRECTION_RESERVATION_REFUND",
    "A Reservation Deposit Refund paid from this Payment's money is not fully returned.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_RECOVERY_ON_CLOSED_LEASE = Refusal(
    409,
    "RECEIPT_CORRECTION_RECOVERY_ON_CLOSED_LEASE",
    "A Refund paid from this Payment's money would be charged on a Lease with a closed Final "
    "Settlement. Return the Payment through a returned-Payment correction of that Final "
    "Settlement.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_NO_RECOVERY = Refusal(
    409,
    "RECEIPT_CORRECTION_NO_RECOVERY",
    "A Refund paid from this Deposit has no planned recovery charge.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_OTHER_SETTLEMENT_USE = Refusal(
    409,
    "RECEIPT_CORRECTION_OTHER_SETTLEMENT_USE",
    "This Deposit was used by another Final Settlement.",
    ("BR-SETTLE-013",),
)
RECEIPT_CORRECTION_FORFEITURE_ACTIVE = Refusal(
    409,
    "RECEIPT_CORRECTION_FORFEITURE_ACTIVE",
    "This Deposit has an active forfeiture. Reverse it with a forfeiture reversal correction "
    "first.",
    ("BR-SETTLE-013", "BR-DEP-027"),
)
RECEIPT_CORRECTION_TOO_LARGE = Refusal(
    409,
    "RECEIPT_CORRECTION_TOO_LARGE",
    "This Deposit receipt correction is too large to store. Use fewer steps or shorter notes.",
    ("BR-SETTLE-013",),
)
RETURN_REVERSAL_NOT_FOUND = Refusal(
    422,
    "RETURN_REVERSAL_NOT_FOUND",
    "No returned-Refund correction with this id is in this Final Settlement.",
    ("BR-SETTLE-013",),
    ("earlier_correction_id",),
)
RETURN_REVERSAL_ALREADY_REVERSED = Refusal(
    409,
    "RETURN_REVERSAL_ALREADY_REVERSED",
    "The return of this correction is reversed already.",
    ("BR-SETTLE-013",),
)
RETURN_REVERSAL_DRAFT_WAITING = Refusal(
    409,
    "RETURN_REVERSAL_DRAFT_WAITING",
    "A return reversal draft of this correction waits for a decision. Decide it first.",
    ("BR-SETTLE-013", "BR-AUTH-010"),
)
RETURN_REVERSAL_REFUND_RETURNED_FIRST = Refusal(
    409,
    "RETURN_REVERSAL_REFUND_RETURNED_FIRST",
    "A Refund paid from the returned money has its own return. Reverse that return first.",
    ("BR-SETTLE-013",),
)
RETURN_REVERSAL_FORFEITED = Refusal(
    409,
    "RETURN_REVERSAL_FORFEITED",
    "A forfeiture kept this return's money, so the return cannot be reversed.",
    ("BR-SETTLE-013", "BR-DEP-027"),
)
RETURN_REVERSAL_VALUE_USED = Refusal(
    409,
    "RETURN_REVERSAL_VALUE_USED",
    "The returned money is used elsewhere now. Undo that use first.",
    ("BR-SETTLE-013",),
)
RETURN_REVERSAL_WAITS_FOR_OWNER = Refusal(
    409,
    "RETURN_REVERSAL_WAITS_FOR_OWNER",
    "The returned money was used in a way this reversal cannot follow yet. Reversing it waits "
    "for the owner.",
    ("BR-SETTLE-013",),
)
RETURN_REVERSAL_TOO_LARGE = Refusal(
    409,
    "RETURN_REVERSAL_TOO_LARGE",
    "This return reversal is too large to store.",
    ("BR-SETTLE-013",),
)
CORRECTION_REFUND_METHOD_OFF = Refusal(
    422,
    "CORRECTION_REFUND_METHOD_OFF",
    "This Refund method is not an active method. Choose an active method.",
    ("BR-SETTLE-013", "BR-REFUND-014"),
    ("refund_method_id",),
)
CORRECTION_NEW_REFUND_METHOD_OFF = Refusal(
    422,
    "CORRECTION_NEW_REFUND_METHOD_OFF",
    "This Refund method is not an active method. Choose an active method.",
    ("BR-SETTLE-013", "BR-REFUND-014"),
    ("new_refund_method_id",),
)
