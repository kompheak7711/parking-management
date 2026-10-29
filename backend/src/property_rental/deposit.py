"""Security and Pet Deposit domain services over the protected PostgreSQL boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Final, NoReturn, TypeAlias, cast
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb, set_json_loads

from property_rental.deposit_disposition import LeaseDepositDispositionContext
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.lock_retry import retry_lock_not_available
from property_rental.payment_confirmation import _exact_json

NIL_UUID: Final = UUID(int=0)
DEPOSIT_MANAGE_CAPABILITY: Final = "deposits.manage"
DEPOSIT_CORRECT_CAPABILITY: Final = "deposits.correct"
DEPOSIT_DISPOSE_CAPABILITY: Final = "deposits.dispose"
DEPOSIT_REFUND_QUALIFY_CAPABILITY: Final = "deposits.refund.qualify"
PAYMENT_ALLOCATE_CAPABILITY: Final = "payments.allocate"
DEPOSIT_CONNECT_TIMEOUT_SECONDS: Final = 3
DEPOSIT_LOCK_TIMEOUT_MS: Final = 3_000
DEPOSIT_QUERY_TIMEOUT_MS: Final = 3_000


class DepositType(StrEnum):
    SECURITY = "SECURITY"
    PET = "PET"


class DepositAdjustmentType(StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class DepositNotFoundError(LookupError):
    pass


class DepositConflictError(RuntimeError):
    pass


class DepositIdempotencyKeyReused(DepositConflictError):
    pass


class DepositInvalidError(ValueError):
    pass


class DepositAuthorizationError(PermissionError):
    pass


class DepositServiceUnavailableError(RuntimeError):
    pass


class LeaseDepositDraftRequired(RuntimeError):
    """A Lease Deposit forfeiture or its reversal is a draft now (BR-AUTH-010, V1-056 slice 6)."""


class DepositReceiptReversalDraftRequired(RuntimeError):
    """A Deposit receipt reversal is a draft now (BR-AUTH-010, V1-056 sub-slice 8r)."""


def _identity(value: UUID, field: str) -> None:
    if value == NIL_UUID:
        raise ValueError(f"{field} must not be the nil UUID")


def _text(value: str, field: str) -> None:
    if not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be normalized and nonblank")


@dataclass(frozen=True, slots=True)
class PetDepositAssessment:
    """A policy-neutral assessment; discovery alone never creates a liability."""

    pet_approved: bool
    signed_terms_require_deposit: bool
    pet_permanently_departed: bool = False

    @property
    def deposit_required(self) -> bool:
        return (
            self.pet_approved
            and self.signed_terms_require_deposit
            and not self.pet_permanently_departed
        )

    @property
    def violation_requires_warning_only(self) -> bool:
        return not self.pet_approved


@dataclass(frozen=True, slots=True)
class CreatePetDepositCommand:
    idempotency_key: UUID
    deposit_id: UUID
    lease_id: UUID
    pet_approval_id: UUID
    required_usd_cents: int
    required_effective_date: date
    reason: str
    authorization_reference: str = DEPOSIT_MANAGE_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "deposit_id", "lease_id", "pet_approval_id"):
            _identity(getattr(self, field), field)
        if self.required_usd_cents <= 0:
            raise ValueError("required_usd_cents must be positive")
        _text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class AdjustDepositRequiredAmountCommand:
    idempotency_key: UUID
    adjustment_id: UUID
    deposit_id: UUID
    adjustment_type: DepositAdjustmentType
    amount_usd_cents: int
    effective_date: date
    reason: str
    authorization_reference: str = DEPOSIT_MANAGE_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "adjustment_id", "deposit_id"):
            _identity(getattr(self, field), field)
        if self.amount_usd_cents <= 0:
            raise ValueError("amount_usd_cents must be positive")
        _text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class ReverseDepositReceiptCommand:
    idempotency_key: UUID
    reversal_id: UUID
    receipt_id: UUID
    reason: str
    authorization_reference: str = DEPOSIT_CORRECT_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "reversal_id", "receipt_id"):
            _identity(getattr(self, field), field)
        _text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class RecordPetDepartureCommand:
    idempotency_key: UUID
    departure_id: UUID
    deposit_id: UUID
    permanently_left_date: date
    reason: str
    authorization_reference: str = DEPOSIT_REFUND_QUALIFY_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "departure_id", "deposit_id"):
            _identity(getattr(self, field), field)
        _text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class QualifyPetDepositRefundReviewCommand:
    idempotency_key: UUID
    review_id: UUID
    departure_id: UUID
    deposit_id: UUID
    obligations_reviewed_usd_cents: int
    review_findings: str
    resolution_reference: str
    reason: str
    authorization_reference: str = DEPOSIT_REFUND_QUALIFY_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "review_id", "departure_id", "deposit_id"):
            _identity(getattr(self, field), field)
        if self.obligations_reviewed_usd_cents < 0:
            raise ValueError("obligations_reviewed_usd_cents must not be negative")
        for field in ("review_findings", "resolution_reference", "reason"):
            _text(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class RecordDepositDispositionCommand:
    idempotency_key: UUID
    disposition_id: UUID
    deposit_id: UUID
    governing_lease_id: UUID
    amount_usd_cents: int
    effective_date: date
    reason: str
    authorization_reference: str = DEPOSIT_DISPOSE_CAPABILITY
    context: LeaseDepositDispositionContext | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "disposition_id", "deposit_id", "governing_lease_id"):
            _identity(getattr(self, field), field)
        if type(self.amount_usd_cents) is not int or not (
            0 < self.amount_usd_cents <= 9_223_372_036_854_775_807
        ):
            raise ValueError(
                "amount_usd_cents must be positive integer USD cents within bigint range"
            )
        if type(self.effective_date) is not date:
            raise ValueError("effective_date must be a date")
        _text(self.reason, "reason")
        if self.context is not None:
            if not isinstance(self.context, LeaseDepositDispositionContext):
                raise ValueError("Deposit disposition context must be typed")
            if len(self.reason) > 1000 or "\x00" in self.reason:
                raise ValueError("Disposition reason must be bounded")
            if any(
                not isinstance(getattr(self, field), UUID)
                for field in (
                    "idempotency_key",
                    "disposition_id",
                    "deposit_id",
                    "governing_lease_id",
                )
            ):
                raise ValueError("Disposition identities must be nonzero UUIDs")


@dataclass(frozen=True, slots=True)
class ReverseDepositDispositionCommand:
    idempotency_key: UUID
    reversal_id: UUID
    disposition_id: UUID
    reason: str
    evidence_reference: str
    authorization_reference: str = DEPOSIT_CORRECT_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "reversal_id", "disposition_id"):
            _identity(getattr(self, field), field)
        _text(self.reason, "reason")
        _text(self.evidence_reference, "evidence_reference")


@dataclass(frozen=True, slots=True)
class RecordDepositReceiptCommand:
    """A receipt from a received Payment into an existing Deposit of a signed or terminated Lease
    (V1-056 sub-slice 10e-2b-4b-2b; owner answer to Q-2026-10-12-92: payments.allocate, no
    draft)."""

    idempotency_key: UUID
    receipt_id: UUID
    deposit_id: UUID
    payment_id: UUID
    amount_usd_cents: int
    reason: str
    authorization_reference: str = PAYMENT_ALLOCATE_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "receipt_id", "deposit_id", "payment_id"):
            _identity(getattr(self, field), field)
        if type(self.amount_usd_cents) is not int or not (
            0 < self.amount_usd_cents <= 9_223_372_036_854_775_807
        ):
            raise ValueError(
                "amount_usd_cents must be positive integer USD cents within bigint range"
            )
        _text(self.reason, "reason")
        if len(self.reason) > 1000:
            raise ValueError("reason must be at most 1000 characters")


@dataclass(frozen=True, slots=True)
class CreateLeaseSecurityDepositCommand:
    """A walk-in Lease's Security Deposit with its required total from the Lease terms (V1-056
    sub-slice 10e-2b-4c; owner answer (a) to Q-2026-10-17-124 point 1: deposits.manage)."""

    idempotency_key: UUID
    deposit_id: UUID
    lease_id: UUID
    required_usd_cents: int
    reason: str
    authorization_reference: str = DEPOSIT_MANAGE_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "deposit_id", "lease_id"):
            _identity(getattr(self, field), field)
        if type(self.required_usd_cents) is not int or not (
            0 < self.required_usd_cents <= 9_223_372_036_854_775_807
        ):
            raise ValueError(
                "required_usd_cents must be positive integer USD cents within bigint range"
            )
        _text(self.reason, "reason")
        if len(self.reason) > 1000:
            raise ValueError("reason must be at most 1000 characters")


DepositCommand: TypeAlias = (
    CreatePetDepositCommand
    | CreateLeaseSecurityDepositCommand
    | AdjustDepositRequiredAmountCommand
    | ReverseDepositReceiptCommand
    | RecordPetDepartureCommand
    | QualifyPetDepositRefundReviewCommand
    | RecordDepositDispositionCommand
    | ReverseDepositDispositionCommand
    | RecordDepositReceiptCommand
)


def deposit_request_digest(action: str, command: DepositCommand) -> str:
    fields = asdict(command)
    if isinstance(command, RecordDepositDispositionCommand) and command.context is None:
        fields.pop("context")
    payload = json.dumps(
        {"action": action, "command": fields},
        default=str,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DepositSnapshot:
    deposit_id: UUID
    property_id: UUID
    deposit_type: DepositType
    customer_id: UUID
    reservation_id: UUID | None
    lease_id: UUID | None
    pet_approval_id: UUID | None
    required_usd_cents: int
    received_usd_cents: int
    held_refundable_usd_cents: int
    outstanding_required_usd_cents: int
    version: int
    pet_departure_id: UUID | None = None
    pet_refund_review_id: UUID | None = None
    deposit_disposition_id: UUID | None = None
    deposit_disposition_reversal_id: UUID | None = None
    refund_qualified: bool = False
    reservation_version: int | None = None


@dataclass(frozen=True, slots=True)
class DepositReceiptRecord:
    """The Deposit after a recorded receipt, with the receipt and its Payment's available value."""

    deposit: DepositSnapshot
    deposit_receipt_id: UUID
    payment_id: UUID
    amount_usd_cents: int
    occurred_at: datetime
    payment_available_usd_cents: int


