"""Explicit payer-authorized Credit recognition and permanent reversal services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized


class CreditNotFoundError(LookupError):
    pass


class CreditAuthorizationError(PermissionError):
    pass


class CreditInvalidError(ValueError):
    pass


class CreditConflictError(RuntimeError):
    pass


class CreditIdempotencyKeyReused(CreditConflictError):
    pass


class CreditUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise CreditInvalidError("A non-nil UUID is required")


def _text(value: str, limit: int) -> None:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= limit:
        raise CreditInvalidError("A normalized bounded value is required")


@dataclass(frozen=True, slots=True)
class RecognizeCreditCommand:
    idempotency_key: UUID
    amount_usd_cents: int
    payer_authorization_reference: str
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        if (
            type(self.amount_usd_cents) is not int
            or not 1 <= self.amount_usd_cents <= 9_000_000_000_000_000
        ):
            raise CreditInvalidError("Credit amount must be positive bounded exact USD cents")
        _text(self.payer_authorization_reference, 500)
        _text(self.reason, 1000)


@dataclass(frozen=True, slots=True)
class ReverseCreditCommand:
    idempotency_key: UUID
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _text(self.reason, 1000)


def _amount(value: object) -> None:
    if type(value) is not int or not 1 <= value <= 9_000_000_000_000_000:
        raise CreditInvalidError("Credit amount must be positive bounded exact USD cents")


def _target_uuid(value: object) -> None:
    try:
        if not isinstance(value, str):
            raise ValueError("UUID text required")
        _uuid(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CreditInvalidError("Credit target UUID is invalid") from exc


def _credit_intent_json(intent: dict[str, object]) -> str:
    def validate(value: object, depth: int = 0, field: str | None = None) -> None:
        if depth > 24:
            raise CreditInvalidError("Credit intent nesting exceeds bound")
        if value is None or isinstance(value, str):
            return
        if type(value) is int:
            limit = (
                9_223_372_036_854_775_807
                if field == "outstanding_usd_cents"
                else 9_000_000_000_000_000
            )
            if abs(value) > limit:
                raise CreditInvalidError("Credit intent integer exceeds bound")
            return
        if isinstance(value, list):
            for child in value:
                validate(child, depth + 1)
            return
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            for key, child in value.items():
                validate(child, depth + 1, key)
            return
        raise CreditInvalidError(
            "Credit intent requires exact integers, strings, objects or arrays"
        )

    try:
        validate(intent)
        encoded = json.dumps(
            intent, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
        )
        if len(encoded.encode()) > 250_000:
            raise CreditInvalidError("Credit intent exceeds bounded envelope")
        if not isinstance(intent, dict):
            raise CreditInvalidError("Credit intent must be an object")
        mode = intent.get("mode")
        if mode == "PROPOSAL":
            proposal = intent.get("proposal")
            if set(intent) != {"mode", "proposal"} or not isinstance(proposal, dict):
                raise CreditInvalidError("Credit proposal confirmation is invalid")
            _target_uuid(proposal.get("invoice_id"))
            _amount(proposal.get("amount_usd_cents"))
        elif mode in {"DESIGNATED", "DIRECT_CHARGE"}:
            target = "invoice_id" if "invoice_id" in intent else "late_payment_charge_id"
            required = {"mode", target, "amount_usd_cents"}
            if mode == "DESIGNATED":
                required.add("designation_reference")
                _text(cast(str, intent.get("designation_reference")), 500)
                if target == "invoice_id":
                    required.add("details")
            elif target != "late_payment_charge_id":
                raise CreditInvalidError("Direct Credit application requires a Charge")
            if set(intent) != required:
                raise CreditInvalidError("Credit application has unexpected or missing fields")
            _target_uuid(intent[target])
            _amount(intent["amount_usd_cents"])
            if target == "invoice_id":
                details = intent.get("details")
                if not isinstance(details, list) or not 1 <= len(details) <= 500:
                    raise CreditInvalidError("Credit Invoice details are required and bounded")
                for detail in details:
                    if not isinstance(detail, dict) or set(detail) != {
                        "invoice_line_id",
                        "amount_usd_cents",
                    }:
                        raise CreditInvalidError("Credit Invoice detail has unexpected fields")
                    _target_uuid(detail["invoice_line_id"])
                    _amount(detail["amount_usd_cents"])
        else:
            raise CreditInvalidError("Credit application mode is invalid")
    except (RecursionError, UnicodeError, TypeError, ValueError) as exc:
        raise CreditInvalidError("Credit application intent is invalid") from exc
    return encoded


@dataclass(frozen=True, slots=True, init=False)
class ApplyCreditCommand:
    idempotency_key: UUID
    _intent_json: str

    def __init__(self, idempotency_key: UUID, intent: dict[str, object]) -> None:
        _uuid(idempotency_key)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "_intent_json", _credit_intent_json(intent))

    @property
    def intent(self) -> dict[str, object]:
        """Return a detached copy, never the command's stored transmission intent."""
        return cast(dict[str, object], json.loads(self._intent_json))


