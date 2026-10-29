"""Authorized Lease lifecycle services over the protected PostgreSQL boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final, TypeAlias, cast
from uuid import UUID

import psycopg

from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.lease_termination import TerminationContext

NIL_UUID: Final = UUID(int=0)
LEASE_DRAFT_CAPABILITY: Final = "leases.draft"
LEASE_SIGN_CAPABILITY: Final = "leases.sign"
LEASE_TERMINATE_CAPABILITY: Final = "leases.terminate"
LEASE_SIGNER_MANAGE_CAPABILITY: Final = "lease_signers.manage"


class LeaseStatus(StrEnum):
    """The complete approved Lease status vocabulary."""

    DRAFTED = "DRAFTED"
    SIGNED = "SIGNED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"


class LeaseNotFoundError(LookupError):
    """Raised when a Lease is absent or outside the exact Property scope."""


class LeaseVersionConflictError(RuntimeError):
    """Raised when a lifecycle command uses a stale optimistic version."""


class LeaseCommandConflictError(RuntimeError):
    """Raised for idempotency, signer identity, or Unit exclusivity conflicts."""


class LeaseCommandInvalidError(ValueError):
    """Raised when a command violates a Lease lifecycle invariant."""


class LeaseEndDateNotMonthEndError(LeaseCommandInvalidError):
    """Raised when a Lease End Date is not the last day of its month (BR-LEASE-031)."""


END_DATE_NOT_MONTH_END: Final = "Lease End Date must be the last day of a calendar month"


class LeaseRequiredServiceMissingError(LeaseCommandInvalidError):
    """Raised when a new Lease draft leaves out a Service its Unit requires (DL-110)."""


REQUIRED_SERVICE_MISSING: Final = "Lease draft is missing a required Service of the Unit"


class LeaseAuthorizationError(PermissionError):
    """Raised before persistence when trusted capability evidence is absent."""


class LeaseServiceUnavailableError(RuntimeError):
    """Raised when Lease persistence cannot be reached safely."""


def _require_identity(value: UUID, field: str) -> None:
    if value == NIL_UUID:
        raise ValueError(f"{field} must not be the nil UUID")


def _require_nonblank(value: str, field: str) -> None:
    if not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be normalized and nonblank")


def _require_optional_period(starts_on: date | None, ends_on: date | None) -> None:
    if (starts_on is None) != (ends_on is None):
        raise ValueError("Lease start and end dates must be supplied together")
    if starts_on is not None and ends_on is not None and ends_on <= starts_on:
        raise ValueError("Lease end date must be later than its start date")


def _json_value(value: object) -> object:
    if isinstance(value, (date, datetime, UUID, StrEnum)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class LeaseDraftSigner:
    """One additional, explicitly identified Lease signer."""

    signer_id: UUID
    customer_id: UUID

    def __post_init__(self) -> None:
        _require_identity(self.signer_id, "signer_id")
        _require_identity(self.customer_id, "customer_id")


@dataclass(frozen=True, slots=True)
class LeaseServiceTerm:
    """One approved configured Service term captured with a Lease draft."""

    term_id: UUID
    property_service_id: UUID
    applicable_from: date
    applicable_through: date | None
    service_approval_period_id: UUID
    terms_reference: str

    def __post_init__(self) -> None:
        for field in ("term_id", "property_service_id", "service_approval_period_id"):
            _require_identity(getattr(self, field), field)
        if self.applicable_through is not None and self.applicable_through < self.applicable_from:
            raise ValueError("Service term period is reversed")
        _require_nonblank(self.terms_reference, "terms_reference")


@dataclass(frozen=True, slots=True)
class LeasePetTerm:
    """Approved pet terms captured without inventing a Pet Deposit policy."""

    approval_id: UUID
    approved_date: date
    deposit_required_by_signed_terms: bool
    pet_description: str | None

    def __post_init__(self) -> None:
        _require_identity(self.approval_id, "approval_id")
        if self.pet_description is not None:
            _require_nonblank(self.pet_description, "pet_description")


@dataclass(frozen=True, slots=True)
class LeaseDraftCommand:
    """Create one stable DRAFTED Lease and its unsigned Primary Tenant signer."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    unit_id: UUID
    primary_tenant_id: UUID
    primary_signer_id: UUID
    start_date: date | None
    end_date: date | None
    monthly_rent_usd_cents: int | None
    predecessor_lease_id: UUID | None
    reason: str
    authorization_reference: str
    additional_signers: tuple[LeaseDraftSigner, ...] = ()
    planned_occupant_customer_ids: tuple[UUID, ...] = ()
    service_terms: tuple[LeaseServiceTerm, ...] = ()
    pet_term: LeasePetTerm | None = None
    security_deposit_id: UUID | None = None

    def __post_init__(self) -> None:
        for field in (
            "idempotency_key",
            "event_id",
            "lease_id",
            "unit_id",
            "primary_tenant_id",
            "primary_signer_id",
        ):
            _require_identity(getattr(self, field), field)
        if self.predecessor_lease_id is not None:
            _require_identity(self.predecessor_lease_id, "predecessor_lease_id")
            if self.predecessor_lease_id == self.lease_id:
                raise ValueError("A Lease cannot be its own predecessor")
        _require_optional_period(self.start_date, self.end_date)
        if self.monthly_rent_usd_cents is not None and self.monthly_rent_usd_cents <= 0:
            raise ValueError("monthly_rent_usd_cents must be positive")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")
        if len(self.additional_signers) > 19 or len(self.planned_occupant_customer_ids) > 20:
            raise ValueError("Lease parties exceed the bounded draft limit")
        if len(self.service_terms) > 20:
            raise ValueError("Lease Service terms exceed the bounded draft limit")
        signer_customers = [
            self.primary_tenant_id,
            *(item.customer_id for item in self.additional_signers),
        ]
        signer_ids = [self.primary_signer_id, *(item.signer_id for item in self.additional_signers)]
        if len(set(signer_customers)) != len(signer_customers) or len(set(signer_ids)) != len(
            signer_ids
        ):
            raise ValueError("Lease signers must be unique")
        if len(set(self.planned_occupant_customer_ids)) != len(self.planned_occupant_customer_ids):
            raise ValueError("Planned Occupants must be unique")
        for customer_id in self.planned_occupant_customer_ids:
            _require_identity(customer_id, "planned_occupant_customer_id")
        if self.security_deposit_id is not None:
            _require_identity(self.security_deposit_id, "security_deposit_id")