def _snapshot(row: tuple[object, ...]) -> DepositSnapshot:
    value = cast(dict[str, object], row[0])

    def optional_uuid(key: str) -> UUID | None:
        raw = value.get(key)
        return None if raw is None else UUID(str(raw))

    return DepositSnapshot(
        deposit_id=UUID(str(value["deposit_id"])),
        property_id=UUID(str(value["property_id"])),
        deposit_type=DepositType(str(value["deposit_type"])),
        customer_id=UUID(str(value["customer_id"])),
        reservation_id=optional_uuid("reservation_id"),
        lease_id=optional_uuid("lease_id"),
        pet_approval_id=optional_uuid("pet_approval_id"),
        required_usd_cents=int(str(value["required_usd_cents"])),
        received_usd_cents=int(str(value["received_usd_cents"])),
        held_refundable_usd_cents=int(str(value["held_refundable_usd_cents"])),
        outstanding_required_usd_cents=int(str(value["outstanding_required_usd_cents"])),
        version=int(str(value["version"])),
        pet_departure_id=optional_uuid("pet_departure_id"),
        pet_refund_review_id=optional_uuid("pet_refund_review_id"),
        deposit_disposition_id=optional_uuid("deposit_disposition_id"),
        deposit_disposition_reversal_id=optional_uuid("deposit_disposition_reversal_id"),
        refund_qualified=bool(value.get("refund_qualified", False)),
        reservation_version=(
            None
            if value.get("reservation_version") is None
            else int(str(value["reservation_version"]))
        ),
    )