@dataclass(frozen=True, slots=True)
class ReverseCreditApplicationCommand:
    idempotency_key: UUID
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _text(self.reason, 1000)


@dataclass(frozen=True, slots=True)
class CustomerCreditService:
    database_url: str
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise CreditAuthorizationError("Credit action is not authorized")
        try:
            identity = UUID(actor.actor_id)
            _uuid(identity)
        except (ValueError, TypeError, AttributeError) as exc:
            raise CreditAuthorizationError("Credit actor identity is invalid") from exc
        return identity

    def _query(
        self, sql: str, parameters: tuple[object, ...], *, mutation: bool = False
    ) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url if mutation else self.database_url,
                connect_timeout=3,
            ) as connection:
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"P5101", "P4501"}:
                raise CreditNotFoundError("Credit source or resource was not found") from exc
            if exc.sqlstate == "P5102":
                raise CreditInvalidError("Credit command is invalid") from exc
            if exc.sqlstate == "P5105":
                raise CreditIdempotencyKeyReused("Credit command key was reused") from exc
            if exc.sqlstate == "P5104":
                raise CreditConflictError(
                    "Credit proposal changed; request a fresh proposal"
                ) from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise CreditAuthorizationError("Credit actor is not authorized") from exc
            # A serialization/timeout/deferred constraint failure does not prove
            # an earlier transmission with the same key did not commit.
            raise CreditUnavailableError(
                "Credit outcome unresolved; preserve and replay the original command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise CreditNotFoundError("Credit source or resource was not found")
        return cast(dict[str, object], row[0])

    def get(
        self, property_id: UUID, credit_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.read")
        _uuid(credit_id)
        return self._query(
            "SELECT app.credit_resource(%s,%s,%s)", (property_id, credit_id, actor_id)
        )

    def recognize(
        self,
        property_id: UUID,
        payment_id: UUID,
        command: RecognizeCreditCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.recognize")
        _uuid(payment_id)
        # Revalidate the immutable scalar envelope at transmission.
        request = RecognizeCreditCommand(
            command.idempotency_key,
            command.amount_usd_cents,
            command.payer_authorization_reference,
            command.reason,
        )
        return self._query(
            "SELECT app.recognize_customer_credit(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                payment_id,
                actor_id,
                request.idempotency_key,
                request.amount_usd_cents,
                request.payer_authorization_reference,
                request.reason,
            ),
            mutation=True,
        )

    def reverse(
        self,
        property_id: UUID,
        credit_id: UUID,
        command: ReverseCreditCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.reverse")
        _uuid(credit_id)
        request = ReverseCreditCommand(command.idempotency_key, command.reason)
        return self._query(
            "SELECT app.reverse_customer_credit(%s,%s,%s,%s,%s)",
            (property_id, credit_id, actor_id, request.idempotency_key, request.reason),
            mutation=True,
        )

    def application_proposal(
        self,
        property_id: UUID,
        credit_id: UUID,
        invoice_id: UUID,
        amount_usd_cents: int,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.apply")
        _uuid(credit_id)
        _uuid(invoice_id)
        _amount(amount_usd_cents)
        return self._query(
            "SELECT app.credit_application_proposal_for_actor(%s,%s,%s,%s,%s)",
            (property_id, credit_id, invoice_id, amount_usd_cents, actor_id),
        )

    def apply(
        self,
        property_id: UUID,
        credit_id: UUID,
        command: ApplyCreditCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.apply")
        _uuid(credit_id)
        request = ApplyCreditCommand(command.idempotency_key, command.intent)
        return self._query(
            "SELECT app.post_credit_application(%s,%s,%s,%s,%s)",
            (property_id, credit_id, actor_id, request.idempotency_key, Jsonb(request.intent)),
            mutation=True,
        )

    def get_application(
        self,
        property_id: UUID,
        application_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.read")
        _uuid(application_id)
        return self._query(
            "SELECT app.credit_application_resource(%s,%s,%s)",
            (property_id, application_id, actor_id),
        )

    def reverse_application(
        self,
        property_id: UUID,
        application_id: UUID,
        command: ReverseCreditApplicationCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.applications.reverse")
        _uuid(application_id)
        request = ReverseCreditApplicationCommand(command.idempotency_key, command.reason)
        return self._query(
            "SELECT app.reverse_credit_application(%s,%s,%s,%s,%s)",
            (property_id, application_id, actor_id, request.idempotency_key, request.reason),
            mutation=True,
        )
