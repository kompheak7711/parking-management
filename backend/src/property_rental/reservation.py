"""Transactional Reservation lifecycle services over the protected PostgreSQL boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Final, NoReturn, cast
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb, set_json_loads

from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.payment_confirmation import _exact_json

NIL_UUID: Final = UUID(int=0)
RESERVATION_CANCEL_CAPABILITY: Final = "reservations.cancel"
DEPOSIT_DISPOSITION_CAPABILITY: Final = "reservation_deposits.dispose"
DEPOSIT_REFUND_CAPABILITY: Final = "reservation_deposits.refund"
DEPOSIT_OUTCOME_CORRECT_CAPABILITY: Final = "reservation_deposits.correct"


class ReservationStatus(StrEnum):
    """The complete approved Reservation status vocabulary."""

    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class CancellationResponsibility(StrEnum):
    """The approved responsibility classifications for a cancellation."""

    CUSTOMER = "CUSTOMER"
    PROPERTY = "PROPERTY"


class DepositOutcomeState(StrEnum):
    """The immutable classified outcome of received Reservation Deposit value."""

    PENDING_V1_031 = "PENDING_V1_031"
    # Cancelled or expired; the Deposit is held until its draft is confirmed (V1-056 slice 3b).
    AWAITING_DECISION = "AWAITING_DECISION"
    NON_REFUNDABLE_DISPOSITION = "NON_REFUNDABLE_DISPOSITION"
    REFUND = "REFUND"


class ReservationNotFoundError(LookupError):
    """Raised when a Reservation is outside the Property scope or absent."""


class ReservationVersionConflictError(RuntimeError):
    """Raised when a lifecycle command targets a stale Reservation version."""


class ReservationCommandConflictError(RuntimeError):
    """Raised for exclusivity or idempotency conflicts."""


class ReservationIdempotencyKeyReused(ReservationCommandConflictError):
    """Raised when one idempotency key is reused for different input (API-016)."""


class ReservationCommandInvalidError(ValueError):
    """Raised when a command violates a Reservation lifecycle invariant."""


class ReservationAuthorizationError(PermissionError):
    """Raised before persistence when trusted capability evidence is absent."""


class ReservationServiceUnavailableError(RuntimeError):
    """Raised when Reservation persistence cannot be reached."""


class ReservationDepositDraftRequired(RuntimeError):
    """A Reservation Deposit outcome or its correction is a draft now (BR-AUTH-010)."""


def _json_value(value: object) -> object:
    if isinstance(value, (date, datetime, UUID, StrEnum)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def reservation_request_digest(
    action: str,
    command: (
        ReservationCreateCommand
        | ReservationExtendCommand
        | ReservationCancelCommand
        | ReservationExpireCommand
    ),
) -> str:
    """Return a stable digest binding one idempotent command to all inputs."""
    if not action.startswith("reservation."):
        raise ValueError("Reservation action is invalid")
    payload = {
        "action": action,
        "command": _json_value(asdict(command)),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _require_identity(value: UUID, field: str) -> None:
    if value == NIL_UUID:
        raise ValueError(f"{field} must not be the nil UUID")


def _require_nonblank(value: str, field: str) -> None:
    if not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be normalized and nonblank")


@dataclass(frozen=True, slots=True)
class ReservationCreateCommand:
    """All deterministic inputs for one Reservation activation bundle."""

    idempotency_key: UUID
    reservation_id: UUID
    unit_id: UUID
    customer_id: UUID
    reservation_date: date
    agreed_monthly_rent_usd_cents: int
    original_expiration_date: date
    acceptance_id: UUID
    accepted_required_amount_usd_cents: int
    acceptance_kind: str
    # None: the database's statement time (owner answer (a) to Q-2026-10-20-147).
    accepted_at: datetime | None
    acceptance_reason: str
    authorization_reference: str
    calculation_trace: dict[str, object]
    deposit_id: UUID
    required_deposit_usd_cents: int
    receipt_id: UUID
    payment_id: UUID
    received_at: datetime | None

    def __post_init__(self) -> None:
        for field in (
            "idempotency_key",
            "reservation_id",
            "unit_id",
            "customer_id",
            "acceptance_id",
            "deposit_id",
            "receipt_id",
            "payment_id",
        ):
            _require_identity(getattr(self, field), field)
        _require_nonblank(self.acceptance_reason, "acceptance_reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")
        if self.agreed_monthly_rent_usd_cents <= 0:
            raise ValueError("agreed_monthly_rent_usd_cents must be positive")
        if self.accepted_required_amount_usd_cents <= 0:
            raise ValueError("accepted_required_amount_usd_cents must be positive")
        if self.required_deposit_usd_cents < self.accepted_required_amount_usd_cents:
            raise ValueError("required Deposit must cover the accepted initial amount")


@dataclass(frozen=True, slots=True)
class ReservationExtendCommand:
    """One version-checked, single-extension command."""

    idempotency_key: UUID
    notice_id: UUID
    reservation_id: UUID
    expected_version: int
    new_expiration_date: date
    # None (every route): the database's own time at the command (Q-2026-10-14-112).
    approved_at: datetime | None
    reason_memo: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "notice_id", "reservation_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        _require_nonblank(self.authorization_reference, "authorization_reference")
        if self.reason_memo and self.reason_memo != self.reason_memo.strip():
            raise ValueError("reason_memo must be normalized")


@dataclass(frozen=True, slots=True)
class ReservationCancelCommand:
    """One classified cancellation; the Deposit stays held until its draft is confirmed."""

    idempotency_key: UUID
    event_id: UUID
    reservation_id: UUID
    expected_version: int
    reason_code: str
    responsibility: CancellationResponsibility
    property_could_provide_unit: bool
    reason_memo: str
    coordination_reference: str | None
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "reservation_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        _require_nonblank(self.reason_code, "reason_code")
        _require_nonblank(self.authorization_reference, "authorization_reference")
        if self.reason_code == "RESERVATION_EXPIRED":
            raise ValueError("RESERVATION_EXPIRED is reserved for automatic expiration")
        if self.reason_memo and self.reason_memo != self.reason_memo.strip():
            raise ValueError("reason_memo must be normalized")
        if self.responsibility is CancellationResponsibility.CUSTOMER:
            if not self.property_could_provide_unit or self.coordination_reference is not None:
                raise ValueError("Customer cancellation classification is inconsistent")
        elif self.property_could_provide_unit:
            raise ValueError("Property cancellation classification is inconsistent")
        elif self.coordination_reference is None:
            raise ValueError("Property cancellation requires coordination evidence")
        else:
            _require_nonblank(self.coordination_reference, "coordination_reference")


@dataclass(frozen=True, slots=True)
class ReservationExpireCommand:
    """One deterministic end-of-date expiration; it never forfeits the Deposit."""

    idempotency_key: UUID
    event_id: UUID
    reservation_id: UUID
    expected_version: int
    property_could_provide_unit: bool
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "reservation_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        if not self.property_could_provide_unit:
            raise ValueError("Property inability requires coordinated cancellation")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class ReservationActivationResult:
    reservation_id: UUID
    unit_id: UUID
    customer_id: UUID
    status: ReservationStatus
    effective_expiration_date: date
    deposit_id: UUID
    received_usd_cents: int
    version: int


@dataclass(frozen=True, slots=True)
class ReservationExtensionResult:
    reservation_id: UUID
    original_expiration_date: date
    previous_expiration_date: date
    effective_expiration_date: date
    status: ReservationStatus
    version: int


@dataclass(frozen=True, slots=True)
class ReservationLifecycleResult:
    reservation_id: UUID
    unit_id: UUID
    status: ReservationStatus
    cancellation_reason_code: str
    cancellation_responsibility: CancellationResponsibility
    effective_expiration_date: date
    version: int
    unit_status: str
    unit_version: int
    deposit_id: UUID
    deposit_received_usd_cents: int
    deposit_outcome_state: DepositOutcomeState
    outcome_id: UUID | None
    refund_number: str | None


@dataclass(frozen=True, slots=True)
class DueReservation:
    reservation_id: UUID
    effective_expiration_date: date
    version: int


def _activation(row: tuple[object, ...]) -> ReservationActivationResult:
    return ReservationActivationResult(
        UUID(str(row[0])),
        UUID(str(row[1])),
        UUID(str(row[2])),
        ReservationStatus(str(row[3])),
        cast(date, row[4]),
        UUID(str(row[5])),
        int(str(row[6])),
        int(str(row[7])),
    )


def _extension(row: tuple[object, ...]) -> ReservationExtensionResult:
    return ReservationExtensionResult(
        UUID(str(row[0])),
        cast(date, row[1]),
        cast(date, row[2]),
        cast(date, row[3]),
        ReservationStatus(str(row[4])),
        int(str(row[5])),
    )


def _lifecycle(row: tuple[object, ...]) -> ReservationLifecycleResult:
    return ReservationLifecycleResult(
        UUID(str(row[0])),
        UUID(str(row[1])),
        ReservationStatus(str(row[2])),
        str(row[3]),
        CancellationResponsibility(str(row[4])),
        cast(date, row[5]),
        int(str(row[6])),
        str(row[7]),
        int(str(row[8])),
        UUID(str(row[9])),
        int(str(row[10])),
        DepositOutcomeState(str(row[11])),
        None if row[12] is None else UUID(str(row[12])),
        None if row[13] is None else str(row[13]),
    )


CREATE_RESERVATION_SQL: Final = """
    SELECT * FROM app.create_reservation(
        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
        COALESCE(%s::timestamptz,statement_timestamp()),%s,%s,%s,%s,%s,%s,%s,
        COALESCE(%s::timestamptz,statement_timestamp()),%s
    )