# V1-061 (DL-112): the Payment and the Security Deposit keys of Receive Security Deposit are made
# from the receipt command's key.
ONE_STEP_NAMESPACE: Final = UUID("0b3d6a1e-52f4-4c8e-a1d9-7c3e5f2b9a04")


def _raise_deposit_error(exc: psycopg.Error) -> NoReturn:
    if exc.sqlstate in {"42501", "P4506"}:
        raise DepositAuthorizationError("Deposit actor is not authorized") from exc
    if exc.sqlstate in {"P0002", "P5301", "P4501"}:
        raise DepositNotFoundError("Deposit resource was not found") from exc
    if exc.sqlstate == "23505" and (
        "Deposit idempotency key conflicts with another request" in str(exc)
    ):
        raise DepositIdempotencyKeyReused("Deposit idempotency key was reused") from exc
    if exc.sqlstate == "P5305":
        raise DepositIdempotencyKeyReused("Deposit payment key was reused") from exc
    if exc.sqlstate in {"23505", "23P01", "P5801", "40001", "P5S01", "23503"}:
        raise DepositConflictError("Deposit command conflicted") from exc
    if exc.sqlstate in {"22023", "23514", "55000", "P5302"}:
        raise DepositInvalidError("Deposit command is invalid") from exc
    raise DepositServiceUnavailableError("Deposit persistence is unavailable") from exc


