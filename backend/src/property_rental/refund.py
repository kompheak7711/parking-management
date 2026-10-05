"""Explicit source-bounded Refund commands and exact, paginated history reads.

These service boundaries do not expose HTTP/UI, invent collection rights, or
change the original outbound event. All Refunds are USD-only, including KHR-origin
Payment/Credit sources; original KHR and conversion evidence remains audit provenance.
Qualified Deposit sources retain their separate eligibility checks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import set_json_loads

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.lock_retry import retry_lock_not_available


class RefundNotFoundError(LookupError):
    pass


class RefundAuthorizationError(PermissionError):
    pass


class RefundInvalidError(ValueError):
    pass


class RefundConflictError(RuntimeError):
    pass


class RefundIdempotencyKeyReused(RefundConflictError):
    pass


class RefundUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise RefundInvalidError("A non-nil UUID is required")


def _amount(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 9_000_000_000_000_000:
        raise RefundInvalidError("Refund amount must be positive bounded exact minor units")


def _text(value: str, limit: int) -> None:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= limit:
        raise RefundInvalidError("A normalized bounded value is required")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise RefundInvalidError("Text must be valid UTF-8") from exc
    if "\x00" in value:
        raise RefundInvalidError("Text must not contain a NUL")


def _instant(value: datetime) -> datetime:
    try:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An aware timestamp is required")
        return value.astimezone(UTC)
    except (ValueError, TypeError, OverflowError) as exc:
        raise RefundInvalidError("A finite timezone-aware timestamp is required") from exc


def _source(kind: str, identity: UUID) -> None:
    if kind not in ("PAYMENT", "CREDIT"):
        raise RefundInvalidError("Unsupported USD Refund source")
    _uuid(identity)


@dataclass(frozen=True, slots=True)
class CreateUsdRefundCommand:
    idempotency_key: UUID
    source_kind: str
    source_id: UUID
    amount_usd_cents: int
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _source(self.source_kind, self.source_id)
        _amount(self.amount_usd_cents)
        _text(self.reason, 1000)


# Refund command keys keep their earlier scope (Property, actor, Refund kind and key): the
# draft id is derived from them, so two people or two Properties may reuse one key.
REFUND_DRAFT_NAMESPACE: Final = UUID("6f0f5c8e-2b1a-4f8e-9d43-56a1d3b7c901")


def refund_draft_id(property_id: UUID, actor_id: UUID, variant: str, idempotency_key: UUID) -> UUID:
    """Stable draft id for one preparer's Refund command key in one Property."""
    return uuid5(
        REFUND_DRAFT_NAMESPACE, f"refund:{property_id}:{actor_id}:{variant}:{idempotency_key}"
    )


@dataclass(frozen=True, slots=True)
class RefundMethodChoice:
    """Configured Refund method and its reference note (BR-REFUND-014)."""

    refund_method_id: UUID
    reference_note: str

    def __post_init__(self) -> None:
        _uuid(self.refund_method_id)
        _text(self.reference_note, 500)


@dataclass(frozen=True, slots=True)
class SignerRecipient:
    """Another Lease Signer chosen in writing by all Signers (BR-REFUND-015)."""

    customer_id: UUID
    agreement: str

    def __post_init__(self) -> None:
        _uuid(self.customer_id)
        _text(self.agreement, 2000)


@dataclass(frozen=True, slots=True)
class CreatePetRefundCommand:
    idempotency_key: UUID
    deposit_id: UUID
    pet_refund_review_id: UUID
    amount_usd_cents: int
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _uuid(self.deposit_id)
        _uuid(self.pet_refund_review_id)
        _amount(self.amount_usd_cents)
        _text(self.reason, 1000)


@dataclass(frozen=True, slots=True)
class VerifyUsdRefundReturnCommand:
    idempotency_key: UUID
    returned_amount_minor: int
    returned_at: datetime
    return_method_reference: str
    evidence_reference: str
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _amount(self.returned_amount_minor)
        object.__setattr__(self, "returned_at", _instant(self.returned_at))
        _text(self.return_method_reference, 500)
        _text(self.evidence_reference, 500)
        _text(self.reason, 1000)


@dataclass(frozen=True, slots=True)
class ReverseRefundCorrectionCommand:
    idempotency_key: UUID
    evidence_reference: str
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _text(self.evidence_reference, 500)
        _text(self.reason, 1000)


@dataclass(frozen=True, slots=True)
class RefundPage:
    limit: int = 50
    after_at: datetime | None = None
    after_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise RefundInvalidError("Refund page size must be between 1 and 100")
        if (self.after_at is None) != (self.after_id is None):
            raise RefundInvalidError("Both Refund cursor fields are required")
        if self.after_at is not None and self.after_id is not None:
            object.__setattr__(self, "after_at", _instant(self.after_at))
            _uuid(self.after_id)

    def parameters(self) -> tuple[int, datetime | None, UUID | None]:
        page = RefundPage(self.limit, self.after_at, self.after_id)
        return page.limit, page.after_at, page.after_id