@dataclass(frozen=True, slots=True)
class LeaseAddSignerCommand:
    """Add one Customer as a pending signer to a DRAFTED Lease."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    signer_id: UUID
    customer_id: UUID
    expected_version: int
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id", "signer_id", "customer_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class LeaseUpdateDraftCommand:
    """Update mutable source terms while a Lease remains DRAFTED."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_version: int
    start_date: date | None
    end_date: date | None
    monthly_rent_usd_cents: int | None
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        _require_optional_period(self.start_date, self.end_date)
        if self.monthly_rent_usd_cents is not None and self.monthly_rent_usd_cents <= 0:
            raise ValueError("monthly_rent_usd_cents must be positive")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class LeaseRecordSignatureCommand:
    """Record one attributed signature while the Lease remains DRAFTED."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    signer_id: UUID
    expected_version: int
    # None (every route): the database's own time at the command (Q-2026-10-14-110).
    signed_at: datetime | None
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id", "signer_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        if self.signed_at is not None and (
            self.signed_at.tzinfo is None or self.signed_at.utcoffset() is None
        ):
            raise ValueError("signed_at must include a timezone")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class LeaseRemoveSignerCommand:
    """Remove one unsigned non-primary signer from a DRAFTED Lease."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    signer_id: UUID
    expected_version: int
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id", "signer_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class LeaseSignCommand:
    """Move one complete, fully signed DRAFTED Lease to SIGNED."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_version: int
    # None (every route): the database's own time at the command (Q-2026-10-14-110).
    signed_at: datetime | None
    reason: str
    authorization_reference: str
    reservation_id: UUID | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id"):
            _require_identity(getattr(self, field), field)
        if self.reservation_id is not None:
            _require_identity(self.reservation_id, "reservation_id")
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        if self.signed_at is not None and (
            self.signed_at.tzinfo is None or self.signed_at.utcoffset() is None
        ):
            raise ValueError("signed_at must include a timezone")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class LeaseCancelCommand:
    """Cancel only a DRAFTED Lease without creating termination policy."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_version: int
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class LeaseTerminateCommand:
    """Terminate one SIGNED Lease through an explicit authorized business event."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_version: int
    actual_termination_date: date
    # None (every route): the database's own time at the command (Q-2026-10-14-112).
    occurred_at: datetime | None
    governing_event_reference: str
    reason: str
    authorization_reference: str
    context: TerminationContext | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        if self.occurred_at is not None and (
            self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("occurred_at must include a timezone")
        _require_nonblank(self.governing_event_reference, "governing_event_reference")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")
        if self.context is not None:
            if not isinstance(self.context, TerminationContext):
                raise ValueError("Termination context must be explicit approved evidence")
            if type(self.expected_version) is not int or self.expected_version > 2_147_483_647:
                raise ValueError("Expected Lease version must be a positive integer")
            self.context.validate_command(
                self.actual_termination_date, self.governing_event_reference
            )


LeaseCommand: TypeAlias = (
    LeaseDraftCommand
    | LeaseUpdateDraftCommand
    | LeaseAddSignerCommand
    | LeaseRecordSignatureCommand
    | LeaseRemoveSignerCommand
    | LeaseSignCommand
    | LeaseCancelCommand
    | LeaseTerminateCommand
)


def lease_request_digest(action: str, command: LeaseCommand) -> str:
    """Bind one idempotent Lease command to every normalized input."""
    if not action.startswith("lease."):
        raise ValueError("Lease action is invalid")
    payload = asdict(command)
    if isinstance(command, LeaseTerminateCommand) and command.context is None:
        # Preserve the exact legacy request identity for historical retries.
        payload.pop("context")
    if isinstance(command, LeaseSignCommand) and command.reservation_id is None:
        # A walk-in signing keeps the request identity of earlier signings.
        payload.pop("reservation_id")
    serialized = json.dumps(
        {"action": action, "command": _json_value(payload)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class LeaseSnapshot:
    """Bounded result for every successful Lease command."""

    lease_id: UUID
    property_id: UUID
    unit_id: UUID
    primary_tenant_id: UUID
    status: LeaseStatus
    start_date: date | None
    end_date: date | None
    monthly_rent_usd_cents: int | None
    predecessor_lease_id: UUID | None
    signed_at: str | None
    terminated_at: str | None
    actual_termination_date: date | None
    version: int
    signer_count: int
    signed_signer_count: int
    occupant_count: int


def _optional_date(value: object) -> date | None:
    return None if value is None else date.fromisoformat(str(value))


def _snapshot(row: tuple[object, ...]) -> LeaseSnapshot:
    payload = cast(dict[str, object], row[0])
    return LeaseSnapshot(
        lease_id=UUID(str(payload["lease_id"])),
        property_id=UUID(str(payload["property_id"])),
        unit_id=UUID(str(payload["unit_id"])),
        primary_tenant_id=UUID(str(payload["primary_tenant_id"])),
        status=LeaseStatus(str(payload["status"])),
        start_date=_optional_date(payload.get("start_date")),
        end_date=_optional_date(payload.get("end_date")),
        monthly_rent_usd_cents=(
            None
            if payload.get("monthly_rent_usd_cents") is None
            else int(str(payload["monthly_rent_usd_cents"]))
        ),
        predecessor_lease_id=(
            None
            if payload.get("predecessor_lease_id") is None
            else UUID(str(payload["predecessor_lease_id"]))
        ),
        signed_at=None if payload.get("signed_at") is None else str(payload["signed_at"]),
        terminated_at=(
            None if payload.get("terminated_at") is None else str(payload["terminated_at"])
        ),
        actual_termination_date=_optional_date(payload.get("actual_termination_date")),
        version=int(str(payload["version"])),
        signer_count=int(str(payload["signer_count"])),
        signed_signer_count=int(str(payload["signed_signer_count"])),
        occupant_count=int(str(payload["occupant_count"])),
    )


@dataclass(frozen=True, slots=True)
class PostgresLeaseService:
    """Execute exact Property-scoped Lease commands with stable retry semantics."""

    database_url: str
    property_id: UUID
    actor_id: UUID

    def __post_init__(self) -> None:
        _require_identity(self.property_id, "property_id")
        _require_identity(self.actor_id, "actor_id")

    def _require_authorized_actor(
        self,
        actor: AuthenticatedActor,
        capability: str,
        authorization_reference: str,
    ) -> None:
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise LeaseAuthorizationError("Lease actor is invalid") from exc
        if authenticated_actor_id != self.actor_id:
            raise LeaseAuthorizationError("Lease actor does not match the command")
        if authorization_reference != capability:
            raise LeaseAuthorizationError("Lease authorization evidence is not authoritative")
        if not is_authorized(
            actor,
            AuthorizationRequirement(capability=capability, property_id=str(self.property_id)),
        ):
            raise LeaseAuthorizationError("Lease capability is not authorized")

    def _execute(self, query: str, parameters: tuple[object, ...]) -> LeaseSnapshot:
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P5406":
                raise LeaseAuthorizationError("Lease actor is not active") from exc
            if exc.sqlstate in {"P0002", "P5401"}:
                raise LeaseNotFoundError("Lease resource was not found") from exc
            if exc.sqlstate == "40001":
                raise LeaseVersionConflictError("Lease version precondition was not met") from exc
            if exc.sqlstate in {"23505", "23P01"}:
                raise LeaseCommandConflictError("Lease command conflicted") from exc
            # Migration 76: draft, update and signing refuse an End Date that is not a month end.
            if exc.sqlstate == "22023" and exc.diag.message_primary == END_DATE_NOT_MONTH_END:
                raise LeaseEndDateNotMonthEndError(END_DATE_NOT_MONTH_END) from exc
            # Migration 251 (DL-110): a new draft holds every Service its Unit requires.
            if exc.sqlstate == "23514" and exc.diag.message_primary == REQUIRED_SERVICE_MISSING:
                raise LeaseRequiredServiceMissingError(REQUIRED_SERVICE_MISSING) from exc
            if exc.sqlstate in {"22023", "23514", "55000"}:
                raise LeaseCommandInvalidError("Lease command is invalid") from exc
            raise LeaseServiceUnavailableError("Lease persistence is unavailable") from exc
        if row is None:
            raise LeaseServiceUnavailableError("Lease command returned no result")
        return _snapshot(row)

    def draft(self, command: LeaseDraftCommand, *, actor: AuthenticatedActor) -> LeaseSnapshot:
        self._require_authorized_actor(
            actor, LEASE_DRAFT_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.draft", command)
        return self._execute(
            "SELECT app.create_lease_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                digest,
                command.event_id,
                command.lease_id,
                command.unit_id,
                command.primary_tenant_id,
                command.primary_signer_id,
                command.start_date,
                command.end_date,
                command.monthly_rent_usd_cents,
                command.predecessor_lease_id,
                command.reason,
                self.actor_id,
            ),
        )

    def draft_with_terms(
        self, command: LeaseDraftCommand, *, actor: AuthenticatedActor
    ) -> LeaseSnapshot:
        """Atomically create a draft and its approved party/term source evidence."""
        self._require_authorized_actor(
            actor, LEASE_DRAFT_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.draft", command)
        additional_signers = json.dumps(
            _json_value([asdict(value) for value in command.additional_signers])
        )
        planned_occupants = json.dumps(_json_value(command.planned_occupant_customer_ids))
        service_terms = json.dumps(_json_value([asdict(value) for value in command.service_terms]))
        pet_term = (
            None if command.pet_term is None else json.dumps(_json_value(asdict(command.pet_term)))
        )
        return self._execute(
            "SELECT app.create_lease_draft_with_terms("
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,"
            "%s::jsonb,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                digest,
                command.event_id,
                command.lease_id,
                command.unit_id,
                command.primary_tenant_id,
                command.primary_signer_id,
                command.start_date,
                command.end_date,
                command.monthly_rent_usd_cents,
                command.predecessor_lease_id,
                additional_signers,
                planned_occupants,
                service_terms,
                pet_term,
                command.security_deposit_id,
                command.reason,
                self.actor_id,
            ),
        )

    def add_signer(
        self, command: LeaseAddSignerCommand, *, actor: AuthenticatedActor
    ) -> LeaseSnapshot:
        self._require_authorized_actor(
            actor, LEASE_SIGNER_MANAGE_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.signer.add", command)
        return self._execute(
            "SELECT app.add_lease_signer(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                digest,
                command.event_id,
                command.lease_id,
                command.signer_id,
                command.customer_id,
                command.expected_version,
                command.reason,
                command.authorization_reference,
                self.actor_id,
            ),
        )

    def update_draft(
        self, command: LeaseUpdateDraftCommand, *, actor: AuthenticatedActor
    ) -> LeaseSnapshot:
        self._require_authorized_actor(
            actor, LEASE_DRAFT_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.draft.update", command)
        return self._execute(
            "SELECT app.update_lease_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                digest,
                command.event_id,
                command.lease_id,
                command.expected_version,
                command.start_date,
                command.end_date,
                command.monthly_rent_usd_cents,
                command.reason,
                command.authorization_reference,
                self.actor_id,
            ),
        )

    def record_signature(
        self, command: LeaseRecordSignatureCommand, *, actor: AuthenticatedActor
    ) -> LeaseSnapshot:
        self._require_authorized_actor(
            actor, LEASE_SIGN_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.signer.sign", command)
        # The function checks the time against statement_timestamp(), the same value here.
        return self._execute(
            "SELECT app.record_lease_signature(%s,%s,%s,%s,%s,%s,%s,"
            "COALESCE(%s::timestamptz,statement_timestamp()),%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                digest,
                command.event_id,
                command.lease_id,
                command.signer_id,
                command.expected_version,
                command.signed_at,
                command.reason,
                self.actor_id,
            ),
        )

    def remove_signer(
        self, command: LeaseRemoveSignerCommand, *, actor: AuthenticatedActor
    ) -> LeaseSnapshot:
        self._require_authorized_actor(
            actor, LEASE_SIGNER_MANAGE_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.signer.remove", command)
        return self._execute(
            "SELECT app.remove_lease_signer(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                digest,
                command.event_id,
                command.lease_id,
                command.signer_id,
                command.expected_version,
                command.reason,
                command.authorization_reference,
                self.actor_id,
            ),
        )

    def sign(self, command: LeaseSignCommand, *, actor: AuthenticatedActor) -> LeaseSnapshot:
        self._require_authorized_actor(
            actor, LEASE_SIGN_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.sign", command)
        # DL-064/DL-066: signing completes the Reservation (if any) and occupies the Unit.
        # The signing time defaults to statement_timestamp(), the value app.sign_lease checks.
        return self._execute(
            "SELECT app.sign_lease_with_reservation(%s,%s,%s,%s,%s,%s,"
            "COALESCE(%s::timestamptz,statement_timestamp()),%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                digest,
                command.event_id,
                command.lease_id,
                command.expected_version,
                command.signed_at,
                command.reason,
                self.actor_id,
                command.reservation_id,
            ),
        )

    def cancel(self, command: LeaseCancelCommand, *, actor: AuthenticatedActor) -> LeaseSnapshot:
        self._require_authorized_actor(
            actor, LEASE_DRAFT_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.cancel", command)
        return self._execute(
            "SELECT app.cancel_draft_lease(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                digest,
                command.event_id,
                command.lease_id,
                command.expected_version,
                command.reason,
                self.actor_id,
            ),
        )

    def terminate(
        self, command: LeaseTerminateCommand, *, actor: AuthenticatedActor
    ) -> LeaseSnapshot:
        self._require_authorized_actor(
            actor, LEASE_TERMINATE_CAPABILITY, command.authorization_reference
        )
        digest = lease_request_digest("lease.terminate", command)
        parameters: tuple[object, ...] = (
            self.property_id,
            command.idempotency_key,
            digest,
            command.event_id,
            command.lease_id,
            command.expected_version,
            command.actual_termination_date,
            command.occurred_at,
            command.governing_event_reference,
            command.reason,
            self.actor_id,
        )
        # The termination time defaults to statement_timestamp(), the value app.terminate_lease
        # checks.
        if command.context is not None:
            return self._execute(
                "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,"
                "COALESCE(%s::timestamptz,statement_timestamp()),%s,%s,%s,%s::jsonb)",
                (*parameters, json.dumps(command.context.intent(), ensure_ascii=False)),
            )
        # The shared database boundary permits genuine legacy replay, but
        # rejects fresh termination without the newly required context.
        return self._execute(
            "SELECT app.terminate_lease(%s,%s,%s,%s,%s,%s,%s,"
            "COALESCE(%s::timestamptz,statement_timestamp()),%s,%s,%s)",
            parameters,
        )
