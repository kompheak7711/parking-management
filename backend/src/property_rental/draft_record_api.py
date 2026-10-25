"""Record routes for Deposit forfeiture, Deposit correction and returned-Payment drafts.

V1-056 slice 11c-3. Each route records one draft through the kind's own service; a draft has no
financial effect until a ``financial.approve`` holder confirms it through the shared draft routes
(``financial_draft_api.py``), where it is also rejected or withdrawn.

- A Lease Deposit forfeiture draft (``deposits.dispose``; BR-DEP-026) forfeits the whole held
  Deposit of a terminated Lease on the ground the database works out from the termination record.
- A Lease forfeiture reversal draft (``deposits.correct``) reverses one confirmed forfeiture.
- A Deposit receipt reversal draft (``deposits.correct``) records that money recorded as received
  for a Deposit was not received (Q-2026-10-05-22).
- A returned-Payment draft (``payments.reverse``; BR-SETTLE-013) returns one received Payment.
- A wrong-Unit Payment move draft (``payments.allocations.reverse``; BR-PAY-042; slice 11d) moves
  one Invoice allocation to the correct Invoice on another Unit, with how each Customer
  acknowledged the mistake.

A named business-state refusal answers 409 with its own code (owner answer of 2026-10-05); a
refusal that is not named keeps the plain answer of its service error. No answer shows database
text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Final, Protocol, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from property_rental.allocation_receipt_api import ReversalInput, _mutation
from property_rental.api_refusals import (
    DEPOSIT_DRAFT_WAITING,
    DEPOSIT_FORFEITURE_ALREADY_REVERSED,
    DEPOSIT_FORFEITURE_DRAFT_WAITING,
    DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED,
    DEPOSIT_FORFEITURE_NO_GROUND,
    DEPOSIT_FORFEITURE_NOTHING_HELD,
    DEPOSIT_FORFEITURE_PET_AT_SETTLEMENT,
    DEPOSIT_FORFEITURE_REVERSAL_DRAFT_WAITING,
    DEPOSIT_RECEIPT_ALREADY_REVERSED,
    DRAFT_OUT_OF_DATE,
    DRAFT_RECORD_ID_IN_USE,
    FINAL_SETTLEMENT_CLOSED,
    IDEMPOTENCY_KEY_REUSED,
    PAYMENT_MOVE_ALREADY_MOVED,
    PAYMENT_MOVE_CREDIT_OR_REFUND_FIRST,
    PAYMENT_MOVE_DRAFT_WAITING,
    PAYMENT_MOVE_NOT_INVOICE_ALLOCATION,
    PAYMENT_MOVE_PAYMENT_REVERSED,
    PAYMENT_MOVE_RELEASED_BY_ADJUSTMENT,
    PAYMENT_MOVE_TARGET_NOT_FOUND,
    PAYMENT_MOVE_TARGET_NOTHING_OWED,
    PAYMENT_MOVE_TARGET_SAME_UNIT,
    PAYMENT_MOVE_TARGET_TOO_LARGE,
    PAYMENT_MOVE_THROUGH_CORRECTION,
    PAYMENT_MOVE_TOO_LARGE,
    PAYMENT_MOVE_VALUE_GONE,
    PAYMENT_RETURN_DEPOSIT_USED,
    PAYMENT_RETURN_DRAFT_WAITING,
    PAYMENT_RETURN_FORFEITURE_ACTIVE,
    PAYMENT_RETURN_NOT_RECEIVED,
    PAYMENT_RETURN_REFUND_NO_RECOVERY,
    PAYMENT_RETURN_REFUND_NOT_RETURNED,
    PAYMENT_RETURN_SETTLEMENT_NOT_CORRECTABLE,
    PAYMENT_RETURN_THROUGH_CORRECTION,
    PAYMENT_RETURN_TOO_LARGE,
    Refusal,
    RefusedRequest,
    database_refusal,
)
from property_rental.credit_refund_api import CreditRefundRequestRoute, _financial_json
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalAuthorizationError,
    DepositReceiptReversalConflictError,
    DepositReceiptReversalInvalidError,
    DepositReceiptReversalKeyReused,
    DepositReceiptReversalNotFoundError,
    DepositReceiptReversalService,
    DepositReceiptReversalUnavailableError,
    RecordDepositReceiptReversalCommand,
)
from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.lease_deposit_forfeiture import (
    DEPOSIT_CORRECT_CAPABILITY,
    DEPOSIT_DISPOSE_CAPABILITY,
    LeaseDepositForfeitureAuthorizationError,
    LeaseDepositForfeitureConflictError,
    LeaseDepositForfeitureInvalidError,
    LeaseDepositForfeitureKeyReused,
    LeaseDepositForfeitureNotFoundError,
    LeaseDepositForfeitureService,
    LeaseDepositForfeitureUnavailableError,
    RecordLeaseDepositForfeitureCommand,
    RecordLeaseDepositReversalCommand,
)
from property_rental.payment_api import Evidence, Identity, Memo, _actor, _queries
from property_rental.payment_move import (
    PAYMENT_MOVE_PREPARE_CAPABILITY,
    PaymentMoveAuthorizationError,
    PaymentMoveConflictError,
    PaymentMoveInvalidError,
    PaymentMoveKeyReused,
    PaymentMoveNotFoundError,
    PaymentMoveService,
    PaymentMoveUnavailableError,
    RecordPaymentMoveCommand,
)
from property_rental.payment_return import (
    PAYMENT_RETURN_PREPARE_CAPABILITY,
    PaymentReturnAuthorizationError,
    PaymentReturnConflictError,
    PaymentReturnInvalidError,
    PaymentReturnKeyReused,
    PaymentReturnNotFoundError,
    PaymentReturnService,
    PaymentReturnUnavailableError,
    RecordPaymentReturnCommand,
)
from property_rental.settings import Settings

T = TypeVar("T")
Key = Annotated[Identity, Header(alias="Idempotency-Key")]


class ForfeitureDraftInput(ReversalInput):
    disposition_id: Identity


class ForfeitureReversalDraftInput(ReversalInput):
    reversal_id: Identity
    evidence_reference: Evidence


class ReceiptReversalDraftInput(ReversalInput):
    reversal_id: Identity


class PaymentReturnDraftInput(ReversalInput):
    evidence_reference: Evidence


class PaymentMoveDraftInput(ReversalInput):
    target_invoice_id: Identity
    source_acknowledgement: Memo
    target_acknowledgement: Memo


class DraftRecordFlow(Protocol):
    def forfeiture(
        self,
        property_id: UUID,
        command: RecordLeaseDepositForfeitureCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def forfeiture_reversal(
        self,
        property_id: UUID,
        command: RecordLeaseDepositReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def receipt_reversal(
        self,
        property_id: UUID,
        command: RecordDepositReceiptReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def payment_return(
        self,
        property_id: UUID,
        command: RecordPaymentReturnCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def payment_move(
        self,
        property_id: UUID,
        command: RecordPaymentMoveCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


class DraftRecordUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PostgresDraftRecordFlow:
    financial_database_url: str | None

    def _url(self) -> str:
        if self.financial_database_url is None:
            raise DraftRecordUnavailable("Financial drafts are unavailable")
        return self.financial_database_url

    def forfeiture(
        self,
        property_id: UUID,
        command: RecordLeaseDepositForfeitureCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return LeaseDepositForfeitureService(self._url()).record(property_id, command, actor=actor)

    def forfeiture_reversal(
        self,
        property_id: UUID,
        command: RecordLeaseDepositReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return LeaseDepositForfeitureService(self._url()).record_reversal(
            property_id, command, actor=actor
        )

    def receipt_reversal(
        self,
        property_id: UUID,
        command: RecordDepositReceiptReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return DepositReceiptReversalService(self._url()).record(property_id, command, actor=actor)

    def payment_return(
        self,
        property_id: UUID,
        command: RecordPaymentReturnCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return PaymentReturnService(self._url()).record(property_id, command, actor=actor)

    def payment_move(
        self,
        property_id: UUID,
        command: RecordPaymentMoveCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return PaymentMoveService(self._url()).record(property_id, command, actor=actor)


NOT_FOUND_ERRORS: Final = (
    LeaseDepositForfeitureNotFoundError,
    DepositReceiptReversalNotFoundError,
    PaymentReturnNotFoundError,
    PaymentMoveNotFoundError,
)
AUTHORIZATION_ERRORS: Final = (
    LeaseDepositForfeitureAuthorizationError,
    DepositReceiptReversalAuthorizationError,
    PaymentReturnAuthorizationError,
    PaymentMoveAuthorizationError,
)
INVALID_ERRORS: Final = (
    LeaseDepositForfeitureInvalidError,
    DepositReceiptReversalInvalidError,
    PaymentReturnInvalidError,
    PaymentMoveInvalidError,
)
KEY_REUSED_ERRORS: Final = (
    LeaseDepositForfeitureKeyReused,
    DepositReceiptReversalKeyReused,
    PaymentReturnKeyReused,
    PaymentMoveKeyReused,
)
CONFLICT_ERRORS: Final = (
    LeaseDepositForfeitureConflictError,
    DepositReceiptReversalConflictError,
    PaymentReturnConflictError,
    PaymentMoveConflictError,
)
UNAVAILABLE_ERRORS: Final = (
    LeaseDepositForfeitureUnavailableError,
    DepositReceiptReversalUnavailableError,
    PaymentReturnUnavailableError,
    DraftRecordUnavailable,
    PaymentMoveUnavailableError,
)

# The database messages each route names (migrations 83, 84, 87, 108, 109, 116 to 118, 157, 167).
# An id the form chose that is already used is named before the key-reuse answer, because the
# services report both as a reused key.
FORFEITURE_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "The Lease is not terminated": DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED,
        "The termination record is ambiguous": DEPOSIT_FORFEITURE_NO_GROUND,
        "The forfeiture ground cannot be worked out from the termination record": (
            DEPOSIT_FORFEITURE_NO_GROUND
        ),
        "The Pet Deposit is not forfeited on this ground; it is decided at Final Settlement "
        "(BR-DEP-024, BR-DEP-027)": DEPOSIT_FORFEITURE_PET_AT_SETTLEMENT,
        "The Deposit holds nothing to forfeit": DEPOSIT_FORFEITURE_NOTHING_HELD,
        "A forfeiture draft for this Deposit is already waiting": DEPOSIT_FORFEITURE_DRAFT_WAITING,
        "Deposit disposition identity was reused": DRAFT_RECORD_ID_IN_USE,
        "A closed Final Settlement's Deposit is forfeited only through a post-settlement "
        "correction": FINAL_SETTLEMENT_CLOSED,
    }
)
FORFEITURE_REVERSAL_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "The forfeiture is already reversed": DEPOSIT_FORFEITURE_ALREADY_REVERSED,
        "A reversal draft for this forfeiture is already waiting": (
            DEPOSIT_FORFEITURE_REVERSAL_DRAFT_WAITING
        ),
        "Deposit disposition reversal identity was reused": DRAFT_RECORD_ID_IN_USE,
        "The Lease's Final Settlement is closed; reverse this forfeiture through a correction of "
        "that Final Settlement": FINAL_SETTLEMENT_CLOSED,
    }
)
RECEIPT_REVERSAL_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "The Deposit receipt is already reversed": DEPOSIT_RECEIPT_ALREADY_REVERSED,
        "A draft for this Deposit is already waiting": DEPOSIT_DRAFT_WAITING,
        "Deposit receipt reversal identity was reused": DRAFT_RECORD_ID_IN_USE,
        "A closed Final Settlement's Deposit receipt changes only through a post-settlement "
        "correction": FINAL_SETTLEMENT_CLOSED,
    }
)
PAYMENT_RETURN_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "Only a received Payment can be returned": PAYMENT_RETURN_NOT_RECEIVED,
        "A closed Final Settlement relied on this Payment's records; return it through a "
        "correction of that Final Settlement": PAYMENT_RETURN_THROUGH_CORRECTION,
        "A Reservation Deposit Refund paid from this Payment's value is not fully returned": (
            PAYMENT_RETURN_REFUND_NOT_RETURNED
        ),
        "A Deposit this Payment funded also holds another Payment's money and has a Refund that "
        "is not fully returned": PAYMENT_RETURN_REFUND_NOT_RETURNED,
        "A Refund paid from this Payment's value has no planned recovery": (
            PAYMENT_RETURN_REFUND_NO_RECOVERY
        ),
        "A Refund paid from this Payment's value would be charged on a Lease whose Final "
        "Settlement is closed; return the Payment through a returned-Payment correction of that "
        "Final Settlement": PAYMENT_RETURN_THROUGH_CORRECTION,
        "A Refund paid from this Payment's value would be charged on a Lease whose closed Final "
        "Settlement this return cannot correct": PAYMENT_RETURN_SETTLEMENT_NOT_CORRECTABLE,
        "A Deposit this Payment funded has an active forfeiture; reverse the forfeiture first": (
            PAYMENT_RETURN_FORFEITURE_ACTIVE
        ),
        "A Deposit this Payment funded has an active Deposit application": (
            PAYMENT_RETURN_DEPOSIT_USED
        ),
        "A draft that names this Payment or one of its records is waiting": (
            PAYMENT_RETURN_DRAFT_WAITING
        ),
        "The return draft exceeds the stored draft size of 16000 bytes (the Payment's records)": (
            PAYMENT_RETURN_TOO_LARGE
        ),
    }
)
# Slice 11d (messages read from the head catalog: migration 85 and later patches). A correct
# Invoice the form chose that is wrong is bad input (422 on its field); the rest is business state.
PAYMENT_MOVE_STATE_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "Only an Invoice allocation can move": PAYMENT_MOVE_NOT_INVOICE_ALLOCATION,
        "The Payment is reversed": PAYMENT_MOVE_PAYMENT_REVERSED,
        "This allocation was already moved": PAYMENT_MOVE_ALREADY_MOVED,
        "A credit Adjustment released this allocation": PAYMENT_MOVE_RELEASED_BY_ADJUSTMENT,
        "Reverse the Customer Credit or Refund from this Payment first": (
            PAYMENT_MOVE_CREDIT_OR_REFUND_FIRST
        ),
        "The Payment no longer holds the value to move": PAYMENT_MOVE_VALUE_GONE,
        "The correct Invoice has too many lines for one move": PAYMENT_MOVE_TARGET_TOO_LARGE,
        "A closed Final Settlement relied on this allocation; move it through a correction of "
        "that Final Settlement": PAYMENT_MOVE_THROUGH_CORRECTION,
    }
)
PAYMENT_MOVE_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PAYMENT_MOVE_STATE_REFUSALS,
        "Invoice was not found": PAYMENT_MOVE_TARGET_NOT_FOUND,
        "The correct Invoice must belong to a Lease of another Unit": (
            PAYMENT_MOVE_TARGET_SAME_UNIT
        ),
        "The correct Invoice has nothing outstanding": PAYMENT_MOVE_TARGET_NOTHING_OWED,
        "A move draft for this allocation is already waiting": PAYMENT_MOVE_DRAFT_WAITING,
        "The move draft exceeds the stored draft size of 16000 bytes (acknowledgements and the "
        "line split of the correct Invoice)": PAYMENT_MOVE_TOO_LARGE,
    }
)
# At the shared confirm the correct Invoice was checked at record, so a change there means the
# draft is out of date; the confirm's own stale refusal (55000) too. The table applies to the
# plain move only (kind PAYMENT_MOVE); a Final Settlement correction keeps its plain answers.
PAYMENT_MOVE_CONFIRM_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PAYMENT_MOVE_STATE_REFUSALS,
        "The correct Invoice has nothing outstanding": DRAFT_OUT_OF_DATE,
        "Payment move draft is stale": DRAFT_OUT_OF_DATE,
        # A Final Settlement closed after the check and before the reversal was written.
        "A closed Final Settlement changes only through a post-settlement correction": (
            PAYMENT_MOVE_THROUGH_CORRECTION
        ),
    }
)
# The shared confirm names the same refusals for these drafts (financial_draft_api.py): a
# confirmation checks the draft's rules again. The three variants share the kind
# DEPOSIT_FORFEITURE with the Reservation Deposit drafts, which keep their plain answers.
DEPOSIT_DRAFT_VARIANTS: Final = frozenset(
    {"LEASE_FORFEITURE", "LEASE_FORFEITURE_REVERSAL", "DEPOSIT_RECEIPT_REVERSAL"}
)
DEPOSIT_DRAFT_CONFIRM_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **FORFEITURE_REFUSALS,
        **FORFEITURE_REVERSAL_REFUSALS,
        **RECEIPT_REVERSAL_REFUSALS,
        # Only a forfeiture confirm waits for a receipt reversal draft (owner answer 2 to
        # Q-2026-10-05-23); recording one stays allowed.
        "A Deposit receipt reversal draft for this Deposit is waiting": DEPOSIT_DRAFT_WAITING,
        # A draft whose Deposit changed since it was recorded stays pending (review round 1).
        "Lease Deposit forfeiture draft is stale": DRAFT_OUT_OF_DATE,
        "Lease Deposit forfeiture reversal draft is stale": DRAFT_OUT_OF_DATE,
        "Deposit receipt reversal draft is stale": DRAFT_OUT_OF_DATE,
    }
)


def _invoke(call: Callable[[], T], refusals: Mapping[str, Refusal]) -> T:
    try:
        return call()
    except (*NOT_FOUND_ERRORS, *AUTHORIZATION_ERRORS, *INVALID_ERRORS, *CONFLICT_ERRORS) as exc:
        refusal = database_refusal(exc, refusals)
        if refusal is not None:
            raise RefusedRequest(refusal) from exc
        if isinstance(exc, KEY_REUSED_ERRORS):
            raise RefusedRequest(IDEMPOTENCY_KEY_REUSED) from exc
        if isinstance(exc, NOT_FOUND_ERRORS):
            raise HTTPException(404) from exc
        if isinstance(exc, AUTHORIZATION_ERRORS):
            raise HTTPException(403) from exc
        if isinstance(exc, INVALID_ERRORS):
            raise HTTPException(422) from exc
        raise HTTPException(409) from exc
    except UNAVAILABLE_ERRORS as exc:
        raise HTTPException(503) from exc


def _pending_draft(
    value: object,
    property_id: UUID,
    kind: str,
    variant: str | None,
    subject: tuple[str, UUID],
) -> dict[str, object]:
    """The recorded draft, checked against the command before it is shown: its Property, kind,
    exact variant (a returned-Payment draft has none) and the record the path names."""
    payload = value.get("payload") if isinstance(value, dict) else None
    key, identity = subject
    if (
        not isinstance(value, dict)
        or value.get("property_id") != str(property_id)
        or value.get("kind") != kind
        or not isinstance(payload, dict)
        or (payload.get("variant") != variant if variant is not None else "variant" in payload)
        or payload.get(key) != str(identity)
    ):
        raise HTTPException(503)
    return value


def create_draft_record_router(
    resolver: ActorResolver, flow: DraftRecordFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1", tags=["financial-drafts"], route_class=CreditRefundRequestRoute
    )

    def context(request: Request, property_id: UUID, capability: str) -> AuthenticatedActor:
        _queries(request, set())
        actor = _actor(request, resolver)
        _mutation(request, settings)
        # A Property the person may not prepare this draft in is hidden.
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise HTTPException(404)
        bind_financial_property(request, property_id)
        return actor

    def envelope(request: Request, result: object) -> dict[str, object]:
        return {"data": result, "meta": financial_metadata(request)}

    @router.post(
        "/properties/{property_id}/deposits/{deposit_id}/forfeiture-drafts",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def record_forfeiture(
        property_id: Identity,
        deposit_id: Identity,
        body: ForfeitureDraftInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Record a draft that forfeits the whole held Deposit of a terminated Lease."""
        actor = context(request, property_id, DEPOSIT_DISPOSE_CAPABILITY)
        command = _invoke(
            lambda: RecordLeaseDepositForfeitureCommand(
                idempotency_key, deposit_id, body.disposition_id, body.reason
            ),
            FORFEITURE_REFUSALS,
        )
        result = _invoke(
            lambda: flow.forfeiture(property_id, command, actor=actor), FORFEITURE_REFUSALS
        )
        return envelope(
            request,
            _pending_draft(
                result,
                property_id,
                "DEPOSIT_FORFEITURE",
                "LEASE_FORFEITURE",
                ("deposit_id", deposit_id),
            ),
        )

    @router.post(
        "/properties/{property_id}/deposit-dispositions/{disposition_id}/reversal-drafts",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def record_forfeiture_reversal(
        property_id: Identity,
        disposition_id: Identity,
        body: ForfeitureReversalDraftInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Record a draft that reverses one confirmed Lease Deposit forfeiture."""
        actor = context(request, property_id, DEPOSIT_CORRECT_CAPABILITY)
        command = _invoke(
            lambda: RecordLeaseDepositReversalCommand(
                idempotency_key,
                disposition_id,
                body.reversal_id,
                body.reason,
                body.evidence_reference,
            ),
            FORFEITURE_REVERSAL_REFUSALS,
        )
        result = _invoke(
            lambda: flow.forfeiture_reversal(property_id, command, actor=actor),
            FORFEITURE_REVERSAL_REFUSALS,
        )
        return envelope(
            request,
            _pending_draft(
                result,
                property_id,
                "DEPOSIT_FORFEITURE",
                "LEASE_FORFEITURE_REVERSAL",
                ("disposition_id", disposition_id),
            ),
        )

    @router.post(
        "/properties/{property_id}/deposit-receipts/{receipt_id}/reversal-drafts",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def record_receipt_reversal(
        property_id: Identity,
        receipt_id: Identity,
        body: ReceiptReversalDraftInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Record a draft saying that money recorded for a Deposit was not received."""
        actor = context(request, property_id, DEPOSIT_CORRECT_CAPABILITY)
        command = _invoke(
            lambda: RecordDepositReceiptReversalCommand(
                idempotency_key, receipt_id, body.reversal_id, body.reason
            ),
            RECEIPT_REVERSAL_REFUSALS,
        )
        result = _invoke(
            lambda: flow.receipt_reversal(property_id, command, actor=actor),
            RECEIPT_REVERSAL_REFUSALS,
        )
        return envelope(
            request,
            _pending_draft(
                result,
                property_id,
                "DEPOSIT_FORFEITURE",
                "DEPOSIT_RECEIPT_REVERSAL",
                ("receipt_id", receipt_id),
            ),
        )

    @router.post(
        "/properties/{property_id}/payments/{payment_id}/return-drafts",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def record_payment_return(
        property_id: Identity,
        payment_id: Identity,
        body: PaymentReturnDraftInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Record a draft that returns one received Payment (a bounced transfer)."""
        actor = context(request, property_id, PAYMENT_RETURN_PREPARE_CAPABILITY)
        command = _invoke(
            lambda: RecordPaymentReturnCommand(
                idempotency_key, payment_id, body.reason, body.evidence_reference
            ),
            PAYMENT_RETURN_REFUSALS,
        )
        result = _invoke(
            lambda: flow.payment_return(property_id, command, actor=actor),
            PAYMENT_RETURN_REFUSALS,
        )
        return envelope(
            request,
            _pending_draft(result, property_id, "PAYMENT_RETURN", None, ("payment_id", payment_id)),
        )

    @router.post(
        "/properties/{property_id}/payment-allocations/{allocation_id}/move-drafts",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def record_payment_move(
        property_id: Identity,
        allocation_id: Identity,
        body: PaymentMoveDraftInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Record a draft that moves one Invoice allocation made on the wrong Unit's Invoice to
        the correct Invoice on another Unit (BR-PAY-042; slice 11d)."""
        actor = context(request, property_id, PAYMENT_MOVE_PREPARE_CAPABILITY)
        command = _invoke(
            lambda: RecordPaymentMoveCommand(
                idempotency_key,
                allocation_id,
                body.target_invoice_id,
                body.reason,
                body.source_acknowledgement,
                body.target_acknowledgement,
            ),
            PAYMENT_MOVE_REFUSALS,
        )
        result = _invoke(
            lambda: flow.payment_move(property_id, command, actor=actor),
            PAYMENT_MOVE_REFUSALS,
        )
        return envelope(
            request,
            _pending_draft(
                result,
                property_id,
                "PAYMENT_MOVE",
                "WRONG_UNIT_MOVE",
                ("source_allocation_id", allocation_id),
            ),
        )

    return router