@dataclass(frozen=True, slots=True)
class PostgresDepositService:
    financial_database_url: str
    property_id: UUID
    actor_id: UUID

    def __post_init__(self) -> None:
        _identity(self.property_id, "property_id")
        _identity(self.actor_id, "actor_id")

    def _authorize(self, actor: AuthenticatedActor, capability: str, reference: str) -> None:
        try:
            actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise DepositAuthorizationError("Deposit actor is invalid") from exc
        if (
            actor_id != self.actor_id
            or reference != capability
            or not is_authorized(
                actor,
                AuthorizationRequirement(capability=capability, property_id=str(self.property_id)),
            )
        ):
            raise DepositAuthorizationError("Deposit capability is not authorized")

    def _execute(self, query: str, parameters: tuple[object, ...]) -> DepositSnapshot:
        return _snapshot(self._fetch(query, parameters))

    def _attempt(self, query: str, parameters: tuple[object, ...]) -> tuple[object, ...] | None:
        with psycopg.connect(
            self.financial_database_url, connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS
        ) as connection:
            connection.execute(
                "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
                (str(DEPOSIT_LOCK_TIMEOUT_MS),),
            )
            connection.execute(
                "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                (str(DEPOSIT_QUERY_TIMEOUT_MS),),
            )
            return connection.execute(query, parameters).fetchone()

    def _fetch(
        self,
        query: str,
        parameters: tuple[object, ...],
        *,
        replay_lock_refusal: bool = False,
    ) -> tuple[object, ...]:
        try:
            if replay_lock_refusal:
                # DL-067 (owner decision 2026-10-03): a command that reaches the excess check's
                # NOWAIT locks is replayed unchanged, with the same key, after 55P03.
                row = retry_lock_not_available(lambda: self._attempt(query, parameters))
            else:
                row = self._attempt(query, parameters)
        except psycopg.Error as exc:
            _raise_deposit_error(exc)
        if row is None:
            raise DepositServiceUnavailableError("Deposit command returned no result")
        return row

    def create_pet_deposit(
        self, command: CreatePetDepositCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        self._authorize(actor, DEPOSIT_MANAGE_CAPABILITY, command.authorization_reference)
        return self._execute(
            "SELECT app.create_pet_deposit_v2(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                self.actor_id,
                command.idempotency_key,
                deposit_request_digest("deposit.pet.create", command),
                command.deposit_id,
                command.lease_id,
                command.pet_approval_id,
                command.required_usd_cents,
                command.required_effective_date,
                command.reason,
                command.authorization_reference,
            ),
        )

    def create_lease_security_deposit(
        self, command: CreateLeaseSecurityDepositCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        self._authorize(actor, DEPOSIT_MANAGE_CAPABILITY, command.authorization_reference)
        return self._execute(
            "SELECT app.create_lease_security_deposit(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                self.actor_id,
                command.idempotency_key,
                deposit_request_digest("deposit.security.create", command),
                command.deposit_id,
                command.lease_id,
                command.required_usd_cents,
                command.reason,
                command.authorization_reference,
            ),
        )

    def adjust_required_amount(
        self, command: AdjustDepositRequiredAmountCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        self._authorize(actor, DEPOSIT_MANAGE_CAPABILITY, command.authorization_reference)
        return self._execute(
            "SELECT app.adjust_deposit_required_amount(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                self.actor_id,
                command.idempotency_key,
                deposit_request_digest("deposit.required.adjust", command),
                command.adjustment_id,
                command.deposit_id,
                command.adjustment_type,
                command.amount_usd_cents,
                command.effective_date,
                command.reason,
                command.authorization_reference,
            ),
        )

    def record_receipt(
        self, command: RecordDepositReceiptCommand, *, actor: AuthenticatedActor
    ) -> DepositReceiptRecord:
        """Record a receipt into an existing Deposit of a signed or terminated Lease, or into an
        ACTIVE Reservation's Security Deposit before signing (sub-slice 10e-2b-4c).

        payments.allocate, no draft; refused once the Lease's Final Settlement is closed (a
        conflict). A Payment confirmed for an Invoice or a Late-payment Charge reaches the excess
        check's NOWAIT locks (sub-slice 10e-2b-4d), so every receipt command is replayed after any
        55P03 (also a lock timeout) at most three times and is unavailable after the last attempt
        (DL-067, as in the Credit and Refund services; at worst about 14 seconds)."""
        self._authorize(actor, PAYMENT_ALLOCATE_CAPABILITY, command.authorization_reference)
        row = self._fetch(
            "SELECT app.record_lease_deposit_receipt(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                self.actor_id,
                command.idempotency_key,
                deposit_request_digest("deposit.receipt.record", command),
                command.receipt_id,
                command.deposit_id,
                command.payment_id,
                command.amount_usd_cents,
                command.reason,
                command.authorization_reference,
            ),
            replay_lock_refusal=True,
        )
        value = cast(dict[str, object], row[0])
        return DepositReceiptRecord(
            deposit=_snapshot(row),
            deposit_receipt_id=UUID(str(value["deposit_receipt_id"])),
            payment_id=UUID(str(value["payment_id"])),
            amount_usd_cents=int(str(value["amount_usd_cents"])),
            occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
            payment_available_usd_cents=int(str(value["payment_available_usd_cents"])),
        )

    def receive_with_payment(
        self,
        lease_id: UUID,
        payment: dict[str, object],
        create: CreateLeaseSecurityDepositCommand | None,
        receipt: RecordDepositReceiptCommand,
        *,
        actor: AuthenticatedActor,
    ) -> tuple[DepositReceiptRecord, dict[str, object]]:
        """V1-061 (DL-112): Receive Security Deposit in one database transaction, or not at all
        (app.receive_lease_security_deposit_with_payment): the Payment and its Receipt, a walk-in
        Lease's Security Deposit when ``create`` is given, and the money into the Security
        Deposit. The Payment's key is made from the receipt command's key, and the receipt's
        request digest is taken with that key in place of the Payment, so the same request always
        answers the same records. ``receipt.payment_id`` is ignored. The whole command is
        replayed after 55P03 (DL-067)."""
        if not is_authorized(
            actor, AuthorizationRequirement("payments.record", str(self.property_id))
        ):
            raise DepositAuthorizationError("Deposit capability is not authorized")
        self._authorize(actor, PAYMENT_ALLOCATE_CAPABILITY, receipt.authorization_reference)
        if create is not None:
            self._authorize(actor, DEPOSIT_MANAGE_CAPABILITY, create.authorization_reference)
            if (
                create.deposit_id != receipt.deposit_id
                or create.reason != receipt.reason
                or create.lease_id != lease_id
            ):
                raise DepositInvalidError("Security Deposit command is invalid")
        payment_key = uuid5(
            ONE_STEP_NAMESPACE,
            f"deposit-payment:{self.property_id}:{self.actor_id}:{receipt.idempotency_key}",
        )
        keyed = replace(receipt, payment_id=payment_key)
        parameters = (
            self.property_id,
            self.actor_id,
            payment_key,
            Jsonb(payment),
            None if create is None else create.idempotency_key,
            None if create is None else deposit_request_digest("deposit.security.create", create),
            receipt.deposit_id,
            lease_id,
            None if create is None else create.required_usd_cents,
            receipt.reason,
            receipt.idempotency_key,
            deposit_request_digest("deposit.receipt.record", keyed),
            receipt.receipt_id,
            receipt.amount_usd_cents,
        )

        def attempt() -> tuple[object, ...] | None:
            with psycopg.connect(
                self.financial_database_url, connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                set_json_loads(_exact_json, connection)
                connection.execute(
                    "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
                    (str(DEPOSIT_LOCK_TIMEOUT_MS),),
                )
                connection.execute(
                    "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                    (str(DEPOSIT_QUERY_TIMEOUT_MS * 2),),
                )
                return connection.execute(
                    "SELECT app.receive_lease_security_deposit_with_payment("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    parameters,
                ).fetchone()

        try:
            row = retry_lock_not_available(attempt)
        except psycopg.Error as exc:
            _raise_deposit_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise DepositServiceUnavailableError("Deposit command returned no result")
        confirmed = cast(dict[str, object], row[0])
        value = cast(dict[str, object], confirmed["deposit"])
        return (
            DepositReceiptRecord(
                deposit=_snapshot((value,)),
                deposit_receipt_id=UUID(str(value["deposit_receipt_id"])),
                payment_id=UUID(str(value["payment_id"])),
                amount_usd_cents=int(str(value["amount_usd_cents"])),
                occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
                payment_available_usd_cents=int(str(value["payment_available_usd_cents"])),
            ),
            confirmed,
        )

    def reverse_receipt(
        self, command: ReverseDepositReceiptCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        """Refused: a receipt reversal is a draft confirmed by financial.approve.

        Use ``DepositReceiptReversalService`` (owner answer to Q-2026-10-05-22).
        """
        self._authorize(actor, DEPOSIT_CORRECT_CAPABILITY, command.authorization_reference)
        raise DepositReceiptReversalDraftRequired("Deposit receipt reversal draft required")

    def record_pet_departure(
        self, command: RecordPetDepartureCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        self._authorize(actor, DEPOSIT_REFUND_QUALIFY_CAPABILITY, command.authorization_reference)
        return self._execute(
            "SELECT app.record_active_lease_pet_departure(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                self.actor_id,
                command.idempotency_key,
                deposit_request_digest("deposit.pet_departure.record", command),
                command.departure_id,
                command.deposit_id,
                command.permanently_left_date,
                command.reason,
                command.authorization_reference,
            ),
        )

    def qualify_pet_refund_review(
        self, command: QualifyPetDepositRefundReviewCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        self._authorize(actor, DEPOSIT_REFUND_QUALIFY_CAPABILITY, command.authorization_reference)
        return self._execute(
            "SELECT app.qualify_active_lease_pet_refund_review("
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                self.actor_id,
                command.idempotency_key,
                deposit_request_digest("deposit.pet_refund.review", command),
                command.review_id,
                command.departure_id,
                command.deposit_id,
                command.obligations_reviewed_usd_cents,
                command.review_findings,
                command.resolution_reference,
                command.reason,
                command.authorization_reference,
            ),
        )

    def record_disposition(
        self, command: RecordDepositDispositionCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        """Refused: a Lease Deposit forfeiture is a draft confirmed by financial.approve.

        Use ``LeaseDepositForfeitureService`` (owner answer to Q-2026-10-04-12).
        """
        self._authorize(actor, DEPOSIT_DISPOSE_CAPABILITY, command.authorization_reference)
        raise LeaseDepositDraftRequired("Lease Deposit forfeiture draft required")

    def reverse_disposition(
        self, command: ReverseDepositDispositionCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        """Refused: a Lease forfeiture reversal is a draft (owner answer to Q-2026-10-04-13)."""
        self._authorize(actor, DEPOSIT_CORRECT_CAPABILITY, command.authorization_reference)
        raise LeaseDepositDraftRequired("Lease Deposit forfeiture reversal draft required")
