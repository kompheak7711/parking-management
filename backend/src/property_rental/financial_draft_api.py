"""Shared financial draft routes: list, detail, reject, withdraw and confirm (V1-056 slice 11b).

Every kind of draft (Refund, Deposit forfeiture, Payment move, Final Settlement and its
corrections, returned Payment, Adjustment reversal) is read and decided here. A reader sees only
the drafts prepared under a capability it holds, or every draft with ``financial.approve``.
Reject needs ``financial.approve``; withdraw is for the person who prepared the draft, with the
draft's own prepare capability. Neither moves money. Confirm (``financial.approve``) calls the
kind's own confirm command, which checks every rule again (``financial_draft_confirm.py``).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Final, Literal, Protocol, TypeVar, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from property_rental.allocation_receipt_api import ReversalInput, _mutation
from property_rental.api_refusals import (
    DRAFT_ALREADY_DECIDED,
    DRAFT_CONFIRM_NOT_AVAILABLE,
    DRAFT_CONFIRM_REFUSED,
    DRAFT_DECISION_NOT_ALLOWED,
    DRAFT_OUT_OF_DATE,
    DRAFT_WITHDRAW_PREPARER_ONLY,
    Refusal,
    RefusedRequest,
    database_refusal,
)
from property_rental.credit_refund_api import (
    REFUND_REFUSALS_BY_DATABASE_MESSAGE,
    CreditRefundRequestRoute,
    _financial_json,
)
from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.financial_draft import (
    FINANCIAL_APPROVE_CAPABILITY,
    PREPARE_CAPABILITIES,
    FinancialDraftAuthorizationError,
    FinancialDraftConflictError,
    FinancialDraftDecidedError,
    FinancialDraftInvalidError,
    FinancialDraftNotFoundError,
    FinancialDraftNotPreparerError,
    FinancialDraftPage,
    FinancialDraftService,
    FinancialDraftState,
    FinancialDraftUnavailableError,
)
from property_rental.financial_draft_confirm import (
    AUTHORIZATION_ERRORS,
    CONFLICT_ERRORS,
    INVALID_ERRORS,
    NOT_FOUND_ERRORS,
    STALE_ERRORS,
    UNAVAILABLE_ERRORS,
    DraftConfirmNotAvailable,
    DraftPayloadInvalid,
    PostgresDraftConfirmer,
)
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.payment_api import Identity, _actor, _cursor, _queries, _timestamp
from property_rental.settings import Settings

T = TypeVar("T")
StateFilter = Literal["PENDING", "CONFIRMED", "REJECTED", "WITHDRAWN"]
PageLimit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=1024)]
Key = Annotated[Identity, Header(alias="Idempotency-Key")]
READ_CAPABILITIES = frozenset({FINANCIAL_APPROVE_CAPABILITY, *PREPARE_CAPABILITIES})
RESERVATION_READ_CAPABILITY = "reservations.read"
RESERVATION_VARIANTS = frozenset({"RESERVATION_OUTCOME", "RESERVATION_CORRECTION"})


class FinancialDraftFlow(Protocol):
    def get(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def list(
        self, property_id: UUID, *, actor: AuthenticatedActor, page: FinancialDraftPage
    ) -> dict[str, object]: ...
    def reject(
        self, property_id: UUID, draft_id: UUID, reason: str, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def withdraw(
        self,
        property_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        prepare_capability: str,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def confirm(
        self, property_id: UUID, draft: dict[str, object], *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class PostgresFinancialDraftFlow:
    database_url: str | None
    financial_database_url: str | None

    def _service(self, *, mutation: bool) -> FinancialDraftService:
        if self.database_url is None or (mutation and self.financial_database_url is None):
            raise FinancialDraftUnavailableError("Financial drafts are unavailable")
        return FinancialDraftService(self.database_url, self.financial_database_url or "")

    def get(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return self._service(mutation=False).get(property_id, draft_id, actor=actor)

    def list(
        self, property_id: UUID, *, actor: AuthenticatedActor, page: FinancialDraftPage
    ) -> dict[str, object]:
        return self._service(mutation=False).list(property_id, actor=actor, page=page)

    def reject(
        self, property_id: UUID, draft_id: UUID, reason: str, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return self._service(mutation=True).reject(property_id, draft_id, reason, actor=actor)

    def withdraw(
        self,
        property_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        prepare_capability: str,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._service(mutation=True).withdraw(
            property_id,
            draft_id,
            reason,
            prepare_capability=prepare_capability,
            actor=actor,
        )

    def confirm(
        self, property_id: UUID, draft: dict[str, object], *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        if self.database_url is None or self.financial_database_url is None:
            raise DraftPayloadInvalid("Financial drafts are unavailable")
        return PostgresDraftConfirmer(self.database_url, self.financial_database_url).confirm(
            property_id, draft, actor=actor
        )


def _without_transaction_id(value: object) -> object:
    """A confirm answer never shows the database transaction id (slice 11b)."""
    if isinstance(value, dict):
        return {
            key: _without_transaction_id(item)
            for key, item in value.items()
            if key != "transaction_id"
        }
    if isinstance(value, list):
        return [_without_transaction_id(item) for item in value]
    return value


# The named refusals of a draft kind's confirm command (slice 11c). Only Refund drafts have
# them yet; the other kinds keep their plain answers until their own routes name them
# (slice 11c-2 review round 1: a closed-Settlement refusal reads wrongly on a correction).
CONFIRM_REFUSALS: Final[Mapping[str, Mapping[str, Refusal]]] = MappingProxyType(
    {"REFUND": REFUND_REFUSALS_BY_DATABASE_MESSAGE}
)


def _confirm_invoke(call: Callable[[], T], kind: object) -> T:
    try:
        return _confirm_call(call)
    except (HTTPException, RefusedRequest) as exc:
        # Slice 11c: a named business-state refusal of the kind's command keeps its own code.
        cause = exc.__cause__
        table = CONFIRM_REFUSALS.get(kind) if isinstance(kind, str) else None
        refusal = None if cause is None or table is None else database_refusal(cause, table)
        if refusal is not None and not (
            isinstance(exc, RefusedRequest) and exc.refusal == DRAFT_OUT_OF_DATE
        ):
            raise RefusedRequest(refusal) from exc
        raise


def _confirm_call(call: Callable[[], T]) -> T:
    try:
        return call()
    except NOT_FOUND_ERRORS as exc:
        raise HTTPException(404) from exc
    except AUTHORIZATION_ERRORS as exc:
        raise HTTPException(403) from exc
    except INVALID_ERRORS as exc:
        raise HTTPException(422) from exc
    except STALE_ERRORS as exc:
        raise RefusedRequest(DRAFT_OUT_OF_DATE) from exc
    except CONFLICT_ERRORS as exc:
        raise RefusedRequest(DRAFT_CONFIRM_REFUSED) from exc
    except DraftConfirmNotAvailable as exc:
        raise RefusedRequest(DRAFT_CONFIRM_NOT_AVAILABLE) from exc
    except (*UNAVAILABLE_ERRORS, DraftPayloadInvalid) as exc:
        raise HTTPException(503) from exc


def _invoke(call: Callable[[], T], *, query: bool = False) -> T:
    try:
        return call()
    except FinancialDraftNotFoundError as exc:
        raise HTTPException(404) from exc
    except FinancialDraftAuthorizationError as exc:
        raise HTTPException(403) from exc
    except FinancialDraftInvalidError as exc:
        raise HTTPException(400 if query else 422) from exc
    except FinancialDraftDecidedError as exc:
        raise RefusedRequest(DRAFT_ALREADY_DECIDED) from exc
    except FinancialDraftConflictError as exc:
        raise RefusedRequest(DRAFT_DECISION_NOT_ALLOWED) from exc
    except FinancialDraftUnavailableError as exc:
        raise HTTPException(503) from exc


def _actor_text(actor: AuthenticatedActor) -> str:
    try:
        return str(UUID(actor.actor_id))
    except ValueError as exc:
        raise HTTPException(403) from exc


def _confirmed_by(draft: dict[str, object]) -> object:
    decision = draft.get("decision")
    return decision.get("decided_by") if isinstance(decision, dict) else None


def _holds(actor: AuthenticatedActor, capability: str, property_id: UUID) -> bool:
    return is_authorized(actor, AuthorizationRequirement(capability, str(property_id)))


def _binding(property_id: UUID, state: StateFilter | None) -> dict[str, str | None]:
    return {"collection": "financial-drafts", "property_id": str(property_id), "state": state}


def _decode_cursor(
    cursor: str | None, binding: dict[str, str | None]
) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        if not cursor.isascii() or len(cursor) > 1024:
            raise ValueError
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(value, dict) or set(value) != {*binding, "prepared_at", "id"}:
            raise ValueError
        if _cursor(value) != cursor or any(value[key] != binding[key] for key in binding):
            raise ValueError
        identity = value["id"]
        if not isinstance(identity, str) or str(UUID(identity)) != identity:
            raise ValueError
        if UUID(identity).int == 0:
            raise ValueError
        return _timestamp(value["prepared_at"]), UUID(identity)
    except (ValueError, TypeError, binascii.Error, UnicodeError, RecursionError) as exc:
        raise HTTPException(400) from exc


def _draft(value: object, property_id: UUID, draft_id: UUID | None = None) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or value.get("property_id") != str(property_id)
        or (draft_id is not None and value.get("draft_id") != str(draft_id))
    ):
        raise HTTPException(503)
    return cast(dict[str, object], value)


def _page(
    value: object, property_id: UUID, limit: int, binding: dict[str, str | None]
) -> tuple[list[dict[str, object]], str | None]:
    if not isinstance(value, dict) or set(value) != {"items"}:
        raise HTTPException(503)
    items = value["items"]
    if not isinstance(items, list) or len(items) > limit:
        raise HTTPException(503)
    drafts = [_draft(item, property_id) for item in items]
    if len(drafts) < limit:
        return drafts, None
    last = drafts[-1]
    prepared_at, identity = last.get("prepared_at"), last.get("draft_id")
    if not isinstance(prepared_at, str) or not isinstance(identity, str):
        raise HTTPException(503)
    cursor = _cursor({**binding, "prepared_at": prepared_at, "id": identity})
    try:
        _decode_cursor(cursor, binding)
    except HTTPException as exc:
        raise HTTPException(503) from exc
    return drafts, cursor


def _shown_to(actor: AuthenticatedActor, property_id: UUID, draft: dict[str, object]) -> bool:
    """A Reservation Deposit draft (it names the Customer) is shown and decided only with
    reservations.read, as on the Reservation's own draft routes (slice 11b review round 1)."""
    payload = draft.get("payload")
    variant = payload.get("variant") if isinstance(payload, dict) else None
    return variant not in RESERVATION_VARIANTS or _holds(
        actor, RESERVATION_READ_CAPABILITY, property_id
    )


