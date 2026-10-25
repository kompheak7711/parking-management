"""Bounded late-payment review, Decision, Charge, and correction service."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast, overload
from uuid import UUID, uuid4

import psycopg
from psycopg import IsolationLevel

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

LATE_PAYMENT_REVIEW_CAPABILITY: Final = "late_payment.review"
LATE_PAYMENT_DECISION_CAPABILITY: Final = "late_payment.final_decision"
LATE_PAYMENT_CORRECTION_CAPABILITY: Final = "late_payment.charge_correction"
LATE_PAYMENT_CONNECT_TIMEOUT_SECONDS: Final = 3
LATE_PAYMENT_LOCK_TIMEOUT_MS: Final = 3_000
LATE_PAYMENT_QUERY_TIMEOUT_MS: Final = 5_000
MAX_USD_MINOR_UNITS: Final = 9_000_000_000_000_000
NIL_UUID: Final = UUID(int=0)


class DecisionOutcome(StrEnum):
    CONFIRMED_DEFAULT = "CONFIRMED_DEFAULT"
    REDUCED = "REDUCED"
    WAIVED = "WAIVED"


class CorrectionKind(StrEnum):
    REDUCTION = "REDUCTION"
    CHARGE_REVERSAL = "CHARGE_REVERSAL"
    REDUCTION_REVERSAL = "REDUCTION_REVERSAL"


class ReductionReason(StrEnum):
    """The three fixed reasons of DL-076 answer 4; the database stores their words."""

    WRONG_INVOICE = "WRONG_INVOICE"
    PAID_ON_TIME_RECORDED_LATE = "PAID_ON_TIME_RECORDED_LATE"
    OTHER_STAFF_MISTAKE = "OTHER_STAFF_MISTAKE"


class LatePaymentNotFoundError(LookupError):
    pass


class LatePaymentConflictError(RuntimeError):
    pass


class LatePaymentIdempotencyKeyReused(LatePaymentConflictError):
    pass


class LatePaymentApplicationReversalRequired(LatePaymentConflictError):
    pass


class LatePaymentInvalidError(ValueError):
    pass


class LatePaymentAuthorizationError(PermissionError):
    pass


class LatePaymentServiceUnavailableError(RuntimeError):
    pass


def _identity(value: UUID, field: str) -> None:
    if value == NIL_UUID:
        raise ValueError(f"{field} must not be the nil UUID")


def _normalized(value: str, field: str, *, maximum: int = 500) -> None:
    if not value.strip() or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be normalized, nonblank, and bounded")


# C0 and C1 control characters other than tab, line feed and carriage return (V1-056 slice
# 11g-2).
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


@dataclass(frozen=True, slots=True)
class FinalizeLatePaymentDecisionCommand:
    idempotency_key: UUID
    outcome: DecisionOutcome
    approved_amount_usd_cents: int
    reason: str

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        if not isinstance(self.outcome, DecisionOutcome):
            raise ValueError("outcome is invalid")
        if (
            type(self.approved_amount_usd_cents) is not int
            or not 0 <= self.approved_amount_usd_cents <= MAX_USD_MINOR_UNITS
        ):
            raise ValueError("approved_amount_usd_cents must be bounded USD minor units")
        _normalized(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class CorrectLatePaymentChargeCommand:
    idempotency_key: UUID
    kind: CorrectionKind
    reason: str
    amount_usd_cents: int | None = None
    reverses_correction_id: UUID | None = None

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        if not isinstance(self.kind, CorrectionKind):
            raise ValueError("kind is invalid")
        _normalized(self.reason, "reason")
        if self.kind is CorrectionKind.REDUCTION:
            if (
                type(self.amount_usd_cents) is not int
                or not 1 <= self.amount_usd_cents <= MAX_USD_MINOR_UNITS
                or self.reverses_correction_id is not None
            ):
                raise ValueError("REDUCTION requires one bounded positive USD amount")
        elif self.kind is CorrectionKind.CHARGE_REVERSAL:
            if self.amount_usd_cents is not None or self.reverses_correction_id is not None:
                raise ValueError("CHARGE_REVERSAL derives its amount")
        else:
            if self.amount_usd_cents is not None or self.reverses_correction_id is None:
                raise ValueError("REDUCTION_REVERSAL requires its source correction")
            _identity(self.reverses_correction_id, "reverses_correction_id")


@dataclass(frozen=True, slots=True)
class ReduceLatePaymentChargeCommand:
    """DL-076 answer 4: the new, lower amount (0 waives the Charge), one fixed reason and what
    happened."""

    idempotency_key: UUID
    new_amount_usd_cents: int
    reason: ReductionReason
    what_happened: str

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        if (
            type(self.new_amount_usd_cents) is not int
            or not 0 <= self.new_amount_usd_cents <= MAX_USD_MINOR_UNITS
        ):
            raise ValueError("new_amount_usd_cents must be bounded USD minor units")
        if not isinstance(self.reason, ReductionReason):
            raise ValueError("reason is invalid")
        _normalized(self.what_happened, "what_happened")
        if CONTROL_CHARACTERS.search(self.what_happened):
            raise ValueError("what_happened must not hold control characters")
        try:
            self.what_happened.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("what_happened must be valid text") from exc


def late_payment_request_digest(
    *, action: str, property_id: UUID, target_id: UUID, payload: dict[str, object]
) -> str:
    """Return a stable digest containing only canonical client intent."""
    serialized = json.dumps(
        {
            "action": action,
            "payload": payload,
            "property_id": str(property_id),
            "target_id": str(target_id),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class LatePaymentCommandResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class PostgresLatePaymentService:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _bound_query(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        connection.execute(
            "SELECT pg_catalog.set_config('lock_timeout',%s,true)",
            (str(LATE_PAYMENT_LOCK_TIMEOUT_MS),),
        )
        connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout',%s,true)",
            (str(LATE_PAYMENT_QUERY_TIMEOUT_MS),),
        )

    @staticmethod
    def _actor_id(actor: AuthenticatedActor) -> UUID:
        try:
            value = UUID(actor.actor_id)
        except ValueError as exc:
            raise LatePaymentAuthorizationError("Late-payment actor identity is invalid") from exc
        _identity(value, "actor_id")
        return value

    @staticmethod
    def _authorize(
        actor: AuthenticatedActor,
        property_id: UUID,
        capability: str,
        *,
        hide: bool = False,
    ) -> None:
        if is_authorized(
            actor,
            AuthorizationRequirement(capability=capability, property_id=str(property_id)),
        ):
            return
        if hide:
            raise LatePaymentNotFoundError("Late-payment resource was not found")
        raise LatePaymentAuthorizationError("Late-payment capability is not authorized")

    @staticmethod
    def _resource(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise LatePaymentServiceUnavailableError("Late-payment snapshot is unavailable")
        return cast(dict[str, object], value)

    @staticmethod
    def _map_error(exc: psycopg.Error) -> Exception:
        if exc.sqlstate in {"P4601", "P0002"}:
            return LatePaymentNotFoundError("Late-payment resource was not found")
        if exc.sqlstate == "P4605":
            return LatePaymentIdempotencyKeyReused("Late-payment idempotency key was reused")
        if exc.sqlstate == "P4606":
            return LatePaymentAuthorizationError("Late-payment actor is not active")
        if exc.sqlstate == "P4608":
            return LatePaymentApplicationReversalRequired(
                "Active applications must be reversed explicitly"
            )
        # Only the explicit business conflict is raised after receipt lookup.
        # Generic database failures can occur while acquiring the Property/actor
        # or advisory locks, reading a receipt, or committing. Current terminal
        # state cannot prove that this exact request has no successful receipt.
        # P5S01 (a closed Final Settlement, V1-056 sub-slice 8e-1) is raised by the insert,
        # which also comes after the receipt lookup.
        if exc.sqlstate in {"P4603", "P5S01"}:
            return LatePaymentConflictError("Late-payment command conflicted")
        if exc.sqlstate == "P4602":
            return LatePaymentInvalidError("Late-payment command is invalid")
        return LatePaymentServiceUnavailableError("Late-payment persistence is unavailable")

    def _read_connection(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(
            self.database_url,
            connect_timeout=LATE_PAYMENT_CONNECT_TIMEOUT_SECONDS,
        )

    def _command_connection(self) -> psycopg.Connection[tuple[object, ...]]:
        if self.financial_database_url is None:
            raise LatePaymentServiceUnavailableError(
                "Late-payment command persistence is unavailable"
            )
        connection = psycopg.connect(
            self.financial_database_url,
            connect_timeout=LATE_PAYMENT_CONNECT_TIMEOUT_SECONDS,
        )
        connection.isolation_level = IsolationLevel.READ_COMMITTED
        return connection

    def _read(self, query: str, target_id: UUID) -> dict[str, object]:
        if target_id == NIL_UUID:
            raise LatePaymentNotFoundError("Late-payment resource was not found")
        try:
            with self._read_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(query, (target_id,)).fetchone()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None or row[0] is None:
            raise LatePaymentNotFoundError("Late-payment resource was not found")
        return self._resource(row[0])

    def _property(self, query: str, target_id: UUID) -> UUID:
        if target_id == NIL_UUID:
            raise LatePaymentNotFoundError("Late-payment resource was not found")
        try:
            with self._read_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(query, (target_id,)).fetchone()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None or row[0] is None:
            raise LatePaymentNotFoundError("Late-payment resource was not found")
        return UUID(str(row[0]))

    def property_for_invoice(self, invoice_id: UUID) -> UUID:
        return self._property("SELECT app.invoice_property_id(%s)", invoice_id)

    def property_for_charge(self, charge_id: UUID) -> UUID:
        return self._property("SELECT app.late_payment_charge_property_id(%s)", charge_id)

    def review(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        resource = self._read("SELECT app.late_payment_review_snapshot(%s)", invoice_id)
        self._authorize(
            actor,
            UUID(str(resource["property_id"])),
            LATE_PAYMENT_REVIEW_CAPABILITY,
            hide=True,
        )
        return resource

    def get_decision(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        resource = self._read(
            "SELECT app.late_payment_decision_snapshot_for_invoice(%s)", invoice_id
        )
        self._authorize(
            actor,
            UUID(str(resource["property_id"])),
            LATE_PAYMENT_REVIEW_CAPABILITY,
            hide=True,
        )
        return resource

    def get_charge(self, charge_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        resource = self._read("SELECT app.late_payment_charge_snapshot(%s)", charge_id)
        self._authorize(
            actor,
            UUID(str(resource["property_id"])),
            LATE_PAYMENT_REVIEW_CAPABILITY,
            hide=True,
        )
        return resource

    def decision_conflict_state(
        self, invoice_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        try:
            resource = self._read(
                "SELECT app.late_payment_decision_snapshot_for_invoice(%s)", invoice_id
            )
        except LatePaymentNotFoundError:
            resource = self._read("SELECT app.late_payment_review_snapshot(%s)", invoice_id)
        self._authorize(
            actor,
            UUID(str(resource["property_id"])),
            LATE_PAYMENT_DECISION_CAPABILITY,
            hide=True,
        )
        return resource

    def charge_conflict_state(
        self, charge_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        resource = self._read("SELECT app.late_payment_charge_snapshot(%s)", charge_id)
        self._authorize(
            actor,
            UUID(str(resource["property_id"])),
            LATE_PAYMENT_CORRECTION_CAPABILITY,
            hide=True,
        )
        return resource

    def _execute(
        self,
        query: str,
        parameters: tuple[object, ...],
        *,
        lock_conflicts: bool = False,
    ) -> LatePaymentCommandResponse:
        try:
            with self._command_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(query, parameters).fetchone()
        except (LatePaymentServiceUnavailableError, LatePaymentAuthorizationError):
            raise
        except psycopg.Error as exc:
            # V1-056 slice 11g-2: on the reduction route a detected deadlock (or a
            # serialization failure, not expected at READ COMMITTED) answers as a conflict. The
            # transaction was rolled back, so nothing was written; the client reads the Charge
            # and retries with the same Idempotency-Key, which replays any receipt a concurrent
            # duplicate wrote.
            if lock_conflicts and exc.sqlstate in {"40P01", "40001"}:
                raise LatePaymentConflictError("Late-payment command conflicted") from exc
            raise self._map_error(exc) from exc
        if row is None:
            raise LatePaymentServiceUnavailableError("Late-payment command returned no result")
        response = self._resource(row[0])
        status_code = response.get("status_code")
        body = response.get("body")
        if type(status_code) is not int or not isinstance(body, dict):
            raise LatePaymentServiceUnavailableError("Late-payment response is unavailable")
        return LatePaymentCommandResponse(status_code, cast(dict[str, object], body))

    @overload
    def finalize_decision(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: FinalizeLatePaymentDecisionCommand,
        *,
        actor: AuthenticatedActor,
        request_id: None = None,
    ) -> dict[str, object]: ...

    @overload
    def finalize_decision(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: FinalizeLatePaymentDecisionCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LatePaymentCommandResponse: ...

    def finalize_decision(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: FinalizeLatePaymentDecisionCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str | None = None,
    ) -> dict[str, object] | LatePaymentCommandResponse:
        self._authorize(actor, property_id, LATE_PAYMENT_DECISION_CAPABILITY)
        digest = late_payment_request_digest(
            action="decision",
            property_id=property_id,
            target_id=invoice_id,
            payload={
                "approved_amount": {
                    "currency": "USD",
                    "minor_units": command.approved_amount_usd_cents,
                },
                "outcome": command.outcome.value,
                "reason": command.reason,
            },
        )
        response = self._execute(
            "SELECT app.finalize_late_payment_decision(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                invoice_id,
                self._actor_id(actor),
                command.idempotency_key,
                digest,
                request_id or "late-payment-service",
                command.outcome.value,
                command.approved_amount_usd_cents,
                command.reason,
                uuid4(),
                uuid4(),
                uuid4(),
            ),
        )
        if request_id is None:
            return self._resource(response.body.get("data"))
        return response

    @overload
    def correct_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: CorrectLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: None = None,
    ) -> dict[str, object]: ...

    @overload
    def correct_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: CorrectLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LatePaymentCommandResponse: ...

    def correct_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: CorrectLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str | None = None,
    ) -> dict[str, object] | LatePaymentCommandResponse:
        self._authorize(actor, property_id, LATE_PAYMENT_CORRECTION_CAPABILITY)
        digest = late_payment_request_digest(
            action="correction",
            property_id=property_id,
            target_id=charge_id,
            payload={
                "amount": (
                    None
                    if command.amount_usd_cents is None
                    else {
                        "currency": "USD",
                        "minor_units": command.amount_usd_cents,
                    }
                ),
                "kind": command.kind.value,
                "reason": command.reason,
                "reverses_correction_id": (
                    str(command.reverses_correction_id)
                    if command.reverses_correction_id is not None
                    else None
                ),
            },
        )
        response = self._execute(
            "SELECT app.correct_late_payment_charge(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                charge_id,
                self._actor_id(actor),
                command.idempotency_key,
                digest,
                request_id or "late-payment-service",
                command.kind.value,
                command.amount_usd_cents,
                command.reverses_correction_id,
                command.reason,
                uuid4(),
                uuid4(),
            ),
        )
        if request_id is None:
            return self._resource(response.body.get("data"))
        return response

    @overload
    def reduce_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: ReduceLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: None = None,
    ) -> dict[str, object]: ...

    @overload
    def reduce_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: ReduceLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LatePaymentCommandResponse: ...

    def reduce_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: ReduceLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str | None = None,
    ) -> dict[str, object] | LatePaymentCommandResponse:
        """V1-056 slice 11g-2: reduce or waive the Charge; paid value above the new amount becomes
        Customer Credit (DL-076 answer 4 and reading (d))."""
        self._authorize(actor, property_id, LATE_PAYMENT_CORRECTION_CAPABILITY)
        digest = late_payment_request_digest(
            action="reduction",
            property_id=property_id,
            target_id=charge_id,
            payload={
                "new_amount": {"currency": "USD", "minor_units": command.new_amount_usd_cents},
                "reason": command.reason.value,
                "what_happened": command.what_happened,
            },
        )
        response = self._execute(
            "SELECT app.reduce_late_payment_charge(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                charge_id,
                self._actor_id(actor),
                command.idempotency_key,
                digest,
                request_id or "late-payment-service",
                command.new_amount_usd_cents,
                command.reason.value,
                command.what_happened,
                uuid4(),
                uuid4(),
            ),
            lock_conflicts=True,
        )
        if request_id is None:
            return self._resource(response.body.get("data"))
        return response