"""
# V1-061 (DL-112): the Payment key of a one-step Reservation is made from the command's key.
ONE_STEP_NAMESPACE: Final = UUID("6f0c2a52-6d1b-4f43-9b7e-2d61c0a5e101")


def _raise_command_error(exc: psycopg.Error) -> NoReturn:
    if exc.sqlstate in {"P0002", "P5301", "P4501"}:
        raise ReservationNotFoundError("Reservation resource was not found") from exc
    if exc.sqlstate == "40001":
        raise ReservationVersionConflictError(
            "Reservation version precondition was not met"
        ) from exc
    if exc.sqlstate == "P0001" and "idempotency key was reused" in str(exc).lower():
        raise ReservationIdempotencyKeyReused("Reservation idempotency key was reused") from exc
    if exc.sqlstate == "P5305":
        raise ReservationIdempotencyKeyReused("Reservation payment key was reused") from exc
    if exc.sqlstate in {"P0001", "23505"}:
        raise ReservationCommandConflictError("Reservation command conflicted") from exc
    if exc.sqlstate in {"22023", "23514", "55000", "P5302"}:
        raise ReservationCommandInvalidError("Reservation command is invalid") from exc
    raise ReservationServiceUnavailableError("Reservation persistence is unavailable") from exc


@dataclass(frozen=True, slots=True)
class PostgresReservationService:
    """Execute Property-scoped Reservation commands with stable retry semantics."""

    database_url: str
    property_id: UUID
    actor_id: UUID
    financial_database_url: str | None = None

    def __post_init__(self) -> None:
        _require_identity(self.property_id, "property_id")
        _require_identity(self.actor_id, "actor_id")

    def _require_authorized_actor(self, actor: AuthenticatedActor, *capabilities: str) -> None:
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise ReservationAuthorizationError("Reservation actor is invalid") from exc
        if authenticated_actor_id != self.actor_id:
            raise ReservationAuthorizationError("Reservation actor does not match the command")
        for capability in capabilities:
            if not is_authorized(
                actor,
                AuthorizationRequirement(
                    capability=capability,
                    property_id=str(self.property_id),
                ),
            ):
                raise ReservationAuthorizationError(
                    "Reservation financial capability is not authorized"
                )

    def _financial_url(self) -> str:
        if self.financial_database_url is None:
            raise ReservationAuthorizationError(
                "Dedicated Reservation financial persistence is unavailable"
            )
        return self.financial_database_url

    def _execute(
        self,
        query: str,
        parameters: tuple[object, ...],
        *,
        database_url: str | None = None,
    ) -> tuple[object, ...]:
        try:
            with psycopg.connect(database_url or self.database_url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            _raise_command_error(exc)
        if row is None:
            raise ReservationServiceUnavailableError("Reservation command returned no result")
        return row

    def create(self, command: ReservationCreateCommand) -> ReservationActivationResult:
        # The acceptance and receipt times default to statement_timestamp() (owner answer (a) to
        # Q-2026-10-20-147): one statement time for both, within the function's own checks.
        return _activation(self._execute(CREATE_RESERVATION_SQL, self._create_values(command)))

    def _create_values(self, command: ReservationCreateCommand) -> tuple[object, ...]:
        return (
            self.property_id,
            command.idempotency_key,
            reservation_request_digest("reservation.create", command),
            command.reservation_id,
            command.unit_id,
            command.customer_id,
            command.reservation_date,
            command.agreed_monthly_rent_usd_cents,
            command.original_expiration_date,
            command.acceptance_id,
            command.accepted_required_amount_usd_cents,
            command.acceptance_kind,
            command.accepted_at,
            command.acceptance_reason,
            command.authorization_reference,
            Jsonb(command.calculation_trace),
            command.deposit_id,
            command.required_deposit_usd_cents,
            command.receipt_id,
            command.payment_id,
            command.received_at,
            self.actor_id,
        )

    def create_with_payment(
        self, command: ReservationCreateCommand, payment: dict[str, object]
    ) -> tuple[ReservationActivationResult, dict[str, object]]:
        """V1-061 (DL-112): the deposit received and the Reservation that holds it, saved in one
        database transaction or not at all (app.create_reservation_with_payment).

        The Payment's key is made from the command's key, and the Reservation's request digest is
        taken with that key in place of the Payment: the same request always confirms the same
        Payment, so the digest stays the same on a replay. ``command.payment_id`` is ignored."""
        url = self._financial_url()
        payment_key = uuid5(
            ONE_STEP_NAMESPACE,
            f"reservation-payment:{self.property_id}:{self.actor_id}:{command.idempotency_key}",
        )
        keyed = replace(command, payment_id=payment_key)
        try:
            with psycopg.connect(url, connect_timeout=3) as connection:
                set_json_loads(_exact_json, connection)
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='10000ms'")
                row = connection.execute(
                    "SELECT app.create_reservation_with_payment("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.property_id,
                        self.actor_id,
                        payment_key,
                        Jsonb(payment),
                        command.idempotency_key,
                        reservation_request_digest("reservation.create", keyed),
                        command.reservation_id,
                        command.unit_id,
                        command.customer_id,
                        command.reservation_date,
                        command.agreed_monthly_rent_usd_cents,
                        command.original_expiration_date,
                        command.acceptance_id,
                        command.accepted_required_amount_usd_cents,
                        command.acceptance_kind,
                        command.acceptance_reason,
                        command.authorization_reference,
                        Jsonb(command.calculation_trace),
                        command.deposit_id,
                        command.required_deposit_usd_cents,
                        command.receipt_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            _raise_command_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise ReservationServiceUnavailableError("Reservation command returned no result")
        value = cast(dict[str, object], row[0])
        made = cast(dict[str, object], value["reservation"])
        return (
            _activation(
                (
                    made["reservation_id"],
                    made["unit_id"],
                    made["customer_id"],
                    made["status"],
                    date.fromisoformat(str(made["effective_expiration_date"])),
                    made["deposit_id"],
                    made["received_usd_cents"],
                    made["version"],
                )
            ),
            value,
        )

    def extend(self, command: ReservationExtendCommand) -> ReservationExtensionResult:
        digest = reservation_request_digest("reservation.extend", command)
        # The approval time defaults to statement_timestamp(), within the notice's own check.
        return _extension(
            self._execute(
                "SELECT * FROM app.extend_reservation_v2(%s,%s,%s,%s,%s,%s,%s,"
                "COALESCE(%s::timestamptz,statement_timestamp()),%s,%s,%s)",
                (
                    self.property_id,
                    command.idempotency_key,
                    digest,
                    command.notice_id,
                    command.reservation_id,
                    command.expected_version,
                    command.new_expiration_date,
                    command.approved_at,
                    command.reason_memo,
                    command.authorization_reference,
                    self.actor_id,
                ),
            )
        )

    def cancel(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationLifecycleResult:
        """Cancel and release the Unit; the Deposit decision is a separate draft."""
        self._require_authorized_actor(actor, RESERVATION_CANCEL_CAPABILITY)
        if command.authorization_reference != RESERVATION_CANCEL_CAPABILITY:
            raise ReservationAuthorizationError("Cancellation evidence is not authoritative")
        digest = reservation_request_digest("reservation.cancel", command)
        return _lifecycle(
            self._execute(
                "SELECT * FROM app.cancel_reservation_v3(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.property_id,
                    command.idempotency_key,
                    digest,
                    command.event_id,
                    command.reservation_id,
                    command.expected_version,
                    command.reason_code,
                    command.responsibility.value,
                    command.property_could_provide_unit,
                    command.reason_memo,
                    command.coordination_reference,
                    command.authorization_reference,
                    self.actor_id,
                ),
                database_url=self._financial_url(),
            )
        )

    def expire(
        self,
        command: ReservationExpireCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationLifecycleResult:
        """Expire and release the Unit (BR-RES-016); the forfeiture waits for a draft."""
        self._require_authorized_actor(actor, RESERVATION_CANCEL_CAPABILITY)
        if command.authorization_reference != RESERVATION_CANCEL_CAPABILITY:
            raise ReservationAuthorizationError("Expiration evidence is not authoritative")
        digest = reservation_request_digest("reservation.expire", command)
        return _lifecycle(
            self._execute(
                "SELECT * FROM app.expire_reservation_v3(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.property_id,
                    command.idempotency_key,
                    digest,
                    command.event_id,
                    command.reservation_id,
                    command.expected_version,
                    command.property_could_provide_unit,
                    command.authorization_reference,
                    self.actor_id,
                ),
                database_url=self._financial_url(),
            )
        )

    def list_due(
        self, *, limit: int = 100, as_of: date | None = None
    ) -> tuple[DueReservation, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        try:
            with psycopg.connect(self.database_url) as connection:
                if as_of is None:
                    rows = connection.execute(
                        "SELECT * FROM app.list_due_reservations(%s,%s)",
                        (self.property_id, limit),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT * FROM app.list_due_reservations_as_of(%s,%s,%s)",
                        (self.property_id, as_of, limit),
                    ).fetchall()
        except psycopg.Error as exc:
            raise ReservationServiceUnavailableError(
                "Reservation persistence is unavailable"
            ) from exc
        return tuple(
            DueReservation(UUID(str(row[0])), cast(date, row[1]), int(str(row[2]))) for row in rows
        )
