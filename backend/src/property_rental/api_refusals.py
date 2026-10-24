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