def _exact_refund_json(value: str | bytes) -> object:
    """Keep integer money exact and fractional exchange evidence as decimal text."""
    return json.loads(value, parse_float=str)


@dataclass(frozen=True, slots=True)
class RefundService:
    database_url: str
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise RefundAuthorizationError("Refund action is not authorized")
        try:
            identity = UUID(actor.actor_id)
            _uuid(identity)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RefundAuthorizationError("Refund actor identity is invalid") from exc
        return identity

    def _attempt(
        self, sql: str, parameters: tuple[object, ...], mutation: bool
    ) -> tuple[object, ...] | None:
        # Leaving the block rolls back and closes the transaction on any error.
        with psycopg.connect(
            self.financial_database_url if mutation else self.database_url,
            connect_timeout=3,
        ) as connection:
            # Local adapter only: do not change decoding for other services.
            set_json_loads(_exact_refund_json, connection)
            connection.execute("SET LOCAL lock_timeout='3000ms'")
            connection.execute("SET LOCAL statement_timeout='5000ms'")
            return connection.execute(sql, parameters).fetchone()

    def _query(
        self, sql: str, parameters: tuple[object, ...], *, mutation: bool = False
    ) -> dict[str, object]:
        try:
            # The same idempotent command is replayed after a NOWAIT refusal.
            row = retry_lock_not_available(lambda: self._attempt(sql, parameters, mutation))
        except psycopg.Error as exc:
            if exc.sqlstate in {"P5201", "P4501"}:
                raise RefundNotFoundError("Refund source or resource was not found") from exc
            if exc.sqlstate == "P5202":
                raise RefundInvalidError("Refund command is invalid") from exc
            if exc.sqlstate == "P5205":
                raise RefundIdempotencyKeyReused("Refund command key was reused") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise RefundAuthorizationError("Refund actor is not authorized") from exc
            # A new timeout/constraint failure cannot resolve an earlier lost reply.
            raise RefundUnavailableError(
                "Refund outcome unresolved; preserve and replay the original command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise RefundNotFoundError("Refund source or resource was not found")
        return cast(dict[str, object], row[0])

    def get(
        self,
        property_id: UUID,
        refund_id: UUID,
        *,
        actor: AuthenticatedActor,
        page: RefundPage | None = None,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "refunds.read")
        _uuid(refund_id)
        return self._query(
            "SELECT app.refund_resource(%s,%s,%s,%s,%s,%s)",
            (property_id, refund_id, actor_id, *(page or RefundPage()).parameters()),
        )

    def list(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        customer_id: UUID | None = None,
        page: RefundPage | None = None,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "refunds.read")
        if customer_id is not None:
            _uuid(customer_id)
        return self._query(
            "SELECT app.list_refunds(%s,%s,%s,%s,%s,%s)",
            (property_id, actor_id, customer_id, *(page or RefundPage()).parameters()),
        )

    def usd_source(
        self, property_id: UUID, source_kind: str, source_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "refunds.create")
        _source(source_kind, source_id)
        return self._query(
            "SELECT app.usd_refund_source(%s,%s,%s,%s)",
            (property_id, actor_id, source_kind, source_id),
        )

    def pet_source(
        self,
        property_id: UUID,
        deposit_id: UUID,
        pet_refund_review_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "refunds.create")
        _uuid(deposit_id)
        _uuid(pet_refund_review_id)
        return self._query(
            "SELECT app.pet_refund_source(%s,%s,%s,%s)",
            (property_id, actor_id, deposit_id, pet_refund_review_id),
        )

    def refund_methods(self, property_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        """List the configured Refund methods (BR-REFUND-014)."""
        _uuid(property_id)
        if not any(
            is_authorized(actor, AuthorizationRequirement(capability, str(property_id)))
            for capability in ("refunds.read", "refunds.create", "property.manage")
        ):
            raise RefundAuthorizationError("Refund method read is not authorized")
        try:
            actor_id = UUID(actor.actor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RefundAuthorizationError("Refund actor identity is invalid") from exc
        return self._query(
            "SELECT app.list_refund_methods(%s,%s)", (property_id, actor_id), mutation=False
        )

    def _draft_call(self, sql: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            row = retry_lock_not_available(lambda: self._attempt(sql, parameters, True))
        except psycopg.Error as exc:
            if exc.sqlstate in {"P5201", "P4501", "P0002"}:
                raise RefundNotFoundError("Refund source or draft was not found") from exc
            if exc.sqlstate == "P5202":
                raise RefundInvalidError("Refund command is invalid") from exc
            if exc.sqlstate == "P5205":
                raise RefundIdempotencyKeyReused("Refund command key was reused") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise RefundAuthorizationError("Refund actor is not authorized") from exc
            if exc.sqlstate == "55000" and exc.diag.message_primary == (
                "Financial draft is already decided"
            ):
                raise RefundConflictError("Refund draft is already decided") from exc
            if exc.sqlstate == "55000" and exc.diag.message_primary == (
                "A Deposit receipt reversal draft for this Deposit is waiting"
            ):
                # Owner answer 2 to Q-2026-10-05-23: the Refund draft stays pending.
                raise RefundConflictError(
                    "A Deposit receipt reversal draft for this Deposit is waiting"
                ) from exc
            raise RefundUnavailableError(
                "Refund outcome unresolved; preserve and replay the original command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise RefundNotFoundError("Refund source or resource was not found")
        return cast(dict[str, object], row[0])

    def record_usd_draft(
        self,
        property_id: UUID,
        command: CreateUsdRefundCommand,
        method: RefundMethodChoice,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a Credit or Payment Refund draft; it has no effect until confirmed."""
        actor_id = self._authorize(actor, property_id, "refunds.create")
        request = CreateUsdRefundCommand(
            command.idempotency_key,
            command.source_kind,
            command.source_id,
            command.amount_usd_cents,
            command.reason,
        )
        choice = RefundMethodChoice(method.refund_method_id, method.reference_note)
        return self._draft_call(
            "SELECT app.record_refund_draft(%s,%s,%s,'USD',%s,%s,NULL,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                refund_draft_id(property_id, actor_id, "USD", request.idempotency_key),
                request.source_kind,
                request.source_id,
                request.amount_usd_cents,
                request.reason,
                choice.refund_method_id,
                choice.reference_note,
                "refunds.create",
            ),
        )

    def record_pet_draft(
        self,
        property_id: UUID,
        command: CreatePetRefundCommand,
        method: RefundMethodChoice,
        *,
        actor: AuthenticatedActor,
        recipient: SignerRecipient | None = None,
    ) -> dict[str, object]:
        """Record a qualified Pet Deposit Refund draft; it has no effect until confirmed.

        Without ``recipient`` the Refund goes to the Primary Tenant; with it, to another Lease
        Signer named by the written agreement of all Signers (BR-REFUND-015).
        """
        actor_id = self._authorize(actor, property_id, "refunds.create")
        request = CreatePetRefundCommand(
            command.idempotency_key,
            command.deposit_id,
            command.pet_refund_review_id,
            command.amount_usd_cents,
            command.reason,
        )
        choice = RefundMethodChoice(method.refund_method_id, method.reference_note)
        parameters: tuple[object, ...] = (
            property_id,
            actor_id,
            refund_draft_id(property_id, actor_id, "PET", request.idempotency_key),
            request.deposit_id,
            request.pet_refund_review_id,
            request.amount_usd_cents,
            request.reason,
            choice.refund_method_id,
            choice.reference_note,
            "refunds.create",
        )
        if recipient is None:
            return self._draft_call(
                "SELECT app.record_refund_draft(%s,%s,%s,'PET',NULL,%s,%s,%s,%s,%s,%s,%s)",
                parameters,
            )
        signer = SignerRecipient(recipient.customer_id, recipient.agreement)
        return self._draft_call(
            "SELECT app.record_refund_draft(%s,%s,%s,'PET',NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (*parameters, signer.customer_id, signer.agreement),
        )

    def confirm_draft(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Create the Refund of a draft; only a financial.approve holder may confirm."""
        actor_id = self._authorize(actor, property_id, "financial.approve")
        _uuid(draft_id)
        return self._draft_call(
            "SELECT app.confirm_refund_draft(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, "financial.approve"),
        )

    def verify_usd_return(
        self,
        property_id: UUID,
        refund_id: UUID,
        command: VerifyUsdRefundReturnCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "refunds.correct")
        _uuid(refund_id)
        request = VerifyUsdRefundReturnCommand(
            command.idempotency_key,
            command.returned_amount_minor,
            command.returned_at,
            command.return_method_reference,
            command.evidence_reference,
            command.reason,
        )
        return self._query(
            "SELECT app.verify_usd_refund_return(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                refund_id,
                actor_id,
                request.idempotency_key,
                request.returned_amount_minor,
                request.returned_at,
                request.return_method_reference,
                request.evidence_reference,
                request.reason,
            ),
            mutation=True,
        )

    def reverse_correction(
        self,
        property_id: UUID,
        refund_id: UUID,
        correction_id: UUID,
        command: ReverseRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "refunds.corrections.reverse")
        _uuid(refund_id)
        _uuid(correction_id)
        request = ReverseRefundCorrectionCommand(
            command.idempotency_key, command.evidence_reference, command.reason
        )
        return self._query(
            "SELECT app.reverse_refund_correction(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                refund_id,
                correction_id,
                actor_id,
                request.idempotency_key,
                request.evidence_reference,
                request.reason,
            ),
            mutation=True,
        )
