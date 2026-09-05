"""Explicit Payment allocation services; proposals never authorize or move money."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

MAX_AMOUNT = 9_000_000_000_000_000
MAX_SNAPSHOT = 9_223_372_036_854_775_807
NIL_UUID = UUID(int=0)


class AllocationNotFoundError(LookupError):
    pass


class AllocationAuthorizationError(PermissionError):
    pass


class AllocationInvalidError(ValueError):
    pass


class AllocationConflictError(RuntimeError):
    pass


class AllocationIdempotencyKeyReused(AllocationConflictError):
    pass


class AllocationUnavailableError(RuntimeError):
    """Outcome may be unknown; retain and replay the exact command identity."""


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value == NIL_UUID:
        raise AllocationInvalidError("A non-nil UUID is required")


def _reason(value: str) -> None:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 1000:
        raise AllocationInvalidError("A normalized, bounded reason is required")


def _exact_json(value: object) -> str:
    def validate(item: object, field: str | None = None) -> None:
        if item is None or isinstance(item, str):
            return
        if type(item) is int:
            limit = MAX_SNAPSHOT if field == "outstanding_usd_cents" else MAX_AMOUNT
            if abs(item) > limit:
                raise AllocationInvalidError("Integer outside the money range")
            return
        if isinstance(item, list):
            for child in item:
                validate(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for key, child in item.items():
                validate(child, key)
            return
        raise AllocationInvalidError("Intent must use exact integers, strings, arrays and objects")

    try:
        validate(value)
        result = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise AllocationInvalidError("Allocation intent is invalid") from exc
    if len(result.encode()) > 250_000:
        raise AllocationInvalidError("Allocation intent is too large")
    return result


@dataclass(frozen=True, slots=True)
class PostAllocationsCommand:
    idempotency_key: UUID
    intent: dict[str, object]

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _exact_json(self.intent)
        if self.intent.get("mode") == "PROPOSAL":
            if set(self.intent) != {"mode", "proposal"}:
                raise AllocationInvalidError("Proposal confirmation has unexpected fields")
        elif self.intent.get("mode") == "DESIGNATED":
            if set(self.intent) != {"mode", "targets", "designation_reference"}:
                raise AllocationInvalidError("Designation has unexpected fields")
            reference = self.intent["designation_reference"]
            if not isinstance(reference, str) or reference != reference.strip():
                raise AllocationInvalidError("Designation reference is invalid")
            if not 1 <= len(reference) <= 500:
                raise AllocationInvalidError("Designation reference is required and bounded")
        elif self.intent.get("mode") == "DIRECT_CHARGE":
            if set(self.intent) != {"mode", "late_payment_charge_id", "amount_usd_cents"}:
                raise AllocationInvalidError("Direct Charge intent has unexpected fields")
            amount = self.intent["amount_usd_cents"]
            if type(amount) is not int or not 1 <= amount <= MAX_AMOUNT:
                raise AllocationInvalidError("Direct Charge amount must be positive exact cents")
            try:
                _uuid(UUID(str(self.intent["late_payment_charge_id"])))
            except ValueError as exc:
                raise AllocationInvalidError("Direct Charge identity is invalid") from exc
        else:
            raise AllocationInvalidError("Explicit proposal, designation or direct Charge required")


@dataclass(frozen=True, slots=True)
class ReverseAllocationCommand:
    idempotency_key: UUID
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _reason(self.reason)


@dataclass(frozen=True, slots=True)
class ReversePaymentCommand:
    idempotency_key: UUID
    reason: str
    expected_status: str = "RECEIVED"

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _reason(self.reason)
        if self.expected_status != "RECEIVED":
            raise AllocationInvalidError("Payment reversal requires expected RECEIVED state")


@dataclass(frozen=True, slots=True)
class PaymentAllocationService:
    database_url: str
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise AllocationAuthorizationError("Payment capability is not authorized")
        try:
            actor_id = UUID(actor.actor_id)
            _uuid(actor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise AllocationAuthorizationError("Payment actor identity is invalid") from exc
        return actor_id

    def _query(
        self, query: str, parameters: tuple[object, ...], *, mutation: bool
    ) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url if mutation else self.database_url,
                connect_timeout=3,
            ) as connection:
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"P4901", "P0002"}:
                raise AllocationNotFoundError("Payment resource was not found") from exc
            if exc.sqlstate == "P4905":
                raise AllocationIdempotencyKeyReused("Payment idempotency key was reused") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise AllocationAuthorizationError("Payment actor is not authorized") from exc
            if exc.sqlstate == "P4904":
                raise AllocationConflictError(
                    "Payment state changed; inspect the current state"
                ) from exc
            if exc.sqlstate == "P4902":
                raise AllocationInvalidError("Payment command is invalid") from exc
            # Serialization, timeout, connection and deferred-constraint failures
            # cannot prove that an earlier transmission of this key did not commit.
            raise AllocationUnavailableError(
                "Payment outcome unresolved; replay the same command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise AllocationNotFoundError("Payment resource was not found")
        return cast(dict[str, object], row[0])

    def proposal(
        self, property_id: UUID, payment_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self._authorize(actor, property_id, "payments.allocate")
        _uuid(payment_id)
        return self._query(
            "SELECT app.payment_allocation_proposal(%s,%s,clock_timestamp(),%s)",
            (property_id, payment_id, uuid4()),
            mutation=False,
        )

    def post(
        self,
        property_id: UUID,
        payment_id: UUID,
        command: PostAllocationsCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "payments.allocate")
        _uuid(payment_id)
        # Capture a single immutable serialization for both digest and SQL payload.
        command = PostAllocationsCommand(command.idempotency_key, command.intent)
        encoded = _exact_json(command.intent)
        digest = self._digest("POST", property_id, payment_id, encoded)
        return self._query(
            "SELECT app.post_payment_allocations(%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                payment_id,
                actor_id,
                command.idempotency_key,
                digest,
                Jsonb(json.loads(encoded)),
            ),
            mutation=True,
        )

    def reverse_allocation(
        self,
        property_id: UUID,
        allocation_id: UUID,
        command: ReverseAllocationCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "payments.allocate")
        _uuid(allocation_id)
        digest = self._digest(
            "REVERSE_ALLOCATION",
            property_id,
            allocation_id,
            _exact_json({"reason": command.reason}),
        )
        return self._query(
            "SELECT app.reverse_payment_allocation_command(%s,%s,%s,%s,%s,%s)",
            (property_id, allocation_id, actor_id, command.idempotency_key, digest, command.reason),
            mutation=True,
        )

    def reverse_payment(
        self,
        property_id: UUID,
        payment_id: UUID,
        command: ReversePaymentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "payments.reverse")
        _uuid(payment_id)
        digest = self._digest(
            "REVERSE_PAYMENT",
            property_id,
            payment_id,
            _exact_json({"reason": command.reason, "expected_status": command.expected_status}),
        )
        return self._query(
            "SELECT app.reverse_payment_command(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                payment_id,
                actor_id,
                command.idempotency_key,
                digest,
                command.expected_status,
                command.reason,
            ),
            mutation=True,
        )

    @staticmethod
    def _digest(action: str, property_id: UUID, target_id: UUID, payload: str) -> str:
        return hashlib.sha256(f"{action}:{property_id}:{target_id}:{payload}".encode()).hexdigest()
