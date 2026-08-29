"""Trusted Utility consumption and confirmed broken-Meter calculation services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import (
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from enum import StrEnum
from typing import Final, cast
from uuid import UUID

import psycopg
from psycopg import IsolationLevel
from psycopg.types.json import set_json_loads

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

UTILITY_CALCULATE_CAPABILITY: Final = "utility.calculate"
UTILITY_ESTIMATE_CAPABILITY: Final = "utility.estimate"
UTILITY_CONNECT_TIMEOUT_SECONDS: Final = 3
UTILITY_LOCK_TIMEOUT_MS: Final = 3_000
UTILITY_QUERY_TIMEOUT_MS: Final = 5_000
NIL_UUID: Final = UUID(int=0)


def _financial_context(precision: int) -> Context:
    """Return a deterministic Decimal context independent of process settings."""

    return Context(
        prec=precision,
        rounding=ROUND_HALF_UP,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


class UtilityCalculationKind(StrEnum):
    ACTUAL = "ACTUAL"
    BROKEN_METER_ESTIMATE = "BROKEN_METER_ESTIMATE"


class UtilityBasisKind(StrEnum):
    LATEST_THREE_HISTORICAL = "LATEST_THREE_HISTORICAL"
    ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO = "ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO"
    FIRST_COMPLETE_FUTURE_ZERO_HISTORY = "FIRST_COMPLETE_FUTURE_ZERO_HISTORY"


class UtilityCalculationStatus(StrEnum):
    READY = "READY"
    PENDING_FUTURE_ACTUAL_BASIS = "PENDING_FUTURE_ACTUAL_BASIS"


class UtilityPreviewSourceKind(StrEnum):
    CONSUMPTION_PERIOD = "CONSUMPTION_PERIOD"
    ESTIMATION_CASE = "ESTIMATION_CASE"


class UtilityNotFoundError(LookupError):
    pass


class UtilityConflictError(RuntimeError):
    pass


class UtilityIdempotencyKeyReused(UtilityConflictError):
    pass


class UtilityInvalidError(ValueError):
    pass


class UtilityAuthorizationError(PermissionError):
    pass


class UtilityServiceUnavailableError(RuntimeError):
    pass


def _identity(value: UUID, field: str) -> None:
    if value == NIL_UUID:
        raise ValueError(f"{field} must not be the nil UUID")


def _normalized(value: str, field: str, *, maximum: int = 500) -> None:
    if not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be normalized and nonblank")
    if len(value) > maximum:
        raise ValueError(f"{field} must not exceed {maximum} characters")


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def weighted_daily_average(total_consumption: Decimal, represented_days: int) -> Decimal:
    """Return the exact weighted average without rounding separate periods."""

    if total_consumption < 0:
        raise ValueError("total_consumption must be nonnegative")
    if represented_days <= 0:
        raise ValueError("represented_days must be positive")
    with localcontext(_financial_context(50)):
        return total_consumption / Decimal(represented_days)


def estimated_consumption(
    total_basis_consumption: Decimal,
    total_basis_days: int,
    unmeasured_days: int,
) -> Decimal:
    """Calculate one weighted estimate and round only the final quantity to six places."""

    if unmeasured_days <= 0:
        raise ValueError("unmeasured_days must be positive")
    with localcontext(_financial_context(50)):
        estimate = weighted_daily_average(total_basis_consumption, total_basis_days) * Decimal(
            unmeasured_days
        )
        return estimate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def utility_charge_usd_cents(quantity: Decimal, rate_usd_per_unit: Decimal) -> int:
    """Apply one generation-date rate to the whole quantity and half-up round cents."""

    if quantity < 0:
        raise ValueError("quantity must be nonnegative")
    if rate_usd_per_unit <= 0:
        raise ValueError("rate_usd_per_unit must be positive")
    with localcontext(_financial_context(80)):
        amount_cents = (quantity * rate_usd_per_unit * Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    return int(amount_cents)


def _digest(action: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"action": action, **payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class FinalizeActualConsumptionCommand:
    idempotency_key: UUID
    consumption_period_id: UUID
    unit_id: UUID
    utility_type: str
    start_reading_id: UUID
    end_reading_id: UUID
    finalized_at: datetime
    authorization_reference: str = UTILITY_CALCULATE_CAPABILITY

    def __post_init__(self) -> None:
        for field in (
            "idempotency_key",
            "consumption_period_id",
            "unit_id",
            "start_reading_id",
            "end_reading_id",
        ):
            _identity(getattr(self, field), field)
        if self.start_reading_id == self.end_reading_id:
            raise ValueError("actual consumption requires distinct Readings")
        if self.utility_type not in {"ELECTRICITY", "WATER"}:
            raise ValueError("utility_type is not supported")
        _aware(self.finalized_at, "finalized_at")
        _normalized(self.authorization_reference, "authorization_reference", maximum=200)


def actual_consumption_request_digest(command: FinalizeActualConsumptionCommand) -> str:
    return _digest(
        "FINALIZE_ACTUAL",
        {
            "authorization_reference": command.authorization_reference,
            "consumption_period_id": str(command.consumption_period_id),
            "end_reading_id": str(command.end_reading_id),
            "finalized_at": command.finalized_at.astimezone(UTC).isoformat(),
            "idempotency_key": str(command.idempotency_key),
            "start_reading_id": str(command.start_reading_id),
            "unit_id": str(command.unit_id),
            "utility_type": command.utility_type,
        },
    )


@dataclass(frozen=True, slots=True)
class OpenBrokenMeterCaseCommand:
    idempotency_key: UUID
    estimation_case_id: UUID
    failed_meter_id: UUID
    replacement_meter_id: UUID
    opened_reason: str
    opened_at: datetime
    authorization_reference: str = UTILITY_ESTIMATE_CAPABILITY

    def __post_init__(self) -> None:
        for field in (
            "idempotency_key",
            "estimation_case_id",
            "failed_meter_id",
            "replacement_meter_id",
        ):
            _identity(getattr(self, field), field)
        if self.failed_meter_id == self.replacement_meter_id:
            raise ValueError("broken-Meter case requires a distinct replacement Meter")
        _normalized(self.opened_reason, "opened_reason")
        _aware(self.opened_at, "opened_at")
        _normalized(self.authorization_reference, "authorization_reference", maximum=200)


def open_broken_meter_request_digest(command: OpenBrokenMeterCaseCommand) -> str:
    return _digest(
        "OPEN_BROKEN_METER_CASE",
        {
            "authorization_reference": command.authorization_reference,
            "estimation_case_id": str(command.estimation_case_id),
            "failed_meter_id": str(command.failed_meter_id),
            "idempotency_key": str(command.idempotency_key),
            "opened_at": command.opened_at.astimezone(UTC).isoformat(),
            "opened_reason": command.opened_reason,
            "replacement_meter_id": str(command.replacement_meter_id),
        },
    )


@dataclass(frozen=True, slots=True)
class FinalizeBrokenMeterEstimateCommand:
    idempotency_key: UUID
    estimation_case_id: UUID
    estimate_id: UUID
    consumption_period_id: UUID
    authorization_reason: str
    authorized_at: datetime
    authorization_reference: str = UTILITY_ESTIMATE_CAPABILITY

    def __post_init__(self) -> None:
        for field in (
            "idempotency_key",
            "estimation_case_id",
            "estimate_id",
            "consumption_period_id",
        ):
            _identity(getattr(self, field), field)
        _normalized(self.authorization_reason, "authorization_reason")
        _aware(self.authorized_at, "authorized_at")
        _normalized(self.authorization_reference, "authorization_reference", maximum=200)


def broken_meter_estimate_request_digest(command: FinalizeBrokenMeterEstimateCommand) -> str:
    return _digest(
        "FINALIZE_BROKEN_METER_ESTIMATE",
        {
            "authorization_reason": command.authorization_reason,
            "authorization_reference": command.authorization_reference,
            "authorized_at": command.authorized_at.astimezone(UTC).isoformat(),
            "consumption_period_id": str(command.consumption_period_id),
            "estimate_id": str(command.estimate_id),
            "estimation_case_id": str(command.estimation_case_id),
            "idempotency_key": str(command.idempotency_key),
        },
    )


@dataclass(frozen=True, slots=True)
class UtilitySourceEvidence:
    consumption_period_id: UUID
    meter_id: UUID
    start_reading_id: UUID
    end_reading_id: UUID


@dataclass(frozen=True, slots=True)
class UtilityCalculationSnapshot:
    status: UtilityCalculationStatus
    property_id: UUID
    unit_id: UUID
    utility_type: str
    consumption_period_id: UUID | None
    calculation_kind: UtilityCalculationKind | None
    period_start: date | None
    period_end: date | None
    consumption_quantity: Decimal | None
    represented_days: int | None
    meter_id: UUID | None
    start_reading_id: UUID | None
    end_reading_id: UUID | None
    failed_meter_id: UUID | None
    replacement_meter_id: UUID | None
    basis_kind: UtilityBasisKind | None
    basis_period_ids: tuple[UUID, ...]
    basis_sources: tuple[UtilitySourceEvidence, ...]
    total_basis_consumption: Decimal | None
    total_basis_days: int | None
    weighted_daily_average: Decimal | None
    generation_date: date | None
    rate_id: UUID | None
    rate_effective_date: date | None
    rate_usd_per_unit: Decimal | None
    amount_usd_cents: int | None


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _optional_date(value: object) -> date | None:
    return None if value is None else date.fromisoformat(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _json_loads_decimal(value: str | bytes) -> object:
    return json.loads(value, parse_float=Decimal)


def _snapshot(row: tuple[object, ...]) -> UtilityCalculationSnapshot:
    value = cast(dict[str, object], row[0])
    basis_ids = cast(list[object] | None, value.get("basis_period_ids")) or []
    basis_sources = cast(list[dict[str, object]] | None, value.get("basis_sources")) or []
    kind = value.get("calculation_kind")
    basis = value.get("basis_kind")
    return UtilityCalculationSnapshot(
        status=UtilityCalculationStatus(str(value["status"])),
        property_id=UUID(str(value["property_id"])),
        unit_id=UUID(str(value["unit_id"])),
        utility_type=str(value["utility_type"]),
        consumption_period_id=_optional_uuid(value.get("consumption_period_id")),
        calculation_kind=None if kind is None else UtilityCalculationKind(str(kind)),
        period_start=_optional_date(value.get("period_start")),
        period_end=_optional_date(value.get("period_end")),
        consumption_quantity=_optional_decimal(value.get("consumption_quantity")),
        represented_days=(
            None if value.get("represented_days") is None else int(str(value["represented_days"]))
        ),
        meter_id=_optional_uuid(value.get("meter_id")),
        start_reading_id=_optional_uuid(value.get("start_reading_id")),
        end_reading_id=_optional_uuid(value.get("end_reading_id")),
        failed_meter_id=_optional_uuid(value.get("failed_meter_id")),
        replacement_meter_id=_optional_uuid(value.get("replacement_meter_id")),
        basis_kind=None if basis is None else UtilityBasisKind(str(basis)),
        basis_period_ids=tuple(UUID(str(item)) for item in basis_ids),
        basis_sources=tuple(
            UtilitySourceEvidence(
                consumption_period_id=UUID(str(source["consumption_period_id"])),
                meter_id=UUID(str(source["meter_id"])),
                start_reading_id=UUID(str(source["start_reading_id"])),
                end_reading_id=UUID(str(source["end_reading_id"])),
            )
            for source in basis_sources
        ),
        total_basis_consumption=_optional_decimal(value.get("total_basis_consumption")),
        total_basis_days=(
            None if value.get("total_basis_days") is None else int(str(value["total_basis_days"]))
        ),
        weighted_daily_average=_optional_decimal(value.get("weighted_daily_average")),
        generation_date=_optional_date(value.get("generation_date")),
        rate_id=_optional_uuid(value.get("rate_id")),
        rate_effective_date=_optional_date(value.get("rate_effective_date")),
        rate_usd_per_unit=_optional_decimal(value.get("rate_usd_per_unit")),
        amount_usd_cents=(
            None if value.get("amount_usd_cents") is None else int(str(value["amount_usd_cents"]))
        ),
    )


@dataclass(frozen=True, slots=True)
class PostgresUtilityService:
    financial_database_url: str
    property_id: UUID
    actor_id: UUID

    def __post_init__(self) -> None:
        _identity(self.property_id, "property_id")
        _identity(self.actor_id, "actor_id")

    def _require(self, actor: AuthenticatedActor, capability: str) -> None:
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise UtilityAuthorizationError("Utility actor is invalid") from exc
        if authenticated_actor_id != self.actor_id or not is_authorized(
            actor,
            AuthorizationRequirement(capability=capability, property_id=str(self.property_id)),
        ):
            raise UtilityAuthorizationError("Utility capability is not authorized")

    def _execute(self, query: str, parameters: tuple[object, ...]) -> UtilityCalculationSnapshot:
        try:
            with psycopg.connect(
                self.financial_database_url,
                connect_timeout=UTILITY_CONNECT_TIMEOUT_SECONDS,
            ) as connection:
                set_json_loads(_json_loads_decimal, connection)
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                connection.execute(
                    "SELECT pg_catalog.set_config('lock_timeout',%s,true)",
                    (str(UTILITY_LOCK_TIMEOUT_MS),),
                )
                connection.execute(
                    "SELECT pg_catalog.set_config('statement_timeout',%s,true)",
                    (str(UTILITY_QUERY_TIMEOUT_MS),),
                )
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise UtilityNotFoundError("Utility source was not found") from exc
            if exc.sqlstate == "55000" and "active" in str(exc).lower():
                raise UtilityAuthorizationError("Utility actor is no longer active") from exc
            if exc.sqlstate == "23505" and "idempotency" in str(exc).lower():
                raise UtilityIdempotencyKeyReused("Utility idempotency key was reused") from exc
            if exc.sqlstate in {"23505", "23P01", "40001", "55P03"}:
                raise UtilityConflictError("Utility command conflicted") from exc
            if exc.sqlstate in {"22023", "23514", "25001", "55000"}:
                raise UtilityInvalidError("Utility command is invalid") from exc
            raise UtilityServiceUnavailableError("Utility persistence is unavailable") from exc
        if row is None:
            raise UtilityServiceUnavailableError("Utility command returned no result")
        return _snapshot(row)

    def finalize_actual(
        self,
        command: FinalizeActualConsumptionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> UtilityCalculationSnapshot:
        self._require(actor, UTILITY_CALCULATE_CAPABILITY)
        if command.authorization_reference != UTILITY_CALCULATE_CAPABILITY:
            raise UtilityAuthorizationError("Actual-consumption authorization is invalid")
        return self._execute(
            "SELECT app.finalize_actual_utility_consumption(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                actual_consumption_request_digest(command),
                command.consumption_period_id,
                command.unit_id,
                command.utility_type,
                command.start_reading_id,
                command.end_reading_id,
                command.finalized_at.astimezone(UTC),
                self.actor_id,
            ),
        )

    def open_broken_meter_case(
        self,
        command: OpenBrokenMeterCaseCommand,
        *,
        actor: AuthenticatedActor,
    ) -> UtilityCalculationSnapshot:
        self._require(actor, UTILITY_ESTIMATE_CAPABILITY)
        if command.authorization_reference != UTILITY_ESTIMATE_CAPABILITY:
            raise UtilityAuthorizationError("Broken-Meter authorization is invalid")
        return self._execute(
            "SELECT app.open_broken_meter_estimation_case(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                open_broken_meter_request_digest(command),
                command.estimation_case_id,
                command.failed_meter_id,
                command.replacement_meter_id,
                command.opened_reason,
                command.opened_at.astimezone(UTC),
                self.actor_id,
                command.authorization_reference,
            ),
        )

    def finalize_broken_meter_estimate(
        self,
        command: FinalizeBrokenMeterEstimateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> UtilityCalculationSnapshot:
        self._require(actor, UTILITY_ESTIMATE_CAPABILITY)
        if command.authorization_reference != UTILITY_ESTIMATE_CAPABILITY:
            raise UtilityAuthorizationError("Broken-Meter authorization is invalid")
        return self._execute(
            "SELECT app.finalize_broken_meter_estimate(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                broken_meter_estimate_request_digest(command),
                command.estimation_case_id,
                command.estimate_id,
                command.consumption_period_id,
                command.authorization_reason,
                command.authorized_at.astimezone(UTC),
                self.actor_id,
                command.authorization_reference,
            ),
        )

    def preview(
        self,
        source_id: UUID,
        generation_at: datetime,
        *,
        source_kind: UtilityPreviewSourceKind,
        actor: AuthenticatedActor,
    ) -> UtilityCalculationSnapshot:
        _identity(source_id, "source_id")
        _aware(generation_at, "generation_at")
        self._require(actor, UTILITY_CALCULATE_CAPABILITY)
        return self._execute(
            "SELECT app.preview_utility_calculation(%s,%s,%s,%s,%s)",
            (
                self.property_id,
                source_kind.value,
                source_id,
                generation_at.astimezone(UTC),
                self.actor_id,
            ),
        )