def visible(
    actor: AuthenticatedActor, property_id: UUID, draft: dict[str, object]
) -> dict[str, object]:
    if not _shown_to(actor, property_id, draft):
        raise HTTPException(404)
    return draft


def create_financial_draft_router(
    resolver: ActorResolver, flow: FinancialDraftFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1", tags=["financial-drafts"], route_class=CreditRefundRequestRoute
    )

    def context(
        request: Request, property_id: UUID, capabilities: frozenset[str]
    ) -> AuthenticatedActor:
        actor = _actor(request, resolver)
        if request.method == "POST":
            _mutation(request, settings)
        # A Property the person cannot read drafts of is hidden, as for the other financial reads.
        if not any(_holds(actor, capability, property_id) for capability in capabilities):
            raise HTTPException(404)
        bind_financial_property(request, property_id)
        return actor

    def envelope(request: Request, result: object) -> dict[str, object]:
        return {"data": result, "meta": financial_metadata(request)}

    @router.get("/properties/{property_id}/financial-drafts")
    def list_drafts(
        property_id: Identity,
        request: Request,
        state: StateFilter | None = None,
        limit: PageLimit = 50,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        """Drafts the person may read, newest first; ``state`` keeps one state only."""
        _queries(request, {"state", "limit", "cursor"})
        actor = context(request, property_id, READ_CAPABILITIES)
        binding = _binding(property_id, state)
        after_prepared_at, after_id = _decode_cursor(cursor, binding)
        page = FinancialDraftPage(
            limit,
            None if state is None else FinancialDraftState(state),
            after_prepared_at,
            after_id,
        )
        result = _invoke(lambda: flow.list(property_id, actor=actor, page=page), query=True)
        drafts, next_cursor = _page(result, property_id, limit, binding)
        # The cursor follows the page as read, so a draft left out never shifts the next page.
        shown = [draft for draft in drafts if _shown_to(actor, property_id, draft)]
        return {
            **envelope(request, shown),
            "page": {"limit": limit, "next_cursor": next_cursor},
        }

    @router.get("/properties/{property_id}/financial-drafts/{draft_id}")
    def get_draft(property_id: Identity, draft_id: Identity, request: Request) -> dict[str, object]:
        _queries(request, set())
        actor = context(request, property_id, READ_CAPABILITIES)
        result = _invoke(lambda: flow.get(property_id, draft_id, actor=actor))
        return envelope(request, visible(actor, property_id, _draft(result, property_id, draft_id)))

    @router.post(
        "/properties/{property_id}/financial-drafts/{draft_id}/reject",
        dependencies=[Depends(_financial_json)],
    )
    def reject_draft(
        property_id: Identity,
        draft_id: Identity,
        body: ReversalInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Reject a waiting draft (financial.approve only). The draft id is the idempotency
        identity: the header is required as on every financial command but is not stored."""
        del idempotency_key
        _queries(request, set())
        actor = context(request, property_id, frozenset({FINANCIAL_APPROVE_CAPABILITY}))
        visible(
            actor,
            property_id,
            _draft(
                _invoke(lambda: flow.get(property_id, draft_id, actor=actor)),
                property_id,
                draft_id,
            ),
        )
        result = _invoke(lambda: flow.reject(property_id, draft_id, body.reason, actor=actor))
        return envelope(request, _draft(result, property_id, draft_id))

    @router.post(
        "/properties/{property_id}/financial-drafts/{draft_id}/withdraw",
        dependencies=[Depends(_financial_json)],
    )
    def withdraw_draft(
        property_id: Identity,
        draft_id: Identity,
        body: ReversalInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Withdraw a waiting draft: only its preparer, with the draft's prepare capability."""
        del idempotency_key
        _queries(request, set())
        actor = context(request, property_id, READ_CAPABILITIES)
        current = visible(
            actor,
            property_id,
            _draft(
                _invoke(lambda: flow.get(property_id, draft_id, actor=actor)),
                property_id,
                draft_id,
            ),
        )
        capability = current.get("prepare_capability")
        if not isinstance(capability, str) or capability not in PREPARE_CAPABILITIES:
            raise HTTPException(503)
        if not _holds(actor, capability, property_id) or current.get("prepared_by") != _actor_text(
            actor
        ):
            raise RefusedRequest(DRAFT_WITHDRAW_PREPARER_ONLY)

        def withdraw() -> dict[str, object]:
            try:
                return flow.withdraw(
                    property_id,
                    draft_id,
                    body.reason,
                    prepare_capability=capability,
                    actor=actor,
                )
            except FinancialDraftNotPreparerError as exc:
                # The database refuses anyone but the preparer (BR-AUTH-010).
                raise RefusedRequest(DRAFT_WITHDRAW_PREPARER_ONLY) from exc

        result = _invoke(withdraw)
        return envelope(request, _draft(result, property_id, draft_id))

    @router.post(
        "/properties/{property_id}/financial-drafts/{draft_id}/confirm",
        dependencies=[Depends(_financial_json)],
    )
    def confirm_draft(
        property_id: Identity,
        draft_id: Identity,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Confirm a waiting draft of any kind (financial.approve only) through its own
        confirm command, which checks every rule again. The draft id is the idempotency
        identity; the approver who confirmed a draft gets its first result again."""
        del idempotency_key
        _queries(request, set())
        actor = context(request, property_id, frozenset({FINANCIAL_APPROVE_CAPABILITY}))
        current = visible(
            actor,
            property_id,
            _draft(
                _invoke(lambda: flow.get(property_id, draft_id, actor=actor)),
                property_id,
                draft_id,
            ),
        )
        # Each confirm command replays only for the approver who confirmed the draft.
        state = current.get("state")
        if state in {"REJECTED", "WITHDRAWN"} or (
            state == "CONFIRMED" and _confirmed_by(current) != _actor_text(actor)
        ):
            raise RefusedRequest(DRAFT_ALREADY_DECIDED)
        try:
            result = _confirm_invoke(
                lambda: flow.confirm(property_id, current, actor=actor), current.get("kind")
            )
        except RefusedRequest as exc:
            # Decided by someone else after the read above: say so, not "cannot be confirmed".
            if exc.refusal in {DRAFT_CONFIRM_REFUSED, DRAFT_CONFIRM_NOT_AVAILABLE}:
                again = _invoke(lambda: flow.get(property_id, draft_id, actor=actor))
                if again.get("state") != "PENDING":
                    raise RefusedRequest(DRAFT_ALREADY_DECIDED) from exc
            raise
        # A failed read here answers 503; the same approver may repeat the confirm safely.
        after = _draft(
            _invoke(lambda: flow.get(property_id, draft_id, actor=actor)), property_id, draft_id
        )
        return envelope(request, {"draft": after, "result": _without_transaction_id(result)})

    return router
